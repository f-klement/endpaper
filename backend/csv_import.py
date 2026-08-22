"""Reading a library export from any of the services people leave.

The Goodreads importer that came before this only read Goodreads, and that is
the wrong shape for the problem: somebody arriving here is arriving **from**
something, and it is as likely to be LibraryThing, StoryGraph, Libib or
another copy of this app as it is to be Goodreads.

The approach is taken from BookWyrm's `bookwyrm/importers/importer.py`, which
solves the same problem and solves it well: rather than a subclass per service
with a fixed column list, each field carries a list of **candidate header
names**, matched case-insensitively against whatever the file actually has.
Two details of theirs are load bearing and are copied deliberately:

* **A matched header is removed from the pool.** Goodreads has both `ISBN` and
  `ISBN13`; without removal the first field to want an ISBN claims both.
* **First match wins, in the order the candidates are written.** Goodreads has
  both `Exclusive Shelf` (the status) and `Bookshelves` (free-form tags), and
  the status list names the former first for exactly that reason.

What is ours rather than theirs: the delimiter and encoding are sniffed instead
of being declared per service, because a file arrives here as an upload with no
label saying where it came from. LibraryThing exports are tab separated and
Latin-1, and asking somebody to know that is asking them to debug a CSV.
"""

import csv
import io
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

from enums import BookFormat, ReadStatus
from isbn import parse as parse_isbn

logger = logging.getLogger("endpaper.csv_import")

MAX_ROWS: Final = 20_000

#: How many rows the preview shows. Enough to see whether the mapping is right,
#: few enough that a 5000-book file does not come back through the browser.
PREVIEW_ROWS: Final = 5

#: Tags one row may carry. A Goodreads "Bookshelves" cell is a comma-separated
#: shelf list and is occasionally enormous.
MAX_TAGS_PER_ROW: Final = 20

#: Tags one book may end up with. Past this the picker on that book is unusable
#: and the extra names are somebody else's filing system, not this shelf's.
MAX_TAGS_PER_BOOK: Final = 50

#: Distinct tags one import may invent. Measured: a 12 KB file of 200 rows
#: created 4032 tags, which are household-wide, unpaginated and permanent. The
#: cap stops creating rather than failing the import: the books are still worth
#: having.
MAX_NEW_TAGS_PER_IMPORT: Final = 200

#: Candidate headers per field, in priority order.
#:
#: Written **normalised**: lower case, with underscores and hyphens as spaces,
#: because that is the form headers are reduced to before matching. A guess
#: spelled `publish_date` can never match anything.
#:
#: Drawn from the real exports: Goodreads, LibraryThing, StoryGraph, Libib,
#: Openreads and this app's own. Adding a service is usually adding a name
#: here rather than writing any code.
COLUMN_GUESSES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("title", ("title", "book title", "name")),
    (
        "author",
        ("author", "authors", "author text", "primary author", "creator", "by"),
    ),
    # Before the looser `isbn`, so a file carrying both gives the 13 to the
    # field that wants a 13.
    ("isbn13", ("isbn13", "isbn 13", "isbns", "ean")),
    ("isbn", ("isbn", "isbn10", "isbn 10", "isbn/uid", "uid")),
    # `exclusive shelf` first: Goodreads also has `bookshelves`, which is the
    # tag list, and claiming that as the status imports everything as unread.
    (
        "status",
        (
            "exclusive shelf",
            "read status",
            "status",
            "shelf",
            "collections",
            "bookshelf",
        ),
    ),
    ("rating", ("my rating", "star rating", "your rating", "rating")),
    # The key stays `date_read`: it names the field on `ImportRow`, and only
    # the candidate strings are normalised.
    (
        "date_read",
        (
            "date read",
            "last date read",
            "date finished",
            "finish date",
            "finished",
            "read date",
        ),
    ),
    ("publisher", ("publisher", "publishers")),
    (
        "year",
        (
            "year published",
            "original publication year",
            "publication year",
            "publish date",
            "date published",
            "year",
        ),
    ),
    ("pages", ("number of pages", "page count", "pages", "length")),
    ("format", ("format", "binding", "edition format", "media")),
    # After `status`, so Goodreads' `bookshelves` is left for this one.
    ("tags", ("bookshelves", "tags", "genres", "labels")),
    ("notes", ("my review", "review", "private notes", "notes", "comments")),
)

