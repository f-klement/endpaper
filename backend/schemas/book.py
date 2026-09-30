import collections.abc as abc
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Final, Union, get_args, get_origin

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
from google_books import CATEGORY_SEPARATOR, join_categories, split_categories
from models import (
    AUTHOR_LINE_MAX,
    COVER_URL_MAX,
    CURRENCY_LENGTH,
    DESCRIPTION_MAX,
    GOOGLE_BOOKS_ID_MAX,
    ISBN_MAX,
    LANGUAGE_MAX,
    LOCATION_MAX,
    MAX_PAGE_NUMBER_IN_A_BOOK,
    MAX_SERIES_INDEX,
    PUBLISHER_MAX,
    PURCHASE_SOURCE_MAX,
    SERIES_NAME_MAX,
    SUBTITLE_MAX,
    TITLE_MAX,
    Book,
)
from schemas.author import RefusedAssertionOut
from schemas.classification import (
    MAX_CLASSIFICATIONS_PER_BOOK,
    ClassificationIn,
    ClassificationOut,
)
from schemas.common import (
    MAX_PAGE_SIZE,
    RowIdField,
    one_line_without_invisible_characters,
)
from schemas.identifier import (
    MAX_IDENTIFIERS_PER_BOOK,
    BookIdentifierIn,
    BookIdentifierOut,
)
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

#: How many subjects one book's list may carry, as a request states them.
#:
#: Here rather than in `models.py`, beside the three other per book request counts
#: (`schemas/identifier.py`, `schemas/classification.py`, `schemas/digital.py`):
#: `books.categories` is `Text`, so none of these three is a column width, and
#: this module is their only consumer.
#:
#: 32 because the failure modes are asymmetric: too loose costs page weight, too
#: tight drops a whole search result silently, since `routers/books._match_rows`
#: builds the match inside a `try` that drops a **row** rather than a field. The
#: widest shape measured in this tree is 14 headings, so it clears 2.3x.
#:
#: **That is why a producer caps rather than letting this refuse.**
#: `catalogue.Record.as_match` passes this number to `join_categories`, so a
#: catalogue record carrying more subjects loses the extra ones rather than its row.
#:
#: **The count only.** A record whose capped list still exceeds `CATEGORIES_MAX` is
#: refused by that width and loses the row after all: measured, 32 subjects of 200
#: characters join to 6,462. That loss is older than this cap and is pinned
#: deliberately by
#: `tests/routers/test_books_search.py::test_the_rest_of_the_page_survives_a_bad_record`,
#: so widening anything to make the sentence unqualified would break an arm that is
#: there on purpose.
#:
#: A client body on `POST /{book_id}/enrich/apply` has had nothing capped, so there
#: the refusal stands and is a 422.
MAX_CATEGORIES_PER_BOOK: Final = 32

#: What one subject may be, as a request states it.
#:
#: **The literal rather than `models.CLASSIFICATION_NUMBER_MAX`, though the two
#: are the same number today.** They are the same number because they are the same
#: population measured, an access point with its subdivisions. Aliasing it would
#: make that claim unfalsifiable and the coupling is live in the wrong direction:
#: that constant is a **column** width, widened three times for column reasons
#: (40, 80, 100, 120) by its own record, and each widening would silently widen
#: every subject list this application accepts.
#: `tests/schemas/test_book.py::test_the_two_widths_are_the_same_population` holds
#: the equality as a measurement, so moving either has to be done twice.
CATEGORY_MAX: Final = 120

#: The longest subject list a client may write into `books.categories`.
#:
#: The second `Text` column on this table and on the **list** payload, so it
#: inherits `DESCRIPTION_MAX`'s argument whole: an oversized value is paid for on
#: every page of every listing, and the column stays `Text` so this bounds new
#: writes without making a stored row unreadable. **A stated bound rather than
#: something the column enforces**: SQLite ignores a declared width, and this one
#: is `Text`, so nothing breaks at 3,903. It is a page weight control.
#:
#: **Computed, and the separator's width is read rather than retyped.** Writing
#: the `2` as a literal put one fact in two modules: a **wider** separator would
#: make this number too small and every widest list claim in this file false,
#: which is the unsafe direction the previous note here did not mention. Reading
#: `len(CATEGORY_SEPARATOR)` removes the second home rather than guarding it, and
#: `tests/schemas/test_book.py::test_the_categories_ceiling_assumes_the_separator_it_is_derived_from`
#: pins the width with literals so this line cannot be a restatement of itself.
CATEGORIES_MAX: Final = MAX_CATEGORIES_PER_BOOK * CATEGORY_MAX + (
    MAX_CATEGORIES_PER_BOOK - 1
) * len(CATEGORY_SEPARATOR)

#: One subject, as a request states it.
#:
#: **120 here and no per subject width on `BookMatch`, over the same population,
#: and the difference is what a refusal costs on each door.** Here the entry is a
#: subject a caller typed, the widest measured shape is 14 headings, and refusing
#: is a 422 a caller can read and act on. There the value is a catalogue's own
#: heading that nobody can retype, and a refusal drops the field on an enrichment
#: the member did not choose the value of, so that door bounds what it would store
#: instead. `BookMatch.rejoin_categories` carries the measurement.
#:
#: **An alias rather than a `max_length` in the validator**, and that is the
#: whole reason it exists: `tests/schemas/test_book.py` reads a list field's
#: element type to decide whether the field is bounded, so a width spelled only
#: inside a validator is invisible to it and `list[str]` reads as unbounded
#: however narrow the validator is. `schemas/common.RowIdField` is the house
#: spelling of the same move.
CategoryField = Annotated[str, Field(max_length=CATEGORY_MAX)]


def subject_for_storage(entry: str) -> str | None:
    """One subject as the column would hold it, `None` where there is nothing left.

    Raises `ValueError` for an entry carrying the separator.
    `normalised_subjects` is the one caller and its docstring carries the
    reasoning: why a separator is a refusal rather than a drop, why an emptied
    entry is a drop rather than a refusal, and which producers reach this at
    all. **Both request bodies that write this column reach this through that
    function rather than calling it**, so there is one place the per entry rule
    is composed into a list and one place the argument for it lives.

    **Module level so that something other than a request can ask it.**
    `conformance/cases/subject.json` pins this rule against the browser's, and
    the runner over it needs the rule itself: reaching it through
    `BookCreate.model_validate` would run every other validator on the model, so
    an unrelated failure would report as a cross language divergence. Writing
    the three steps out again in the runner is worse still, because a case file
    exists to stop a rule having a second home and a reimplementation is the
    third.
    """
    tidied = one_line_without_invisible_characters(entry)
    if not tidied:
        return None
    if CATEGORY_SEPARATOR.strip() in tidied:
        raise ValueError(
            f"A subject may not contain {CATEGORY_SEPARATOR.strip()!r}, which "
            "separates subjects in storage. Send them as separate entries."
        )
    return tidied


