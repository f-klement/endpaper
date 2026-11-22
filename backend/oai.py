"""OAI-PMH, served: an aggregator harvests the published catalogue by date.

## The third surface reachable without a session, answering the same questions

| Question | Answered by |
|---|---|
| Is anything published at all? | `public_reader`, then `oai_switch`, in `routers/oai.py` |
| Which **rows** may be shown? | `Shelf.seen_by_the_public`, the only row filter here, on every page |
| Which **columns** may be shown? | `PublicBookOut` for `oai_dc`; `marc.record_element`, pinned to it |
| May these rows leave the instance? | `shelf.Outbound`, from `outbound_page` and `outbound_first` |
| How fast may a stranger ask? | `ratelimit.public_catalogue_limiter`, the same counter |
| What does a deleted record say? | an identifier and a datestamp, from `OaiTombstone` (`harvest.py`) |

**A deleted header names only a record that was public.** `harvest.py` writes a
tombstone for a Book that leaves the public shelf after this provider first
answered a request, never for one that was always private, so a private Book's
id answers `idDoesNotExist` exactly as an id that never existed does.

## Datestamps are served to the day

**A header says more than the JSON catalogue does, and only this**: the day a
record last changed, and for a deleted header the day it left. A record never
edited carries the day its Book was added, which the JSON catalogue withholds
(`schemas.public.PublicBookSort`). The owner accepted that cost and chose the
day over the second, so `Identify` advertises `YYYY-MM-DD`, every datestamp is
the day, and a `from` or `until` given to the second is `badArgument`, as the
specification asks of a granularity finer than the repository's. What is stored
is to the second; only what is served is coarsened.

## No query language, so the whole input is six verbs and five arguments

Every argument is read against a closed syntax before anything is looked up: a
value that is not printable ASCII within `MAX_ARGUMENT_CHARS` is `badArgument`,
so what the `<request>` element echoes back is always a value this module
already accepted. `badVerb` and `badArgument` echo nothing, as the specification
asks.

## The resumption token cannot widen anything

It carries the format, the `from` and `until` window and the last id served,
base64 encoded so a harvester treats it as opaque. **Every field is one a caller
may ask for in a fresh request**, so a forged token reaches exactly what a fresh
request reaches. The window travels as day numbers, which cannot name an hour,
and `_within` compares every bound as the start of its day whatever built it, so
neither path can bisect a day to recover a datestamp to the second. What bounds
a harvest is not in it: the row filter and `PAGE_SIZE` are applied by the
server on every page. Anything not exactly the shape `_encode` writes is
`badResumptionToken`.

**Paged by id, not by offset**: the next page is the ids after the last one
served, so a record changed during a harvest is neither served twice nor makes
another skip. One that moves out of the window is caught by the next
incremental harvest, which is what its new datestamp is for.
"""

import base64
import binascii
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Final, NamedTuple
from urllib.parse import parse_qsl
from xml.etree import ElementTree

from sqlalchemy import func
from sqlalchemy.orm import InstrumentedAttribute, Session

import marc
import settings_store
from enums import SettingKey
from models import Book, OaiTombstone, datestamp_now
from schemas.common import MAX_ROW_ID
from schemas.public import PublicBookOut
from serialisation import books_to_public_out
from shelf import Loading, Shelf

NAMESPACE: Final = "http://www.openarchives.org/OAI/2.0/"
_XSI: Final = "http://www.w3.org/2001/XMLSchema-instance"
_OAI_DC: Final = "http://www.openarchives.org/OAI/2.0/oai_dc/"
_DC: Final = "http://purl.org/dc/elements/1.1/"

#: What every response is labelled. The specification's own type.
MEDIA_TYPE: Final = "text/xml; charset=utf-8"

#: The application's name and nothing about the deployment, as SRU's `explain`.
REPOSITORY_NAME: Final = "Endpaper"

#: The granularity every datestamp is served at. See the module docstring.
GRANULARITY: Final = "YYYY-MM-DD"

#: Records per page. Fixed, and absent from the token, so no caller can raise it.
#: A page of `marc21` at this size is a few hundred kilobytes.
PAGE_SIZE: Final = 50

