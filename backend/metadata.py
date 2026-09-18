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
from collections.abc import Awaitable, Callable, Collection, Coroutine, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum, auto
from types import MappingProxyType
from typing import Any, Final
from xml.etree import ElementTree

import httpx
from rapidfuzz.distance import Levenshtein

import covers
import ddc
import decoders
import fetch
import google_books
import marc_fields
import sources
import targets
import z3950
from bibliographic import (
    LANGUAGES,
    flip_catalogue_name,
    is_a_disc,
    is_physical_book,
    is_placeholder_title,
    pages_from_extent,
    split_title_statement,
    strip_isbd_punctuation,
)
from catalogue import Heading, Record, Subject, uncontrolled
from enums import (
    Capability,
    CatalogueSource,
    ClassificationScheme,
)
from isbn import parse as parse_isbn
from isbn import registration_group
from models import MAX_PAGE_NUMBER_IN_A_BOOK

logger = logging.getLogger("endpaper.metadata")

#: The login each catalogue's request carries, by source.
#:
#: **`fetch.Credential` and not `credentials.Credential`**, and the difference is
#: the whole reason this is a parameter. The store reaches the ORM; this module
#: makes every outbound catalogue request and reaches no database, so it states
#: what it needs of a login and lets the caller satisfy it. That is the same
#: argument the Google Books key already uses, and the reason a credential is
#: resolved in `routers/books.py` rather than read here.
#:
#: A source absent from the mapping sends nothing, which is what every free
#: catalogue does.
Logins = Mapping[CatalogueSource, fetch.Credential]

#: No login for any catalogue, and the default everywhere one is optional.
#:
#: A `MappingProxyType` rather than a literal, so a caller cannot mutate the
#: shared default and leave another library's login on it for the next request.
_NO_LOGINS: Final[Logins] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Access:
    """What one request may ask of the catalogues, resolved once.

    Every door below used to take the three separately, and six handlers
    assembled them in the same order before each one. What that spread was the
    ability to get them out of step: a handler reaching outward twice could ask
    two different rosters, and one that resolved the plan and forgot the logins
    sent an unauthenticated request with nothing saying so.

    **Frozen, because the value being resolved once is the whole of it.**
    `routers/books.py::enrich_book` reaches outward up to three times off one of
    these, and a plan narrowed in place between two of them is exactly the defect
    resolving it once removes. A signature guard cannot see that happen; the
    type can refuse it.

    **`api_key` is `repr=False` with a `__str__` beside it, on
    `credentials.Credential`'s rule**, stated at `credentials.py:1162` and not
    restated here. Every `logins` value already prints under that same rule, so
    without it the aggregate would be the one thing here that leaks.

    **Resolved by `settings_store.library_access`, which lives there and not
    here.** This module makes every outbound catalogue request and reaches no
    database; the resolver reads settings and opens the keychain. That invariant
    is the reason, and it is the whole of it: a module level import the other
    way round does cycle, and `settings_store`'s own import block carries the
    chain it measured.
    """

    #: Which catalogues this library asks, and in what order.
    plan: sources.Plan
    #: Google Books' key, which is this deployment's own and travels in a query
    #: string. Empty where none is in force, and the plan is what decides
    #: whether Google is asked at all.
    api_key: str = field(repr=False)
    #: The login each catalogue's request carries. See `Logins`.
    logins: Logins = _NO_LOGINS

    def __str__(self) -> str:
        return f"<access to {len(self.plan.asked)} catalogue(s)>"


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

#: Open Library's own host, read off its row rather than written twice.
#:
#: **It was a literal here and a literal on the row, agreeing by luck.** An
#: address stored in two places is the fact `sources.MEASURED` refuses to store
#: twice, and here it had a second cost: a host allowlist derived from the rows
#: would have authorised a string that was not the one the request used.
_OPEN_LIBRARY: Final = targets.SEEDED[CatalogueSource.OPEN_LIBRARY].base_url

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
        # wherever the result fits `models.CLASSIFICATION_NUMBER_MAX`, which is
        # **120** characters. This comment said 40, which is not a bound this
        # application has anywhere: a `str()` of a dict or a list is well inside
        # 120 and so would be stored rather than refused, which is a larger hole
        # than the sentence described. Found by another trio and corrected here
        # because the file is this one's.
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
    return LANGUAGES.get(key.rsplit("/", 1)[-1].lower())


def _open_library_pages(raw: object) -> int | None:
    """`number_of_pages`, if it is a number of pages a book could have.

    **Bounded here rather than left to a downstream bound**, and the reason is
    what the value does rather than what any other module currently checks.
    Measured: `10**19` raises `OverflowError` on the commit, so a 500 on the
    refresh, and anything from 100,001 to `2**63-1` stores silently past the
    app's own stated ceiling, because `books.page_count` carries no CHECK. On the
    scan path the same value reaches `BookCreate`, whose `le` then 422s the
    member's own post.

    **This used to say "because nothing downstream bounds it", which was a claim
    about other modules and so a claim with an expiry date.** It was true when it
    was written. A bound added downstream makes it false without anything
    failing, and makes this function look redundant to whoever reads it next,
    which is the argument for deleting the one check that stands between a wiki
    field and the row.

    The unbounded writer is pre-existing (`pages_from_extent` and
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
            subjects=uncontrolled(_open_library_subjects(data, work)),
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


async def _google_volume(volume_id: str, api_key: str) -> Lookup:
    """Google's volume record by its own identifier, through the keyed client.

    The same three refusals `_google_books` maps, from the same exception type
    and read the same way, because they are the same endpoint's: a rejected key
    and a rate limit are the two a member can act on, and everything else is an
    outage.

    **A miss here is NOT_FOUND and says nothing about the id.**
    `google_books.lookup_by_volume_id` answers None both for a value that is not
    a volume id and for a volume id Google has never heard of, and neither is
    worth a distinct outcome: the record is not coming either way, and the
    caller that cares which it was asks `google_books.is_a_volume_id` before it
    ever gets here. See `routers/books._resolvable_volume_id`.
    """
    try:
        fields = await google_books.lookup_by_volume_id(volume_id, api_key)
    except google_books.GoogleBooksError as error:
        outcome = (
            Outcome.RATE_LIMITED if "rate limiting" in str(error) else Outcome.UNAVAILABLE
        )
        logger.info("Google Books declined volume %s: %s", volume_id, error)
        return Lookup(outcome, source="google_books")
    except (httpx.HTTPError, ValueError):
        logger.warning("Google Books volume lookup failed for %s", volume_id, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="google_books")

    if fields is None:
        return Lookup(Outcome.NOT_FOUND, source="google_books")

    # No `isbn` argument, unlike `_google_books`. There is no ISBN to fall back
    # to: the whole reason this path exists is a Book that has none, so the
    # record's ISBN is whatever Google's own `industryIdentifiers` carried,
    # parsed by `_google_isbn13` and absent where it was not a real one.
    return Lookup(Outcome.FOUND, source="google_books", record=_google_record(fields))


async def lookup_volume(
    volume_id: str, api_key: str, *, plan: sources.Plan
) -> Lookup:
    """Resolve a Google volume id, if this library asks Google Books at all.

    **One source, and that is the difference from `lookup`.** An ISBN is a name
    every catalogue in `sources.LOOKUP_SOURCES` answers to, so that function is a
    roster, a tier and a budget. A volume id is Google's own accession number
    and nothing else in the world can resolve one, so there is no chain here and
    no order to decide: the request is made or it is not.

    **Which makes the plan a gate rather than an order**, and it is the gate
    that matters. `settings_store.ready_sources` puts Google Books in the plan
    only when its own section is switched on **and** a key is in force, so
    asking `plan.asked` is asking the three questions at once: does this library
    use Google, has it a usable key, and is the provider switched on in the
    list. `Outcome.NO_SOURCES` is the answer when it is not, for that outcome's
    own reason: a provider that cannot answer has to say so, and a route that
    reported nothing found would send a member to type in a book over a setting
    they could change in one click.

    **Spending metered quota here is the point, and `Plan.lookup_together`'s
    refusal does not apply.** That rule keeps a metered source out of the tier
    asked on **every** lookup, because a bill for a book another catalogue
    already answered is a bill for nothing. Nothing else can answer this one.

    **`plan` is keyword only with no default**, which is what `access` is at the
    four doors that take one: a caller that forgot it would silently ask Google
    on behalf of a library that switched Google off.

    **The key and the plan apart, and not an `Access`**, which is the one
    exemption `tests/test_metadata.py::TestNoDoorTakesTheKeyAndThePlanApart`
    names. One bespoke target answers here and its secret is an API key in a
    query string, so there is no login to send: an `Access` would hand this door
    a keychain it drops without a word, which is the shape that makes a caller
    believe a login went out. Resolving one for this route costs a keychain
    round trip per request as well.

    **Not cached**, where `lookup` is. The cache is keyed on an ISBN and exists
    because a scan repeats: the same barcode is read twice while somebody
    checks the screen. A volume id is resolved once, during an import of a
    library that holds each book once, so a cache would hold entries nothing
    reads and evict the ISBNs that are read.
    """
    if CatalogueSource.GOOGLE_BOOKS not in plan.asked:
        return Lookup(Outcome.NO_SOURCES, source="")
    return await _google_volume(volume_id, api_key)


def _google_isbn13(fields: dict[str, Any]) -> str | None:
    """The volume's own ISBN, if it really is one.

    **Google's identifier is not validated anywhere before this.**
    `google_books._volume_to_fields` takes `industryIdentifiers` straight out of
    somebody else's JSON and picks the entry whose `type` is `ISBN_13`, without
    looking at what the `identifier` beside it is. Measured through the real
    lookup path, two shapes get through and they fail differently:

    * a 40 character string builds a `BookLookup` perfectly happily and puts a
      40 digit ISBN in front of a member;
    * a **non string** identifier, an int, a float or a bool, reaches
      `BookLookup.isbn`, which is `str`, and raises `ValidationError` inside a
      handler that catches none. That is a 500 on a scan.

    **`isinstance` and not just a parse, which is the half a one line fix
    misses.** `parse_isbn` calls string methods, so handing it the int that
    causes the second failure raises `TypeError` out of here, where
    `_google_books`' own handler does not catch it: the same 500 wearing a
    different exception. The type has to be refused
    before the value is parsed.

    Returning None puts the caller back on the canonicalised argument
    `metadata.lookup` was given, which is what the other five lookup adapters
    use unconditionally, so `Record.as_lookup`'s stated guarantee holds for
    Google too rather than holding for everything except Google.
    """
    candidate = fields.get("isbn13")
    return parse_isbn(candidate) if isinstance(candidate, str) else None


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
        # Parsed, never taken as given. `_google_isbn13` carries the two
        # measured failures and why a bare parse is not enough.
        isbn=_google_isbn13(fields) or isbn,
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
        subjects=uncontrolled(google_books.split_categories(fields.get("categories"))),
    )


#: The one construct that makes a response's size a lie. XML spells it exactly
#: this way and only in the prolog, and character data cannot contain a literal
#: `<`, so a substring test is exact rather than a heuristic.
#:
#: **Public, and it is the only name in this module that three others read.**
#: `marc.py` refuses the same construct on an upload and `opds.py` on a feed,
#: both from this constant rather than a second spelling, because two spellings
#: let one be tightened while the other stays as it was. A name read across the
#: tree is public by behaviour, and spelling it private made `opds.py` an
#: offender under
#: `tests/test_marc.py::TestNoModuleReadsAnotherModulesPrivateNames`, which
#: admits no module at all.
DOCTYPE: Final = "<!DOCTYPE"


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

    Raised as `ParseError` because all eleven callers already catch it: a catalogue
    that starts sending a doctype degrades to "this source is unavailable"
    rather than to a 500.

    **The other half is `fetch.MAX_RESPONSE_BYTES`**, which caps the bytes read
    off the wire. Both halves are needed and neither substitutes for the other:
    the cap bounds an honest body at a measured 15.28x its own size, and the
    doctype refusal bounds the one construct that makes that ratio a lie.
    """
    if DOCTYPE in body:
        raise ElementTree.ParseError("Refused a catalogue response carrying a doctype.")
    return ElementTree.fromstring(body)


# ── MARC21, shared ────────────────────────────────────────────────────────────
#
# Every source whose reader is in `decoders.MARC_READERS` speaks MARC21, and
# `marc_fields.py` is where a record is taken apart, because the upload reader
# in `marc.py` is a third profile over the same fields. What is left here is
# which fields a catalogue fills in and how it marks a role, in each source's
# own section below.


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
# parser did run `is_physical_book`, on `dc:format`, and an online record has
# no `dc:format`, so the one thing it could never reject was the one thing that
# field exists to reject. `300 $a` says "Online-Ressource" on all 28 of the 85
# records that are one.

# The value is `targets.SEEDED[CatalogueSource.DNB].base_url`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

#: Kept because the BnF parser reads Dublin Core. The DNB no longer does.
_DC: Final = "{http://purl.org/dc/elements/1.1/}"


