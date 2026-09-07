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

* **The first candidate that is present wins, in the order the candidates are
  written**, whatever order the file puts its columns in. A LibraryThing export
  carries `Length` (`5.12 inches`, a shelf dimension) before `Page Count`, so a
  590 page book imported with 4 pages while the file decided.
* **A matched header is removed from the pool**, so two fields cannot claim one
  column. No name is shared between two fields today, so it decides nothing yet;
  it is what makes a name added to two lists resolve by field order rather than
  by both reading the same column.

What is ours rather than theirs: the delimiter and encoding are sniffed instead
of being declared per service, because a file arrives here as an upload with no
label saying where it came from. LibraryThing exports are tab separated and
UTF-8 with a few bytes that are not, and asking somebody to know that is asking
them to debug a CSV.

## Where the candidate names end, and what stands there instead

Two export shapes cannot be a candidate name, so this module holds more than
one reader. `import_readers.py` is the contract and says why; the readers
themselves are at the foot of this file, behind `READERS`.

* **A compound cell.** LibraryThing packs a publisher, a year and a format into
  `Publication`, and Openreads packs a start and a finish per session into
  `readings`. No candidate name reaches inside a cell.
* **A file that is not a table.** Google Play Books exports nested JSON. Not
  read here yet, and the seam is shaped so that it is a reader rather than a
  second door.

**A row exclusion is a third shape no candidate name can carry, and it is a
reason this module holds fewer readers rather than more.** It names no field, so
it is not in `COLUMN_GUESSES`; it needs no reader either, because nothing has to
be right about which service wrote the file. `_ROW_EXCLUSIONS` is where it
lives, and every reader honours it.