def normalised_subjects(value: object) -> object:
    """Normalise each subject, and refuse one carrying the separator.

    **A function rather than a validator body, because two bodies write this
    column.** `BookCreate` and `BookDetailsUpdate` each call it from a
    `mode="before"` validator named `one_subject_per_entry`. The rule is
    re-applied rather than restated: it is one column's rule, and the
    paragraphs below are the argument for it, which is the thing that would
    have gone stale in the copy.

    **The ground is that the value is unrepresentable, not that it is risky.**
    `google_books.split_categories` splits on a **bare** separator, so a stored
    `"Fiction; general"` is served as two subjects to every reader of this
    column, including the member who typed it. So the refusal says "this column
    cannot hold that value", which is true whoever produced it and however many
    other writers exist.

    **A 422 here and a drop at a parser is this tree's existing arrangement for
    a body a caller composed, not a choice made for this field.**
    `classifications.bounded_headings` states it: a bad entry is dropped and
    logged there, because nothing in a record is worth failing a whole lookup
    for, while `ClassificationIn.number` is a hard 422 on the create route.
    `google_books.join_categories` drops a separator bearing subject for the two
    upstream joins, and the scan flow's own file readers drop one in the browser
    before the request is built, which is the parser layer this column used to
    lack.

    **This refuses the whole request and not the entry**, which is what a
    `field_validator` raising means. That still costs nothing, because no honest
    producer reaches it, checked per producer rather than argued: four file
    readers now emit a subject and the scan flow forwards the field, and its
    browser side bound drops a separator bearing entry rather than sending it;
    the MARC import's field list excludes this column and its gap filler assigns
    by plain `setattr`, so no validator of any model runs; and the CSV and OPDS
    imports read bounds only to truncate. **The first of those is the one held
    up by a bound rather than by an absence**, so it is the one that becomes a
    lost book rather than a lost subject if that bound goes. **The update door
    has no producer at all yet**: nothing in the browser sends this field, so
    the only caller is one somebody wrote by hand.

    `BookMatch.rejoin_categories` splits instead, and the divergence is
    deliberate: **it is forced there rather than chosen.** That door is handed
    one already joined string, in which the separator is structural and
    indistinguishable from a typed one, so a refusal would refuse every record
    carrying two or more subjects.

    **This is a correctness control, not a security control.** A hostile client
    can store any value the column holds through any door onto it.

    Both validators are `mode="before"`, so the per entry width on
    `CategoryField` applies to the normalised value rather than to what arrived.
    Normalising only ever shortens, so an entry made wide by characters that
    have no width would otherwise be refused before they were removed.

    **`renderable_cover` is the contrast and not the precedent.** It has no
    `mode`, so it runs after, and its own comment says the width bounded what
    arrived while the value it hands on is one character longer, which is why
    `_a_cover_url_the_column_can_hold` exists at all. Here normalisation only
    shortens, so running before needs no second bound.
    """
    if not isinstance(value, list):
        return value
    kept: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            # Left to pydantic, which names the offending index. **This
            # returns the whole list unnormalised**, so it skips the refusal
            # for every entry, which is only safe while nothing coercible to
            # a string can arrive: measured, pydantic coerces `bytes` in lax
            # mode and refuses `int` and `None`, and JSON carries neither, so
            # no HTTP payload reaches this line.
            return value
        # The per entry rule is `subject_for_storage`, at module level, so the
        # shared conformance cases can run the rule itself rather than a copy of
        # it: reaching it through `model_validate` would run every other
        # validator on the model, so an unrelated failure would report as a
        # cross language divergence. `None` is the drop, tested by identity
        # rather than truthiness, so an empty string would be kept if that
        # signal ever changed.
        tidied = subject_for_storage(entry)
        if tidied is None:
            continue
        kept.append(tidied)
    return kept


def _a_cover_url_the_column_can_hold(url: str | None) -> str | None:
    """The value back, refusing one whose **stored** form is wider than the column.

    `Book`'s `@validates("cover_url")` runs `covers.https_url` on every write,
    turning `http://` into `https://` and so **lengthening the value by one
    character**. A `max_length` alone therefore bounds a different string from
    the one stored: measured on both request bodies carrying this field, a 500
    character http URL was accepted and stored as 501 against a `String(500)`.
    SQLite holds the over-wide row rather than refusing it; an engine that
    enforces a `VARCHAR` width fails the flush mid request.

    **It needs no hostile upstream.** `POST /api/books` and
    `POST /api/books/{book_id}/enrich/apply` both take a URL a member chose, so
    one long real catalogue address is the whole of it.

    `catalogue._AS_STORED` is the same rule on the catalogue path, where a
    record clears the field instead. Here there is a caller to tell, so this
    raises: a 422 on both routes, and `routers/books._bounded_match` catches it
    and drops the field, which is the catalogue path's answer reached through
    this one rule rather than through a second copy of it.

    Deleting this passes every other test in the tree, so
    `tests/schemas/test_book.py::TestAColumnRewrittenOnWriteIsBoundedAfterTheRewrite`
    drives it from the rewrite table rather than from a list of field names.
    """
    if url is not None and len(covers.https_url(url) or "") > COVER_URL_MAX:
        raise ValueError(
            "A cover URL is stored upgraded to https, so it may be at most "
            f"{COVER_URL_MAX} characters once stored"
        )
    return url


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
    isbn: str | None = Field(default=None, max_length=ISBN_MAX)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    subtitle: str | None = Field(default=None, max_length=SUBTITLE_MAX)
    author: str | None = Field(default=None, max_length=AUTHOR_LINE_MAX)
    publisher: str | None = Field(default=None, max_length=PUBLISHER_MAX)
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    cover_url: str | None = Field(default=None, max_length=COVER_URL_MAX)
    is_private: bool = False
    series_name: str | None = Field(default=None, max_length=SERIES_NAME_MAX)
    series_index: float | None = Field(default=None, ge=0, le=MAX_SERIES_INDEX)
    location: str | None = Field(default=None, max_length=LOCATION_MAX)
    #: Which collection to file it into, or absent for none. Refused with a 400
    #: when no such collection exists, rather than surfacing the foreign key as
    #: a 500. Bounded like every other caller-supplied row id: see MAX_ROW_ID.
    collection_id: RowIdField | None = None
    #: 10, which is what `books.language` is, and it was 16 until 2026-09-02.
    #: SQLite ignores VARCHAR width so the disagreement refused nothing here,
    #: but it meant this API accepted six characters no engine that enforces a
    #: width would store, and `importing.py` had to consult both numbers and
    #: take the smaller. Nothing legitimate is lost: every language this app
    #: writes comes from `bibliographic.LANGUAGES` (two letters) or Google's own
    #: `language` (two or three), and the longest tag anybody could want,
    #: `zh-Hant-HK`, is exactly 10. A row already holding a longer value stays
    #: readable and editable: `BookOut` bounds nothing and `BookDetailsUpdate`
    #: has no language field.
    language: str | None = Field(default=None, max_length=LANGUAGE_MAX)
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
    #: What a store calls this Book, where that is not an ISBN.
    #:
    #: **A second identifier field rather than a wider `isbn`**, and that is the
    #: decision this field exists to record: `books.isbn` is the importer's
    #: match key and every path into it check digits its input, so an ASIN
    #: stored there matches nothing and takes the dedupe surface down with it.
    #: `enums.BookIdentifierScheme` carries the argument in full.
    #:
    #: Bounded: every entry becomes a row. Duplicates within one payload are
    #: dropped by `identifiers.add_identifiers` rather than refused, because a
    #: client reading two of its own files may find one book in both.
    identifiers: list[BookIdentifierIn] = Field(
        default=[], max_length=MAX_IDENTIFIERS_PER_BOOK
    )
    #: Subjects a client asserts about this book, stored and never interpreted.
    #:
    #: **Deliberately not the Tag system**, which is the distinction
    #: `models.Book.categories` exists to record: a tag is a word this library
    #: chose from its own small vocabulary, and one of these is whatever a
    #: publisher or a stranger's file said. Nothing is minted from them, no tag
    #: is created, and `serialisation.match_subjects_to_tags` is not called on
    #: this route.
    #:
    #: Bounded by a count and a per entry width rather than by the column's
    #: width, because this is the shape a request carries: see
    #: `MAX_CATEGORIES_PER_BOOK` above, which `CATEGORIES_MAX` is computed from,
    #: so an accepted list cannot join to a value the column refuses.
    #: `tests/schemas/test_book.py` holds that identity.
    #:
    #: A list on the wire and one delimited string in the column, for the reason
    #: `BookColumns.categories` states: making every client parse the same
    #: delimiter is how one of them eventually parses it differently.
    categories: list[CategoryField] = Field(
        default=[], max_length=MAX_CATEGORIES_PER_BOOK
    )

    #: What this book's arrival establishes about ownership.
    #:
    #: **Owned is the default because that is what the two original routes into
    #: this endpoint mean**: somebody scanning a barcode is holding the book,
    #: and somebody adding one by hand is cataloguing theirs. `routers/books.py`
    #: states the same reason where a copy is created.
    #:
    #: **A store import is the third route and it is the one that cannot always
    #: say.** An Adobe Digital Editions catalogue records a three week library
    #: loan and a purchase identically, and no amount of reading it recovers the
    #: difference: the loan lives in the fulfilment token beside the book, which
    #: is the protection on the file and is not something this app opens. A
    #: client reading such a store sends `unknown` rather than letting this
    #: default make a claim about what somebody owns.
    #:
    #: Not a new idea and not a new value: `importing.py` already writes
    #: `unknown` on the two server side import routes, for this reason. What was
    #: missing was any way for a client to say it, so every store import wrote
    #: `owned` whether or not its store had established one.
    ownership: OwnershipStatus = OwnershipStatus.OWNED

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
        # The width goes last and against `upgraded`, because this validator
        # returns the upgraded form: the `max_length` above bounded what
        # arrived, and what this model hands on is one character longer.
        return _a_cover_url_the_column_can_hold(upgraded)

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

    @field_validator("categories", mode="before")
    @classmethod
    def one_subject_per_entry(cls, value: object) -> object:
        """The rule is `normalised_subjects` above, applied rather than
        restated.

        It lived here, and four files outside this module cite this name for
        it, which is why the name stays where they point while the body moves:
        `BookDetailsUpdate` is the second door onto this column and a second
        copy of that paragraph is the fact in two files the writing rule is
        about."""
        return normalised_subjects(value)


