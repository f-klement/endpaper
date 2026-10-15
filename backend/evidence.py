"""Applying outside evidence to a Book that already exists, under a named policy.

A Catalogue record, a matched candidate a Member picked, or a row of an imported
file is evidence: somebody else's statement about a Book this Library already
holds (ADR 0004). Five writers used to apply one, each with its own rules, and two
definitions of empty between them. This module is the one place that decides:

- **what empty is**: `is_empty`, None or a blank string, for every policy. A
  stored blank is a gap to fill, an incoming blank asserts nothing, and a column
  a refresh clears is written null, never blank;
- **which columns evidence may reach**: cells of `book_columns`, never
  `WORK_IDENTITY` outside a refresh, never `SELECTED_ONLY` from a record no
  Member selected (but `google_books_id` from a lookup by that same id,
  `apply_own_volume`), never what a row claims about the Library;
- **bounding**: a record is held to `BookMatch` field by field before it writes;
- **cover precedence**: a cover a Member uploaded outranks any remote one;
- **whether Classifications cross**: only through a door a Member's choice
  opened, which is ADR 0006 held by which door a caller can reach. `confirm`
  is the door for a record a Member selected, and `confirm_file_headings` for
  a MARC file a Member chose to import.

What stays with the caller: fetching the cover (`routers/books._store_cover`,
which the create paths share and which runs on a thread from a coroutine) and the
commit. Ownership on an OPDS sync stays with `importing`, because its gap is
`UNKNOWN` rather than an empty value.
"""

import logging
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy.orm import Session

import book_columns
import covers
from catalogue import Heading, Record
from classifications import add_headings, bounded_headings
from logvalues import clipped
from models import Book, blank_as_none
from schemas import BookMatch

logger = logging.getLogger("endpaper.evidence")


class Policy(Enum):
    """How a piece of evidence meets what the Book already holds."""

    #: Write only where the Book holds nothing. The default everywhere: a value a
    #: Member typed outranks a stranger's record, because the person holding the
    #: copy knows more about it.
    FILL_GAPS = "fill_gaps"
    #: Write every column the evidence asserts, for a stored record known to be
    #: wrong. A Member asks for it with `overwrite`.
    OVERWRITE = "overwrite"
    #: `PUT /{book_id}/refresh`: rewrite `REFRESHED` and the cover from the record
    #: the Book's own ISBN found. The only policy that writes `title`.
    REFRESH = "refresh"


#: The columns a refresh rewrites besides the cover, which with it are nine.
#:
#: It writes `title`, which the other policies leave alone as work identity,
#: because the record was found by this Book's own ISBN. Why it skips
#: `categories`, the series fields and `google_books_id` is in
#: `docs/decisions.md`.
REFRESHED: Final[tuple[str, ...]] = (
    "title", "subtitle", "author", "publisher", "year", "description",
    "language", "page_count",
)

#: The work's details a record nobody selected does not write: `categories`, the
#: series fields and `google_books_id`. Such a record writes what a refresh
#: writes and no more, owner's ruling of 2026-10-15, with one exception:
#: `apply_own_volume` writes `google_books_id` when it equals the id looked up.
#: The id is an identity claim, which volume this Book is, and a wrong one
#: silently drops the Book out of the identifier backfill's candidates. Derived
#: from `REFRESHED` so the two unselected paths cannot drift apart.
SELECTED_ONLY: Final[tuple[str, ...]] = tuple(
    name for name in book_columns.WORK_DETAIL if name not in REFRESHED
)

#: The columns a refresh clears when the source no longer asserts them: five of
#: `REFRESHED`, and the cover unless the Member uploaded it. The other three keep
#: what the Book had: `title` because the column is not nullable, `language` and
#: `page_count` because a source lacking one should not delete it.
_CLEARED_BY_REFRESH: Final = frozenset(
    {"subtitle", "author", "publisher", "year", "description", "cover_url"}
)

#: The columns `fill_gaps` may write: the work's details, and `format`, because
#: the CSV importer reads a Member's own shelf export, which describes their
#: copy. The copy's other details are out: no importer names one, and a file
#: naming the shelf or the collection of a matched Book would be filing it.
#: Identity and standing are out, as they are for a merge. The cover is out
#: because it has its own precedence and no importer fetches one.
_FILLABLE: Final = frozenset(book_columns.WORK_DETAIL) | {"format"}