**The generic reader is still the answer for every service that fits**, and
most do. A member here is names in `COLUMN_GUESSES` and no code at all.
"""

import codecs
import csv
import io
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

from enums import BookFormat, ReadStatus
from import_readers import Extraction, ImportReader
from isbn import parse as parse_isbn
from models import MAX_PAGE_NUMBER_IN_A_BOOK

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
#: created 4032 tags, which are library wide, unpaginated and permanent. The
#: cap stops creating rather than failing the import: the books are still worth
#: having.
MAX_NEW_TAGS_PER_IMPORT: Final = 200

#: Candidate headers per field, in priority order.
#:
#: Written **normalised**: lower case, with underscores and hyphens as spaces,
#: because that is the form headers are reduced to before matching. A guess
#: spelled `publish_date` can never match anything.
#:
#: Drawn from the services people arrive from: Goodreads, LibraryThing,
#: StoryGraph, Libib, Openreads, Open Library, BookWyrm and this app's own.
#: Adding a service is usually adding a name here rather than writing any code.
#:
#: **The Libib names are read off that vendor's import template rather than off
#: an export**, so they stand on the assumption that its export writes the
#: template's column names, and nothing has confirmed that. Which artefact each
#: name was quoted from, and when, is beside the fixture in
#: `tests/test_csv_import.py`.
COLUMN_GUESSES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("title", ("title", "book title", "name")),
    (
        "author",
        (
            "author",
            "authors",
            "author text",
            "primary author",
            "creator",
            "creators",
            "by",
        ),
    ),
    # `ean` belongs to the 13: an EAN printed on a book is its ISBN-13. Which
    # of the two fields a row ends up using is `parse`'s decision, not this
    # order's, and it is stated at that site.
    ("isbn13", ("isbn13", "isbn 13", "isbns", "ean isbn13", "ean")),
    ("isbn", ("isbn", "isbn10", "isbn 10", "upc isbn10", "isbn/uid", "uid")),
    # Specific names before generic ones: `shelf` and `collections` are what a
    # file calls a shelf when it has no status column at all, so a file
    # carrying both gives this field the one that really is the status.
    #
    # `my status` is this app's own export column, and without it Endpaper's
    # export did not survive Endpaper's importer.
    #
    # `bookshelves` is deliberately absent rather than last. It is Goodreads'
    # free-form shelf list, it is already the first `tags` candidate, and
    # reading it as the status imports a whole library as unread.
    (
        "status",
        (
            "exclusive shelf",
            "my status",
            "read status",
            "status",
            "shelf",
            "collections",
            "bookshelf",
        ),
    ),
    # `my ratings` is Open Library's spelling, and it stands with `my rating`
    # rather than at the end for the reason `my rating` is first: the member's
    # own number beats a column that may hold everyone's. Deliberately not a
    # loose `ratings`, which would claim a column named exactly that, and on a
    # site publishing an average that column is the crowd's count.
    ("rating", ("my rating", "my ratings", "star rating", "your rating", "rating")),
    # The key stays `date_read`: it names the field on `ImportRow`, and only
    # the candidate strings are normalised.
    #
    # `completed` is a header name here and a READ value in `STATUS_GUESSES`.
    # Those are separate namespaces: this table is matched against the header
    # row and that one against a cell, so a file with a `Completed` column and
    # a `Completed` status value fills both fields and neither reads the other.
    (
        "date_read",
        (
            "date read",
            "last date read",
            "date finished",
            "finish date",
            "finished",
            "read date",
            "completed date",
            "completed",
        ),
    ),
    ("publisher", ("publisher", "publishers")),
    (
        "year",
        (
            "year published",
            "original publication year",
            "first publish year",
            "publication year",
            "publish date",
            "date published",
            "year",
        ),
    ),
    # `length of` stands **before** `length`, not after it. The bare `length`
    # is a page count in some files and the shelf dimension this module's
    # docstring names in a LibraryThing export, while Libib's `length_of` is
    # only ever a page count. Appending it hands a file carrying both the
    # dimension, and no Libib file carries both, so nothing else notices.
    ("pages", ("number of pages", "page count", "pages", "length of", "length")),
    ("format", ("format", "binding", "edition format", "book format", "media")),
    ("tags", ("bookshelves", "tags", "genres", "labels")),
    (
        "notes",
        ("my review", "review content", "review", "private notes", "notes", "comments"),
    ),
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
        "planned",
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
    # A container name is a format vocabulary here, the way `epub` already is
    # for EBOOK: a Calibre or Komga export writes `CBZ` in the column where
    # Goodreads writes `Paperback`. `cbr` earns a spelling for the reason its
    # refusal is stated in `frontend/src/lib/cbz.ts`: this app will not parse
    # one, and a member who owns one still owns a comic.
    #
    # **`trade paperback` is deliberately not here** and stays with PAPERBACK,
    # where it already is. It is the binding of a collected comic and it is
    # also the binding of an ordinary novel, and this table sees only the word.
    BookFormat.COMIC: (
        "comic",
        "comics",
        "comic book",
        "graphic novel",
        "manga",
        "cbz",
        "cbr",
    ),
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
    #: Which reader read the file. Reported for the reason the mapping is: a
    #: file read as the wrong service's export is invisible until afterwards,
    #: and afterwards the fix is deleting a few hundred books.
    reader: ImportReader = ImportReader.GENERIC
    #: Rows the file itself says are not wanted, read off whichever of
    #: `_ROW_EXCLUSIONS` the file carries.
    #:
    #: **A separate count from `skipped` rather than folded into it**, which is
    #: the opposite of what `importing.py` does with the row whose ISBN belongs
    #: to an invisible Book, and the difference is what the number discloses.
    #: That one is an oracle for "does a Book with this ISBN exist in this
    #: house" and has to be hidden inside a wider count. This one is read
    #: entirely off the member's own upload and says nothing about the instance,
    #: so it can be reported plainly, and it has to be: a member who exported
    #: 400 titles and imported 380 is owed the other twenty.
    excluded: int = 0
    #: The header `excluded` was read from, stripped and truncated to what a
    #: header may be quoted at, or None where the file has no such column. Where a file names
    #: more than one such column every one of them is honoured and the first is
    #: what this names.
    #:
    #: **Reported because the column is honoured wherever it appears.** Nothing
    #: detects whose export a file is any more, so the count is the only thing a
    #: member would see, and a count with no column beside it is a number they
    #: cannot check against their own file. It also separates "no such column"
    #: from "such a column, and none of its rows said yes", which the count
    #: alone cannot.
    exclusion_column: str | None = None


class ImportError_(Exception):
    """The file cannot be read as a book list."""


def _stray_bytes_as_cp1252(error: UnicodeError) -> tuple[str, int]:
    """The error handler `decode` reads a non UTF-8 byte with.

    `replace` on the inner decode because cp1252 leaves five byte values
    undefined (0x81, 0x8d, 0x8f, 0x90, 0x9d), and a handler that raised on
    those would put the whole file back where it started.

    Deleting this and passing `errors="replace"` instead would cost every
    accented character of a file that really is cp1252, since each of them is
    one byte that is not UTF-8.

    **It resumes at `error.end`, and one past it eats the next byte.** A 0x81
    between `Ace` and `Books` comes back as `Ace`, the replacement character,
    `ooks`: the `B` is consumed here and never decoded, silently and in the
    middle of a cell. The run count `decode` budgets against cannot see it
    either, because that count comes from a `replace` decode, which never
    calls this.
    """
    if not isinstance(error, UnicodeDecodeError):
        raise error
    return error.object[error.start : error.end].decode("cp1252", errors="replace"), error.end


#: Registered once, at import, because the name is resolved per decode call.
_STRAY_BYTES: Final = "endpaper.csv_import.stray_bytes"

codecs.register_error(_STRAY_BYTES, _stray_bytes_as_cp1252)

#: How many runs of bytes may fail UTF-8 before the file is read whole.
#:
#: Past this the premise is false: this is not a UTF-8 file with a few stray
#: bytes, it is a file in a single byte encoding, and the whole file question
#: is the right one to ask about it.
#:
#: **It is also what bounds the work, which is the half that bites.** The
#: handler above is a Python call per run, measured at 1.9 microseconds, so the
#: bound costs 95 ms and the 5 MB `MAX_UPLOAD_BYTES` allows would otherwise cost
#: **10.2 seconds** of it, on a route any member can reach three times a minute.
#: The count is taken before any of it is paid, and taking it is C level
#: throughout: a file that is valid UTF-8 pays one pass and no Python call at
#: all, and a file with a few stray bytes pays four more passes plus one call
#: per run.
#:
#: The three figures were measured on one machine, which this file may not
#: name, so what the bound rests on is the ratio between them rather than any
#: one of them.
_STRAY_RUN_BUDGET: Final = 50_000

#: U+FFFD as UTF-8, which is what a file may already carry a lot of.
#:
#: Subtracting its count below is exact rather than approximate, and that rests
#: on three properties of this sequence rather than on the one that is easiest
#: to state. `0xef` is never a continuation byte, so no run around it can
#: swallow it; the sequence is valid, neither overlong nor a surrogate, so it
#: always decodes to the character; and no proper prefix of it equals a proper
#: suffix, so `bytes.count`, which does not count overlapping matches, counts
#: every occurrence.
_REPLACEMENT_AS_UTF8: Final = "�".encode()


def decode(content: bytes) -> str:
    """Text from bytes, deciding per byte where the file is UTF-8 and per file
    where it is not.

    The byte order mark a spreadsheet writes is stripped here rather than by
    the `utf-8-sig` codec, because both readings below have to see the same
    bytes. Left on, it glues itself to the first header, so `Title` becomes
    `﻿Title` and matches nothing.

    **A stray byte costs its own character and nothing else.** Trying whole
    encodings in turn let one byte re-encode a library: measured on a real
    LibraryThing export, one MARC-8 byte at offset 927, in a column nothing
    maps, sent the file to cp1252 and mangled every accent in it. Such a byte
    is read as cp1252 on its own instead, which is a single byte encoding, so a
    file that really is cp1252 comes back right on this path too: every
    accented byte in it fails UTF-8 alone and is decoded alone.

    **A file that mostly fails is read whole**, past `_STRAY_RUN_BUDGET`, which
    gives up the valid UTF-8 inside such a file and buys what the budget states.
    The per byte path gives up the other side of the same coin: a run of cp1252
    bytes that happens to form a valid UTF-8 sequence is read as that sequence.
    Both are pinned in `TestOneStrayByteDoesNotDecideTheEncodingOfTheWholeFile`.
    """
    body = content.removeprefix(codecs.BOM_UTF8)
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # Counted at C speed before anything is paid per byte. `replace` emits one
    # character per invalid run and one for every U+FFFD the file already
    # carried, and only the first is work the handler does. The second is
    # subtracted rather than tolerated: this importer writes that character
    # itself, so a file that has been through it once would otherwise be voted
    # into another encoding by its own past, which is this module's own defect
    # arriving through a second door. Measured against a counting handler over
    # every byte string of length three or less, 16,843,008 of them: no over or
    # undercount. An undercount is the direction that would matter, since it is
    # what would let the work past the budget.
    runs = body.decode("utf-8", errors="replace").count("�") - body.count(
        _REPLACEMENT_AS_UTF8
    )
    if runs > _STRAY_RUN_BUDGET:
        return body.decode("cp1252", errors="replace")
    return body.decode("utf-8", errors=_STRAY_BYTES)


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

    **The candidates are what is iterated, and the file's column order decides
    nothing.** Iterating the headers instead reads a LibraryThing export's
    `Length` column (`5.12 inches`) as the page count, because it stands before
    `Page Count` in the file: a 590 page book imports with 4 pages.

    The pool a match is taken out of is a list per name, so two headers spelled
    the same way are two entries and the first is taken.
    """
    # Normalised once here rather than once per candidate: Openreads writes
    # `publication_year` and Goodreads writes `Year Published`, and a name
    # separated by an underscore is the same name.
    available: dict[str, list[str]] = {}
    for header in headers:
        available.setdefault(_normalise_term(header), []).append(header)

    mapping: dict[str, str | None] = {}
    for field_name, guesses in COLUMN_GUESSES:
        mapping[field_name] = None
        for guess in guesses:
            holders = available.get(guess)
            if holders:
                # Removed from the pool, so a name added to two fields' lists
                # goes to the earlier field rather than to both.
                mapping[field_name] = holders.pop(0)
                break

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