#: Fields of `BookCreate` the `Book` constructor is never handed, because every
#: entry becomes a child row: `classifications.add_headings` and
#: `identifiers.add_identifiers` write them after the insert, from the validated
#: models on the payload rather than from the dump.
CARRIED_AS_CHILD_ROWS: Final[tuple[str, ...]] = ("classifications", "identifiers")

#: Fields of `BookCreate` that ARE a column of `books` but whose request shape is
#: not the stored shape, so the constructor is handed the stored form instead.
#:
#: A separate cell from the one above rather than a third name in it, because the
#: remedies differ: a name there has no column at all, and a name here has one
#: whose value has to be reshaped on the way in. The assignment stays at the
#: writer, since what the reshaping IS differs per field and there is no enum over
#: them.
RESHAPED_FOR_ITS_COLUMN: Final[tuple[str, ...]] = ("categories",)

#: What `routers/books._create_book` takes out of the dump before the
#: constructor. The router loops this rather than spelling one `pop` per name, so
#: the popped set and the refusal below are one object and cannot drift.
POPPED_BEFORE_THE_CONSTRUCTOR: Final[tuple[str, ...]] = (
    CARRIED_AS_CHILD_ROWS + RESHAPED_FOR_ITS_COLUMN
)


def _without_annotations(annotation: object) -> object:
    """The annotation with every `Annotated[...]` wrapper stripped."""
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


#: What counts as a container when a field's annotation is read.
#:
#: **An explicit tuple rather than `collections.abc.Collection`.** That ABC decides
#: membership through a subclass hook over `__len__`, `__iter__` and `__contains__`,
#: so a field type that later grew those three would newly satisfy the refusal below
#: and stop **this module** importing, which is the application rather than a test.
#: The abstract three are here because a field may be annotated with them directly
#: and `get_origin` answers them rather than a concrete type.
_CONTAINER_ORIGINS: Final = (
    list,
    set,
    frozenset,
    dict,
    tuple,
    abc.Sequence,
    abc.Set,
    abc.Mapping,
)

#: Excluded although every one of them satisfies `abc.Sequence`.
#:
#: Their size is a character width, which the width rules already read, so counting
#: them here would report every string field on the body as a container.
_NOT_A_CONTAINER: Final = (str, bytes, bytearray)


def admits_a_container(annotation: object) -> bool:
    """Whether this annotation admits a list, a set, a mapping or a tuple.

    Public because `importing.within_bounds` reads it too: a `MaxLen` on a
    container field is a count of entries and not a character width, and one home
    for "what is a container" is what keeps the two readings from disagreeing.

    **`Annotated` is peeled before the origin is read, and that is not tidiness.**
    Measured: `get_origin(Annotated[list[str], "x"])` answers `typing.Annotated`,
    not `list`, so without the peel this answers False for
    `Annotated[list[str], Field(max_length=1)] | None`, which is the house spelling
    of a bounded container on an optional field and the shape every optional field
    on these bodies has. It answered correctly for `RowIdField | None` for the
    **wrong reason**, that `typing.Annotated` is not a `type`, and a reader who
    believed the stated reason would believe the bounded container case was covered.

    A union is unwrapped member by member; the container set and the three
    exclusions carry their own reasons above.
    """
    annotation = _without_annotations(annotation)
    origin = get_origin(annotation)
    if origin is UnionType or origin is Union:
        return any(admits_a_container(member) for member in get_args(annotation))
    subject = origin if origin is not None else annotation
    if not isinstance(subject, type):
        return False
    if issubclass(subject, _NOT_A_CONTAINER):
        return False
    return issubclass(subject, _CONTAINER_ORIGINS)


