"""Metadata enrichment from the Google Books API.

Distinct from the ISBN lookup in `routers/books.py`, which runs once when a
book is added and fills the fields needed to recognise it. This runs on demand,
against a book already in the catalogue, and fills the fields Open Library
usually lacks: page count, language, and the publisher's own subject
categories.

Needs an API key. The unauthenticated endpoint exists but is rate limited per
IP, which for a library behind one address means a handful of lookups before
everyone is throttled together.

**Three ways in, and the third is the only exact one.** `lookup_by_isbn` and
`search` ask `/volumes` a question; `lookup_by_volume_id` asks `/volumes/{id}`
for a record by its own name. A Google Play Books Takeout carries a volume id
for every book and no ISBN at all, so that third door is the difference between
a store import matched by title and one matched by identifier.
"""

import logging
import re
from typing import TYPE_CHECKING, Any, Final

import covers
import fetch
import targets
from enums import CatalogueSource
from isbn import parse as parse_isbn

if TYPE_CHECKING:
    # Under `TYPE_CHECKING` because the dependency is genuinely mutual:
    # `schemas/book.py` imports `split_categories` from this module, so a
    # runtime import here is a cycle and fails on the first import of either.
    # `merge_into` only ever calls methods on the value, never the class, so
    # the name is needed for the annotation and nowhere else, and PEP 649
    # leaves an annotation unevaluated. Removing the guard is an ImportError
    # rather than a subtle failure.
    from schemas.book import BookMatch

logger = logging.getLogger("endpaper.google_books")

#: The volumes endpoint, read off Google Books' row rather than written twice.
#: See `metadata._OPEN_LIBRARY` for why an address may not be a second literal.
_VOLUMES_URL: Final = targets.SEEDED[CatalogueSource.GOOGLE_BOOKS].base_url


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


def _mapping(value: object) -> dict[str, Any]:
    """A JSON object, or an empty one for anything else.

    **Every reader below assumes a shape this payload does not promise.** Google
    answers with JSON of its own design and this module is the only thing between
    it and a Book, so a `volumeInfo` that arrives as a list turns `.get` into an
    `AttributeError` and a 500 out of the unhandled exception handler, on a route
    whose only other failure modes are a 404 and a 503. Measured against
    `_volume_to_fields` directly: `{"volumeInfo": []}` raised
    `AttributeError: 'list' object has no attribute 'get'`.

    `str` is the case worth naming, because it is the one a looser test admits:
    a string is iterable and subscriptable, so anything short of an `isinstance`
    check on `dict` lets one through to fail further in.
    """
    return value if isinstance(value, dict) else {}


def _strings(value: object) -> list[str]:
    """The strings in a JSON array, dropping everything else.

    **A bare string is not a list of one, and that is the arm worth having.**
    `", ".join("Dune")` is `"D, u, n, e"`, so an `authors` that arrives as a
    string rather than an array would put a credit line of single letters on a
    Book with no error anywhere. Refusing the whole value is right because the
    two shapes are not a spelling apart: Google's field is documented as an
    array, so a string there is a payload this module does not understand.
    """
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str)]