def _dnb_record(
    fields: marc_fields.Fields,
    isbn: str | None,
    *,
    source: str = "dnb",
    read_author_identifiers: bool = True,
) -> Record | None:
    """One MARC record as book fields, or None if it is not a book.

    Shared by the lookup and the search paths. `isbn` is what the lookup already
    knows and verified; the search path has none, so the record's own is read.

    **`read_author_identifiers` is off for the OeNB and the NLG**, because
    neither carries GND numbers, so asking costs a parse and returns nothing.

    **Whether an online record is a book is asked by the caller, not here**, since
    the phrasing is per source and only the two Dublin Core sources need one.

    **A disc is refused on both paths.** It is a different object rather than a
    slower edition of the same one.

    **The Dewey number is first in `headings`**, which costs nothing and makes the
    common case the first thing a reader sees.
    """
    title, subtitle, series_name, series_index = fields.title_statement()
    if not title:
        return None
    # A cross-referenced ISBN matched a volume slot, not this book. Reporting a
    # miss is right: some other catalogue may hold the real record, and putting
    # `[Hauptbd.].` in as a title poisons the entry for good.
    if is_placeholder_title(title):
        return None

    # **The one refusal here still decided by prose, and it decides almost
    # nothing.** Measured over 510 live DNB search records on 2026-09-03, 91 are
    # discs by their own codes and `is_a_disc` names **0** of them: the German
    # for what this catalogue holds is `2 CDs`, `15 CDs`, `1 Schallplatte` and
    # `1 Track`, and `bibliographic._DISC_FORMS` spells none of those. 84 of the 91 are refused
    # anyway by the **online** half of `bibliographic._NOT_A_BOOK`, because a DNB audiobook is
    # usually a download, so the disc half has been carrying none of them and
    # **7 escape both halves**: `1 Track` twice, `2 CDs` twice, `1 CD`,
    # `1 Schallplatte`, `15 CDs`. An earlier draft of this sentence credited the
    # disc half with those 7, which inverts what they are and would send anyone
    # deleting `is_a_disc` looking for seven regressions that do not exist.
    # Both critics caught it separately. Separately again, `is_a_disc` names 7
    # records across all 2,605, and that coincidence is where the wrong 7 came
    # from.
    #
    # So this is not a language gap, it is a vocabulary gap that English shares,
    # and #124's answer covers it: every caller now applies
    # `marc_fields.Fields.describes_a_book`, which refuses all 91 on `007/00`
    # and leader/06.
    # What is left here is one asymmetry worth naming rather than half fixing:
    # this refuses outright and the caller only ranks, so a disc this misses is
    # ranked down at a lookup where one it names is a miss. Closing that means
    # giving this function the record node, a four call site signature change,
    # and it changes an answer rather than correcting one.
    if is_a_disc(fields.extent()):
        return None

    isbn = isbn or fields.isbn()
    subjects, gnd = fields.controlled_subjects()

    return Record(
        source=source,
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=fields.authors() or fields.credited_names(),
        publisher=fields.publisher(),
        year=fields.year(),
        # Through the shared reader rather than hardcoded to None, which is
        # what this was under Dublin Core. The DNB catalogues books rather than
        # blurbs and it shows: 520 appears on 1 of 85 live records measured
        # 2026-08-24. Reading it costs a function call and stops being a
        # special case that has to be remembered.
        description=fields.description(),
        language=fields.language(),
        page_count=pages_from_extent(fields.extent()),
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
        headings=tuple(fields.ddc_headings() + gnd),
        # The one catalogue here that supplies a person's identifier. K10plus
        # writes the same subfield and is deliberately not read for it: see
        # `_k10plus_record`. The ÖNB writes it too and is held to the same
        # rule: see `read_author_identifiers`.
        author_identifiers=(
            tuple(fields.author_identifiers()) if read_author_identifiers else ()
        ),
    )


# How many records the lookup asks for, where it asked for one until
# 2026-08-24. **The extra four are what let the print edition win.** `num=`
# matches any identifier anywhere in a record, including the "also published
# as" cross reference an ebook record carries for its print edition, so the
# catalogue's first answer for a printed book's ISBN is sometimes the ebook.
# Under Dublin Core there was no way to tell: `dc:format` is absent on an
# online record, so `is_physical_book` had nothing to test and the ebook was
# taken. Measured over 74 live lookups on 2026-08-24: 8 answers held more than
# one record, and asking for five rather than one puts a printed edition in
# front of an online one twice and changes no other pick.
#
# Five, the same number `targets.SEEDED[CatalogueSource.K10PLUS].lookup_records` uses,
# for the same reason: several
# printings of one book each carry the ISBN somewhere, and the best of them
# should win rather than whichever the catalogue happened to sort first.
# The value is `targets.SEEDED[CatalogueSource.DNB].lookup_records`. It became a row on the
# catalogue targets table, and what is left here is the measurement.


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

# The value is `targets.SEEDED[CatalogueSource.K10PLUS].base_url`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# Several printings of one book each carry the same ISBN, so the search
# returns a handful of near-identical records and the fullest one wins.
# The value is `targets.SEEDED[CatalogueSource.K10PLUS].lookup_records`. It became a row on the
# catalogue targets table, and what is left here is the measurement.


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


