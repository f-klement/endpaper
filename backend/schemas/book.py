from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator, model_validator

import covers
import isbn as isbn_utils
from authors import split_authors
from enums import (
    BookCondition,
    BookFormat,
    BulkAction,
    CatalogueSource,
    LendingWillingness,
    OwnershipStatus,
    ReadStatus,
)
from google_books import split_categories
from models import (
    CATEGORIES_MAX,
    DESCRIPTION_MAX,
    MAX_PAGE_NUMBER_IN_A_BOOK,
    MAX_SERIES_INDEX,
)
from schemas.author import RefusedAssertionOut
from schemas.classification import (
    MAX_CLASSIFICATIONS_PER_BOOK,
    ClassificationIn,
    ClassificationOut,
)
from schemas.common import RowIdField
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

# How long `BookMatch.source` may be. Here rather than in `models.py` because
# there is no column: it is a label naming which catalogues answered, and
# nothing stores it. See the field for the derivation.
SOURCE_LABEL_MAX = 120


class BookLookup(BaseModel):
    """Metadata fetched for an ISBN. Nothing is persisted at this point: the
    client edits it and posts it back to /api/books/scan."""

    isbn: str
    title: str
    subtitle: str | None = None
    author: str | None = None
    publisher: str | None = None
    year: int | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    cover_url: str | None = None
    series_name: str | None = None
    series_index: float | None = None
    # Carried because the DNB supplies both and is the only source that does so
    # reliably for German publishing. Without them here a scan pays for the
    # lookup and then throws half the record away.
    language: str | None = None
    page_count: int | None = None
    #: What the catalogues placed this book at, kept whole: scheme, number and
    #: the caption they gave it. Here and not only in `suggested_tag_ids`
    #: because the suggestion is the library's reading of the number and this
    #: is the library's own assertion.
    #:
    #: `ClassificationIn`, not `ClassificationOut`, and that is the point: this
    #: whole model is a draft the client posts straight back to
    #: `POST /api/books`, so what it carries has to be what that accepts. The
    #: bounds are applied where the record is parsed (`classifications.bounded_headings`), so a
    #: caption longer than the column is dropped there rather than 422ing the
    #: member's own request.
    classifications: list[ClassificationIn] = []
    #: Tags the library might want on this book, from the subject headings
    #: **and** from any DDC number above. Never applied on its own: see
    #: `serialisation.suggested_tag_ids`.
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
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    cover_url: str | None = Field(default=None, max_length=500)
    is_private: bool = False
    series_name: str | None = Field(default=None, max_length=255)
    series_index: float | None = Field(default=None, ge=0, le=MAX_SERIES_INDEX)
    location: str | None = Field(default=None, max_length=120)
    #: Which collection to file it into, or absent for none. Refused with a 400
    #: when no such collection exists, rather than surfacing the foreign key as
    #: a 500. Bounded like every other caller-supplied row id: see MAX_ROW_ID.
    collection_id: RowIdField | None = None
    #: 10, which is what `books.language` is, and it was 16 until 2026-09-02.
    #: SQLite ignores VARCHAR width so the disagreement refused nothing here,
    #: but it meant this API accepted six characters no engine that enforces a
    #: width would store, and `importing.py` had to consult both numbers and
    #: take the smaller. Nothing legitimate is lost: every language this app
    #: writes comes from `metadata._LANGUAGES` (two letters) or Google's own
    #: `language` (two or three), and the longest tag anybody could want,
    #: `zh-Hant-HK`, is exactly 10. A row already holding a longer value stays
    #: readable and editable: `BookOut` bounds nothing and `BookDetailsUpdate`
    #: has no language field.
    language: str | None = Field(default=None, max_length=10)
    page_count: int | None = Field(default=None, ge=1, le=MAX_PAGE_NUMBER_IN_A_BOOK)
    # The one collector field offered at add time. Somebody scanning a book is
    # holding it, so this is the one moment they can answer without checking.
    format: BookFormat | None = None
    #: The headings the lookup returned, posted back so the scan flow stores
    #: them. Bounded: every entry becomes a row. Duplicates within one payload
    #: are dropped by `classifications.add_headings` rather than refused, because the
    #: catalogues themselves repeat a number across sources.
    classifications: list[ClassificationIn] = Field(
        default=[], max_length=MAX_CLASSIFICATIONS_PER_BOOK
    )

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