def is_empty(value: object) -> bool:
    """Whether a value is absent: None or a blank string, for every policy.

    A stored blank is a gap rather than a value somebody chose, and an incoming
    blank asserts nothing. Before this, enrichment held that and the importers
    held only None, so one Book took a publisher from Google and refused the same
    one from a file. Blank is `models.blank_as_none`'s, the rule every write of
    a `Book` stores by, so a record and a request cannot disagree on it.
    """
    return blank_as_none(value) is None


def apply_record(book: Book, record: Record, policy: Policy) -> list[str]:
    """Apply one catalogue record to `book`, returning the columns that changed.

    No Classification crosses, under any policy: nobody selected this record.
    `as_match()` carries none and this door reads none.

    `FILL_GAPS` and `OVERWRITE` write `book_columns.WORK_DETAIL` less
    `SELECTED_ONLY`, and the cover, off the record bounded by `BookMatch` one
    field at a time. `REFRESH` writes
    `REFRESHED` and the cover straight off the record: `Record.__post_init__`
    already cleared every scalar the columns cannot hold, so a value too wide
    arrives as None and is read like a source that carries no such field.
    """
    if policy is Policy.REFRESH:
        changed = _write(
            book, {name: getattr(record, name) for name in REFRESHED}, policy
        )
        if _write_cover(book, record.cover_url, policy):
            changed.append("cover_url")
        return changed
    return _apply_match(book, _unselected(record, SELECTED_ONLY), policy)


def apply_own_volume(
    book: Book, record: Record, volume_id: str, policy: Policy
) -> list[str]:
    """Apply the record a lookup by the Book's own `volume_id` returned.

    The door for the identifier backfill and for `POST /{id}/enrich` when the
    volume id is what found the record. What `apply_record` writes, and
    `google_books_id` as well, **only where the record's id is `volume_id`**:
    then the id is the one the Member's own import carried rather than a
    guess. Compared here rather than trusted to the caller, because
    `google_books.lookup_by_volume_id` checks that the payload's id is a
    volume id, not that it is the one asked for, and a caller's flag is one
    edit from covering a title search. Writing it is what takes the Book out
    of the backfill's candidate set.

    `REFRESH` is refused, for `confirm`'s reason: it reads a `Record` whole
    rather than through a match.
    """
    if policy is Policy.REFRESH:
        raise ValueError("A refresh is found by ISBN, not by a volume id")
    withheld = tuple(
        name
        for name in SELECTED_ONLY
        if name != "google_books_id" or record.google_books_id != volume_id
    )
    return _apply_match(book, _unselected(record, withheld), policy)


def confirm(book: Book, match: BookMatch, db: Session, policy: Policy) -> list[str]:
    """Apply a record a Member selected, Classifications included.

    Of the writers applying a catalogue's answer, the one door through which a
    Catalogue record's Classifications reach an existing Book (ADR 0006):
    selecting the row confirms the whole record. The body arrives validated by
    `BookMatch`, so its headings go in as they are.

    `REFRESH` is refused: a refresh selects no record, and its policy reads a
    `Record` rather than a match.
    """
    if policy is Policy.REFRESH:
        raise ValueError("A refresh selects no record, so it confirms nothing")
    changed = _apply_match(book, match, policy)
    if add_headings(book, match.classifications, db):
        changed.append("classifications")
    return changed


def confirm_file_headings(
    book: Book, headings: Sequence[Heading], db: Session
) -> list[str]:
    """Add an imported MARC file's headings to `book`, returning the numbers changed.

    The importer's door for Classifications, matched Book or created one.
    Choosing the file is the confirmation, as selecting a picker row is for
    `confirm`, so nothing waits on a Member afterwards.

    `bounded_headings` drops an entry the column cannot hold and `add_headings`
    counts what the Book already carries, so neither a long caption nor a
    repeated import can push a Book past the ceiling.
    """
    return add_headings(book, bounded_headings(headings), db)


def fill_gaps(book: Book, values: Mapping[str, object]) -> list[str]:
    """Fill the columns `book` holds nothing in from an imported file's values.

    The importers' door. Which columns each importer names stays at that
    importer (ADR 0008): MARC and OPDS by a tuple, CSV by its own literal. This
    refuses a name outside the work's details and `format`, so a mistake there
    is a `ValueError` in the suite rather than a write.
    """
    unfillable = set(values) - _FILLABLE
    if unfillable:
        raise ValueError(f"No imported file may fill {sorted(unfillable)}")
    return _write(book, values, Policy.FILL_GAPS)