def _k10plus_record(
    fields: marc_fields.Fields,
    isbn: str | None = None,
    *,
    source: str = CatalogueSource.K10PLUS.value,
) -> Record:
    """One MARC record as book fields.

    `isbn` is passed by the lookup path, where it is already known and already
    verified. The search path has none, so it is read off 020 instead.
    """
    isbn = isbn or fields.isbn()
    title, subtitle, series_name, series_index = fields.title_statement()

    # `$2` and `$0` off the same field, which this catalogue fills in far less
    # often than the DNB does: measured 2026-08-31 over 133 live `650` fields
    # with an `$a`, 3 carry a `$2` (all `DLC`) and the same 3 carry a `$0` (all
    # `(OCoLC)fst`). Read anyway, because the alternative is a reader that is
    # correct only while a catalogue's habits hold.
    #
    # **The vocabulary belongs to the whole heading, subdivisions included.**
    # `$x` is a subdivision of the `$a` above it rather than a heading of its
    # own, so the joined string is one subject and takes the field's one `$2`.
    subjects = [
        Subject(
            " ".join(part for part in (entry.get("a"), entry.get("x")) if part),
            entry.subject_vocabulary("650"),
            entry.subject_identifier(),
        )
        for entry in fields.get("650")
        if entry.get("a")
    ]

    return Record(
        source=source,
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=fields.authors(),
        publisher=fields.publisher(),
        year=fields.year(),
        description=fields.description(),
        language=fields.language(),
        page_count=pages_from_extent(fields.extent()),
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
        headings=tuple(fields.ddc_headings()),
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
# Superseded as a ranking by `sources.MEASURED`, which times all five free
# sources on one 500 ISBN sample rather than three of them on this one.

# The value is `targets.SEEDED[CatalogueSource.OENB].base_url`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# The CQL index that means "the ISBN", **established by probing rather than by
# reading the documentation**, and it is the single fact this source was
# blocked on.
#
# The published examples establish MMS ID, AC number, barcode and title, and
# none of them establish this. Guessing it does not fail the way a wrong index
# name usually fails. Measured live on 2026-08-27 against the same ISBN:
#
# | query | numberOfRecords |
# |---|---|
# | `alma.isbn=9783825354077` | 1 |
# | `alma.isbn13=9783825354077` | **7,793,152** |
# | `zzz.qqq=9783825354077` | **7,793,152** |
#
# **An unknown index is not an error.** It is HTTP 200, no diagnostic, and the
# entire catalogue in catalogue order, of which `maximumRecords` arbitrary
# records come back. So a typo here ships plausible MARC for an unrelated
# book rather than an empty result somebody would notice, and the only thing
# standing between that and a member's shelf is `marc_fields.Fields.claims_isbn`.
#
# Confirmed the only way it can be: an ISBN was read off a live ÖNB record's
# own 020 and put back through this index, returning exactly that record.
# The value is `targets.SEEDED[CatalogueSource.OENB].isbn_index`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# The CQL index for a title word. `alma.title`, from the same explain record,
# and verified live.
#
# **One term per index reference, ANDed**, which is the shape the K10plus title search
# already uses and here it is a hard requirement rather than a precision
# preference: a bare multi-word term is refused. Measured, `alma.title=wien
# geschichte` answers 200 with SRU diagnostic 200812 `Invalid query`, where
# `alma.title=wien and alma.title=geschichte` answers with 4,885 records.
# The value is `targets.SEEDED[CatalogueSource.OENB].title_index`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# Five, for the same reason `targets.SEEDED[CatalogueSource.DNB].lookup_records` and
# `targets.SEEDED[CatalogueSource.K10PLUS].lookup_records` are five:
# several printings of one book each carry the ISBN somewhere and the fullest
# of them should win rather than whichever the catalogue sorted first.
# The value is `targets.SEEDED[CatalogueSource.OENB].lookup_records`. It became a row on the
# catalogue targets table, and what is left here is the measurement.


# ── The National Library of Greece ────────────────────────────────────────────

# The Greek legal deposit catalogue, over SRU.
#
# **Plaintext HTTP by necessity, which is the second source here that is.**
# Port 210 speaks no TLS, and `https://catalogue.nlg.gr` on 443 is a different
# service that answers 404 to this path. Both measured 2026-08-30.
#
# So this carries the exposure `targets.SEEDED[CatalogueSource.LOC].base_url` already
# documents: the ISBN or the
# title asked about travels in clear, and anyone on the path, or anyone
# answering DNS for the pod, can answer for the catalogue.
#
# `fetch.RedirectedOffHost` refuses any hop off this host on both paths, so a
# forged reply cannot turn a request into a GET somewhere else, which is the
# SSRF.
#
# **The identity check covers one of the two paths and not the other, and the
# difference is worth stating rather than leaving to be inferred.** the NLG lookup
# filters through `Fields.claims_isbn`, so a forged body has to be a plausible
# MARC record for the book the member scanned rather than for any book.
# the NLG title search has no identifier to check against, exactly as the Library of Congress title search
# has none, so a forged body there can offer any row it likes. What stands
# between that and a shelf is the same thing that stands there for the Library
# of Congress: a person reads the row and picks it. The search path's exposure
# is the Library of Congress's, not narrower.
# The value is `targets.SEEDED[CatalogueSource.NLG].base_url`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# The CQL index that means "the ISBN", established by probing. The endpoint
# answers `explain`, and its explain record carries the record schemas and no
# index list at all, so the documentation could not settle this.
#
# **A wrong index here fails loudly, unlike the ÖNB's**, and the defence built
# for that one is kept all the same. Measured 2026-08-30 against this endpoint:
#
# | query | answer |
# |---|---|
# | `dc.isbn=9789600426656` | 1 record |
# | `isbn=9789600426656` | 1 record |
# | `bib.isbn=...`, `srw.isbn=...` | SRU diagnostic 1/15, unsupported context set |
# | `bath.title=...`, `cql.anywhere=...` | SRU diagnostic 1/16, unsupported index |
# | `dc.identifier=9789600426656` | 0 records |
#
# None of them answers with the catalogue, which is what `alma.isbn13` did at
# the ÖNB. Confirmed the only way it can be: an ISBN read off a live NLG record
# and put back through this index returns exactly that record, in 0.186s.
# The value is `targets.SEEDED[CatalogueSource.NLG].isbn_index`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# The CQL index for a title word, ANDed one term per reference like the two
# SRU sources above.
#
# **The AND is applied rather than ignored**, which is the thing to check on a
# target whose explain record lists no indexes: measured 2026-08-30,
# `dc.title=zorba` answers 15 and `dc.title=zorba and dc.title=xyzzyqq`
# answers 0. A target that ignored the second term would have answered 15
# twice and every search here would have been one word wide.
# The value is `targets.SEEDED[CatalogueSource.NLG].title_index`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# Five, for the reason `targets.SEEDED[CatalogueSource.OENB].lookup_records` is five: one ISBN reaches several
# printings and the fullest of them should win.
# The value is `targets.SEEDED[CatalogueSource.NLG].lookup_records`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# What one title search may bring back.
#
# **This endpoint does not clamp `maximumRecords`, so this number is the only
# bound there is.** Measured 2026-08-30, asking for 200 returns 200 records
# where the ÖNB silently caps at 50. `fetch.MAX_RESPONSE_BYTES` is the backstop
# and it is a byte count rather than a record count, so a catalogue with fat
# records could spend the whole cap before this fired. Fifty is the same
# ceiling the ÖNB title search asks for, so the fan out's worst case is unchanged.
# The value is `targets.SEEDED[CatalogueSource.NLG].search_cap`. It became a row on the
# catalogue targets table, and what is left here is the measurement.


# Whether a component part is refused here is
# `targets.SEEDED[CatalogueSource.NLG].refuses_component_parts`, and this is
# the measurement behind it.
# Every MARC record in an NLG response that describes a whole publication.
#
# **The component part filter is here on the concept, not on a measurement
# that needs it.** Measured over 400 live records on 2026-08-30, drawn from
# eight title searches and not the same sample as the 500 record probe behind
# `Fields.isbn`'s own 020 table, the leader bibliographic level is `m` 371 times and
# `s` 29 times, and a component part appears **zero** times, where the same
# measurement at the ÖNB found 55.4%.
# It is kept because an article is never a book in any MARC21 catalogue and
# reading one leader costs nothing, and it is documented because the next
# reader would otherwise have to re-measure to know whether it is load
# bearing here. It is not, today.
#
# A serial is not refused, which is the ÖNB's decision and is not re-taken
# here: refusing them is a decision about what this app catalogues.
# """


# ── The Czech National Library ────────────────────────────────────────────────

# The Czech legal deposit catalogue, over SRU with a PQF query.
#
# **Plaintext HTTP, the third source here that is**, for the same reason as the
# other two: port 9991 offers no TLS. `targets.SEEDED[CatalogueSource.NLG].base_url`
# carries the reasoning in full
# and it applies unchanged, with one difference in this source's favour. It
# answers **only** an ISBN lookup, so every record it returns is checked against
# the ISBN that was asked for by `_nkp_claims_isbn`. There is no search path
# here for a forged body to reach.
#
# **The database path is load bearing and the ticket did not have it.**
# `aleph.nkp.cz:9991` alone, and `/biblios`, both answer SRU diagnostic 1/235,
# "database does not exist". Measured 2026-08-31.
# The value is `targets.SEEDED[CatalogueSource.NKP].base_url`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# The parameter this target takes a query in, and it is not `query`.
#
# Measured 2026-08-31: `query=` with CQL answers diagnostic **1/11**,
# unsupported query type, and `queryType=x-pquery` answers **1/8**, unsupported
# parameter, so the SRU 2.0 spelling does not reach it either. The query goes in
# its own `x-pquery` parameter, which is YAZ's SRU 1.1 extension.
# The value is `targets.SEEDED[CatalogueSource.NKP].query_parameter`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

# One record, because this target renders exactly one whatever is asked for.
#
# **The other four SRU sources ask for five and rank the fullest.** That would
# be four empty stubs and a wasted page here: measured 2026-08-31 across three
# queries and four page sizes, a response carries data at position 2 of 2, 3 of
# 3, 5 of 5 and 20 of 20, and nowhere else. Over eight title searches at fifty
# records, 391 of 400 records were empty. Asking for one is the only size at
# which what arrives is what was requested.
# The value is `targets.SEEDED[CatalogueSource.NKP].lookup_records`. It became a row on the
# catalogue targets table, and what is left here is the measurement.


# The PQF for one ISBN lookup is built by `targets.Target.isbn_query` off
# `targets.SEEDED[CatalogueSource.NKP].isbn_attribute`, and this is the round
# trip that established it.
# The PQF for one ISBN lookup, built by `z3950`.
#
# **Established by round trip, not by reading the attribute set.** An identifier
# read off a live record, `978-3-319-52267-8`, put back through `@attr 1=7`
# returns exactly that record, and so does its normalised form
# `9783319522678`: the target folds the hyphens itself. Twenty ISBNs harvested
# from this catalogue's own records and put back through it returned a populated
# record **20 of 20** on 2026-08-31.
#
# **Neither half of that query is spelled here, and the reason is the bug this
# adapter already shipped once.** It first carried a local `_pqf_literal` that
# removed the double quote and stopped there, on the stated ground that a quote
# is the only character able to end a PQF literal. That is false, and
# `z3950.pqf_term` had said so since 2026-08-28 from live `p_query_rpn`
# renderings: an `@` followed by a digit is read **before** the quoted run, so
# `@1=1016 praha` survives quoting and repins the use attribute, and a trailing
# backslash escapes the closing quote. So it was a guard being wrong rather
# than a leak being open, and `z3950.pqf_term` is the whole reason that is
# true.
#
# **The second reason this paragraph used to give was itself false.** It said
# the shape was "not reachable through `parse_isbn`, which yields thirteen
# ASCII digits or nothing". `parse_isbn` gated on `str.isdigit()` alone, which
# is true of every Unicode digit, so it yielded thirteen characters that were
# not all ASCII: `POST /api/books` stored an ISBN ending in an Arabic-Indic
# zero. The sentence is true now, since `isbn.is_valid_isbn13` narrows to
# ASCII, and it is written down this way because the code was defensible while
# one of the two reasons for it was not.
#
# The attribute was then the same defect one level up: a local `@attr 1=7`
# beside `z3950.USE_ISBN`, in a module whose `isbn_query` already names this
# catalogue by name in its own measurement. So the whole query comes from
# there, and what stays here is the round trip above, which is this adapter's
# measurement rather than PQF's rule.
#
# `z3950.isbn_query` refuses an empty, over-long or control-bearing term with
# `BadQuery`. A canonical ISBN reaches none of those; a future caller can, and
# the NKP lookup turns it into an unavailable answer rather than a 500.


#: The Dublin Core element names this reader wants, un-namespaced.
#:
#: **The BnF's selector cannot see these records and that is not a fixable
#: oversight.** It looks for `{http://purl.org/dc/elements/1.1/}title`; this
#: target writes `<record-list><dc-record><title>` with no namespace at all, so
#: the same query returns zero. Measured against a live body.
_NKP_RECORD: Final = "dc-record"


def _nkp_records(root: ElementTree.Element) -> list[ElementTree.Element]:
    """Every Dublin Core record element in an NKP response.

    **A record with no `recordData` is ordinary here rather than broken**, which
    is the single most surprising thing about this source: 391 of 400 records
    measured on 2026-08-31 carried none.

    **This filters nothing, and an earlier version of this docstring said it
    did.** It searches the whole tree for `dc-record` elements, and an empty
    `<record>` simply holds none, so the empty ones fall out of the search rather
    than being rejected by a test here. The distinction matters to whoever adds a
    filter: there is no "populated" predicate to extend, and a record that
    carried a `dc-record` with no useful children would be returned.
    """
    return list(root.iter(_NKP_RECORD))


def _nkp_text(record: ElementTree.Element, tag: str) -> list[str]:
    """Every non empty value of one un-namespaced element."""
    return [
        element.text.strip()
        for element in record.findall(tag)
        if element.text and element.text.strip()
    ]


def _nkp_claims_isbn(record: ElementTree.Element, isbn: str) -> bool:
    """Whether this record names the ISBN that was asked for.

    The same defence `marc_fields.Fields.claims_isbn` is for the MARC sources, in the one
    shape Dublin Core offers: `identifier` carries the ISBN, hyphenated as the
    catalogue prints it, and `isbn.parse` folds both sides to one form. A
    plaintext connection is the reason it is here even though this target
    diagnoses a wrong attribute rather than answering with the catalogue.
    """
    return any(
        parse_isbn(value) == isbn for value in _nkp_text(record, "identifier")
    )


#: What this catalogue calls an online resource.
#:
#: **`bibliographic._NOT_A_BOOK` is written in German and English and does not reach Czech.**
#: `online[- ]?(?:ressource|resource)` and `elektronische ressource` match
#: nothing in `1 online zdroj (106 pages) :`, which is what this catalogue writes
#: and which appeared in the first record ever probed from it. So the refusal
#: that keeps a digitised copy off a shelf was language scoped, and silently, for
#: every catalogue that is not German or English.
#:
#: **Added here rather than to `bibliographic._ONLINE_FORMS`, deliberately.** Widening the
#: shared pattern is the tempting move and it changes what every other source
#: refuses, on a phrase measured in one catalogue. This source states its own
#: and `test_metadata.py` pins that the shared rule is unchanged.
#:
#: **#124 asked whether the rule should be per source everywhere and the answer
#: was no**: it is per source exactly where the record carries no code, which is
#: the two Dublin Core sources and nowhere else. `marc_fields` holds
#: the reasoning and `_BNF_ONLINE` is the other half of the pair.
#:
#: **This source is the harder of the two and is why the pair exists.** Its
#: `dc:type` is `text` on 118 of the 119 live records measured on 2026-09-03,
#: including on an online resource, so no type gate separates anything here and
#: the format prose is genuinely all there is. Widening the type gate to fix the
#: BnF would refuse this whole catalogue: see `_BNF_PRINTED`.
_NKP_ONLINE: Final = re.compile(r"online\s+zdroj|elektronick\w*\s+zdroj", re.IGNORECASE)


def _nkp_record(
    record: ElementTree.Element, isbn: str, *, source: str
) -> Record | None:
    """One bare Dublin Core record as book fields, or None if it is not a book.

    **`source` is keyword only and passed in rather than spelled here**, because
    two catalogues write this dialect: the Czech National Library and the Biblioteca Nacional
    Argentina. It was a literal `"nkp"` until the second one arrived, at which
    point a live Argentine lookup returned a `Lookup` labelled `bna` carrying a
    `Record` labelled `nkp`, and `Record.source` is what
    `_MATCH_PRECEDENCE`, `_SECONDARY_SOURCES`, `_merge_matches` and the
    attribution on a member's screen all read. Named after the first of the two
    for the reason `_dnb_record` is, which reads four MARC catalogues.

    **Contributors rather than creators, because this catalogue writes no
    creator at all.** Measured 2026-08-31 over the **9 records that carried
    data**, out of 400 fetched: `creator` appears **0** times and `contributor`
    appears on 8 of the 9. So a reader that looked for `creator`, as the BnF's
    does, would give every Czech book no author rather than a wrong one.

    **The denominator is 9 and not 400, and both numbers matter for different
    reasons.** 400 is what it cost to see 9, which is
    `targets.SEEDED[CatalogueSource.NKP].lookup_records`' whole
    argument. 9 is what the rules below rest on, and it is a thin sample: an
    earlier version of this docstring quoted the 400 as though `creator` had been
    looked for that many times.

    **And the first contributor only.** Those 9 carry up to three per record, and
    the trailing ones are the publisher's supply chain rather than the book's
    authors: `ProQuest (firma)` sits beside the translator and the author on the
    record this was read off. `firma` is Czech for a company.

    **Nothing was observed with the firm first**, so nothing tests it, and
    positional selection is not the same rule as filtering firms. Recorded rather
    than guarded because a filter guessed from one example is the shape this
    repository keeps paying for: `bibliographic._NOT_A_BOOK` widened on an unmeasured phrase is
    the same mistake with a different constant. A real contributor role reader
    belongs to whichever ticket gives this source a second measurement.
    """
    titles = _nkp_text(record, "title")
    if not titles:
        return None

    # Printed books only, the same rule and the same constant the BnF uses:
    # this catalogue writes `text`, which `_BNF_PRINTED` already holds.
    kinds = " ".join(_nkp_text(record, "type")).casefold()
    if kinds and not any(kind in kinds for kind in _BNF_PRINTED):
        return None

    # `Ostře sledované vlaky /` is how this catalogue writes it: the ISBD slash
    # introduces a statement of responsibility that is not in this record at
    # all, so `split_title_statement` has nothing to split off and leaves it.
    title, subtitle = split_title_statement(titles[0])
    title = strip_isbd_punctuation(title)
    # **Both halves, and the subtitle half was missing.** `split_title_statement`
    # drops a statement of responsibility only where the slash has a space after
    # it, and both catalogues in this dialect write `main : sub /` with nothing
    # following, so the slash survives into the subtitle. The title beside it
    # was already stripped and the subtitle was not, so `El mundo gamer` came
    # back with `del juego al reclutamiento /` under it, measured over 10 live
    # Argentine records on 2026-09-07, 3 of which carry a subtitle and all 3 of
    # those ended in a slash. Stripped here rather than inside
    # `split_title_statement`, which the BnF and the DNB also call.
    subtitle = strip_isbd_punctuation(subtitle) if subtitle else None
    if is_placeholder_title(title):
        return None

    extent = next(iter(_nkp_text(record, "format")), None)
    # Two refusals rather than one: the shared rule for the forms every source
    # writes, and this catalogue's own Czech phrasing, which the shared one
    # cannot see. See `_NKP_ONLINE`.
    if not is_physical_book(extent, title) or (
        extent is not None and _NKP_ONLINE.search(extent)
    ):
        return None

    contributors = _nkp_text(record, "contributor")
    year_match = re.search(r"\d{4}", " ".join(_nkp_text(record, "date")))
    publisher = next(iter(_nkp_text(record, "publisher")), None)

    return Record(
        source=source,
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=flip_catalogue_name(contributors[0]) if contributors else None,
        publisher=strip_isbd_punctuation(publisher) if publisher else None,
        year=int(year_match.group()) if year_match else None,
        language=LANGUAGES.get((_nkp_text(record, "language") or [""])[0].lower()),
        page_count=pages_from_extent(extent),
        cover_url=covers.open_library_url(isbn),
        # The un-namespaced dialect, and it has no more room for a stamp than
        # the namespaced one: see `catalogue.uncontrolled`.
        subjects=uncontrolled(_nkp_text(record, "subject")),
    )


# ── The Spanish National Library ──────────────────────────────────────────────

# The Biblioteca Nacional de España, over Alma's SRU, and its profile is the
# Austrian National Library's: SRU 1.2, CQL, `alma.isbn`, `marcxml`, MARC21 read
# by `_dnb_record`. It needed no adapter at all, which is the property
# `targets.py` was rearranged to have.
#
# **The address is the OPAC hostname, and finding it is the whole of this
# entry.** Two earlier surveys recorded Spain's national library as closed. Both
# measured `z3950.bne.es`, which authenticates and answers every database name,
# real or invented, with the identical access control failure, so no database
# name can be established there without a credential. `catalogo.bne.es` was read
# as an OPAC and never asked for SRU. It is Alma fronted: `/sru` answers an Ex
# Libris error report, which is what says what is behind it, and
# `/view/sru/34BNE_INST` answers a 186,457 byte explainResponse naming 414
# indexes and eight record schemas. Measured 2026-09-05.
#
# **An unknown index answers with the catalogue, exactly as the OENB does.**
# `alma.zzzqqq=9786077428893` returns **6,285,115 records** under HTTP 200 with
# no diagnostic; so does an unknown context set. That is the #5 failure
# reproducing at a second Alma target, and it is why
# `targets.SEEDED[CatalogueSource.BNE].requires_isbn_claim` is not a preference:
# a mistyped index here ships well formed MARC for an arbitrary book. The index
# name is pinned by `targets._INDEX` and the identity check by
# `Fields.claims_isbn`, and both have to fail before that reaches a shelf.
#
# **The `020 $z` trap the NLG documents reproduces here too.**
# `alma.isbn=0000000000000` returns one record whose only match is `$z`, the
# cancelled ISBN subfield. `Fields.claims_isbn` reads `$a` only and already
# refuses it, so this is recorded rather than guarded a second time.
#
# ISBN forms normalise, which the two Spanish ministry catalogues notably do
# not: `978-607-742-889-3`, `9786077428893` and `6077428892` each return the one
# record. So a normalised ISBN is what this target wants.
#
# **`100 $0` is a BNE authority number**, `XX1098899` rather than a `(DE-588)`
# GND URI, so `reads_author_identifiers` is False here for a different reason
# than at the OENB: not a decision withheld, but an identifier scheme
# `_dnb_record` does not read.
#
# **And its live records contribute no `Heading`, which is a fact about this
# catalogue and not about the reader.** The distinction cost two rounds here, so
# it is stated rather than implied: `classifications.bounded_headings` bounds
# what `_merge` can concatenate by counting the sources whose **reader** builds
# a `Heading`, and this row's reader is `_dnb_record`, which builds them from
# `082` and from a `(DE-588)` `$0`. Fed a record carrying either, it returns
# them, and nothing on this row suppresses that. So this source counts toward
# that bound whatever its records happen to hold this week, and the figures
# below do not move it.
#
# What they do describe is what Spanish cataloguing practice supplies today.
# Measured over 400 live records on 2026-09-05:
#
#   * `082`, which is all `Fields.ddc_headings` reads: **0 of 400**. Classification here
#     is `080`, UDC, on 272 of the 400, and nothing in this tree reads UDC.
#   * the subject tags `Fields.controlled_subjects` walks, `650 651 655 689 600`: **459**
#     datafields across the 400 records, carrying **0** `$0` subfields of any
#     kind, so **0** begin with `(DE-588)` and none becomes a `Heading`.
#     it appends only where `Subfields.gnd_identifier` answers.
#
# **Neither figure is the count in `classifications.bounded_headings`**, and
# both wrong readings of that were made here before the right one. Raising it on
# `650` being *present* is wrong because presence of the tag is not presence of
# a GND identifier. Lowering it on these two zeros is wrong for a larger reason:
# it would make a bound that a third party can falsify by adding one `082` to
# one record, with nothing in this tree noticing. That is sampling the tail
# rather than bounding it, which is the mistake `fetch.MAX_RESPONSE_BYTES`
# records against the 1 MB proposal. The count is structural and this row is in
# it.
#
# What it answers, over the 500 ISBN sample committed at
# `tests/fixtures/catalogue_survey_2026_08_31.json`, measured 2026-09-05 in one
# serial pass with nothing else in flight:
#
#   * **14 of the 15 Spanish ISBNs the free chain misses**, which is the figure
#     that decided it. #5 admitted the Austrian National Library on 3 of 50.
#   * 57 of 500 overall: 47 Spanish, 3 Italian, 3 Portuguese, 2 Argentine,
#     2 Uruguayan, and nothing in the four non Romance frames.
#   * Lookup latency min 0.122s, median 0.155s, p90 0.276s, max 1.030s.
#
# **Its `serves_groups` is deliberately empty**, and that is a measurement
# rather than an omission. The rule in `sources.SERVES_GROUPS` is that a remit
# is listed only where no book the source alone answers falls outside it, and
# this one alone answers **four** books outside `978-84`: one Portuguese, one
# Argentine and two Uruguayan. A `978-84` remit would stop it being asked about
# all four, which is precisely the silent failure that rule exists to prevent.
# So Spanish language publishing outside Spain is reached here, by a catalogue
# whose legal deposit does not cover it.
#
# **It answers no title search, and the reason is ours rather than the
# server's.** Its search works: 30 records, which is what a `search_multiplier`
# of 3 would ask for a limit of 10 and is what every other search row carries,
# answers in 1.117s median over 15 samples, and its largest measured page
# is 341,362 bytes under `accept-encoding: identity`, which it honours. What was
# never measured is what a search here would **find** that the roster does not,
# and **no incumbent search source has that measurement either**: the BnF and
# the Library of Congress hold their slots on the reverse argument, that neither
# was worth an ISBN request. So this is the conservative default for a new
# source and not a bar the others cleared. At 50 records it costs 2.448 to
# 5.911s against a 4.0s whole fan out, so the cheap version of the question is
# not free either. `sources.SEARCH_SOURCES` carries the full argument.

# ── The Biblioteca Nacional Argentina ─────────────────────────────────────────

# Argentina's legal deposit catalogue, and the Czech National Library's row with
# a different address: SRU 1.1, PQF in `x-pquery`, use attribute 7, no
# `recordSchema`, bare Dublin Core through `_nkp_record`. It needed no adapter,
# which is the second time that property has paid for the way `targets.py` is
# arranged.
#
# **The credential is the gate and the transport is ordinary.** #91 inferred
# that from the refusal being identical over both protocols; it is now a round
# trip rather than an inference. Measured 2026-09-07 against
# `targets.SEEDED[CatalogueSource.BNA].base_url`, YAZ 4.2.66:
#
#   * unauthenticated, `operation=searchRetrieve` with `x-pquery`: HTTP **200**
#     carrying SRU diagnostic `info:srw/diagnostic/1/3`, `Authentication error`,
#     with details naming an Aleph service code and **the user name the request
#     carried**, truncated by the target's own parser. A refusal arrives as a
#     diagnostic under a 200, which is why `_sru_refusal` is what separates this
#     from an empty answer, and the details are the one part of a diagnostic
#     nothing here logs or quotes: they are half a login at this target, so they
#     are described rather than reproduced, here as well as in a log line.
#   * the same request under HTTP Basic: `numberOfRecords` and a record.
#   * `recordSchema=marcxml`: diagnostic 1/66, measured 2026-09-06 and recorded
#     on the ticket rather than here. So the ticket's parameter table, which
#     says MARC21, describes the **Z39.50** route and not this one.
#
# **This tree ships the credential the library publishes about itself**, on its
# own page for librarians, `bn.gov.ar/bibliotecarios/protocoloZ3950`, beside a
# contact address and with no stated restriction on use. Owner's decision of
# 2026-09-07, taken against the refusal of the trio that added this row; both
# sides are kept in `docs/decisions.md` and the argument is at
# `targets.ShippedCredential`.
#
# **What makes it safe is that it loses to anything else.**
# `credentials._resolve` walks a variable the deployment pinned, then a login an
# admin entered, then this. An institution with its own arrangement with the
# library uses that arrangement, and does not have to ask anyone to be allowed
# to. Replaceability is a requirement of the decision rather than a consequence
# of the implementation, so it is the property to check before changing anything
# here.
#
# **What it costs, stated rather than left to be discovered.** Every install now
# asks a plaintext Argentine catalogue about any ISBN the sources above it miss,
# where before only an install that had entered a login did. This row declares
# an empty `serves_groups`, so that is every miss rather than the Argentine
# ones: the member's ISBN reaches a further third party, the library sees fan
# out from one account for books it is unlikely to hold, and the tail pays a
# request for a source that will usually answer nothing.
#
# **Narrowing it was measured on 2026-09-07 and refused, and the refusal is the
# measurement's answer rather than a deferral.** Argentina's groups are
# `978-950` and `978-987`; the question a remit turns on is what this catalogue
# answers *outside* them, and this sample cannot be asked it. This source has no
# column in the 500 rows, and the pass below covered the fifty Argentine rows
# only, so 450 were never put to it. Inside those fifty the answer is vacuous by
# construction: all 50 carry an Argentine group, 36 `978-950` and 14 `978-987`,
# so the remit would have refused 0 of the 10 answers because the frame holds
# nothing for it to refuse.
#
# **What is measured points the other way.** Over the five sampled sources with
# a country of their own, the DNB, the OeNB, the NLG, the NKP and the BNE, the
# share of yield outside the source's own groups runs 0% at the NLG to 17.5% at
# the BNE. Named rather than counted, because "national catalogue" is used
# further down this module to mean the five added most recently, which excludes
# the DNB and would make the same sentence read four. So a group rule is not
# disqualified by
# most of the yield sitting elsewhere. It is disqualified by the bar in
# `sources.SERVES_GROUPS`, which is zero books lost, and by the nearest measured
# analogue failing that bar worst: 4 of the 18 books the BNE alone answers fall
# outside `978-84`, and **one of the four is Argentine**. A Spanish catalogue
# holds an Argentine book this chain has nowhere else, which is exactly the
# shape a `978-950` remit here would lose in the other direction.
#
# **And there is nothing else for a remit to key on.** `Plan.lookup_in_turn`
# takes a registration group, and a group is the only thing an ISBN carries
# about where it came from. Another key means another input, and on the lookup
# path, before any record comes back, there is none. Moving this needs the 500
# put to this catalogue, which is a probe rather than a pass over the fixture.
#
# **A rotated credential has to read as a credential**, which is the ticket's
# own requirement and was not true of this application before this row. Any SRU
# diagnostic now makes the source unavailable rather than empty handed, so a
# credential that stops working reads as "this catalogue could not be asked".
# `_sru_refusal` carries the rule and why it is structural rather than a list of
# diagnostic numbers.
#
# **Plaintext, and here that is a sharper statement than at the other three.**
# Port 9991 speaks no TLS, so the request and every record cross the network in
# clear, and this is the one catalogue request in the application that carries
# an `Authorization` header. `credentials.Credential.header_for` binds that
# header to this origin, and `fetch._same_host_hop` refuses a redirect off it;
# the two are deliberately separate guards, because a redirect leaking a page is
# an information leak and one carrying this header is account theft. What no
# guard here can fix is that the credential is Basic over plaintext to begin
# with, which is what the library published and is the whole of what it
# protects: a catalogue nobody's library card opens.
#
# **One populated record per response, whatever page size is asked for**, which
# is the Czech National Library's property at a second Aleph target. Measured
# 2026-09-07: an ISBN with two hits, at `maximumRecords=5`, answers two
# `<zs:record>` elements and **one** `recordData`. So `lookup_records` is 1 and
# `answers_search` is False, the second being forced anyway because
# `targets.Target._check_sru` allows a search only on a CQL target.
#
# What it answers, over the fifty Argentine rows of the 500 ISBN sample
# committed at `tests/fixtures/catalogue_survey_2026_08_31.json`, one serial
# pass on 2026-09-07 with nothing else in flight:
#
#   * **10 of the 50**, and **4 of the 26 that the seven sources needing no
#     credential miss**. Seven and not eight: the eighth is this source, and
#     a count of what it adds cannot count itself. A stock install asks this one
#     too, because it ships its library's published login.
#     The frame goes from 24 answered to 28.
#   * Lookup latency min 0.496s, median 0.516s, p90 0.529s, max 0.530s, over all
#     fifty, which is the tightest spread of any source here and is one Aleph
#     answering from one machine.
#   * 10 of 10 records parsed as books through the reader unchanged, and 10 of
#     10 named the ISBN asked for, so `requires_isbn_claim` refused nothing.
#
# **4 is the number to plan against and the ticket says 56.0%.** That figure is
# a coverage claim over a different sample and it is not what this pass found:
# against the committed one, what this source uniquely answers is four books in
# five hundred. It is admitted on the tail's terms, where the OENB sits on one,
# and it would not clear `sources.SLOT_MUST_EARN` for a tier slot.
#
# **The Spanish for an online resource is not refused**, and that is recorded
# rather than guarded. `_NKP_ONLINE` is Czech and `bibliographic._NOT_A_BOOK` is German and
# English, so `1 recurso electrónico` would reach a shelf here. None of the ten
# records measured is one, so there is nothing measured to write a pattern
# against, and a refusal guessed from no example is the mistake `_NKP_ONLINE`'s
# own comment records. Whichever ticket gives this source a second pass writes
# it, from records rather than from a dictionary.

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
# install runs.** Two sources need a credential (`sources.NEEDS_A_KEY`), one of
# them ships the login its library publishes and the other does not, so the
# chain most deployments actually run is the eight sources a stock install asks.
# Measured over 500 domestic ISBNs across ten frames, it answers 399 and misses
# 101, and outside German language publishing it misses 97 of 400.
#
# The four books between that and the figure this module quoted before are the
# Argentine row's: the seven sources that need nothing answer 395 and miss 105,
# and the row above uniquely adds 4 of those.
#
# The same 500 books
# under the roster of three releases
# ago, and the previous `020` rule, answered 300. So a sentence anywhere in this module saying
# the chain covers a country is a statement about a **keyed** install. #91
# measured the size of that on the same books, Italy 36% missed keyless against
# 0% with a key and Greece 86% against 54%; **that keyed half is #91's
# measurement and is not re-derived here**, because the seat that wrote this had
# no key. The per source figures and the frames: `sources.MEASURED`.

#: The ISBN lookup adapter for a transport that is neither SRU nor Z39.50.
#:
#: **Two entries where there used to be seven**, and the five that left are the
#: whole ticket: every SRU source now shares `_sru_lookup`, driven by its row.
#: What is left is the two catalogues with a JSON API of their own, and they are
#: keyed on the reader rather than on the source for the same reason the search
#: tables are: a reader is what a row names.
#:
#: `metadata.resolve` is what stops a row naming a reader that is not in here.
#: The bespoke lookup **adapters**, by `decoders.Reader`, and the word is not
#: decoration.
#:
#: **These fetch as well as decode, and they are the one place in the roster
#: where the two are still welded.** Splitting them is a rewrite of two JSON
#: adapters rather than a seam over what is there, so it is out of this ticket's
#: scope. The decoder is already separate inside each: `_open_library_edition`
#: and `_google_record` take parsed JSON and return a `Record`, and neither
#: mentions a request. What is missing is only the registry entry for them.
_BESPOKE_LOOKUPS: Final[
    dict[decoders.Reader, Callable[[str, str], Awaitable[Lookup]]]
] = {
    decoders.Reader.OPEN_LIBRARY: _open_library,
    decoders.Reader.GOOGLE_BOOKS: _google_books,
}

#: Bookland registration group for German-language publishing.
#:
#: **Not converted to `isbn.registration_group(isbn) == "978-3"`, deliberately.**
#: The two denote exactly the same set, because 3 is a single digit group, so it
#: would be a rename rather than a fix. And the tidier looking version is worse
#: here: `covers.py` keeps its own `_GERMAN_PREFIX = "9783"` for a different
#: question, so converting one of the two leaves the repository with two
#: **different** spellings of one registration group instead of two identical
#: ones. Converting both is a change to a subsystem #122 had no reason to touch.
#: Recorded here rather than in a session note, which is deleted when the wave
#: ships.
_GERMAN_PREFIX: Final = "9783"

#: Which of the fast pair to believe when both answer and they disagree.
#:
#: For a German ISBN the legal deposit library is the authority on its own
#: publishing. For anything else K10plus is preferred: it holds foreign books
#: as first-class records, where the DNB holds them mostly as cross references,
#: which is the failure `is_placeholder_title` exists to catch.
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
                language=LANGUAGES.get((doc.get("language") or [""])[0].lower()),
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
#: CQL boolean keywords. A search for "black and white" must not become two
#: terms joined by an operator. The characters that would do the same thing are
#: `targets.CQL_STRUCTURE`, which this used to sit under a stale copy of.
_CQL_KEYWORDS: Final = frozenset({"and", "or", "not", "prox"})

#: Below this a term is noise in a catalogue index: initials, articles, and the
#: single letters left behind by stripping punctuation.
_MIN_TERM_LENGTH: Final = 2


def _search_terms(query: str) -> list[str]:
    """The query as safe, meaningful, ANDable terms.

    **Every term returned has been through `targets.cql_term`**, and that is a
    guarantee rather than a coincidence of the strip above it. This function
    used to carry its own copy of the CQL metacharacter class, one character
    different from the one in `targets.py`: `\\s` was in the refusing spelling
    and not in the stripping one. Two spellings of one rule is the defect the
    Czech National Library block records having shipped once already, in the
    other query language, so there is one class now and this is a caller of it.

    **The two halves of that class are stripped differently, and a critic
    measured why.** A relation character joins two things, so it becomes a
    space. A masking character sits inside one word, so it is deleted:
    `har*ry potter` was becoming `har AND ry AND potter`, three title words that
    find nothing, where the target would have masked it to "harry potter".
    Deleting gives `harry potter`. `targets._JOINS` and `targets._MASKS` are the
    two halves and `targets.CQL_STRUCTURE` is their union, composed rather than
    spelled again.

    A term the strip could not make safe is dropped rather than raised on, which
    is this function's contract and not `cql_term`'s. A control character is the
    reachable case: `str.split` does not treat one as whitespace, so it survives
    into a term.
    """
    cleaned = targets.CQL_JOINS.sub(" ", targets.CQL_MASKS.sub("", query))
    terms: list[str] = []
    for term in cleaned.split():
        if len(term) < _MIN_TERM_LENGTH or term.lower() in _CQL_KEYWORDS:
            continue
        try:
            terms.append(targets.cql_term(term))
        except targets.BadQuery:
            continue
    return terms


def _fullest_physical(
    books: list[tuple[marc_fields.Fields, Record]],
) -> Record:
    """The fullest of several records for one ISBN, a book before a digitisation.

    **The three lookups this serves ranked on `completeness` alone and refused
    nothing**, where the DNB has carried the physical test in its ranking key
    since the halves were split. Measured over the cached bodies of 210 live
    K10plus ISBN lookups on 2026-09-03: 9 answered with a physical **and** a non
    physical record in the same response, and **8 of those 9 returned the non
    physical one**, because a digitisation is often the fuller record. That is a
    member scanning a barcode and being handed the wrong object, and it needed no
    foreign language to happen. The ÖNB and the NLG carry the same gap and the
    same fix; measured on the same day it changes 0 of 55 and 0 of 37 answers
    there, so this is one source's live defect and two sources' consistency.

    **31 of those 210 are answered only by records this refuses**, and they stay
    answered, which is what makes the paragraph below a decision rather than an
    omission.

    **A rank and not a refusal**, which is the DNB's documented asymmetry, now
    carried on `targets.Target.requires_isbn_claim`, and is re-taken here rather
    than assumed: an online resource is this book in another
    form, so when it is the only answer it is better than reporting a miss. A
    search has no ISBN to tie the two together and refuses outright instead.
    """
    return max(
        books,
        key=lambda book: (
            book[0].describes_a_book(book[1].title),
            book[1].completeness,
        ),
    )[1]


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

# The value is `targets.SEEDED[CatalogueSource.BNF].base_url`. It became a row on the
# catalogue targets table, and what is left here is the measurement.
# The value is `targets.SEEDED[CatalogueSource.LOC].base_url`. It became a row on the
# catalogue targets table, and what is left here is the measurement.

_MODS: Final = "{http://www.loc.gov/mods/v3}"

#: BnF `dc:type` values that are a printed book. It also catalogues manuscripts,
#: scores, maps and recordings, all of which match a title search.
#:
#: **`text` is the entry that lets an electronic resource through, and taking it
#: out is not the fix.** This constant is shared with `_nkp_record`, and 118 of
#: the 119 live NKP records measured on 2026-09-03 carry a `dc:type` of exactly
#: `text`, so dropping it refuses the whole Czech catalogue to fix the French
#: one. `_BNF_NOT_PRINTED` refuses on the other side instead.
_BNF_PRINTED: Final = ("texte imprim", "printed text", "text")

#: What the BnF's `dc:type` says when the thing is **not** printed, tested after
#: `_BNF_PRINTED` rather than instead of it.
#:
#: The BnF repeats `dc:type` in French, in English and as a DCMI type, and the
#: DCMI type of an ebook is `text`: `ressource électronique | electronic
#: resource | text` passes the gate above on its last third. Measured over 444
#: live BnF records, 8 pass that way. The English term is matched because the
#: BnF emits all three spellings on every record, so one is enough and it is the
#: one with no accents to normalise.
_BNF_NOT_PRINTED: Final = "electronic resource"

#: What this catalogue calls a digital copy in its `dc:format`, which is the
#: BnF's `_NKP_ONLINE` and exists for the same reason.
#:
#: **The `dc:type` does not save this case**, which is the thing to know before
#: deleting it as redundant: 6 of those 444 records carry `dc:type` = `texte
#: imprimé | printed text | text`, the printed value, beside `dc:format` = `1
#: ressource dématérialisée`. The type is simply wrong on them and the format is
#: right. So Dublin Core needs prose here even where a type gate exists, and
#: this is the second of the **two** per source constants the roster needs.
_BNF_ONLINE: Final = re.compile(r"ressources?\s+d[eé]mat[eé]rialis", re.IGNORECASE)


def _bnf_record(record: ElementTree.Element, *, source: str) -> Record | None:
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
    # And not printed, which is a separate question from not being printed:
    # the DCMI `text` on an ebook satisfies the gate above. See the constant.
    if _BNF_NOT_PRINTED in kinds:
        return None

    # The BnF writes the statement of responsibility into the title, the same
    # way the DNB does, so the same parser applies.
    title, subtitle = split_title_statement(titles[0])
    if is_placeholder_title(title):
        return None

    extent = next((value for value in texts("format")), None)
    # Two refusals, the same pair `_nkp_record` makes: the shared rule for the
    # forms every source writes, and this catalogue's own French, which the
    # shared one cannot see. See `_BNF_ONLINE`.
    if not is_physical_book(extent, title) or (
        extent is not None and _BNF_ONLINE.search(extent)
    ):
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
        source=source,
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=_bnf_authors(texts("creator")),
        publisher=publisher,
        year=int(year_match.group()) if year_match else None,
        language=LANGUAGES.get((texts("language") or [""])[0].lower()),
        page_count=pages_from_extent(extent),
        cover_url=covers.open_library_url(isbn) if isbn else None,
        # Dublin Core names no vocabulary and carries no identifier, in either
        # dialect: see `catalogue.uncontrolled`.
        subjects=uncontrolled(texts("subject")),
    )


