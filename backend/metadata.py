"""Turning a scanned ISBN into a book, across several catalogues.

Previously this was two functions inside `routers/books.py`: Open Library, then
Google Books, then a bare 404. Three things were wrong with it, all of them
measured against the live deployment rather than guessed at.

1. **The Google fallback never sent the API key.** It built the URL by hand
   while `google_books.py` had a `_request` helper that appends `key`. So every
   fallback lookup went to the unauthenticated endpoint, which is rate limited
   per source address, and a library behind one address exhausts it almost at
   once. The observed result was a run of `429 Too Many Requests` and a 404 for
   every scan.
2. **Neither source covers German publishing.** Open Library returned 404 for
   both 978-3 ISBNs tested, and its search index returned `numFound: 0` for
   them as well. The DNB, which is the legal deposit library for Germany,
   returned a full record for each. A shelf of German books therefore looked
   like a broken scanner.
3. **Every failure reported the same thing.** "Book not found for this ISBN"
   was returned whether the catalogues genuinely had no record, or Google was
   throttling us, or the network was down. Those need different actions from
   the reader, so they are now different answers.

**Which sources are asked, and in what order, is the library's own setting**
and arrives as a `sources.Plan`: see `sources.py` for what the order does and
what it deliberately does not. Two rules stay here because they are not
preferences: `_preferred_source`, which believes the German legal deposit
library about a `9783` ISBN and K10plus about anything else, and
`_MATCH_PRECEDENCE`, which decides whose version of a shared field wins.

This sentence used to read "the sources are ordered per ISBN rather than fixed:
see `_sources_for`", naming a function that has never existed in this file.
"""

import asyncio
import functools
import logging
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any, Final
from xml.etree import ElementTree

import httpx
from rapidfuzz.distance import Levenshtein

import covers
import ddc
import fetch
import google_books
import sources
from catalogue import AuthorityAssertion, Heading, Record
from enums import AuthorityScheme, CatalogueSource, ClassificationScheme
from isbn import parse as parse_isbn
from models import MAX_PAGE_NUMBER_IN_A_BOOK

logger = logging.getLogger("endpaper.metadata")


class Outcome(StrEnum):
    """Why a source did or did not produce a record.

    The distinction is the point. `NOT_FOUND` means the catalogue was asked and
    genuinely has no such book, so the reader should type the details in.
    `RATE_LIMITED` and `UNAVAILABLE` mean nobody knows yet, and trying again in
    a minute may well work. Collapsing them, as the old code did, tells someone
    to do manual data entry for a book that was going to resolve on its own.
    """

    FOUND = auto()
    NOT_FOUND = auto()
    RATE_LIMITED = auto()
    UNAVAILABLE = auto()
    #: Nothing was asked, because this library has no catalogue switched on that
    #: can answer an ISBN.
    #:
    #: **Distinct from `NOT_FOUND` for the reason the two above it are**, and it
    #: is the sharper case of the same mistake: "no catalogue has this book"
    #: sends a reader to type it in by hand over a setting they could change in
    #: one click, and it is a claim about the world made by an app that asked
    #: nobody. A provider that cannot answer has to say so rather than fail
    #: quietly.
    NO_SOURCES = auto()