class CopyCreate(BaseModel):
    """Another copy of a book already in the catalogue.

    Carries only what differs between two copies of one title. Everything about
    the *work* (title, author, ISBN, cover, series, description) is taken from
    the book being copied rather than accepted here, because a payload that
    could restate them is a payload that can disagree with them, and two rows
    claiming to be copies of each other while naming different books is a state
    nothing else in this app knows how to render.

    `is_private` is absent for a sharper reason: it is inherited from the
    source. A copy of somebody's private book that came back public would
    disclose the book, and this is the one field where the caller getting their
    way is a privacy leak rather than a preference. The copy belongs to whoever
    added it, so `PATCH /api/books/{id}/privacy` can change it afterwards.
    """

    location: str | None = Field(default=None, max_length=120)
    #: Deliberately **not** inherited from the book being copied, unlike the
    #: work fields and unlike `is_private`. Which collection a copy belongs to
    #: is a fact about the object, like its shelf and its condition: the
    #: library with an Ebooks collection buying the paperback wants the two
    #: apart, and inheriting would put them together and call it a default.
    #: A copy starts unfiled unless this says otherwise.
    collection_id: RowIdField | None = None
    format: BookFormat | None = None
    condition: BookCondition | None = None
    lending: LendingWillingness | None = None
    purchase_price_minor: int | None = Field(default=None, ge=0, le=MAX_PRICE_MINOR)
    purchase_currency: str | None = Field(default=None, min_length=3, max_length=3)
    purchased_at: date | None = None
    purchase_source: str | None = Field(default=None, max_length=120)

    @field_validator("purchase_currency")
    @classmethod
    def upper_case_currency(cls, value: str | None) -> str | None:
        """`eur` and `EUR` are the same currency and must not sort apart."""
        return value.upper() if value else value