def _int(
    value: str, *, minimum: int = 1, maximum: int = MAX_PAGE_NUMBER_IN_A_BOOK
) -> int | None:
    """A bounded integer, or nothing.

    Bounded because a page count of 0 and a year of 12345 are both what a
    spreadsheet produces when a column has slipped, and both are worse stored
    than absent.

    The default ceiling is the page ceiling, because `pages` is the one caller
    that takes it, and it is imported rather than retyped: this column ends up
    in `books.page_count`, which `BookCreate` and `BookDetailsUpdate` bound by
    the same constant. An importer that admitted a page count the API refuses
    would be a second answer to the same question.

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


#: The shape every pattern below can accept, and nothing narrower.
#:
#: **A gate in front of `strptime`, and it is a bound on work rather than a
#: parse.** A caller that loops over the parts of one cell pays this per part,
#: and `strptime` is expensive on a miss: measured, 16.56 microseconds against
#: **0.21** for this pattern, so an unpacker walking the 1.25 million parts a
#: 5 MB upload admits fell from 23.2 seconds of CPU to 0.22. A route any member
#: can reach three times a minute.
#:
#: **It is a superset, checked rather than reasoned about.** `%Y` is four digits
#: exactly and `%m` and `%d` are one or two, and `strptime` tolerates whitespace
#: around a component (`8/ 7/9455` parses), which is why the `\s*` are there and
#: why the first version of this pattern was wrong. Derived by comparing the
#: gated function against the ungated one over 716,655 strings: every random
#: string up to fourteen characters over the digits, the three separators,
#: space, tab and one letter, plus every pattern's own output for 3,333 years.
#: No disagreement.
_A_DATE_SHAPE: Final = re.compile(r"\s*\d{1,4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,4}\s*")


def parse_date(raw: str) -> date | None:
    """A date in whichever shape the exporting service or spreadsheet used.

    Anything unrecognised is treated as absent. A wrong date is worse than no
    date, because it lands in "books finished in 2021" and nobody notices.
    """
    text = raw.strip()
    if not text or _A_DATE_SHAPE.fullmatch(text) is None:
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


# ── The readers ───────────────────────────────────────────────────────────────
#
# `import_readers.py` is the contract and says why there is more than one of
# these. What is here is the implementations, the registry they are reached
# through, and the claims a file is recognised by.
#
# Everything above this line is shared by every reader, which is why the three
# below are one factory: decoding, sniffing, the candidate table, the small
# matchers and the row exclusion. A reader is still a whole reader rather than a
# hook on one path, and the next one, for a file that is not a table at all,
# will share almost none of it.


#: How much of one header a refusal may quote.
#:
#: `headers[:12]` bounds how many and nothing bounded how long. Measured: a file
#: with no delimiter at all is one enormous header, and a 100,000 character line
#: produced a 100,108 character message, which `routers/imports.py` hands back
#: as the `detail` of a 400. So a file that is not a table was echoed to the
#: caller in full.
_MAX_HEADER_QUOTED: Final = 40

#: How many headers a refusal may quote.
_MAX_HEADERS_QUOTED: Final = 12


@dataclass
class _Table:
    """A file read as rows of cells, before any field means anything.

    The half every table reader shares. What each of them does with it is the
    half that differs, which is why this is not a `ParsedFile`.
    """

    headers: list[str]
    delimiter: str
    rows: list[dict[str, str]]


def _read_table(text: str) -> _Table:
    """The file as a table, or a refusal naming what is wrong with it."""
    delimiter = sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    # The `csv` module raises on structural problems the caller can do
    # something about: a field over its 128k limit, a NUL in the stream, a bare
    # carriage return in an unquoted field. Those describe the file, not a bug
    # here, so they become the same refusal every other unreadable file gets
    # rather than a 500.
    #
    # **`fieldnames` is inside this, and that is the half that was wrong.**
    # Reading it is what parses the header row, so a file whose FIRST line is
    # the malformed one raised past this handler and reached a member as a 500:
    # measured, a CR terminated file and a 200,000 character quoted header both
    # did. A file is not more readable for being broken on line one.
    try:
        headers = list(reader.fieldnames or [])
        if not headers:
            raise ImportError_(
                "That file has no header row, so its columns cannot be read."
            )
        rows = list(_limited(reader))
    except csv.Error as error:
        raise ImportError_(
            "That file could not be read as a table. It may be damaged, or not "
            "a CSV at all."
        ) from error

    return _Table(headers=headers, delimiter=delimiter, rows=rows)


def _headers_of(text: str) -> list[str]:
    """The header row alone, for a detector that must not pay for the file.

    **The first line is sliced off before anything reads it**, because
    `sniff_delimiter` splits whatever it is handed into every line, and every
    claim in `CLAIMS` asks this question again. Over the whole text that is one
    list of every line in a 5 MB upload per claim.

    **A file with no newline in it at all is the one that pays**, and it is this
    module's own pathological input rather than a hypothetical: it is the file
    `_MAX_HEADER_QUOTED` exists for. `find` answers -1 there, so a slice ending
    at `find + 1` ends at zero and an `or` on the empty string hands the whole
    file back, which is the bug this spelling replaces. The `or` is on the index
    now, where -1 + 1 is falsy and a newline at k gives k + 1, which is not.

    Measured over 5 MB with no newline, three claims, `time.process_time` and
    `tracemalloc`: **108 ms and 25.5 MB** of peak allocation, against 20 ms and
    1.3 MB with the window. **Both halves are one instrument's run**, which is
    what makes the pair a comparison; three instruments read the unwindowed side
    and the other two landed at 132 ms and at 437.8 ms, so the figure written
    here is the lowest of the three and a floor rather than a number to
    reproduce to the digit. With one newline in the file it is 0.06 ms either
    way, which is the shape every real export has.

    The cost is a header row with a newline inside a quoted field, which is
    truncated here and read correctly by `_read_table` afterwards. That sends
    such a file to the generic reader, which is the fallback direction.

    Anything unreadable is no headers, because the detector's answer for a file
    it cannot read is the reader that already refuses it.
    """
    line = text[: text.find("\n") + 1 or _CLAIM_WINDOW]
    try:
        return next(csv.reader(io.StringIO(line), delimiter=sniff_delimiter(line)), [])
    except csv.Error:
        return []


def _by_normalised_name(headers: list[str]) -> dict[str, str]:
    """Normalised header name to the header itself, first of a repeat winning.

    First wins, matching `build_mapping`'s pool, which hands a repeated name to
    the earlier column.
    """
    found: dict[str, str] = {}
    for header in headers:
        found.setdefault(_normalise_term(header), header)
    return found


def _guessed_mapping(headers: list[str], overrides: Mapping[str, str]) -> dict[str, str | None]:
    """The guessed mapping, corrected, and refused if it found no title.

    An override naming a header that is not in the file is ignored rather than
    raising: it describes a file that is not this one.
    """
    mapping = build_mapping(headers)
    for field_name, header in overrides.items():
        if field_name in mapping and header in headers:
            mapping[field_name] = header

    if mapping["title"] is None:
        quoted = ", ".join(
            header[:_MAX_HEADER_QUOTED] for header in headers[:_MAX_HEADERS_QUOTED]
        )
        raise ImportError_(
            "No title column was found. Export a CSV from your old app, or pick "
            f"the right column by hand. This file has: {quoted}"
        )
    return mapping


def _cells(raw: dict[str, str], mapping: Mapping[str, str | None]) -> Callable[[str], str]:
    """A reader of one row's mapped fields."""

    def cell(name: str) -> str:
        header = mapping.get(name)
        return _clean(raw.get(header)) if header else ""

    return cell