#: The longest argument value read at all. A token is far shorter.
MAX_ARGUMENT_CHARS: Final = 256

#: The most `key=value` pairs read from one query string: six arguments and one
#: repeat, which is `badArgument` anyway, need no more.
MAX_FIELDS: Final = 8

#: The longest resumption token `_encode` can write, and so the longest read.
MAX_TOKEN_CHARS: Final = 64

#: A value the `<request>` element may echo: printable ASCII and nothing else.
_ECHOABLE: Final = re.compile(rf"[\x21-\x7e]{{1,{MAX_ARGUMENT_CHARS}}}")

#: A `from` or `until` at the one granularity served.
_DAY: Final = re.compile(r"\d{4}-\d{2}-\d{2}")

#: The decoded token: format, window start and end as `date.toordinal()`, last id.
_TOKEN: Final = re.compile(
    r"(?P<prefix>[a-z0-9_]{1,10})!(?P<start>\d{1,7})?!(?P<end>\d{1,7})?!(?P<after>\d{1,10})"
)
_TOKEN_CHARACTERS: Final = re.compile(rf"[A-Za-z0-9_\-]{{1,{MAX_TOKEN_CHARS}}}")


class Format(NamedTuple):
    prefix: str
    schema: str
    namespace: str


#: The two formats served. `oai_dc` is the protocol's mandatory one.
FORMATS: Final[dict[str, Format]] = {
    "oai_dc": Format("oai_dc", "http://www.openarchives.org/OAI/2.0/oai_dc.xsd", _OAI_DC),
    "marc21": Format("marc21", "http://www.loc.gov/standards/marcxml/schema/MARC21slim.xsd", marc.NAMESPACE),
}


class ErrorCode(StrEnum):
    """The errors the specification names, every one this server can answer."""

    BAD_VERB = "badVerb"
    BAD_ARGUMENT = "badArgument"
    BAD_RESUMPTION = "badResumptionToken"
    CANNOT_DISSEMINATE_FORMAT = "cannotDisseminateFormat"
    ID_DOES_NOT_EXIST = "idDoesNotExist"
    NO_RECORDS_MATCH = "noRecordsMatch"
    NO_SET_HIERARCHY = "noSetHierarchy"


#: The two errors after which `<request>` carries no arguments: what was sent
#: was not a request this server can describe.
_UNECHOED: Final = frozenset({ErrorCode.BAD_VERB, ErrorCode.BAD_ARGUMENT})


class OaiError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Repository:
    """Where this request says the repository is, for `Identify` and the identifiers."""

    host: str
    base_url: str

    def identifier(self, book_id: int) -> str:
        return f"oai:{self.host}:{book_id}"

    def book_id(self, identifier: str) -> int:
        """The id an identifier names, or `idDoesNotExist`."""
        prefix = f"oai:{self.host}:"
        number = identifier.removeprefix(prefix)
        if number == identifier or not re.fullmatch(r"[1-9]\d{0,9}", number) or int(number) > MAX_ROW_ID:
            raise OaiError(ErrorCode.ID_DOES_NOT_EXIST, "No such record")
        return int(number)


#: Each verb's required and optional arguments. `resumptionToken` is exclusive:
#: `_read` refuses it beside anything but the verb.
_ARGUMENTS: Final[dict[str, tuple[frozenset[str], frozenset[str]]]] = {
    "Identify": (frozenset(), frozenset()),
    "ListMetadataFormats": (frozenset(), frozenset({"identifier"})),
    "ListSets": (frozenset(), frozenset({"resumptionToken"})),
    "GetRecord": (frozenset({"identifier", "metadataPrefix"}), frozenset()),
    "ListIdentifiers": (
        frozenset({"metadataPrefix"}),
        frozenset({"from", "until", "set", "resumptionToken"}),
    ),
    "ListRecords": (frozenset({"metadataPrefix"}), frozenset({"from", "until", "set", "resumptionToken"})),
}


# ── Reading the request ──────────────────────────────────────────────────────


def _pairs(query_string: str) -> list[tuple[str, str]]:
    try:
        return parse_qsl(query_string, keep_blank_values=True, max_num_fields=MAX_FIELDS)
    except ValueError as error:
        raise OaiError(ErrorCode.BAD_ARGUMENT, "Too many arguments") from error


