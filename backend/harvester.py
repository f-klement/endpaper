"""The OAI-PMH harvester: another repository's records, read in as a bulk import.

The client half of the protocol. `harvest.py` and `oai.py` are the provider's,
and serve this Library's records; this module reads somebody else's.

**An import, never a lookup source.** OAI-PMH has no query: selective
harvesting is by set and datestamp only, so there is no way to ask a repository
about one book, and this has no place in `sources.py`'s chain (ticket 177).

## The four verbs, and what bounds a run

`Repository` speaks `Identify`, `ListMetadataFormats`, `ListRecords` and
`GetRecord`. Every request goes through `fetch.get` on a `fetch.pinned_client`
under `fetch.HOUSEHOLD_ADDRESSES` (owner, 2026-11-20): the name is resolved and
classified per request and connected to as classified, so no DNS answer is
trusted from the moment an admin typed the address.

| Bound | Value | Where |
|---|---|---|
| one response | `fetch.MAX_RESPONSE_BYTES`, counted raw | `fetch.get` |
| one request | `fetch.TIMEOUT_SECONDS`, or what is left of the run | `Repository._fetched` |
| a run | `RUN_DEADLINE_SECONDS` | `repository` |
| records per run | `MAX_RECORDS`, deleted headers included | `_Walk` |
| pages per run | `MAX_PAGES` | `Repository.list_records` |
| a resumption token seen before in the run | refused | `_next_token` |
| a resumption token's width | `MAX_TOKEN_LENGTH`, refused past it | `_next_token` |
| runs at once | one, a second refused | `one_run` |

**A cap, a deadline (the run's or a request's) or a busy repository
truncates the run**, and the pages already read are kept and reported
`truncated`: a slow repository of a few thousand records is the migration case
this exists for, and a run that threw its pages away at the deadline could
never harvest it. Before the first
`ListRecords` page there is nothing to keep, so the same cut is refused.

**A repeated token is refused rather than ending the walk quietly**: a
repository handing back a token it already gave is broken, and an import of the
pages before it would look complete when it is not.

**The parsing runs in a worker thread**, a page's response and its records
both: a page is up to `fetch.MAX_RESPONSE_BYTES` of XML read through Python
callbacks, and on the event loop every other request would wait behind each of
up to `MAX_PAGES` of them.

## What is read

**MARCXML only**, chosen by namespace rather than by prefix, since a repository
names its own formats (`oai.py` serves `marc21`; others say `marcxml`). Each
record goes through `marc.read`, the upload reader, so a harvested record is
read exactly as a file's. The `oai_dc` fallback is not built: a repository
offering no MARC21 format is refused with that said.

A deleted record's header is counted and nothing is deleted here: a partner
withdrawing a record is not this Library withdrawing its Book.
"""

import functools
import logging
import threading
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from itertools import islice
from typing import Final
from urllib.parse import SplitResult, urlsplit
from xml.etree import ElementTree

import anyio.to_thread
import httpx
from sqlalchemy.orm import Session

import credentials
import fetch
import marc
import marc_fields
import metadata
import settings_store
import xml_parse
from deadline import in_, left
from models import HARVEST_METADATA_PREFIX_MAX, HARVESTED_IDENTIFIER_MAX

logger = logging.getLogger("endpaper.harvester")

#: The OAI-PMH 2.0 namespace every response element is in.
OAI: Final = "http://www.openarchives.org/OAI/2.0/"
_OAI: Final = f"{{{OAI}}}"

#: Records one run reads, deleted headers counted with the rest.
#:
#: `opds.MAX_ENTRIES`'s number and its reason: the applying is one transaction,
#: and an import is bounded by a count rather than a clock because a half
#: applied import is worse than a slow one. Half of `marc.MAX_RECORDS`, since a
#: harvest is fetched while the request waits and a file is not.
MAX_RECORDS: Final = 10_000

#: How much of the name a repository gives itself the preview shows. Cut
#: rather than refused: it is shown to the admin alone, and unbounded it could
#: fill the whole response cap.
NAME_MAX: Final = 200