@dataclass(frozen=True)
class Lookup:
    """What the chain came back with, and from where."""

    outcome: Outcome
    #: The typed draft, or None where nothing was found. `catalogue.Record`
    #: rather than a dictionary since 2026-08-27: every source used to invent
    #: its own keys here and every consumer used to guess which were present.
    record: Record | None = None
    #: Which source answered, for the log line and the cache entry.
    source: str = ""
    #: Every source that was tried, in order, with its own outcome. Kept so a
    #: failure can be explained rather than only reported.
    attempts: list[tuple[str, Outcome]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.outcome is Outcome.FOUND and self.record is not None


# ── Open Library ──────────────────────────────────────────────────────────────
#
# The only source here with no key, no registration and no quota, and the only
# one that clusters printings: an *edition* record is one printing, a *work*
# record is the book, and `/works/{key}/editions.json` is every printing of it
# Open Library has merged. That cluster is the `thingISBN` capability without
# LibraryThing's terms attached, and it is what `metadata.candidates` answers
# with.
#
# Three request shapes, and each buys something the one before it does not:
#
#   /isbn/{isbn}.json                 the printing: title, publisher, pages,
#                                     and the two classification fields below
#   /works/{key}.json                 the book: subjects, and the author key
#   /works/{key}/editions.json        the other printings

_OPEN_LIBRARY: Final = "https://openlibrary.org"

#: A key out of an Open Library response, before it goes into a URL.
#:
#: **Not decoration.** Every one of these is concatenated into a host we own
#: (`f"{_OPEN_LIBRARY}{key}.json"`), and a value such as `@example.com/` moves
#: the *host* rather than the path: `https://openlibrary.org@example.com/.json`
#: is a request to somebody else's server, made by ours, with our timeout and
#: our network position. Matching the documented shape is what stops that.
#: Bounded rather than `\d+`: an upstream key of `/authors/OL` plus ten thousand
#: digits plus `A` is a well formed key and a 10,040 byte URL. Live ids are six
#: to eight digits.
#:
#: **Four requests interpolate a key and this guard precedes all four**:
#: `_open_library_author`, `_open_library_work`, `_open_library_author_names._name`
#: and `editions`. Nothing else here does.
#:
#: **Named rather than cited by line, because the line numbers were wrong three
#: times.** Twice from edits elsewhere in the file, and once because writing the
#: correction inserted six lines and moved every request it had just named. A
#: function name survives that; a line number is stale the moment anything above
#: it changes.
#:
#: The two requests that look similar, `_open_library`'s and `editions`' first
#: one, interpolate an **ISBN** that `isbn.parse` has already reduced to a
#: canonical ISBN-13, which is a different guard on a different value.
#:
#: What it constrains is the host at request time. What happens after the
#: request is `fetch.get`'s: redirects are walked by hand and a hop that
#: changes scheme, host or port is refused, so a key that got past this could
#: still not move the request off `openlibrary.org`. The threat this is
#: actually against is a wiki field any account can edit, not control of the
#: site, and two independent guards is the right amount for it.
_OL_AUTHOR_KEY: Final = re.compile(r"/authors/OL\d{1,12}A")
_OL_WORK_KEY: Final = re.compile(r"/works/OL\d{1,12}W")


def _open_library_key(value: object, pattern: re.Pattern[str]) -> str | None:
    """One key, or None where it is not the shape Open Library documents.

    **`fullmatch`, and that is the guard rather than a detail.** `match` and
    `search` both accept a key that merely *starts* with a valid one, so
    `/authors/OL1A@example.com/` would pass and move the host. The pinning test
    uses exactly that value, because a value the three functions all refuse
    would let a regression from `fullmatch` to `search` pass green.
    """
    if isinstance(value, str) and pattern.fullmatch(value):
        return value
    return None


def _open_library_object(response: fetch.Fetched) -> dict[str, Any]:
    """A response body as a JSON object, or an empty one.

    **A valid body that is not an object is the failure this exists for.**
    `response.json()` raises `JSONDecodeError`, a `ValueError`, which every
    caller here catches; `[]`, `"x"` and `null` parse cleanly and then raise
    `AttributeError` on `.get`, which is in no `except` clause on any of these
    paths. From the lookup that escapes to a 500 on `GET /api/books/lookup`;
    from `editions` it 500s the whole candidates page. A CDN or proxy error page
    served as `application/json` is enough to reach it.
    """
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


#: Where a subject hides on an Open Library record. All four are the same kind
#: of value: an uncontrolled string somebody typed.
_OPEN_LIBRARY_SUBJECT_KEYS: Final = (
    "subjects",
    "subject_places",
    "subject_times",
    "subject_people",
)

#: How many subjects Open Library may contribute to one record.
#:
#: **A bound, not a taste, and the number is what the measurement supports.**
#: Open Library's work subjects are a folksonomy and they are long: measured
#: over nine live works on 2026-08-24 the lists ran 0, 0, 3, 36, 65, 82, 101,
#: 122 and 137 entries. `subjects` is not stored, but it feeds two things that
#: are: `suggested_tag_ids`, which the web client pre-selects, and
#: `Record.as_match`, which joins them into the `categories` column.
#:
#: Uncapped, the union of the edition's and the work's subjects pre-selects up
#: to **16** of the 105 seeded tags on one book (1984: Fiction, Play, Essays,
#: Classic, Contemporary Fiction, Crime, Dystopian, Fantasy, Satire, Science
#: Fiction, Short Stories, War, Art, History, Language, Science). At twelve the
#: worst case over the same nine books is **4**, and the matches are the ones a
#: person would have picked: Pride and Prejudice resolves to Fiction and
#: Romance (and to Classic as well, until the matcher stopped reading a tag
#: name inside a longer word: see `match_subjects_to_tags`).
#:
#: Edition subjects are taken first, so the printing's own cataloguer beats the
#: work's crowd where both have something to say.
#:
#: **Both figures above are what a substring matcher produced.**
#: `match_subjects_to_tags` matches on word boundaries since 2026-08-24, which
#: removes four of that sixteen outright (Art out of "Outer Party", Crime out of
#: "thoughtcrime"). The cap is what keeps the rest in proportion, and the two
#: fixes are independent: the matcher stops reading a tag inside a word, and
#: this stops one book carrying 137 chances to do it.
_OPEN_LIBRARY_MAX_SUBJECTS: Final = 12


def _open_library_subjects(*records: dict[str, Any]) -> list[str]:
    """Every subject on these records, deduplicated, in order, bounded."""
    found: dict[str, None] = {}
    for record in records:
        for key in _OPEN_LIBRARY_SUBJECT_KEYS:
            entries = record.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                name = entry if isinstance(entry, str) else None
                if isinstance(entry, dict):
                    name = entry.get("name")
                if isinstance(name, str) and name.strip():
                    found.setdefault(" ".join(name.split()), None)
    return list(found)[:_OPEN_LIBRARY_MAX_SUBJECTS]


def _open_library_classifications(record: dict[str, Any]) -> list[Heading]:
    """`dewey_decimal_class` and `lc_classifications`, which are the controlled half.

    **This is the whole of what Open Library asserts from a published scheme,
    and its subjects are not part of it.** §30i's rule for the
    `classifications` table is an assertion from a published scheme; a live
    Open Library subject list carries `open_syllabus_project`,
    `fiction classics` and `Fiction, Romance, Historical, Regency`, which are
    somebody's words rather than a heading another institution can act on. They
    go to `subjects`, where the publisher's uncontrolled list already lives.

    Measured over 45 live edition records on 2026-08-24: 11 carry a Dewey
    number, always exactly one, and 17 carry an LC call number, 11 of them one,
    five two and one three.

    **Only the first LC value.** The repeats are one call number written
    several ways (`QB45.Z43 1998`, `QB45 .Z43 1998`, `QB45`), not several
    assertions, and `uq_classifications_book_scheme_number` cannot collapse
    them because they differ by a character. Storing all three would spend
    three of a book's eight rows saying one thing.

    Dewey goes through `ddc.parse_heading` like every other source path, which
    is what strips the segmentation prime and refuses `[Fic]`.
    """
    found: list[Heading] = []
    dewey = record.get("dewey_decimal_class")
    if isinstance(dewey, list):
        for value in dewey:
            if not isinstance(value, str):
                continue
            heading = ddc.parse_heading(value)
            if heading is None:
                continue
            number, label = heading
            found.append(Heading(ClassificationScheme.DDC, number, label))
    call_numbers = record.get("lc_classifications")
    if isinstance(call_numbers, list) and call_numbers:
        # No normaliser for LCC, the same as the Library of Congress path: a
        # call number is alphanumeric and this app has no schedule for it.
        # Checked rather than cast, symmetrically with the Dewey loop above:
        # `str()` on a non-string entry stores its Python repr as a call number
        # wherever the result is under 40 characters.
        first = call_numbers[0]
        number = " ".join(first.split()) if isinstance(first, str) else ""
        if number:
            found.append(Heading(ClassificationScheme.LCC, number))
    return found


def _open_library_year(raw: object) -> int | None:
    """A four digit year out of `publish_date`, which is free text.

    Live values include `2018` and `April 10, 1925`, so the year is searched
    for rather than parsed.
    """
    if not isinstance(raw, str):
        return None
    match = re.search(r"\d{4}", raw)
    return int(match.group()) if match else None


def _open_library_language(raw: object) -> str | None:
    """`[{"key": "/languages/eng"}]` as `en`, through the shared table."""
    if not isinstance(raw, list) or not raw:
        return None
    first = raw[0]
    key = first.get("key") if isinstance(first, dict) else None
    if not isinstance(key, str):
        return None
    return _LANGUAGES.get(key.rsplit("/", 1)[-1].lower())


def _open_library_pages(raw: object) -> int | None:
    """`number_of_pages`, if it is a number of pages a book could have.

    **Bounded here because nothing downstream bounds it.**
    `BookLookup.page_count` is deliberately unbounded and `PUT /{id}/refresh`
    assigns it straight onto the row, where `books.page_count` carries no CHECK.
    Measured: `10**19` raises `OverflowError` on the commit, so a 500 on the
    refresh, and anything from 100,001 to `2**63-1` stores silently past the
    app's own stated ceiling. On the scan path the same value reaches
    `BookCreate`, whose `le` then 422s the member's own post.

    The unbounded writer is pre-existing (`_pages_from_extent` and
    `google_books` pass their values through raw). What is new is the supplier:
    Open Library is a wiki and this field is editable by any account, with no
    MARC extent string in between, which is a weaker boundary than either of the
    other two.
    """
    if not isinstance(raw, int) or isinstance(raw, bool):
        return None
    return raw if 0 < raw <= MAX_PAGE_NUMBER_IN_A_BOOK else None


def _open_library_author_key(entries: object) -> str | None:
    """The first credited author's key on an edition record, if it has one.

    73 of 129 live editions listing entries carry one (measured 2026-08-24);
    the rest credit nobody at all.
    """
    if not isinstance(entries, list) or not entries:
        return None
    first = entries[0]
    return _open_library_key(
        first.get("key") if isinstance(first, dict) else None, _OL_AUTHOR_KEY
    )


def _open_library_description(raw: object) -> str | None:
    """A description, which is a plain string or `{"value": ...}` depending on age."""
    if isinstance(raw, dict):
        raw = raw.get("value")
    return raw.strip() or None if isinstance(raw, str) else None


def _open_library_work_author_key(work: dict[str, Any]) -> str | None:
    """The author on a *work* record, which nests the key one level deeper.

    An edition says `authors: [{"key": "/authors/OL..."}]` and a work says
    `authors: [{"author": {"key": ...}}]`. Both spellings are needed, because
    the edition record usually credits nobody: measured over five live
    lookups on 2026-08-24, four carried no author at all on the edition and
    every one of the four carried it on the work.
    """
    entries = work.get("authors")
    if not isinstance(entries, list) or not entries:
        return None
    first = entries[0]
    nested = first.get("author") if isinstance(first, dict) else None
    return _open_library_key(
        nested.get("key") if isinstance(nested, dict) else None, _OL_AUTHOR_KEY
    )


async def _open_library_author(
    client: httpx.AsyncClient, key: str | None
) -> str | None:
    """One author key resolved to a name, which no other record carries.

    **Its own `except`, and that is load bearing rather than defensive.** This
    runs after the edition record has already been fetched successfully, so an
    exception escaping to `_open_library`'s handler would discard a 200 that
    arrived, answer `UNAVAILABLE`, and have `_remember` cache that miss for
    `_MISS_TTL_SECONDS`. One transient timeout would then make the ISBN
    uncatalogueable for five minutes. Before this round there was one request
    and nothing to lose.
    """
    if key is None:
        return None
    try:
        response = await fetch.get(client, f"{_OPEN_LIBRARY}{key}.json")
        if response.status_code != 200:
            return None
        name = _open_library_object(response).get("name")
    except (httpx.HTTPError, ValueError):
        logger.info("Open Library author %s did not answer", key, exc_info=True)
        return None
    return name if isinstance(name, str) else None


def _open_library_work_key(entries: object) -> str | None:
    """The work an edition belongs to, which is the handle on every other printing."""
    if not isinstance(entries, list) or not entries:
        return None
    first = entries[0]
    return _open_library_key(
        first.get("key") if isinstance(first, dict) else None, _OL_WORK_KEY
    )


async def _open_library_work(
    client: httpx.AsyncClient, key: str | None
) -> dict[str, Any]:
    """The work record, for the subjects the edition record mostly lacks.

    Measured over nine live editions on 2026-08-24: the edition carried
    subjects on two of them, the work on seven. Reading only the edition is why
    Open Library used to contribute nothing to the tag suggestion for books it
    describes perfectly well.

    **Its own `except`, for the reason `_open_library_author`'s docstring
    gives**: a transport failure here must not throw away an edition record that
    already arrived, because the resulting miss is cached for five minutes.
    """
    if key is None:
        return {}
    try:
        response = await fetch.get(client, f"{_OPEN_LIBRARY}{key}.json")
        if response.status_code != 200:
            return {}
        return _open_library_object(response)
    except (httpx.HTTPError, ValueError):
        logger.info("Open Library work %s did not answer", key, exc_info=True)
        return {}


async def _open_library(isbn: str, api_key: str) -> Lookup:
    """The edition record, its work, and one call for the author's name.

    `?default=false` on the cover URL matters: without it Open Library answers
    every request with a grey placeholder image, so a book with no cover gets
    one that looks like a broken image rather than no cover at all.

    Three requests at worst, and this is the *fallback* source: it is only
    asked when the DNB and K10plus have both missed, so the cost lands on the
    lookups that were going to be slow anyway. A failure in either of the two
    extra calls costs that field and not the record.
    """
    del api_key  # Open Library needs none.

    try:
        async with fetch.catalogue_client() as client:
            response = await fetch.get(client, f"{_OPEN_LIBRARY}/isbn/{isbn}.json")
            if response.status_code == 429:
                return Lookup(Outcome.RATE_LIMITED, source="open_library")
            if response.status_code == 404:
                return Lookup(Outcome.NOT_FOUND, source="open_library")
            if response.status_code != 200:
                return Lookup(Outcome.UNAVAILABLE, source="open_library")
            data = _open_library_object(response)
            if not data:
                # A 200 carrying no object at all is a fault at the other end
                # rather than an absence, so it is `UNAVAILABLE` and not
                # `NOT_FOUND`: the difference is whether the reader is told to
                # type the book in by hand or to try again.
                logger.info("Open Library answered %s with no record object", isbn)
                return Lookup(Outcome.UNAVAILABLE, source="open_library")

            # The work first, because it is the fallback for the author: an
            # edition record names one on a minority of records and the work
            # behind it almost always does.
            work = await _open_library_work(
                client, _open_library_work_key(data.get("works"))
            )
            author = await _open_library_author(
                client,
                _open_library_author_key(data.get("authors"))
                or _open_library_work_author_key(work),
            )
    except (httpx.HTTPError, ValueError):
        logger.warning("Open Library lookup failed for %s", isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="open_library")

    publishers = data.get("publishers", [])

    return Lookup(
        Outcome.FOUND,
        source="open_library",
        record=Record(
            source="open_library",
            isbn=isbn,
            title=data.get("title", ""),
            subtitle=data.get("subtitle"),
            author=author,
            publisher=publishers[0] if publishers else None,
            year=_open_library_year(data.get("publish_date")),
            description=_open_library_description(data.get("description")),
            cover_url=covers.open_library_url(isbn),
            # Both were missing entirely until 2026-08-24, so a fallback lookup
            # answered without two of the seven fields `Record.completeness`
            # scores and `_merge` had nothing to fill them from.
            page_count=_open_library_pages(data.get("number_of_pages")),
            language=_open_library_language(data.get("languages")),
            subjects=tuple(_open_library_subjects(data, work)),
            # The edition record's own, not the cluster's. 24 of 129 live
            # sibling editions carry a Dewey number where the edition asked
            # for carries none, so harvesting the cluster here would find
            # more; it would also cost a fourth request on every fallback
            # lookup, and the cluster is already fetched where somebody is
            # choosing an edition. Left as the cheaper half deliberately.
            headings=tuple(_open_library_classifications(data)),
        ),
    )


# ── Google Books ──────────────────────────────────────────────────────────────


async def _google_books(isbn: str, api_key: str) -> Lookup:
    """Google's volume record, through the keyed client in `google_books`.

    Routed through that module rather than building the URL here, which is
    exactly the bug this replaced: a second hand-rolled request that forgot the
    key and got throttled on every call.
    """
    try:
        fields = await google_books.lookup_by_isbn(isbn, api_key)
    except google_books.GoogleBooksError as error:
        # `google_books` raises one exception type for every refusal, so the
        # message is the only thing carrying which one it was.
        outcome = (
            Outcome.RATE_LIMITED if "rate limiting" in str(error) else Outcome.UNAVAILABLE
        )
        logger.info("Google Books declined %s: %s", isbn, error)
        return Lookup(outcome, source="google_books")
    except (httpx.HTTPError, ValueError):
        logger.warning("Google Books lookup failed for %s", isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="google_books")

    if fields is None:
        return Lookup(Outcome.NOT_FOUND, source="google_books")

    return Lookup(
        Outcome.FOUND, source="google_books", record=_google_record(fields, isbn)
    )


def _google_record(fields: dict[str, Any], isbn: str | None = None) -> Record:
    """A Google volume as a Catalogue record. The adapter for that source.

    `google_books.py` stays the HTTP client for Google and knows nothing about
    this type, exactly as `fetch.py` stays the door outwards. The mapping lives
    here beside the other five, so a reader comparing what the sources supply
    has one file to read.

    `google_books_id` is carried because it is the one field only Google has and
    `google_books.merge_into` writes it onto the Book. The categories are split
    back into subjects here and joined again by `Record.as_match`, which looks
    like a round trip and is the price of there being exactly two functions in
    this repository that know the separator is a semicolon.
    """
    return Record(
        source="google_books",
        isbn=fields.get("isbn13") or isbn,
        title=fields.get("title") or "",
        subtitle=fields.get("subtitle"),
        author=fields.get("author"),
        publisher=fields.get("publisher"),
        year=fields.get("year"),
        description=fields.get("description"),
        cover_url=fields.get("cover_url"),
        page_count=fields.get("page_count"),
        language=fields.get("language"),
        google_books_id=fields.get("google_books_id"),
        series_name=fields.get("series_name"),
        series_index=fields.get("series_index"),
        subjects=tuple(google_books.split_categories(fields.get("categories"))),
    )


#: The one construct that makes a response's size a lie. XML spells it exactly
#: this way and only in the prolog, and character data cannot contain a literal
#: `<`, so a substring test is exact rather than a heuristic.
_DOCTYPE: Final = "<!DOCTYPE"


def _parsed(body: str) -> ElementTree.Element:
    """A catalogue's XML, refusing the one thing that unbounds its cost.

    `xml.etree` expands internal entities, so a body carrying a doctype can
    define an entity worth a thousand times its own bytes: measured on this
    project's Python 3.14.7, ten characters nested three deep expand to 1,000,
    and six deep is a million. Everything else this module holds is bounded by
    the response size; this was not.

    **No catalogue here sends one.** 225 live DNB and K10plus responses cached
    2026-08-24 carry none, nor does a live BnF or Library of Congress answer,
    nor did any of roughly 120 live ÖNB responses on 2026-08-27. So
    refusing costs nothing measurable, and the source that would send one is the
    substituted response `docs/decisions.md` records the Library of Congress as
    reachable for, over plaintext HTTP.

    Raised as `ParseError` because all eight callers already catch it: a catalogue
    that starts sending a doctype degrades to "this source is unavailable"
    rather than to a 500.

    **The other half is `fetch.MAX_RESPONSE_BYTES`**, which caps the bytes read
    off the wire. Both halves are needed and neither substitutes for the other:
    the cap bounds an honest body at a measured 15.28x its own size, and the
    doctype refusal bounds the one construct that makes that ratio a lie.
    """
    if _DOCTYPE in body:
        raise ElementTree.ParseError("Refused a catalogue response carrying a doctype.")
    return ElementTree.fromstring(body)


# ── MARC21, shared ────────────────────────────────────────────────────────────
#
# Two catalogues here speak MARC21: the DNB and K10plus. The primitives that
# take a record apart live in this block because both read the same subfields.
# What differs is which fields a catalogue fills in and how it marks a role,
# and that stays in each source's own section below.


class _Subfields(dict[str, str]):
    """One MARC field's subfields: the first value per code, repeats kept.

    Indexing gives the first occurrence, because a scalar read wants one value
    and MARC writes the primary one first. `all()` gives every occurrence, and
    two fields in this file need it. **Remove it and both go quiet rather than
    failing**, which is why it is a type rather than a call at each site.

    * `082 $a` repeats. The DNB puts the Dewey number and its own Sachgruppe
      letter in one field, `$a=830 $a=B`, in 10 of 85 live records measured
      2026-08-24. Keeping the last value reads the number as `B`,
      `ddc.notation` refuses it, and the record stores no classification at all.
    * `$0` repeats wherever a heading is authority controlled. The DNB writes
      `(DE-588)118181505`, then `https://d-nb.info/gnd/118181505`, then
      `(DE-101)118181505`, so keeping the last takes one library's house number
      where the GND identifier is the point.

    A `dict[str, str]` subclass rather than `dict[str, list[str]]`, so the
    scalar reads elsewhere in this file keep working unchanged: repeats are the
    exception and `entry.get("a")` is the rule.
    """

    def __init__(self, pairs: Iterable[tuple[str, str]]) -> None:
        repeats: dict[str, list[str]] = {}
        for code, value in pairs:
            repeats.setdefault(code, []).append(value)
        super().__init__({code: values[0] for code, values in repeats.items()})
        self._repeats = repeats

    def all(self, code: str) -> list[str]:
        """Every value under one code, in the order the record wrote them."""
        return self._repeats.get(code, [])


_MARC: Final = "{http://www.loc.gov/MARC21/slim}"

#: MARC's non-sorting delimiters. A record brackets a leading article with
#: these so a catalogue can file `Die Deutschen und die USA` under D.
#:
#: **Two spellings of one convention, because the catalogues do not agree on
#: which characters to use.** The DNB writes U+0098 and U+009C, which is what
#: MARC21 specifies. ÖNB writes `<<` and `>>`, and writes U+0098 nowhere at
#: all. Measured over live 245 `$a` values on 2026-08-27: 21 of 189 DNB carry
#: U+0098 and 0 carry `<<`; 21 of 150 ÖNB carry `<<` and 0 carry U+0098;
#: K10plus carries neither in 200.
#:
#: **Stripped wherever they appear rather than only at the front**, which is
#: how the MARC characters were already treated and is also what the data
#: needs: 28 of the 111 bracketed runs in 21,760 live ÖNB subfields are not at
#: the start, because the same device marks a nobiliary particle inside a
#: personal name (`Einem, Gottfried <<von>>`). So this reaches `100 $a`, 21
#: occurrences, as well as `245 $a`, 52.
#:
#: **Safe to apply to every source rather than to ÖNB alone**, and that is a
#: measurement rather than a hope: `<<` and `>>` appear in 0 of 32,038 live DNB
#: subfields and 0 of 45,710 K10plus subfields. Scoping it to one parser would
#: mean `_marc_text` doing different things depending on who called it, which
#: is the invisible kind of rule this function exists to avoid.
_NON_SORTING: Final = ("\x98", "\x9c", "<<", ">>")


def _marc_text(raw: str | None) -> str:
    """One subfield's text, as a person would write it.

    Three repairs, all measured against the live DNB on 2026-08-24, and none
    needed under Dublin Core because that crosswalk had already done them.
    **All three are invisible in a terminal**, which is why they are done here
    for every subfield rather than field by field where somebody would
    eventually read a diff and see nothing wrong.

    * **The non-sorting delimiters are stripped**, in both the spellings
      `_NON_SORTING` lists. They are a filing device and not part of the title,
      and they carry through into whatever is stored: 28 of 85 live DNB records
      hold at least one, and one live ÖNB title in seven.
    * **Internal whitespace is collapsed.** MARC pads subfields, which
      `ClassificationIn.tidy_number` already says and already fixes for one
      column. `245 $a` on the reference record 9783446249974 reads
      `Reisen im  Licht der Sterne`, a real double space, where that record's
      own `776 $t` spells it with one.
    * **The text is normalised to NFC.** The DNB serves MARC21 decomposed and
      Dublin Core composed, so `Müller` arrives as `u` plus a combining
      diaeresis: 83 of the same 85 records are affected. It renders identically
      and compares unequal, which is enough to store two spellings of one
      author and to defeat `_duplicate_key`, which casefolds and collapses
      whitespace and does not normalise. Not enough to duplicate a
      classification: `uq_classifications_book_scheme_number` is on `number`,
      which is digits in DDC and digits and hyphens in GND.
    """
    text = raw or ""
    for delimiter in _NON_SORTING:
        text = text.replace(delimiter, "")
    return " ".join(unicodedata.normalize("NFC", text).split())


def _marc_fields(record: ElementTree.Element) -> dict[str, list[_Subfields]]:
    """One MARC record as `{tag: [subfields]}`."""
    fields: dict[str, list[_Subfields]] = {}
    for datafield in record.findall(f"{_MARC}datafield"):
        tag = datafield.get("tag")
        if tag is None:
            continue
        fields.setdefault(tag, []).append(
            _Subfields(
                (subfield.get("code") or "", _marc_text(subfield.text))
                for subfield in datafield.findall(f"{_MARC}subfield")
            )
        )
    return fields


#: The GND's code in MARC's `$0`, which is what says the identifier beside it
#: is a GND number rather than some other authority file's.
_GND_PREFIX: Final = "(DE-588)"


def _gnd_identifier(entry: _Subfields) -> str | None:
    """The GND number a field's `$0` carries, or None if it carries none.

    Stored bare. `(DE-588)` is MARC naming the scheme, the scheme is already a
    column of its own, and keeping the prefix would let one heading arrive
    under two spellings that `uq_classifications_book_scheme_number` cannot
    collapse.

    A record without one is ordinary rather than broken: 33 of 70 live 655
    fields and 21 of 73 live 100 fields carry no `(DE-588)` at all, measured
    over 85 records on 2026-08-24.
    """
    for value in entry.all("0"):
        if value.startswith(_GND_PREFIX):
            return value[len(_GND_PREFIX) :].strip() or None
    return None


# ── Deutsche Nationalbibliothek ───────────────────────────────────────────────
#
# The legal deposit library for Germany, so it holds essentially everything
# published there. It is the reason a 978-3 shelf can be catalogued at all: for
# the two ISBNs that prompted this work, Open Library answered 404 and its
# search index returned no rows, while the DNB returned a full record for each.
#
# The public SRU endpoint needs no key and no registration.
#
# **MARC21 rather than Dublin Core.** This block used to say the opposite: that
# Dublin Core was already the shape we wanted and MARC would mean a subfield
# parser for the same five values. That was true as far as it went, and what it
# missed is that the crosswalk into Dublin Core drops every identifier the
# record holds. Measured against ISBN 9783446249974 on 2026-08-23:
#
#   | schema     | bytes  | GND identifiers                       |
#   |------------|--------|---------------------------------------|
#   | oai_dc     |  1,713 | none at all                           |
#   | MARC21-xml | 15,502 | 100, 600, 650, 651, 655, 689, 710     |
#
# **The switch costs one field, and it is the DDC caption.** `dc:subject` reads
# `830 Deutsche Literatur`; MARC 082 carries `830` and nothing else, because in
# MARC the printed schedule holds the words. No other MARC field supplies it:
# grepped over the same 85 records, the German captions appear in the Dublin
# Core responses and in none of the MARC ones. Filling it in from
# `ddc.DIVISION_TAGS` would put our word in a column that records theirs, so
# the caption stays absent and `Record`'s union takes one from another source
# if any has it.
#
# What it buys, over 85 live records fetched 2026-08-24: 187 GND identified
# subject headings where Dublin Core carried none, a title and subtitle already
# split (`245 $a` and `$b`) rather than one statement of responsibility to take
# apart by hand, and an extent on 85 of 85 records where `dc:format` was
# present on 51 of 74. That last one matters more than it sounds: the old
# parser did run `_is_physical_book`, on `dc:format`, and an online record has
# no `dc:format`, so the one thing it could never reject was the one thing that
# field exists to reject. `300 $a` says "Online-Ressource" on all 28 of the 85
# records that are one.

_DNB_URL: Final = "https://services.dnb.de/sru/dnb"

#: Kept because the BnF parser reads Dublin Core. The DNB no longer does.
_DC: Final = "{http://purl.org/dc/elements/1.1/}"

# ISO 639-2/B, which is what every MARC-derived source emits, to the 639-1
# codes stored elsewhere. Shared by the DNB and K10plus parsers.
_LANGUAGES: Final[dict[str, str]] = {
    "ger": "de",
    "deu": "de",
    "eng": "en",
    "fre": "fr",
    "fra": "fr",
    "ita": "it",
    "spa": "es",
    "dut": "nl",
    "nld": "nl",
    "pol": "pl",
    "rus": "ru",
    "por": "pt",
    "swe": "sv",
    "dan": "da",
    "nor": "no",
    "fin": "fi",
    "cze": "cs",
    "gre": "el",
    "tur": "tr",
    "jpn": "ja",
    "chi": "zh",
    "ukr": "uk",
    "lat": "la",
}


def _dc_title_statement(raw: str) -> tuple[str, str | None]:
    """Pull a title and subtitle out of a whole Dublin Core title statement.

    **The BnF is the only caller.** This was the DNB parser until the DNB moved
    to MARC21, where `245 $a` and `$b` arrive already separated and none of
    this guessing is needed; the BnF still writes the statement of
    responsibility into `dc:title` the same way, so the parser moved rather
    than being deleted. The example below is the DNB record it was written
    against.

    A record carries one string holding as much as:

        [Docker: up & running] ; Praxiswissen Docker : Grundlagen und Best
        Practices ... / Sean P. Kane mit Karl Matthias ; deutsche Übersetzung
        von Thomas Demmig

    which is, in order: the original title of a translation in brackets, the
    German title, a colon and the subtitle, then a slash and the statement of
    responsibility. Everything after the slash duplicates `dc:creator`, and the
    bracketed part is a different book's title, so both are dropped.
    """
    title = raw.strip()

    # The statement of responsibility. Split on the first " / " only: a title
    # may legitimately contain a slash later on.
    title = title.split(" / ", 1)[0].strip()

    # A leading "[original title] ; " on a translation.
    title = re.sub(r"^\[[^\]]*\]\s*;\s*", "", title).strip()

    # Anything still separated by " ; " is a second work in the same volume.
    title = title.split(" ; ", 1)[0].strip()

    if " : " in title:
        main, subtitle = title.split(" : ", 1)
        return main.strip(), subtitle.strip() or None
    return title, None


def _pages_from_extent(raw: str | None) -> int | None:
    r"""`390 Seiten`, `348 S.` and `528 p.` all become a number.

    Shared by every MARC-derived source. The unit is required rather than
    optional: an extent statement also carries plate counts and dimensions, and
    a bare first number picks up `23 cm` as a page count.

    **The digit run is bounded, and that is a fix for a 500 rather than a
    tidy-up.** This read `(\d+)` and called `int()` on whatever it caught.
    CPython refuses an int/str conversion of more than
    `sys.get_int_max_str_digits()` digits, 4,300 by default, and raises
    **`ValueError`**, which is neither `httpx.HTTPError` nor
    `ElementTree.ParseError`, so none of the eight SRU handlers caught it: one
    record with 4,301 digits in its `300 $a` turned `GET /api/books/search` and
    `GET /api/books/lookup` into a 500 for every MARC source at once.

    **`fetch.MAX_RESPONSE_BYTES` cannot reach it, and the percentage is not the
    sharpest way to say so.** The poisoned envelope measures **4,870 bytes**,
    0.23% of the cap. The stronger fact is that it is **larger than the smallest
    honest response this source sends**: the ÖNB lookup floor is **4,585 bytes**,
    measured across 50 live lookups on 2026-08-27. So no cap that still admits a
    real lookup could ever have refused this. A transport bound and a parser
    bound are not substitutes, and that is the measurement which proves it
    rather than merely suggesting it.

    `_LOC_URL` is plaintext HTTP, so this needed no compromised catalogue,
    which is the same on-path attacker `fetch.RedirectedOffHost` exists for.

    **The lookbehind is what makes it a refusal rather than a guess.** A bare
    `\d{1,6}` would match the *last* six digits of a 4,301 digit run and report
    a page count invented out of the tail of an attack. Requiring that no digit
    precede the run makes an over-long number no number at all.

    The range is `MAX_PAGE_NUMBER_IN_A_BOOK`, which `_open_library_pages` has
    always applied to the same field from the other source. This was the only
    `int()` on catalogue text in this module with no bound on its digits; every
    other one reads `\d{4}`.
    """
    if not raw:
        return None
    match = re.search(r"(?<!\d)(\d{1,6})\s*(?:Seiten|Bl\.|S\.|pages|p\.|pp\.)", raw)
    if not match:
        return None
    pages = int(match.group(1))
    return pages if 0 < pages <= MAX_PAGE_NUMBER_IN_A_BOOK else None


#: Titles that are a position in a multi-volume set rather than a book.
#:
#: The DNB's `num=` index matches any identifier anywhere in a record,
#: including the "also published as" cross references a collected edition
#: carries for its parts. Searching a French ISBN therefore returned a German
#: multi-volume record whose whole title was `[Hauptbd.].`, and the chain
#: accepted it, because it had a title and a date and looked like a hit.
#:
#: Measured: `9782070360024` (Gallimard, L'Étranger) returns exactly that.
_PLACEHOLDER_TITLES: Final = re.compile(
    r"^\[?\s*(Hauptbd|Haupt-Bd|Bd|Band|Teil|Vol|Volume|Reg|Register)\b", re.IGNORECASE
)


def _is_placeholder_title(title: str) -> bool:
    """Whether a title names a volume slot rather than a work."""
    stripped = title.strip().strip("[].").strip()
    return not stripped or bool(_PLACEHOLDER_TITLES.match(title.strip()))


#: Subject fields whose headings are authority controlled, in the order they
#: are read.
#:
#: **689 is the RSWK chain and restates what the others said**, so reading all
#: five double counts by design and the repeats are folded rather than chosen
#: between. That folding is `catalogue.Record`'s since 2026-08-27 and was
#: `_dnb_subjects`'s before it, which is why that function now hands its repeats
#: on rather than resolving them. Choosing would lose headings either way:
#: measured over 85 live records on 2026-08-24, 10 of the 13 600 fields carry a
#: GND number and only 3 of those 10 appear in 689 as well, 5 being on records
#: with no 689 at all. Dropping 689 loses the chains no other field holds;
#: dropping 600 loses seven personal name subjects in ten.
#:
#: 600 is the one beyond the four the round was specified with, and it is the
#: same kind of assertion as the rest. A person named here is the *subject*, not
#: the author; the author is 100, and `docs/decisions.md` says why nothing reads
#: its identifier. 655 is the odd one: it is the **form** of the work rather
#: than its subject ("Fiktionale Darstellung"), and it is kept because a genre
#: is what a library would look for.
#:
#: **`$2` is not read, and these are not all one vocabulary.** Measured over 85
#: live records on 2026-08-24, the five fields supply 363 values: 188 declare
#: `gnd`, 37 `gnd-content`, 18 the DNB's own genre list `gatbeg`, 11 `local`,
#: and 689 declares nothing at all on 152. The uncontrolled share is accepted
#: where 653's is refused, and the difference is measurable rather than a
#: preference: 29 values against 1,403, and they are genre and local subject
#: terms rather than ONIX product codes. **That 29 counts only the fields that
#: name another vocabulary.** 689 names none, and while most of its 152 restate
#: a heading 600, 650 or 651 already carried with a GND number, some are free
#: strings such as `Geschichte 1889-1894`, so the uncontrolled share is 29 plus
#: an unmeasured part of 689 rather than 29 exactly. A value with no `(DE-588)`
#: also cannot become a classification row: `_dnb_subjects` writes one only when
#: `_gnd_identifier` answers, so the uncontrolled half reaches `subjects` alone,
#: which is the field documented as weak evidence. Filter on `$2` if that stops
#: being true.
_DNB_SUBJECT_TAGS: Final = ("650", "651", "655", "689", "600")


def _dnb_subjects(
    fields: dict[str, list[_Subfields]],
) -> tuple[list[str], list[Heading]]:
    """The controlled subject headings, as plain subjects and as GND rows.

    **A subject heading never enters the DDC path**, and that is load bearing
    rather than tidy. `ddc.parse_heading` accepts any three digit token, so
    "100 Jahre Bauhaus" as a 650 heading would be stored as DDC 100 and
    suggest the Philosophy tag. Dublin Core made that unreachable by accident,
    because `dc:subject` carried only Sachgruppen; MARC puts free text and
    Dewey in different fields, so the rule is now structural: 082 is the only
    field this module hands to `ddc`, and the headings here are GND or nothing.

    **The GND number is the half that does not move**, the way a Dewey number
    is: `(DE-588)4203576-4` names one heading whatever a record captions it.
    Unlike Dewey that is untested here rather than measured, the DNB being the
    only supplier and every caption German. It is stored bare, under its own
    scheme, with the heading text as the caption.

    **Repeats are not folded here, and they used to be.** A record restates
    itself: 689 repeats the 600, 650 and 651 headings it was built from, so the
    reference record 9783446249974 names Stevenson, Samoainseln and Schatz
    twice each. `Record` folds both collections at construction, keeping the
    first of each, which is what this function used to do with two dictionaries
    of its own. Deleting them is the point of the seam being typed: the rule has
    one owner, and the next source added inherits it rather than copying it.
    """
    subjects: list[str] = []
    headings: list[Heading] = []
    for tag in _DNB_SUBJECT_TAGS:
        for entry in fields.get(tag, []):
            heading = _strip_marc_punctuation(entry.get("a", ""))
            if not heading:
                continue
            subjects.append(heading)
            number = _gnd_identifier(entry)
            if number is not None:
                headings.append(Heading(ClassificationScheme.GND, number, heading))
    return subjects, headings


def _dnb_record(
    fields: dict[str, list[_Subfields]],
    isbn: str | None,
    *,
    source: str = "dnb",
    read_author_identifiers: bool = True,
) -> Record | None:
    """One MARC record as book fields, or None if it is not a book.

    Shared by the lookup and the search paths. `isbn` is what the lookup
    already knows and verified; the search path has none, so the record's own
    020 is read instead.

    **`read_author_identifiers` is off for the ÖNB, and that is a decision
    withheld rather than a mapping gap.** Its `100 $0` is if anything better
    than the DNB's: measured 2026-08-27 over 209 live `100 $a` fields, 158
    carry one, 75.6%, and every `$0` on a 100 field is `(DE-588)` with no other
    authority file appearing at all. What stops it being read is the rule
    `_k10plus_record` states: a catalogue is not read for a person's identifier
    until somebody has compared it live, and comparing the *numbers* is not the
    same as comparing the people they name. Leaving it on would have doubled
    the input to that path as a side effect of reusing this parser, which is
    not a thing a mapping should decide. The measurement is here so that
    turning it on costs an argument and a comparison rather than a fresh probe.

    **Shared by the ÖNB too, which is why the source is a parameter.** Its
    records are this profile and not K10plus's: measured over 150 live records
    on 2026-08-27, 360 `(DE-588)` subfields on 600/650/651/655/689, 102 Dewey
    082 fields on 85 records, and the same 020 `$q` cross references. A second
    parser would be the two dialects `catalogue.Record` has just finished
    deleting, in miniature. `Record` is frozen and no module outside
    `catalogue.py` may `replace` a field on one, so the source has to be known
    here rather than corrected afterwards.

    It reads the same subfields `_k10plus_record` does, through the same
    helpers, and differs in two places. It refuses a title that names a volume
    slot rather than a work, because the DNB's `num=` index reaches those. And
    it harvests the GND identified subject headings, which is the reason this
    parser reads MARC at all.

    **Whether an online record is a book is asked by the caller, not here**,
    because the two callers want different answers. `_dnb_search` refuses one
    outright, exactly as `_k10plus_search` does. `_dnb` ranks it below a
    physical record and takes it rather than reporting a miss: `dc:format` was
    absent on every online record, so the old parser accepted all of them, and
    refusing here would have turned 21 of 74 live lookups into misses (measured
    2026-08-24) for records that name the scanned ISBN in their own 020 and
    describe the right book.

    **A disc is refused here, on both paths.** It is a different object rather
    than this book in another form, and the Dublin Core parser refused it too
    whenever `dc:format` was present, which was 51 of 74 records. Zero of 85
    live records carry a disc extent, so this costs nothing measurable and
    stops a scanned ISBN that names a DVD becoming a book.

    **The Dewey number is first in `headings`**, which costs nothing and
    is not what makes it survive the per book ceiling: `routers/books._headings`
    sorts by scheme before it slices, because by the time a list reaches there
    `_merge` has concatenated up to four catalogues and no parser can order
    that. Measured over 85 live records on 2026-08-24: one produced 13 entries
    and every other produced 8 or fewer.
    """
    title_entry = (fields.get("245") or [_Subfields(())])[0]
    title, subtitle, series_name, series_index = _marc_title(title_entry)
    if not title:
        return None
    # A cross-referenced ISBN matched a volume slot, not this book. Reporting a
    # miss is right: some other catalogue may hold the real record, and putting
    # `[Hauptbd.].` in as a title poisons the entry for good.
    if _is_placeholder_title(title):
        return None

    if _IS_A_DISC.search(_marc_extent(fields) or ""):
        return None

    isbn = isbn or _marc_isbn(fields)
    subjects, gnd = _dnb_subjects(fields)

    return Record(
        source=source,
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=_marc_authors(fields) or _marc_credited_names(fields),
        publisher=_marc_publisher(fields),
        year=_marc_year(fields),
        # Through the shared reader rather than hardcoded to None, which is
        # what this was under Dublin Core. The DNB catalogues books rather than
        # blurbs and it shows: 520 appears on 1 of 85 live records measured
        # 2026-08-24. Reading it costs a function call and stops being a
        # special case that has to be remembered.
        description=_marc_description(fields),
        language=_marc_language(fields),
        page_count=_pages_from_extent(_marc_extent(fields)),
        # No cover in a MARC record. Open Library serves one by ISBN for a good
        # number of German books even where it has no edition record, so it is
        # worth the guess. Built by covers.py, which is the only module allowed
        # to know an image host: see COVER_HOSTS, which the CSP is derived from.
        cover_url=covers.open_library_url(isbn) if isbn else None,
        # 245 `$n` and `$p`, the same volume statement K10plus is read for. The
        # Dublin Core parser had no series at all: the part designation was
        # inside the title statement and there was no honest way to tell it
        # from a subtitle.
        series_name=series_name,
        series_index=series_index,
        subjects=tuple(subjects),
        headings=tuple(_marc_ddc(fields) + gnd),
        # The one catalogue here that supplies a person's identifier. K10plus
        # writes the same subfield and is deliberately not read for it: see
        # `_k10plus_record`. The ÖNB writes it too and is held to the same
        # rule: see `read_author_identifiers`.
        author_identifiers=(
            tuple(_marc_author_identifiers(fields)) if read_author_identifiers else ()
        ),
    )


#: How many records the lookup asks for, where it asked for one until
#: 2026-08-24. **The extra four are what let the print edition win.** `num=`
#: matches any identifier anywhere in a record, including the "also published
#: as" cross reference an ebook record carries for its print edition, so the
#: catalogue's first answer for a printed book's ISBN is sometimes the ebook.
#: Under Dublin Core there was no way to tell: `dc:format` is absent on an
#: online record, so `_is_physical_book` had nothing to test and the ebook was
#: taken. Measured over 74 live lookups on 2026-08-24: 8 answers held more than
#: one record, and asking for five rather than one puts a printed edition in
#: front of an online one twice and changes no other pick.
#:
#: Five, the same number `_K10PLUS_RECORDS` uses, for the same reason: several
#: printings of one book each carry the ISBN somewhere, and the best of them
#: should win rather than whichever the catalogue happened to sort first.
_DNB_RECORDS: Final = 5


async def _dnb(isbn: str, api_key: str) -> Lookup:
    del api_key  # The public SRU endpoint needs none.

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": f"num={isbn}",
        "recordSchema": "MARC21-xml",
        "maximumRecords": str(_DNB_RECORDS),
    }
    try:
        response = await fetch.get_once(_DNB_URL, params=params)
        if response.status_code == 429:
            return Lookup(Outcome.RATE_LIMITED, source="dnb")
        if response.status_code != 200:
            return Lookup(Outcome.UNAVAILABLE, source="dnb")
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("DNB lookup failed for %s", isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="dnb")

    books = [
        (fields, record)
        for fields in (_marc_fields(node) for node in root.iter(f"{_MARC}record"))
        for record in [_dnb_record(fields, isbn)]
        if record is not None
    ]
    if not books:
        logger.info("DNB matched %s only as a cross reference or a non-book", isbn)
        return Lookup(Outcome.NOT_FOUND, source="dnb")

    # Three questions, in the order they decide. Does the record name this
    # ISBN in its own 020, which separates the book from the cross references
    # `num=` also matches. Is it something that can sit on a shelf, so a
    # printed edition beats the ebook that shares its ISBN in a note. And is
    # it the fullest, which is the same tie-break `_merge` uses between
    # catalogues. `sorted` is stable, so records that tie on all three keep the
    # catalogue's own order and the first answer wins, which is what asking for
    # a single record used to give.
    ranked = sorted(
        books,
        key=lambda pair: (
            _marc_claims_isbn(pair[0], isbn),
            _is_physical_book(_marc_extent(pair[0]), pair[1].title),
            pair[1].completeness,
        ),
        reverse=True,
    )
    return Lookup(Outcome.FOUND, source="dnb", record=ranked[0][1])