def _verb(pairs: list[tuple[str, str]]) -> str:
    verbs = [value for key, value in pairs if key == "verb"]
    if len(verbs) != 1 or verbs[0] not in _ARGUMENTS:
        raise OaiError(ErrorCode.BAD_VERB, "Exactly one verb, and one of the six")
    return verbs[0]


def _arguments(pairs: list[tuple[str, str]]) -> dict[str, str]:
    arguments: dict[str, str] = {}
    for key, value in pairs:
        if key == "verb":
            continue
        if key in arguments:
            raise OaiError(ErrorCode.BAD_ARGUMENT, "An argument was repeated")
        if not _ECHOABLE.fullmatch(value):
            raise OaiError(
                ErrorCode.BAD_ARGUMENT, "An argument's value is empty, too long or not printable ASCII"
            )
        arguments[key] = value
    return arguments


def _read(query_string: str) -> tuple[str, dict[str, str]]:
    """The verb and its arguments, or the error the specification names."""
    pairs = _pairs(query_string)
    verb = _verb(pairs)
    arguments = _arguments(pairs)
    required, optional = _ARGUMENTS[verb]
    if set(arguments) - required - optional:
        raise OaiError(ErrorCode.BAD_ARGUMENT, "An argument this verb does not take")
    if "resumptionToken" in arguments:
        if len(arguments) > 1:
            raise OaiError(ErrorCode.BAD_ARGUMENT, "resumptionToken is exclusive")
    elif required - set(arguments):
        raise OaiError(ErrorCode.BAD_ARGUMENT, "A required argument is missing")
    return verb, arguments


def _format(prefix: str) -> Format:
    found = FORMATS.get(prefix)
    if found is None:
        raise OaiError(ErrorCode.CANNOT_DISSEMINATE_FORMAT, "Formats served: oai_dc and marc21")
    return found


def _instant(value: str, *, end: bool) -> date | None:
    """A `from` or `until` as a bound.

    An `until` is inclusive, so it becomes the next day. Past year 9999 there is
    no next, and the bound is open.
    """
    refused = OaiError(ErrorCode.BAD_ARGUMENT, f"from and until are {GRANULARITY}")
    # Only once the pattern matched: `fromisoformat` alone reads forms the
    # specification does not allow, a time, an offset or a fraction among them.
    if not _DAY.fullmatch(value):
        raise refused
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise refused from error
    if not end:
        return day
    try:
        return day + timedelta(days=1)
    except OverflowError:
        return None


# ── Harvest windows and the token ────────────────────────────────────────────


@dataclass(frozen=True)
class Harvest:
    """One page's question: a format, a half open window of days, and the last id served."""

    format: Format
    start: date | None
    end: date | None
    after: int


def _window(arguments: Mapping[str, str]) -> tuple[date | None, date | None]:
    start = _instant(arguments["from"], end=False) if "from" in arguments else None
    end = _instant(arguments["until"], end=True) if "until" in arguments else None
    if start is not None and end is not None and start >= end:
        raise OaiError(ErrorCode.BAD_ARGUMENT, "from is later than until")
    return start, end


def _ordinal(day: date | None) -> str:
    return "" if day is None else str(day.toordinal())


def _day(ordinal: str | None) -> date | None:
    return None if ordinal is None else date.fromordinal(int(ordinal))


def _encode(harvest: Harvest, after: int) -> str:
    raw = f"{harvest.format.prefix}!{_ordinal(harvest.start)}!{_ordinal(harvest.end)}!{after}"
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def _decode(token: str) -> Harvest:
    """A token `_encode` wrote, or `badResumptionToken`. Nothing in one can name
    a row the window and the shelf would not, nor a bound finer than a day."""
    refused = OaiError(ErrorCode.BAD_RESUMPTION, "Not a token this server issued")
    if not _TOKEN_CHARACTERS.fullmatch(token):
        raise refused
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        match = _TOKEN.fullmatch(raw)
        if match is None or match["prefix"] not in FORMATS or int(match["after"]) > MAX_ROW_ID:
            raise refused
        return Harvest(
            FORMATS[match["prefix"]], _day(match["start"]), _day(match["end"]), int(match["after"])
        )
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise refused from error