#: Pages one run fetches. A repository serving one record a page would
#: otherwise turn `MAX_RECORDS` into ten thousand requests.
MAX_PAGES: Final = 200

#: The wall clock a whole run may spend fetching.
#:
#: `opds.SYNC_DEADLINE_SECONDS`'s bound for its reason: the per request bound
#: times `MAX_PAGES` is not a bound anybody would accept written down as one.
#: A run that reaches it stops and reports itself truncated, with what it read.
RUN_DEADLINE_SECONDS: Final = 120

#: The widest resumption token a run keeps, in characters.
#:
#: **Every token is kept for the run**, to refuse one handed back twice, and
#: sent back as a query string. Unbounded, a hostile repository answering
#: `MAX_PAGES` pages, each a fresh token as wide as `fetch.MAX_RESPONSE_BYTES`,
#: would have this server hold hundreds of megabytes for the run. A real token
#: is an offset or a cursor, a few dozen characters.
MAX_TOKEN_LENGTH: Final = 2_000

#: This door's half of its allocation bound: a call of `read_response` peaks, by
#: `tracemalloc`, under this times the bytes of the body plus
#: `xml_parse.ALLOCATION_FLOOR`, which says what the bound is and what holds it.
#:
#: **`opds.ALLOCATION_FACTOR`, because the cost is the same parse**: text fed
#: through `xml_parse.DepthBoundedTree`, the bounds in `xml_parse` admitting the
#: same costliest shape, and nothing read off the tree past a root and an error
#: code. `tests/test_harvester.py` reads that shape at the density bound.
ALLOCATION_FACTOR: Final = 30

#: The OAI-PMH error codes, the only ones named back to the admin. A code
#: outside the set is the repository's own text and is not echoed.
_ERROR_CODES: Final = frozenset(
    {
        "badArgument",
        "badResumptionToken",
        "badVerb",
        "cannotDisseminateFormat",
        "idDoesNotExist",
        "noMetadataFormats",
        "noRecordsMatch",
        "noSetHierarchy",
    }
)


#: The one error code `ListRecords` reads as an answer: nothing in that range.
_EMPTY_IS_AN_ANSWER: Final = frozenset({"noRecordsMatch"})


class HarvestError(Exception):
    """A run this module refuses to finish. The message is for the admin, and
    never carries the repository's address, which goes to the log only."""


class _RunCut(HarvestError):
    """A request a deadline or a busy repository cut short.

    **A `HarvestError`, so a cut nothing catches is still refused by name**:
    `Repository.list_records` catches it once a page is read and truncates the
    run there; anywhere else nothing has been read and it is the refusal.
    """


class AlreadyRunning(Exception):
    """A harvest was asked for while another runs: `one_run`."""


#: Held for the whole of a run, preview or apply. A process lock is a pod lock:
#: the image runs one worker, which `tests/routers/test_concurrency_bounds.py`
#: holds.
_ONE_RUN: Final = threading.Lock()


@contextmanager
def one_run() -> Iterator[None]:
    """The body runs as the only harvest, or `AlreadyRunning` before it starts.

    **Refused rather than queued**, as `vocabulary_copy.start` refuses a second
    download: a run holds its request open for up to `RUN_DEADLINE_SECONDS` and
    then the apply, so behind a proxy with a shorter timeout an admin sees an
    error while the run goes on, and retries. A second run then would import
    every record with no ISBN twice, since neither run sees the other's Books
    before its one commit.
    """
    if not _ONE_RUN.acquire(blocking=False):
        raise AlreadyRunning("A harvest is already running. Wait for it to finish, then run it again.")
    try:
        yield
    finally:
        _ONE_RUN.release()


@dataclass(frozen=True, slots=True)
class Identity:
    """What a repository's `Identify` says about itself."""

    name: str | None
    protocol_version: str | None


@dataclass(frozen=True, slots=True)
class Format:
    """One entry of `ListMetadataFormats`."""

    prefix: str
    namespace: str | None


