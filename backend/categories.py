"""A Book's Categories: the stored form of `books.categories`, its bounds, and the
four producer policies.

A Category is a subject somebody outside this library asserted about a Book: a
publisher, a catalogue, a stranger's file. It is not a Tag (ADR 0004), so nothing
is minted from one. The column is `Text` holding the subjects joined on
`CATEGORY_SEPARATOR`, because SQLite has no array type, and the API serves it as a
list so that no client has to know the separator to read one.

**Every reader and writer of the stored form comes here**, and this module imports
nothing from the application. That is what keeps it the one home: a module that
needs the codec can always import it, so the separator never has to be spelled a
second time, and no import cycle can hold it somewhere it does not belong. In the
Google Books adapter it was one: `schemas.book` reads the codec and the adapter
takes a `BookMatch`, so either had to import the other under `TYPE_CHECKING`.
`tests/test_categories.py` refuses an application import here.

**A subject carrying the bare separator cannot be stored.** `split_categories`
splits on that character, so storing `"Fiction; general"` serves two subjects to
every reader, including the member who typed it. What a producer does about such a
subject depends on what a refusal costs it, and so there are four policies rather
than one:

1. **Refuse**, a 422, for a request body carrying a list: `BookCreate` and
   `BookDetailsUpdate`, through `schemas.book.normalised_subjects` and
   `refuse_separator`. The caller chose the value and there is somebody to tell.
2. **Split and re-bound** for the match body, one joined string: `BookMatch`,
   through `rebound_categories`. Refusing is impossible there rather than unkind,
   because a pre joined string cannot say which separator was structural and which
   was typed.
3. **Drop and cap**, logged, for a catalogue read: `google_books._volume_to_fields`
   and `catalogue.Record.as_match`, through `kept_categories` and
   `join_categories`. Nobody can retype a catalogue's value, and raising inside a
   catalogue read would lose a whole record over one subject, which is
   `classifications.bounded_headings`' arrangement for headings.
4. **Drop in the browser**, before the request is built, for the scan flow's file
   readers: `frontend/src/lib/bookRequest.ts`, `boundCategories`. The scan flow
   forwards subjects a file wrote, and the refusal at `BookCreate` would cost the
   member the book rather than the subject. The browser cannot import Python, so
   the rule is restated there and `conformance/cases/subject.json` pins the two
   sides together by behaviour.

`docs/decisions.md`, "The three doors over `books.categories`", records how the
first three were argued.
"""

import logging
from collections.abc import Iterable
from typing import Final

logger = logging.getLogger("endpaper.categories")

#: Semicolon, not comma: Google's own category names contain commas ("Fiction,
#: general"), so a comma joined list cannot be split back apart.
CATEGORY_SEPARATOR: Final = "; "

#: How many subjects one Book's list may carry, as a request states it.
#:
#: 32 because the failure modes are asymmetric: too loose costs page weight, too
#: tight drops a whole search result silently, since `routers/books._match_rows`
#: builds `BookMatch` inside a `try` that drops a **row** rather than a field. The
#: widest shape measured in this tree is 14 headings, so it clears 2.3x.
#:
#: **That is why a catalogue producer caps rather than letting the model refuse**,
#: and why the cap is `join_categories`' default rather than an argument a caller
#: has to remember to pass.
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
#: is `Text`. It is a page weight control.
#:
#: **Computed, and the separator's width is read rather than retyped**: a wider
#: separator would otherwise make this number too small, which is the unsafe
#: direction.
#: `tests/schemas/test_book.py::test_the_categories_ceiling_assumes_the_separator_it_is_derived_from`
#: pins the width with literals so this line cannot be a restatement of itself.
CATEGORIES_MAX: Final = MAX_CATEGORIES_PER_BOOK * CATEGORY_MAX + (MAX_CATEGORIES_PER_BOOK - 1) * len(
    CATEGORY_SEPARATOR
)

_BARE: Final = CATEGORY_SEPARATOR.strip()


def split_categories(value: str | None) -> list[str]:
    """The stored string as the list every reader serves.

    Splits on the **bare** separator, so a stored value never has to have been
    joined with the two character one to read back. Empty segments are dropped: a
    trailing separator is not a category.
    """
    if not value:
        return []
    return [part.strip() for part in value.split(_BARE) if part.strip()]


