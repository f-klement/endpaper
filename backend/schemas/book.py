from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

import isbn as isbn_utils
from enums import BulkAction, OwnershipStatus, ReadStatus
from google_books import split_categories
from schemas.tag import TagOut
from schemas.user import UserOut

if TYPE_CHECKING:
    # Imported for typing only: loan.py imports this module in turn, so a
    # real import here would be circular. The annotation below is therefore
    # unquoted but references a name that does not exist at runtime, which
    # works because Python 3.14 defers annotation evaluation (PEP 649), and is
    # part of why this package requires 3.14. `__init__.py` then resolves it
    # with model_rebuild() once both modules are loaded.
    from schemas.loan import LoanOut

# Loose bounds, meant to catch a typo or a scanner misread rather than to
# adjudicate publishing history.
MIN_YEAR = 1
MAX_YEAR = 2200


class BookLookup(BaseModel):
    """Metadata fetched for an ISBN. Nothing is persisted at this point: the
    client edits it and posts it back to /api/books/scan."""

    isbn: str
    title: str
    subtitle: str | None = None
    author: str | None = None
    publisher: str | None = None
    year: int | None = None
    description: str | None = None
    cover_url: str | None = None
    series_name: str | None = None
    series_index: float | None = None
    suggested_tag_ids: list[int] = []


class BookCreate(BaseModel):
    # Accepts any written form (hyphenated, spaced, ISBN-10) and stores the
    # canonical ISBN-13, so the same book cannot be added twice under two
    # spellings. See the validator below.
    isbn: str | None = Field(default=None, max_length=20)
    title: str = Field(min_length=1, max_length=500)
    subtitle: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=255)
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    description: str | None = None
    cover_url: str | None = Field(default=None, max_length=500)
    is_private: bool = False
    series_name: str | None = Field(default=None, max_length=255)
    series_index: float | None = Field(default=None, ge=0, le=1000)
    location: str | None = Field(default=None, max_length=120)

    @field_validator("isbn")
    @classmethod
    def canonicalise_isbn(cls, value: str | None) -> str | None:
        """Normalise to ISBN-13, or reject.

        An ISBN that fails its checksum is a misread or a typo, and accepting
        it produces a catalogue entry that can never be matched against any
        metadata source. Books with no ISBN at all stay allowed: that is how
        manual entries work.
        """
        if value is None or not value.strip():
            return None
        canonical = isbn_utils.parse(value)
        if canonical is None:
            raise ValueError(
                "Not a valid ISBN. Check the digits, or leave it blank to add the book manually."
            )
        return canonical


class BookOut(BaseModel):
    id: int
    isbn: str | None
    title: str
    subtitle: str | None
    author: str | None
    publisher: str | None
    year: int | None
    description: str | None
    cover_url: str | None
    added_at: datetime
    is_private: bool = False
    ownership: OwnershipStatus = OwnershipStatus.OWNED
    added_by: UserOut | None = None
    tags: list[TagOut] = []

    # Enrichment fields. `categories` is stored as one delimited string on the
    # model because SQLite has no array type, but served as a list: making every
    # client parse the same delimiter is how one of them eventually parses it
    # differently.
    page_count: int | None = None
    language: str | None = None
    categories: list[str] = []
    google_books_id: str | None = None

    series_name: str | None = None
    series_index: float | None = None
    location: str | None = None

    # The two fields below are not columns. They are computed per request and
    # depend on *who is asking*, so the same row serialises differently for
    # different members. Never cache a BookOut across accounts.
    active_loan: LoanOut | None = None
    my_status: ReadStatus = ReadStatus.UNREAD
    my_rating: int | None = None
    my_started_at: datetime | None = None
    my_finished_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("categories", mode="before")
    @classmethod
    def parse_categories(cls, value: object) -> object:
        """Turn the stored "Fiction; Science Fiction" into a list.

        The separator is a semicolon, not a comma, and that is load bearing:
        Google's own category names contain commas ("Fiction, general"), so
        splitting on one would shred them. `google_books.CATEGORY_SEPARATOR`
        is the single definition of what was joined.

        `mode="before"` because the attribute read off the model is a string
        and the field is a list, so this has to run ahead of validation rather
        than after it. Empty segments are dropped: a trailing separator is not
        a category.
        """
        if isinstance(value, str):
            return split_categories(value)
        if value is None:
            return []
        return value