@dataclass(frozen=True, slots=True)
class Harvested:
    """What one run read: the records as `marc.read` reads a file, and the counts."""

    prefix: str
    parsed: marc.ParsedMarc
    #: Record headers read, deleted ones included.
    seen: int
    #: Headers marked deleted, counted and acted on nowhere.
    deleted: int
    pages_read: int
    #: Whether a cap or the deadline stopped the run before the repository ran out.
    truncated: bool
    #: Each record's OAI identifier, at the same position as `parsed.records`,
    #: or None where the header names none that fits
    #: `models.HARVESTED_IDENTIFIER_MAX`. What a re-run matches first.
    identifiers: tuple[str | None, ...] = ()


@dataclass
class _Walk:
    """The records a run has taken so far, held to `max_records`."""

    max_records: int
    seen: int = 0
    deleted: int = 0
    unreadable: int = 0
    truncated: bool = False
    pages: list[marc.ParsedMarc] = field(default_factory=list)
    identifiers: list[str | None] = field(default_factory=list)

    def full(self) -> bool:
        return self.seen >= self.max_records

    def take(self, records: list[ElementTree.Element]) -> None:
        """One page's `<record>` elements, as far as the cap admits.

        **A MARC record holding another is unreadable, and none of it is kept**:
        `marc.read` reads every `<record>` beneath what it is handed, so the
        nested ones would each become a Book past `max_records`, and every
        record after them would carry its predecessor's identifier. So is a
        `<metadata>` holding two MARC records side by side, which would
        otherwise keep the first and drop the rest uncounted.
        """
        room = self.max_records - self.seen
        if len(records) > room:
            self.truncated = True
            records = records[:room]
        self.seen += len(records)
        kept: list[tuple[str | None, ElementTree.Element]] = []
        for record in records:
            header = record.find(f"{_OAI}header")
            if header is not None and header.get("status") == "deleted":
                self.deleted += 1
                continue
            node = _the_one_record(record)
            if node is None:
                self.unreadable += 1
            else:
                kept.append((_identifier(header), node))
        if kept:
            self._read(kept)

    def _read(self, kept: list[tuple[str | None, ElementTree.Element]]) -> None:
        """One page's MARC records, each kept beside its identifier.

        **Read as one page, and again one record at a time only when the page
        skipped one**: `marc.read` drops a record with no title without saying
        which, so the identifiers line up with the records only while it drops
        none. Measured on 1000 records, reading them one at a time cost up to 40
        per cent more, so the common page pays nothing for it.
        """
        page = _read_marc([node for _, node in kept])
        if not page.skipped:
            self.pages.append(page)
            self.identifiers.extend(key for key, _ in kept)
            return
        for key, node in kept:
            one = _read_marc([node])
            self.pages.append(one)
            self.identifiers.extend([key] * len(one.records))

    def harvested(self, prefix: str, pages_read: int) -> Harvested:
        records = tuple(record for page in self.pages for record in page.records)
        links = tuple(entry for page in self.pages for entry in page.links)
        skipped = self.unreadable + sum(page.skipped for page in self.pages)
        return Harvested(
            prefix=prefix,
            parsed=marc.ParsedMarc(records=records, skipped=skipped, links=links),
            seen=self.seen,
            deleted=self.deleted,
            pages_read=pages_read,
            truncated=self.truncated,
            identifiers=tuple(self.identifiers),
        )


def _the_one_record(record: ElementTree.Element) -> ElementTree.Element | None:
    """An OAI record's one MARC record, or None where its `<metadata>` holds
    none, two side by side, or one holding another."""
    nodes = record.findall(f"{_OAI}metadata/{marc_fields.RECORD_TAG}")
    if len(nodes) != 1 or _nests_a_record(nodes[0]):
        return None
    return nodes[0]


def _nests_a_record(node: ElementTree.Element) -> bool:
    """Whether a MARC record holds another beneath it, which `iter` reaches
    as `marc.read` does: the first node it yields is `node` itself."""
    return next(islice(node.iter(marc_fields.RECORD_TAG), 1, None), None) is not None


def _identifier(header: ElementTree.Element | None) -> str | None:
    """A record header's OAI identifier, or None where it names none that fits
    the column: such a record is matched as a file's record is."""
    found = (header.findtext(f"{_OAI}identifier") or "").strip() if header is not None else ""
    return found if 0 < len(found) <= HARVESTED_IDENTIFIER_MAX else None


