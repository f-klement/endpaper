"""Turning a scanned ISBN into a book, across several catalogues.

Previously this was two functions inside `routers/books.py`: Open Library, then
Google Books, then a bare 404. Three things were wrong with it, all of them
measured against the live deployment rather than guessed at.

1. **The Google fallback never sent the API key.** It built the URL by hand
   while `google_books.py` had a `_request` helper that appends `key`. So every
   fallback lookup went to the unauthenticated endpoint, which is rate limited
   per source address, and a household behind one address exhausts it almost at
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

The sources are ordered per ISBN rather than fixed: see `_sources_for`.
"""

import asyncio
import logging
import re
import time
import unicodedata
from collections.abc import Coroutine
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any, Final
from xml.etree import ElementTree

import httpx
from rapidfuzz.distance import Levenshtein

import covers
import google_books
from isbn import parse as parse_isbn

logger = logging.getLogger("endpaper.metadata")

# Third-party services sit on the request path, so the timeout is what stops a
# slow one from holding a worker open.
TIMEOUT_SECONDS: Final = 10


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


@dataclass(frozen=True)
class Lookup:
    """What the chain came back with, and from where."""

    outcome: Outcome
    data: dict[str, Any] | None = None
    #: Which source answered, for the log line and the cache entry.
    source: str = ""
    #: Every source that was tried, in order, with its own outcome. Kept so a
    #: failure can be explained rather than only reported.
    attempts: list[tuple[str, Outcome]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.outcome is Outcome.FOUND and self.data is not None


# ── Open Library ──────────────────────────────────────────────────────────────


async def _open_library(isbn: str, api_key: str) -> Lookup:
    """The edition record, plus one extra call for the author's name.

    `?default=false` on the cover URL matters: without it Open Library answers
    every request with a grey placeholder image, so a book with no cover gets
    one that looks like a broken image rather than no cover at all.
    """
    del api_key  # Open Library needs none.

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(f"https://openlibrary.org/isbn/{isbn}.json")
            if response.status_code == 429:
                return Lookup(Outcome.RATE_LIMITED, source="open_library")
            if response.status_code == 404:
                return Lookup(Outcome.NOT_FOUND, source="open_library")
            if response.status_code != 200:
                return Lookup(Outcome.UNAVAILABLE, source="open_library")
            data = response.json()

            author: str | None = None
            authors_list = data.get("authors", [])
            if authors_list:
                author_key = authors_list[0].get("key", "")
                author_response = await client.get(
                    f"https://openlibrary.org{author_key}.json"
                )
                if author_response.status_code == 200:
                    author = author_response.json().get("name")
    except (httpx.HTTPError, ValueError):
        logger.warning("Open Library lookup failed for %s", isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="open_library")

    publishers = data.get("publishers", [])
    publish_dates = data.get("publish_date", "")
    year_match = re.search(r"\d{4}", publish_dates) if publish_dates else None

    # description is either a plain string or {"value": ...}, depending on age.
    description_raw = data.get("description", "")
    description = (
        description_raw.get("value", "")
        if isinstance(description_raw, dict)
        else description_raw
    )

    subjects: list[str] = []
    for key in ("subjects", "subject_places", "subject_times", "subject_people"):
        for entry in data.get(key, []):
            if isinstance(entry, str):
                subjects.append(entry)
            elif isinstance(entry, dict) and "name" in entry:
                subjects.append(entry["name"])

    return Lookup(
        Outcome.FOUND,
        source="open_library",
        data={
            "isbn": isbn,
            "title": data.get("title", ""),
            "subtitle": data.get("subtitle"),
            "author": author,
            "publisher": publishers[0] if publishers else None,
            "year": int(year_match.group()) if year_match else None,
            "description": description or None,
            "cover_url": (
                f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
            ),
            "subjects": subjects,
        },
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
        Outcome.FOUND,
        source="google_books",
        data={
            "isbn": fields.get("isbn13") or isbn,
            "title": fields.get("title") or "",
            "subtitle": fields.get("subtitle"),
            "author": fields.get("author"),
            "publisher": fields.get("publisher"),
            "year": fields.get("year"),
            "description": fields.get("description"),
            "cover_url": fields.get("cover_url"),
            "series_name": fields.get("series_name"),
            "series_index": fields.get("series_index"),
            "subjects": google_books.split_categories(fields.get("categories")),
        },
    )


# ── Deutsche Nationalbibliothek ───────────────────────────────────────────────
#
# The legal deposit library for Germany, so it holds essentially everything
# published there. It is the reason a 978-3 shelf can be catalogued at all: for
# the two ISBNs that prompted this work, Open Library answered 404 and its
# search index returned no rows, while the DNB returned a full record for each.
#
# The public SRU endpoint needs no key and no registration. `oai_dc` is
# requested rather than MARC21 because Dublin Core is already the shape we
# want, where MARC would mean a subfield parser for the same five values.

_DNB_URL: Final = "https://services.dnb.de/sru/dnb"

_DC: Final = "{http://purl.org/dc/elements/1.1/}"
_SRW: Final = "{http://www.loc.gov/zing/srw/}"

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

# Creator roles worth keeping as the author. The DNB marks translators and
# editors the same way, and listing "deutsche Übersetzung von ..." as the
# author of a book is worse than listing nobody.
_AUTHOR_ROLES: Final = ("Verfasser", "Autor")


def _dnb_person(raw: str) -> tuple[str, str]:
    """Split `Kane, Sean P. [Verfasser]` into a display name and a role."""
    role_match = re.search(r"\[([^\]]+)\]\s*$", raw)
    role = role_match.group(1).strip() if role_match else ""
    name = re.sub(r"\s*\[[^\]]+\]\s*$", "", raw).strip()

    # Catalogue order is "Surname, Forenames". One comma means it is a person;
    # more than one, or none, means it is something else and is left alone.
    if name.count(",") == 1:
        surname, forenames = (part.strip() for part in name.split(","))
        if surname and forenames:
            name = f"{forenames} {surname}"
    return name, role


def _dnb_title(raw: str) -> tuple[str, str | None]:
    """Pull a title and subtitle out of the DNB's whole title statement.

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
    """`390 Seiten`, `348 S.` and `528 p.` all become a number.

    Shared by every MARC-derived source. The unit is required rather than
    optional: an extent statement also carries plate counts and dimensions, and
    a bare first number picks up `23 cm` as a page count.
    """
    if not raw:
        return None
    match = re.search(r"(\d+)\s*(?:Seiten|Bl\.|S\.|pages|p\.|pp\.)", raw)
    return int(match.group(1)) if match else None


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


def _dnb_record(record: ElementTree.Element, isbn: str | None) -> dict[str, Any] | None:
    """One Dublin Core record as book fields, or None if it is not a book.

    Shared by the lookup and the search paths. `isbn` is what the lookup
    already knows and verified; the search path has none, so the record's own
    identifier is read instead.
    """

    def text(tag: str) -> str | None:
        element = record.find(f"{_DC}{tag}")
        return element.text.strip() if element is not None and element.text else None

    raw_title = text("title")
    if not raw_title:
        return None
    title, subtitle = _dnb_title(raw_title)
    # A cross-referenced ISBN matched a volume slot, not this book. Reporting a
    # miss is right: some other catalogue may hold the real record, and putting
    # `[Hauptbd.].` in as a title poisons the entry for good.
    if _is_placeholder_title(title):
        return None

    extent = text("format")
    if not _is_physical_book(extent, title):
        return None

    people = [
        _dnb_person(element.text)
        for element in record.findall(f"{_DC}creator")
        if element.text
    ]
    authors = [name for name, role in people if role in _AUTHOR_ROLES]
    # A record with roles on nobody still names the author first, so falling
    # back to every listed person beats reporting no author at all.
    if not authors:
        authors = [name for name, _ in people]

    # "Heidelberg : O'Reilly" is place and publisher in one field.
    publisher = text("publisher")
    if publisher and " : " in publisher:
        publisher = publisher.split(" : ", 1)[1].strip()

    if isbn is None:
        isbn = next(
            (
                parsed
                for element in record.findall(f"{_DC}identifier")
                if element.text
                for parsed in [parse_isbn(element.text.split()[0])]
                if parsed is not None
            ),
            None,
        )

    year_match = re.search(r"\d{4}", text("date") or "")

    return {
        "isbn": isbn,
        "title": title,
        "subtitle": subtitle,
        "author": ", ".join(authors) or None,
        "publisher": publisher,
        "year": int(year_match.group()) if year_match else None,
        # The DNB catalogues books, not blurbs: there is no description in the
        # record, and inventing one from the subject headings would be worse
        # than leaving it empty.
        "description": None,
        "language": _LANGUAGES.get((text("language") or "").lower()),
        "page_count": _pages_from_extent(extent),
        # No cover either. Open Library serves one by ISBN for a good number of
        # German books even where it has no edition record, so it is worth the
        # guess: `default=false` makes it 404 rather than return a placeholder
        # when there is none.
        "cover_url": (
            f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
            if isbn
            else None
        ),
        # DDC headings such as "004 Informatik". The leading number is dropped
        # so it can match a tag by name.
        "subjects": [
            re.sub(r"^\d[\d.]*\s+", "", element.text.strip())
            for element in record.findall(f"{_DC}subject")
            if element.text
        ],
    }


async def _dnb(isbn: str, api_key: str) -> Lookup:
    del api_key  # The public SRU endpoint needs none.

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": f"num={isbn}",
        "recordSchema": "oai_dc",
        "maximumRecords": "1",
    }
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(_DNB_URL, params=params)
        if response.status_code == 429:
            return Lookup(Outcome.RATE_LIMITED, source="dnb")
        if response.status_code != 200:
            return Lookup(Outcome.UNAVAILABLE, source="dnb")
        root = ElementTree.fromstring(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("DNB lookup failed for %s", isbn, exc_info=True)
        return Lookup(Outcome.UNAVAILABLE, source="dnb")

    node = root.find(f".//{_DC}title/..")
    if node is None:
        return Lookup(Outcome.NOT_FOUND, source="dnb")

    record = _dnb_record(node, isbn)
    if record is None:
        logger.info("DNB matched %s only as a cross reference or a non-book", isbn)
        return Lookup(Outcome.NOT_FOUND, source="dnb")

    return Lookup(Outcome.FOUND, source="dnb", data=record)


# ── K10plus ───────────────────────────────────────────────────────────────────
#
# The union catalogue of the German library networks (GBV and SWB), roughly 200
# million records. It earns its place by being broad rather than national: it
# holds what German libraries hold, which is a large slice of English, French
# and Italian publishing alongside everything German.
#
# Measured over ten ISBNs spanning five languages: 6 hits, 3.5 of 5 fields per
# hit, 0.36s average. Open Library was broader (9 hits) but thinner (2.7) and
# five times slower (1.64s, one case over 3s). See `_FAST_SOURCES` for what
# that ranking bought.
#
# Free, no key, no registration. MARCXML rather than Dublin Core because the
# subfield structure is what makes the ISBN check below possible at all.

_K10PLUS_URL: Final = "https://sru.k10plus.de/opac-de-627"

_MARC: Final = "{http://www.loc.gov/MARC21/slim}"

#: Several printings of one book each carry the same ISBN, so the search
#: returns a handful of near-identical records and the fullest one wins.
_K10PLUS_RECORDS: Final = 5

#: MARC relator codes for somebody who wrote the thing. Translators (`trl`) and
#: editors (`edt`) arrive in the same field and must not become the author.
_AUTHOR_RELATORS: Final = ("aut", "cre")


def _marc_fields(record: ElementTree.Element) -> dict[str, list[dict[str, str]]]:
    """One MARC record as `{tag: [{subfield code: value}]}`."""
    fields: dict[str, list[dict[str, str]]] = {}
    for datafield in record.findall(f"{_MARC}datafield"):
        tag = datafield.get("tag")
        if tag is None:
            continue
        fields.setdefault(tag, []).append(
            {
                subfield.get("code") or "": (subfield.text or "").strip()
                for subfield in datafield.findall(f"{_MARC}subfield")
            }
        )
    return fields


def _marc_claims_isbn(fields: dict[str, list[dict[str, str]]], isbn: str) -> bool:
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


def _strip_person_noise(raw: str) -> str:
    """Drop life dates and role words from a catalogue person string."""
    cleaned = raw
    for _ in range(3):  # A name can carry both, in either order.
        stripped = _PERSON_NOISE.sub("", cleaned).strip().rstrip(".,;")
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


def _marc_authors(fields: dict[str, list[dict[str, str]]]) -> str | None:
    """The 100 main entry plus any 700 that actually wrote something."""
    names: list[str] = []
    for entry in fields.get("100", []):
        if entry.get("a"):
            names.append(_flip_catalogue_name(entry["a"]))
    for entry in fields.get("700", []):
        # `t` marks an added entry for a *work*, not a person: the row exists
        # to link the original title, and its name is the original author's.
        if entry.get("a") and "t" not in entry and entry.get("4") in _AUTHOR_RELATORS:
            names.append(_flip_catalogue_name(entry["a"]))
    # Order preserved, repeats dropped: 100 and 700 can name the same person.
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return ", ".join(seen) or None


def _marc_title(entry: dict[str, str]) -> tuple[str, str | None, str | None, float | None]:
    """A 245 field as title, subtitle, series name and series number.

    `$n` and `$p` are the part designation and part title, which is how a
    catalogue records a numbered volume: `$a=Harry Potter`, `$n=[1]`,
    `$p=Harry Potter and the philosopher's stone`. The part title is the book
    somebody is holding, so it becomes the title, and the collective title
    becomes the series. Without this the whole series is catalogued seven times
    under one name.
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


def _marc_year(fields: dict[str, list[dict[str, str]]]) -> int | None:
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
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(_K10PLUS_URL, params=params)
        if response.status_code == 429:
            return Lookup(Outcome.RATE_LIMITED, source="k10plus")
        if response.status_code != 200:
            return Lookup(Outcome.UNAVAILABLE, source="k10plus")
        root = ElementTree.fromstring(response.text)
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

    data = [_k10plus_record(fields, isbn) for fields in candidates]
    return Lookup(
        Outcome.FOUND, source="k10plus", data=max(data, key=_completeness)
    )


def _marc_isbn(fields: dict[str, list[dict[str, str]]]) -> str | None:
    """The record's own ISBN, ignoring cross references to other editions."""
    for entry in fields.get("020", []):
        if "q" in entry:
            continue
        parsed = parse_isbn(entry.get("a", ""))
        if parsed is not None:
            return parsed
    return None


def _k10plus_record(
    fields: dict[str, list[dict[str, str]]], isbn: str | None = None
) -> dict[str, Any]:
    """One MARC record as book fields.

    `isbn` is passed by the lookup path, where it is already known and already
    verified. The search path has none, so it is read off 020 instead.
    """
    isbn = isbn or _marc_isbn(fields)
    title_entry = (fields.get("245") or [{}])[0]
    title, subtitle, series_name, series_index = _marc_title(title_entry)

    publisher = next(
        (
            entry["b"].rstrip(",")
            for tag in ("264", "260")
            for entry in fields.get(tag, [])
            if entry.get("b")
        ),
        None,
    )

    language = None
    for entry in fields.get("041", []):
        language = _LANGUAGES.get(entry.get("a", "").lower())
        if language:
            break

    subjects = [
        " ".join(part for part in (entry.get("a"), entry.get("x")) if part)
        for entry in fields.get("650", [])
        if entry.get("a")
    ]

    description = next(
        (entry["a"] for entry in fields.get("520", []) if entry.get("a")), None
    )

    return {
        "isbn": isbn,
        "title": title,
        "subtitle": subtitle,
        "author": _marc_authors(fields),
        "publisher": publisher,
        "year": _marc_year(fields),
        "description": description,
        "language": language,
        "page_count": _pages_from_extent(
            next((entry.get("a") for entry in fields.get("300", [])), None)
        ),
        "series_name": series_name,
        "series_index": series_index,
        # No cover in a MARC record. The Open Library cover service answers by
        # ISBN for a good number of these anyway, and `default=false` makes it
        # 404 rather than hand back a placeholder when it has none. A record
        # with no ISBN at all, which is most pre-1970 printings, gets none.
        "cover_url": (
            f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
            if isbn
            else None
        ),
        "subjects": subjects,
    }


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

_SOURCES: Final = {
    "open_library": _open_library,
    "google_books": _google_books,
    "dnb": _dnb,
    "k10plus": _k10plus,
}

#: Asked together, on every lookup. Free, unmetered, and fast enough that the
#: cost of asking both is the slower of the two rather than the sum.
_FAST_SOURCES: Final = ("dnb", "k10plus")

#: Asked in turn, only if the fast pair found nothing. Open Library is broad and
#: slow; Google is the only source with a key, a quota and a bill attached.
_FALLBACK_SOURCES: Final = ("open_library", "google_books")

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


#: Fields worth having, and therefore worth scoring a record on.
_SCORED_FIELDS: Final = (
    "author",
    "year",
    "publisher",
    "page_count",
    "language",
    "description",
    "series_name",
)


def _completeness(data: dict[str, Any]) -> int:
    """How much of a record is actually filled in.

    Used twice: to choose between several printings of one ISBN within a single
    catalogue, and to decide which catalogue leads the merge when both answer.
    """
    score = sum(1 for name in _SCORED_FIELDS if data.get(name))
    return score + (1 if data.get("subjects") else 0)


def _merge(results: list[Lookup], isbn: str) -> dict[str, Any]:
    """Fold several catalogues' answers into one record.

    Taking the first hit and stopping is what the chain used to do, and it left
    fields empty that the next source down would have filled: K10plus carries
    page counts and series numbering, the DNB carries subject headings, and
    neither reliably carries a blurb. Nothing is overwritten, only filled in,
    so the leading source stays the one describing the book.

    Subjects are unioned rather than replaced. They feed the tag suggestion,
    where a heading from either catalogue is equally good evidence.
    """
    preferred = _preferred_source(isbn)
    ordered = sorted(
        results,
        key=lambda result: (result.source == preferred, _completeness(result.data or {})),
        reverse=True,
    )

    merged: dict[str, Any] = dict(ordered[0].data or {})
    subjects: list[str] = list(merged.get("subjects") or [])

    for result in ordered[1:]:
        for name, value in (result.data or {}).items():
            if name == "subjects":
                subjects.extend(value or [])
            elif merged.get(name) is None and value is not None:
                merged[name] = value

    seen: dict[str, None] = {}
    for subject in subjects:
        seen.setdefault(subject, None)
    merged["subjects"] = list(seen)
    return merged


# ── Title search ──────────────────────────────────────────────────────────────
#
# The other half of getting a book in: no barcode to scan, a damaged one, or a
# book printed before ISBNs existed at all. Until recently this was Google
# Books only, which meant a household without an API key had **no way** to add
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

_OPEN_LIBRARY_SEARCH: Final = "https://openlibrary.org/search.json"

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


async def _open_library_search(query: str, limit: int) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "limit": str(limit),
        "fields": _OPEN_LIBRARY_SEARCH_FIELDS,
    }
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(_OPEN_LIBRARY_SEARCH, params=params)
        if response.status_code != 200:
            logger.info("Open Library search returned %s", response.status_code)
            return []
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Open Library search failed for %r", query, exc_info=True)
        return []

    results: list[dict[str, Any]] = []
    for doc in payload.get("docs", [])[:limit]:
        cover_id = doc.get("cover_i")
        results.append(
            {
                "google_books_id": None,
                "title": doc.get("title"),
                "subtitle": doc.get("subtitle"),
                # Every credited name, in order. Joined the same way the DNB
                # and K10plus parsers join theirs, so one book looks the same
                # whichever source found it.
                "author": ", ".join(doc.get("author_name") or []) or None,
                "publisher": (doc.get("publisher") or [None])[0],
                "year": doc.get("first_publish_year"),
                # The search index carries no blurb. Enrichment fills it in.
                "description": None,
                "page_count": doc.get("number_of_pages_median"),
                "language": _LANGUAGES.get((doc.get("language") or [""])[0].lower()),
                "categories": None,
                "cover_url": (
                    f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
                    if cover_id
                    else None
                ),
                "isbn13": _first_isbn13(doc.get("isbn") or []),
                "series_name": None,
                "series_index": None,
                "source": "open_library",
            }
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
_NOT_A_BOOK: Final = re.compile(
    r"online[- ]?(ressource|resource)|elektronische ressource|streaming|"
    r"audio disc|sound (disc|recording)|videodisc|dvd|blu-?ray",
    re.IGNORECASE,
)


def _is_physical_book(extent: str | None, title: str) -> bool:
    """Whether a record describes something that can sit on a shelf."""
    if extent and _NOT_A_BOOK.search(extent):
        return False
    return not _is_placeholder_title(title)


async def _k10plus_search(query: str, limit: int) -> list[dict[str, Any]]:
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
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(_K10PLUS_URL, params=params)
        if response.status_code != 200:
            return []
        root = ElementTree.fromstring(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("K10plus search failed for %r", query, exc_info=True)
        return []

    results: list[dict[str, Any]] = []
    for node in root.iter(f"{_MARC}record"):
        fields = _marc_fields(node)
        record = _k10plus_record(fields)
        extent = next((entry.get("a") for entry in fields.get("300", [])), None)
        if not record["title"] or not _is_physical_book(extent, record["title"]):
            continue
        results.append(_as_match(record, "k10plus"))
    return results


async def _dnb_search(query: str, limit: int) -> list[dict[str, Any]]:
    """The DNB, through its word-sequence index.

    `WOE` is the index that takes several words and requires all of them, which
    is what a typed search actually means. It is precise to the point of being
    narrow: "clean code martin" is one record.
    """
    terms = _search_terms(query)
    if not terms:
        return []

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": f"WOE={' '.join(terms)}",
        "recordSchema": "oai_dc",
        "maximumRecords": str(min(limit * 3, 50)),
    }
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(_DNB_URL, params=params)
        if response.status_code != 200:
            return []
        root = ElementTree.fromstring(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("DNB search failed for %r", query, exc_info=True)
        return []

    results: list[dict[str, Any]] = []
    for node in root.findall(f".//{_DC}title/.."):
        record = _dnb_record(node, isbn=None)
        if record is None:
            continue
        results.append(_as_match(record, "dnb"))
    return results


# ── The regional catalogues ───────────────────────────────────────────────────
#
# Kept for the languages the primary three cover least well, and ranked below
# them for exactly that reason: they are here for the books nobody else holds,
# not to reorder the ones everybody does.
#
#   bnf   Bibliothèque nationale de France. French legal deposit. Free, no key.
#   loc   Library of Congress. Poor for ISBN lookup (two hits in ten, both
#         covered elsewhere) and worth having for search, where it holds
#         Spanish, Portuguese and Latin American printings the German and
#         French catalogues do not: "cien anos de soledad" returns 73 records,
#         "ensaio sobre a cegueira" six.
#
# Spain and Portugal have no usable free interface of their own. The Biblioteca
# Nacional de España redirects its SRU endpoint and refuses its SPARQL one; the
# Portuguese PORBASE endpoint is gone. The Library of Congress is the honest
# substitute rather than a first choice.

_BNF_URL: Final = "https://catalogue.bnf.fr/api/SRU"
_LOC_URL: Final = "http://lx2.loc.gov:210/lcdb"

_MODS: Final = "{http://www.loc.gov/mods/v3}"

#: BnF `dc:type` values that are a printed book. It also catalogues manuscripts,
#: scores, maps and recordings, all of which match a title search.
_BNF_PRINTED: Final = ("texte imprim", "printed text", "text")


async def _bnf_search(query: str, limit: int) -> list[dict[str, Any]]:
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
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(_BNF_URL, params=params)
        if response.status_code != 200:
            return []
        root = ElementTree.fromstring(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("BnF search failed for %r", query, exc_info=True)
        return []

    results: list[dict[str, Any]] = []
    for node in root.findall(f".//{_DC}title/.."):
        record = _bnf_record(node)
        if record is not None:
            results.append(_as_match(record, "bnf"))
    return results


def _bnf_record(record: ElementTree.Element) -> dict[str, Any] | None:
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
    title, subtitle = _dnb_title(titles[0])
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

    return {
        "isbn": isbn,
        "title": title,
        "subtitle": subtitle,
        "author": _bnf_authors(texts("creator")),
        "publisher": publisher,
        "year": int(year_match.group()) if year_match else None,
        "description": None,
        "language": _LANGUAGES.get((texts("language") or [""])[0].lower()),
        "page_count": _pages_from_extent(extent),
        "cover_url": (
            f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
            if isbn
            else None
        ),
        "subjects": texts("subject"),
        "series_name": None,
        "series_index": None,
    }


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


async def _loc_search(query: str, limit: int) -> list[dict[str, Any]]:
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
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.get(_LOC_URL, params=params)
        if response.status_code != 200:
            return []
        root = ElementTree.fromstring(response.text)
    except (httpx.HTTPError, ElementTree.ParseError):
        logger.warning("Library of Congress search failed for %r", query, exc_info=True)
        return []

    results: list[dict[str, Any]] = []
    for node in root.iter(f"{_MODS}mods"):
        record = _loc_record(node)
        if record is not None:
            results.append(_as_match(record, "loc"))
    return results


def _loc_record(record: ElementTree.Element) -> dict[str, Any] | None:
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

    return {
        "isbn": isbn,
        "title": title,
        "subtitle": subtitle,
        "author": ", ".join(authors) or None,
        "publisher": publisher,
        "year": int(year_match.group()) if year_match else None,
        "description": None,
        "language": language,
        "page_count": _pages_from_extent(extent),
        "cover_url": (
            f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
            if isbn
            else None
        ),
        "subjects": [
            element.text.strip()
            for element in record.findall(f"{_MODS}subject/{_MODS}topic")
            if element.text
        ],
        "series_name": None,
        "series_index": None,
    }


def _as_match(record: dict[str, Any], source: str) -> dict[str, Any]:
    """A lookup-shaped record as a search-result-shaped one.

    The two shapes differ in three places and nowhere else: a lookup knows the
    ISBN it was asked about, a match carries `isbn13` and a `source`, and a
    match's categories are the joined string the client already understands.
    """
    return {
        "source": source,
        "google_books_id": None,
        "title": record.get("title"),
        "subtitle": record.get("subtitle"),
        "author": record.get("author"),
        "publisher": record.get("publisher"),
        "year": record.get("year"),
        "description": record.get("description"),
        "page_count": record.get("page_count"),
        "language": record.get("language"),
        "categories": google_books.join_categories(record.get("subjects") or []) or None,
        "cover_url": record.get("cover_url"),
        "isbn13": record.get("isbn"),
        "series_name": record.get("series_name"),
        "series_index": record.get("series_index"),
    }


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
#: without ever outranking a real title match: a German household searching an
#: English title still gets the English book.
_LANGUAGE_WEIGHT: Final = 3

#: Catalogues kept for the languages the primary three cover least well. A row
#: only they found is worth having; a row they merely duplicate is not worth
#: promoting, so a point comes off. One point is less than a single term match,
#: so this only ever breaks a tie.
_SECONDARY_SOURCES: Final = frozenset({"bnf", "loc"})
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
    "isbn13",
    "cover_url",
)


def _relevance(
    match: dict[str, Any], terms: list[str], prefer_language: str | None
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
    title = _normalise_words(match.get("title"))
    searchable = title | _normalise_words(match.get("subtitle"))
    author = _normalise_words(match.get("author"))
    series = _normalise_words(match.get("series_name"))

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

    if prefer_language and match.get("language") == prefer_language:
        score += _LANGUAGE_WEIGHT

    # Regional catalogues answer last among equals. The penalty applies only
    # when they are the **only** source for a row: a book a primary catalogue
    # also holds is a primary row, and docking it for having been confirmed by
    # a second catalogue pushed the fuller record below the sparser one.
    sources = {source for source in match.get("source", "").split("+") if source}
    if sources and sources <= _SECONDARY_SOURCES:
        score -= _SECONDARY_PENALTY

    completeness = sum(1 for name in _COMPLETENESS_FIELDS if match.get(name))
    return (score, completeness, match.get("year") or 0)


def _match_key(match: dict[str, Any]) -> str:
    """What makes two results from different sources the same book.

    Deliberately lossy, and it only has to be good enough to stop the picker
    showing the same book twice. `_duplicate_key` in the books router does the
    same job for stored books and does it more carefully, because a wrong
    answer there merges two records rather than hiding one row.
    """
    title = re.sub(r"[^\w\s]", "", (match.get("title") or "").casefold()).strip()
    author = (match.get("author") or "").casefold().split(",")[0].strip()
    return f"{title}|{author}"


async def search(
    query: str,
    api_key: str = "",
    limit: int = 10,
    prefer_language: str | None = None,
) -> list[dict[str, Any]]:
    """Find a book by title and author, across every catalogue available.

    Three tiers, and the tiering is what keeps this both broad and quick.

    **Tier one, free, primary:** Open Library for breadth and covers, K10plus
    for German and European publishing, the DNB for German legal deposit.

    **Tier two, free, regional:** the BnF for French, the Library of Congress
    for Spanish, Portuguese and Latin American printings. Both are ranked a
    point below the primaries: they are here for the books nobody else holds,
    not to reorder the ones everybody does.

    **Tier three, only with a key:** Google Books, for the blurb and the
    categories the others do not carry.

    Every source in every tier is asked **concurrently**, so the wall clock is
    the slowest of six rather than the sum, measured at 1.2s to 1.8s.

    **Then ours:** filtering out what is not a book, merging one book's rows
    from several catalogues into one, and ranking the result against the query.
    That last part is not optional. The SRU catalogues return catalogue order,
    which is roughly newest first, so without it a search for a novel surfaces
    whichever reprint was catalogued most recently.

    `prefer_language` breaks ties towards the reader's own language without
    ever outranking a title match, so a German household searching an English
    title still gets the English book.

    A source that fails is skipped rather than failing the search. Losing one
    of four is not worth refusing to answer.
    """
    trimmed = query.strip()
    terms = _search_terms(trimmed)
    if not terms:
        return []

    async def _google() -> list[dict[str, Any]]:
        if not api_key:
            return []
        try:
            found = await google_books.search(trimmed, api_key, limit=limit)
        except (google_books.GoogleBooksError, httpx.HTTPError, ValueError):
            logger.info("Google Books search unavailable for %r", trimmed, exc_info=True)
            return []
        return [dict(item, source="google_books") for item in found]

    tiers = await _within_deadline(
        [
            _open_library_search(trimmed, limit),
            _k10plus_search(trimmed, limit),
            _dnb_search(trimmed, limit),
            _bnf_search(trimmed, limit),
            _loc_search(trimmed, limit),
            _google(),
        ]
    )

    merged = _merge_matches([row for tier in tiers for row in tier])

    ranked = sorted(
        merged, key=lambda match: _relevance(match, terms, prefer_language), reverse=True
    )
    return ranked[:limit]


#: How long a search may take, whatever the catalogues do.
#:
#: Six sources are asked at once, so the wall clock is the slowest of them, and
#: one national catalogue having a bad afternoon was turning a 1.3s search into
#: a 7s one. A deadline degrades the *results* instead of the latency: whatever
#: has answered is ranked and returned, and the straggler is cancelled.
#:
#: Well above the 1.2s to 1.8s a healthy search measures, so this only ever
#: fires on a source that is genuinely struggling.
SEARCH_DEADLINE_SECONDS: Final = 4.0


async def _within_deadline(
    searches: list[Coroutine[Any, Any, list[dict[str, Any]]]],
) -> list[list[dict[str, Any]]]:
    """Run every search, keep what answers in time, drop the rest."""
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
)


def _merge_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    """
    order = {source: index for index, source in enumerate(_MATCH_PRECEDENCE)}
    rows: list[dict[str, Any]] = []
    by_isbn: dict[str, dict[str, Any]] = {}
    by_work: dict[str, dict[str, Any]] = {}

    def register(row: dict[str, Any]) -> None:
        isbn = row.get("isbn13")
        if isbn:
            by_isbn[isbn] = row
        by_work[f"{_match_key(row)}:{row.get('year') or ''}"] = row

    for match in matches:
        if not match.get("title"):
            continue

        isbn = match.get("isbn13")
        work = f"{_match_key(match)}:{match.get('year') or ''}"
        existing = (by_isbn.get(isbn) if isbn else None) or by_work.get(work)

        # A translation is not the same book. Two rows sharing a title, an
        # author and a year but naming **different** languages are a German
        # printing and an English one, and folding them together hides the one
        # somebody wants. Only refused when both actually say: an unknown
        # language is not evidence of disagreement.
        if existing is not None:
            languages = {existing.get("language"), match.get("language")}
            if None not in languages and len(languages) > 1:
                existing = None

        if existing is None:
            row = dict(match)
            rows.append(row)
            register(row)
            continue

        # The more trusted source leads and the other fills its gaps, so a
        # Google blurb and a K10plus page count end up on one row.
        incoming_rank = order.get(match.get("source", ""), len(order))
        existing_rank = min(
            (order.get(source, len(order)) for source in existing.get("source", "").split("+")),
            default=len(order),
        )
        if incoming_rank < existing_rank:
            # The new row leads. Rewrite in place so the list keeps its slot.
            filler = dict(existing)
            existing.clear()
            existing.update(match)
        else:
            filler = match
        for name, value in filler.items():
            if name != "source" and existing.get(name) is None and value is not None:
                existing[name] = value

        # Every catalogue that found it, so the picker can say where a row came
        # from and a bug report can name the source.
        sources = {
            *filler.get("source", "").split("+"),
            *existing.get("source", "").split("+"),
        }
        existing["source"] = "+".join(sorted(part for part in sources if part))
        register(existing)

    return rows


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
    """Drop every entry. For tests, and for an admin who has just set a key."""
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


async def lookup(raw_isbn: str, api_key: str = "") -> Lookup:
    """Resolve an ISBN to the best record the free catalogues can produce.

    Two phases. The fast pair is asked **together** and their answers merged,
    which is where the record quality comes from. Only if neither knows the
    book do the broad-but-slow and the metered sources get a turn, one at a
    time, so an ordinary lookup never spends Google quota at all.

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
    fast = await asyncio.gather(
        *(_SOURCES[name](isbn, api_key) for name in _FAST_SOURCES)
    )
    attempts.extend(
        (name, result.outcome)
        for name, result in zip(_FAST_SOURCES, fast, strict=True)
    )

    hits = [result for result in fast if result.found]
    if hits:
        sources = "+".join(sorted(result.source for result in hits))
        merged = _merge(hits, isbn)
        # Neither of the fast pair carries an image: they are bibliographic
        # catalogues returning MARC and Dublin Core. The cover is resolved
        # against the image services and **checked**, because storing an
        # unverified guess is how a book ends up with a permanently broken
        # cover. See covers.py.
        merged["cover_url"] = await covers.resolve(isbn, merged.get("cover_url"))
        found = Lookup(
            Outcome.FOUND, data=merged, source=sources, attempts=attempts
        )
        async with _cache_lock:
            _remember(isbn, found)
        logger.info("Resolved %s from %s", isbn, sources)
        return found

    for name in _FALLBACK_SOURCES:
        result = await _SOURCES[name](isbn, api_key)
        attempts.append((name, result.outcome))
        if result.found:
            data = dict(result.data or {})
            # Open Library's own record carries a cover URL and Google's
            # carries a thumbnail from the volume record. Both are checked
            # here too: an Open Library edition record does not guarantee the
            # cover service has an image for it.
            data["cover_url"] = await covers.resolve(isbn, data.get("cover_url"))
            found = Lookup(
                Outcome.FOUND, data=data, source=name, attempts=attempts
            )
            async with _cache_lock:
                _remember(isbn, found)
            logger.info("Resolved %s from %s", isbn, name)
            return found

    missed = Lookup(_worst(attempts), source="", attempts=attempts)
    async with _cache_lock:
        _remember(isbn, missed)
    logger.info(
        "No record for %s: %s",
        isbn,
        ", ".join(f"{name}={outcome.name.lower()}" for name, outcome in attempts),
    )
    return missed
