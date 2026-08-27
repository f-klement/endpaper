"""Metadata enrichment from the Google Books API.

Distinct from the ISBN lookup in `routers/books.py`, which runs once when a
book is added and fills the fields needed to recognise it. This runs on demand,
against a book already in the catalogue, and fills the fields Open Library
usually lacks: page count, language, and the publisher's own subject
categories.

Needs an API key. The unauthenticated endpoint exists but is rate limited per
IP, which for a library behind one address means a handful of lookups before
everyone is throttled together.
"""

import logging
import re
from typing import Any, Final

import covers
import fetch
from isbn import parse as parse_isbn

logger = logging.getLogger("endpaper.google_books")

_VOLUMES_URL: Final = "https://www.googleapis.com/books/v1/volumes"


class GoogleBooksError(Exception):
    """Raised for anything the caller should be told about verbatim."""


# Semicolon, not comma: Google's own category names contain commas ("Fiction,
# general"), so a comma-joined list cannot be split back apart. Everything
# that joins or splits this field goes through the two helpers below.
CATEGORY_SEPARATOR: Final = "; "


def join_categories(categories: list[str]) -> str | None:
    return CATEGORY_SEPARATOR.join(categories) or None


def split_categories(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(CATEGORY_SEPARATOR.strip()) if part.strip()]


def _volume_to_fields(volume: dict[str, Any]) -> dict[str, Any]:
    """Pick out the fields worth storing, ignoring the rest of the payload."""
    info = volume.get("volumeInfo", {})

    categories = info.get("categories") or []
    identifiers = info.get("industryIdentifiers") or []
    isbn13 = next(
        (entry["identifier"] for entry in identifiers if entry.get("type") == "ISBN_13"),
        None,
    )

    published = str(info.get("publishedDate") or "")
    year = int(published[:4]) if published[:4].isdigit() else None

    series_name, series_index = _series_from(info)

    return {
        "google_books_id": volume.get("id"),
        "series_name": series_name,
        "series_index": series_index,
        "title": info.get("title"),
        "subtitle": info.get("subtitle"),
        "author": ", ".join(info.get("authors") or []) or None,
        "publisher": info.get("publisher"),
        "year": year,
        "description": info.get("description"),
        "page_count": info.get("pageCount"),
        "language": info.get("language"),
        # Stored as one string rather than related rows: these are whatever the
        # publisher supplied, not the curated Tag vocabulary the library picks
        # from, and mixing the two would muddle both.
        "categories": join_categories(categories),
        # Google serves these over plain **http**, which is mixed content on an
        # https page: blocked by the browser, whatever the CSP says. Cleaned
        # here rather than only on the way into the database, because a search
        # result is rendered in the picker long before anything is stored, and
        # the question "may a browser be pointed at this?" has the same answer
        # either way.
        "cover_url": covers.storable((info.get("imageLinks") or {}).get("thumbnail")),
        "isbn13": isbn13,
    }


def _series_from(info: dict[str, Any]) -> tuple[str | None, float | None]:
    """Pull series name and number out of a volume.

    Google has a structured `seriesInfo` on some volumes and nothing at all on
    most. Where it is absent the title is the only source, and titles carry the
    series in a small number of recognisable shapes:

        Dune (Dune Chronicles #1)
        Dune, Book 1
        Dune (Dune #1)

    Deliberately conservative. A wrong series silently regroups the shelf and
    invents gaps that are not there, so anything that does not match one of
    these shapes is left alone for a person to fill in.
    """
    name, index = _series_from_title(info.get("title") or "")

    # `seriesInfo` carries the position and, despite the field name,
    # `bookDisplayNumber` is a number rather than a series name. The name is
    # not in that payload at all, so the title stays the only source for it and
    # this only ever improves the index.
    series = info.get("seriesInfo") or {}
    if series.get("volumeSeries"):
        display = str(series.get("bookDisplayNumber") or "").strip()
        order = (series["volumeSeries"][0] or {}).get("orderNumber")
        from_info = _to_index(display) if display else _to_index(str(order))
        if from_info is not None:
            index = from_info

    return name, index


