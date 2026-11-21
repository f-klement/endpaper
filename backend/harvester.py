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

**MARCXML whenever the repository offers it, and Dublin Core only when it does
not** (owner, 2026-11-21): `oai_dc` is the protocol's mandatory format, so every
repository has it, and it carries less. A format is chosen by namespace rather
than by prefix, since a repository names its own formats (`oai.py` serves
`marc21`; others say `marcxml`), and `oai_dc` is also taken by its prefix, which
the protocol reserves for it. `Harvested.read_as` says which a run read, and the
preview and the result say it to the admin.

A MARC record goes through `marc.read`, the upload reader, so a harvested record
is read exactly as a file's. A Dublin Core record goes through
`_dublin_core_record`, the same upload profile in the other serialisation: it
refuses only a record with no title. What Dublin Core cannot say is said there.
Either way the records reach the same apply and the same matching ladder.

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

import bibliographic
import credentials
import fetch
import marc
import marc_fields
import metadata
import settings_store
import xml_parse
from catalogue import Record, uncontrolled
from deadline import in_, left
from enums import HarvestFormat
from models import HARVEST_METADATA_PREFIX_MAX, HARVESTED_IDENTIFIER_MAX

logger = logging.getLogger("endpaper.harvester")

#: The OAI-PMH 2.0 namespace every response element is in.
OAI: Final = "http://www.openarchives.org/OAI/2.0/"
_OAI: Final = f"{{{OAI}}}"

#: The `oai_dc` namespace, and the prefix the protocol reserves for it.
#:
#: **Spelled here and not imported from `oai.py`**, which serves the same format:
#: that module is the provider, reads the Shelf and the public serialisation, and
#: a client importing it would carry the server into every harvest.
#: `tests/test_harvester.py` holds the two spellings equal.
OAI_DC: Final = "http://www.openarchives.org/OAI/2.0/oai_dc/"
OAI_DC_PREFIX: Final = "oai_dc"
_DC: Final = "{http://purl.org/dc/elements/1.1/}"

#: The formats a run reads, by namespace, in the order it prefers them.
_PREFERRED: Final = ((marc_fields.NAMESPACE, HarvestFormat.MARCXML), (OAI_DC, HarvestFormat.DUBLIN_CORE))

#: What labels a Dublin Core record, as `marc.SOURCE` labels a MARC one.
DUBLIN_CORE_SOURCE: Final = "oai_dc"

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
class Chosen:
    """The format a run asks for: the repository's prefix, and what it is."""

    prefix: str
    read_as: HarvestFormat


@dataclass(frozen=True, slots=True)
class Harvested:
    """What one run read: the records as an upload reads a file, and the counts."""

    prefix: str
    #: Which serialisation the records were read in. Dublin Core carries less.
    read_as: HarvestFormat
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
    read_as: HarvestFormat = HarvestFormat.MARCXML
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
            node = _the_one_record(record, self.read_as)
            if node is None:
                self.unreadable += 1
            else:
                kept.append((_identifier(header), node))
        if kept:
            self._read(kept)

    def _read(self, kept: list[tuple[str | None, ElementTree.Element]]) -> None:
        """One page's records, each kept beside its identifier."""
        if self.read_as is HarvestFormat.DUBLIN_CORE:
            self._read_dublin_core(kept)
        else:
            self._read_marc(kept)

    def _read_dublin_core(self, kept: list[tuple[str | None, ElementTree.Element]]) -> None:
        """One page's Dublin Core records, one at a time, so a refused one
        takes its identifier with it."""
        records: list[Record] = []
        skipped = 0
        for key, node in kept:
            record = _dublin_core_record(node)
            if record is None:
                skipped += 1
                continue
            records.append(record)
            self.identifiers.append(key)
        self.pages.append(marc.ParsedMarc(records=tuple(records), skipped=skipped))

    def _read_marc(self, kept: list[tuple[str | None, ElementTree.Element]]) -> None:
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
            read_as=self.read_as,
            parsed=marc.ParsedMarc(records=records, skipped=skipped, links=links),
            seen=self.seen,
            deleted=self.deleted,
            pages_read=pages_read,
            truncated=self.truncated,
            identifiers=tuple(self.identifiers),
        )