#: Their status vocabularies, mapped onto ours. Lower case, exact match after
#: normalising separators, because "to-read", "to read" and "To Read" are one
#: value written three ways.
STATUS_GUESSES: Final[dict[ReadStatus, tuple[str, ...]]] = {
    ReadStatus.READ: (
        "read",
        "already read",
        "finished",
        "completed",
        "done",
        "gelesen",
    ),
    ReadStatus.READING: (
        "currently reading",
        "reading",
        "in progress",
        "started",
        "am lesen",
    ),
    ReadStatus.WANT_TO_READ: (
        "to read",
        "want to read",
        "for later",
        "wishlist",
        "tbr",
        "not begun",
        "plan to read",
        "moechte ich lesen",
    ),
    # Goodreads and StoryGraph both express this, as a custom shelf and as a
    # status respectively, and the shelf name people actually type is
    # "abandoned" at least as often as "did not finish". All the spellings map
    # onto one member, so the stored name is not a compatibility surface.
    ReadStatus.DID_NOT_FINISH: (
        "did not finish",
        "dnf",
        "abandoned",
        "gave up",
        "unfinished",
        "stopped reading",
        "abgebrochen",
        "nicht beendet",
    ),
}

#: Their edition vocabularies. Endpaper's `format` column is new, and an export
#: that carries one is the only chance to fill it without asking.
FORMAT_GUESSES: Final[dict[BookFormat, tuple[str, ...]]] = {
    BookFormat.HARDCOVER: ("hardcover", "hardback", "hardbound", "gebunden"),
    BookFormat.PAPERBACK: (
        "paperback",
        "softcover",
        "mass market paperback",
        "trade paperback",
        "taschenbuch",
    ),
    BookFormat.EBOOK: ("ebook", "e book", "kindle edition", "epub", "digital"),
    BookFormat.AUDIOBOOK: ("audiobook", "audio", "audible audio", "audio cd", "hoerbuch"),
}


@dataclass
class ImportRow:
    """One line of an export, in this app's own terms."""

    title: str
    author: str | None = None
    isbn: str | None = None
    status: ReadStatus | None = None
    rating: int | None = None
    date_read: date | None = None
    publisher: str | None = None
    year: int | None = None
    pages: int | None = None
    format: BookFormat | None = None
    tags: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass
class ParsedFile:
    """What a file turned out to hold, and how it was read."""

    rows: list[ImportRow] = field(default_factory=list)
    #: Which header filled each field, or None where nothing matched. Shown in
    #: the preview so a wrong guess is visible before anything is written.
    mapping: dict[str, str | None] = field(default_factory=dict)
    headers: list[str] = field(default_factory=list)
    delimiter: str = ","
    #: Rows with no title. Counted rather than dropped silently, so the summary
    #: adds up to the number of lines in the file.
    skipped: int = 0


class ImportError_(Exception):
    """The file cannot be read as a book list."""