class BookOut(BaseModel):
    #: Authority identifiers a catalogue asserted for this Book's author and
    #: this Library declined, because it already holds a different one.
    #:
    #: **Empty on every response but two.** Only `PUT /{id}/refresh` and
    #: `POST /{id}/enrich` fetch a catalogue record and so can produce one; a
    #: plain read has nothing to report and leaves it empty. It is on `BookOut`
    #: rather than on an enrichment-only model because those two handlers return
    #: different types and the fact is the same one.
    #:
    #: Not stored. See `schemas.author.RefusedAssertionOut`.
    refused_identifiers: list[RefusedAssertionOut] = Field(default_factory=list)
    id: int
    isbn: str | None
    title: str
    subtitle: str | None
    author: str | None
    #: The credit line split into the people in it, in the order written.
    #:
    #: Derived from `author` on every serialisation, never stored: the column
    #: stays the one place a book says who wrote it, and this is the same fact
    #: parsed. It is here so a card can link each name to that author's shelf
    #: without every client reimplementing the separator rule, which is the
    #: mistake `categories` already documents (Google's own category names
    #: contain commas, so that field is semicolon joined; this one is not, and
    #: the two rules must not be swapped).
    #:
    #: Costs no statement: `authors.split_authors` is a string operation on a
    #: column already loaded. See the note above `_books_to_out` about what
    #: adding a per-request *query* here would cost.
    authors: list[str] = []
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

    #: Published scheme headings, in insertion order. Distinct from `tags`
    #: (this library's own words) and from `categories` (whatever the
    #: publisher claimed): only this one carries a scheme that means something
    #: outside this house. Batched with the tags in `books_to_out`, so it costs
    #: no statement per book.
    classifications: list[ClassificationOut] = []

    series_name: str | None = None
    series_index: float | None = None
    location: str | None = None

    #: Which collection this **object** is filed in, or null for none. Per row
    #: rather than per copy group: see `models.Book.collection_id`.
    collection_id: int | None = None
    #: Its name, filled in by `serialisation.books_to_out` in one statement for
    #: the whole page. A projection of the row the id names, not a second copy
    #: of it: nothing writes this, and a client that renamed a collection reads
    #: the new name on the next fetch. Present so a card can show where a book
    #: lives without every consumer fetching the collection list to join
    #: against.
    collection_name: str | None = None

    format: BookFormat | None = None
    condition: BookCondition | None = None
    #: Whether the library will lend this copy. Null while nobody has said.
    lending: LendingWillingness | None = None
    #: Minor units (cents). The client divides by 100 to display it; storing a
    #: decimal would round-trip through a float over SQLite.
    purchase_price_minor: int | None = None
    purchase_currency: str | None = None
    purchased_at: date | None = None
    purchase_source: str | None = None

    #: How many copies of this title the library holds, counting this row.
    #:
    #: 1 for almost every book. Served on every payload rather than only on the
    #: detail page, because two copies are two rows and the library grid shows
    #: both: without a number on the card, a shelf with a spare paperback looks
    #: like a catalogue that has double-added something.
    #:
    #: Counts only the copies the caller may see, like everything else here. A
    #: member who made their own copy private does not thereby tell the rest of
    #: the library that a third copy exists.
    copy_count: int = 1

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

    #: Whether the caller has offered to talk about this book.
    my_wants_to_discuss: bool = False
    #: Everybody who has, the caller included.
    #:
    #: The one per-member field on this payload that is **not** scoped to who
    #: is asking, and deliberately so: a flag meaning "ask me about it" is
    #: worth nothing if only the person who set it can see it. It says nothing
    #: about anybody's reading status, which stays private.
    discuss_with: list[UserOut] = []

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

    @model_validator(mode="after")
    def derive_authors(self) -> BookOut:
        """Split the credit line, every time this model is built.

        Here rather than in `serialisation.books_to_out` so the two fields
        cannot disagree: any future caller that builds a `BookOut` gets the
        same split, and a value passed in for `authors` is overwritten rather
        than believed. `author` is the fact; this is that fact parsed.

        Free: a string operation on a column already loaded, with no statement
        behind it.
        """
        self.authors = split_authors(self.author)
        return self


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

    **Every field is bounded, because this is a request body and not only a
    response.** `POST /api/books/{id}/enrich/apply` accepts one, so each field
    is a value a member chose rather than one a catalogue supplied.

    **And since 2026-09-03 it is the only way a catalogue value reaches a Book
    column through `merge_into`**, which is a second reason for the same
    bounds rather than a second rule. `google_books.merge_into` takes this
    model rather than a dictionary, so `POST /api/books/{id}/enrich` builds one
    through `routers/books._bounded_match` instead of handing over whatever
    `Record.as_match()` assembled. Before that the ceilings applied on one
    route and not on its neighbour: the same oversized value was a 422 on
    apply and a stored row on enrich, same book, one route apart.

    **Through `merge_into` was the whole of the claim, because a third route
    did not go through it, and that closed on 2026-09-03 one layer below all
    three.** `PUT /api/books/{id}/refresh` assigns nine columns straight off the
    same `catalogue.Record` and builds no model at all, so a 9999 year and a
    40,000 character description were stored there and refused on both of the
    other two. Measured, one volume, three routes. Both critic seats found it
    separately while checking an earlier version of this paragraph that claimed
    the whole family was closed, which is why the sentence says which door it
    means.

    `catalogue.Record` now clears every scalar its column cannot hold at
    construction, so no producer hands any of the three an unusable value and
    the refresh route needed no model of its own. What these bounds still do
    alone is the two fields a record does not carry: `categories`, which
    `as_match` assembles from the record's subject list, and `suggested_tag_ids`.
    """

    # **Where each number comes from, and it is never taste.** A field naming a
    # column `BookCreate` also names takes `BookCreate`'s number, so two
    # request bodies for one column cannot disagree. A field naming a column
    # `BookCreate` does not takes the column's own width from `models.py`.
    # Only `source` has neither, and its bound is derived at the field.
    #
    # **Naming, not writing**, and the distinction is a correction rather than
    # pedantry: `google_books.merge_into` writes eleven of these plus
    # `cover_url`, and `title` and `isbn13` are not among them. The rule that
    # picks their numbers is agreement with the other bodies writing that
    # column, which holds whether or not this route writes it.
    #
    # Four of these seventeen fields were bounded and thirteen were not,
    # until 2026-09-02, under a comment saying the bounds matched
    # `BookCreate`'s. That was true of the two fields it sat above and false of
    # the rest, which is why reading it found nothing. The ticket that fixed it
    # counted eleven, having read only the strings: `series_index` is a float
    # and `suggested_tag_ids` is a list, and both were open too.
    #
    # A comment does not keep this, so
    # `tests/schemas/test_book.py::TestEveryFieldARequestBodyCarriesIsBounded`
    # does, over every request body in the application rather than over this
    # model: this model is how the class arrived, not where it ends.

    #: Which catalogue this row came from, for the label in the picker.
    #:
    #: The one field with no column behind it: `apply_enrichment` excludes it
    #: and `merge_into` does not name it, so nothing stores it. The bound is
    #: therefore about the request rather than the row, and is derived from
    #: what the field can legitimately say: `catalogue.Record.sources` joins
    #: the answering catalogues with `+`, and the whole roster of nine
    #: (bnf, dnb, google_books, k10plus, loc, nkp, nlg, oenb, open_library)
    #: joined measures **58** characters. 120 admits that roster roughly
    #: doubling.
    source: str = Field(default="", max_length=SOURCE_LABEL_MAX)
    #: `books.google_books_id` is `String(50)` and `BookCreate` has no
    #: counterpart, so the column is the source of the number. A Google volume
    #: id is 12 characters (`zyTCAlFPjgYC`), so the column already carries 4.2x
    #: what the field holds.
    google_books_id: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=500)
    subtitle: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=255)
    # `{"year": 2**63}` raised `OverflowError` on the commit and answered 500
    # to any member. Measured, and the reason this model started carrying
    # bounds at all.
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    page_count: int | None = Field(default=None, ge=1, le=MAX_PAGE_NUMBER_IN_A_BOOK)
    language: str | None = Field(default=None, max_length=10)
    categories: str | None = Field(default=None, max_length=CATEGORIES_MAX)
    cover_url: str | None = Field(default=None, max_length=500)
    #: The `isbn` column under another name, because a search row is one
    #: printing among several rather than the one asked for. So
    #: `BookCreate.isbn`'s 20, which is the agreement rule's number rather than
    #: a column's: `merge_into` names neither `isbn13` nor `title`, so neither
    #: is written on this route at all. Both critic seats caught the earlier
    #: wording claiming a write that does not happen.
    isbn13: str | None = Field(default=None, max_length=20)
    series_name: str | None = Field(default=None, max_length=255)
    #: **The sharpest of the thirteen**, and a stored denial of service rather
    #: than an oversized row. `merge_into` writes this column, and
    #: `routers/books.list_series` computes `set(range(1, max(held) + 1))` over
    #: it under `Shelf.seen_by`, so every member pays. Measured twice, on
    #: different machines and by different seats: 70.5 bytes and 0.624 seconds
    #: per million elements (`importing.py`), and 99.2 bytes and 1.554 seconds
    #: per million counting the `sorted()` list as well as the set. A stored
    #: `1e9` is therefore tens of gigabytes and tens of minutes, per request,
    #: until somebody finds the row.
    #:
    #: **Both routes that write the column now go through here**, and the
    #: second one was closed on 2026-09-03. `POST /api/books/{id}/enrich` used
    #: to hand `Record.as_match()` straight to `merge_into` and never build a
    #: `BookMatch`, so a catalogue supplying `1e9` was stored with a 200 where
    #: the identical value here was a 422: measured end to end, same book, one
    #: route apart. It is reachable from a catalogue rather than only from an
    #: upload, because `metadata._marc_title` takes the first digit run of
    #: `245 $n` and calls `float()` on it.
    #:
    #: So `importing.py`'s claim that this field is `ge=0, le=1000` on every
    #: API path is true of every path that validates, and it was false of one
    #: of those until then. `POST /api/backup/restore` is outside it and always
    #: was: it inserts through Core, where neither pydantic nor a `@validates`
    #: fires, and its own module states that an admin is not a reason to trust
    #: a file. That is why the ceiling is also applied at the reader, in
    #: `routers/books.list_series`, which is the only thing that covers a row
    #: already written.
    #:
    #: **The bound is on the signature rather than at the call site**, because
    #: a rule a caller has to remember is a rule the next caller forgets: this
    #: hole was one route failing to do what its neighbour did.
    #: `google_books.merge_into` takes a `BookMatch`, so a dictionary fails
    #: mypy at any call site and raises on the first `getattr` at runtime.
    #: The mutual import that costs is `TYPE_CHECKING` only and cannot be
    #: otherwise: this module imports `split_categories` from `google_books`,
    #: which is the cycle, and PEP 649 is why the annotation still needs no
    #: quoting.
    series_index: float | None = Field(default=None, ge=0, le=MAX_SERIES_INDEX)
    #: Bounded for the same reason `year` is: this model is a request body, and
    #: `POST /api/books/{id}/enrich/apply` turns every entry into a row.
    classifications: list[ClassificationIn] = Field(
        default=[], max_length=MAX_CLASSIFICATIONS_PER_BOOK
    )
    # Populated by the pre-creation search, where the result is about to
    # become a new book and the tag guess saves the person picking them by
    # hand. Left empty by the enrichment candidates endpoint, where the book
    # already exists and its tags are a deliberate choice not to overwrite.
    #
    # Row ids, so bounded like every other one, even though `apply_enrichment`
    # excludes this field from the merge today: a body field is caller supplied
    # whether or not this year's handler reads it.
    #
    # **`RowIdField` bounds the value and `max_length` bounds the count, and
    # this field carried only the first.** On a `list`, `max_length` is the
    # number of entries, so a list of bounded ids is still an unbounded amount
    # of parsing. 500 rather than something tighter because the handler ignores
    # the field, so the bound is there to make the work finite rather than to
    # police a size: it matches `BulkRequest.book_ids`, the largest
    # caller-supplied id list here, and is 4.8x the 105 seeded tags, so no
    # realistic vocabulary trips it.
    suggested_tag_ids: list[RowIdField] = Field(default=[], max_length=500)


class BookSearchOut(BaseModel):
    """A page of search results, and which catalogues produced it.

    **The roster travels with the answer rather than sitting on a feature
    flag**, for two reasons that both bite. It is per request: the same library
    asks a different set depending on whether the reader asked to search harder,
    and a deployment level flag cannot say which of the two this page is. And
    `FeatureFlagsOut` is served without a token, so a bit about which catalogues
    a household runs would be readable by anyone who can reach the door.

    **Names and not booleans, which cost a round to arrive at.** The first draft
    sent `slow_available` and `asked_slow`, and their fourth quadrant was
    undefined for exactly the case every install reaches today: a harder request
    on a library with no slow catalogue, where the response includes no slow
    source and it is unclear whether that means "none contributed" or "not run
    harder". Two lists have no such quadrant, they partition the roster by
    construction, and they let the screen name the catalogue it is offering
    rather than describing the machine's effort.
    """

    matches: list[BookMatch]
    #: The catalogues this fan out actually asked.
    #:
    #: **What was asked, not what was wanted.** A harder request runs the
    #: ordinary search when the two rosters are equal or when the one slow fan
    #: out allowed at a time is already running, and this reports what happened
    #: either way. Empty with an empty `matches` is a real state and a different
    #: one from finding nothing: it means this library's only search catalogues
    #: are slow ones and nobody has asked for them yet.
    asked: list[CatalogueSource]
    #: The enabled search catalogues this fan out did not ask.
    #:
    #: Non empty is the whole trigger for offering a second, longer search: it
    #: is exactly what asking harder would add. Empty means asking again would
    #: ask nothing new, whatever the reader presses.
    unasked: list[CatalogueSource]


class BookStatusUpdate(BaseModel):
    status: ReadStatus


class BookRatingUpdate(BaseModel):
    """A personal rating, or `null` to clear it.

    Separate from the status update because rating and progress are not the
    same act: finishing a book and deciding what you thought of it happen at
    different moments, and often days apart.
    """

    rating: int | None = Field(default=None, ge=1, le=5)


class BookDiscussUpdate(BaseModel):
    """Offer to talk about this book, or withdraw the offer.

    Its own schema rather than a field on `BookStatusUpdate`, because the two
    are not the same act and are not set at the same moment: a book can be
    unread and worth talking about, and finishing one says nothing about
    wanting to be asked.
    """

    wants_to_discuss: bool


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
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    series_name: str | None = Field(default=None, max_length=255)
    series_index: float | None = Field(default=None, ge=0, le=MAX_SERIES_INDEX)
    location: str | None = Field(default=None, max_length=120)

    format: BookFormat | None = None
    condition: BookCondition | None = None
    lending: LendingWillingness | None = None
    purchase_price_minor: int | None = Field(default=None, ge=0, le=MAX_PRICE_MINOR)
    # Upper case, three letters, ISO 4217 shaped without asserting the code is
    # real: a library using a currency this app has never heard of is not an
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

    Matched on normalised title plus author rather than ISBN: an accidental
    exact repeat is already refused by `uq_books_isbn_single_copy`, and the
    case worth catching is a hardback and a paperback, which are legitimately
    two different ISBNs.

    **Deliberate copies are not duplicates and never appear here.** They share
    a `copy_group`, and the endpoint collapses each group to one row before
    deciding whether anything is left over.
    """

    key: str
    books: list[BookOut]