def _row_from(raw: dict[str, str], mapping: dict[str, str | None]) -> ImportRow | None:
    """One row in this app's terms, or None where it has no title."""
    cell = _cells(raw, mapping)

    title = cell("title")
    if not title:
        return None

    # ISBN-13 first: it is the canonical form and the one books here carry.
    # `parse_isbn` converts a 10 and rejects anything that is not an ISBN,
    # so a UID column holding something else contributes nothing.
    isbn = parse_isbn(cell("isbn13")) or parse_isbn(cell("isbn"))

    return ImportRow(
        title=title[:500],
        author=flip_catalogue_name(cell("author"))[:500] or None,
        isbn=isbn,
        status=match_status(cell("status")),
        rating=_int(cell("rating"), minimum=1, maximum=5),
        date_read=parse_date(cell("date_read")),
        publisher=cell("publisher")[:255] or None,
        year=_year(cell("year")),
        pages=_int(cell("pages")),
        format=match_format(cell("format")),
        tags=_split_tags(cell("tags")),
        notes=cell("notes") or None,
    )


def _infer_status_from_the_date(row: ImportRow) -> None:
    """A file may name a collection where a status should be ("Your library"),
    or carry no status column at all. A read date says the book was read
    whatever the other column claims, which is how BookWyrm recovers a shelf
    from a LibraryThing export.

    **Applied after a compound cell has been unpacked, and that is the reason it
    is a function.** Openreads' finish date arrives out of `readings` rather
    than out of a mapped column, so a rule applied while the row was being built
    would have run before the date existed. One home, both callers.
    """
    if row.status is None and row.date_read is not None:
        row.status = ReadStatus.READ