def _harvest(arguments: Mapping[str, str]) -> Harvest:
    if "resumptionToken" in arguments:
        return _decode(arguments["resumptionToken"])
    if "set" in arguments:
        raise OaiError(ErrorCode.NO_SET_HIERARCHY, "This repository has no sets")
    start, end = _window(arguments)
    return Harvest(_format(arguments["metadataPrefix"]), start, end, 0)


def _within(
    identity: InstrumentedAttribute[int], stamp: InstrumentedAttribute[datetime], harvest: Harvest
) -> list[Any]:
    """The rows of one page. Each bound is compared as the start of its day,
    even a `datetime` handed in as a `date`: a bound finer than the day served
    would let a caller bisect a stored datestamp to the second (`combine` drops
    a `datetime`'s time)."""
    criteria = [identity > harvest.after]
    if harvest.start is not None:
        criteria.append(stamp >= datetime.combine(harvest.start, time()))
    if harvest.end is not None:
        criteria.append(stamp < datetime.combine(harvest.end, time()))
    return criteria


# ── The records ──────────────────────────────────────────────────────────────


def _datestamp(moment: datetime) -> str:
    """A datestamp as served: the day, at `GRANULARITY`."""
    return moment.strftime("%Y-%m-%d")


def _response_date(moment: datetime) -> str:
    """`responseDate`, which the specification fixes to the second."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _element(parent: ElementTree.Element, tag: str, text: str | None = None) -> ElementTree.Element:
    child = ElementTree.SubElement(parent, tag)
    if text is not None:
        child.text = text
    return child


def _dc_values(record: PublicBookOut) -> Iterator[tuple[str, object]]:
    """Unqualified Dublin Core, read off the public model and nothing else."""
    yield "title", f"{record.title}: {record.subtitle}" if record.subtitle else record.title
    for name in record.authors:
        yield "creator", name
    yield from _dc_subjects(record)
    yield from _dc_description(record)


def _dc_subjects(record: PublicBookOut) -> Iterator[tuple[str, object]]:
    for subject in (*record.categories, *(c.label or c.number for c in record.classifications)):
        yield "subject", subject
    for tag in record.tags:
        yield "subject", tag.name


def _dc_description(record: PublicBookOut) -> Iterator[tuple[str, object]]:
    yield "description", record.description
    yield "publisher", record.publisher
    yield "date", record.year
    yield "format", record.format.value if record.format else None
    yield "identifier", f"urn:isbn:{record.isbn}" if record.isbn else None
    for link in record.online_links:
        yield "identifier", link.url
    yield "language", record.language
    yield "relation", record.series_name


def dublin_core(record: PublicBookOut) -> ElementTree.Element:
    """One record as `oai_dc`. Built from `PublicBookOut`, so it carries nothing
    the JSON catalogue withholds: a column that is not on that model cannot be
    named here."""
    root = ElementTree.Element(
        "oai_dc:dc",
        {
            "xmlns:oai_dc": _OAI_DC,
            "xmlns:dc": _DC,
            "xmlns:xsi": _XSI,
            "xsi:schemaLocation": f"{_OAI_DC} {FORMATS['oai_dc'].schema}",
        },
    )
    for name, value in _dc_values(record):
        text = marc.xml_text(value) if value is not None else ""
        if text:
            _element(root, f"dc:{name}", text)
    return root


def _header(parent: ElementTree.Element, identifier: str, stamp: datetime, *, deleted: bool) -> None:
    header = _element(parent, "header")
    if deleted:
        header.set("status", "deleted")
    _element(header, "identifier", identifier)
    _element(header, "datestamp", _datestamp(stamp))


@dataclass(frozen=True)
class _Entry:
    """One record of a page: a live Book with its public form, or a tombstone."""

    book_id: int
    stamp: datetime
    book: Book | None = None
    public: PublicBookOut | None = None


def _metadata(entry: _Entry, format: Format) -> ElementTree.Element:
    if format.prefix == "marc21":
        return marc.record_element(entry.book)  # type: ignore[arg-type]
    return dublin_core(entry.public)  # type: ignore[arg-type]


def _write(parent: ElementTree.Element, entry: _Entry, repository: Repository, format: Format | None) -> None:
    """A `<header>`, or a `<record>` with its metadata where `format` is given."""
    deleted = entry.book is None
    if format is None:
        _header(parent, repository.identifier(entry.book_id), entry.stamp, deleted=deleted)
        return
    record = _element(parent, "record")
    _header(record, repository.identifier(entry.book_id), entry.stamp, deleted=deleted)
    if not deleted:
        _element(record, "metadata").append(_metadata(entry, format))


def _live(db: Session, harvest: Harvest, *, with_metadata: bool) -> list[_Entry]:
    """At most one page and one more of the public shelf in the window, by id."""
    books, _ = (
        Shelf.seen_by_the_public(db)
        .where(*_within(Book.id, Book.oai_datestamp, harvest))
        .outbound_page(
            0, PAGE_SIZE + 1, Book.id.asc(), load=Loading.PUBLISHED if with_metadata else Loading.NOTHING
        )
    )
    public = books_to_public_out(books) if with_metadata else [None] * len(books)
    return [
        _Entry(book.id, book.oai_datestamp, book, record) for book, record in zip(books, public, strict=True)
    ]


def _gone(db: Session, harvest: Harvest) -> list[_Entry]:
    rows = (
        db.query(OaiTombstone)
        .filter(*_within(OaiTombstone.book_id, OaiTombstone.datestamp, harvest))
        .order_by(OaiTombstone.book_id)
        .limit(PAGE_SIZE + 1)
        .all()
    )
    return [_Entry(row.book_id, row.datestamp) for row in rows]


def _page(db: Session, harvest: Harvest, *, with_metadata: bool) -> list[_Entry]:
    """The two sources merged by id. A live record wins over a tombstone for
    the same id, which `harvest.py` never leaves standing; the order is the
    safe one should it ever happen."""
    live = _live(db, harvest, with_metadata=with_metadata)
    held = {entry.book_id for entry in live}
    merged = live + [entry for entry in _gone(db, harvest) if entry.book_id not in held]
    return sorted(merged, key=lambda entry: entry.book_id)


# ── The six verbs ────────────────────────────────────────────────────────────


def _earliest(db: Session) -> datetime:
    """The oldest datestamp served, or now where nothing is."""
    live = Shelf.seen_by_the_public(db).select(func.min(Book.oai_datestamp)).scalar()
    gone = db.query(func.min(OaiTombstone.datestamp)).scalar()
    return min((stamp for stamp in (live, gone) if stamp is not None), default=datestamp_now())


def _identify(db: Session, repository: Repository, _arguments: Mapping[str, str]) -> ElementTree.Element:
    identify = ElementTree.Element("Identify")
    _element(identify, "repositoryName", REPOSITORY_NAME)
    _element(identify, "baseURL", repository.base_url)
    _element(identify, "protocolVersion", "2.0")
    _element(identify, "adminEmail", settings_store.get_raw(db, SettingKey.OAI_ADMIN_EMAIL).strip())
    _element(identify, "earliestDatestamp", _datestamp(_earliest(db)))
    _element(identify, "deletedRecord", "persistent")
    _element(identify, "granularity", GRANULARITY)
    return identify


def _resolve(db: Session, repository: Repository, identifier: str) -> _Entry:
    """One record by identifier: live from the public shelf, else its tombstone,
    else `idDoesNotExist`, which is also the answer for a private Book."""
    book_id = repository.book_id(identifier)
    books = Shelf.seen_by_the_public(db).where(Book.id == book_id).outbound_first(load=Loading.PUBLISHED)
    if books:
        book = next(iter(books))
        return _Entry(book.id, book.oai_datestamp, book, books_to_public_out(books)[0])
    tombstone = db.get(OaiTombstone, book_id)
    if tombstone is None:
        raise OaiError(ErrorCode.ID_DOES_NOT_EXIST, "No such record")
    return _Entry(tombstone.book_id, tombstone.datestamp)


def _list_formats(db: Session, repository: Repository, arguments: Mapping[str, str]) -> ElementTree.Element:
    if "identifier" in arguments:
        _resolve(db, repository, arguments["identifier"])
    formats = ElementTree.Element("ListMetadataFormats")
    for served in FORMATS.values():
        entry = _element(formats, "metadataFormat")
        _element(entry, "metadataPrefix", served.prefix)
        _element(entry, "schema", served.schema)
        _element(entry, "metadataNamespace", served.namespace)
    return formats


def _list_sets(_db: Session, _repository: Repository, arguments: Mapping[str, str]) -> ElementTree.Element:
    if "resumptionToken" in arguments:
        raise OaiError(ErrorCode.BAD_RESUMPTION, "This repository has no sets to resume")
    raise OaiError(ErrorCode.NO_SET_HIERARCHY, "This repository has no sets")


def _get_record(db: Session, repository: Repository, arguments: Mapping[str, str]) -> ElementTree.Element:
    format = _format(arguments["metadataPrefix"])
    entry = _resolve(db, repository, arguments["identifier"])
    answer = ElementTree.Element("GetRecord")
    _write(answer, entry, repository, format)
    return answer


def _listing(
    verb: str, *, with_metadata: bool
) -> Callable[[Session, Repository, Mapping[str, str]], ElementTree.Element]:
    """`ListIdentifiers` or `ListRecords`: the same page, with or without metadata."""

    def answer(db: Session, repository: Repository, arguments: Mapping[str, str]) -> ElementTree.Element:
        harvest = _harvest(arguments)
        entries = _page(db, harvest, with_metadata=with_metadata)
        if not entries:
            raise OaiError(ErrorCode.NO_RECORDS_MATCH, "No record in this window")
        listing = ElementTree.Element(verb)
        for entry in entries[:PAGE_SIZE]:
            _write(listing, entry, repository, harvest.format if with_metadata else None)
        _resume(listing, harvest, entries)
        return listing

    return answer


def _resume(listing: ElementTree.Element, harvest: Harvest, entries: list[_Entry]) -> None:
    """A token where more follow; an empty one ends a list that was resumed."""
    if len(entries) > PAGE_SIZE:
        _element(listing, "resumptionToken", _encode(harvest, entries[PAGE_SIZE - 1].book_id))
    elif harvest.after:
        _element(listing, "resumptionToken")


_VERBS: Final[dict[str, Callable[[Session, Repository, Mapping[str, str]], ElementTree.Element]]] = {
    "Identify": _identify,
    "ListMetadataFormats": _list_formats,
    "ListSets": _list_sets,
    "GetRecord": _get_record,
    "ListIdentifiers": _listing("ListIdentifiers", with_metadata=False),
    "ListRecords": _listing("ListRecords", with_metadata=True),
}


# ── The response ─────────────────────────────────────────────────────────────


def _envelope(repository: Repository, verb: str | None, arguments: Mapping[str, str]) -> ElementTree.Element:
    """The root, the response date and `<request>`, echoing only what was read."""
    root = ElementTree.Element(
        "OAI-PMH",
        {
            "xmlns": NAMESPACE,
            "xmlns:xsi": _XSI,
            "xsi:schemaLocation": f"{NAMESPACE} http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd",
        },
    )
    _element(root, "responseDate", _response_date(datestamp_now()))
    request = _element(root, "request", repository.base_url)
    if verb is not None:
        request.set("verb", verb)
        for key in sorted(arguments):
            request.set(key, arguments[key])
    return root


def respond(query_string: str, db: Session, repository: Repository) -> str:
    """One OAI-PMH request as one XML document. The seam the tests drive.

    A query string rather than a parsed mapping, for SRU's reason: a repeated
    argument and an argument nobody implements are errors this protocol names,
    and a mapping has already lost both. **Every refusal returns from here as a
    200 with an `<error>`**, so no input reaches a traceback.
    """
    verb: str | None = None
    arguments: dict[str, str] = {}
    try:
        verb, arguments = _read(query_string)
        body = _VERBS[verb](db, repository, arguments)
    except OaiError as error:
        echoed = error.code not in _UNECHOED
        root = _envelope(repository, verb if echoed else None, arguments if echoed else {})
        _element(root, "error", error.message).set("code", error.code.value)
    else:
        root = _envelope(repository, verb, arguments)
        root.append(body)
    return ElementTree.tostring(root, encoding="unicode", xml_declaration=True)