def kept_categories(subjects: Iterable[str], *, limit: int | None = MAX_CATEGORIES_PER_BOOK) -> list[str]:
    """Drop and cap: the subjects a catalogue supplied, as a reader would get them back.

    **Dropped rather than raised**, because this runs inside a catalogue read and
    raising would lose a whole record over one subject. Dropping loses a subject,
    which asserts nothing false; storing it would serve two.

    **Capped at `limit`**, `MAX_CATEGORIES_PER_BOOK` unless a caller says
    otherwise, because `BookMatch` refuses past that count inside a `try` that drops
    the row. `catalogue.Record.match_headings` carries the same rule one field over
    and the incident that bought it.

    **Dropped first and truncated second**: slicing to the limit before the drop
    would let separator bearing entries at the front hide good subjects behind
    them. Padding and empty entries are removed **after** the cap, so the cap
    counts what was supplied, and the result is exactly what `split_categories`
    reads back from the kept entries joined. `tests/test_categories.py` holds
    that identity, which is what lets an adapter hand on a list rather than a
    joined string.

    The trim changes no stored value today because every adapter already trims
    its labels and drops empty ones. One that handed padded labels to
    `catalogue.Record.as_match` would get a shorter join here, so `BookMatch`'s
    `max_length`, which reads the joined string as it arrives, would admit more
    than before; what is stored stays bounded by `rebound_categories`.
    """
    supplied = list(subjects)
    keepable = [subject for subject in supplied if _BARE not in subject]
    if len(keepable) != len(supplied):
        logger.info(
            "Dropped %d of %d subjects: this column stores them joined on %r, so "
            "one carrying it would read back as two",
            len(supplied) - len(keepable),
            len(supplied),
            _BARE,
        )
    if limit is not None and len(keepable) > limit:
        logger.info(
            "Kept the first %d of %d subjects: a producer's value may not exceed "
            "what the request model accepts, or the model refuses the whole row",
            limit,
            len(keepable),
        )
        keepable = keepable[:limit]
    return [subject.strip() for subject in keepable if subject.strip()]


def join_categories(subjects: Iterable[str], *, limit: int | None = MAX_CATEGORIES_PER_BOOK) -> str | None:
    """The stored form of a subject list: `kept_categories`, joined.

    None for an empty list, so a list of nothing stays a stored NULL rather than an
    empty string. Every writer of the column calls this, and for the request
    bodies the drop and the cap are no ops: their validators refused a separator
    and bounded the count before the value got here.
    """
    return CATEGORY_SEPARATOR.join(kept_categories(subjects, limit=limit)) or None


def refuse_separator(subject: str) -> str:
    """Refuse: the subject back, or `ValueError` if it carries the separator.

    The request bodies' policy. A `field_validator` raising refuses the whole
    request, which costs nothing there because the caller chose the value and is
    told why. `schemas.book.normalised_subjects` composes it into a list and
    carries the per door argument.
    """
    if _BARE in subject:
        raise ValueError(
            f"A subject may not contain {_BARE!r}, which separates subjects in "
            "storage. Send them as separate entries."
        )
    return subject


def rebound_categories(value: str | None) -> str | None:
    """Split and re-bound: one already joined string, bounded by the subjects in it.

    `BookMatch`'s policy, and it is forced rather than chosen. What arrives there is
    one joined string in which the separator is structural:
    `catalogue.Record.as_match` joins with a string containing the bare character,
    so a refusal would refuse every record carrying two or more subjects, and
    nothing about a pre joined string distinguishes a structural separator from a
    typed one. **The producer differs per path rather than per door**:
    `evidence._bounded_match` builds the model server side on `POST /enrich`,
    and `POST /api/books/{book_id}/enrich/apply` validates a body the client sent.
    So the wire shape decides, not the producer.

    **The two bounds apply after the split and never before**, which is why the
    field's own `max_length` is not enough: a pre joined string satisfies any per
    subject width at once, and 3,902 characters of `a;` is 1,951 subjects against
    the 32 the member's own door allows.

    **The second bound is the width of the rejoin, and not a per subject width.** A
    per subject width would refuse a single long heading that is inside the
    column's stated bound, which
    `tests/schemas/test_book.py::test_the_enrichment_door_stores_one_subject_the_column_can_hold`
    pins as the deliberate answer on this path. And splitting on a bare separator
    then rejoining with the two character one **lengthens** the value: a payload of
    exactly `CATEGORIES_MAX` carrying 31 bare separators is 32 subjects, inside the
    count, and rejoins to 3,933. Measured. The count alone does not protect that
    bound and the rejoin width does, exactly.

    **A correctness control, not a security control.** A hostile caller can store
    any value the column holds through any door onto it.
    """
    subjects = split_categories(value)
    if not subjects:
        # `split_categories` answers `[]` for None and for a string with nothing in
        # it, so an empty value stays a stored NULL rather than becoming "".
        return None
    if len(subjects) > MAX_CATEGORIES_PER_BOOK:
        raise ValueError(f"At most {MAX_CATEGORIES_PER_BOOK} subjects, and this carries {len(subjects)}")
    # Rejoined rather than returned as parts, so what the model hands on is what
    # the column stores, and the width below is measured against that rather than
    # against what arrived. Idempotent by construction: no part `split_categories`
    # returns is empty, padded, or carries the separator, so the join's drop and
    # cap are no ops here.
    rejoined = join_categories(subjects)
    if rejoined is not None and len(rejoined) > CATEGORIES_MAX:
        raise ValueError(
            f"These subjects are stored joined, which is {len(rejoined)} "
            f"characters against a bound of {CATEGORIES_MAX}"
        )
    return rejoined