def _apply_match(book: Book, match: BookMatch, policy: Policy) -> list[str]:
    """Copy a validated match onto `book` under `FILL_GAPS` or `OVERWRITE`.

    **A `BookMatch` rather than a dictionary, and that is the bound rather than a
    tidier signature.** Every value written here came from outside the library,
    and until 2026-09-03 one route validated its dictionary and the other did not:
    `series_index` was the sharp one, since `routers/books.list_series` computes
    `set(range(1, max(held) + 1))` over the column for every member. A dictionary
    raises on the first `getattr` rather than writing anything.

    **The loop's set is asked for, not written out**: `book_columns.WORK_DETAIL`,
    the descriptive facts a merge also absorbs and the MARC importer narrows.
    """
    values: dict[str, object] = {}
    for name in book_columns.WORK_DETAIL:
        values[name] = getattr(match, name)
    changed = _write(book, values, policy)
    if _write_cover(book, match.cover_url, policy):
        changed.append("cover_url")
    return changed


def _unselected(record: Record, withheld: tuple[str, ...]) -> BookMatch:
    """A record nobody selected, bounded, asserting nothing about `withheld`.

    Cleared on the match rather than skipped in `_apply_match`'s loop, so that
    loop stays the one set `confirm` writes. A cleared field asserts nothing
    under `FILL_GAPS` and `OVERWRITE` alike, which `_write` already holds.
    """
    match = _bounded_match(record.as_match())
    return match.model_copy(update=dict.fromkeys(withheld))


def _write(book: Book, values: Mapping[str, object], policy: Policy) -> list[str]:
    """Write each value the policy allows, returning the names that changed."""
    changed: list[str] = []
    for name, incoming in values.items():
        current = getattr(book, name)
        if is_empty(incoming):
            # An absent value asserts nothing, except where a refresh reads the
            # source's silence as the source no longer asserting it.
            if not (policy is Policy.REFRESH and name in _CLEARED_BY_REFRESH):
                continue
            # Compared as null, which is what `Book` stores for a blank:
            # compared as the blank, a column already null would be reported
            # changed on every refresh.
            incoming = None
        elif policy is Policy.FILL_GAPS and not is_empty(current):
            continue
        if current == incoming:
            continue
        setattr(book, name, incoming)
        changed.append(name)
    return changed


def _write_cover(book: Book, incoming: str | None, policy: Policy) -> bool:
    """Apply the cover precedence, returning whether `cover_url` changed.

    A cover the Member uploaded outranks any remote one under every policy, and
    `covers.is_local` is the only reader of the prefix that decides it: a literal
    here would not follow the constant, and this writer would then overrule an
    upload with the stored row looking correct.

    Below that it is any other column under `_write`, one a refresh clears: a
    refresh replaces the cover with the record's, clearing it where the record
    has none.
    """
    if covers.is_local(book.cover_url):
        return False
    return bool(_write(book, {"cover_url": incoming}, policy))


def _bounded_match(fields: dict[str, Any]) -> BookMatch:
    """One catalogue record as a bounded match, dropping what the columns cannot hold.

    **The field rather than the record, which is the opposite of
    `routers/books._match_rows` and is deliberate.** A search page can afford to
    lose one row of many; an enrichment answer is about the book in hand, so
    losing it whole would answer "nothing found" for a book the catalogue does
    hold. A cleared field is a gap the member can see and fill; a dropped record
    is a question answered wrongly.
    """
    kept = dict(fields)
    for _ in range(len(kept) + 1):
        try:
            return BookMatch(**kept)
        except ValidationError as exc:
            refused = {
                str(error["loc"][0]) for error in exc.errors() if error["loc"]
            } & kept.keys()
            if not refused:
                break
            logger.info(
                "Dropped %s from a record from %s: the column cannot hold it",
                ", ".join(sorted(refused)),
                clipped(fields.get("source")),
            )
            for name in refused:
                del kept[name]

    logger.info(
        "Discarded a record from %s the schema refused whole",
        clipped(fields.get("source")),
    )
    return BookMatch.model_construct()