#: Header names that mark a row the file itself says is not wanted.
#:
#: **Written as the header the export actually carries, and reduced here**,
#: which is the opposite of `COLUMN_GUESSES`, where the form is a rule a test
#: enforces over a table too large to reduce at import. Two things come of it:
#: a name added later is quoted from the artefact rather than transcribed into
#: another form, and the reduction is load bearing today rather than the day a
#: second name arrives, since `HasBeenDeleted` matches no normalised header
#: without it. Transcribed by hand and got wrong it would be the failure this
#: whole rule exists to remove: deleted rows back, with the count reading zero.
#:
#: **Honoured wherever the column appears.** Nothing detects which service wrote
#: a file, so there is no detection width to get wrong: the column is there or
#: it is not. Owner's decision, 2026-09-07, and `docs/decisions.md` carries
#: what it settled.
#:
#: **It cannot be a candidate header name.** A name in `COLUMN_GUESSES` says
#: which column fills a field of `ImportRow`; this one says whether the row
#: exists at all, and no field means "do not import me".
#:
#: Amazon's Kindle document listing is the one attested spelling. A second
#: service is a name here and no code, which is the same shape adding a service
#: to `COLUMN_GUESSES` has.
#:
#: **This is the half that changes what a member sees**, so every doubt keeps
#: the row: an unrecognised value keeps it, a file with no such column loses
#: nothing, and the count and the column are both on the preview before
#: anything is written.
_ROW_EXCLUSIONS: Final = tuple(
    _normalise_term(header) for header in ("HasBeenDeleted",)
)

#: Cell values a row exclusion column is written with when it means yes.
#:
#: **Anything else keeps the row**, which is the direction that does not destroy
#: data. The attested column's vocabulary is `true` and `false`, so a word
#: outside it describes a file this module has not seen, and inventing an
#: exclusion from an unrecognised word would drop books nobody deleted. The
#: opposite default loses a member's library to a spelling.
_MEANS_DELETED: Final = frozenset({"true", "1", "yes", "y"})