# ── K10plus ───────────────────────────────────────────────────────────────────
#
# The union catalogue of the German library networks (GBV and SWB), roughly 200
# million records. It earns its place by being broad rather than national: it
# holds what German libraries hold, which is a large slice of English, French
# and Italian publishing alongside everything German.
#
# Measured over ten ISBNs spanning five languages: 6 hits, 3.5 of 5 fields per
# hit, 0.36s average. Open Library was broader (9 hits) but thinner (2.7) and
# five times slower (1.64s, one case over 3s). See `sources.DEFAULT_ORDER`
# for what that ranking bought.
#
# Free, no key, no registration. MARCXML rather than Dublin Core because the
# subfield structure is what makes the ISBN check below possible at all.

_K10PLUS_URL: Final = "https://sru.k10plus.de/opac-de-627"

#: Several printings of one book each carry the same ISBN, so the search
#: returns a handful of near-identical records and the fullest one wins.
_K10PLUS_RECORDS: Final = 5

#: MARC relator codes for somebody who wrote the thing. Translators (`trl`) and
#: editors (`edt`) arrive in the same field and must not become the author.
_AUTHOR_RELATORS: Final = ("aut", "cre")


def _marc_claims_isbn(fields: dict[str, list[_Subfields]], isbn: str) -> bool:
    """Whether 020 names this book, rather than merely mentioning it.

    Two traps, both hit on real records:

    * A subfield `q` is a qualifier such as "amerik. Original" or "Hardback".
      The first is a **cross reference to a different edition**, and taking it
      as a match returned a Ukrainian translation of Dune for the American
      ISBN. Qualified entries are therefore not accepted as identity.
    * 020 often holds the **ISBN-10** even when the search was by ISBN-13, so
      both sides are canonicalised rather than compared as strings.
    """
    for entry in fields.get("020", []):
        if "q" in entry:
            continue
        if parse_isbn(entry.get("a", "")) == isbn:
            return True
    return False


#: What a catalogue hangs off a person's name. The BnF writes
#: `Zafón, Carlos (1964-2020). Auteur du texte`; MARC and MODS write
#: `Melville, Herman, 1819-1891`. None of it is part of the name.
_PERSON_NOISE: Final = re.compile(
    r"\s*\(\s*\d{3,4}\s*[-–]?\s*\d{0,4}\s*\)"  # (1964-2020)
    r"|\s*\.\s*(Auteur|Autrice|Éditeur|Editeur|Traducteur|Traductrice|"
    r"Illustrateur|Illustratrice|Préfacier|Compilateur)[^.]*\.?\s*$"
    r"|,\s*\d{4}\s*[-–]\s*\d{0,4}\s*$",  # , 1819-1891
    re.IGNORECASE,
)

#: BnF role markers for somebody who wrote the thing. A record with no marker
#: at all is the main entry and is kept.
_BNF_AUTHOR_ROLES: Final = ("auteur", "autrice", "author")

#: Every role marker the BnF uses, so "has a role but not an author one" can be
#: told apart from "has no role".
_BNF_ANY_ROLE: Final = re.compile(
    r"\.\s*(Auteur|Autrice|Éditeur|Editeur|Traducteur|Traductrice|Illustrateur|"
    r"Illustratrice|Préfacier|Compilateur|Author|Editor|Translator)",
    re.IGNORECASE,
)


#: A trailing initial, which is the one full stop in a name that is part of it.
#: `Pohl, Robert O.` loses its meaning as `Robert O`, and the ISBD full stop
#: this strips off `Melville, Herman.` looks exactly the same to a regex.
#: Measured: 2 of 53 live DNB records credit an author with a trailing initial.
_TRAILING_INITIAL: Final = re.compile(r"(?:^|[\s.])[A-Za-z]\.$")


def _strip_person_noise(raw: str) -> str:
    """Drop life dates and role words from a catalogue person string."""
    cleaned = raw
    for _ in range(3):  # A name can carry both, in either order.
        stripped = _PERSON_NOISE.sub("", cleaned).strip().rstrip(",;")
        if stripped.endswith(".") and not _TRAILING_INITIAL.search(stripped):
            stripped = stripped[:-1].strip()
        if stripped == cleaned:
            break
        cleaned = stripped
    return cleaned


def _flip_catalogue_name(raw: str) -> str:
    """`Williams, John` becomes `John Williams`.

    One comma means a person in catalogue order. None, or more than one, means
    something else (a corporate body, a compound credit) and is left alone.
    """
    name = _strip_person_noise(raw.strip()).rstrip(",")
    if name.count(",") != 1:
        return name
    surname, forenames = (part.strip() for part in name.split(","))
    return f"{forenames} {surname}" if surname and forenames else name