def _bnf_authors(creators: list[str]) -> str | None:
    """The people who wrote it, not the ones who translated or edited it.

    The BnF marks the role inside the creator string rather than in a field of
    its own, so it has to be read out of the text. A creator with no role
    marker is the main entry and is kept: dropping it would leave records with
    no author at all.
    """
    authors = [
        flip_catalogue_name(creator)
        for creator in creators
        if not _BNF_ANY_ROLE.search(creator)
        or any(role in creator.casefold() for role in _BNF_AUTHOR_ROLES)
    ]
    return ", ".join(authors) or None


#: MODS `physicalDescription/form` values that say the carrier is electronic,
#: per `@authority`, which is this source's spelling of the MARC codes.
#:
#: **The Library of Congress publishes MODS generated from MARC**, so
#: `marcform` is `008/23` written out, `marccategory` is `007/00` written out,
#: and `rdamedia` is the RDA media type. Whole strings from a controlled
#: vocabulary, so nothing here is a positional read.
#:
#: **`typeOfResource` does not cover this**, which is the point: it is `text` on
#: 322 of 391 live records measured on 2026-09-03, and **30 of those 322** carry
#: a form saying electronic. `bibliographic._NOT_A_BOOK` refuses **5** of the 30, on
#: `1 online resource` and `1 electronic resource (255 pages )`; 6 more read
#: `1 CD-ROM : sd., col. ; 4 3/4 in.`, which no alternative in that pattern
#: matches in any language.
#:
#: **All three authorities, not the shortest rule that fits.** `rdamedia` alone
#: agrees with the union on 322 of 322 here, and it is RDA: a record catalogued
#: before RDA carries `marcform` and `marccategory` and no `rdamedia` at all. 3
#: of the 322 already carry no `rdamedia`, and none of those 3 is electronic
#: today, which is a fact about this sample rather than about the catalogue.
#:
#: Microform is deliberately absent. 17 of the 322 are microfilm, and whether
#: this app shelves one is the decision `marc_fields._COMPONENT_PART_LEVELS` declines to
#: take about serials.
_LOC_NOT_A_BOOK_FORMS: Final = {
    "marcform": frozenset({"electronic"}),
    "marccategory": frozenset({"electronic resource"}),
    "rdamedia": frozenset({"computer"}),
}