def _means_deleted(value: str | None) -> bool:
    """Whether an exclusion cell says the member deleted this at the source."""
    return _clean(value).lower() in _MEANS_DELETED


def _exclusion_columns(headers: list[str]) -> list[str]:
    """Every header that marks deleted rows, in the file's own order.

    **Every one of them and not the first**, because they disagree in only one
    direction that matters: a column saying the member deleted this row is what
    the file says, and a second column silent about it takes nothing back. The
    first is what the count is reported against.

    **A name repeated exactly is a refusal rather than a guess**, and this is
    the one place in this module where refusing beats reading. `csv.DictReader`
    keys a row on the header string, so two columns with the same name collapse
    to one value, the last one's, and the first column's answer is gone before
    any row is seen. Measured: `Title,HasBeenDeleted,HasBeenDeleted` with
    `true,false` on the row imported the row the file marked deleted, with the
    count reading zero and the column named beside it, which is the silent miss
    this whole rule exists to remove. Refusing destroys nothing: the member
    removes a duplicated column and imports again.
    """
    wanted = set(_ROW_EXCLUSIONS)
    found = [header for header in headers if _normalise_term(header) in wanted]

    # **Tallied once, not counted per header.** `list.count` scans the whole
    # header row for each header it is asked about, and nothing bounds how many
    # columns a file has: `MAX_ROWS` bounds rows, `csv.field_size_limit` bounds
    # one field, and the column count is bounded only by `MAX_UPLOAD_BYTES`.
    # Measured on one machine, so the ratio is the claim and not the seconds,
    # and read by two instruments rather than one: 80,000 such columns, 1.68 MB
    # and inside that limit, cost **155.42 s** of CPU counted per header against
    # 0.112 s as this stands; 30,000 columns read 23.35 s against 0.069 through
    # one instrument and 15.5 s against 0.040 through the other. Duplicates are
    # not needed to pay it, only to be refused afterwards, and the route it is
    # reachable on writes nothing and allows three a minute.
    seen = Counter(headers)
    repeated = {header for header in found if seen[header] > 1}
    if repeated:
        # Bounded in both dimensions, like the refusal above and for the same
        # reason: a header is as long as the file makes it, and there are as
        # many spellings of one name as there are lengths of padding, so a 5 MB
        # upload of padded duplicates quoted every one of them. Stripped before
        # slicing, because the left of a padded header is padding and a message
        # naming forty spaces tells a member to remove a column it has not
        # named.
        quoted = ", ".join(
            sorted({header.strip()[:_MAX_HEADER_QUOTED] for header in repeated})[
                :_MAX_HEADERS_QUOTED
            ]
        )
        raise ImportError_(
            f"That file has more than one column called {quoted}, so which "
            "rows it marks as deleted cannot be read. Remove the repeated "
            "columns and import it again."
        )
    return found


#: What a compound cell reader is handed: the cell, and the row so far.
UnpackCell = Callable[[str, ImportRow], None]


def _guessing_reader(column: str | None = None, unpack: UnpackCell | None = None) -> ReaderFn:
    """The generic reader, optionally reaching inside one named cell as well.

    **The row exclusion is here rather than in a service's own reader**, so a
    file marking its deleted rows is honoured whoever wrote it and whichever
    reader was asked for. It used to be one reader's, reached only when a claim
    recognised that service by two of its headers, so renaming either header
    brought every deleted title back with the count reading zero.

    **A factory rather than three near identical readers**, because a compound
    cell is a family and not an example: two services need one already, and the
    two differ only in which column and what it holds. A third is an unpacker
    and one line here.

    `column` is a **normalised** header name, matched the way every other name
    in this module is, so `Publication` and `publication` are one name.

    The unpacker fills gaps and never overwrites: a service that ships both a
    compound cell and a plain column for one of its parts must keep the plain
    one, which is the same rule `importing._fill_gaps` applies for the same
    reason.
    """

    def read(text: str, extraction: Extraction) -> ParsedFile:
        table = _read_table(text)
        mapping = _guessed_mapping(table.headers, extraction.overrides)
        compound = _by_normalised_name(table.headers).get(column or "")
        exclusions = _exclusion_columns(table.headers)

        parsed = ParsedFile(
            mapping=mapping,
            headers=table.headers,
            delimiter=table.delimiter,
            reader=extraction.reader,
            # Stripped, then bounded like every other header this module hands
            # back. One header is as long as `csv.field_size_limit` allows, and
            # a 100,000 character 400 is a refusal this module has paid for
            # once; slicing a padded header from the left reports its padding,
            # which is a count beside a blank on the one file the bound is for.
            exclusion_column=(
                exclusions[0].strip()[:_MAX_HEADER_QUOTED] if exclusions else None
            ),
        )
        for raw in table.rows:
            # Before the title is looked at, so the two counts stay apart: what
            # the file asked for is `excluded`, what a row lacks is `skipped`,
            # and a deleted row with no title is the file's answer rather than
            # this module's.
            if any(_means_deleted(raw.get(header)) for header in exclusions):
                parsed.excluded += 1
                continue
            row = _row_from(raw, mapping)
            if row is None:
                parsed.skipped += 1
                continue
            if unpack is not None and compound is not None:
                unpack(_clean(raw.get(compound)), row)
            _infer_status_from_the_date(row)
            parsed.rows.append(row)
        return parsed

    return read