_SERIES_PATTERNS = (
    # "Dune (Dune Chronicles #1)" and "Dune (Dune Chronicles, Book 1)"
    re.compile(r"\(([^)]+?)[,\s]+(?:#|book\s+|bk\.?\s*)(\d+(?:\.\d+)?)\)\s*$", re.I),
    # "Dune, Book 1"
    re.compile(r"^(?P<ignored>.*?),\s*book\s+(\d+(?:\.\d+)?)\s*$", re.I),
)


def _series_from_title(title: str) -> tuple[str | None, float | None]:
    match = _SERIES_PATTERNS[0].search(title)
    if match:
        return match.group(1).strip(), _to_index(match.group(2))

    match = _SERIES_PATTERNS[1].match(title)
    if match:
        # This shape names no series, only a position in one. Reporting the
        # number without a name would put the book in a nameless series, so
        # only the index is taken.
        return None, _to_index(match.group(2))

    return None, None


def _to_index(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def _request(params: dict[str, str], api_key: str) -> dict[str, Any]:
    query = dict(params)
    if api_key:
        query["key"] = api_key

    response = await fetch.get_once(_VOLUMES_URL, params=query)

    if response.status_code in (401, 403):
        # Almost always a bad or restricted key, and the admin can fix it, so
        # say so rather than reporting a generic failure.
        raise GoogleBooksError(
            "Google Books rejected the API key. Check it in Settings, and that "
            "the Books API is enabled for it."
        )
    if response.status_code == 429:
        raise GoogleBooksError("Google Books is rate limiting this key. Try again later.")
    if response.status_code != 200:
        logger.error("Google Books returned %s", response.status_code)
        raise GoogleBooksError("Google Books is not responding. Try again later.")

    return dict(response.json())


async def lookup_by_isbn(isbn: str, api_key: str) -> dict[str, Any] | None:
    """The volume for an ISBN, or None if Google does not know it."""
    canonical = parse_isbn(isbn)
    if canonical is None:
        return None

    payload = await _request({"q": f"isbn:{canonical}"}, api_key)
    items = payload.get("items") or []
    if not items:
        return None
    return _volume_to_fields(items[0])


async def search(query: str, api_key: str, limit: int = 5) -> list[dict[str, Any]]:
    """Free-text search, for books whose ISBN is unknown or wrong.

    A scanned ISBN can be missing from Google's catalogue even when the book is
    there under a different edition, so title and author are the fallback.
    """
    if not query.strip():
        return []

    payload = await _request(
        {"q": query.strip(), "maxResults": str(min(limit, 20))}, api_key
    )
    items = payload.get("items") or []
    return [_volume_to_fields(item) for item in items[:limit]]


def merge_into(book: object, fields: dict[str, Any], *, overwrite: bool) -> list[str]:
    """Copy fields onto a book, returning the names actually changed.

    By default only empty fields are filled. Enrichment is meant to add what is
    missing, not to overrule what someone typed by hand: a member who corrected
    a title should not have Google quietly undo it. `overwrite` is offered for
    the case where the stored record is known to be wrong.
    """
    changed: list[str] = []

    for name in (
        "subtitle",
        "author",
        "publisher",
        "year",
        "description",
        "page_count",
        "language",
        "categories",
        "google_books_id",
        "series_name",
        "series_index",
    ):
        incoming = fields.get(name)
        if incoming in (None, "", []):
            continue

        current = getattr(book, name, None)
        if current not in (None, "") and not overwrite:
            continue
        if current == incoming:
            continue

        setattr(book, name, incoming)
        changed.append(name)

    # A cover the member uploaded lives under /covers/ and always outranks a
    # remote one, exactly as in the metadata refresh.
    incoming_cover = fields.get("cover_url")
    current_cover = getattr(book, "cover_url", None)
    keeps_local_cover = (current_cover or "").startswith("/covers/")
    replaceable = not current_cover or overwrite

    if (
        incoming_cover
        and not keeps_local_cover
        and replaceable
        and current_cover != incoming_cover
    ):
        book.cover_url = incoming_cover  # type: ignore[attr-defined]
        changed.append("cover_url")

    return changed