def decode(content: bytes) -> str:
    """Text from bytes, trying the encodings these exports actually use.

    `utf-8-sig` first because a spreadsheet writes a byte order mark and a
    plain UTF-8 decode leaves it glued to the first header, so `Title` becomes
    `﻿Title` and matches nothing. Latin-1 last because it decodes any byte
    sequence at all, which makes it the one that cannot fail: LibraryThing
    exports in it, and a mangled character is better than a refused file.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="replace")


def sniff_delimiter(sample: str) -> str:
    """Comma or tab.

    Sniffed rather than declared per service. LibraryThing exports tab
    separated, and a tab-separated file read as CSV yields one enormous column
    whose name is the whole header line, which reports as "no title column"
    and sends somebody looking for a problem in their data.

    Counted on the header line only: a comma inside a quoted title would
    outvote the real delimiter if the whole file were counted.
    """
    header = sample.splitlines()[0] if sample.splitlines() else ""
    return "\t" if header.count("\t") > header.count(",") else ","


def _normalise_term(raw: str) -> str:
    """`To-Read`, `to_read` and `To Read` are one value written three ways.

    Applied to headers as well as to values, so `publication_year` and
    `Year Published` do not need two entries each in the tables above.
    """
    return re.sub(r"[\s_-]+", " ", raw.strip().lower())


def build_mapping(headers: list[str]) -> dict[str, str | None]:
    """Guess which header holds which field.

    A matched header is removed from the pool, so two fields cannot claim the
    same column. That is what keeps `ISBN` and `ISBN13` apart on a Goodreads
    export, and `Exclusive Shelf` apart from `Bookshelves`.
    """
    available = list(headers)
    mapping: dict[str, str | None] = {}

    for field_name, guesses in COLUMN_GUESSES:
        # Normalised the same way the values are: Openreads writes
        # `publication_year` and Goodreads writes `Year Published`, and a name
        # separated by an underscore is the same name.
        match = next(
            (header for header in available if _normalise_term(header) in guesses),
            None,
        )
        if match is not None:
            available.remove(match)
        mapping[field_name] = match

    return mapping


def match_status(raw: str) -> ReadStatus | None:
    term = _normalise_term(raw)
    if not term:
        return None
    for status, guesses in STATUS_GUESSES.items():
        if term in guesses:
            return status
    return None


def match_format(raw: str) -> BookFormat | None:
    term = _normalise_term(raw)
    if not term:
        return None
    for book_format, guesses in FORMAT_GUESSES.items():
        if term in guesses:
            return book_format
    return None


def flip_catalogue_name(raw: str) -> str:
    """`Mann, Thomas` becomes `Thomas Mann`.

    LibraryThing writes its primary author in catalogue order, and Goodreads
    offers both orders in separate columns. One comma means a person; none, or
    more than one, means a corporate name or a list of people, and reordering
    either of those mangles it. The same rule as `metadata._flip_catalogue_name`,
    which reads it off MARC records for the same reason.
    """
    name = raw.strip().rstrip(",")
    if name.count(",") != 1:
        return name
    surname, forenames = (part.strip() for part in name.split(","))
    return f"{forenames} {surname}" if surname and forenames else name


def unwrap_excel_formula(value: str) -> str:
    """Turn Goodreads' `="9780441013593"` into `9780441013593`.

    They wrap identifier columns this way so spreadsheets do not strip leading
    zeros or render long numbers in scientific notation. Left in place, the
    value matches no book in the catalogue, and it is the single most common
    reason an import silently matches nothing.
    """
    cleaned = value.strip()
    if cleaned.startswith('="') and cleaned.endswith('"'):
        cleaned = cleaned[2:-1]
    return cleaned.strip()


def _clean(value: str | None) -> str:
    """One cell, with the decorations these exports add.

    LibraryThing wraps values in square brackets, which is why BookWyrm's
    importer for it strips them too.
    """
    text = unwrap_excel_formula(value or "")
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.strip()


def _int(value: str, *, minimum: int = 1, maximum: int = 100_000) -> int | None:
    """A bounded integer, or nothing.

    Bounded because a page count of 0 and a year of 12345 are both what a
    spreadsheet produces when a column has slipped, and both are worse stored
    than absent.

    Anchored at the start, which matters more than it looks: taking the first
    run of digits anywhere read "1,234 pages" as **1** and a date sitting in a
    year column as **3**. A number that does not begin the cell is not this
    cell's number.

    A separator followed by one or two digits is a decimal point and the
    fraction is dropped: StoryGraph writes its ratings as "4.0". Anything else
    is a grouping separator and is stripped, so "1,234" is 1234. The two cases
    genuinely collide (German "4,0" against English "1,234"), and truncating
    towards the integer is right for both of the things this reads: a rating
    and a count.
    """
    match = re.match(r"\s*(\d[\d.,]*)", value)
    if match is None:
        return None

    raw = match.group(1).rstrip(".,")
    decimal = re.fullmatch(r"(\d+)[.,](\d{1,2})", raw)
    digits = decimal.group(1) if decimal else re.sub(r"[.,]", "", raw)
    if not digits:
        return None

    number = int(digits)
    return number if minimum <= number <= maximum else None


def parse_date(raw: str) -> date | None:
    """A date in whichever shape the exporting service or spreadsheet used.

    Anything unrecognised is treated as absent. A wrong date is worse than no
    date, because it lands in "books finished in 2021" and nobody notices.
    """
    text = raw.strip()
    if not text:
        return None
    # Day first before month first: an unambiguous US date still parses by
    # falling through, and the ambiguous middle (03/04/2021) is far more often
    # written day first by the people this app is for.
    #
    # A bare year is deliberately NOT accepted. "1998" in a Date Read column
    # would become 1998-01-01, and a date is enough to infer that the book was
    # read, so a year alone would fabricate both a finish date and a status.
    for pattern in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _year(raw: str) -> int | None:
    """A publication year, from a year or from a whole date.

    `publish_date` in a Libib export really does hold a date, and `_int` is
    anchored at the start, so "03/06/2014" would otherwise be read as the year
    **3**. A cell that parses as a date gives up its year; everything else is
    an ordinary bounded number.
    """
    as_date = parse_date(raw)
    if as_date is not None:
        return as_date.year
    return _int(raw, minimum=1, maximum=2200)


def _split_tags(raw: str) -> list[str]:
    """A tag column, whichever separator the service chose."""
    parts = re.split(r"[;,|]", raw)
    return [tag.strip() for tag in parts if tag.strip()][:MAX_TAGS_PER_ROW]


def _limited(reader: csv.DictReader[str]) -> Iterator[dict[str, str]]:
    """At most `MAX_ROWS`, so one upload cannot become an unbounded import."""
    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            logger.warning("Import truncated at %d rows", MAX_ROWS)
            return
        yield row


def parse(content: bytes, overrides: dict[str, str] | None = None) -> ParsedFile:
    """Read an export into rows this app can act on.

    `overrides` replaces a guessed column with one the reader picked, which is
    the escape hatch for a file whose headers are in a language or a shape the
    guesses do not cover. An override naming a header that is not in the file
    is ignored rather than raising: it describes a file that is not this one.
    """
    text = decode(content)
    if not text.strip():
        raise ImportError_("That file is empty.")

    delimiter = sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = list(reader.fieldnames or [])
    if not headers:
        raise ImportError_("That file has no header row, so its columns cannot be read.")

    mapping = build_mapping(headers)
    for field_name, header in (overrides or {}).items():
        if field_name in mapping and header in headers:
            mapping[field_name] = header

    if mapping["title"] is None:
        raise ImportError_(
            "No title column was found. Export a CSV from your old app, or pick "
            f"the right column by hand. This file has: {', '.join(headers[:12])}"
        )

    parsed = ParsedFile(mapping=mapping, headers=headers, delimiter=delimiter)

    # The `csv` module raises on structural problems the caller can do
    # something about: a field over its 128k limit, a NUL in the stream. Those
    # describe the file, not a bug here, so they become the same refusal every
    # other unreadable file gets rather than a 500.
    try:
        rows = list(_limited(reader))
    except csv.Error as error:
        raise ImportError_(
            "That file could not be read as a table. It may be damaged, or not "
            "a CSV at all."
        ) from error

    for row in rows:

        def cell(name: str, _row: dict[str, str] = row) -> str:
            """One mapped field of this row.

            `_row` is bound as a default argument rather than closed over: a
            closure here captures the loop variable, so every call would read
            whichever row the loop had reached last.
            """
            header = mapping.get(name)
            return _clean(_row.get(header)) if header else ""

        title = cell("title")
        if not title:
            parsed.skipped += 1
            continue

        # ISBN-13 first: it is the canonical form and the one books here carry.
        # `parse_isbn` converts a 10 and rejects anything that is not an ISBN,
        # so a UID column holding something else contributes nothing.
        isbn = parse_isbn(cell("isbn13")) or parse_isbn(cell("isbn"))

        rating = _int(cell("rating"), minimum=1, maximum=5)
        date_read = parse_date(cell("date_read"))

        # A file may name a collection where a status should be ("Your
        # library"), or carry no status column at all. A read date says the
        # book was read whatever the other column claims, which is how
        # BookWyrm recovers a shelf from a LibraryThing export.
        status = match_status(cell("status"))
        if status is None and date_read is not None:
            status = ReadStatus.READ

        parsed.rows.append(
            ImportRow(
                title=title[:500],
                author=flip_catalogue_name(cell("author"))[:500] or None,
                isbn=isbn,
                status=status,
                rating=rating,
                date_read=date_read,
                publisher=cell("publisher")[:255] or None,
                year=_year(cell("year")),
                pages=_int(cell("pages")),
                format=match_format(cell("format")),
                tags=_split_tags(cell("tags")),
                notes=cell("notes") or None,
            )
        )

    return parsed