def _marc_author_entries(
    fields: dict[str, list[_Subfields]],
) -> list[tuple[str, _Subfields]]:
    """The 100 main entry plus any 700 that actually wrote something, with its field.

    **The field is returned beside the name so that the credit line and the
    authority identifiers cannot be built from two different sets of people.**
    `_marc_authors` joins the names and `_marc_author_identifiers` reads `$0`
    off the same entries, so every identifier this module produces is filed
    under a spelling that is in this record's own `author` string. Two loops
    testing the same three conditions would make that alignment a comment, and a
    comment is what would drift the day a relator code is added to one of them.

    Order preserved, repeats dropped: 100 and 700 can name the same person, and
    the first field naming them is the one whose `$0` is read.
    """
    entries: list[tuple[str, _Subfields]] = []
    for entry in fields.get("100", []):
        if entry.get("a"):
            entries.append((_flip_catalogue_name(entry["a"]), entry))
    for entry in fields.get("700", []):
        # `t` marks an added entry for a *work*, not a person: the row exists
        # to link the original title, and its name is the original author's.
        if entry.get("a") and "t" not in entry and entry.get("4") in _AUTHOR_RELATORS:
            entries.append((_flip_catalogue_name(entry["a"]), entry))
    seen: dict[str, _Subfields] = {}
    for name, entry in entries:
        seen.setdefault(name, entry)
    return list(seen.items())


def _marc_authors(fields: dict[str, list[_Subfields]]) -> str | None:
    """The 100 main entry plus any 700 that actually wrote something."""
    return ", ".join(name for name, _ in _marc_author_entries(fields)) or None


def _marc_author_identifiers(
    fields: dict[str, list[_Subfields]],
) -> list[AuthorityAssertion]:
    """Which GND record each credited author is, where the record says so.

    **The same `$0` `_gnd_identifier` reads for a subject heading, in a field
    that means something else.** 600 says a person is what the book is *about*
    and 100 says they wrote it, so the identifier is the same kind of string
    with a different subject, and the two go to different stores. See
    `enums.AuthorityScheme`.

    **A record with no `$0` is ordinary rather than broken**: 21 of 73 live 100
    fields carry no `(DE-588)` at all, measured over 85 records on 2026-08-24,
    which is the same measurement `_gnd_identifier` records.

    Nothing here decides whether the assertion is trustworthy. That is the
    path's question and not the parser's, and `catalogue.AuthorityAssertion`
    says why it cannot be answered here.
    """
    return [
        AuthorityAssertion(name, AuthorityScheme.GND, number)
        for name, entry in _marc_author_entries(fields)
        if (number := _gnd_identifier(entry)) is not None
    ]


def _marc_credited_names(fields: dict[str, list[_Subfields]]) -> str | None:
    """Every person the record names, whatever role it gives them.

    **The fallback for a record that credits nobody with writing the book**,
    which is what an edited volume looks like in MARC: no 100 at all, and the
    editors in 700 with `$4=edt`. `_marc_authors` answers None there, and
    naming the editors beats naming nobody, which is the same call the Dublin
    Core parser made when no `dc:creator` carried `[Verfasser]`.

    Measured over 74 live DNB lookups on 2026-08-24: without this, 8 of the 53
    that still return a record lose an author the Dublin Core path answers with
    today.

    Used only where `_marc_authors` came back empty. Reading it first would put
    a translator in the credit line of every book that has one.
    """
    names: dict[str, None] = {}
    for tag in ("100", "700"):
        for entry in fields.get(tag, []):
            # `$t` marks an added entry for a *work* rather than a person: the
            # row links the original title and carries its author's name.
            if entry.get("a") and "t" not in entry:
                names.setdefault(_flip_catalogue_name(entry["a"]), None)
    return ", ".join(names) or None


def _marc_title(entry: _Subfields) -> tuple[str, str | None, str | None, float | None]:
    """A 245 field as title, subtitle, series name and series number.

    `$n` and `$p` are the part designation and part title, which is how a
    catalogue records a numbered volume: `$a=Harry Potter`, `$n=[1]`,
    `$p=Harry Potter and the philosopher's stone`. The part title is the book
    somebody is holding, so it becomes the title, and the collective title
    becomes the series. Without this the whole series is catalogued seven times
    under one name.

    **A subfield that was never split gets split here.** An older record puts
    the whole statement in one subfield, subtitle and statement of
    responsibility and all: DNB record 900329866 (ISBN 9783442002009) reads
    `$p=Der Zinker : Kriminalroman / [aus d. Engl. übertr. von Gregor Müller]`.
    Taking it whole puts a translator credit in the title, which is what the
    Dublin Core parser existed to prevent, so where MARC supplied no `$b` the
    title goes through the same splitter. Only where there is no `$b`: a record
    that did subfield itself has already answered this question, and a title
    with a colon in it is then the title.
    """
    main = _strip_marc_punctuation(entry.get("a", ""))
    part_title = _strip_marc_punctuation(entry.get("p", ""))
    subtitle = _strip_marc_punctuation(entry.get("b", "")) or None

    series_name: str | None = None
    series_index: float | None = None
    if part_title:
        series_name = main or None
        number = re.search(r"\d+", entry.get("n", ""))
        series_index = float(number.group()) if number else None
        title = part_title
    else:
        title = main

    if subtitle is None:
        title, subtitle = _dc_title_statement(title)

    return _fix_non_filing_space(title), subtitle, series_name, series_index


def _strip_marc_punctuation(raw: str) -> str:
    """Drop the ISBD punctuation that introduces the *next* subfield.

    Catalogue records end a subfield with the separator for the one after it,
    so `$a` reads `Stoner :` when a subtitle follows. Leaving it in puts a
    stray colon at the end of half the titles in the library.
    """
    return raw.strip().rstrip("/:;,=").strip()


def _fix_non_filing_space(title: str) -> str:
    """`L' étranger` becomes `L'étranger`.

    MARC records put the space after an elided article so that sorting can skip
    it. It is a filing device, not how the title is printed.
    """
    return re.sub(r"(\w')\s+(\w)", r"\1\2", title)


def _marc_year(fields: dict[str, list[_Subfields]]) -> int | None:
    """The publication year, from 264 or the older 260.

    `$c` is free text and really does arrive as `2000 (copyright)`, so the
    first four-digit run is taken rather than the whole field.
    """
    for tag in ("264", "260"):
        for entry in fields.get(tag, []):
            match = re.search(r"\d{4}", entry.get("c", ""))
            if match:
                return int(match.group())
    return None


async def _k10plus(isbn: str, api_key: str) -> Lookup:
    del api_key  # Free, and no registration to have a key from.

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": f"pica.isb={isbn}",
        "recordSchema": "marcxml",
        "maximumRecords": str(_K10PLUS_RECORDS),
    }
    try:
        response = await fetch.get_once(_K10PLUS_URL, params=params)
        if response.status_code == 429:
            return Lookup(Outcome.RATE_LIMITED, source="k10plus")
        if response.status_code != 200:
            return Lookup(Outcome.UNAVAILABLE, source="k10plus")
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("K10plus lookup failed for %s", isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="k10plus")

    candidates = [
        record
        for record in (_marc_fields(node) for node in root.iter(f"{_MARC}record"))
        if _marc_claims_isbn(record, isbn)
    ]
    if not candidates:
        return Lookup(Outcome.NOT_FOUND, source="k10plus")

    records = [_k10plus_record(fields, isbn) for fields in candidates]
    return Lookup(
        Outcome.FOUND,
        source="k10plus",
        record=max(records, key=lambda record: record.completeness),
    )


def _marc_publisher(fields: dict[str, list[_Subfields]]) -> str | None:
    """The publisher, from the RDA 264 or the older 260."""
    return next(
        (
            entry["b"].rstrip(",")
            for tag in ("264", "260")
            for entry in fields.get(tag, [])
            if entry.get("b")
        ),
        None,
    )


def _marc_language(fields: dict[str, list[_Subfields]]) -> str | None:
    """The first 041 code this app has a two letter equivalent for."""
    for entry in fields.get("041", []):
        language = _LANGUAGES.get(entry.get("a", "").lower())
        if language:
            return language
    return None


def _marc_extent(fields: dict[str, list[_Subfields]]) -> str | None:
    """300 `$a`: the page count, and whether this is a book at all.

    Two readers, and they are not the same question: `_pages_from_extent`
    wants the number, `_is_physical_book` wants to know whether the string
    says "Online-Ressource".
    """
    return next((entry.get("a") for entry in fields.get("300", [])), None)


def _marc_description(fields: dict[str, list[_Subfields]]) -> str | None:
    """520 `$a`, the summary note, on the rare record that carries one."""
    return next((entry["a"] for entry in fields.get("520", []) if entry.get("a")), None)


def _marc_ddc(fields: dict[str, list[_Subfields]]) -> list[Heading]:
    """082 as Dewey headings, and the one field this module hands to `ddc`.

    082 is the Dewey number and normally nothing else: MARC carries the
    notation and the printed schedule carries the caption, so the label is
    usually null rather than filled in from our own mapping. A record often
    holds two numbers at different precisions (`005.133` and `004`, measured
    2026-08-23), and both are kept: they are two catalogues' answers, not a
    duplicate.

    Through `ddc.parse_heading` like every other source path, which is what
    strips MARC's segmentation prime: 53 of 463 live K10plus `$a` values
    (11.4%, measured 2026-08-23) arrive as `005.13/3` where the DNB stores
    `005.133`, and storing both spellings makes two rows out of one heading
    that `uq_classifications_book_scheme_number` cannot collapse.

    **Every `$a` in the field, not the first.** The DNB writes the Dewey
    number and its own Sachgruppe letter into one 082 (`$a=830 $a=B`, 10 of 85
    live records measured 2026-08-24). The letter is not a Dewey number and
    `parse_heading` drops it; reading a single `$a` would drop the number
    instead on whichever of the two came second.
    """
    return [
        Heading(ClassificationScheme.DDC, number, label)
        for entry in fields.get("082", [])
        for value in entry.all("a")
        for heading in [ddc.parse_heading(value)]
        if heading is not None
        for number, label in [heading]
    ]


def _marc_isbn(fields: dict[str, list[_Subfields]]) -> str | None:
    """The record's own ISBN, ignoring cross references to other editions."""
    for entry in fields.get("020", []):
        if "q" in entry:
            continue
        parsed = parse_isbn(entry.get("a", ""))
        if parsed is not None:
            return parsed
    return None


def _k10plus_record(
    fields: dict[str, list[_Subfields]], isbn: str | None = None
) -> Record:
    """One MARC record as book fields.

    `isbn` is passed by the lookup path, where it is already known and already
    verified. The search path has none, so it is read off 020 instead.
    """
    isbn = isbn or _marc_isbn(fields)
    title_entry = (fields.get("245") or [_Subfields(())])[0]
    title, subtitle, series_name, series_index = _marc_title(title_entry)

    subjects = [
        " ".join(part for part in (entry.get("a"), entry.get("x")) if part)
        for entry in fields.get("650", [])
        if entry.get("a")
    ]

    return Record(
        source="k10plus",
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=_marc_authors(fields),
        publisher=_marc_publisher(fields),
        year=_marc_year(fields),
        description=_marc_description(fields),
        language=_marc_language(fields),
        page_count=_pages_from_extent(_marc_extent(fields)),
        series_name=series_name,
        series_index=series_index,
        # No cover in a MARC record. The Open Library cover service answers by
        # ISBN for a good number of these anyway. A record with no ISBN at all,
        # which is most pre-1970 printings, gets none.
        cover_url=covers.open_library_url(isbn) if isbn else None,
        subjects=tuple(subjects),
        # K10plus is not read for GND identifiers, though its records carry
        # them in the same `$0`. Doing that is a second catalogue's worth of
        # live comparison and belongs in its own round, not as a side effect of
        # the DNB's. **That covers a person's identifier too**, which is why
        # this record sets no `author_identifiers`: the same subfield on `100`
        # would file an author under a GND number nothing here has checked
        # against a live K10plus record.
        headings=tuple(_marc_ddc(fields)),
    )


# ── The Austrian National Library ─────────────────────────────────────────────
#
# The Österreichische Nationalbibliothek, through the Alma SRU interface the
# Austrian library network publishes. CQL in, MARCXML out, no key, metadata
# under CC0.
#
# **This is the catalogue interface and not `api.onb.ac.at`.** That one is the
# IIIF digital collections API: image tiles, manifests, OCR and files. A reader
# looking for "the ÖNB API" finds it first and it holds no catalogue records.
#
# **Why it is a fallback rather than a fifth fast source.** 50 ISBNs, five each
# from ten Austrian imprints, taken off live ÖNB records printed after 2005 and
# put to all three catalogues on 2026-08-27: ÖNB held 50, the DNB 47, K10plus
# 39, and **3 of the 50 were held by ÖNB and by neither of the German pair**.
# 6% is worth a request that costs nothing when the fast pair answers.
#
# **The second half of that argument is superseded too, and separately.** It also
# said 3 of 50 was not worth widening the pair everybody pays for, which is the
# `ALWAYS_ASKED` question, and that is now settled on a wider measurement: a
# third concurrent slot answers 2 more books of 500 and costs half again as many
# outbound requests. See `sources.ALWAYS_ASKED` and `sources.TIER_UNION`. This
# block supersedes cleanly in two directions and it is worth saying which,
# because the order it justified and the tier size it justified were replaced by
# different evidence.
#
# **Read that sample for how it was drawn, because the drawing decides which of
# its two numbers means anything.** Every ISBN came off a live ÖNB record, so
# the 50 of 50 is true by construction and is not evidence about what the ÖNB
# holds. The 3 of 50 is evidence, and it is a floor: ten well known presses lean
# towards the books the German catalogues are most likely to hold too.
#
# **The order it was used to justify is superseded.** This sample also put the
# ÖNB ahead of Open Library in the fallback tier, and #115 reversed that on a
# wider one. The measurement, the frames and the reason are in the chain comment
# below and in `sources.DEFAULT_ORDER`, and are not repeated here.
#
# Mean lookup latency over that sample: DNB 0.210s, ÖNB 0.240s, K10plus 0.390s.
# Superseded as a ranking by `sources.MEASURED`, which times all four free
# sources on one 500 ISBN sample rather than three of them on this one.

_OENB_URL: Final = "https://obv-at-oenb.alma.exlibrisgroup.com/view/sru/43ACC_ONB"

#: The CQL index that means "the ISBN", **established by probing rather than by
#: reading the documentation**, and it is the single fact this source was
#: blocked on.
#:
#: The published examples establish MMS ID, AC number, barcode and title, and
#: none of them establish this. Guessing it does not fail the way a wrong index
#: name usually fails. Measured live on 2026-08-27 against the same ISBN:
#:
#: | query | numberOfRecords |
#: |---|---|
#: | `alma.isbn=9783825354077` | 1 |
#: | `alma.isbn13=9783825354077` | **7,793,152** |
#: | `zzz.qqq=9783825354077` | **7,793,152** |
#:
#: **An unknown index is not an error.** It is HTTP 200, no diagnostic, and the
#: entire catalogue in catalogue order, of which `maximumRecords` arbitrary
#: records come back. So a typo here ships plausible MARC for an unrelated
#: book rather than an empty result somebody would notice, and the only thing
#: standing between that and a member's shelf is `_marc_claims_isbn` below.
#:
#: Confirmed the only way it can be: an ISBN was read off a live ÖNB record's
#: own 020 and put back through this index, returning exactly that record.
_OENB_ISBN_INDEX: Final = "alma.isbn"

#: The CQL index for a title word. `alma.title`, from the same explain record,
#: and verified live.
#:
#: **One term per index reference, ANDed**, which is the shape `_k10plus_search`
#: already uses and here it is a hard requirement rather than a precision
#: preference: a bare multi-word term is refused. Measured, `alma.title=wien
#: geschichte` answers 200 with SRU diagnostic 200812 `Invalid query`, where
#: `alma.title=wien and alma.title=geschichte` answers with 4,885 records.
_OENB_TITLE_INDEX: Final = "alma.title"

#: Five, for the same reason `_DNB_RECORDS` and `_K10PLUS_RECORDS` are five:
#: several printings of one book each carry the ISBN somewhere and the fullest
#: of them should win rather than whichever the catalogue sorted first.
_OENB_RECORDS: Final = 5

#: MARC leader/07, the bibliographic level, for a record that is part of
#: something else rather than a thing on a shelf: `a` is a monographic
#: component part and `b` a serial component part.
#:
#: **These two, because these are the levels the sample actually held.** The 280
#: records measured on 2026-08-27 carried `a` (155), `m` (122) and `c` (3), so
#: `b` is here on the MARC definition rather than on evidence and nothing else
#: is here at all. A later live page turned up one `s`, a serial, which is
#: neither a component part nor a book: it is **not** refused, because refusing
#: serials is a decision about what this app catalogues rather than a correction
#: to this one, and widening a frozenset is the quietest possible place to take
#: a decision like that.
#:
#: **Over half of what an ÖNB title search returns is one of these**, and
#: nothing already here catches them. Measured over 8 title searches on
#: 2026-08-27, 280 records: 155 (55.4%) are level `a`, journal articles and
#: book chapters with a 773 host item entry and usually no 300 extent at all.
#: `_is_physical_book` tests the extent for an online form and the title for a
#: volume slot, and an absent extent passes both, so every one of the 155 would
#: have reached the picker as a book.
#:
#: **The leader decides rather than the 773**, and the difference was measured
#: on the same 280 records: the leader catches 155 of 155 and loses **0** of
#: the 122 monographs, where refusing anything carrying a 773 catches the same
#: 155 and loses 3 monographs that carry a host entry legitimately.
_COMPONENT_PART_LEVELS: Final = frozenset({"a", "b"})


def _is_component_part(record: ElementTree.Element) -> bool:
    """Whether this MARC record describes an article or a chapter.

    Reads the leader off the record node, because `_marc_fields` maps
    `datafield` only and the leader is neither a datafield nor a controlfield.
    Kept here rather than added to that map: one source needs it, and widening
    the shared shape for one caller is how a field map grows keys nobody reads.

    A leader shorter than eight characters is not a component part. A truncated
    leader is a broken record rather than an article, and the fields below
    decide it on their own merits.
    """
    leader = record.findtext(f"{_MARC}leader") or ""
    return len(leader) > 7 and leader[7] in _COMPONENT_PART_LEVELS