def _volume_to_fields(volume: dict[str, Any]) -> dict[str, Any]:
    """Pick out the fields worth storing, ignoring the rest of the payload.

    **Nothing here trusts a type.** See `_mapping`: this is somebody else's JSON
    and the accessors around it are the whole of what stops an odd payload being
    a 500. The two collections are read through the helpers above, because they
    are **joined** here rather than passed along, and a join is where a wrong
    type stops being a wrong value and starts being an exception.

    **The scalars are left as they arrive because `catalogue._drop_unstorable`
    clears a value that is not text, and that sentence used to name the wrong
    function.** It said `routers/books._bounded_match` bounds them, which is
    true of what it bounds and is not the first thing to touch them:
    `metadata._google_record` builds a `Record` first, and its `__post_init__`
    measured every text field with `len()`. A security critic measured 15 of 25
    combinations raising `TypeError` there, before any Pydantic model ran.
    """
    info = _mapping(volume.get("volumeInfo"))

    categories = _strings(info.get("categories"))
    identifiers = info.get("industryIdentifiers")
    isbn13 = next(
        (
            entry["identifier"]
            for entry in (identifiers if isinstance(identifiers, list) else [])
            # `_mapping` on each entry, so a list of strings is skipped rather
            # than raising, and `"identifier" in` rather than `entry["identifier"]`
            # after the fact: an entry naming the type and carrying no value
            # would be a `KeyError` inside a generator nothing catches.
            if _mapping(entry).get("type") == "ISBN_13" and "identifier" in _mapping(entry)
        ),
        None,
    )

    published = str(info.get("publishedDate") or "")
    # `isascii()` beside `isdigit()`: this is somebody else's JSON, and a year
    # of four superscript digits would satisfy `isdigit()` and raise out of
    # `int()`. See `isbn.is_valid_isbn13` for the measurement.
    head = published[:4]
    year = int(head) if head.isascii() and head.isdigit() else None

    series_name, series_index = _series_from(info)

    return {
        "google_books_id": volume.get("id"),
        "series_name": series_name,
        "series_index": series_index,
        "title": info.get("title"),
        "subtitle": info.get("subtitle"),
        "author": ", ".join(_strings(info.get("authors"))) or None,
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
        #
        # **Both halves guarded, and this was the field that was not.** It read
        # `(info.get("imageLinks") or {}).get("thumbnail")`, which is the `or {}`
        # idiom `_mapping` exists to replace, and it handed whatever was inside
        # straight to `covers.storable`. Measured against this function: an
        # `imageLinks` of `"http://x/y"` raised `AttributeError`, a `thumbnail`
        # of `5` raised `TypeError`, of `{"a": 1}` raised `KeyError`. None of
        # the three is `GoogleBooksError`, `httpx.HTTPError` or `ValueError`, so
        # none is caught anywhere on this path: it is a 500, and on the backfill
        # it loses the whole batch before the commit rather than one book. The
        # field beside it, `_google_isbn13`, records paying for exactly this
        # once already.
        "cover_url": _cover_url(info),
        "isbn13": isbn13,
    }


def _cover_url(info: dict[str, Any]) -> str | None:
    """The volume's thumbnail, where it is a string. See `_mapping`.

    `covers.storable` takes `str | None` and calls string methods on it, so the
    type has to be refused before the value is judged. What `storable` then
    decides is a different question and its own: a thumbnail may name any https
    host, and `covers.is_fetchable` and the CSP's `img-src` are what bound that.
    """
    thumbnail = _mapping(info.get("imageLinks")).get("thumbnail")
    return covers.storable(thumbnail if isinstance(thumbnail, str) else None)


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
    raw_title = info.get("title")
    name, index = _series_from_title(raw_title if isinstance(raw_title, str) else "")

    # `seriesInfo` carries the position and, despite the field name,
    # `bookDisplayNumber` is a number rather than a series name. The name is
    # not in that payload at all, so the title stays the only source for it and
    # this only ever improves the index.
    #
    # Read through `_mapping` and `isinstance` at every step, for that helper's
    # reason: a `volumeSeries` of `"ab"` is truthy and subscriptable, so the
    # `[0]` below would yield `"a"` and `.get` would raise.
    series = _mapping(info.get("seriesInfo"))
    volumes = series.get("volumeSeries")
    if isinstance(volumes, list) and volumes:
        display = str(series.get("bookDisplayNumber") or "").strip()
        order = _mapping(volumes[0]).get("orderNumber")
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


async def _get(url: str, params: dict[str, str], api_key: str) -> fetch.Fetched:
    """One bounded GET at Google, with the key attached where there is one.

    **The URL is an argument because there are two endpoints, and it is the only
    thing that varies.** `/volumes` takes a query; `/volumes/{id}` takes the
    identifier in the path. Both carry the same key, the same bounds and the
    same refusals, so the status handling below is shared rather than written
    twice with one arm added.
    """
    query = dict(params)
    if api_key:
        query["key"] = api_key
    return await fetch.get_once(url, params=query)


def _refuse(status_code: int) -> None:
    """Raise for a status this application cannot use. Returns on 200.

    **404 is not handled here**, because the two endpoints disagree about it:
    `/volumes` answers 200 with no `items` for a query nothing matches, and
    `/volumes/{id}` answers 404 for a volume id Google does not know. "Google
    has no such book" is a different answer from "Google would not talk to us",
    so the caller that can get one decides what it means rather than this
    function guessing for both.
    """
    if status_code in (401, 403):
        # Almost always a bad or restricted key, and the admin can fix it, so
        # say so rather than reporting a generic failure.
        raise GoogleBooksError(
            "Google Books rejected the API key. Check it in Settings, and that "
            "the Books API is enabled for it."
        )
    if status_code == 429:
        raise GoogleBooksError("Google Books is rate limiting this key. Try again later.")
    if status_code != 200:
        logger.error("Google Books returned %s", status_code)
        raise GoogleBooksError("Google Books is not responding. Try again later.")


