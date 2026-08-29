"""What a reader with no account is shown.

**This module is the column boundary, and it exists because the row filter is
not one.** `Shelf.seen_by_the_public` decides which Books a public reader may
see; it filters **rows**. A Book that is public still carries fields that are
nobody's business: what the household paid for it, which room it is in, who
added it, whether they will lend it, and whether anybody has read it. None of
that stops being private because the Book is public.

So the public payload is a **separate model with its own fields**, not `BookOut`
with an exclusion list. The difference is which way the default falls. An
exclusion list publishes every field somebody forgets to add to it, and a field
is added to `BookOut` about twice a release; a separate model publishes nothing
it was not written to publish, and the cost is that a genuinely public new field
has to be added in two places.

**The rule that decided each field**, so the next one can be decided the same
way rather than by taste: a field is public when it is a fact about the *work*
or about the *object as a catalogue record*, and withheld when it is a fact
about a member, about the household, or about the transaction that brought the
book in. `tests/schemas/test_public.py::TestEveryFieldOnBookOutIsClassified`
is what stops a new field defaulting to either answer: it fails until somebody
puts the field in one of the two lists with a reason.

Applying that rule, three placements are worth their sentence because they are
the ones a reader will query.

* **`location` is withheld**, although in library mode it is the shelf mark a
  patron needs. The column is shared with household mode, where it holds
  "bedroom", and the switch that publishes the catalogue does not change what
  is in it. Publishing a room list is not a trade this makes on a household's
  behalf. A shelf mark for patrons wants its own field.
* **`copy_count` is withheld** for a different reason, which is that it cannot
  be computed here. It counts the copies *the caller may see*, so it takes a
  viewer, and a public reader has none.
* **`id` is published, and it discloses more than an identifier.** It is the
  insert order, so the catalogue comes back in acquisition order with no `sort`
  parameter at all, and `max(id)` against the number of rows returned gives the
  count of rows that were withheld: measured on ten rows, three private and one
  trashed, `max(id) - count` is exactly 4. It stays published because it is the
  URL a record is read at, and an opaque public id is a schema change with its
  own ticket rather than a column decision. Recorded in `docs/decisions.md`
  rather than left to be discovered.
* **A locally uploaded `cover_url` is dropped**, which is narrower than
  withholding the field: see `only_a_cover_the_public_can_already_reach`.
"""

from enum import StrEnum

from pydantic import BaseModel, field_validator, model_validator

from authors import split_authors
from enums import BookFormat, BookSort, ClassificationScheme, TagCategory
from google_books import split_categories
from schemas.tag import KnownTagKey


class PublicBookSort(StrEnum):
    """How a public reader may order the catalogue.

    **A subset of `BookSort`, declared separately rather than reused**, and for
    the same reason `PublicBookOut` is a separate model rather than an exclusion
    list: an ordering is a read of the column it orders by, and it returns the
    whole ordering in one request where a filter reads the column one query at a
    time. `BookSort.NEWEST` sorts on `added_at`, which is withheld because it
    says when this household acquired the book.

    **That one member is a weaker case than it first looked, and saying so is
    the point of the paragraph.** `id` is published, `id` is the insert order,
    and `order_for` appends `Book.id.asc()` to every ordering, so acquisition
    order already comes back with no `sort` parameter at all. Excluding `NEWEST`
    therefore withholds the `added_at` **column** and not the order it implies.
    What the subset is actually for is the next member: a `BookSort` over a
    price, a condition or a location would be publicly sortable the day it was
    added.

    Declaring the subset means a member added to `BookSort` tomorrow is not
    publicly sortable until somebody puts it here.
    `tests/schemas/test_public.py::TestEveryPublicSortOrdersByAPublishedColumn`
    is the half that decides whether it should be: it compiles the clauses
    `order_for` produces and fails on any column the public payload does not
    carry, so the judgement is made against the model rather than by eye.
    """

    TITLE_ASC = "title_asc"
    TITLE_DESC = "title_desc"
    AUTHOR = "author"
    YEAR_ASC = "year_asc"
    YEAR_DESC = "year_desc"
    SERIES = "series"

    def as_book_sort(self) -> BookSort:
        """The `BookSort` this stands for, so `order_for` needs no second table.

        The member **values** are the same strings, deliberately: the subset is
        a narrowing of one vocabulary rather than a second one, and a mismatch
        would be a `ValueError` at the first request rather than a wrong order.
        """
        return BookSort(self.value)