def _unconstructable_fields(
    child_rows: Iterable[str],
    reshaped: Iterable[str],
    fields: Mapping[str, object],
    columns: Iterable[str],
) -> dict[str, str]:
    """Every field of one request body its writer cannot write as it stands.

    **Two doors read this, so the faults name no writer.** `BookCreate` reaches
    the `Book` constructor and `BookDetailsUpdate` reaches an assignment onto a
    row that already exists; the partition is the same either way, and the two
    call sites say which writer they are about. It was the create door's alone
    until the update door grew a reshaped field, at which point the missing
    half was not the field but the refusal.

    Five faults with five different remedies, so the answer names the fault per
    field rather than returning a set: a name popped for the wrong reason teaches
    the next reader the wrong rule, and a field written to the row as a list is a
    failed write rather than a mistake in a comment.

    The two arms over the remainder are the ones that fire for somebody who has
    not read this: a further scalar field whose name is a column needs no edit
    anywhere and nothing here fires, which is the common case and is why this is
    a derivation rather than a list of names. **The container arm is what makes
    the column arm more than a name check**, since a field that shares a name
    with a column and arrives as a list passes the column arm and still cannot be
    constructed.

    **Two blind spots, and the extent of neither is claimed.** A scalar whose type
    the column cannot hold, a `date` field over an `Integer` column, passes the
    container arm. And `admits_a_container` answers False for the abstract
    supertypes above `Collection`: measured, `abc.Iterable[str]`,
    `abc.Collection[str]` and `abc.Iterator[str]` all read as scalars, pydantic
    accepts them as annotations, and the failure would be the write rather than a
    report. They are absent from the set on purpose, for the reason
    `_CONTAINER_ORIGINS` carries, so this is a cost rather than an oversight.

    Takes its four sides rather than reading them, for `book_columns._misfiled`'s
    reason: a test can drive it against a model and a table it builds, so every
    arm can be made to fail.
    """
    popped = set(child_rows) | set(reshaped)
    held = set(columns)
    faults: dict[str, str] = {}
    for name in sorted(popped - set(fields)):
        faults[name] = "is popped before the write but is not a field of the body"
    # Both cells subtract the names already reported above, so a name the body does
    # not have keeps the "not a field" remedy rather than acquiring a second, wrong
    # one. Without this subtraction on the child row cell, such a name was reported
    # as one that should pass through or be reshaped, which is the wrong instruction
    # for a field nobody sends.
    for name in sorted((set(child_rows) & held) - (popped - set(fields))):
        faults[name] = (
            "is popped as a child row but IS a column of `books`, so it should "
            "pass through or be reshaped"
        )
    for name in sorted(set(reshaped) - held - (popped - set(fields))):
        faults[name] = (
            "is popped as a reshaped column but is not a column of `books`, so "
            "it is a child row rather than a reshape"
        )
    for name in sorted(set(fields) - popped):
        if name not in held:
            faults[name] = "is written to the row unchanged but is not a column of `books`"
        elif admits_a_container(fields[name]):
            faults[name] = (
                "is written to the row unchanged as a container, which no column "
                "of `books` can be handed"
            )
    return faults


#: Refused at import, not at the first create.
#:
#: A check at the first create fires on somebody's library, and the two faults
#: that matter most are silent rather than loud: a pop with no write is a 201 that
#: accepted a field and stored nothing. This fires on the machine of whoever added
#: the field and stops every test run until the route says what to do with it.
#:
#: `_UNASSIGNABLE`, beneath `BookDetailsUpdate`, is the same partition read
#: against the other writer of these columns.
_UNCONSTRUCTABLE = _unconstructable_fields(
    CARRIED_AS_CHILD_ROWS,
    RESHAPED_FOR_ITS_COLUMN,
    {name: field.annotation for name, field in BookCreate.model_fields.items()},
    Book.__table__.c.keys(),
)
if _UNCONSTRUCTABLE:
    raise RuntimeError(
        "`BookCreate` and the create route disagree about what the `Book` "
        "constructor is handed: "
        + "; ".join(f"`{name}` {fault}" for name, fault in sorted(_UNCONSTRUCTABLE.items()))
        + ". Every field of that body either names a column and reaches the "
        "constructor unchanged, or is named in `CARRIED_AS_CHILD_ROWS` or in "
        "`RESHAPED_FOR_ITS_COLUMN` above. A name in the second of those needs an "
        "assignment at `routers/books._create_book` as well as the pop: a pop "
        "with no write stores nothing and answers 201."
    )


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

    location: str | None = Field(default=None, max_length=LOCATION_MAX)
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
    purchase_currency: str | None = Field(
        default=None, min_length=CURRENCY_LENGTH, max_length=CURRENCY_LENGTH
    )
    purchased_at: date | None = None
    purchase_source: str | None = Field(default=None, max_length=PURCHASE_SOURCE_MAX)

    @field_validator("purchase_currency")
    @classmethod
    def upper_case_currency(cls, value: str | None) -> str | None:
        """`eur` and `EUR` are the same currency and must not sort apart."""
        return value.upper() if value else value


class BookColumns(BaseModel):
    """Everything on a Book payload that a Book row answers for itself.

    A column, or something derived from one by a string operation with no
    statement behind it. Validating this from an ORM object is complete: every
    field here has a value the moment the row is loaded.

    **Split from the rest so that the rest cannot be forgotten.** See `BookOut`.
    """

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
    #: column already loaded. See the note above `books_to_out` about what
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

    #: What a store calls this Book, in insertion order. Batched with the tags
    #: and the headings in `books_to_out`, so it costs no statement per book.
    #:
    #: **This is the whole of what reads the table today**, which
    #: `models.BookIdentifier` states rather than leaves to be discovered: no
    #: query matches on an identifier and nothing renders one yet. It is here so
    #: that the fact a member's own import wrote is readable back through the
    #: API rather than only through the archive.
    #:
    #: Withheld from `PublicBookOut`: see `tests/schemas/test_public.py`.
    identifiers: list[BookIdentifierOut] = []

    series_name: str | None = None
    series_index: float | None = None
    location: str | None = None

    #: Which collection this **object** is filed in, or null for none. Per row
    #: rather than per copy group: see `models.Book.collection_id`.
    collection_id: int | None = None

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
    def derive_authors(self) -> BookColumns:
        """Split the credit line, every time this model is built.

        Here rather than in `serialisation.books_to_out` so the two fields
        cannot disagree: any future caller that builds one gets the same split,
        and a value passed in for `authors` is overwritten rather than believed.
        `author` is the fact; this is that fact parsed.

        Free: a string operation on a column already loaded, with no statement
        behind it.
        """
        self.authors = split_authors(self.author)
        return self


class ViewerFields(BaseModel):
    """The part of a Book payload that no Book row answers.

    Twelve fields, computed once per page by `serialisation.books_to_out` from
    queries a Book does not carry: the open loan, the caller's reading record,
    the caller's latest position, who is willing to talk about it, how many
    copies the caller may see, and the name behind `collection_id`.

    **No defaults, and that is the whole reason this is a type.** Every one of
    them used to be declared on `BookOut` with a plausible one: `my_status`
    defaulted to UNREAD, `copy_count` to 1, `discuss_with` to empty. A default
    on a field that is always written is a value that validates and is wrong,
    so a thirteenth field declared and then not assigned produced a well formed
    200 carrying a wrong answer with nothing red anywhere. Required here, the
    same omission is a `TypeError` at the one construction site.

    **Eleven of the twelve are scoped to the caller and `collection_name` is
    not**, which is a name this type does not quite fit. It is here because it
    has the same failure mode rather than the same audience: it is computed by
    the same loop, from the same page of queries, and a forgotten write to it
    would be the same silent wrong answer. `discuss_with` is the reverse case
    and is documented at the field.

    This is what `shelf.Outbound` does for the public path, where the class of
    error is the opposite: there the danger is a per viewer field arriving at a
    reader who has no viewer, and it is closed the same way, by construction.
    """

    #: The open loan on this copy, or null while it is on the shelf.
    active_loan: LoanOut | None
    #: The name behind `collection_id`, filled in in one statement for the whole
    #: page. A projection of the row the id names, not a second copy of it:
    #: nothing writes this, and a client that renamed a collection reads the new
    #: name on the next fetch. Present so a card can show where a book lives
    #: without every consumer fetching the collection list to join against.
    collection_name: str | None
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
    copy_count: int
    #: Everybody who has offered to talk about this book, the caller included.
    #:
    #: The one field here that is **not** scoped to who is asking, and
    #: deliberately so: a flag meaning "ask me about it" is worth nothing if
    #: only the person who set it can see it. It says nothing about anybody's
    #: reading status, which stays private.
    discuss_with: list[UserOut]

    #: The caller's own reading record. A member never sees another member's.
    my_status: ReadStatus
    my_rating: int | None
    my_started_at: datetime | None
    my_finished_at: datetime | None
    #: Whether the caller has offered to talk about this book.
    my_wants_to_discuss: bool

    #: The caller's own latest recorded position, from `reading_progress`.
    my_progress_page: int | None
    #: Derived, never stored twice: `page / page_count` when the page count is
    #: known, else whatever percent was recorded, else null. Rounded to a whole
    #: number, which is the precision a progress bar can show.
    my_progress_percent: int | None
    my_progress_recorded_at: datetime | None