#: The two compound cells, named once each.
#:
#: Each is both the column its reader reaches inside and half of what recognises
#: the file, and written twice they drift into a file that is detected and then
#: unpacks nothing, silently.
#: `tests/test_csv_import.py::test_a_compound_readers_column_is_one_of_the_names_that_found_the_file`
#: is what holds the two together for a reader added later.
_PUBLICATION: Final = "publication"
_READINGS: Final = "readings"

#: A year inside brackets, which is what tells a LibraryThing `Publication`
#: apart from a publisher's name.
_BRACKETED_YEAR: Final = re.compile(r"\((\d{4})\)")

#: How many comma separated parts after the year may be tried as a format.
_FORMAT_PARTS_SCANNED: Final = 8


def _unpack_publication(value: str, row: ImportRow) -> None:
    """`Gallimard (1979), Poche`: a publisher, a year and a format in one cell.

    **The bracketed year is the anchor, and nothing is read without it.** A
    publisher's name carries commas of its own (`Farrar, Straus and Giroux`), so
    splitting on punctuation reads part of a name as a year or as a binding. The
    year in brackets is the one token in this cell whose shape says what it is,
    so the publisher is what stands before it and the format is what stands
    after it.

    **With no bracketed year the whole cell is the publisher**, which is the
    conservative half: a cell that is only a name is a name. Read the other way
    round, `Gallimard, Poche` would invent a year out of nothing, and this
    module already says a wrong value is worse than an absent one.
    """
    text = value.strip()
    if not text:
        return

    found = list(_BRACKETED_YEAR.finditer(text))
    if not found:
        if row.publisher is None:
            row.publisher = text[:255] or None
        return

    # The last, not the first: a publisher named after a year would otherwise
    # take the anchor, and the year of publication is written last here.
    year_at = found[-1]
    if row.year is None:
        row.year = _int(year_at.group(1), minimum=1, maximum=2200)

    if row.publisher is None:
        row.publisher = text[: year_at.start()].strip().rstrip(",").strip()[:255] or None

    if row.format is None:
        # Bounded, because the parts of this cell are bounded by the upload and
        # not by anything about a publication. `match_format` costs 1.46
        # microseconds on a miss, so an unbounded scan over a 5 MB file of
        # commas was 6.1 seconds of CPU on a route any member can reach three
        # times a minute. No real cell carries a format past the eighth comma.
        for part in text[year_at.end() :].split(",")[:_FORMAT_PARTS_SCANNED]:
            row.format = match_format(part)
            if row.format is not None:
                break


def _unpack_readings(value: str, row: ImportRow) -> None:
    """`start|finish|` per reading session, and the finish is what is wanted.

    **The finishes are the odd numbered parts, which holds whatever separates
    two sessions.** One session is written `start|finish|`, so two of them are
    `start|finish|Xstart|finish|` for whatever X is; split on the pipe, and the
    separator glues itself to the front of the next session's start. Index 1, 3,
    5 are finishes either way. The session separator was not attested in the
    artefact this was written against, and reading structure that was not
    attested is how a start becomes a finish.

    **The latest finish, not the first.** A book read twice has two, and the
    later one is when this member last finished it.

    **A start is never read as a finish**, which is the property the odd index
    buys: an open session contributes a start and no finish, and a book somebody
    is part way through does not get a finish date out of the day they began.
    """
    if row.date_read is not None:
        return
    finishes = [parse_date(part) for part in value.split("|")[1::2]]
    dates = [finish for finish in finishes if finish is not None]
    if dates:
        row.date_read = max(dates)


#: What every reader is, and the signature is the enforcement.
#:
#: Text and an `Extraction`, never bytes, a filename, an upload or a session.
#: A reader that named any of those fails the type check on `READERS` below,
#: which is the contract in `import_readers.py` held by mypy rather than by a
#: reviewer.
ReaderFn = Callable[[str, "Extraction"], "ParsedFile"]


def _complete(readers: dict[ImportReader, ReaderFn]) -> dict[ImportReader, ReaderFn]:
    """The registry, refused unless it covers the closed set.

    **This is the whole of what adding a reader costs, so it is the thing that
    must not be forgettable.** A member added to `ImportReader` and not wired up
    here would be selectable by name over the API and raise `KeyError` on
    dispatch, which reaches a member as a 500.

    Derived by asking the enum what its members are rather than by listing them,
    so the check grows with the set instead of going stale beside it. It runs at
    import, so the failure is the application not starting.
    """
    missing = set(ImportReader) - set(readers)
    if missing:
        raise RuntimeError(
            "import readers with no implementation: "
            + ", ".join(sorted(reader.value for reader in missing))
        )
    return readers


#: Every reader, by the member of the closed set that names it.
READERS: Final[dict[ImportReader, ReaderFn]] = _complete(
    {
        ImportReader.GENERIC: _guessing_reader(),
        ImportReader.LIBRARYTHING: _guessing_reader(_PUBLICATION, _unpack_publication),
        ImportReader.OPENREADS: _guessing_reader(_READINGS, _unpack_readings),
    }
)