class BookEnrichmentOut(BaseModel):
    """The outcome of an enrichment run.

    `updated_fields` is what makes this honest: enrichment often finds a volume
    but has nothing to add, and reporting "done" would look like a no-op bug.
    """

    book: BookOut
    updated_fields: list[str]
    found: bool


class GoogleBooksMatch(BaseModel):
    """One candidate from a free-text search, for picking the right edition."""

    google_books_id: str | None = None
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    publisher: str | None = None
    year: int | None = None
    description: str | None = None
    page_count: int | None = None
    language: str | None = None
    categories: str | None = None
    cover_url: str | None = None
    isbn13: str | None = None
    series_name: str | None = None
    series_index: float | None = None
    # Populated by the pre-creation search, where the result is about to
    # become a new book and the tag guess saves the person picking them by
    # hand. Left empty by the enrichment candidates endpoint, where the book
    # already exists and its tags are a deliberate choice not to overwrite.
    suggested_tag_ids: list[int] = []


class BookStatusUpdate(BaseModel):
    status: ReadStatus


class BookRatingUpdate(BaseModel):
    """A personal rating, or `null` to clear it.

    Separate from the status update because rating and progress are not the
    same act: finishing a book and deciding what you thought of it happen at
    different moments, and often days apart.
    """

    rating: int | None = Field(default=None, ge=1, le=5)


class BookDetailsUpdate(BaseModel):
    """The fields a person edits by hand after a book exists.

    Every field is optional and absent means "leave alone", so the form can
    send only what changed. An explicit `null` clears, which is how a series is
    unset; the two cases are distinguished with `model_fields_set`.
    """

    title: str | None = Field(default=None, min_length=1, max_length=500)
    subtitle: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=255)
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    description: str | None = None
    series_name: str | None = Field(default=None, max_length=255)
    series_index: float | None = Field(default=None, ge=0, le=1000)
    location: str | None = Field(default=None, max_length=120)


class SeriesOut(BaseModel):
    """One series, as the browse list shows it."""

    name: str
    book_count: int = Field(ge=0)
    # What is missing from an otherwise contiguous run: [2, 5] for a shelf
    # holding 1, 3, 4 and 6. Only whole numbers, and only below the highest
    # index held, because a series with no known length has no meaningful
    # "missing" beyond what sits between the ones present.
    missing_indexes: list[int] = []


class LocationOut(BaseModel):
    """A distinct shelf location and how much is on it."""

    name: str
    book_count: int = Field(ge=0)


class DuplicateGroup(BaseModel):
    """Books that look like the same work.

    Matched on normalised title plus author rather than ISBN: the unique ISBN
    already prevents exact repeats, and the case worth catching is a hardback
    and a paperback, which are legitimately two different ISBNs.
    """

    key: str
    books: list[BookOut]


class MergeRequest(BaseModel):
    """Fold several books into one.

    `keep_id` survives and must appear in `book_ids`, spelled out rather than
    inferred so a mistyped request fails instead of silently keeping whichever
    row sorted first.
    """

    book_ids: list[int] = Field(min_length=2, max_length=20)
    keep_id: int


class OwnershipUpdate(BaseModel):
    ownership: OwnershipStatus


class BulkRequest(BaseModel):
    """One verb applied to a selection.

    `value` is deliberately loose: which field it fills depends on the action,
    and the handler validates it against that action rather than the schema
    carrying six mutually exclusive optional fields.
    """

    book_ids: list[int] = Field(min_length=1, max_length=500)
    action: BulkAction
    value: str | int | None = None


class BulkResult(BaseModel):
    """What a bulk action did.

    `skipped` is not an error: a selection can include a book the caller may
    not modify, and reporting success for it would be a lie. `unchanged`
    separates "already in that state" from "changed", so the UI can say what
    actually happened rather than implying work that did not occur.
    """

    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    skipped: int = Field(ge=0)


class BulkOwnershipUpdate(BaseModel):
    """Mark several books at once.

    The flow this exists for: import a Goodreads library, then pick out the
    ones actually on the shelf. Doing that one book at a time for a few hundred
    imported rows is not a realistic ask.
    """

    book_ids: list[int] = Field(min_length=1, max_length=500)
    ownership: OwnershipStatus


class BulkOwnershipResult(BaseModel):
    """What the bulk update did.

    `skipped` is not an error: a selection can include a book the caller may
    not modify, and silently reporting success for it would be a lie.
    """

    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    skipped: int = Field(ge=0)


class PrivacyUpdate(BaseModel):
    is_private: bool