def _object(response: fetch.Fetched) -> dict[str, Any]:
    """The body as a JSON object, refusing anything else.

    **`isinstance` rather than `dict(...)`, which is what this replaced.** That
    spelling reads as a coercion and is a constructor: `dict([1, 2])` raises
    `TypeError`, which no caller of this module catches, while `dict(["ab"])`
    **succeeds** and yields `{"a": "b"}`, so a body of two character strings
    became an object this code then read fields off. A JSON top level that is
    not an object is a payload we do not understand, and saying so is the whole
    of the handling it needs.

    **A body this cannot parse is a `ValueError` whatever is wrong with it**,
    including nested deeply enough to overflow the stack, which `json.loads`
    raises as a `RecursionError`. `fetch.Fetched.json` converts that at the one
    place a response body is parsed, and `test_house_rules.py` keeps it the one
    place. It was worth closing here as three call sites and it stayed open at
    four others, which is the argument for the door rather than the arm.
    """
    payload = response.json()
    if not isinstance(payload, dict):
        raise GoogleBooksError("Google Books answered with something unreadable.")
    return payload


async def _request(params: dict[str, str], api_key: str) -> dict[str, Any]:
    """The `/volumes` search endpoint: a query in, a page of `items` out."""
    response = await _get(_VOLUMES_URL, params, api_key)
    _refuse(response.status_code)
    return _object(response)


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


#: The shape a Google volume id has to be before it may reach a URL.
#:
#: **Twelve characters of the URL safe alphabet**, measured by the trio that
#: wrote `frontend/src/lib/takeout.ts` over all 24 sidecars of a real Play Books
#: export, every one twelve characters and every one distinct. Calibre's own
#: `google` regression fixture, `s7NIrgEACAAJ`, is one.
#:
#: **The refusal and the encoding are the same fact, which is why this is a
#: bound rather than a call to `quote`.** This value goes into a **path
#: segment** at Google, and `schemas/identifier.BookIdentifierOut` already
#: states the rule it would otherwise break: an identifier is opaque text of up
#: to 60 characters with no shape anything checks, so putting one in a path
#: makes every reader of that URL responsible for encoding it. Every character
#: this admits is unreserved in RFC 3986, so a value that passes needs no
#: encoding at all and a value that would have needed some never becomes a
#: request.
#:
#: **`\A` and `\Z`, not `^` and `$`.** Python's `$` also matches immediately
#: before a trailing newline, so `^[A-Za-z0-9_-]{12}$` admits
#: `"abcdefghijkl\n"`, which is a newline in a URL path. `takeout.ts` spells the
#: same rule with `^...$` and is right to: JavaScript's `$` without the `m` flag
#: is end of input. `tests/test_google_books.py::TestTheVolumeIdBound` pins the
#: newline directly rather than leaving it to the anchors being read correctly.
#:
#: **Three spellings of one rule, and the drift is guarded rather than
#: regretted.** `takeout.ts`'s `VOLUME_ID` keeps a sidecar line that is not an
#: id out of the browser's parse, `calibre.ts`'s `PRODUCED_VALUE.google_books`
#: keeps a plugin's invented value out of a stored row, and this one keeps a
#: stored row out of a URL. Only this one is a security bound, because only this
#: one is on the server: `backup.restore` writes `book_identifiers` through Core
#: and runs no Pydantic model, so a restored row reaches here having passed
#: neither of the others. `tests/test_google_books.py::TestTheThreeSpellings`
#: reads the two frontend files and fails if either has moved.
VOLUME_ID: Final = re.compile(r"\A[A-Za-z0-9_-]{12}\Z")


def is_a_volume_id(value: str) -> bool:
    """Whether this is a value that may be asked about.

    Public because the bound is asked in three places and must not be re-spelled
    at any of them: `lookup_by_volume_id` refuses on it, and `routers/books.py`
    counts candidates by it on both the single book path and the backfill, where
    a book whose identifier cannot be resolved must not be reported as one that
    could.
    """
    return VOLUME_ID.match(value) is not None