def _the_one_record(record: ElementTree.Element, read_as: HarvestFormat) -> ElementTree.Element | None:
    """An OAI record's one record in the run's format, or None where its
    `<metadata>` holds none, two side by side, or a MARC record holding another.

    **A Dublin Core record holding another is not refused**, because nothing
    walks it: `_dublin_core_record` reads only its direct children.
    """
    if read_as is HarvestFormat.DUBLIN_CORE:
        nodes = record.findall(f"{_OAI}metadata/{{{OAI_DC}}}dc")
        return nodes[0] if len(nodes) == 1 else None
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
    writes none, only suggestions: `docs/decisions.md`, *Harvesting an OAI-PMH
    repository*.
    """
    collection = ElementTree.Element(f"{{{marc_fields.NAMESPACE}}}collection")
    collection.extend(nodes)
    try:
        return marc.read(ElementTree.tostring(collection, encoding="utf-8"))
    except marc.MarcError as error:
        raise HarvestError(
            f"The repository sent MARC records this library could not read: {error}"
        ) from error


def _dublin_core_record(node: ElementTree.Element) -> Record | None:
    """One `oai_dc` record as evidence about a book, or None where it has no title.

    **The upload profile, as `marc._record` is MARC's**: a record with no title
    is the only thing refused, and an over wide string is cut to its column
    rather than dropped, through `Record.from_upload`, for the reason given
    there. So no carrier test runs: a MARC harvest imports a disc too, and a
    Dublin Core `type` is a free word with no carrier code behind it.

    **What Dublin Core cannot say, and what is read instead:**

    | Element | Read as |
    |---|---|
    | `title` | the first, split by `bibliographic.split_title_statement` |
    | `creator` | every one in order, through `bibliographic.credit_line`: no role, so all are authors |
    | `contributor` | the authors where no `creator` is, as MARC names everybody where nobody wrote it |
    | `identifier` | an ISBN, `bibliographic.isbn_among_identifiers` |
    | `date` | the earliest year, `bibliographic.earliest_year` |
    | `language` | a two letter code, `bibliographic.two_letter_language` |
    | `publisher`, `description` | the first |
    | `format` | a page count, where one reads as an extent |
    | `subject` | uncontrolled subjects, and never a heading |

    **No heading, so a Dublin Core run raises no suggestion.** `dc:subject`
    names no scheme, and a heading is a number in a scheme: a `ddc:830` or a
    bare `830` is one repository's convention, not the format's, and a guess
    would put a number in the wrong vocabulary on a Book. No series, since
    `dc:relation` is any relation at all, and no links, since a `dc:identifier`
    URL is as often the repository's own landing page as a copy of the book.
    """

    def values(element: str) -> list[str]:
        return [
            text.strip() for child in node.findall(f"{_DC}{element}") if (text := child.text) and text.strip()
        ]

    titles = values("title")
    title, subtitle = bibliographic.split_title_statement(titles[0]) if titles else ("", None)
    if not title:
        return None
    return Record.from_upload(
        source=DUBLIN_CORE_SOURCE,
        isbn=bibliographic.isbn_among_identifiers(values("identifier")),
        title=title,
        subtitle=subtitle,
        author=bibliographic.credit_line(values("creator") or values("contributor")),
        publisher=next(iter(values("publisher")), None),
        year=bibliographic.earliest_year(values("date")),
        description=next(iter(values("description")), None),
        language=bibliographic.two_letter_language(values("language")),
        page_count=next(
            (pages for extent in values("format") if (pages := bibliographic.pages_from_extent(extent))), None
        ),
        subjects=uncontrolled(values("subject")),
    )


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


def _reads_as(entry: Format, namespace: str, read_as: HarvestFormat) -> bool:
    """Whether a listed format is the one `namespace` names, by its namespace
    or, for Dublin Core alone, by the prefix the protocol reserves."""
    return entry.namespace == namespace or (
        read_as is HarvestFormat.DUBLIN_CORE and entry.prefix == OAI_DC_PREFIX
    )


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

    async def chosen_format(self) -> Chosen:
        """MARC21 slim where the repository offers it, else Dublin Core.

        **By namespace**, because the prefix is the repository's own name for
        it, except that `oai_dc` is also taken by its prefix, which the protocol
        reserves for Dublin Core. One wider than `harvests.metadata_prefix` is
        passed over, since the run could not record what it asked for, so a
        repository offering MARC only under such a prefix is read in Dublin
        Core, and the admin is told it offers no MARCXML this app can ask for.
        A repository offering neither is broken, since `oai_dc` is mandatory.

        **MARCXML listed and then refused at `ListRecords` fails the run**
        rather than falling back: the choice is made once, from what the
        repository lists, and a repository refusing a format it lists is
        broken in a way the admin should hear about.
        """
        offered = [
            entry
            for entry in await self.metadata_formats()
            if len(entry.prefix) <= HARVEST_METADATA_PREFIX_MAX
        ]
        for namespace, read_as in _PREFERRED:
            for entry in offered:
                if _reads_as(entry, namespace, read_as):
                    return Chosen(entry.prefix, read_as)
        raise HarvestError(
            "The repository offers neither MARCXML nor Dublin Core, which every repository must offer."
        )

    async def list_records(
        self,
        prefix: str,
        *,
        read_as: HarvestFormat = HarvestFormat.MARCXML,
        set_spec: str | None = None,
        max_records: int = MAX_RECORDS,
        max_pages: int = MAX_PAGES,
    ) -> Harvested:
        """Every record the repository lists, page by page, within the run's bounds.

        `noRecordsMatch` is an empty repository or set, and answers no records
        rather than an error. Every way out of the loop but the last page is a
        truncation, and keeps the pages read.
        """
        walk = _Walk(max_records, read_as)
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

    async def get_record(
        self, identifier: str, prefix: str, read_as: HarvestFormat = HarvestFormat.MARCXML
    ) -> Harvested:
        """One record by its OAI identifier."""
        walk = _Walk(1, read_as)
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
    """One run over `base_url`: who it is, then every record it lists, in MARCXML
    where it offers that and in Dublin Core where it does not."""
    async with repository(base_url, resolver=resolver) as source:
        identity = await source.identify()
        chosen = await source.chosen_format()
        return identity, await source.list_records(chosen.prefix, read_as=chosen.read_as, set_spec=set_spec)