class MergeRequest(BaseModel):
    """Fold several books into one.

    `keep_id` survives and must appear in `book_ids`, spelled out rather than
    inferred so a mistyped request fails instead of silently keeping whichever
    row sorted first.
    """

    book_ids: list[RowIdField] = Field(min_length=2, max_length=20)
    keep_id: RowIdField


class OwnershipUpdate(BaseModel):
    ownership: OwnershipStatus


class BulkRequest(BaseModel):
    """One verb applied to a selection.

    `value` is deliberately loose: which field it fills depends on the action,
    and the handler validates it against that action rather than the schema
    carrying six mutually exclusive optional fields.
    """

    book_ids: list[RowIdField] = Field(min_length=1, max_length=500)
    action: BulkAction
    # unbounded ok: not a row id, and it cannot be typed as one. Which field it
    # fills depends on the verb, so a tag id, an ownership status, a shelf name
    # and a collection id all arrive here. Every handler that reads it as an id
    # validates the range itself before the value reaches the database
    # (`_require_tag`, `_checked_collection`), which is why those checks are
    # written out rather than left to the schema.
    #
    # **That sentence named two handlers and only one of them did it**, from
    # the day it was written until 2026-09-03. `_checked_collection` carried
    # the range check and said so in its own docstring; `_require_tag` beside
    # it did `int(str(value))` and went straight to `db.get`, so
    # `{"action": "add_tag", "value": 2**63}` was an `OverflowError` from
    # inside the driver and a **500** to any member. This is the shape this
    # repository keeps meeting: a guard proved on one field, trusted for the
    # field beside it, and a comment asserting both is what carries it past a
    # reader. Counted rather than read, next time.
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