async def lookup_by_volume_id(volume_id: str, api_key: str) -> dict[str, Any] | None:
    """The volume Google filed under this id, or None if there is no such volume.

    **The point of the whole feature, in one request.** A Play Books Takeout
    carries a volume id for every book and no ISBN anywhere, so the alternative
    is matching by title and author, which this application already knows is its
    weakest instrument. One identifier in, one record out, no ranking and no
    guess.

    **`/volumes/{id}` and not `q=id:...`.** Both exist; the query form is a
    search that happens to have one hit, so it costs the same quota, answers
    with a page to be unwrapped, and can answer with somebody else's book. The
    direct endpoint either has the volume or answers 404.

    **None for a value that is not a volume id, without a request.** That is the
    same shape as `lookup_by_isbn`, which returns None for an ISBN that fails
    its check digit rather than asking Google about it, and it is what keeps a
    malformed stored row from becoming an outbound URL. See `VOLUME_ID`.

    **None for a 404**, which is Google saying it has no such volume: a fact
    about the book, so the caller carries on rather than reporting an outage.
    Every other refusal raises `GoogleBooksError`, exactly as the search path
    does, so a rejected key and a rate limit stay distinguishable from a miss.
    """
    if not is_a_volume_id(volume_id):
        logger.info("Not a Google volume id, so not asked: %r", volume_id[:64])
        return None

    response = await _get(f"{_VOLUMES_URL}/{volume_id}", {}, api_key)
    if response.status_code == 404:
        return None
    _refuse(response.status_code)

    payload = _object(response)
    # **A 200 is not on its own evidence that this is a volume.** The volume
    # endpoint and the search endpoint share a host and a path prefix, and their
    # bodies are different shapes: a search answers `{"items": [...]}`, or
    # `{"items": []}` for a query nothing matches. Without this arm a body of
    # that shape parses happily into a record with every field absent, which
    # `_volume_to_fields` reports as a volume Google answered for and which
    # enriches nothing.
    #
    # **Both members, and the `id` is the half a design critic found missing.**
    # A volume resource always carries both; a search page carries neither. With
    # `volumeInfo` alone, a 200 carrying one and no `id` was reported as an
    # answer, wrote nothing, and **left the book a candidate**, so every press
    # spent a metered request on it again. Measured through the route: two
    # consecutive presses, `enriched: 0` and `remaining: 0` both times, one
    # request each.
    #
    # **`is_a_volume_id` and not `isinstance(..., str)`, and the difference is
    # the same defect one layer up.** `models.GOOGLE_BOOKS_ID_MAX` is 50, so an
    # `id` of 60 characters is a string, passes a type check, and is then
    # dropped by `BookMatch` before `merge_into` sees it: nothing is written,
    # the Book keeps no `google_books_id`, and it is a candidate again on the
    # next press. Measured through the route at the same shape: two presses,
    # `enriched: 1` both times, `google_books_id` still None. A volume
    # resource's id **is** a volume id, which is a bound this module already
    # owns, and requiring it is what makes
    # `routers/books.backfill_from_identifiers` able to count an answer as
    # enrichment by construction rather than by a clause about Google.
    identifier = payload.get("id")
    if not isinstance(payload.get("volumeInfo"), dict) or not (
        isinstance(identifier, str) and is_a_volume_id(identifier)
    ):
        logger.info("Google Books answered for %s with no volume", volume_id)
        return None
    return _volume_to_fields(payload)


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


def merge_into(book: object, match: BookMatch, *, overwrite: bool) -> list[str]:
    """Copy a validated match onto a book, returning the names actually changed.

    By default only empty fields are filled. Enrichment is meant to add what is
    missing, not to overrule what someone typed by hand: a member who corrected
    a title should not have Google quietly undo it. `overwrite` is offered for
    the case where the stored record is known to be wrong.

    **A `BookMatch` rather than a dictionary, and that is the bound rather than
    a tidier signature.** Every value written here came from outside the
    library, on both of the two routes that reach this function, and until
    2026-09-03 one of them validated its dictionary and the other did not:
    `POST /{id}/enrich/apply` refused an oversized value with a 422 and
    `POST /{id}/enrich` stored whatever a catalogue answered with a 200, one
    route apart on the same book. `series_index` was the sharp one, and it is a
    stored denial of service rather than an untidy row: `routers/books.list_series`
    computes `set(range(1, max(held) + 1))` over the column under
    `Shelf.seen_by`, so a stored `1e9` is roughly 70 GB and ten minutes on
    every request by every member until somebody finds the row.

    The type is what keeps that closed. A caller cannot hand this an unbounded
    dictionary without failing mypy, and at runtime a dictionary raises on the
    first `getattr` rather than writing twelve unchecked columns, so a third
    call site inherits the bound instead of having to remember it. Twelve, not
    eleven: the loop names eleven and `cover_url` is assigned below it.
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
        incoming = getattr(match, name)
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
    incoming_cover = match.cover_url
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