class BookOut(ViewerFields, BookColumns):
    """One Book, as one member sees it. The wire shape, flat and unchanged.

    **Never cache one across accounts**: half of what is on it is an answer to
    who asked. The split above is what makes that readable rather than a comment
    in the middle of a field list.

    Built only by `seen_by`, which is the point: `model_validate(book)` cannot
    produce one, because a Book row does not know eleven of these twelve.

    **The base order is what puts the columns first in the response body.**
    Pydantic collects fields in reverse MRO, so the class listed second is the
    one whose fields lead, which is the opposite of how it reads. It governs the
    body's key order and nothing else: `scripts/dump_openapi.py` dumps with
    `sort_keys=True`, so the schema and everything orval writes from it are
    alphabetical whatever this says.
    """

    #: Authority identifiers a catalogue asserted for this Book's author and
    #: this Library declined, because it already holds a different one.
    #:
    #: **Empty on every response but two, and its default is therefore not the
    #: kind `ViewerFields` refuses.** Only `PUT /{id}/refresh` and
    #: `POST /{id}/enrich` fetch a catalogue record and so can produce one; the
    #: other eighteen callers have nothing to report, and the empty list is the
    #: answer rather than a placeholder for one. It is written by
    #: `routers.books._with_refusals`, which copies rather than assigning into
    #: the serialiser's loop.
    #:
    #: Not stored. See `schemas.author.RefusedAssertionOut`.
    refused_identifiers: list[RefusedAssertionOut] = Field(default_factory=list)

    @classmethod
    def seen_by(cls, columns: BookColumns, viewer: ViewerFields) -> BookOut:
        """The one construction site.

        **The guarantee is upstream of this line**, at the `ViewerFields(...)`
        call in `serialisation.books_to_out`: a field added there and not
        written fails to construct, and by the time both halves reach here they
        are already validated. This assembles them.

        **It re-validates the columns**, which is a real cost and a measured
        one. Per book, on the control plane: `BookColumns.model_validate` 19.5
        microseconds, `ViewerFields(**kwargs)` 2.4, this reassembly 20.1, the
        whole path 46.2. That roughly doubles per book serialisation and is
        about half a millisecond on a page of 25, against six to eight SQL round
        trips. **Not `model_construct`**, which measured 167 microseconds, eight
        times the cost of validating, besides skipping the validators.

        The one thing the re-validation asks of a `BookColumns` field is that a
        `mode="before"` validator on it be idempotent, because it runs twice.
        `parse_categories` and `derive_authors` are, and nothing pins that.
        """
        return cls(**columns.__dict__, **viewer.__dict__)


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
    # **`categories` is a fourth case, and it does not take `BookCreate`'s
    # number.** Both bodies name the column and they carry it in two shapes: a
    # list there, one joined string here. So the numbers differ and neither is a
    # copy of the other. This field states `CATEGORIES_MAX`, the column's width;
    # that one states `MAX_CATEGORIES_PER_BOOK` and `CATEGORY_MAX`, which are the
    # two factors this width is the product of. What holds them together is
    # therefore an identity rather than an equality, that the widest list the
    # other body admits joins to exactly this number, and
    # `tests/schemas/test_book.py` is where it is asserted: no type checker
    # relates a product to its factors across two modules.
    #
    # The validator below is the second half of the same fact. A bound on a
    # joined string bounds the string and not the subjects inside it, so the
    # count and the per entry width are applied here after the split, against
    # the same two factors the other body states.
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
    google_books_id: str | None = Field(default=None, max_length=GOOGLE_BOOKS_ID_MAX)
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    subtitle: str | None = Field(default=None, max_length=SUBTITLE_MAX)
    author: str | None = Field(default=None, max_length=AUTHOR_LINE_MAX)
    publisher: str | None = Field(default=None, max_length=PUBLISHER_MAX)
    # `{"year": 2**63}` raised `OverflowError` on the commit and answered 500
    # to any member. Measured, and the reason this model started carrying
    # bounds at all.
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    page_count: int | None = Field(default=None, ge=1, le=MAX_PAGE_NUMBER_IN_A_BOOK)
    language: str | None = Field(default=None, max_length=LANGUAGE_MAX)
    categories: str | None = Field(default=None, max_length=CATEGORIES_MAX)
    #: Bounded twice: `max_length` on what arrives, and the validator below on
    #: what the column ends up holding. See `_a_cover_url_the_column_can_hold`.
    cover_url: str | None = Field(default=None, max_length=COVER_URL_MAX)
    #: The `isbn` column under another name, because a search row is one
    #: printing among several rather than the one asked for. So
    #: `BookCreate.isbn`'s 20, which is the agreement rule's number rather than
    #: a column's: `merge_into` names neither `isbn13` nor `title`, so neither
    #: is written on this route at all. Both critic seats caught the earlier
    #: wording claiming a write that does not happen.
    isbn13: str | None = Field(default=None, max_length=ISBN_MAX)
    series_name: str | None = Field(default=None, max_length=SERIES_NAME_MAX)
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

    @field_validator("cover_url")
    @classmethod
    def storable_cover(cls, value: str | None) -> str | None:
        """Refuse a cover URL the column cannot hold once the ORM upgrades it.

        The width only, and **not** `BookCreate`'s renderability refusal:
        `Book`'s validator drops a cover on a host this app will not point an
        `<img>` at, silently, and turning that into a 422 here would refuse an
        enrichment over a field the member did not choose the value of.

        The value goes back unchanged rather than upgraded, so this bounds what
        will be stored without deciding what is stored.
        """
        return _a_cover_url_the_column_can_hold(value)

    @field_validator("categories")
    @classmethod
    def rejoin_categories(cls, value: str | None) -> str | None:
        """Bound the subjects inside the joined string, not just the string.

        **This door splits where `BookCreate` refuses, and the split is forced
        rather than chosen.** What arrives here is one already joined string, in
        which the separator is structural: `catalogue.Record.as_match` joins with a
        string containing the bare character, so a refusal would refuse every record
        carrying two or more subjects. Nothing about a pre joined string
        distinguishes a structural separator from a typed one, so this is the only
        rule this door can implement. `normalised_subjects` carries why the two
        request bodies refuse instead.

        **The producer differs per path rather than per door, which is why the
        forcing reason above is the one that holds.** `routers/books._bounded_match`
        builds this model server side on `POST /enrich`, and
        `POST /api/books/{book_id}/enrich/apply` validates a body the **client**
        sent, which is the same producer class the other doors refuse. So a producer
        argument would not separate these doors; the wire shape does.

        **A correctness control, not a security control.** A hostile caller can
        store any value the column holds through any door onto it. What this closes is
        the looseness one route apart that `max_length` alone left: 3,902 characters
        is 1,951 subjects when they are two characters each, against the 32 the
        member's own door allows, and `merge_into` writes the column from here.

        **The two bounds apply after the split and never before**, which is the
        whole of why the field's own `max_length` is not enough: a pre joined
        string satisfies any per subject width at once. The field stays a string
        rather than becoming a list, because `google_books.merge_into` assigns
        this column by name off `book_columns.WORK_DETAIL` and `as_match` joins
        it, so a list here would move the reshaping to three sites instead of one.

        **The second bound is the width of the rejoin, and not a per subject
        width.** A per subject width would refuse a single long heading that is
        inside this column's stated bound, which
        `tests/routers/test_books_google.py::TestACatalogueCannotWriteWhatTheColumnsRefuse`
        pins as the deliberate answer on this path: what the bound admits is stored.
        And it is not the bound the column needs. Splitting on a bare separator and
        rejoining with the two character one **lengthens** the value, so a payload
        of exactly `CATEGORIES_MAX` carrying 31 bare separators is 32 subjects,
        inside the count, and rejoins to 3,933, which is 31 past
        `CATEGORIES_MAX`. Measured. The count alone therefore does not protect that
        bound and the rejoin width does, exactly.

        **`CATEGORIES_MAX` is a stated bound and not something the column
        enforces**: `books.categories` is `Text` and SQLite ignores a declared width
        anyway, so nothing breaks at 3,903. It is a page weight control, for the
        reason its own definition carries, and the wording here says "past the
        bound" rather than "more than the column can take" because the latter would
        be a claim about the database.
        """
        subjects = split_categories(value)
        if not subjects:
            # `split_categories` answers `[]` for None and for a string with
            # nothing in it, and `join_categories` answers None for `[]`, so an
            # empty value stays a stored NULL rather than becoming "".
            return None
        if len(subjects) > MAX_CATEGORIES_PER_BOOK:
            raise ValueError(
                f"At most {MAX_CATEGORIES_PER_BOOK} subjects, and this carries "
                f"{len(subjects)}"
            )
        # Rejoined rather than returned as parts, so what this model hands on is
        # what the column stores, and the width below is measured against that
        # rather than against what arrived. Idempotent by construction: no part
        # it returns is empty, padded, or carries the separator.
        rejoined = join_categories(subjects)
        if rejoined is not None and len(rejoined) > CATEGORIES_MAX:
            raise ValueError(
                f"These subjects are stored joined, which is {len(rejoined)} "
                f"characters against a bound of {CATEGORIES_MAX}"
            )
        return rejoined


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