def _loc_carrier_is_book(record: ElementTree.Element) -> bool:
    """Whether this MODS record's own form codes say it is a thing on a shelf.

    the MARC carrier test for the one source that answers MODS. A record with
    no `form` at all decides nothing here: 1 of the 391 measured carries none,
    and an absent code is a thin record rather than a disc.
    """
    for form in record.findall(f"{_MODS}physicalDescription/{_MODS}form"):
        refused = _LOC_NOT_A_BOOK_FORMS.get(form.get("authority") or "")
        if refused and (form.text or "").strip().casefold() in refused:
            return False
    return True


def _loc_record(record: ElementTree.Element, *, source: str) -> Record | None:
    kind = record.find(f"{_MODS}typeOfResource")
    if kind is None or (kind.text or "").strip() != "text":
        return None
    if not _loc_carrier_is_book(record):
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
    if is_placeholder_title(title):
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
            authors.append(flip_catalogue_name(part.text.strip().rstrip(",.")))

    extent_element = record.find(f"{_MODS}physicalDescription/{_MODS}extent")
    extent = extent_element.text.strip() if extent_element is not None and extent_element.text else None
    if not is_physical_book(extent, title):
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
        LANGUAGES.get((language_element.text or "").strip().lower())
        if language_element is not None
        else None
    )

    return Record(
        source=source,
        isbn=isbn,
        title=title,
        subtitle=subtitle,
        author=", ".join(authors) or None,
        publisher=publisher,
        year=int(year_match.group()) if year_match else None,
        language=language,
        page_count=pages_from_extent(extent),
        cover_url=covers.open_library_url(isbn) if isbn else None,
        subjects=_loc_subjects(record),
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


def _loc_subjects(record: ElementTree.Element) -> tuple[Subject, ...]:
    """Every `<topic>`, carrying the authority its `<subject>` declares.

    **MODS supplies the vocabulary and never the identifier**, which is the
    opposite half of what Dublin Core supplies and the reason this reader is not
    `catalogue.uncontrolled`. Measured 2026-08-31 over 432 `<subject>` elements
    in 200 live MODS records: `authority` names `lcsh` 372 times, `fast` 19,
    `lctgm` 4, `lcshac` 3 and `rvm` once, is absent 33 times, and **`valueURI`
    appears on 0 of the 432**. That reproduces the 0 of 2,280 already recorded
    in `ClassificationScheme`, on a fresh sample, and it is why an LCSH row
    stores the heading string as its own identifier.

    **Every authority, not only `lcsh`.** `_loc_subject_headings` reads `lcsh`
    alone, because a `classifications` row needs a scheme this app has a reading
    for. A subject is the field with no such requirement: the whole point of
    #134 is that a vocabulary is recorded as declared and never mapped, so
    `fast` and `rvm` arrive labelled with their own names rather than dropped or
    folded into `lcsh`. This is the same record and costs no request.

    **The topic, not the whole chain.** `_loc_subject_headings` joins an
    element's parts into `Computer software -- Development` because that is the
    heading LCSH authorises. Here each `<topic>` stays its own word, which is
    what the tag suggestion and the `categories` string want, and is what this
    reader did before.

    Lower cased here, which is `catalogue.Subject`'s rule and the same one
    `marc_fields.Subfields.subject_vocabulary` applies to a `$2`. **Case is the whole of the tidying
    and punctuation is not**: `_LOC_SUBJECT_AUTHORITY` records a stray
    `bisacsh.` beside `bisacsh` over 900 records, and the trailing full stop is
    left on, because guessing at punctuation inside somebody else's code is how
    one vocabulary quietly becomes two under a name nobody chose.

    **An empty `<topic>` is not a subject**, where it used to be an empty
    string. `catalogue.Subject` has no bound and no validation, by design, so
    nothing downstream would have refused it.
    """
    found: list[Subject] = []
    for element in record.findall(f"{_MODS}subject"):
        authority = (element.get("authority") or "").lower() or None
        for topic in element.findall(f"{_MODS}topic"):
            if topic.text and topic.text.strip():
                found.append(Subject(topic.text.strip(), authority))
    return tuple(found)


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
    request and the Library of Congress does not join `metadata._lookup_one`. It stays off
    the lookup path for the reason `docs/decisions.md` records: it is reached
    over plaintext HTTP, and it held nothing for either German ISBN measured,
    which is this library's main case. **It was the only plaintext catalogue
    when that was written and is now one of three**, with the National Library
    of Greece and the Czech national library; the count moved twice without
    this sentence moving, so it no longer states one.

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


# ── The SRU door ──────────────────────────────────────────────────────────────
#
# One request builder and one dispatch over `targets.Target` rows, where there
# used to be eleven near identical adapters: five ISBN lookups and six title
# searches, differing in an index name, a version string, a record schema and a
# page size. Adding an SRU catalogue is now a row in `targets.SEEDED` plus, only
# if its record format is genuinely new, a `Reader`.
#
# **What did not move.** The parsers, and every refusal in them. A row picks a
# reader; it cannot say what a reader accepts. That is the line the ticket drew
# against Koha's `add_xslt`, and `Fields.claims_isbn`, `is_placeholder_title`,
# `is_physical_book` and `Fields.isbn` are what sit on our side of it.


def _marc_nodes(
    root: ElementTree.Element, decoding: decoders.Decoding
) -> list[ElementTree.Element]:
    """Every MARC record in a response that this decoding wants read.

    **An SRU diagnostic needs no branch of its own here**, and it is worth
    saying because these endpoints answer every error with HTTP 200. An invalid
    query and an unsupported one both come back as a well formed
    `searchRetrieveResponse` carrying a `diag:diagnostic` and no records, so the
    body parses and this returns nothing. `test_metadata.py` pins that with a
    recorded diagnostic rather than leaving it to be rediscovered.

    **On the search path that is the whole answer and on the lookup path it is
    not**, which is the asymmetry to read before moving this rule.
    `_sru_lookup` turns a diagnostic into `Outcome.UNAVAILABLE` before a reader
    is reached, because a lookup can say "nobody could be asked" and a search
    cannot: this returns `list[Record]`, and an empty list is the only thing it
    has to say with. `_sru_refusal` carries the argument.

    The component part filter is the ÖNB's and the NLG's. What it catches and
    what it does not is on `targets.Target.refuses_component_parts`, and the two
    measurements behind it are in those sources' blocks above.
    """
    nodes = root.iter(marc_fields.RECORD_TAG)
    if decoding.refuses_component_parts:
        return [node for node in nodes if not marc_fields.is_component_part(node)]
    return list(nodes)


def _marc_build(
    decoding: decoders.Decoding,
    fields: marc_fields.Fields,
    isbn: str | None,
) -> Record | None:
    """One MARC record as book fields, through the reader the decoding names.

    **Two MARC readers and not one**, which is where this diverges from the
    ticket's "four readers cover all nine". `_dnb_record` harvests GND identified
    headings across five tags and refuses a title that names a volume slot;
    `_k10plus_record` joins `650 $a` and `$x` into one subject and does neither.
    Folding them would change answers rather than restructure code, which is the
    class of thing `add_xslt` was refused over.
    """
    if decoding.reader is decoders.Reader.MARC_PLAIN:
        return _k10plus_record(fields, isbn, source=decoding.source)
    return _dnb_record(
        fields,
        isbn,
        source=decoding.source,
        read_author_identifiers=decoding.reads_author_identifiers,
    )


def _marc_lookup(
    root: ElementTree.Element, isbn: str, decoding: decoders.Decoding
) -> Lookup:
    """The best MARC record in a response for the ISBN that was asked about.

    **Two behaviours, and the row picks which.** Everywhere but the DNB a record
    that does not name the ISBN in its own 020 is refused: at the ÖNB that check
    is the whole defence against a mistyped index answering with the entire
    catalogue rather than with nothing. The DNB's `num=` index matches cross
    references, so refusing there turns a live lookup into a miss for a record
    that describes the right book, and it ranks instead. See
    `targets.Target.requires_isbn_claim`, which defaults to the refusing arm so
    a new row gets the safe answer by omission.

    **The ranking key is the same three questions in both arms**, in the order
    they decide: does the record claim this ISBN, can it sit on a shelf, and is
    it the fullest. `sorted` is stable, so records that tie keep the catalogue's
    own order and its first answer wins.
    """
    name = decoding.source
    books = [
        (fields, record)
        for node in _marc_nodes(root, decoding)
        for fields in [marc_fields.Fields(node)]
        for record in [_marc_build(decoding, fields, isbn)]
        if record is not None
    ]
    if not books:
        logger.info("%s matched %s only as a cross reference or a non-book", name, isbn)
        return Lookup(Outcome.NOT_FOUND, source=name)

    if decoding.requires_isbn_claim:
        claimed = [book for book in books if book[0].claims_isbn(isbn)]
        if not claimed:
            return Lookup(Outcome.NOT_FOUND, source=name)
        return Lookup(Outcome.FOUND, source=name, record=_fullest_physical(claimed))

    ranked = sorted(
        books,
        key=lambda book: (
            book[0].claims_isbn(isbn),
            book[0].describes_a_book(book[1].title),
            book[1].completeness,
        ),
        reverse=True,
    )
    return Lookup(Outcome.FOUND, source=name, record=ranked[0][1])


def _dublin_core_bare_lookup(
    root: ElementTree.Element, isbn: str, decoding: decoders.Decoding
) -> Lookup:
    """The best un-namespaced Dublin Core record for the ISBN that was asked about.

    The Czech National Library's shape, and the Biblioteca Nacional Argentina's,
    which is this reader's whole roster. `_nkp_claims_isbn` is this format's
    `Fields.claims_isbn`: it has no 020 to read and tests the record's own
    identifier elements instead.

    **`decoding.source` labels the record as well as the lookup.** It labelled
    only the lookup until the second catalogue in this dialect arrived; see
    `_nkp_record`.
    """
    name = decoding.source
    parsed = [
        record
        for node in _nkp_records(root)
        if not decoding.requires_isbn_claim or _nkp_claims_isbn(node, isbn)
        for record in [_nkp_record(node, isbn, source=name)]
        if record is not None
    ]
    if not parsed:
        return Lookup(Outcome.NOT_FOUND, source=name)
    return Lookup(
        Outcome.FOUND,
        source=name,
        record=max(parsed, key=lambda record: record.completeness),
    )


def _marc_record(
    record: ElementTree.Element, decoding: decoders.Decoding
) -> Record | None:
    """One MARC record as a `catalogue.Record`, or None for what is not a book.

    **The refusals are here and not in the caller**, which is what makes this a
    decoder rather than a step of one: a file has no caller to add them.
    `Fields.describes_a_book` is the carrier door and `record.title` is the
    thinness test.

    **An online resource is refused here and only ranked down at a lookup**, and
    the asymmetry is deliberate rather than an oversight: a search has no ISBN to
    tell an edition of this book from a digitisation of another one, and neither
    has a file. `_marc_lookup` therefore does not build on this.
    """
    fields = marc_fields.Fields(record)
    built = _marc_build(decoding, fields, None)
    if built is None or not built.title:
        return None
    if not fields.describes_a_book(built.title):
        return None
    return built


def _dublin_core_record(
    record: ElementTree.Element, decoding: decoders.Decoding
) -> Record | None:
    """One namespaced Dublin Core record. The BnF's shape."""
    return _bnf_record(record, source=decoding.source)


def _mods_record(
    record: ElementTree.Element, decoding: decoders.Decoding
) -> Record | None:
    """One MODS record. The Library of Congress's shape."""
    return _loc_record(record, source=decoding.source)


#: Which decoder reads ONE catalogue record, by `decoders.Reader`. The catalogue
#: family's half of the contract `decoders.py` states, and `opds.READERS` is the
#: import family's.
#:
#: **The value type is the contract**, and mypy is what holds it: a decoder is
#: handed a parsed record and a `decoders.Decoding`, answers with a
#: `catalogue.Record` or `None`, and is told nothing about how the bytes
#: arrived. No URL, no status, no handle, no `targets.Target`.
#:
#: **Three catalogue readers are deliberately absent, and each exclusion is a
#: measurement rather than an oversight.** The rule is that these four plus the
#: three below partition `decoders.CATALOGUE_READERS`, asserted by
#: `tests/test_decoders.py::TestEveryCatalogueReaderIsPlacedOrExcluded`, so a
#: new reader fails that test until somebody places it. An inclusion list is
#: what goes stale when the registry grows.
#:
#: * `OPEN_LIBRARY` and `GOOGLE_BOOKS` answer in JSON, so their records are not
#:   `ElementTree.Element` and cannot be values of this type. They are also the
#:   two that still weld fetching to decoding, which is a separate seam.
#: * `DUBLIN_CORE_BARE` **is** XML and is still not a decoder, which is the one
#:   worth reading twice. `_nkp_record` stamps the ISBN that was **asked** onto
#:   the record it returns and builds its cover URL from it. The dialect does
#:   carry the ISBN: `_nkp_claims_isbn` runs `isbn.parse` over every
#:   `identifier` element to test one. What is missing is a reader that picks
#:   one out and writes it to the record, so a file, which asks no ISBN, would
#:   decode to `isbn=""` and a cover URL built from it. Writing that reader is
#:   what admits this one.
READERS: Final[
    dict[
        decoders.Reader,
        Callable[[ElementTree.Element, decoders.Decoding], Record | None],
    ]
] = {
    decoders.Reader.MARC_GND: _marc_record,
    decoders.Reader.MARC_PLAIN: _marc_record,
    decoders.Reader.DUBLIN_CORE: _dublin_core_record,
    decoders.Reader.MODS: _mods_record,
}

#: The catalogue readers `READERS` cannot hold, and why, in one place a test can
#: read. See `READERS`.
NOT_DECODERS: Final[dict[decoders.Reader, str]] = {
    decoders.Reader.OPEN_LIBRARY: "answers in JSON, not in XML elements",
    decoders.Reader.GOOGLE_BOOKS: "answers in JSON, not in XML elements",
    decoders.Reader.DUBLIN_CORE_BARE: (
        "stamps the ISBN that was asked, which a file has not asked"
    ),
}


def _records(
    nodes: Iterable[ElementTree.Element], decoding: decoders.Decoding
) -> list[Record]:
    """Every node a decoder accepted, through `READERS` and never by name.

    One dispatch for all three search shapes, so a reader reachable from a
    search is a reader in the published table by construction.
    """
    reader = READERS[decoding.reader]
    return [
        record
        for node in nodes
        for record in [reader(node, decoding)]
        if record is not None
    ]


def _marc_search(
    root: ElementTree.Element, decoding: decoders.Decoding
) -> list[Record]:
    """Every book in a MARC response. `_marc_record` is what refuses."""
    return _records(_marc_nodes(root, decoding), decoding)


def _dublin_core_search(
    root: ElementTree.Element, decoding: decoders.Decoding
) -> list[Record]:
    """Every book in a namespaced Dublin Core response. The BnF's shape.

    The selector is the format's and not the row's; the decoder the row names
    is what reads what it finds.
    """
    return _records(root.findall(f".//{_DC}title/.."), decoding)


def _mods_search(
    root: ElementTree.Element, decoding: decoders.Decoding
) -> list[Record]:
    """Every book in a MODS response. The Library of Congress's shape."""
    return _records(root.iter(f"{_MODS}mods"), decoding)


#: Which decoder reads a lookup response, by `decoders.Reader`.
#:
#: **Keyed on the reader and not on the source**, which is the whole change:
#: four sources share `MARC_GND` and a fifth would add no entry here. A reader
#: absent from this table is a target that answers a lookup with nothing able to
#: parse the answer, and `resolve` is what turns that into a failure at load
#: rather than a `KeyError` on the path that adds a book.
#:
#: **The value type is the seam, and it is enforced by the type rather than by a
#: comment.** A decoder takes a parsed record and a `decoders.Decoding`; a
#: `targets.Target` here would put an address and a query grammar inside a
#: parser and weld every format to the one way this application currently
#: reaches it. mypy refuses the weld, which is the strongest rung available:
#: nothing has to remember the rule.
_LOOKUP_READERS: Final[
    dict[
        decoders.Reader,
        Callable[[ElementTree.Element, str, decoders.Decoding], Lookup],
    ]
] = {
    decoders.Reader.MARC_GND: _marc_lookup,
    decoders.Reader.MARC_PLAIN: _marc_lookup,
    decoders.Reader.DUBLIN_CORE_BARE: _dublin_core_bare_lookup,
}

#: Which decoder reads a title search response, by `decoders.Reader`.
_SEARCH_READERS: Final[
    dict[
        decoders.Reader,
        Callable[[ElementTree.Element, decoders.Decoding], list[Record]],
    ]
] = {
    decoders.Reader.MARC_GND: _marc_search,
    decoders.Reader.MARC_PLAIN: _marc_search,
    decoders.Reader.DUBLIN_CORE: _dublin_core_search,
    decoders.Reader.MODS: _mods_search,
}


#: What an SRU diagnostic's own identifier looks like, and the whole of what is
#: ever written down from one.
#:
#: **The URI and never the details, because the details echo what was sent.**
#: Measured 2026-09-07: the Biblioteca Nacional Argentina answers an
#: unauthenticated request with an Aleph error whose text quotes back the user
#: name on the request, truncated by the target's own parser. A log line
#: carrying a target's prose therefore carries half a login at that target, and
#: no reading of a third party's free text makes that safe. A URI is a code out
#: of a registry, and one that does not look like one is dropped rather than
#: repeated.
_DIAGNOSTIC_URI: Final = re.compile(r"[\w.:/+-]{1,120}")


def _local_name(tag: str) -> str:
    """An element's name without its namespace.

    Namespace agnostic on purpose: SRU 1.1 and 1.2 and the servers in this
    roster disagree about which namespace a diagnostics block carries, and a
    match on one spelling would read a refusal from the others as an empty
    catalogue.
    """
    return tag.rsplit("}", 1)[-1]


def _sru_refusal(root: ElementTree.Element) -> str | None:
    """A refused request as its diagnostic URI, or None where nothing refused.

    **A diagnostic is not an empty answer, and every SRU endpoint here reports
    both under HTTP 200.** Zero results are `numberOfRecords 0`; a diagnostic
    means the request was not honoured at all, whether because a credential is
    wrong, a schema is unsupported or a database name does not exist. Reading
    the second as the first tells a member their book is not held by a catalogue
    that was never asked, which is `Outcome`'s founding distinction and the
    conflation #91 found for the Greek `$q` case.

    **Structural rather than a list of codes.** It asks whether the response
    carries a diagnostics block, not which diagnostic: the authentication
    numbers are one family in an open registry, and a guard naming 1/3 today
    would read 1/2 and 1/235 as books this library does not hold.

    **A diagnostic beside records is not a refusal, and this function cannot
    tell**, which is why `_sru_lookup` asks it only after the reader has found
    nothing. The National Library of Greece answers the true `numberOfRecords`
    **and** `Unknown schema for retrieval` when no `recordSchema` is named, and
    `docs/decisions.md` records a probe that read every such response as
    unreadable and reported a confident zero for the country it was recommending.
    Records that parse win over anything the envelope says about itself.

    **The case this rule would get wrong is a target that diagnoses an honest
    empty answer, and it is measured rather than argued about.** Asked on
    2026-09-07 for an ISBN none of them holds, every one of the seven SRU lookup
    targets answered `numberOfRecords 0` and **no diagnostic element of any
    kind**: 457, 463, 205, 420, 462, 420 and 205 bytes. The Argentine
    catalogue's forty other empty answers that day carried none either. A target
    that starts attaching one is the thing to watch for, and the symptom would be
    that source reporting `UNAVAILABLE` on every miss.

    **What a refusal costs is the whole lookup and not only the source**, which
    is `_worst`: it reports `UNAVAILABLE` over `NOT_FOUND` when nothing was found
    anywhere, so one target declining to be asked is the answer a member sees for
    all of them. That is the intended reading, "nobody could be asked" rather
    than "nobody holds it", and it is the reason this arm is narrow.

    **A diagnostic inside `records` is deliberately not read.** SRU allows one
    there and it describes a single record rather than the request, so this
    looks only at a direct child of the response element. That is also what
    stops a record's own text becoming a refusal for the whole lookup.

    **None and the empty string are two different answers**, which is why this
    is not a `bool` and not a `str`. None is "nothing refused". Empty is "a
    refusal whose URI is missing or is not a URI", which is still a refusal and
    is a thing this application may not repeat into a log.
    """
    for child in root:
        if _local_name(child.tag) != "diagnostics":
            continue
        for element in child.iter():
            if _local_name(element.tag) != "uri":
                continue
            uri = (element.text or "").strip()
            return uri if _DIAGNOSTIC_URI.fullmatch(uri) else ""
        return ""
    return None


async def _sru_lookup(
    target: targets.Target, isbn: str, credential: fetch.Credential | None
) -> Lookup:
    """One ISBN lookup against an SRU target.

    **`credential` is offered to the request and attached by nothing else.**
    `fetch` hands it to each hop and `credentials.Credential.header_for` decides,
    per hop, whether this is the origin it was set for. None is the ordinary case
    and means an unauthenticated GET, which is what every free catalogue takes.

    **The query is built inside the `try`, because building one raises.**
    `targets.cql_term` refuses a value that is not a term and `z3950.pqf_term`
    refuses an empty, over-long or control bearing one, so outside the block the
    `BadQuery` arm below is unreachable, which is exactly what it was when that
    arm was first written for the Czech National Library.
    """
    name = target.source.value
    try:
        params = target.sru_params(target.isbn_query(isbn), target.lookup_records)
        response = await fetch.get_once(
            target.base_url, params=params, credential=credential
        )
        if response.status_code == 429:
            return Lookup(Outcome.RATE_LIMITED, source=name)
        if response.status_code != 200:
            return Lookup(Outcome.UNAVAILABLE, source=name)
        root = _parsed(response.text)
    except (
        httpx.HTTPError,
        ElementTree.ParseError,
        targets.BadQuery,
        z3950.BadQuery,
    ):
        logger.warning("%s lookup failed for %s", name, isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source=name)
    answer = _LOOKUP_READERS[target.reader](root, isbn, target.decoding)
    if answer.outcome is not Outcome.NOT_FOUND:
        return answer
    refusal = _sru_refusal(root)
    if refusal is None:
        return answer
    # Nothing was read and the target said why, so this is a refusal rather than
    # a miss. See `_sru_refusal` for why the reader runs first, why the URI is
    # the only part of a diagnostic that is ever written down, and what `_worst`
    # then does with this one source's answer.
    logger.warning("%s refused a lookup: %r", name, refusal)
    return Lookup(Outcome.UNAVAILABLE, source=name)


async def _sru_search(
    target: targets.Target, query: str, limit: int, credential: fetch.Credential | None
) -> list[Record]:
    """One title search against an SRU target.

    `credential` carries the same rule it does at a lookup: see `_sru_lookup`.

    The shape of the query is the row's, out of the four `targets.TitleQuery`
    holds, and every term in it has been through `targets.cql_term`. Asking for
    more records than the caller wants is deliberate: the ordering is the
    catalogue's and the ranking is ours, so taking the first `limit` would be
    taking the catalogue's opinion, which is the one we do not trust.
    """
    terms = _search_terms(query)
    if not terms:
        return []
    try:
        params = target.sru_params(
            target.title_query(terms), target.search_records(limit)
        )
        response = await fetch.get_once(
            target.base_url, params=params, credential=credential
        )
        if response.status_code != 200:
            return []
        root = _parsed(response.text)
    except (httpx.HTTPError, ElementTree.ParseError, targets.BadQuery):
        logger.warning(
            "%s search failed for %r", target.source.value, query, exc_info=True
        )
        return []
    return _SEARCH_READERS[target.reader](root, target.decoding)


def resolve(target: targets.Target) -> None:
    """Refuse a row that names a capability nothing here can serve.

    **The successor to `TestTheProviderRosterIsOneList`, and it is a function
    rather than only a test because a row is written to a database.** That test
    compared two dispatch tables against `sources`, which was the right guard
    while a source was a Python constant: a source in one and not the other was a
    `KeyError` on the path that adds a book. Both tables are keyed on
    `decoders.Reader` now and one reader serves several sources, so the comparison
    cannot be restated; this asks the question it was really asking, one row at a
    time.

    **Two call sites, and neither validates a database row**, which is worth
    stating because the name invites the opposite reading.
    `main.seed_catalogue_targets` calls this over `targets.SEEDED` at boot, so a
    constant naming a reader nothing implements fails the boot rather than a
    member's scan, and
    `test_house_rules.py::TestEveryTargetResolvesToADoorAndAReader` calls it over
    the same roster. Both check the **code** against itself. What checks a row is
    `models.CatalogueTarget`'s CHECK constraints, because `backup.restore` writes
    through Core and reaches no Python. #130 is where a row becomes a `Target`
    and where this starts having something to say about one.

    Raises `ValueError`, which is what `targets.Target.__post_init__` raises for
    the invariants it can see on one row on its own. This is the half that needs
    to know what code exists.
    """
    if target.can(Capability.ANSWERS_ISBN):
        table = (
            _LOOKUP_READERS
            if target.transport is targets.Transport.SRU
            else _BESPOKE_LOOKUPS
        )
        if target.reader not in table:
            raise ValueError(
                f"{target.source}: answers a lookup and {target.reader} reads none"
            )
    if target.can(Capability.ANSWERS_TITLE_SEARCH):
        readers: Collection[decoders.Reader]
        if target.transport is targets.Transport.SRU:
            readers = _SEARCH_READERS.keys()
        elif target.can(Capability.METERED):
            readers = _METERED_SEARCHES.keys()
        else:
            readers = _FREE_SEARCHES.keys()
        if target.reader not in readers:
            raise ValueError(
                f"{target.source}: answers a search and {target.reader} reads none"
            )


def carries_a_credential(target: targets.Target) -> bool:
    """Whether a request to this target would actually carry a login.

    **The SRU door takes one and hands it to `fetch`, and no other door does.** A
    bespoke target's secret is an argument to its own adapter, which is where the
    Google Books key goes, so a login handed to `_lookup_one` for a bespoke row is
    dropped without a word.

    **Public, and asked rather than restated, which is the whole reason it is a
    function.** `routers/books.py` resolves a login only for the targets this
    admits, and `tests/test_credentials.py` asks the same question of the roster.
    Written out at both sites instead, the day a transport starts carrying one
    would turn the test red and the edit it demands is to the test's own copy,
    which greens the suite while the router still skips the row and the request
    still goes out unauthenticated. That is #209 recurring with its own tripwire
    green.

    **Measured against the wire rather than stated**, by
    `tests/test_metadata.py::TestWhichDoorCarriesALogin`, which asks every seeded
    row that answers a lookup through `_lookup_one` and compares this answer with
    whether an `Authorization` header left the process. So this is not a second
    spelling of the branch below: it is a claim about that branch's effect, and
    the two are checked against each other rather than kept in step by hand.

    **That instrument reaches the rows with a lookup door, which is not all of
    them.** The rows whose only door is the search door are off it, because
    `_lookup_one` is not the door they use; `test_a_title_search_carries_the_login_too`
    is what covers that side, behaviourally rather than per row. The count is
    deliberately not written here: it is a live cardinality, and one written into
    this module would be a number nothing recomputes.

    `Z3950` answers False and must, because `fetch.py` never opens that socket.
    #129 is where that door and what it carries are decided together.
    """
    return target.transport is targets.Transport.SRU


async def _lookup_one(
    target: targets.Target,
    isbn: str,
    api_key: str,
    *,
    credential: fetch.Credential | None,
) -> Lookup:
    """Ask one target about one ISBN, through whichever door its row names.

    **`credential` is keyword only with no default, so mypy refuses a call site
    that forgets it.** That is the property worth having here: an omitted login
    is an unauthenticated GET that a catalogue answers with a diagnostic and
    this module reports as "not found", which is the failure #209 was opened
    for. The public entry points take `plan` keyword only with no default for
    exactly the same reason.

    **A bespoke target is handed `api_key` and never a sealed login**, because
    that is where its secret lives: Google Books' key is an argument to its own
    adapter. A row that needed a sealed login on a bespoke transport would be
    resolved by the router and dropped here. `carries_a_credential` above is that
    rule as a question anything may ask, and
    `tests/test_credentials.py::TestASealedLoginNeedsATransportThatCarriesIt` is
    the tripwire that asks it of the roster.

    **Only a metered one, which is the same test `_search_one` already applies.**
    The key is this deployment's own and it is metered quota: a bespoke target
    that is not metered has no use for it and must not be handed it, because a
    row added to `_BESPOKE_LOOKUPS` would otherwise receive it by arriving. That
    is the evasion the security seat recorded against this rule on 2026-09-17,
    and it costs nothing today: Open Library is the other bespoke door and its
    adapter opens with `del api_key`.
    """
    if target.transport is targets.Transport.SRU:
        return await _sru_lookup(target, isbn, credential)
    metered = api_key if target.can(Capability.METERED) else ""
    return await _BESPOKE_LOOKUPS[target.reader](isbn, metered)


async def _search_one(
    target: targets.Target,
    query: str,
    limit: int,
    api_key: str,
    *,
    credential: fetch.Credential | None,
) -> list[Record]:
    """Ask one target for title matches, through whichever door its row names.

    `credential` carries the rule `_lookup_one` states, including which doors
    take one.
    """
    if target.transport is targets.Transport.SRU:
        return await _sru_search(target, query, limit, credential)
    if target.can(Capability.METERED):
        return await _METERED_SEARCHES[target.reader](query, limit, api_key)
    return await _FREE_SEARCHES[target.reader](query, limit)


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
#:
#: **The NKP, BNE and BNA entries are inert and are here so they stay correct if
#: that changes.** This set is read only from `_relevance`, which scores
#: **search** rows, and none of the three answers a title search:
#: `sources.SEARCH_SOURCES` leaves all three out, the NKP and the BNA because
#: their server renders one populated record per response whatever page size is
#: asked, the BNE because its search gain was never measured. So none can reach
#: this comparison today. Listing them costs nothing and omitting them would put
#: a wrong default in place the day one does, which is the same reasoning
#: `_MATCH_PRECEDENCE` records for the same three. A reader meeting this line
#: should not conclude that any of them appears in search results.
_SECONDARY_SOURCES: Final = frozenset(
    {"bnf", "loc", "oenb", "nlg", "nkp", "bne", "bna"}
)
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


@dataclass(frozen=True)
class Search:
    """What one title search asked, and what it found.

    **`asked` is what the fan out really did**, not what the request wanted. A
    harder search can be refused its slot (`_HARDER_AT_ONCE`) or find the two
    rosters equal, and in both cases it runs the ordinary search. A screen that
    then reported the slow catalogues as asked would be promising something the
    server did not do, which is the one thing this repository's derived fields
    exist to stop.
    """

    matches: list[Record]
    asked: tuple[CatalogueSource, ...]
    #: The enabled search catalogues this fan out did not reach, which is
    #: exactly what asking harder would add.
    #:
    #: **Computed here and not from `plan` by the caller**, because only here is
    #: it known that a query with no usable terms asked nothing **and** has
    #: nothing left to ask. A caller subtracting `asked` from `plan.searched_harder`
    #: gets the whole roster for that query, and a screen reading it then tells a
    #: reader who typed "and" that every catalogue this library runs is a slow
    #: one. That is a claim about their configuration made by something that
    #: never looked at it, which is the failure this whole feature exists to
    #: remove, one level in.
    unasked: tuple[CatalogueSource, ...]


async def search(
    query: str,
    limit: int = 10,
    prefer_language: str | None = None,
    *,
    access: Access,
    harder: bool = False,
) -> list[Record]:
    """The rows alone, for a caller with no use for the roster.

    A wrapper over `title_search` rather than a second implementation. Kept
    because most callers want the list and threading a dataclass through them
    buys nothing.
    """
    return (
        await title_search(
            query,
            limit,
            prefer_language,
            access=access,
            harder=harder,
        )
    ).matches


async def title_search(
    query: str,
    limit: int = 10,
    prefer_language: str | None = None,
    *,
    access: Access,
    harder: bool = False,
) -> Search:
    """Find a book by title and author, across every catalogue this library asks.

    **Which catalogues those are is `access.plan`**, the household's choice
    rather than this module's: a source switched off is never constructed and
    never awaited. What follows describes the eight a new install asks.

    **`access.logins` is what a catalogue asking for one is sent**, resolved by
    the caller: see `Access`.

    Three tiers, which is what keeps this both broad and quick.

    **Tier one, free, primary:** Open Library for breadth and covers, K10plus for
    German and European publishing, the DNB for German legal deposit.

    **Tier two, free, regional:** the BnF for French, the Library of Congress
    for Uruguayan printings and for anything printed before ISBNs existed, the
    ÖNB for Austrian imprints, the NLG for Greek publishing. All four rank a
    point below the primaries: they are here for the books nobody else holds, not
    to reorder the ones everybody does.

    **The Library of Congress is here for Uruguay and for pre ISBN printings**,
    which is measured rather than assumed. Editions held, by country:

    | | Uruguay | Spain | Italy | Brazil | Portugal | Argentina |
    |---|---|---|---|---|---|---|
    | held | 26/47 | 12/48 | 12/48 | 9/47 | 9/48 | 8/48 |
    | | **55.3%** | 25.0% | 25.0% | 19.1% | 18.8% | 16.7% |

    **The label was twice written wider than the data.** Aggregated, Latin America
    is 43/142 against Spain and Italy's 24/96, +5.3 points, 95% Newcombe -6.5 to
    +16.3, which includes zero; without Uruguay it is 17/95, or 17.9%.

    **Uruguay is the only result here that separates from anything**: +30.3
    points over Spain, 95% Newcombe +10.6 to +47.0, excluding zero. Nothing
    separates the five below it, so the line names Uruguay and stops.

    `TestTheLibraryOfCongressTableAgreesWithItself` recomputes every percentage
    from the fraction beside it and both intervals from the table, so a row and
    the prose above it cannot be corrected one at a time.
    **Holding the edition is necessary and not sufficient**, since a record still
    has to carry what this app reads.

    **Tier three, only with a key:** Google Books, for the blurb and the cover.

    **Then ours:** filtering out what is not a book, merging one book's rows and
    ranking the result.

    **`harder` asks the catalogues the default search leaves out**, under a
    deadline of its own, because a slow catalogue inside the shared deadline is a
    burned connection and never a record. **A library whose every search
    catalogue is slow gets an empty default and is told so**, rather than being
    shown "no matches" for a search that was never allowed to finish.
    """
    trimmed = query.strip()
    terms = _search_terms(trimmed)
    if not terms:
        # Nothing was asked and there is nothing left to ask, because there was
        # no question. Reachable on a two character query: "and" and "a b" both
        # reduce to no terms. See `Search.unasked`.
        return Search([], (), ())

    # **Only the enabled sources are constructed**, so a source this library
    # turned off is never built and never awaited. Building all eight and
    # dropping some would leave un-awaited coroutines behind, which is a warning
    # per search and a request nobody asked for if one ever ran.
    #
    # Both rosters hold only names in `sources.SEARCH_SOURCES`, which is
    # derived from `answers_search` on the rows, so `targets.SEEDED[name]` here
    # cannot miss and `_search_one` has a reader for whatever it finds:
    # `metadata.resolve` is what refuses a row that would not.
    # **Asked for is not the same as granted**, and the two conditions that
    # narrow it are separate because they refuse for separate reasons.
    #
    # A wider roster is the only thing the longer deadline buys. Where this
    # library has no slow catalogue enabled the two rosters are the same set, so
    # `harder` would spend three times the wall clock on the identical fan out,
    # and `harder` is a query parameter rather than a button: nothing makes a
    # caller press anything.
    #
    # A slot is the second condition, and it is taken without waiting. See
    # `_HARDER_AT_ONCE`.
    harder_now = harder and bool(access.plan.searched_only_harder)
    # `locked()` then `acquire()` is atomic here and it is worth saying why,
    # because it reads like a race. `Semaphore.acquire` returns without
    # suspending while a slot is free, and this is one event loop, so no task
    # can run between the two lines. A `Lock` would read the same and buy
    # nothing; waiting is the thing being refused, not the thing being tuned.
    if harder_now and not _HARDER_AT_ONCE.locked():
        await _HARDER_AT_ONCE.acquire()
    else:
        harder_now = False

    try:
        # **The roster and its deadline move together, in one branch.** Two
        # conditionals on the same flag would admit the combination nothing
        # wants: the long roster under the short deadline, which asks the slow
        # catalogues and then cancels every one of them, spending the requests
        # and returning the same rows as before with nothing to say what
        # happened.
        roster, deadline = (
            (access.plan.searched_harder, SEARCH_HARDER_DEADLINE_SECONDS)
            if harder_now
            else (access.plan.searched, SEARCH_DEADLINE_SECONDS)
        )
        tiers = await _within_deadline(
            [
                _search_one(
                    targets.SEEDED[name],
                    trimmed,
                    limit,
                    access.api_key,
                    credential=access.logins.get(name),
                )
                for name in roster
            ],
            deadline,
        )
    finally:
        if harder_now:
            _HARDER_AT_ONCE.release()

    merged = _merge_matches([row for tier in tiers for row in tier])

    ranked = sorted(
        merged, key=lambda match: _relevance(match, terms, prefer_language), reverse=True
    )
    asked = frozenset(roster)
    return Search(
        ranked[:limit],
        tuple(roster),
        tuple(name for name in access.plan.searched_harder if name not in asked),
    )


#: The title search adapter for a bespoke transport that needs no credential.
#:
#: **One entry, where this held seven.** Six of those were SRU sources that now
#: share `_sru_search`, driven by a row, and the seventh is Google Books, which
#: needs a key and so cannot share this signature: `_METERED_SEARCHES` below
#: holds it.
#:
#: **Keyed on the reader and not on the source**, which is what makes the
#: sharing possible: three sources name `MARC_GND` and a fourth would add no
#: entry anywhere. What that costs is the guard: `set(this) | set(that) ==
#: sources.SEARCH_SOURCES` cannot be restated against a reader keyed table, and
#: `resolve` is the replacement. It asks the question the old one was really
#: asking, one row at a time: this row says it answers a search, is there
#: anything here that can read the answer.
#:
#: **Module level and introspectable on purpose.** The guard that keeps this in
#: step with the roster used to read the fan out with `ast`, as a list literal
#: handed to `_within_deadline`, and it broke the moment the fan out stopped
#: being a literal. A table a test can import cannot go stale that way.
_FREE_SEARCHES: Final[
    dict[decoders.Reader, Callable[[str, int], Coroutine[Any, Any, list[Record]]]]
] = {
    decoders.Reader.OPEN_LIBRARY: _open_library_search,
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
#: is exactly one of them. `resolve` is what stops a metered row naming a reader
#: that is not in here.
_METERED_SEARCHES: Final[
    dict[decoders.Reader, Callable[[str, int, str], Coroutine[Any, Any, list[Record]]]]
] = {
    decoders.Reader.GOOGLE_BOOKS: _google_search,
}


#: How long a search may take, whatever the catalogues do.
#:
#: Up to eight sources are asked at once, so the wall clock is the slowest of
#: them, and one national catalogue having a bad afternoon was turning a 1.3s
#: search into a 7s one. A deadline degrades the *results* instead of the latency: whatever
#: has answered is ranked and returned, and the straggler is cancelled.
#:
#: Well above the 1.2s to 1.8s a healthy search measures, so this only ever
#: fires on a source that is genuinely struggling.
SEARCH_DEADLINE_SECONDS: Final = 4.0

#: How long an explicit "search harder" may take, whatever the catalogues do.
#:
#: **A second constant rather than a bigger first one**, and that is the whole of
#: the decision behind it: raising `SEARCH_DEADLINE_SECONDS` makes every search
#: in the library wait longer, including the ones that find nothing, which is the
#: common case. Nobody waits this long unless they asked to.
#:
#: **The margin over the transport is chosen, not measured, and saying so
#: replaces a sentence this constant shipped with for one round.** That sentence
#: read that 12.0 leaves 2.0s over the 10.0s ceiling one request already has and
#: is three times the default, "so two derivations land on the same number".
#: They are not two derivations: `10.0 + m = 3 x 4.0` has one solution, so the
#: margin was picked to make the coincidence and the second clause restates the
#: first.
#:
#: **And on today's adapters it does not bind.** Every title search adapter here
#: makes exactly one request, and `fetch.TIMEOUT_SECONDS` and
#: `z3950.TIMEOUT_SECONDS` both cap one request at 10.0s, so a concurrent fan out
#: cannot reach 12.0s however slow a catalogue is. What this admits that 4.0s
#: does not is the whole of that 10.0s, which is what a slow catalogue actually
#: needs. The only caller the extra 2.0s could serve is a source whose search
#: costs more than one request, and that shape is refused in
#: `sources.SLOW_SEARCHES` for a reason of its own.
#:
#: **So a measurement is owed before that set is filled**: the p90 of at least
#: twenty title searches against the candidate, which is the bar
#: `sources.SLOW_SEARCHES` states, and this figure re-derived against it rather
#: than assumed to still be roomy.
#:
#: **Bounded, which is the point of its being a constant at all.** Searching
#: harder is not searching forever: a source that has not answered by here is
#: cancelled exactly as it is at 4.0s, and the rows that did arrive are ranked
#: and returned. `_HARDER_AT_ONCE` bounds how many of these may run together,
#: which is a different question and one a deadline cannot answer.
SEARCH_HARDER_DEADLINE_SECONDS: Final = 12.0


#: How many "search harder" fan outs may run at once, process wide.
#:
#: **A concurrency bound, which a rate limit cannot supply.** `metadata_limiter`
#: allows 60 requests a minute per member and says nothing about how many are
#: open together. At that ceiling Little's law puts rate times wall clock in
#: flight: 1.0/s x 4.0s is 4 searches on the default path, and 1.0/s x 12.0s
#: would be 12 on this one, from one member, inside the limit, with no burst.
#: Each holds one socket per source, so twelve is 96 sockets and, at the ~81 MB
#: an eight source search costs by `fetch.MAX_RESPONSE_BYTES`' own honest figure,
#: about 972 MB against a 512 MiB pod.
#:
#: **One, because a reader who asked is one reader.** It takes that sustained
#: figure from 12 back to 1 and costs nothing when nobody searches hard.
#:
#: **Never waited on, and that half is what makes it safe.** A queue here would
#: be worse than what it fixes: `auth.get_current_user` checks a database
#: connection out before this runs and `get_db` returns it only after the
#: response, so a request parked on this semaphore holds one of the pool's
#: fifteen for as long as it waits. Fifteen waiters at 12.0s each is a pool
#: exhausted for minutes, which is a worse outage than the memory it saves. A
#: caller that cannot have the slot runs the ordinary search instead, and the
#: answer says which catalogues were asked, so it is a true answer rather than a
#: slow one.
_HARDER_AT_ONCE: Final = asyncio.Semaphore(1)


async def _within_deadline(
    searches: list[Coroutine[Any, Any, list[Record]]], deadline: float
) -> list[list[Record]]:
    """Run every search, keep what answers in time, drop the rest.

    **The deadline is an argument and has no default**, which is what stops the
    two from silently becoming one. A default would be whichever of them was
    written here, and the other would then be reached only by a caller that
    remembered to pass it; the failure mode is the long roster run under the
    short deadline, which cancels every slow source and produces exactly the
    result the reader asked to avoid, with nothing in the output to say so.

    **Empty is a real case and is answered here rather than raised.**
    `asyncio.wait` refuses an empty set with `ValueError`, so a library that has
    switched off every catalogue turned a title search into a 500. It arrived
    with the fix for the sibling case: `lookup` learned to say "nothing was
    asked" and this path was left to find out the hard way.
    """
    if not searches:
        return []
    tasks = [asyncio.ensure_future(search) for search in searches]
    done, pending = await asyncio.wait(tasks, timeout=deadline)

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
    # Last five, and named rather than left to the default so that a reader can
    # see it was decided. They are the newest and the least compared of the
    # eleven, and the field any of them would win is a field the DNB or K10plus
    # has already filled for any book all five hold. Where one is the only
    # catalogue with a row, precedence never runs.
    #
    # **The order among the five national catalogues is arbitrary**, which is
    # worth saying rather than implying a comparison nobody made. They collect
    # different countries, so a book two of them hold is a book the primary
    # three hold as well, and the tie this would break has not been observed.
    #
    # The NKP, the BNE and the BNA are here rather than absent because a source
    # missing from this tuple sorts last by default and silently, which is the
    # thing `test_precedence_names_every_source_and_nothing_else` exists to
    # catch. It caught the NKP. None of the three answers a title search, so
    # none can reach this comparison today; see `_SECONDARY_SOURCES`, which
    # carries the same three for the same reason.
    "oenb",
    "nlg",
    "nkp",
    "bne",
    "bna",
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
        subjects=uncontrolled(_open_library_subjects(entry)),
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
    isbn: str | None = None,
    limit: int = 10,
    prefer_language: str | None = None,
    *,
    access: Access,
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
        _work_cluster(isbn, max(limit - 1, 0), prefer_language, access.plan),
        search(query, limit=limit, prefer_language=prefer_language, access=access),
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
    """`editions`, bounded by `SEARCH_DEADLINE_SECONDS` and never fatal.

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


async def lookup(raw_isbn: str, *, access: Access) -> Lookup:
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

    **`access.logins` is what a catalogue asking for one is sent**, resolved by
    the caller: see `Access`. It is deliberately not part of the cache key, because
    a cached record is a book rather than a session: the same edition comes back
    whoever asked for it.
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
    together = access.plan.lookup_together
    fast = await asyncio.gather(
        *(
            _lookup_one(
                targets.SEEDED[name],
                isbn,
                access.api_key,
                credential=access.logins.get(name),
            )
            for name in together
        )
    )
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

    # **The tail this ISBN gets, which is not the whole tail.** A catalogue whose
    # remit is one registration group is not asked about a book from another
    # one: it is a round trip that cannot answer, and the tail stops at the first
    # hit so it is paid in front of whatever would have. `sources.SERVES_GROUPS`
    # carries the measurement and the bound that keeps it from losing a book.
    for name in access.plan.lookup_in_turn(registration_group(isbn)):
        result = await _lookup_one(
            targets.SEEDED[name],
            isbn,
            access.api_key,
            credential=access.logins.get(name),
        )
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
    #
    # **Read off the roster and not off `attempts`.** The question `NO_SOURCES`
    # answers is whether this library has a catalogue that can answer an ISBN at
    # all, and its 409 tells a household to go and switch one back on. Since the
    # group rule arrived, an empty `attempts` can also mean the list is full and
    # this book's registration group is outside every remit in it, which is a
    # fact about the book and gets that same wrong sentence.
    #
    # **The two spellings agree on today's roster and this is not a bug fix**,
    # which is worth saying because the paragraph above reads like one. The
    # leading tier is never filtered and holds a non metered chain member
    # whenever one exists, and every metered source is unrestricted, so an empty
    # `attempts` today implies an empty chain. They come apart the moment one
    # source is both metered and in `SERVES_GROUPS`, which is one row away and is
    # what `test_a_metered_source_with_a_remit_is_still_not_no_sources` pins.
    # The chain is the thing actually being asked about; `attempts` getting the
    # right answer is a coincidence of two rules that live elsewhere.
    outcome = Outcome.NO_SOURCES if not access.plan.lookup_chain else _worst(attempts)
    missed = Lookup(outcome, source="", attempts=attempts)
    async with _cache_lock:
        _remember(isbn, missed)
    logger.info(
        "No record for %s: %s",
        isbn,
        ", ".join(f"{name}={outcome.name.lower()}" for name, outcome in attempts),
    )
    return missed
