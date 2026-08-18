"""Reading a Goodreads library export.

Goodreads retired its public API in December 2020: no new developer keys are
issued and existing ones were deactivated, so there is no way to authenticate
against it or read someone's shelves programmatically. What still works is the
CSV export under **My Books -> Import/Export -> Export Library**, which is the
supported way to get your own data out.

So the sync is a file upload rather than a credential. That is not a
workaround; it is the only route that exists, and it has the advantage of not
asking anyone to hand over a password.

Two things about the format are worth knowing before changing this:

* **ISBNs are written as spreadsheet formulas**: `="9780441013593"`, and `=""`
  when absent. Parsing the column naively yields `="978...` and matches
  nothing. This is the single most common reason a Goodreads import silently
  imports nothing.
* **`Exclusive Shelf`** carries the status, not `Bookshelves`. The latter is
  the free-form tag list and usually contains several values at once.
"""

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

from enums import ReadStatus
from isbn import parse as parse_isbn

logger = logging.getLogger("endpaper.goodreads")

# Their shelf names, mapped onto our statuses. `to-read` is why ReadStatus has
# WANT_TO_READ: collapsing it into "unread" would lose the distinction between
# "on my shelf, not started" and "I mean to read this".
SHELF_TO_STATUS: Final[dict[str, ReadStatus]] = {
    "read": ReadStatus.READ,
    "currently-reading": ReadStatus.READING,
    "to-read": ReadStatus.WANT_TO_READ,
}

# Columns we rely on. Goodreads has changed the export before, so a missing one
# is reported rather than producing a silent no-op.
REQUIRED_COLUMNS: Final = ("Title", "Exclusive Shelf")

MAX_ROWS: Final = 20_000


@dataclass
class GoodreadsRow:
    title: str
    author: str | None
    isbn: str | None
    status: ReadStatus
    rating: int | None = None
    # From the export's "Date Read" column. Goodreads writes it as YYYY/MM/DD
    # and leaves it empty for anything not on the read shelf.
    date_read: date | None = None


@dataclass
class ParseResult:
    rows: list[GoodreadsRow] = field(default_factory=list)
    # Rows skipped because the shelf was not one we map (a custom shelf, or an
    # empty cell). Counted rather than dropped silently so the summary adds up.
    skipped: int = 0


def unwrap_excel_formula(value: str) -> str:
    """Turn Goodreads' `="9780441013593"` into `9780441013593`.

    They wrap identifier columns this way so spreadsheets do not strip leading
    zeros or render long numbers in scientific notation. Left in place, the
    value matches no book in the catalogue.
    """
    cleaned = value.strip()
    if cleaned.startswith('="') and cleaned.endswith('"'):
        cleaned = cleaned[2:-1]
    return cleaned.strip()


def _cell(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def parse_export(content: bytes) -> ParseResult:
    """Read an export into rows we can act on.

    Raises ValueError with a readable message for a file that is not a
    Goodreads export, because "0 books imported" is not a useful thing to tell
    someone who picked the wrong file.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Exports are UTF-8, but a file round-tripped through a spreadsheet may
        # not be. Latin-1 decodes any byte sequence, so this cannot fail twice.
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])

    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise ValueError(
            "This does not look like a Goodreads export: no "
            f"{' or '.join(missing)} column. Use My Books, then Import/Export, "
            "then Export Library."
        )

    result = ParseResult()

    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            logger.warning("Goodreads export truncated at %d rows", MAX_ROWS)
            break

        status = SHELF_TO_STATUS.get(_cell(row, "Exclusive Shelf").lower())
        if status is None:
            result.skipped += 1
            continue

        title = _cell(row, "Title")
        if not title:
            result.skipped += 1
            continue

        # ISBN13 first: it is the canonical form and the one our books carry.
        isbn = parse_isbn(unwrap_excel_formula(_cell(row, "ISBN13"))) or parse_isbn(
            unwrap_excel_formula(_cell(row, "ISBN"))
        )

        raw_rating = _cell(row, "My Rating")
        rating = int(raw_rating) if raw_rating.isdigit() and raw_rating != "0" else None

        result.rows.append(
            GoodreadsRow(
                title=title,
                author=_cell(row, "Author") or None,
                isbn=isbn,
                status=status,
                rating=rating,
                date_read=parse_date_read(_cell(row, "Date Read")),
            )
        )

    return result


def parse_date_read(raw: str) -> date | None:
    """Read the export's "Date Read" column.

    Goodreads writes `2021/03/14`, but exports edited in a spreadsheet come
    back in whatever that spreadsheet's locale produced, so two more shapes are
    accepted. Anything else is treated as absent: a wrong date is worse than no
    date, because it lands in "books finished in 2021" and nobody notices.
    """
    text = raw.strip()
    if not text:
        return None
    for pattern in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def search_url(title: str, isbn: str | None = None) -> str:
    """A Goodreads search link for a book.

    An outbound link is all that remains possible without an API, and it is
    what the lookup button uses. Searching by ISBN lands on the exact edition;
    by title it lands on a result list, which is still the useful destination.
    """
    from urllib.parse import quote_plus

    query = isbn or title
    return f"https://www.goodreads.com/search?q={quote_plus(query)}"