#: The `books` columns a row is never allowed to be missing.
#:
#: Read off the table rather than written out, because the defect is a **pair**
#: and not either half: a field that accepts `null` in a partial update, over a
#: column that refuses one, is `UPDATE books SET title=NULL`, an `IntegrityError`
#: out of the flush, and a 500 from `errors.unhandled_exception_handler`. One
#: field is enough, and `title` was it. Derived, the next optional field added
#: over a NOT NULL column is covered on the day it is added rather than on the
#: day somebody sends it a null.
COLUMNS_THAT_REFUSE_NULL = frozenset(
    name for name, column in Book.__table__.columns.items() if not column.nullable
)


class BookDetailsUpdate(BaseModel):
    """The fields a person edits by hand after a book exists.

    Every field is optional and absent means "leave alone", so the form can
    send only what changed. An explicit `null` clears, which is how a series is
    unset; the two cases are distinguished with `model_fields_set`. A column
    that refuses null refuses the clear too: see the validator at the foot.

    **`categories` is the one field whose clear is not a null**, for the reason
    written at it, and it is the one field whose request shape is not the
    stored shape.
    """

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    subtitle: str | None = Field(default=None, max_length=SUBTITLE_MAX)
    author: str | None = Field(default=None, max_length=AUTHOR_LINE_MAX)
    publisher: str | None = Field(default=None, max_length=PUBLISHER_MAX)
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    series_name: str | None = Field(default=None, max_length=SERIES_NAME_MAX)
    series_index: float | None = Field(default=None, ge=0, le=MAX_SERIES_INDEX)
    location: str | None = Field(default=None, max_length=LOCATION_MAX)

    format: BookFormat | None = None
    condition: BookCondition | None = None
    lending: LendingWillingness | None = None
    purchase_price_minor: int | None = Field(default=None, ge=0, le=MAX_PRICE_MINOR)
    # Upper case, three letters, ISO 4217 shaped without asserting the code is
    # real: a library using a currency this app has never heard of is not an
    # error worth refusing an edit over.
    purchase_currency: str | None = Field(
        default=None, min_length=CURRENCY_LENGTH, max_length=CURRENCY_LENGTH
    )
    purchased_at: date | None = None
    purchase_source: str | None = Field(default=None, max_length=PURCHASE_SOURCE_MAX)

    #: The subjects on this book, replaced wholesale. **An empty list clears
    #: them, and this is the only removal in the product that is not deleting
    #: the book.**
    #:
    #: **Empty clears and absent leaves alone, and null is not a spelling of
    #: either.** Every other field here is `X | None` because its column holds
    #: one value and a null is how that value goes away. This one arrives as a
    #: list and is stored as one joined string, and `google_books.join_categories`
    #: already answers `None` for `[]`, so an empty list **is** the cleared
    #: column and a null beside it would be a second spelling of one act.
    #: Refused rather than accepted as a synonym: two spellings reaching one
    #: column is how the two of them eventually reach it differently, and it
    #: would also give the create body and this one different types for one
    #: field in the generated client.
    #:
    #: **The clear reaches this column and nothing else.** Not a copy already
    #: served to a public reader, not `book_tags`, not the classifications:
    #: those are separate tables behind their own doors, and a member clearing
    #: subjects should not be told more than the clear does.
    #:
    #: **Why the column needed one at all.** Three writes and no removal: the
    #: create route, the catalogue gap fill and the merge's absorb. Even an
    #: overwriting enrich cannot empty it, because `google_books.merge_into`
    #: skips an incoming value in `(None, "", [])`. And it publishes:
    #: `schemas/public.PublicBookOut` serves this field to a reader with no
    #: account, so flipping a book public and folding a private row into a
    #: public keeper each carry a subject across that boundary with no undo.
    #: The cover beside it in that payload is withheld on the ground that
    #: publishing it is a decision nobody made; a subject had the opposite
    #: treatment and no way back.
    #:
    #: Bounded exactly as `BookCreate.categories` is, and by the same two
    #: constants, so the list shaped doors onto this column cannot accept
    #: different things. `BookMatch` is bounded differently on purpose, being
    #: handed one already joined string.
    categories: list[CategoryField] = Field(
        default=[], max_length=MAX_CATEGORIES_PER_BOOK
    )

    @field_validator("categories", mode="before")
    @classmethod
    def one_subject_per_entry(cls, value: object) -> object:
        """The second door onto this column, applying the same rule.

        `normalised_subjects` holds it and the argument for it. Called rather
        than restated: a copy here would be the one that goes stale, because
        the paragraph a reader checks is the one at the older door.
        """
        return normalised_subjects(value)

    @field_validator("purchase_currency")
    @classmethod
    def upper_case_currency(cls, value: str | None) -> str | None:
        """`eur` and `EUR` are the same currency and must not sort apart."""
        return value.upper() if value else value

    @model_validator(mode="after")
    def refuse_to_clear_a_column_that_cannot_be_null(self) -> BookDetailsUpdate:
        """An explicit `null` is refused where the column behind it refuses one.

        `routers/books.update_book_details` writes every field the caller sent,
        so a null for such a column reached SQLite and came back as a 500. See
        `COLUMNS_THAT_REFUSE_NULL` for why this is derived from the table.

        **Absent still means "leave alone".** This reads `model_fields_set`, so
        it fires on a null somebody wrote and never on a field left out, which
        is the whole of what makes the update partial.

        Raising `ValueError` rather than `HTTPException`: this is body
        validation, so FastAPI answers 422 with the array of entries the schema
        declares for that status, where a hand raised refusal would send a
        sentence the schema says is an array.
        """
        cleared = sorted(
            field
            for field in self.model_fields_set
            if field in COLUMNS_THAT_REFUSE_NULL and getattr(self, field, None) is None
        )
        if cleared:
            raise ValueError(
                f"{', '.join(cleared)} cannot be cleared: send a value, or leave the "
                "field out to keep the one already stored"
            )
        return self