#: How much of a file a claim is handed.
#:
#: **Borrowed from `csv.field_size_limit` rather than chosen, and it is not the
#: same bound.** That one is per field and this is per file, so a header row of
#: many small fields can be longer than this and is read rather than refused:
#: measured, a header of 40,003 fields and 160,031 characters parses, and a
#: LibraryThing export shaped that way is a claim miss. What the borrowing buys is a
#: number of the right order that moves with the module's own limits instead of
#: a new one nobody can size. Read at import, so a runtime change to that limit
#: moves `_read_table` and not this; both directions are safe, since raising it
#: makes claims miss and lowering it makes `_read_table` refuse first.
#:
#: **A header row past the window is a miss, which is the fallback direction**,
#: and truncation is monotone on detection: it can take names away from what a
#: claim sees and never add one, so it cannot make a claim fire that would not
#: have.
#:
#: **The bound is on the type rather than on today's claims, and that is the
#: point.** A set of header names could only ask one question about one line, so
#: the work was bounded by what a claim was. A predicate over the text is free to
#: walk a 5 MB upload, once per claim, on a route reachable three times a minute,
#: and a sentence saying it does not is the bottom rung. Every claim today reads
#: the first line and the next one cannot: a pretty printed `Library.json` opens
#: with a single `{`.
_CLAIM_WINDOW: Final = csv.field_size_limit()

#: What a claim is: a predicate over the front of the decoded file.
#:
#: **Over the text and not over a header row**, which is the one thing this seam
#: promises about the second service. Google Play Books' library export is
#: nested JSON, so no set of header names could ever claim it, and a claim about
#: something other than a header row has to be a row in `CLAIMS` rather than a
#: change to what a claim is.
#:
#: It is handed `_CLAIM_WINDOW` characters, never the file.
Claim = Callable[[str], bool]


@dataclass(frozen=True)
class HeaderNames:
    """A claim that a file's header row carries all of these names.

    The only kind of claim there is today, and a class rather than a closure so
    the names stay readable: the guard below takes each one away in turn, and a
    compound reader's column is checked against them.
    """

    names: frozenset[str]

    def __call__(self, text: str) -> bool:
        return self.names <= {_normalise_term(header) for header in _headers_of(text)}


#: How a file is recognised as one service's export, in the order tried.
#:
#: The generic reader is not in here: it has no claim because it is what a file
#: gets when nothing claims it.
#:
#: **What a miss costs and what a wrong claim costs are both small now, and one
#: of them was not.** A miss leaves a file with the reader that reads it today.
#: A wrong claim hands it to a reader that reads everything the generic one
#: reads and additionally unpacks one named cell, so it costs that cell misread.
#: Each claim names two headers, which is what stops a service that happens to
#: share one of them paying for it.
#:
#: **Nothing here decides whether a member's deleted titles come back.** That
#: was the largest cost on this table and it is not on it any more: the row
#: exclusion is `_ROW_EXCLUSIONS`, honoured by the generic mapping wherever the
#: column appears, so a claim that misses costs a cell rather than a library.
#:
#: Ordered, and the first claim that fires wins.
CLAIMS: Final[tuple[tuple[ImportReader, Claim], ...]] = (
    (ImportReader.LIBRARYTHING, HeaderNames(frozenset({_PUBLICATION, "primary author"}))),
    (ImportReader.OPENREADS, HeaderNames(frozenset({_READINGS, "book format"}))),
)


def detect(text: str) -> ImportReader:
    """Which reader a file is for, from the file itself.

    Consulted only when the member did not name one.

    **The window is cut once here and every claim is handed that**, so what a
    detection costs is a property of this function rather than a promise each
    claim makes about itself. `_CLAIM_WINDOW` says why the promise is not where
    it belongs.
    """
    head = text[:_CLAIM_WINDOW]
    for reader, claims in CLAIMS:
        if claims(head):
            return reader
    return ImportReader.GENERIC


def parse(
    content: bytes,
    overrides: dict[str, str] | None = None,
    reader: ImportReader | None = None,
) -> ParsedFile:
    """Read an export into rows this app can act on.

    **The one door, and the only place an `Extraction` is built from an
    upload.** Decoding happens here and once, because every reader wants the
    same answer about the encoding and this application has measured that answer
    already.

    `reader` names one explicitly and is the escape hatch for a file the
    detector reads as the wrong service's. Left out, `detect` chooses and
    `ParsedFile.reader` reports what it chose.

    `overrides` replaces a guessed column with one the reader picked, which is
    the escape hatch for a file whose headers are in a language or a shape the
    guesses do not cover. An override naming a header that is not in the file is
    ignored rather than raising: it describes a file that is not this one.

    **A row the file's own exclusion column marks as deleted is dropped whoever
    reads it**, so naming a reader is not a way to bring those rows back. The
    file itself is: it is the member's own upload, and the column is theirs to
    remove.
    """
    text = decode(content)
    if not text.strip():
        raise ImportError_("That file is empty.")

    chosen = reader if reader is not None else detect(text)
    return READERS[chosen](text, Extraction(reader=chosen, overrides=overrides or {}))
