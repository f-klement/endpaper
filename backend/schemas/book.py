from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

import covers
import isbn as isbn_utils
from enums import BookCondition, BookFormat, BulkAction, OwnershipStatus, ReadStatus
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

# A price in minor units (cents). The ceiling is 100 million cents, which is a
# million in any ordinary currency: high enough for a genuinely rare book, low
# enough that a mistyped field is caught rather than stored.
MAX_PRICE_MINOR = 100_000_000


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
    # Carried because the DNB supplies both and is the only source that does so
    # reliably for German publishing. Without them here a scan pays for the
    # lookup and then throws half the record away.
    language: str | None = None
    page_count: int | None = None
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
    language: str | None = Field(default=None, max_length=16)
    page_count: int | None = Field(default=None, ge=1, le=100_000)
    # The one collector field offered at add time. Somebody scanning a book is
    # holding it, so this is the one moment they can answer without checking.
    format: BookFormat | None = None

    @field_validator("cover_url")
    @classmethod
    def renderable_cover(cls, value: str | None) -> str | None:
        """Refuse a cover URL a browser should not be pointed at.

        This is the one schema through which a member supplies this field;
        every other writer of it is a metadata source of ours. A 422 here
        rather than the ORM validator's silent drop, because here there is a
        caller to tell. See `covers.is_renderable`.
        """
        # The two steps rather than `covers.storable`, because this is the one
        # layer that refuses instead of dropping: `storable` answers None for
        # "no cover" and for "not allowed" alike, and here those are a stored
        # null and a 422.
        upgraded = covers.https_url(value)
        if upgraded is not None and not covers.is_renderable(upgraded):
            raise ValueError("A cover URL must be https or an uploaded cover")
        return upgraded

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
    #: When this book was trashed, or null while it is on the shelf. Always
    #: null outside the trash listing, since `visible_to()` excludes the rest.
    deleted_at: datetime | None = None
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

    format: BookFormat | None = None
    condition: BookCondition | None = None
    #: Minor units (cents). The client divides by 100 to display it; storing a
    #: decimal would round-trip through a float over SQLite.
    purchase_price_minor: int | None = None
    purchase_currency: str | None = None
    purchased_at: date | None = None
    purchase_source: str | None = None

    # Nothing below here is a column. Every one is computed per request and
    # depends on *who is asking*, so the same row serialises differently for
    # different members. Never cache a BookOut across accounts.
    active_loan: LoanOut | None = None
    my_status: ReadStatus = ReadStatus.UNREAD
    my_rating: int | None = None
    my_started_at: datetime | None = None
    my_finished_at: datetime | None = None

    # The caller's own latest recorded position, from `reading_progress`.
    # Personal like the four above: a member never sees another member's.
    my_progress_page: int | None = None
    #: Derived, never stored twice: `page / page_count` when the page count is
    #: known, else whatever percent was recorded, else null. Rounded to a whole
    #: number, which is the precision a progress bar can show.
    my_progress_percent: int | None = None
    my_progress_recorded_at: datetime | None = None

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


class BookMatch(BaseModel):
    """One candidate from a free-text search, for picking the right edition.

    Named for what it is rather than where it came from: search asks Open
    Library always and Google Books when a key is configured, and merges what
    they agree on into one row. `source` says which of them supplied it.
    """

    #: Which catalogue this row came from, for the label in the picker.
    source: str = ""
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

    format: BookFormat | None = None
    condition: BookCondition | None = None
    purchase_price_minor: int | None = Field(default=None, ge=0, le=MAX_PRICE_MINOR)
    # Upper case, three letters, ISO 4217 shaped without asserting the code is
    # real: a household using a currency this app has never heard of is not an
    # error worth refusing an edit over.
    purchase_currency: str | None = Field(default=None, min_length=3, max_length=3)
    purchased_at: date | None = None
    purchase_source: str | None = Field(default=None, max_length=120)

    @field_validator("purchase_currency")
    @classmethod
    def upper_case_currency(cls, value: str | None) -> str | None:
        """`eur` and `EUR` are the same currency and must not sort apart."""
        return value.upper() if value else value


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


class PurgeResult(BaseModel):
    """How many books emptying the trash destroyed."""

    purged: int = Field(ge=0)


class PrivacyUpdate(BaseModel):
    is_private: bool


class CoverBackfillOut(BaseModel):
    """What one run of the cover backfill managed.

    Numbers rather than one, because "fixed 12" on its own cannot be acted on.
    `examined` is how many books the run looked at, `stored` how many now have a
    cover this app serves itself, `unreachable` how many resolved to a URL this
    server could not download (so the remote link is kept and it is tried again
    on the next pass through the library, not the next run, which starts past
    it), `still_missing` how many no image service has one for, and `remaining`
    how many are left beyond this batch.

    `next_after_id` is the cursor. **Without it the backfill cannot finish a
    library**: the batch is chosen by book id and a book that could not be fixed
    stays in the candidate set, so it sits at the front of every subsequent run
    for ever. About 20% of ISBNs resolve to nothing (measured across ten), so on
    a large import the counter stops moving after a few runs, and a pod with no
    egress produces it on run one. The client sends the value back to carry on
    past what it has already tried.
    """

    examined: int = Field(ge=0)
    stored: int = Field(ge=0)
    unreachable: int = Field(ge=0)
    still_missing: int = Field(ge=0)
    remaining: int = Field(ge=0)
    #: Where the next run starts. 0 when this run reached the end, which is what
    #: makes the next press start again from the beginning rather than answering
    #: nothing for ever.
    next_after_id: int = Field(ge=0)