#: What `routers/books.update_book_details` takes out of the dump before its
#: assignment loop, for the reason `RESHAPED_FOR_ITS_COLUMN` gives.
#:
#: **The intersection of that cell with this body, not the cell whole.** The
#: two bodies carry different fields on purpose, and a name reshaped on create
#: that this one does not offer is not a fault: it is a field this door does
#: not edit. Derived, so a second reshaped column added to both bodies is
#: popped here on the day it is added rather than assigned as a list.
POPPED_BEFORE_THE_ASSIGNMENT: Final[tuple[str, ...]] = tuple(
    name for name in RESHAPED_FOR_ITS_COLUMN if name in BookDetailsUpdate.model_fields
)

#: Refused at import, the same partition read against the other door.
#:
#: **The create route had this and the update route did not, which is the
#: defect underneath the subject clear rather than the missing field.**
#: `update_book_details` assigns every field of the dump straight onto the row,
#: so a container field added to this body was not a report: measured on
#: SQLAlchemy over SQLite, assigning a list to a `Text` column raises
#: `sqlite3.ProgrammingError: Error binding parameter 1: type 'list' is not
#: supported` at the flush. That is a 500 on somebody's library rather than a
#: red on the machine of whoever added the field, which is exactly what the
#: create side's refusal was built to retire, at the door it was not written
#: for.
#:
#: No child row cell: this door writes no child tables, so the tuple is empty
#: rather than absent, which is what keeps the two arms over it live.
_UNASSIGNABLE = _unconstructable_fields(
    (),
    POPPED_BEFORE_THE_ASSIGNMENT,
    {name: field.annotation for name, field in BookDetailsUpdate.model_fields.items()},
    Book.__table__.c.keys(),
)
if _UNASSIGNABLE:
    raise RuntimeError(
        "`BookDetailsUpdate` and the update route disagree about what is "
        "assigned to the row: "
        + "; ".join(f"`{name}` {fault}" for name, fault in sorted(_UNASSIGNABLE.items()))
        + ". Every field of that body either names a column of `books` and is "
        "assigned unchanged, or is named in `RESHAPED_FOR_ITS_COLUMN` above. A "
        "name in the second of those needs an assignment at "
        "`routers/books.update_book_details` as well as the pop: a pop with no "
        "write stores nothing and answers 200."
    )


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


#: The most Books one merge may name, and therefore the most members one
#: duplicate group is allowed to show.
#:
#: **The two are one constant because they were two numbers once and the pair
#: was a dead button.** The card sends every id it renders, so a group of 21
#: rendered 21 buttons and every one of them answered 422. Reachable from a
#: catalogue import of many same titled rows sharing no copy group.
#: `tests/routers/test_books_duplicates.py::TestTheMemberCap` holds the
#: diagonal, a group one larger than this.
MERGE_BOOKS_MAX = 20

#: The most Books one duplicates answer carries, across all its groups.
#:
#: `MAX_PAGE_SIZE` rather than a number of its own: it is already this
#: repository's justified ceiling for how many Books one response may hold, and
#: a second figure here would be a second thing to argue about. Groups are
#: accumulated whole, so the answer may stop below this and never above it.
#:
#: **It is a cap and deliberately not a page.** Nothing resumes: a duplicates
#: view is a worklist whose rows the viewer is there to delete, so an offset
#: names a different group on every request, and a cursor is an address that
#: would have to refuse an invisible group and an absent one identically.
DUPLICATE_BOOKS_SHOWN = MAX_PAGE_SIZE


class DuplicateMember(BaseModel):
    """One entry in a duplicate group: what the card shows and nothing else.

    **Not a `BookOut`.** A person choosing which of two rows survives reads the
    cover, the title and what tells the two apart, which is the format, the
    publisher, the year and the ISBN. Carrying the rest cost this route a
    hydration of the whole visible shelf and a serialisation pass over every
    duplicate in it, for fields nothing rendered.

    The trade, stated so the next reader sees a decision rather than an
    omission: the card can no longer grow a field without a column here and a
    client regeneration. The fields it would want are small scalars and adding
    one is two lines.

    `copy_group` is read by the collapse and is deliberately absent: a group
    token on a payload is a fact about another member's copies.
    """

    id: int
    title: str
    format: BookFormat | None = None
    publisher: str | None = None
    year: int | None = None
    isbn: str | None = None
    cover_url: str | None = None


class DuplicateGroup(BaseModel):
    """Books that look like the same work.

    Matched on normalised title plus author rather than ISBN: an accidental
    exact repeat is already refused by `uq_books_isbn_single_copy`, and the
    case worth catching is a hardback and a paperback, which are legitimately
    two different ISBNs.

    **Deliberate copies are not duplicates and never appear here.** They share
    a `copy_group`, and the endpoint collapses each group to one row before
    deciding whether anything is left over.

    **`books` carries at least two members, refused here rather than trusted.**
    `key` is readable plaintext of the form `dune|frank herbert`, so a group
    standing on one visible row plus one the viewer cannot see would publish
    that row's title and author. The route builds groups only out of a shelf,
    which is what makes that impossible. `min_length` is the second latch:
    it fires when the group is **built**, so a future route that grouped
    before it filtered would raise here rather than answer 200.
    """

    key: str
    #: Members the grouping produced, before the member cap, so a group larger
    #: than `MERGE_BOOKS_MAX` says so rather than looking complete.
    #:
    #: **It counts rows this viewer can see, after deliberate copies are
    #: collapsed**, which is fewer than the Books behind it: three visible
    #: rows, two of them sharing a copy group, are a size of two. That is the
    #: right number for the card, because the collapsed row is not on offer.
    #: Said exactly, because "what this viewer can see" is a different and
    #: larger number and was what this line used to claim.
    size: int = Field(ge=2)
    books: list[DuplicateMember] = Field(min_length=2, max_length=MERGE_BOOKS_MAX)

    @model_validator(mode="after")
    def _the_size_is_what_the_membership_says(self) -> DuplicateGroup:
        """`size` and `len(books)` are two spellings of one fact.

        **The relation is what the card reads**, as `size - books.length`, and
        neither field's own bound constrains it: a size of 999 beside two
        members passed, and so did a size of 2 beside three, which renders a
        negative "left for a second pass". Bounding each field separately is
        not bounding the pair.

        Below the cap the two are equal, because nothing was withheld. At the
        cap the size may be larger, because that is what withholding is. There
        is no third case: `books` cannot exceed the cap.

        **The input boundary and the branch boundary are not the same
        boundary**, which is worth saying because the arms are parametrised on
        the first. Below the cap the second `if` never decides anything on its
        own: the equality above has already refused every input that reaches
        it. The only membership at which it does work alone is exactly the
        cap, which the capped arm holds. So a reader checking coverage by
        counting parameters will conclude the branch is covered from below,
        and it is not.
        """
        shown = len(self.books)
        if shown < MERGE_BOOKS_MAX and self.size != shown:
            raise ValueError(
                f"an uncapped group of {shown} cannot claim a size of {self.size}"
            )
        if self.size < shown:
            raise ValueError(
                f"a group of {shown} cannot claim a size of {self.size}"
            )
        return self