def is_harvestable(url: str) -> bool:
    """Whether the harvester may be pointed at this repository address.

    **A household address is admitted, over http or https** (owner's decision
    on issue #177, 2026-11-20): migrating off another system on the same
    network is the case the feature exists for, and this server's own loopback
    is admitted with it, as at the OPDS door. So the form is the OPDS door's,
    `credentials.typed_address_host`, and this adds three clauses of its own: no
    query or fragment (a base URL takes the verbs as its query), an address
    `credentials.origin_of` can read, which is httpx's parser and the one the
    request is made with, and no address literal `credentials.household_admits`
    refuses, link local above all. A name is not resolved; that function says why.

    It is read by `routers/settings.py` on the write and by
    `configured_repository` on every run, and it lives here rather than in
    `settings_store` because that module parses stored JSON and so may not
    import `fetch`: `TestOneDoorParsesAResponseBody` in
    `tests/test_house_rules.py` holds every module that does to
    `fetch.Fetched.json`.
    """
    host = credentials.typed_address_host(url)
    if host is None or not credentials.origin_of(url):
        return False
    return not _carries_more_than_a_place(urlsplit(url)) and credentials.household_admits(host)


def _carries_more_than_a_place(parsed: SplitResult) -> bool:
    """A query or a fragment: a base URL takes the verbs as its query."""
    return bool(parsed.query or parsed.fragment)


def configured_repository(db: Session) -> str | None:
    """The repository an admin may harvest now, or None.

    `settings_store.harvest_repository`'s switches and stored address, with
    `is_harvestable` applied again rather than trusted from the write: a
    restore or a hand edit stores the rows without passing the settings route.
    The routes ask this and nothing else.
    """
    address = settings_store.harvest_repository(db)
    return address if address is not None and is_harvestable(address) else None


def _read_marc(nodes: list[ElementTree.Element]) -> marc.ParsedMarc:
    """These MARC records, through the upload reader.

    **Written out as one collection and read back**, rather than read off the
    page, so the records are exactly the ones the walk took: `marc.read` reads
    every `<record>` in what it is handed, and a page cut at the cap holds more.
    Serialising is not parsing, and what is parsed is this module's own output.

    **No local vocabulary copy is asked**, so a second indicator counts only on
    a Library of Congress record. It reaches headings alone, and a harvest
    writes none: `docs/decisions.md`, *Harvesting an OAI-PMH repository*.
    """
    collection = ElementTree.Element(f"{{{marc_fields.NAMESPACE}}}collection")
    collection.extend(nodes)
    try:
        return marc.read(ElementTree.tostring(collection, encoding="utf-8"))
    except marc.MarcError as error:
        raise HarvestError(
            f"The repository sent MARC records this library could not read: {error}"
        ) from error


def _parsed(body: str) -> ElementTree.Element:
    """A repository's response as a tree, refusing what unbounds its cost.

    `metadata._parsed`'s two halves: a doctype is refused because `xml.etree`
    expands internal entities, and the tree is built through `xml_parse`, which
    bounds the rest. `fetch.MAX_RESPONSE_BYTES` caps the body before this.
    """
    if metadata.DOCTYPE in body:
        raise HarvestError("The repository answered with a document type declaration, which is refused.")
    try:
        parser = ElementTree.XMLParser(target=xml_parse.DepthBoundedTree())  # noqa: S314  doctype refused above, bytes capped, depth bounded
        return xml_parse.fed(parser, body)
    except (ElementTree.ParseError, ValueError) as error:
        raise HarvestError("The repository did not answer with XML this library could read.") from error


def read_response(body: str, *, allow: frozenset[str] = frozenset()) -> ElementTree.Element:
    """One OAI-PMH response as its root element, or `HarvestError`.

    **This module's byte door**: every verb's answer passes here, and
    `TestAResponseIsReadOrRefusedByName` in `tests/test_harvester.py` drives it
    at the `fetch.Fetched` seam. An error code in `allow` is an answer.
    """
    root = _parsed(body)
    if root.tag != f"{_OAI}OAI-PMH":
        raise HarvestError("The repository did not answer with an OAI-PMH response.")
    code = _error_code(root)
    if code is not None and code not in allow:
        raise HarvestError(f"The repository refused the request: {code}.")
    return root