class PublicClassificationOut(BaseModel):
    """A published scheme heading: the call number and what it was captioned.

    **Its own model rather than `ClassificationOut`**, which is the rule applied
    to `PublicTagOut` beside it and which the first draft did not apply here. A
    field added to `ClassificationOut` would otherwise reach a public reader
    with nothing failing, and the library mode epic extends classifications
    next.
    `tests/schemas/test_public.py::TestThePublicPayloadIsBuiltOnlyFromPublicModels`
    makes that structural rather than a habit: every model reachable from
    `PublicBookOut` has to be declared in this module.

    Identical to `ClassificationOut` today, and being identical is not an
    argument for sharing it. What differs is who may change it without a review.
    """

    scheme: ClassificationScheme
    number: str
    #: Absent where the source carried the number alone, which is every MARC
    #: 082. A client showing a heading has to be ready for the number by itself.
    label: str | None = None
    model_config = {"from_attributes": True}


class PublicTagOut(BaseModel):
    """A tag as a public reader sees it: the library's own word for the work.

    Narrower than `TagOut`, which also carries `is_predefined` and a
    `book_count`. Neither means anything here: one drives a delete control no
    public reader has, and the other is a count over the whole catalogue that
    would have to be recomputed against the public shelf to be true.
    """

    id: int
    name: str
    category: TagCategory
    #: So the public catalogue can show a seeded tag in the reader's own
    #: language, exactly as the signed in one does. See `TagKey`.
    key: KnownTagKey = None
    model_config = {"from_attributes": True}


class PublicBookOut(BaseModel):
    """One catalogue record, as published.

    Every field here is a fact about the work or about the object as a
    catalogue record. Nothing on it depends on who is asking, which is the
    property that makes a public response cacheable and `BookOut` not: see the
    warning at the top of `serialisation.py`.
    """

    id: int
    isbn: str | None = None
    title: str
    subtitle: str | None = None
    author: str | None = None
    #: The credit line split into the people in it, derived on every
    #: serialisation exactly as on `BookOut`, so a public card can link a name
    #: without reimplementing the separator rule.
    authors: list[str] = []
    publisher: str | None = None
    year: int | None = None
    description: str | None = None
    cover_url: str | None = None
    series_name: str | None = None
    series_index: float | None = None
    language: str | None = None
    page_count: int | None = None
    #: Paperback, hardback, ebook, audiobook. A fact about the object, and the
    #: one such fact that decides whether a patron can use it at all.
    format: BookFormat | None = None
    categories: list[str] = []
    #: This library's own vocabulary for the work.
    tags: list[PublicTagOut] = []
    #: Published scheme headings: the call number and the Classification.
    #: **This is what library mode is for**, so it is the one addition the
    #: public payload makes over a plain bibliographic record.
    classifications: list[PublicClassificationOut] = []

    model_config = {"from_attributes": True}

    @field_validator("cover_url")
    @classmethod
    def only_a_cover_the_public_can_already_reach(cls, value: str | None) -> str | None:
        """Drop a locally uploaded cover, keep a catalogue's own https URL.

        `cover_url` holds one of two things: an https URL at one of
        `covers.COVER_HOSTS`, which is already on the public internet and
        discloses nothing this response does not, or `/covers/<book id>.<ext>`,
        which is a path into **this** deployment. That path is served by
        `routers/covers.py` behind `book_for_read`, so a public reader cannot
        fetch it and a public payload that carried it would be advertising a
        broken image.

        Serving those bytes publicly is a new file route with its own
        authorization, and #95 scopes this to search and item detail. So the
        published catalogue shows a cover where a metadata source supplied one
        and none where a member uploaded one. Stated rather than hidden,
        because it is visible on the screen.
        """
        return value if value and value.startswith("https://") else None

    @field_validator("categories", mode="before")
    @classmethod
    def parse_categories(cls, value: object) -> object:
        """The stored "Fiction; Science Fiction" as a list.

        A semicolon, never a comma: Google's own category names contain commas
        ("Fiction, general"), so splitting on one shreds them. Same rule as
        `BookOut.parse_categories`, and it has to be restated rather than
        inherited because this model deliberately does not inherit.
        """
        if isinstance(value, str):
            return split_categories(value)
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def derive_authors(self) -> PublicBookOut:
        """Split the credit line every time, so the two fields cannot disagree.

        Free: a string operation on a column already loaded.
        """
        self.authors = split_authors(self.author)
        return self