class DuplicateReport(BaseModel):
    """The duplicates worth working on, and how many there are in all.

    `groups` is capped by `DUPLICATE_BOOKS_SHOWN`. `total_groups` is not: it is
    what the scan found, so a member whose import ran twice is told the size of
    what happened instead of being handed it.

    **A count is a disclosure, and this route had never carried one.** Both
    numbers count the groups this viewer **can see**, so neither can be moved
    by a Book the viewer cannot see.

    **Can see, not owns**, and the two are separate in this data model on
    purpose. A member looking at two public Books somebody else added is
    counted one group and is offered the merge, which is intended and is what
    `merge_books` reasons about: `visible_to` yields exactly the set a caller
    may write, because a public Book is a shared shelf. This sentence used to
    say the viewer's own shelf, which reads as ownership and is the opposite
    of the rule.
    """

    groups: list[DuplicateGroup]
    total_groups: int = Field(ge=0)


class MergeRequest(BaseModel):
    """Fold several books into one.

    `keep_id` survives and must appear in `book_ids`, spelled out rather than
    inferred so a mistyped request fails instead of silently keeping whichever
    row sorted first.
    """

    book_ids: list[RowIdField] = Field(min_length=2, max_length=MERGE_BOOKS_MAX)
    keep_id: RowIdField


class OwnershipUpdate(BaseModel):
    ownership: OwnershipStatus


class BulkRequest(BaseModel):
    """One verb applied to a selection.

    `value` is deliberately loose: which field it fills depends on the action,
    and the handler validates it against that action rather than the schema
    carrying one mutually exclusive optional field per verb.
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
    `examined` is how many books the run has an outcome for, `stored` how many now
    have a cover this app serves itself, `unreachable` how many resolved to a URL
    this server could not download (so the remote link is kept and it is tried
    again on the next pass through the library, not the next run, which starts past
    it), `still_missing` how many no image service has one for, and `remaining` how
    many candidates are left beyond what this run examined.

    **`examined` is not always the whole batch.** The run is bounded in wall clock,
    so a slow or blackholing image service can leave it short; the counts then
    describe the books it reached and `next_after_id` clears exactly those. A book
    the run fetched after the cut is stored and counted in none of the three, so
    this understates what the run did and never overstates it, and that book stops
    being a candidate rather than being fetched twice.

    **Nothing here says whether a run was cut short**, for the reason
    `IdentifierBackfillOut` gives at length: the client's action is to press again
    while `remaining` is above zero, which is the same action either way, and the
    cursor is what makes pressing again safe.

    `next_after_id` is the cursor. **Without it the backfill cannot finish a
    library**: the batch is chosen by book id and a book that could not be fixed
    stays in the candidate set, so it sits at the front of every subsequent run
    for ever. About 20% of ISBNs resolve to nothing (measured across ten), so on
    a large import the counter stops moving after a few runs, and a pod with no
    egress produces it on run one. The client sends the value back to carry on
    past what it has already tried. It is the last book of the unbroken examined
    run, so a short run skips nothing it never reached, and it comes back unchanged
    where the run reached none of them.
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


class IdentifierBackfillOut(BaseModel):
    """What one run of the store identifier backfill managed.

    The same shape as `CoverBackfillOut` above, and deliberately so: it is the
    same job on a different column, so a member who has run one knows how to
    read the other and the screen draws them the same way.

    **The four outcomes are four different things to do next**, which is the
    whole reason this is not one number. `enriched` is books that gained at
    least one field. `not_found` is Google saying it has no such volume, which
    is permanent and means the identifier is stale or the book was delisted.
    `unavailable` is Google not answering, which is transient and worth pressing
    again. `unresolvable` is a stored value that is not a volume id and so was
    never asked about at all: also permanent, and **not** Google's answer, which
    is why it is not folded into `not_found`. `remaining` is how many candidates
    are left beyond this batch.

    **There is no `unchanged`, and a design critic is why.** One was declared,
    for books whose record answered and carried nothing new. It could not
    happen: a candidate is a Book with no `google_books_id`, every volume
    resource carries one, and `merge_into` writes it, so every answered book
    gains at least that field. The only body that reached it was a 200 with no
    `id`, which `google_books.lookup_by_volume_id` now refuses as not a volume.
    A count that cannot be non zero is a fact about the code stated on the wire.

    **`examined` is the sum of the four and not a fifth outcome**, so a client
    can check the arithmetic rather than trust it.

    **`examined` counts the books this run has an outcome for, which is not
    always every book it looked at.** The run is bounded in wall clock, so a slow
    or busy catalogue can leave it short. The counts then describe the books it
    reached, and `next_after_id` clears exactly those.

    **Nothing here says whether a run was cut short, and that is deliberate.** An
    earlier version of this paragraph told a client to compare `examined` against
    the batch size, which this reply does not carry and no request sets, so the
    comparison was not one a client could make. There is no flag either: a
    client's action is to press again while `remaining` is above zero, which is
    the same action whether the run was cut short or finished its batch, and the
    cursor is what makes pressing again safe. A field would also make this diverge
    from `CoverBackfillOut`, which is bounded in wall clock the same way and says
    the same nothing about it.

    A book the run resolved after the cut is stored and counted in neither
    number, so this understates what the run did and never overstates it; that
    book stops being a candidate, so the next press does not spend another
    metered request on it.

    **`remaining` counts candidates, not books this will fix.** The candidate
    query narrows on carrying a `google_books` identifier and cannot narrow on
    the identifier being shaped like one, so a library whose rows are all
    unresolvable reports them here and then reports them as `unresolvable` as
    the cursor clears them. Honest either way, and worth saying: the number is
    how much work is left, not how many books will improve.

    `next_after_id` is the cursor, and it is here for exactly the reason
    `CoverBackfillOut` carries one: a book that could not be resolved stays a
    candidate, so without a cursor it sits at the front of every subsequent run
    for ever. 0 means this run reached the end. It is the last book of the
    unbroken examined run rather than the last book of the batch, so a run cut
    short cannot skip the books it never reached, and it comes back unchanged
    where the run reached none of them.
    """

    examined: int = Field(ge=0)
    enriched: int = Field(ge=0)
    not_found: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    unresolvable: int = Field(ge=0)
    remaining: int = Field(ge=0)
    next_after_id: int = Field(ge=0)