def _oenb_records(root: ElementTree.Element) -> list[ElementTree.Element]:
    """Every MARC record in an ÖNB response that describes a whole publication.

    **An SRU diagnostic needs no branch of its own here**, which is worth
    saying because the endpoint answers every error with HTTP 200. An invalid
    query and an unsupported one both come back as a well formed
    `searchRetrieveResponse` carrying a `diag:diagnostic` and no records, so the
    body parses, this returns nothing, and the source reports no results, which
    is what it should do. `test_metadata.py` pins that with a recorded
    diagnostic rather than leaving it to be rediscovered.
    """
    return [
        record
        for record in root.iter(f"{_MARC}record")
        if not _is_component_part(record)
    ]


async def _oenb(isbn: str, api_key: str) -> Lookup:
    del api_key  # Free, CC0, and no registration to have a key from.

    params = {
        "version": "1.2",
        "operation": "searchRetrieve",
        "query": f"{_OENB_ISBN_INDEX}={isbn}",
        "recordSchema": "marcxml",
        "maximumRecords": str(_OENB_RECORDS),
    }
    try:
        response = await fetch.get_once(_OENB_URL, params=params)
        if response.status_code == 429:
            return Lookup(Outcome.RATE_LIMITED, source="oenb")
        if response.status_code != 200:
            return Lookup(Outcome.UNAVAILABLE, source="oenb")
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("ÖNB lookup failed for %s", isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="oenb")

    # **`_marc_claims_isbn` is not a tidy extra check on this source, it is the
    # whole defence.** A mistyped index name answers with the entire catalogue
    # rather than with nothing, so without this a future edit to
    # `_OENB_ISBN_INDEX` would answer a member's scan with an arbitrary record
    # that parses perfectly. See that constant.
    records = [
        fields
        for fields in (_marc_fields(node) for node in _oenb_records(root))
        if _marc_claims_isbn(fields, isbn)
    ]
    parsed = [
        record
        for fields in records
        for record in [_dnb_record(fields, isbn, source="oenb", read_author_identifiers=False)]
        if record is not None
    ]
    if not parsed:
        return Lookup(Outcome.NOT_FOUND, source="oenb")

    return Lookup(
        Outcome.FOUND,
        source="oenb",
        record=max(parsed, key=lambda record: record.completeness),
    )


async def _oenb_search(query: str, limit: int) -> list[Record]:
    """The ÖNB, one ANDed title term per word.

    Not the catch-all `alma.all_for_ui`, which is the same choice
    `_k10plus_search` made and for a sharper reason here: measured 2026-08-27,
    ANDing "wien" and "geschichte" over the title index returns 4,885 records
    where the same pair over the keyword index returns 65,872.
    """
    terms = _search_terms(query)
    if not terms:
        return []

    cql = " and ".join(f"{_OENB_TITLE_INDEX}={term}" for term in terms)
    params = {
        "version": "1.2",
        "operation": "searchRetrieve",
        "query": cql,
        "recordSchema": "marcxml",
        # More than asked for, because the ordering is the catalogue's and the
        # ranking is ours. The endpoint clamps this at 50 silently: asking for
        # 100 or 200 returns 50 records with no diagnostic, measured.
        "maximumRecords": str(min(limit * 3, 50)),
    }
    try:
        response = await fetch.get_once(_OENB_URL, params=params)
        if response.status_code != 200:
            return []
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("ÖNB search failed for %r", query, exc_info=True)
        return []

    results: list[Record] = []
    for node in _oenb_records(root):
        fields = _marc_fields(node)
        record = _dnb_record(
            fields, isbn=None, source="oenb", read_author_identifiers=False
        )
        if record is None or not _is_physical_book(
            _marc_extent(fields), record.title
        ):
            continue
        results.append(record)
    return results


# ── The chain ─────────────────────────────────────────────────────────────────
#
# Ranked by measurement, not reputation. Ten ISBNs across five languages, each
# put to every free catalogue, scoring whether a record came back and how many
# of author, year, page count, description and subjects it carried:
#
#   | source       | hits  | fields per hit | mean latency |
#   |--------------|-------|----------------|--------------|
#   | open_library | 9/10  | 2.7 / 5        | 1.64s        |
#   | k10plus      | 6/10  | 3.5 / 5        | 0.36s        |
#   | dnb          | 5/10  | 3.8 / 5        | 0.11s        |
#   | loc          | 2/10  | 4.0 / 5        | 0.28s        |
#
# Three conclusions, and they are what this code is shaped by.
#
# **Open Library is the broadest and the worst.** It answered nine times and
# each answer was thin, and it is five times slower than anything else, with
# one lookup over three seconds. It belongs in the chain and it does not
# belong first, which is where it used to be for every non-German ISBN.
#
# **The two catalogues that were fast were also the most complete**, and they
# miss different books: the DNB is the German legal deposit library, K10plus is
# what German libraries collectively hold, which is most of English, French and
# Italian publishing too. Asking both costs 0.4s of wall clock because they run
# together, and produces a fuller record than either alone.
#
# **The Library of Congress is not worth an ISBN request.** Two hits in ten, and
# both were covered by something else. It is kept for title search, where it is
# the best free source for a book printed before ISBNs existed.
#
# **ÖNB is not in that table and deliberately not added to it**, because it was
# measured on a different sample and a row carrying a figure from somewhere else
# is worse than no row. Where it sits and why is `sources.DEFAULT_ORDER`, which
# carries the measurement.
#
# **Its old figures measured a different population, and the ÖNB block above
# records which.** They were 50 Austrian imprint ISBNs on 2026-08-27: the ÖNB
# answered 50 of 50 against the DNB's 47 and K10plus's 39, and held 3 the German
# pair both missed. **Every one of those ISBNs was taken off a live ÖNB
# record**, so the 50 of 50 is true by construction. #115 drew a fresh Austrian
# sample on 2026-08-30, 50 ISBNs from Wikidata by publisher country, and got 22,
# 39 and 25, with the ÖNB holding **1** of the 7 the German pair missed and
# Open Library holding **2**. The two do not disagree: one is drawn from books
# the ÖNB holds and the other from books Austrian publishers published, and
# only the second can answer how often the ÖNB answers where the German pair
# did not, which is the question the fallback order turns on.
#
# **What this chain covers without a Google Books key, which is what a default
# install runs.** Google Books needs one (`sources.NEEDS_A_KEY`) and most
# installations have none, so the chain most deployments actually run is the
# four free sources. Measured 2026-08-30 over 500 domestic ISBNs across ten
# frames: the free four answer 300 and miss 200, and outside German language
# publishing they miss 196 of 400. So a sentence anywhere in this module saying
# the chain covers a country is a statement about a **keyed** install. #91
# measured the size of that on the same books, Italy 36% missed keyless against
# 0% with a key and Greece 86% against 54%; **that keyed half is #91's
# measurement and is not re-derived here**, because the seat that wrote this had
# no key. The per source figures and the frames: `sources.MEASURED`.

#: Every source that can answer an **ISBN**, by name. BNF and LOC are absent
#: because neither was worth an ISBN request; they answer title search only.
#:
#: **Keyed on the enum, and `sources.LOOKUP_SOURCES` must name exactly these
#: five.** `TestTheProviderRosterIsOneList` asserts it rather than a comment
#: claiming it, because a source added to one and not the other is a `KeyError`
#: on the path that adds a book.
_SOURCES: Final[dict[CatalogueSource, Callable[[str, str], Awaitable[Lookup]]]] = {
    CatalogueSource.OPEN_LIBRARY: _open_library,
    CatalogueSource.GOOGLE_BOOKS: _google_books,
    CatalogueSource.DNB: _dnb,
    CatalogueSource.K10PLUS: _k10plus,
    CatalogueSource.OENB: _oenb,
}

#: Bookland registration group for German-language publishing.
_GERMAN_PREFIX: Final = "9783"

#: Which of the fast pair to believe when both answer and they disagree.
#:
#: For a German ISBN the legal deposit library is the authority on its own
#: publishing. For anything else K10plus is preferred: it holds foreign books
#: as first-class records, where the DNB holds them mostly as cross references,
#: which is the failure `_is_placeholder_title` exists to catch.
def _preferred_source(isbn: str) -> str:
    return "dnb" if isbn.startswith(_GERMAN_PREFIX) else "k10plus"


def _merge(records: list[Record], isbn: str) -> Record:
    """Fold several catalogues' answers into one record.

    Taking the first hit and stopping is what the chain used to do, and it left
    fields empty that the next source down would have filled: K10plus carries
    page counts and series numbering, the DNB carries subject headings, and
    neither reliably carries a blurb. `Record.merged_with` holds the rule:
    nothing is overwritten, only filled in, so the leading source stays the one
    describing the book, and both catalogues' subjects and headings are kept.

    What is decided **here** is only which record leads, because that is the one
    thing that depends on the ISBN rather than on the records.
    """
    preferred = _preferred_source(isbn)
    ordered = sorted(
        records,
        key=lambda record: (record.source == preferred, record.completeness),
        reverse=True,
    )
    return functools.reduce(lambda merged, other: merged.merged_with(other), ordered)


# ── Title search ──────────────────────────────────────────────────────────────
#
# The other half of getting a book in: no barcode to scan, a damaged one, or a
# book printed before ISBNs existed at all. Until recently this was Google
# Books only, which meant a library without an API key had **no way** to add
# a book by title, and the search box was hidden from them entirely.
#
# All three free catalogues answer here, and getting the German pair to be
# useful was a question of asking properly. A first attempt sent the whole
# phrase to K10plus's catch-all index and got a Russian translation, an online
# resource and a theatre programme leaflet, which read as a noisy source. It
# was a bad query: the words have to be **ANDed term by term**, and once they
# are, "clean code martin" narrows from tens of thousands of records to eighty,
# and "zauberberg mann" returns the right novel at the top.
#
# So the shape here is: ask everything that is free, filter what is not a book,
# score what is left against the query, and merge. What each source is for:
#
#   open_library  breadth and ranking, plus a cover image per row
#   k10plus       German and European publishing, and pre-ISBN printings
#   dnb           German legal deposit, precise: `WOE=clean code martin` is
#                 one record
#   google_books  the blurb and the categories, when a key is configured
#
# The catalogues return **catalogue order, not relevance order**, so their
# ranking cannot be trusted and is replaced by `_relevance` below. That is the
# piece doing the real work: without it a precise query still puts an obscure
# 1974 reprint above the edition somebody is holding.

_OPEN_LIBRARY_SEARCH: Final = f"{_OPEN_LIBRARY}/search.json"

#: Only what is used. The default response carries a hundred fields per row.
_OPEN_LIBRARY_SEARCH_FIELDS: Final = ",".join(
    (
        "title",
        "subtitle",
        "author_name",
        "first_publish_year",
        "isbn",
        "number_of_pages_median",
        "cover_i",
        "language",
        "publisher",
    )
)


def _first_isbn13(candidates: list[str]) -> str | None:
    """The first entry that is a real ISBN, canonicalised.

    Open Library lists every ISBN of every printing it has merged into one
    work, in no particular order, and some of them are not valid at all.
    """
    for candidate in candidates:
        parsed = parse_isbn(candidate)
        if parsed is not None:
            return parsed
    return None


async def _open_library_search(query: str, limit: int) -> list[Record]:
    params = {
        "q": query,
        "limit": str(limit),
        "fields": _OPEN_LIBRARY_SEARCH_FIELDS,
    }
    try:
        response = await fetch.get_once(_OPEN_LIBRARY_SEARCH, params=params)
        if response.status_code != 200:
            logger.info("Open Library search returned %s", response.status_code)
            return []
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Open Library search failed for %r", query, exc_info=True)
        return []

    results: list[Record] = []
    for doc in payload.get("docs", [])[:limit]:
        cover_id = doc.get("cover_i")
        results.append(
            Record(
                source="open_library",
                title=doc.get("title"),
                subtitle=doc.get("subtitle"),
                # Every credited name, in order. Joined the same way the DNB
                # and K10plus parsers join theirs, so one book looks the same
                # whichever source found it.
                author=", ".join(doc.get("author_name") or []) or None,
                publisher=(doc.get("publisher") or [None])[0],
                year=doc.get("first_publish_year"),
                # The search index carries no blurb. Enrichment fills it in.
                page_count=doc.get("number_of_pages_median"),
                language=_LANGUAGES.get((doc.get("language") or [""])[0].lower()),
                # By Open Library's own cover id, which the search index
                # carries and which resolves where an ISBN lookup does not.
                cover_url=(
                    covers.open_library_id_url(cover_id) if cover_id else None
                ),
                isbn=_first_isbn13(doc.get("isbn") or []),
            )
        )
    return results


# ── The SRU search sources ────────────────────────────────────────────────────

#: CQL operators and punctuation. A query is user input and goes into a query
#: language, so the metacharacters come out rather than being escaped: there is
#: no book whose title depends on an unbalanced quote.
_CQL_UNSAFE: Final = re.compile(r'[=<>"()/\\]+')

#: CQL boolean keywords. A search for "black and white" must not become two
#: terms joined by an operator.
_CQL_KEYWORDS: Final = frozenset({"and", "or", "not", "prox"})

#: Below this a term is noise in a catalogue index: initials, articles, and the
#: single letters left behind by stripping punctuation.
_MIN_TERM_LENGTH: Final = 2


def _search_terms(query: str) -> list[str]:
    """The query as safe, meaningful, ANDable terms."""
    cleaned = _CQL_UNSAFE.sub(" ", query)
    return [
        term
        for term in cleaned.split()
        if len(term) >= _MIN_TERM_LENGTH and term.lower() not in _CQL_KEYWORDS
    ]


#: Extents that mean the record is not a physical book. A digitised copy of a
#: novel is a real catalogue record and a wrong answer to "which book am I
#: holding", and it is the single largest source of noise in both SRU sources.
#:
#: **Written as two halves on 2026-08-24, because the DNB lookup treats them
#: differently.** An online resource is this book in another form, and the DNB
#: answers with one for an ISBN whose printed record it also holds, so `_dnb`
#: ranks it below a physical record and takes it rather than reporting a miss.
#: A disc is a different object, so `_dnb_record` refuses it outright. Both
#: halves are still one refusal everywhere else, `_is_physical_book` being what
#: the search paths and K10plus ask.
_ONLINE_FORMS: Final = (
    r"online[- ]?(?:ressource|resource)|elektronische ressource|streaming"
)
_DISC_FORMS: Final = r"audio disc|sound (?:disc|recording)|videodisc|dvd|blu-?ray"

_NOT_A_BOOK: Final = re.compile(f"{_ONLINE_FORMS}|{_DISC_FORMS}", re.IGNORECASE)

_IS_A_DISC: Final = re.compile(_DISC_FORMS, re.IGNORECASE)


def _is_physical_book(extent: str | None, title: str | None) -> bool:
    """Whether a record describes something that can sit on a shelf.

    Both arguments are optional because a `Record`'s are: an untitled record is
    one a catalogue answered thinly, not one naming a volume slot, so it fails
    the placeholder test rather than passing it.
    """
    if extent and _NOT_A_BOOK.search(extent):
        return False
    return not _is_placeholder_title(title or "")


async def _k10plus_search(query: str, limit: int) -> list[Record]:
    """K10plus, one ANDed term per word.

    `pica.all=zauberberg mann` is **not** the same query: the catch-all index
    treats the phrase loosely and returns anything sharing a word. ANDing the
    terms is what turns this from a noisy source into a precise one.
    """
    terms = _search_terms(query)
    if not terms:
        return []

    cql = " and ".join(f"pica.all={term}" for term in terms)
    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": cql,
        "recordSchema": "marcxml",
        # More than asked for, because the ordering is the catalogue's and the
        # ranking below is ours. Taking the first `limit` would be taking the
        # catalogue's opinion, which is the one we do not trust.
        "maximumRecords": str(min(limit * 3, 50)),
    }
    try:
        response = await fetch.get_once(_K10PLUS_URL, params=params)
        if response.status_code != 200:
            return []
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("K10plus search failed for %r", query, exc_info=True)
        return []

    results: list[Record] = []
    for node in root.iter(f"{_MARC}record"):
        fields = _marc_fields(node)
        record = _k10plus_record(fields)
        extent = _marc_extent(fields)
        if not record.title or not _is_physical_book(extent, record.title):
            continue
        results.append(record)
    return results


async def _dnb_search(query: str, limit: int) -> list[Record]:
    """The DNB, through its word-sequence index.

    `WOE` is the index that takes several words and requires all of them, which
    is what a typed search actually means. It is precise to the point of being
    narrow: "clean code martin" is one record.

    **MARC21 costs bandwidth here and it is the one place it is worth naming.**
    A full page of results is 438 to 588 KB against Dublin Core's 51 KB,
    measured on 2026-08-24 over four `WOE=` queries at the 50 record ceiling
    (`clean code` 437,805 bytes, `roman liebe` 449,535, `informatik grundlagen`
    440,115, `geschichte deutschland` 587,810), for 0.60s against 0.37s. It is
    paid on a typed search rather than on a scan, the responses are parsed and
    dropped rather than stored, and `docs/decisions.md` records that no
    catalogue response is size capped, which this makes worth revisiting sooner
    than it was.
    """
    terms = _search_terms(query)
    if not terms:
        return []

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": f"WOE={' '.join(terms)}",
        "recordSchema": "MARC21-xml",
        "maximumRecords": str(min(limit * 3, 50)),
    }
    try:
        response = await fetch.get_once(_DNB_URL, params=params)
        if response.status_code != 200:
            return []
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("DNB search failed for %r", query, exc_info=True)
        return []

    results: list[Record] = []
    for node in root.iter(f"{_MARC}record"):
        fields = _marc_fields(node)
        record = _dnb_record(fields, isbn=None)
        # Online resources are refused here and merely ranked down in `_dnb`,
        # and the asymmetry is deliberate: a search has no ISBN to tell an
        # edition of this book from a digitisation of another one, so it is the
        # same refusal `_k10plus_search` makes two functions above.
        if record is None or not _is_physical_book(
            _marc_extent(fields), record.title
        ):
            continue
        results.append(record)
    return results