def _error_code(root: ElementTree.Element) -> str | None:
    """The first OAI-PMH error the response carries, named only when it is one
    of the protocol's own codes."""
    error = root.find(f"{_OAI}error")
    if error is None:
        return None
    code = error.get("code") or ""
    return code if code in _ERROR_CODES else "unknown"


def _text(root: ElementTree.Element, path: str) -> str | None:
    found = root.findtext(path)
    return found.strip() or None if found is not None else None


def _next_token(root: ElementTree.Element, seen: set[str]) -> str | None:
    """The page's resumption token, kept in `seen`, or None on the last page.

    Refuses a token wider than `MAX_TOKEN_LENGTH`, and one already in `seen`.
    """
    token = _text(root, f"{_OAI}ListRecords/{_OAI}resumptionToken")
    if token is None:
        return None
    if len(token) > MAX_TOKEN_LENGTH:
        raise HarvestError("The repository handed back a resumption token wider than this library keeps.")
    if token in seen:
        raise HarvestError("The repository handed back a resumption token it had already given.")
    seen.add(token)
    return token


class Repository:
    """One repository, for the length of one run. Made by `repository`."""

    __slots__ = ("_base_url", "_client", "_ends")

    def __init__(self, client: httpx.AsyncClient, base_url: str, ends: float) -> None:
        self._client = client
        self._base_url = base_url
        self._ends = ends

    async def identify(self) -> Identity:
        root = await self._ask({"verb": "Identify"})
        identify = root.find(f"{_OAI}Identify")
        if identify is None:
            raise HarvestError("The repository did not identify itself as an OAI-PMH repository.")
        name = _text(identify, f"{_OAI}repositoryName")
        return Identity(
            name=name[:NAME_MAX] if name else name,
            protocol_version=_text(identify, f"{_OAI}protocolVersion"),
        )

    async def metadata_formats(self) -> tuple[Format, ...]:
        root = await self._ask({"verb": "ListMetadataFormats"})
        return tuple(
            Format(prefix=prefix, namespace=_text(entry, f"{_OAI}metadataNamespace"))
            for entry in root.iter(f"{_OAI}metadataFormat")
            for prefix in [_text(entry, f"{_OAI}metadataPrefix")]
            if prefix
        )

    async def marc_prefix(self) -> str:
        """The prefix this repository serves MARC21 slim under.

        **By namespace**, because the prefix is the repository's own name for
        it. One wider than `harvests.metadata_prefix` is passed over, since the
        run could not record what it asked for.
        """
        for entry in await self.metadata_formats():
            if entry.namespace == marc_fields.NAMESPACE and len(entry.prefix) <= HARVEST_METADATA_PREFIX_MAX:
                return entry.prefix
        raise HarvestError(
            "The repository offers no MARCXML format, and Dublin Core alone is not read by this library yet."
        )

    async def list_records(
        self,
        prefix: str,
        *,
        set_spec: str | None = None,
        max_records: int = MAX_RECORDS,
        max_pages: int = MAX_PAGES,
    ) -> Harvested:
        """Every record the repository lists, page by page, within the run's bounds.

        `noRecordsMatch` is an empty repository or set, and answers no records
        rather than an error. Every way out of the loop but the last page is a
        truncation, and keeps the pages read.
        """
        walk = _Walk(max_records)
        params = {"verb": "ListRecords", "metadataPrefix": prefix} | ({"set": set_spec} if set_spec else {})
        tokens: set[str] = set()
        pages = 0
        while (root := await self._page(params, pages)) is not None:
            pages += 1
            await anyio.to_thread.run_sync(walk.take, root.findall(f"{_OAI}ListRecords/{_OAI}record"))
            token = _next_token(root, tokens)
            if token is None:
                return walk.harvested(prefix, pages)
            if walk.full() or pages >= max_pages or left(self._ends) <= 0:
                break
            params = {"verb": "ListRecords", "resumptionToken": token}
        walk.truncated = True
        return walk.harvested(prefix, pages)

    async def _page(self, params: Mapping[str, str], pages_read: int) -> ElementTree.Element | None:
        """One `ListRecords` page, or None where the run was cut after a page was read."""
        try:
            return await self._ask(params, allow=_EMPTY_IS_AN_ANSWER)
        except _RunCut:
            if pages_read == 0:
                raise
            return None

    async def get_record(self, identifier: str, prefix: str) -> Harvested:
        """One record by its OAI identifier."""
        walk = _Walk(1)
        root = await self._ask({"verb": "GetRecord", "identifier": identifier, "metadataPrefix": prefix})
        walk.take(root.findall(f"{_OAI}GetRecord/{_OAI}record"))
        return walk.harvested(prefix, 1)

    async def _ask(
        self, params: Mapping[str, str], allow: frozenset[str] = frozenset()
    ) -> ElementTree.Element:
        """One request, as a parsed OAI-PMH response, or the refusal an admin acts on.

        **A 503 is a cut, not a failure**: it is OAI-PMH's own flow control, a
        busy repository asking the harvester to wait. `fetch.Fetched` carries no
        header, so its `Retry-After` is not read and the run stops there with
        what it has; the next run asks again.
        """
        answer = await self._fetched(params)
        if answer.status_code == 503:
            raise _RunCut("The repository answered 503: it is busy, and the run stopped there.")
        if answer.status_code >= 400:
            raise HarvestError(f"The repository answered {answer.status_code}.")
        return await anyio.to_thread.run_sync(functools.partial(read_response, answer.text, allow=allow))

    async def _fetched(self, params: Mapping[str, str]) -> fetch.Fetched:
        """One request's answer, whatever its status.

        **Both deadlines, the smaller one winning**: `fetch.get` treats a
        supplied deadline as the whole budget, so the run's alone would let one
        request spend all of it (`opds.holdings` found the same). Either one
        running out is a `_RunCut`, so a slow page keeps the pages before it.
        """
        try:
            return await fetch.get(
                self._client,
                self._base_url,
                params=params,
                deadline=min(self._ends, in_(fetch.TIMEOUT_SECONDS)),
            )
        except fetch.AddressRefused as refusal:
            # Ahead of the `httpx.HTTPError` arm, which it is a subclass of: a
            # refused address is a fact about the setting, not about the server.
            logger.warning("OAI-PMH repository at %s is at a refused address: %s", self._base_url, refusal)
            raise HarvestError(
                "The repository is at an address this library will not connect to."
            ) from refusal
        except httpx.HTTPError as refusal:
            logger.warning("OAI-PMH repository at %s could not be read: %s", self._base_url, refusal)
            if isinstance(refusal, fetch.DeadlineExceeded):
                raise _RunCut(
                    "The repository did not answer in time, and the run stopped there."
                ) from refusal
            raise HarvestError(
                "The repository could not be reached, or did not answer in time or within the size"
                " this library reads."
            ) from refusal


@asynccontextmanager
async def repository(
    base_url: str,
    *,
    resolver: fetch.Resolver = fetch.system_resolver,
    deadline_seconds: float = RUN_DEADLINE_SECONDS,
) -> AsyncIterator[Repository]:
    """A `Repository` at `base_url`, on a pinned client, for one run.

    **`resolver` is a seam and never a policy**, as at `opds.holdings`:
    `fetch.HOUSEHOLD_ADDRESSES` is applied to whatever it answers.
    """
    async with fetch.pinned_client(fetch.HOUSEHOLD_ADDRESSES, resolver=resolver) as client:
        yield Repository(client, base_url, in_(deadline_seconds))


async def harvest(
    base_url: str,
    *,
    set_spec: str | None = None,
    resolver: fetch.Resolver = fetch.system_resolver,
) -> tuple[Identity, Harvested]:
    """One run over `base_url`: who it is, then every MARC record it lists."""
    async with repository(base_url, resolver=resolver) as source:
        identity = await source.identify()
        prefix = await source.marc_prefix()
        return identity, await source.list_records(prefix, set_spec=set_spec)