# ── The regional catalogues ───────────────────────────────────────────────────
#
# Kept for the languages the primary three cover least well, and ranked below
# them for exactly that reason: they are here for the books nobody else holds,
# not to reorder the ones everybody does.
#
#   bnf   Bibliothèque nationale de France. French legal deposit. Free, no key.
#   loc   Library of Congress. Poor for ISBN lookup (two hits in ten, both
#         covered elsewhere) and worth having for search, where a Spanish or
#         Portuguese title the German and French catalogues do not hold still
#         surfaces: "cien anos de soledad" returns 73 records, "ensaio sobre a
#         cegueira" six. Those two counts are the evidence that belongs here,
#         because they measure the path this source is actually on.
#
# **What this comment used to claim, and why it no longer does.** It said the LoC
# "holds Spanish, Portuguese and Latin American printings", which is the sentence
# `search`'s docstring retracts with a measurement: by ISBN it holds 25.0% of a
# Spanish sample and 55.3% of a Uruguayan one, and Uruguay is the only country
# that separates from any other. Read the two together: the table there says which
# countries it **holds**, the two counts above say the search **surfaces** them,
# and those are different questions.
#
# It also said Spain and Portugal "have no usable free interface of their own",
# and both halves are now measured false. **Spain has three reachable
# catalogues** (the CSIC library network, and the ministry's CCPB and REBECA),
# two of which answer SRU over plain HTTP; it is the Biblioteca Nacional
# specifically that authenticates. **PORBASE is not gone**: its hostname was
# retired and the national library publishes two live ones on another domain.
# Neither is in the chain, so the Library of Congress is still the substitute
# here, but it is a substitute for something that exists rather than for nothing.

_BNF_URL: Final = "https://catalogue.bnf.fr/api/SRU"
_LOC_URL: Final = "http://lx2.loc.gov:210/lcdb"

_MODS: Final = "{http://www.loc.gov/mods/v3}"

#: BnF `dc:type` values that are a printed book. It also catalogues manuscripts,
#: scores, maps and recordings, all of which match a title search.
_BNF_PRINTED: Final = ("texte imprim", "printed text", "text")


async def _bnf_search(query: str, limit: int) -> list[Record]:
    """The BnF, through its catch-all index.

    `bib.anywhere all "..."` requires every word, which is the same contract as
    the other two SRU sources and the same reason it is precise enough to use.
    """
    terms = _search_terms(query)
    if not terms:
        return []

    params = {
        "version": "1.2",
        "operation": "searchRetrieve",
        "query": f'bib.anywhere all "{" ".join(terms)}"',
        "recordSchema": "dublincore",
        "maximumRecords": str(min(limit * 2, 20)),
    }
    try:
        response = await fetch.get_once(_BNF_URL, params=params)
        if response.status_code != 200:
            return []
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("BnF search failed for %r", query, exc_info=True)
        return []

    results: list[Record] = []
    for node in root.findall(f".//{_DC}title/.."):
        record = _bnf_record(node)
        if record is not None:
            results.append(record)
    return results


def _bnf_record(record: ElementTree.Element) -> Record | None:
    def texts(tag: str) -> list[str]:
        return [
            element.text.strip()
            for element in record.findall(f"{_DC}{tag}")
            if element.text and element.text.strip()
        ]

    titles = texts("title")
    if not titles:
        return None

    # Printed books only. `dc:type` is repeated in French and English.
    kinds = " ".join(texts("type")).casefold()
    if kinds and not any(kind in kinds for kind in _BNF_PRINTED):
        return None

    # The BnF writes the statement of responsibility into the title, the same
    # way the DNB does, so the same parser applies.
    title, subtitle = _dc_title_statement(titles[0])
    if _is_placeholder_title(title):
        return None

    extent = next((value for value in texts("format")), None)
    if not _is_physical_book(extent, title):
        return None

    # `dc:identifier` holds an ARK URL and sometimes "ISBN 0333532945".
    isbn = next(
        (
            parsed
            for value in texts("identifier")
            for parsed in [parse_isbn(value.replace("ISBN", "").strip())]
            if parsed is not None
        ),
        None,
    )

    # "M. J. Minard, Lettres modernes (Paris)" is publisher then place.
    publisher = next((value for value in texts("publisher")), None)
    if publisher:
        publisher = re.sub(r"\s*\([^)]*\)\s*$", "", publisher).strip()

    year_match = re.search(r"\d{4}", " ".join(texts("date")))

    return Record(
        source="bnf",
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=_bnf_authors(texts("creator")),
        publisher=publisher,
        year=int(year_match.group()) if year_match else None,
        language=_LANGUAGES.get((texts("language") or [""])[0].lower()),
        page_count=_pages_from_extent(extent),
        cover_url=covers.open_library_url(isbn) if isbn else None,
        subjects=tuple(texts("subject")),
    )


def _bnf_authors(creators: list[str]) -> str | None:
    """The people who wrote it, not the ones who translated or edited it.

    The BnF marks the role inside the creator string rather than in a field of
    its own, so it has to be read out of the text. A creator with no role
    marker is the main entry and is kept: dropping it would leave records with
    no author at all.
    """
    authors = [
        _flip_catalogue_name(creator)
        for creator in creators
        if not _BNF_ANY_ROLE.search(creator)
        or any(role in creator.casefold() for role in _BNF_AUTHOR_ROLES)
    ]
    return ", ".join(authors) or None


async def _loc_search(query: str, limit: int) -> list[Record]:
    """The Library of Congress, restricted to text.

    `typeOfResource` is the denoising that makes this usable: without it a
    title search returns sound recordings and microfilm alongside the book,
    and "moby dick" came back as a 78rpm spoken-word disc.
    """
    terms = _search_terms(query)
    if not terms:
        return []

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": f'dc.title="{" ".join(terms)}"',
        "recordSchema": "mods",
        "maximumRecords": str(min(limit * 2, 20)),
    }
    try:
        response = await fetch.get_once(_LOC_URL, params=params)
        if response.status_code != 200:
            return []
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("Library of Congress search failed for %r", query, exc_info=True)
        return []

    results: list[Record] = []
    for node in root.iter(f"{_MODS}mods"):
        record = _loc_record(node)
        if record is not None:
            results.append(record)
    return results


def _loc_record(record: ElementTree.Element) -> Record | None:
    kind = record.find(f"{_MODS}typeOfResource")
    if kind is None or (kind.text or "").strip() != "text":
        return None

    title_info = record.find(f"{_MODS}titleInfo")
    if title_info is None:
        return None
    title_element = title_info.find(f"{_MODS}title")
    title = (title_element.text or "").strip().rstrip(":;,/ ") if title_element is not None else ""
    if not title:
        return None

    # `nonSort` holds the leading article, split out so the catalogue can file
    # under the first real word. Dropping it turned "L'étranger" into
    # "étranger" and "The Hobbit" into "Hobbit", which reads as a data error
    # and stops the title matching what somebody typed.
    non_sort = title_info.find(f"{_MODS}nonSort")
    if non_sort is not None and non_sort.text:
        prefix = non_sort.text.strip()
        # An elided article joins the word; a whole one takes a space.
        title = prefix + ("" if prefix.endswith("'") else " ") + title
    if _is_placeholder_title(title):
        return None

    subtitle_element = title_info.find(f"{_MODS}subTitle")
    subtitle = (
        subtitle_element.text.strip()
        if subtitle_element is not None and subtitle_element.text
        else None
    )

    # A `name` with no role is the main entry. Roles are spelled out in MODS
    # ("author", "editor"), so a translator can be dropped by name.
    authors: list[str] = []
    for name in record.findall(f"{_MODS}name"):
        roles = " ".join(
            (role.text or "").strip().casefold()
            for role in name.findall(f"{_MODS}role/{_MODS}roleTerm")
        )
        if roles and "author" not in roles and "creator" not in roles:
            continue
        part = name.find(f"{_MODS}namePart")
        if part is not None and part.text:
            authors.append(_flip_catalogue_name(part.text.strip().rstrip(",.")))

    extent_element = record.find(f"{_MODS}physicalDescription/{_MODS}extent")
    extent = extent_element.text.strip() if extent_element is not None and extent_element.text else None
    if not _is_physical_book(extent, title):
        return None

    isbn = next(
        (
            parsed
            for element in record.findall(f"{_MODS}identifier")
            if element.text
            for parsed in [parse_isbn(element.text)]
            if parsed is not None
        ),
        None,
    )

    publisher_element = record.find(f"{_MODS}originInfo/{_MODS}publisher")
    if publisher_element is None:
        publisher_element = record.find(
            f"{_MODS}originInfo/{_MODS}agent/{_MODS}namePart"
        )
    publisher = (
        publisher_element.text.strip()
        if publisher_element is not None and publisher_element.text
        else None
    )

    years = [
        element.text
        for element in record.findall(f"{_MODS}originInfo/{_MODS}dateIssued")
        if element.text
    ]
    year_match = re.search(r"\d{4}", " ".join(years))

    language_element = record.find(
        f"{_MODS}language/{_MODS}languageTerm"
    )
    language = (
        _LANGUAGES.get((language_element.text or "").strip().lower())
        if language_element is not None
        else None
    )

    return Record(
        source="loc",
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=", ".join(authors) or None,
        publisher=publisher,
        year=int(year_match.group()) if year_match else None,
        language=language,
        page_count=_pages_from_extent(extent),
        cover_url=covers.open_library_url(isbn) if isbn else None,
        subjects=tuple(
            element.text.strip()
            for element in record.findall(f"{_MODS}subject/{_MODS}topic")
            if element.text
        ),
        # The shelf classifications first and the subject headings after,
        # which is load bearing rather than tidy. `Record.match_headings`
        # slices to `MAX_CLASSIFICATIONS_PER_BOOK` and
        # `routers/books._headings` applies `_SCHEME_ORDER` only afterwards, so
        # on the search path a record's own order decides what survives. One
        # live record carries 14 LCSH headings (measured over 900 records,
        # 2026-08-24); putting them in front would cost this record its Dewey
        # number and its call number, which are the two schemes nothing else in
        # the chain supplies together.
        headings=tuple(_loc_classifications(record) + _loc_subject_headings(record)),
    )


#: MODS names the scheme in an attribute, so the two are told apart by the
#: record rather than by guessing at the shape of the notation.
_LOC_AUTHORITIES: Final[dict[str, ClassificationScheme]] = {
    "ddc": ClassificationScheme.DDC,
    "lcc": ClassificationScheme.LCC,
}


def _loc_classifications(record: ElementTree.Element) -> list[Heading]:
    """The `<classification>` elements, which no other source here carries.

    The Library of Congress is the only one that returns both a DDC and an LCC
    number for one book (`QA76.73.P98 V53 2021` beside `005.133`, measured
    2026-08-23), which is why the store has a scheme column rather than a Dewey
    column. Neither carries a caption in MODS, so both are stored with none.

    An authority this app has no reading for is dropped rather than stored: a
    number whose scheme nothing recognises cannot be sorted, matched or shown
    as anything but a string.
    """
    found: list[Heading] = []
    for element in record.findall(f"{_MODS}classification"):
        scheme = _LOC_AUTHORITIES.get((element.get("authority") or "").lower())
        raw = " ".join((element.text or "").split())
        if scheme is None or not raw:
            continue
        if scheme is ClassificationScheme.DDC:
            # Through the same normaliser as the other two source paths. MODS
            # carries the prime here too, and a `<classification>` that is not
            # a Dewey number at all is dropped rather than stored under a
            # scheme that cannot read it.
            heading = ddc.parse_heading(raw)
            if heading is None:
                continue
            number, label = heading
        else:
            # No normaliser for LCC: a call number is alphanumeric and this app
            # has no schedule for it. The whitespace collapse above and
            # `ClassificationIn`'s 40 character bound are the whole guard.
            number, label = raw, None
        found.append(Heading(scheme, number, label))
    return found


#: The subject vocabulary this app reads, of the 23 the Library of Congress
#: mixes into one record.
#:
#: Measured over 900 live MODS records on 2026-08-24: 2,280 `<subject>`
#: elements, of which 289 name no authority at all and the other 1,991 name 23
#: distinct values (one of them a stray `bisacsh.` beside `bisacsh`). `lcsh` is
#: 1,559 of them; the largest of the other 22 are `fast` 213, `lcshac` 59,
#: `rvm` 49, `sears` 19, `mesh` 19 and `gtt` 18, and the remaining 16 supply 55
#: between them.
#:
#: Only `lcsh` is read, which is the rule `_LOC_AUTHORITIES` already applies to
#: `<classification>`: a heading whose vocabulary this app has no reading for
#: is a string nothing can match against another catalogue. `lcshac` is the
#: children's subject list and is deliberately **not** folded in: it is a
#: separate authority file with its own headings, so `lcsh` would stop meaning
#: one vocabulary. `fast` is the closest miss, being LCSH mechanically
#: flattened, and it is left out for the same reason.
_LOC_SUBJECT_AUTHORITY: Final = "lcsh"

#: How LCSH writes a heading and its subdivisions: `Computer software --
#: Development`. MODS gives the parts as sibling elements instead, so the
#: separator has to be put back.
#:
#: Two ASCII hyphens, which is the vocabulary's own notation and not this
#: repository's prose. 1,056 of 1,559 live headings carry at least one, 67.7%.
_LCSH_SUBDIVISION: Final = " -- "


def _loc_subject_headings(record: ElementTree.Element) -> list[Heading]:
    """The `<subject authority="lcsh">` elements, as classification rows.

    **A parser extension rather than a new source.** The record this reads is
    the one `_loc_record` already has in hand, so LCSH costs no outbound
    request and the Library of Congress does not join `_SOURCES`. It stays off
    the lookup path for the reason `docs/decisions.md` records: it is the one
    catalogue here reached over plaintext HTTP, and it held nothing for either
    German ISBN measured, which is this library's main case.

    **No `<subject>` element ever reaches `ddc`.** `ddc.parse_heading` accepts
    any three digit token, so a heading opening with one would be stored as a
    Dewey number and would suggest a curated tag from it. Checked rather than
    assumed: `parse_heading("004 Jahre Bauhaus")` answers `("004", "Jahre
    Bauhaus")`, where `parse_heading("1968 -- Fiction")` answers None, four
    digits not being a notation. The guard is structural and is the same
    one round 2 built for the DNB: `<classification>` is the only element
    handed to `ddc`, in `_loc_classifications`, and this function builds LCSH
    rows without importing it.

    **The heading is the whole chain, not its first part.** MODS gives
    `Computer software -- Development` as two sibling `<topic>` elements, and
    `Computer software` alone is a different heading that a different set of
    books carries. The parts are joined in document order, which is the order
    LCSH itself prescribes.

    **A part either carries its text or nests it, and the second shape is not
    an edge case.** `<topic>`, `<genre>`, `<geographic>` and `<temporal>` hold
    their own text; `<titleInfo>` wraps a `<title>` and `<name>` wraps one to
    four `<namePart>` elements. That is not only the personal case: a personal name
    splits into a name and its dates (`Süssheim, Karl, 1878-1947`), and a
    corporate one splits into a body and its subordinate unit (`Canada.` plus
    `Board of railway commissioners.`), which was 2 of 10 multi part names in a
    live sample. Both shapes lose their tail if only the first part is read.
    Measured over 900 live records: 21 nested
    titles and 116 nested names, and those are the only two shapes with
    children, so reading a part's own children is the whole rule rather than
    two special cases.

    Getting that wrong is worse than losing a row. A `<name>` read as empty
    does not drop the heading, it **shortens** it: `Catholic Church -- History`
    becomes `History`, which is a different heading asserted about the wrong
    thing. 116 of 1,559 live LCSH elements, 7.4%, are that shape.

    **`number` holds the heading and this parser leaves `label` empty**, because the
    record supplies no identifier to separate them: see `models.Classification`
    for the measurement and what it costs.

    Not deduplicated here. `Record` unions on (scheme, number) at construction,
    **before** `match_headings` slices, so a record repeating a heading spends
    one place and not two, and a second dedupe would be the same rule enforced
    twice.
    """
    found: list[Heading] = []
    for element in record.findall(f"{_MODS}subject"):
        if (element.get("authority") or "").lower() != _LOC_SUBJECT_AUTHORITY:
            continue
        parts: list[str] = []
        for part in element:
            words = (part.text or "").split()
            if not words:
                # Nested rather than absent: see the docstring. A name's parts
                # are joined with a space because the record already writes the
                # comma, `Süssheim, Karl,` then `1878-1947`.
                words = [
                    word
                    for child in part
                    for word in (child.text or "").split()
                ]
            if words:
                parts.append(" ".join(words))
        if not parts:
            continue
        found.append(Heading(ClassificationScheme.LCSH, _LCSH_SUBDIVISION.join(parts)))
    return found


# ── Ranking ───────────────────────────────────────────────────────────────────


def _fold(value: str) -> str:
    """Strip accents, so `Schätzing` and `Schatzing` are the same word.

    Half the catalogues in this chain are national ones and half the shelf is
    not English. Somebody typing on a phone keyboard writes "etranger" and
    "schatzing", and a search that only matches the accented spelling is a
    search that fails for exactly the books the German and French sources were
    added for.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _normalise_words(value: str | None) -> set[str]:
    return set(re.sub(r"[^\w\s]", " ", _fold(value or "").casefold()).split())


def _edit_budget(term: str) -> int:
    """How many characters a term may differ by and still be the same word.

    Scaled by length rather than fixed, because a ratio is the wrong measure
    for short words: one character between "code" and "coder" is 89% similar
    and a different word, while one between "philosopher" and "philosophers"
    is 96% similar and the same one. Below five characters nothing is close
    enough to guess at.
    """
    if len(term) < 5:
        return 0
    return 1 if len(term) < 8 else 2


def _matches_any(term: str, words: set[str]) -> bool:
    """Whether a query term appears in a field, allowing for near spellings.

    Exact set membership was the first version and it failed on the ordinary
    cases: `Manns` against `mann`, `philosopher's` against `philosopher`,
    `Schatzing` against `Schätzing`. Accent folding fixes the third; a small
    edit budget handles the other two without a stemmer for five languages.
    """
    if term in words:
        return True
    budget = _edit_budget(term)
    if not budget:
        return False
    return any(
        Levenshtein.distance(term, word, score_cutoff=budget) <= budget for word in words
    )


#: What one query term matching is worth. Title and author score the **same**,
#: deliberately. Weighting the title higher let a study guide called "Textanalyse
#: und Interpretation zu Thomas Manns Der Zauberberg" outrank the novel, because
#: it carries the author's name inside its own title and so matched four terms
#: there instead of two plus two.
_TERM_WEIGHT: Final = 3
_SERIES_WEIGHT: Final = 1

#: A title that is almost entirely query terms is almost certainly the book.
#: This is what separates "Der Zauberberg" from a twelve-word title that
#: happens to contain those two words, and it is worth about one extra term.
_PRECISION_WEIGHT: Final = 4

#: A row that satisfies **both halves** of a "title author" query. That is how
#: people search, and it is the signal that separates a novel from a book
#: about it: "L'Etranger, Camus" by Pierre Louis Rey carries both terms in its
#: title and none in its author, where the novel carries one in each. Worth
#: more than one term deliberately: three rows tied at two points and the
#: study guide won on having a nicer cover.
_BOTH_HALVES_BONUS: Final = 4

#: Matching the reader's own language. One term's worth, so it orders printings
#: without ever outranking a real title match: a German library searching an
#: English title still gets the English book.
_LANGUAGE_WEIGHT: Final = 3

#: Catalogues kept for the publishing the primary three cover least well. A row
#: only they found is worth having; a row they merely duplicate is not worth
#: promoting, so a point comes off. One point is less than a single term match,
#: so this only ever breaks a tie.
_SECONDARY_SOURCES: Final = frozenset({"bnf", "loc", "oenb"})
_SECONDARY_PENALTY: Final = 1

#: Fields that make a row pickable rather than a stub. Scored **separately**
#: from matching and only ever as a tiebreaker: a fully populated record that
#: answers nothing must never outrank a sparse one that answers the question.
#: It did, and "Christmas at Hogwarts" came second for "harry potter
#: philosopher's stone".
_COMPLETENESS_FIELDS: Final = (
    "author",
    "year",
    "publisher",
    "page_count",
    "isbn",
    "cover_url",
)


def _relevance(
    match: Record, terms: list[str], prefer_language: str | None
) -> tuple[int, int, int]:
    """How well one result answers the query, most significant part first.

    A tuple rather than a number, and that is the point: the parts are ranked
    against each other rather than added up, so no amount of metadata can lift
    a row that does not match, and no amount of matching is decided by a
    publication year.

      1. how much of the query this row accounts for
      2. how complete the row is
      3. how recent the printing is

    Needed at all because the catalogues return **catalogue order**, which for
    the SRU sources is roughly newest first. Without it a search for a novel
    surfaces whichever reprint was catalogued most recently.
    """
    wanted = {term for term in _normalise_words(" ".join(terms)) if len(term) > 1}
    if not wanted:
        return (0, 0, 0)

    # The subtitle counts for matching but **not** for precision below. A book
    # with a subtitle is not a worse answer than one without, and including it
    # in the denominator made "Clean Code: A Handbook of Agile Software
    # Craftsmanship" score three points below a 2025 reprint with no subtitle.
    title = _normalise_words(match.title)
    searchable = title | _normalise_words(match.subtitle)
    author = _normalise_words(match.author)
    series = _normalise_words(match.series_name)

    score = 0
    in_title = in_author = False
    for term in wanted:
        title_hit = _matches_any(term, searchable)
        author_hit = _matches_any(term, author)
        if title_hit or author_hit:
            score += _TERM_WEIGHT
            in_title = in_title or title_hit
            in_author = in_author or author_hit
        elif _matches_any(term, series):
            score += _SERIES_WEIGHT

    if in_title and in_author:
        score += _BOTH_HALVES_BONUS

    # How much of the *title* is query, rather than how much of the query is
    # title. A long title dilutes; an exact one does not. This is what stops a
    # study guide called "Textanalyse und Interpretation zu Thomas Manns Der
    # Zauberberg" outranking the novel it is about.
    if title:
        covered = sum(1 for word in title if _matches_any(word, wanted))
        score += round(_PRECISION_WEIGHT * covered / len(title))

    if prefer_language and match.language == prefer_language:
        score += _LANGUAGE_WEIGHT

    # Regional catalogues answer last among equals. The penalty applies only
    # when they are the **only** source for a row: a book a primary catalogue
    # also holds is a primary row, and docking it for having been confirmed by
    # a second catalogue pushed the fuller record below the sparser one.
    sources = match.sources
    if sources and sources <= _SECONDARY_SOURCES:
        score -= _SECONDARY_PENALTY

    completeness = sum(1 for name in _COMPLETENESS_FIELDS if getattr(match, name))
    return (score, completeness, match.year or 0)


def _match_key(match: Record) -> str:
    """What makes two results from different sources the same book.

    Deliberately lossy, and it only has to be good enough to stop the picker
    showing the same book twice. `_duplicate_key` in the books router does the
    same job for stored books and does it more carefully, because a wrong
    answer there merges two records rather than hiding one row.
    """
    title = re.sub(r"[^\w\s]", "", (match.title or "").casefold()).strip()
    author = (match.author or "").casefold().split(",")[0].strip()
    return f"{title}|{author}"


async def search(
    query: str,
    api_key: str = "",
    limit: int = 10,
    prefer_language: str | None = None,
    *,
    plan: sources.Plan,
) -> list[Record]:
    """Find a book by title and author, across every catalogue this library asks.

    **Which catalogues those are is `plan`**, and it is the household's, not
    this module's. A source switched off is never constructed and never
    awaited. What follows describes the seven a new install asks, which is the
    seeded default and the shape every measurement below was taken at.

    Three tiers, and the tiering is what keeps this both broad and quick.

    **Tier one, free, primary:** Open Library for breadth and covers, K10plus
    for German and European publishing, the DNB for German legal deposit.

    **Tier two, free, regional:** the BnF for French, the Library of Congress
    for Uruguayan printings and for anything printed before ISBNs existed, the
    ÖNB for Austrian imprints. All three are ranked a point below the primaries:
    they are here for the books nobody else holds, not to reorder the ones
    everybody does.

    **That line has now named the wrong countries twice, and the second time was
    the correction.** It said "Spanish, Portuguese and Latin American printings",
    which nothing had measured. Measured 2026-08-30, asking `lx2.loc.gov` by
    `bath.isbn` for 50 domestic ISBNs per country, denominators varying because
    two or three per country went unanswered:

    | | Uruguay | Spain | Italy | Brazil | Portugal | Argentina |
    |---|---|---|---|---|---|---|
    | held | 26/47 | 12/48 | 12/48 | 9/47 | 9/48 | 8/48 |
    | | **55.3%** | 25.0% | 25.0% | 19.1% | 18.8% | 16.7% |

    So the first correction read "Latin American printings", **and that was the
    same mistake one category up**: the label is carried entirely by Uruguay,
    while Brazil at 19.1% and Argentina at 16.7% are **below** the Spain and
    Italy figures the correction had just dropped for being unsupported.
    Aggregated, Latin America is 43/142 against Spain and Italy's 24/96, +5.3
    points, 95% Newcombe -6.5 to +16.3, which includes zero; without Uruguay it
    is 17/95, or 17.9%.

    **Uruguay is the only result here that separates from anything**: +30.3
    points over Spain, 95% Newcombe +10.6 to +47.0, excluding zero. Nothing
    separates the five below it, so the line names Uruguay and stops.

    Those three figures said +28.0, +9.0 and +44.4 for one round, which is what
    26/50 against 12/50 gives. **They were the numbers from before the table
    above was corrected to its real denominators**, so this paragraph was the
    claim written in two places and fixed in one, committed in the paragraph
    that names that mistake. `TestTheLibraryOfCongressTableAgreesWithItself`
    now recomputes all three from the table's own fractions, because the six
    percentages were pinned and these three were pinned by nothing, which is
    how they survived.

    **Holding the edition is necessary and not sufficient**, because this is a
    title search source: the table says the record exists to be found, not that
    a title query finds it. `_loc_search` below carries the title side, and the
    durable half of this source's justification is not in the table at all: it
    is the best free source for a book printed before ISBNs existed, which no
    ISBN measurement can touch.

    The method behind the table, and the two title search counts that measure the
    other half of this source, are in `docs/decisions.md` and in the regional
    catalogues comment below.

    **Tier three, only with a key:** Google Books, for the blurb and the
    categories the others do not carry.

    Every enabled source is asked **concurrently**, so the wall clock is the
    slowest of them rather than the sum, measured at 1.2s to 1.8s across seven
    before the seventh joined. **Enabling one costs a slot of the deadline and
    nothing of the wall clock; disabling one buys back neither**, since the
    budget is spent waiting on the slowest survivor. What it does buy is the
    request never being made, which is the point of the switch.

    **The seventh moved that, and the honest figure is a range rather than a
    number.** Across 24 live ÖNB title searches on 2026-08-27, at the shape this
    function actually requests, latency ran **0.156s to 3.23s**. It is variable
    enough that which source is slowest changes between runs: one eight query
    comparison of the six free sources, Google Books excluded because it needs
    a key and a library without one never asks it, put the BnF slowest by mean
    at 1.216s and K10plus slowest by any single request at 1.687s, with the ÖNB
    third at 0.795s mean,
    while a twelve query run of the ÖNB alone reached 2.121s and a separate four
    query run reached 3.23s.

    What matters is not which one is slowest, it is that a single measured ÖNB
    request has come within **0.8s of `SEARCH_DEADLINE_SECONDS`**. So this
    source is the most likely of the seven to be the one the deadline drops, and
    the deadline is what stops that costing the search. An earlier version of
    this sentence said 0.82s to 1.41s, which was in no record, was about half
    the true upper bound, and read as "the seventh source changes nothing".

    **Then ours:** filtering out what is not a book, merging one book's rows
    from several catalogues into one, and ranking the result against the query.
    That last part is not optional. The SRU catalogues return catalogue order,
    which is roughly newest first, so without it a search for a novel surfaces
    whichever reprint was catalogued most recently.

    `prefer_language` breaks ties towards the reader's own language without
    ever outranking a title match, so a German library searching an English
    title still gets the English book.

    A source that fails is skipped rather than failing the search. Losing one
    of four is not worth refusing to answer, and a library that has switched
    every source off gets an empty list rather than an error.
    """
    trimmed = query.strip()
    terms = _search_terms(trimmed)
    if not terms:
        return []

    # **Only the enabled sources are constructed**, so a source this library
    # turned off is never built and never awaited. Building all seven and
    # dropping some would leave un-awaited coroutines behind, which is a warning
    # per search and a request nobody asked for if one ever ran.
    #
    # `plan.searched` holds only names in `sources.SEARCH_SOURCES`, and
    # `TestTheProviderRosterIsOneList` pins that set equal to `_FREE_SEARCHES`
    # plus the metered one, so there is no `KeyError` to reach here.
    tiers = await _within_deadline(
        [
            _METERED_SEARCHES[name](trimmed, limit, api_key)
            if name in _METERED_SEARCHES
            else _FREE_SEARCHES[name](trimmed, limit)
            for name in plan.searched
        ]
    )

    merged = _merge_matches([row for tier in tiers for row in tier])

    ranked = sorted(
        merged, key=lambda match: _relevance(match, terms, prefer_language), reverse=True
    )
    return ranked[:limit]


#: The title search adapter for every source that needs no credential.
#:
#: **Module level and introspectable on purpose.** The guard that keeps this
#: table and the roster in step used to read the fan out with `ast`, as a list
#: literal handed to `_within_deadline`, and it broke the moment the fan out
#: stopped being a literal. A dictionary a test can compare with
#: `sources.SEARCH_SOURCES` at runtime cannot go stale the same way.
#:
#: Google Books is the one absent, because it is the one that needs an API key
#: and so cannot share this signature. `_METERED_SEARCHES` below holds it, and
#: `TestTheProviderRosterIsOneList` asserts the two tables together are the
#: whole roster: a source added to the roster and to neither table fails rather
#: than going quietly unasked.
_FREE_SEARCHES: Final[
    dict[CatalogueSource, Callable[[str, int], Coroutine[Any, Any, list[Record]]]]
] = {
    CatalogueSource.OPEN_LIBRARY: _open_library_search,
    CatalogueSource.K10PLUS: _k10plus_search,
    CatalogueSource.DNB: _dnb_search,
    CatalogueSource.BNF: _bnf_search,
    CatalogueSource.LOC: _loc_search,
    CatalogueSource.OENB: _oenb_search,
}


async def _google_search(query: str, limit: int, api_key: str) -> list[Record]:
    """Google Books, which needs a key and so takes one more argument.

    A module level adapter rather than a closure inside `search`, so the table
    below can be compared with the roster at runtime. It was a closure and the
    dispatch tested `name is CatalogueSource.GOOGLE_BOOKS`, which is a second
    metered source away from a `KeyError`: the roster guard would have been
    satisfied by `set(_FREE_SEARCHES) | METERED` while the dispatch sent it to
    the free table.

    An absent key answers nothing rather than requesting anonymously.
    `settings_store.ready_sources` already keeps a keyless Google out of the
    plan, so this is the second of two checks, kept because a caller passing a
    plan by hand is not a caller that consulted the settings table.
    """
    if not api_key:
        return []
    try:
        found = await google_books.search(query, api_key, limit=limit)
    except (google_books.GoogleBooksError, httpx.HTTPError, ValueError):
        logger.info("Google Books search unavailable for %r", query, exc_info=True)
        return []
    return [_google_record(item) for item in found]


#: The title search adapter for every source that needs a credential.
#:
#: Separate from `_FREE_SEARCHES` because the signature differs, and a table
#: rather than a branch on one name because a branch is only correct while there
#: is exactly one of them. `TestTheProviderRosterIsOneList` pins these keys equal
#: to `sources.METERED`.
_METERED_SEARCHES: Final[
    dict[CatalogueSource, Callable[[str, int, str], Coroutine[Any, Any, list[Record]]]]
] = {
    CatalogueSource.GOOGLE_BOOKS: _google_search,
}


#: How long a search may take, whatever the catalogues do.
#:
#: Seven sources are asked at once, so the wall clock is the slowest of them, and
#: one national catalogue having a bad afternoon was turning a 1.3s search into
#: a 7s one. A deadline degrades the *results* instead of the latency: whatever
#: has answered is ranked and returned, and the straggler is cancelled.
#:
#: Well above the 1.2s to 1.8s a healthy search measures, so this only ever
#: fires on a source that is genuinely struggling.
SEARCH_DEADLINE_SECONDS: Final = 4.0


async def _within_deadline(
    searches: list[Coroutine[Any, Any, list[Record]]],
) -> list[list[Record]]:
    """Run every search, keep what answers in time, drop the rest.

    **Empty is a real case and is answered here rather than raised.**
    `asyncio.wait` refuses an empty set with `ValueError`, so a library that has
    switched off every catalogue turned a title search into a 500. It arrived
    with the fix for the sibling case: `lookup` learned to say "nothing was
    asked" and this path was left to find out the hard way.
    """
    if not searches:
        return []
    tasks = [asyncio.ensure_future(search) for search in searches]
    done, pending = await asyncio.wait(tasks, timeout=SEARCH_DEADLINE_SECONDS)

    for task in pending:
        task.cancel()
    if pending:
        # Awaited so the cancellations are actually delivered rather than left
        # to be reported later as "task was destroyed but it is pending".
        await asyncio.gather(*pending, return_exceptions=True)
        logger.info("%d catalogue(s) missed the search deadline", len(pending))

    # Order restored: `asyncio.wait` returns a set, and the merge below reads
    # source precedence from the order rows arrive in.
    return [task.result() for task in tasks if task in done and not task.cancelled()]


#: Sources in the order their version of a shared field is believed. Open
#: Library leads on the title because its search index is edited towards how
#: people write titles, where a catalogue records them as printed.
_MATCH_PRECEDENCE: Final = (
    "open_library",
    "google_books",
    "k10plus",
    "dnb",
    "bnf",
    "loc",
    # Last, and named rather than left to the default so that a reader can see
    # it was decided. It is the newest and the least compared of the seven, and
    # the field it would win is a field the DNB or K10plus has already filled
    # for any book all three hold. Where it is the only catalogue with a row,
    # precedence never runs.
    "oenb",
)


def _merge_matches(matches: list[Record]) -> list[Record]:
    """One row per book, whichever catalogues found it.

    Two indexes rather than one key, because the catalogues disagree about
    what they know. An ISBN is proof: two records naming it are the same
    printing and nothing else needs checking. But plenty of records carry none
    at all, and a record with an ISBN and one without still have to be able to
    meet, or the picker shows the same book twice with half the fields on each
    row.

    So a row is looked up by ISBN **and** by work, and merging by either is
    enough. The work key carries the **year**, which is what actually
    distinguishes two printings: without it, choosing between editions, which
    is the whole point of the picker, becomes impossible.

    **The indexes hold slots rather than rows**, because a `Record` is frozen:
    folding two of them produces a third, which then has to replace the first in
    the list. The dictionaries this replaced were rewritten in place with
    `clear()` and `update()` for exactly that reason, and the slot is the honest
    version of the same trick. `is None` and not falsiness on every lookup
    below, because slot 0 is a row.

    **What is not here any more is the fill rule.** `Record.filled_from` holds
    it, along with the reason an empty collection counts as absent where an
    empty string does not: that was a live defect here, where a source finding
    no heading wrote `[]`, `[]` is not `None`, and the empty list beat a
    populated one from the next source.
    """
    order = {source: index for index, source in enumerate(_MATCH_PRECEDENCE)}
    rows: list[Record] = []
    by_isbn: dict[str, int] = {}
    by_work: dict[str, int] = {}

    def work_of(row: Record) -> str:
        return f"{_match_key(row)}:{row.year or ''}"

    def register(slot: int) -> None:
        row = rows[slot]
        if row.isbn:
            by_isbn[row.isbn] = slot
        by_work[work_of(row)] = slot

    def rank(row: Record) -> int:
        """How trusted the most trusted catalogue behind this row is."""
        return min(
            (order.get(source, len(order)) for source in row.sources),
            default=len(order),
        )

    for match in matches:
        if not match.title:
            continue

        slot = by_isbn.get(match.isbn) if match.isbn else None
        if slot is None:
            slot = by_work.get(work_of(match))

        # A translation is not the same book. Two rows sharing a title, an
        # author and a year but naming **different** languages are a German
        # printing and an English one, and folding them together hides the one
        # somebody wants. Only refused when both actually say: an unknown
        # language is not evidence of disagreement.
        if slot is not None:
            languages = {rows[slot].language, match.language}
            if None not in languages and len(languages) > 1:
                slot = None

        if slot is None:
            rows.append(match)
            register(len(rows) - 1)
            continue

        # The more trusted source leads and the other fills its gaps, so a
        # Google blurb and a K10plus page count end up on one row. The winner
        # keeps the list's slot, and `filled_from` records both catalogues in
        # `source` so the picker can say where a row came from and a bug report
        # can name them.
        existing = rows[slot]
        if rank(match) < rank(existing):
            rows[slot] = match.filled_from(existing)
        else:
            rows[slot] = existing.filled_from(match)
        register(slot)

    return rows


# ── Other editions of one work ────────────────────────────────────────────────
#
# What a cataloguer reaches for when a donation arrives in an unfamiliar
# printing, and the one thing on Koha's enrichment list that endpaper did not
# have: `thingISBN` edition clustering, without LibraryThing's terms attached.
# Open Library merges printings under a *work* and publishes the cluster.
#
# `GET /api/books/{id}/enrich/candidates` used to answer this with a free text
# search for the book's own title and author, which is a guess that happens to
# be right most of the time. The cluster is not a guess.

#: How many sibling editions the cluster is asked for.
#:
#: The difference between a request and a download: work sizes measured live on
#: 2026-08-24 run 1, 1, 11, 18, 120, 204, 213, 536 and 4,040 (Pride and
#: Prejudice). Twenty is four times the five rows the picker shows, which
#: leaves the completeness sort something to choose from without paying for a
#: catalogue.
_OPEN_LIBRARY_EDITIONS: Final = 20

#: How many author records the cluster resolves, for any number of rows.
#:
#: An editions listing names its authors by key. Resolving each row's own key
#: is one request per row; the keys repeat, because a work's printings are by
#: the same person, so the distinct keys are resolved instead and this bounds
#: the tail. A row whose key did not make the cap keeps no author rather than
#: somebody else's.
_OPEN_LIBRARY_AUTHOR_LOOKUPS: Final = 3


async def _open_library_author_names(
    client: httpx.AsyncClient, entries: list[Any]
) -> dict[str, str]:
    """Author key to name, for the whole cluster, in at most three requests."""
    keys: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = _open_library_author_key(entry.get("authors"))
        if key is not None and key not in keys:
            keys.append(key)
    wanted = keys[:_OPEN_LIBRARY_AUTHOR_LOOKUPS]
    if not wanted:
        return {}

    async def _name(key: str) -> tuple[str, str | None]:
        response = await fetch.get(client, f"{_OPEN_LIBRARY}{key}.json")
        if response.status_code != 200:
            return key, None
        found = _open_library_object(response).get("name")
        return key, found if isinstance(found, str) else None

    names: dict[str, str] = {}
    for result in await asyncio.gather(
        *(_name(key) for key in wanted), return_exceptions=True
    ):
        # One author record failing costs that author's name, not the cluster.
        if isinstance(result, BaseException):
            continue
        key, name = result
        if name:
            names[key] = name
    return names


def _open_library_edition(entry: dict[str, Any], names: dict[str, str]) -> Record:
    """One entry of an editions listing, as a Catalogue record.

    The same type every other adapter produces, so a cluster row inherits the
    heading dedupe, the completeness score and both wire shapes rather than
    carrying its own copy of any of them.
    """
    identifiers = [
        value
        for key in ("isbn_13", "isbn_10")
        for value in (entry.get(key) or [])
        if isinstance(value, str)
    ]
    isbn13 = _first_isbn13(identifiers)
    cover_ids = entry.get("covers")
    cover_id = (
        cover_ids[0] if isinstance(cover_ids, list) and cover_ids else None
    )
    author_key = _open_library_author_key(entry.get("authors"))
    publishers = entry.get("publishers")
    title = entry.get("title")
    return Record(
        source="open_library",
        isbn=isbn13,
        title=title if isinstance(title, str) else None,
        subtitle=entry.get("subtitle"),
        author=names.get(author_key) if author_key else None,
        publisher=(
            publishers[0] if isinstance(publishers, list) and publishers else None
        ),
        year=_open_library_year(entry.get("publish_date")),
        description=_open_library_description(entry.get("description")),
        page_count=_open_library_pages(entry.get("number_of_pages")),
        language=_open_library_language(entry.get("languages")),
        # By Open Library's own cover id where the entry has one, which resolves
        # for a printing whose ISBN the cover service does not know. 75 of 129
        # live entries carry a cover id and 69 carry an ISBN, and they are not
        # the same 69.
        cover_url=(
            covers.open_library_id_url(cover_id)
            if isinstance(cover_id, int)
            else covers.open_library_url(isbn13)
            if isbn13
            else None
        ),
        subjects=tuple(_open_library_subjects(entry)),
        headings=tuple(_open_library_classifications(entry)),
    )


async def editions(
    isbn: str,
    limit: int,
    prefer_language: str | None = None,
    *,
    plan: sources.Plan,
) -> list[Record]:
    """Every other printing of this work Open Library has merged.

    **Two requests, plus at most three author lookups.** The ISBN gives the
    work and the work gives the cluster, sequentially; then
    `_open_library_author_names` resolves up to `_OPEN_LIBRARY_AUTHOR_LOOKUPS`
    distinct keys concurrently, so the worst case is five requests and three
    round trips. Said precisely because this is the sentence any argument about
    outbound amplification rests on.

    **A translation is dropped, and a printing that says it is the wanted
    language leads.** A work spans translations. The cluster behind
    `9783442002009` (Der Zinker) holds 11 entries, of which 9 declare English
    and are printings of *The Squeaker*, measured live on 2026-08-24. Every one
    is the same work; none can fill in a German printing's publisher, page count
    or cover, and left in they took four of the five rows the picker shows and
    pushed the German editions out of it.

    **An entry declaring no language is kept, and that is a compromise rather
    than a guarantee.** Open Library leaves the field blank far more often than
    this round's first measurement suggested: **56 of 250 entries across 14 live
    clusters, 22.4%**, and a second sample of 14 **different** works measured 52
    of 160, **32.5%**. Both measured on 2026-08-24, against the 19 of 129
    (14.7%) this docstring used to argue from. They are two samples of one
    population on one day over different works, so the **range** is the honest
    reading rather than either figure alone. Refusing them
    would throw away the wanted printing on any cluster that never labels it,
    which is the Der Zinker case: both German printings there carry an empty
    `languages`. Keeping them costs the opposite, and it is the reason the
    language match is the **first** term of the sort rather than a filter alone:
    without it, King's *Es* (`9783453435773`) showed Turkish, Spanish, English
    and French rows, all unlabelled, while the one printing that says
    `languages: [ger]` ranked fifth and was never seen.

    **What that still cannot fix**, and it is recorded rather than claimed away:
    where **no** entry declares the wanted language, nothing in the payload
    distinguishes the wanted printing. `9783596905683` is the live case: four
    Catalan and Spanish rows lead and the German Fischer printing ranks eighth,
    because it is itself unlabelled. The search half of `candidates` is the only
    thing that answers that book, which is why the cluster is capped one row
    short of the page.

    **Then `Record.completeness`, not catalogue order**, which is the same score
    and the same reason `_merge` uses it to choose between printings: an entry
    with a publisher, a year, a page count and a language is one somebody can
    recognise their copy from, and Open Library returns the cluster in no
    useful order. Year descending breaks the tie, because a donation is
    likelier to be a recent printing than the first edition.

    **Ordered before the slice, never after.** The cluster is asked for twenty
    entries and the picker shows four, so an ordering applied to the answer
    would be an ordering applied to whatever twenty Open Library happened to
    list first.

    Empty rather than raising on every failure path, including an ISBN that is
    not one: this is an enrichment, and losing it costs a picker some rows.

    **Open Library off means this answers nothing**, because there is no second
    source for it: the cluster is Open Library's own merge and nothing else here
    holds one. "Off means not asked" has to be true on every path that reaches
    outward, not only the two the settings screen names, and this is the path
    that would otherwise keep asking a source a household switched off.
    """
    if CatalogueSource.OPEN_LIBRARY not in plan.asked:
        return []
    canonical = parse_isbn(isbn)
    if canonical is None or limit <= 0:
        return []
    try:
        async with fetch.catalogue_client() as client:
            response = await fetch.get(client, f"{_OPEN_LIBRARY}/isbn/{canonical}.json")
            if response.status_code != 200:
                return []
            key = _open_library_work_key(_open_library_object(response).get("works"))
            if key is None:
                return []
            listing = await fetch.get(
                client,
                f"{_OPEN_LIBRARY}{key}/editions.json",
                params={"limit": str(_OPEN_LIBRARY_EDITIONS)},
            )
            if listing.status_code != 200:
                return []
            entries = _open_library_object(listing).get("entries")
            if not isinstance(entries, list):
                return []
            names = await _open_library_author_names(client, entries)
    except (httpx.HTTPError, ValueError):
        logger.warning("Open Library editions failed for %s", isbn, exc_info=True)
        return []

    records = [
        _open_library_edition(entry, names)
        for entry in entries
        if isinstance(entry, dict)
    ]
    if prefer_language:
        records = [
            record for record in records if record.language in (prefer_language, None)
        ]
    records.sort(
        key=lambda record: (
            # First, not a tiebreak. A printing that says it is the wanted
            # language beats one that says nothing, and 22% to 33% of live
            # entries say nothing. Without this, King's Es showed four
            # unlabelled foreign printings and never the German one.
            bool(prefer_language) and record.language == prefer_language,
            record.completeness,
            record.year or 0,
        ),
        reverse=True,
    )
    return records[:limit]


async def candidates(
    query: str,
    api_key: str = "",
    isbn: str | None = None,
    limit: int = 10,
    prefer_language: str | None = None,
    *,
    plan: sources.Plan,
) -> list[Record]:
    """Editions to choose between for a book that already exists, cluster first.

    Two answers to one question, and they fail on opposite books. Open
    Library's work cluster is **certain**: every row is a printing of the same
    work by Open Library's own merge, so nothing in it needs ranking against
    the query because nothing in it is a different book. The free text search
    is **broad**: it is the only answer for a book with no ISBN, for a work
    Open Library has not merged, and for German publishing, where Open Library
    frequently holds nothing at all (`9783446249974`, round 2's reference
    record, is a 404 there while the DNB returns 15,502 bytes).

    So the cluster leads and the search fills. **The cluster is capped one
    short of the page** so a work merged wrongly is never the entire answer:
    the search row underneath it is the way out.

    Both are asked at once, and the cluster is held to the search's own
    deadline, so a slow Open Library costs its rows rather than the response.
    """
    cluster, searched = await asyncio.gather(
        _work_cluster(isbn, max(limit - 1, 0), prefer_language, plan),
        search(query, api_key, limit=limit, prefer_language=prefer_language, plan=plan),
    )
    rows = list(cluster)
    # **Deduplicated on the ISBN and on nothing else**, which is the one thing
    # that identifies a printing. `_match_key` is title plus author, and every
    # row on this page shares both by construction: using it here collapsed a
    # five row answer to one, live, because five printings of one book are
    # five rows the picker exists to show. A row with no ISBN is always kept,
    # for the same reason.
    seen = {row.isbn for row in rows if row.isbn}
    for row in searched:
        found = row.isbn
        if found and found in seen:
            continue
        if found:
            seen.add(found)
        rows.append(row)
    return rows[:limit]


async def _work_cluster(
    isbn: str | None, limit: int, prefer_language: str | None, plan: sources.Plan
) -> list[Record]:
    """`editions`, bounded by the search deadline and never fatal.

    **The same 4.0s the search is held to**, so the endpoint's worst case does
    not move: both halves are asked at once and neither may exceed it. Measured
    over 15 live fetches on 2026-08-24 the editions listing answers in 0.64s to
    2.19s, with one 10.1s outlier, and the outlier is the whole reason this
    exists.
    """
    if not isbn or limit <= 0:
        return []
    try:
        return await asyncio.wait_for(
            editions(isbn, limit, prefer_language, plan=plan), SEARCH_DEADLINE_SECONDS
        )
    except TimeoutError:
        logger.info("Open Library's edition cluster missed the deadline for %s", isbn)
        return []


# ── Cache ─────────────────────────────────────────────────────────────────────
#
# An ISBN's metadata does not change, so a repeat lookup is pure waste: it costs
# the reader a second of latency and costs us a slice of the Google quota. The
# rapid scanner makes this concrete, since holding a barcode in frame produces
# the same ISBN many times a second.
#
# In process, not in the database, and that is a deliberate limit: the
# deployment is a single pod with `strategy: Recreate` over one SQLite file, so
# there is exactly one cache and a restart clears it. A second replica would
# each keep their own, which is harmless here because the entries are
# immutable facts about a book.

#: Successful records are cached for a day. They are facts about a printed
#: object and will not change while the pod is up.
_HIT_TTL_SECONDS: Final = 24 * 60 * 60

#: Failures expire far sooner. A book missing from a catalogue today may be
#: catalogued tomorrow, and a throttled key recovers within the hour.
_MISS_TTL_SECONDS: Final = 5 * 60

#: Bounded so a long scanning session cannot grow it without limit.
_MAX_ENTRIES: Final = 2_000

_cache: dict[str, tuple[float, Lookup]] = {}
_cache_lock = asyncio.Lock()


def _cached(isbn: str) -> Lookup | None:
    entry = _cache.get(isbn)
    if entry is None:
        return None
    expires_at, result = entry
    if expires_at < time.monotonic():
        del _cache[isbn]
        return None
    return result


def _remember(isbn: str, result: Lookup) -> None:
    ttl = _HIT_TTL_SECONDS if result.found else _MISS_TTL_SECONDS
    if len(_cache) >= _MAX_ENTRIES:
        # Oldest first. Insertion order is good enough for a bound this size
        # and costs nothing to maintain.
        for key in list(_cache)[: _MAX_ENTRIES // 4]:
            del _cache[key]
    _cache[isbn] = (time.monotonic() + ttl, result)


def clear_cache() -> None:
    """Drop every entry.

    **Called whenever a setting changes which catalogues are asked**, because
    this cache is keyed on the ISBN alone: a record a source supplied before it
    was switched off would otherwise keep being served for the rest of its 24
    hours, and "off means not asked" would be true on the wire and false on the
    screen.

    That is three writes, not one, and the docstring used to name the wrong one:
    it said "for an admin who has just set a key", which was inverted by the
    time the provider list arrived. The three are the provider list itself, the
    Google Books switch and the Google Books key, since
    `settings_store.ready_sources` reads the last two and either can take a
    source out of the plan on its own. `routers/settings.update_settings` is
    where they are wired.
    """
    _cache.clear()


def _worst(attempts: list[tuple[str, Outcome]]) -> Outcome:
    """The failure worth reporting when nothing was found.

    Ordered by what the reader should do about it. Being throttled outranks a
    genuine miss, because "try again shortly" is right and "type it in by hand"
    is not.
    """
    outcomes = {outcome for _, outcome in attempts}
    for candidate in (Outcome.RATE_LIMITED, Outcome.UNAVAILABLE):
        if candidate in outcomes:
            return candidate
    return Outcome.NOT_FOUND


async def lookup(
    raw_isbn: str, api_key: str = "", *, plan: sources.Plan
) -> Lookup:
    """Resolve an ISBN to the best record the free catalogues can produce.

    Two phases. The leading `sources.ALWAYS_ASKED` enabled sources are asked
    **together** and their answers merged, which is where the record quality
    comes from. Only if none of them knows the book do the rest get a turn, one
    at a time, stopping at the first hit.

    **The household decides which sources those are, and the count is a
    constant.** An ordinary lookup makes `sources.ALWAYS_ASKED` outbound
    requests whatever the list says, so reordering can never turn every lookup
    into a full fan out. What it changes is which pair leads, which is what
    makes this useful to a shelf that is not German. A household that leaves
    Google Books below the leading pair still never spends quota on an ordinary
    lookup; one that promotes it has chosen to, and the settings screen says so.

    The ISBN is canonicalised first, so a lookup costs nothing for input that
    could not be a book, and the cache is keyed on one spelling.
    """
    isbn = parse_isbn(raw_isbn)
    if isbn is None:
        return Lookup(Outcome.NOT_FOUND, source="")

    async with _cache_lock:
        hit = _cached(isbn)
    if hit is not None:
        logger.debug("Cached lookup for %s from %s", isbn, hit.source)
        return hit

    attempts: list[tuple[str, Outcome]] = []

    # `return_exceptions` is not set: every source already turns its own
    # failures into an UNAVAILABLE outcome, so an exception escaping one of
    # them is a bug worth seeing rather than a network condition to absorb.
    together = plan.lookup_together
    fast = await asyncio.gather(*(_SOURCES[name](isbn, api_key) for name in together))
    attempts.extend(
        (name, result.outcome) for name, result in zip(together, fast, strict=True)
    )

    hits = [result.record for result in fast if result.found and result.record]
    if hits:
        merged = _merge(hits, isbn)
        # Neither of the fast pair carries an image: they are bibliographic
        # catalogues returning MARC and Dublin Core. The cover is resolved
        # against the image services and **checked**, because storing an
        # unverified guess is how a book ends up with a permanently broken
        # cover. See covers.py.
        merged = merged.with_cover(await covers.resolve(isbn, merged.cover_url))
        # `merged.source` rather than a second join of the same names: folding
        # two records already names both catalogues, and it is the same string
        # the search path builds and the one the cache and the log carry.
        found = Lookup(
            Outcome.FOUND, record=merged, source=merged.source, attempts=attempts
        )
        async with _cache_lock:
            _remember(isbn, found)
        logger.info("Resolved %s from %s", isbn, merged.source)
        return found

    for name in plan.lookup_in_turn:
        result = await _SOURCES[name](isbn, api_key)
        attempts.append((name, result.outcome))
        if result.found and result.record is not None:
            # Open Library's own record carries a cover URL and Google's
            # carries a thumbnail from the volume record. Both are checked
            # here too: an Open Library edition record does not guarantee the
            # cover service has an image for it.
            record = result.record.with_cover(
                await covers.resolve(isbn, result.record.cover_url)
            )
            found = Lookup(
                Outcome.FOUND, record=record, source=name, attempts=attempts
            )
            async with _cache_lock:
                _remember(isbn, found)
            logger.info("Resolved %s from %s", isbn, name)
            return found

    # Asked nothing, so `_worst` has nothing to weigh: an empty `attempts` would
    # answer NOT_FOUND, which is a statement about the book rather than about
    # this library's settings.
    outcome = Outcome.NO_SOURCES if not attempts else _worst(attempts)
    missed = Lookup(outcome, source="", attempts=attempts)
    async with _cache_lock:
        _remember(isbn, missed)
    logger.info(
        "No record for %s: %s",
        isbn,
        ", ".join(f"{name}={outcome.name.lower()}" for name, outcome in attempts),
    )
    return missed
