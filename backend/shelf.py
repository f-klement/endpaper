"""Every query that returns or counts many Books, and the only place the privacy
predicate is applied.

A Book is visible to a Member when it is on the shelf and either public or one
they added. `models.visible_to()` says that in SQL, and for most of this app's
life every listing, search, export, count and index was expected to remember to
apply it. What held that together was a test: `TestEveryBookQueryIsFiltered`
walked the AST of every backend module, tracked scopes and bindings through
`symtable`, and failed on a `query(Book)` or a `query(Book.<column>)` with no
predicate in the same statement. It had five opt-out comments and a second test
counting them.

That guard was scar tissue over a missing seam, and this module is the seam.
`dependencies.py` already owned the rule for **one** Book, which is why no
handler has written its own 404 check since; there was no counterpart for many,
which is exactly where the leaks were. `list_tags` counted Books without the
filter and disclosed which Tags existed only on somebody's Private Books.

So visibility is applied **by construction** here. There is no way to build a
many-Book query through this module that is not narrowed, and the two cases
**in this module** that must read past a viewer are two named functions at the
bottom of this file rather than a comment a reader has to notice. They are not
the only ways past a viewer in the backend: see "What this module does not own"
below, which names the third.

Narrowed, rather than narrowed to a viewer, because since 2026-08-28 there is
one constructor with no viewer: `seen_by_the_public`, for a reader who has no
account and so has no id to compare a Book's owner against. It is not an
exception to the rule and does not weaken it. It applies a **stricter**
predicate than `seen_by` (public and on the shelf, with no "or mine" arm at
all), so a request routed through it by mistake sees less rather than more, and
the property the whole design rests on is pinned by
`tests/test_shelf.py::TestThePublicShelfHasNoOwnershipArm`.

## The interface, in the order a caller meets it

    shelf = Shelf.seen_by(db, member.id)     # or trashed_by, for the trash
    shelf = Shelf.seen_by_the_public(db)     # a reader with no account
    shelf = shelf.where(Book.location == "study")
    shelf = shelf.matching(filters)          # the listing's own filter chain
    total = shelf.count()
    books = shelf.all(load=Loading.SERIALISED)
    books, total = shelf.page(paging, *order, load=Loading.SERIALISED)
    rows = shelf.select(Book.location, func.count(Book.id)).group_by(...).all()

`select()` is the way out to a query whose rows are not Books: an index, a
count grouped by something else, or a join to another table that must still be
scoped to what this Member may see. It anchors the FROM at `books` and applies
the predicate before the caller sees it, so a join is written outward from Book
rather than inward to it.

**The anchoring fixes the join direction and nothing else.** It does not stop a
caller forgetting the join: measured, `db.query(Tag.name).filter(visible_to(1))`
compiles to `FROM tags, books` and `Shelf.seen_by(db, 1).select(Tag.name)`
compiles to `FROM books, tags`, both two FROMs and both a cartesian product
SQLite answers rather than refuses. `tests/test_shelf.py` pins that limit rather
than leaving it to be discovered.

## What this module does not own

Two modules, both deliberate, both named in the house rule rather than left to
pass quietly.

`notifications.py` reads Books through `Loan` and applies no viewer predicate at
all, because there is no viewer: the overdue digest runs on a schedule for the
Library rather than for a Member, and its two halves deliberately **partition**
on privacy (`is_(False)` for the reminders, `is_(True)` for the count of what
privacy held back) rather than filter by it. A Shelf would have to be told to
mean both things at once, which is the mistake `in_trash_for` exists as a
separate function to avoid.

`backup.py` reads every row of every table, `books` included, through
`db.query(model)` on a loop variable. A backup that silently omitted everyone
else's Private Books would restore to a Library missing rows, which is the one
thing a backup must never do, so it is unfiltered on purpose and admin only for
that reason. It is also **invisible to every rule that reads the arguments to
`query()`**, this module's included, which is why the house rule asserts it
separately instead of counting on being able to see it.

## The tables that belong only to a Book

`classifications`, `custom_field_values` and `book_tags` carry a Book and no
user, so they have no viewer of their own and their privacy is entirely the
Book's. An **index** over one of them ("every DDC number in the Library, with a
count") publishes a name and a count over every Member's Private Books, which
is the `list_tags` disclosure again by a different door, and it names no `Book`
anywhere, so nothing above sees it.

`select()` is the door, **and going through it does not satisfy the guard**. It
anchors the FROM at the filtered `books` and does not supply the join, exactly
as its own docstring says: `Shelf.seen_by(db, bob).select(Classification.number,
func.count())` compiles to `FROM books, classifications` with no join
condition, and against a two-Book database Bob reads the DDC number of Alice's
Private Book.

`tests/test_shelf.py` therefore reports **every** statement that reads one of
these tables, including the two correct indexes that exist,
`routers/stats.py`'s Tag counts and `routers/books.py`'s Tag index. It used to
try to recognise a correct join instead, in five successive versions, and each
was demonstrated to leak by the next review round while the list of statements
a person had checked did not move. So the judgement is a person's and is
recorded once, in `BOOK_OWNED_READERS`, which holds ten statements across four
modules with a reason each. Writing a new query over one of these tables turns
that test red on purpose: the comment block above that list says what is being
asked.

Which tables count as children of `books` is derived from the foreign keys.
Which of those children have a viewer of their own is **pinned**, because a
foreign key to `users` does not answer it: `collections`, `author_aliases` and
`author_identifiers` each carry a `created_by_user_id` that no query consults.
A ninth child fails a test until somebody classifies it.

Not `books.added_by_user_id`, which is the opposite case and is the column
`visible_to` is built on. `books` is outside the derivation for being the
parent table.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Self

from sqlalchemy import func, nullslast, or_, select
from sqlalchemy.orm import Query, Session, joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression

import filing
from enums import (
    BookFormat,
    BookSort,
    ClassificationScheme,
    LendingWillingness,
    OwnershipStatus,
    ReadStatus,
)
from models import Book, Classification, Tag, UserBook, in_trash_for, visible_to


class Loading(Enum):
    """Which relationships to fetch with the rows, rather than per row.

    An enum rather than an options list retyped at each call site. Measured at
    `5559d16`, the `joinedload(added_by) + selectinload(tags)` pair was written
    out verbatim **six** times (`dependencies.py:69,119`,
    `routers/books.py:836,1748,2359,2515`), plus once more with
    `joinedload(Book.collection)` beside it for the export, and a seventh caller
    that forgot it got the N+1 back with no error anywhere.

    `routers/loans.py` used to write the same pair through `Loan.book` and was
    left alone, because it eager-loads from a Loan rather than from a Shelf and
    so is not a call site this enum can reach. It writes only the `added_by`
    half now: the tags half was deleted there on 2026-08-29 for the reason this
    one was deleted here a day later, and the comment above `loans.py:141`
    records that measurement.

    Statement cost, which is the number that matters and the one
    `tests/test_shelf.py` pins for each of the four:

    * `NOTHING`: one statement.
    * `SERIALISED`: one. `added_by` is a many to one and rides on the row
      itself, and nothing else is loaded.
    * `EXPORTED`: two. `collection` is another many to one, so it joins rather
      than adding a statement; `tags` is a collection and costs one more for
      the whole page, not one per Book.
    * `PUBLISHED`: three. `tags` and `classifications` are both collections and
      cost one each for the whole page, and there is no many to one to ride on
      the row: the public payload names no member, so `added_by` is not loaded.

    **`SERIALISED` deliberately does not load `tags`, and `EXPORTED` does.**
    That asymmetry is the whole of it, and what decides it is whether a second
    reader exists. No caller fetching with `SERIALISED` reads a **page** of
    tags outside `serialisation.books_to_out`, which re-reads the page with a
    `selectinload(Book.tags)` of its own, so an option here loads a collection
    that is loaded again a moment later and can never do work. The CSV export
    has no such second reader: it reads `book.tags` per row itself, so there
    the option is the only thing standing between it and an N+1.

    **The stronger sentence is false, and it was the one written here until
    2026-08-30.** "Everything fetched with `SERIALISED` is serialised by
    `books_to_out`" is falsified by **17 of the 33 routes** that reach
    `book_for_read` or `book_in_trash`, all of them in `routers/books.py` and
    nowhere else: **11** serialise a sub-resource and never the book (the
    reads and writes under notes, quotes, progress and custom fields, plus
    `GET /{id}/enrich/candidates`), **5** answer 204 and serialise nothing at
    all (`DELETE /{id}`, `DELETE /{id}/permanent`, and the note, quote and
    progress deletes), and `add_copy` serialises the **copy** rather than the
    book it read. `list_duplicates` falsifies it a second way, fetching the
    whole shelf and serialising only the rows that fell into a group.

    **Those numbers are recomputed from the routers by
    `tests/test_shelf.py::TestTheRoutesThisDocstringCounts`, and the reason is
    that two breakdowns were written before this one and both were wrong.**
    First `19` with a split of `16/2`, because the enrichment **family** has
    three routes and only `GET /{id}/enrich/candidates` fails to serialise its
    book, so counting families rather than routes gave 19 where the answer is
    17. Then `17` with a split of `14/2`, filing the note, quote and progress
    deletes as sub-resource routes. The rule that settles it is one sentence
    neither had: **a route that answers 204 serialises nothing, whether it
    hangs off a book or off a note.**

    Two critics reviewing independently agreed on the total and produced two
    different splits of it, which is why each bucket is asserted apart rather
    than summed.

    The conclusion survives all of them, and the reason is the word **page**.
    Every one of those 17 routes holds a single Book, where an eager load of one
    row's collection and a lazy read of it cost one statement each. That is why
    the measurement below shows `POST /{id}/copies` going 3 to 2 rather than
    3 to 1: the option's statement was not saved there, it was replaced. Only a
    caller that serialises a **page** by some route other than `books_to_out`
    would turn this deletion into an N+1, and there is none.

    Measured 2026-08-30 by counting the statements that read `book_tags`, at
    all six call sites, at two lengths each, by a viewer who added none of the
    books, with the owner's view taken beside it on three of the routes as a
    control (identical, because a collection load is never answered from the
    identity map). Option present to option absent: 2 to 1 on `GET /api/books`,
    `/api/books/trash`, `/api/books/duplicates` and `/api/books/{id}`; 3 to 1
    on `/api/books/{id}/copies` and `POST /api/books/{id}/restore`, which read
    the shelf twice in one request; 1 to 0 on `/api/books/{id}/notes`, which
    serialises nothing; 3 to 2 on `POST /api/books/{id}/copies` and on the
    working arm of each `/api/books/{id}/tags/{tag_id}` route, which are the
    three that read `book.tags` outside the serialiser and so replace the
    statement rather than saving it; and unchanged at 1 on
    `DELETE /api/books/{id}/permanent`, whose cascade loads the collection
    either way.

    **One arm of one route is dearer without the option, at both library sizes,
    and nothing else in thirty scenarios is.**
    `POST /api/books/{id}/tags/{tag_id}` where
    the tag is already on the book: **11 statements with the option and 12
    without**, at a library of 5 and of 25 alike. Neither of the two is a tag
    load, and that is what identifies it. The handler calls
    `db.get(Tag, tag_id)` before it reads `book.tags`, and the eager load had
    already put that Tag in the identity map, so the `get` was answered without
    a statement. The same route's working arm falls 15 to 14, and `DELETE` of
    a tag that is present is flat at 14, trading the tag load for that same
    `get`.

    So the trade is one statement on one arm of one write, against one on every
    listing the app serves. It is recorded rather than rounded away because
    "nothing rose anywhere" is what this paragraph said until a second seat
    measured the arms separately, and an absolute is the shape of claim this
    repository keeps getting wrong.

    Measured twice, in both directions, by two seats. The first run dropped the
    option; the second added it back, which is the only direction still
    available once it is gone, and reproduced every row. Neither direction is
    sufficient alone: dropping it tells a redundant eager load apart from one
    replaced by a lazy load, and adding it back proves no call site was left
    paying for a load it needed.

    A caller that serialises a page of Books by any route other than
    `books_to_out` has to load the collection itself, or it pays one statement
    per Book. That is the trap this paragraph exists to name.
    """

    NOTHING = "nothing"
    SERIALISED = "serialised"
    EXPORTED = "exported"
    PUBLISHED = "published"


_LOADING_OPTIONS: dict[Loading, tuple[Any, ...]] = {
    Loading.NOTHING: (),
    # No `tags`, deliberately: `books_to_out` re-reads every page it serialises
    # with a `selectinload(Book.tags)` of its own, so an option here is a
    # second load of the same collection. See the enum's docstring for the
    # measurement and for why EXPORTED below keeps the option it drops.
    Loading.SERIALISED: (joinedload(Book.added_by),),
    # No `added_by`, and that omission is the point rather than an economy:
    # `PublicBookOut` has no member on it, so loading the User who added a Book
    # would fetch a row nothing may render. Three statements in all: the rows,
    # then one each for the two collections.
    Loading.PUBLISHED: (
        selectinload(Book.tags),
        selectinload(Book.classifications),
    ),
    Loading.EXPORTED: (
        joinedload(Book.added_by),
        # `Book.collection` eagerly, because the CSV writes its name per row.
        # A many to one lazy load would be answered from the identity map after
        # the first Book on each shelf, so the cost is small and the reason to
        # state it is that it is not zero and not obvious.
        joinedload(Book.collection),
        selectinload(Book.tags),
    ),
}


# Annotated explicitly: without it mypy widens the heterogeneous values to
# `object`, and passing that to order_by() is an error.
_SORT_CLAUSES: dict[BookSort, UnaryExpression[Any]] = {
    BookSort.TITLE_ASC: Book.title.asc(),
    BookSort.TITLE_DESC: Book.title.desc(),
    BookSort.AUTHOR: Book.author.asc(),
    BookSort.YEAR_ASC: Book.year.asc(),
    BookSort.YEAR_DESC: Book.year.desc(),
    BookSort.NEWEST: Book.added_at.desc(),
}

# Series order needs two columns and a null rule, so it does not fit the table
# above. `nullslast` keeps the un-serialised Books together at the end instead
# of scattering them through the list wherever SQLite puts NULL.
_SERIES_ORDER: tuple[UnaryExpression[Any], ...] = (
    nullslast(Book.series_name.asc()),
    nullslast(Book.series_index.asc()),
)


def _looks_like_a_notation(number: Any) -> ColumnElement[bool]:
    """True where the first three characters are digits, which is what a Dewey
    number opens with and what makes the division projection meaningful.

    **This exists because the projection used to trust a comment.**
    `_division_key` carried "every write path goes through `ddc.notation`", and
    `ddc.notation` is called from nowhere outside `ddc.py`: `POST /api/books`
    with `{"scheme": "ddc", "number": "Hello world"}` stored it, and the facet
    then published a division `He0` whose own filter link matched nothing,
    dropped the token and returned the whole library. Both critic seats found
    that independently on 2026-08-29.

    `ClassificationIn.dewey_numbers_are_notations` now refuses that at the door,
    which is the real fix. This is the read side of it, and it is not
    redundant: a database written before that validator existed still holds
    whatever it was given, and a facet is exactly where such a row surfaces.

    Three `BETWEEN`s rather than `GLOB` or a regex, because those are SQLite's
    and this expression has no reason to know which database it is on.
    """
    return (
        func.substr(number, 1, 1).between("0", "9")
        & func.substr(number, 2, 1).between("0", "9")
        & func.substr(number, 3, 1).between("0", "9")
    )


def _division_key(number: Any) -> Any:
    """The first two digits of a Dewey number, which identify its division.

    **Two characters rather than the division itself**, so nothing has to build
    `"15" || "0"` in SQL to compare against `"150"`. A division's third
    character is always `0` by construction, so the first two carry all of it,
    and a caller comparing against `division[:2]` asks the same question with
    one fewer expression in it.

    Meaningful only on a row `_looks_like_a_notation` admits, and every caller
    here pairs the two. `ddc.division` is the Python side of the same
    projection, and `tests/test_shelf.py::TestTheDivisionProjectionsAgree`
    compares them across all 1,000 three digit numbers rather than trusting
    that they agree.
    """
    return func.substr(number, 1, 2)


def _shelf_order(scheme: ClassificationScheme) -> tuple[UnaryExpression[Any], ...]:
    """This Book's place on a shelf filed under one scheme.

    **The key is the scheme's own, and that is the whole point.** `filing.py`
    holds one rule per scheme and this asks it rather than deciding; before it
    existed there was one order, Dewey's, offered on a column that also draws
    Library of Congress numbers. `BF75` files before `BF575` on a shelf and
    after it in a string comparison, so the old order was wrong exactly where a
    cataloguer would trust it.

    A correlated subquery rather than a join, because a join would multiply the
    listing: a Book carries up to eight classifications, so joining the table to
    order by it returns that Book once per row. The count would follow, and a
    page of 25 would hold fewer than 25 Books.

    `min` because a Book may carry more than one number in one scheme, from more
    than one catalogue, and an ORDER BY needs one value per row. The lowest is
    the one a shelf would file it under. Taken over the **key** rather than over
    the stored number, so "lowest" means lowest on the shelf. For Dewey the two
    differ only on a number carrying MARC's segmentation prime, which
    `filing.DeweyFiling` removes and which `ClassificationIn` lets through, so
    every other row keeps exactly the key it had. Its **position** can still
    move, because a primed row jumping past it changes what sits above it: 53
    of 463 live K10plus 082 values carry a prime, 11.4%, measured 2026-08-23
    and recorded in `ddc.SEGMENTATION_PRIME`. For LCC the two differ on every
    row that has a class number at all.

    `nullslast` for the reason `_SERIES_ORDER` has it: a library is mostly
    unclassified until somebody enriches it, and scattering those through the
    list wherever SQLite puts NULL would make the sort look broken rather than
    partial. It covers a Book with no number in **this** scheme too, so a Dewey
    only library asked for the LCC order gets its books in one block rather than
    an error.

    **Refuses a scheme whose rule orders no shelf, at import.** Without this
    `orders_a_shelf` was a field three documents described as the mechanism and
    nothing read: giving GND a `BookSort` member and an entry in `_SHELF_SORTS`
    below would have shipped a shelf ordered by a subject vocabulary under the
    generic rule, with every test green. Two steps rather than one, because
    `BookSort` has no GND member to map; an earlier version of this sentence
    wrote `BookSort.GND` as though it did, which made the illustration an
    `AttributeError` nobody could follow. Both critic seats found the missing
    enforcement independently, and the design seat found the bad example.
    Raising here rather than in the request is deliberate, since this runs once
    while `_MULTI_COLUMN_ORDERS` is built: the failure is a broken import in
    the developer's own gate, not a 500 for a member.
    """
    rule = filing.rule_for(scheme)
    if not rule.orders_a_shelf:
        raise ValueError(
            f"{scheme.value!r} files under the {rule.name} rule, which orders no "
            "shelf. See filing.GenericFiling for why."
        )
    key = rule.sort_expression(Classification.number)
    lowest = (
        select(func.min(key))
        .where(
            Classification.book_id == Book.id,
            Classification.scheme == scheme,
        )
        .scalar_subquery()
    )
    return (nullslast(lowest.asc()),)


#: Which `BookSort` value asks for which scheme's shelf order.
#:
#: **Two tables meeting, and the test is what holds them together.** `filing`
#: says which schemes file a shelf and this says how a client asks for one, and
#: neither can derive the other: `BookSort` is the API's vocabulary and a
#: scheme is the catalogue's. `tests/test_shelf.py::TestEverySortHasAnOrdering`
#: pins that this covers `filing.SHELF_SCHEMES` exactly, so a scheme whose rule
#: starts ordering a shelf is a failing test rather than an order nobody can ask
#: for.
_SHELF_SORTS: dict[BookSort, ClassificationScheme] = {
    BookSort.DDC: ClassificationScheme.DDC,
    BookSort.LCC: ClassificationScheme.LCC,
}

#: The sorts that need more than one column. `_SORT_CLAUSES` holds one each;
#: series needs two and a null rule, and a shelf order needs a subquery. A
#: second table rather than a special case in an `if`, so a third one is an
#: entry rather than another branch. The two tables partition `BookSort` between
#: them, which `tests/test_shelf.py` pins: a value in neither raises `KeyError`
#: on a request rather than failing a test.
_MULTI_COLUMN_ORDERS: dict[BookSort, tuple[UnaryExpression[Any], ...]] = {
    BookSort.SERIES: _SERIES_ORDER,
    **{sort: _shelf_order(scheme) for sort, scheme in _SHELF_SORTS.items()},
}


def order_for(sort: BookSort) -> tuple[UnaryExpression[Any], ...]:
    """The ordering one `sort=` value asks for, with the tie broken.

    `Book.id` last so paging is stable: two Books with the same title would
    otherwise be free to swap between pages.
    """
    clauses = _MULTI_COLUMN_ORDERS.get(sort) or (_SORT_CLAUSES[sort],)
    return (*clauses, Book.id.asc())


@dataclass(frozen=True, slots=True)
class BookFilters:
    """What `GET /api/books` was asked to narrow the listing to.

    A value rather than thirteen parameters threaded through, so the filter
    chain can be applied and tested without a router, a request or a session.
    `tests/test_shelf.py` asserts that `matching()` reads every one of them, so
    a field the API accepts and the shelf ignores is a failing test.

    **`author_ids` is resolved by the caller, and that is layering rather than
    laziness.** An author is a name inside a comma separated column, and
    deciding which spellings are one person needs the alias rows, the accent
    and punctuation folding, and the case rules that all live with the author
    code. That is an identity question, not a shelf question. What reaches here
    is its answer: the Book ids that credit line resolved to.
    """

    q: str | None = None
    status: ReadStatus | None = None
    tag_ids: Sequence[int] = ()
    ownership: OwnershipStatus | None = None
    format: BookFormat | None = None
    lending: LendingWillingness | None = None
    series: str | None = None
    author_ids: Collection[int] | None = None
    location: str | None = None
    collection_id: int | None = None
    unfiled: bool = False
    unrated: bool = False
    discuss: bool = False
    #: Exact headings, each a scheme and that scheme's own identifier.
    #:
    #: A pair rather than a string, because the number alone means nothing:
    #: `004` is computing in Dewey and is not a Library of Congress call number
    #: at all. Parsed at the edge (`dependencies.headings`), so what reaches
    #: here is already a closed-enum scheme and a bounded string.
    headings: Sequence[tuple[ClassificationScheme, str]] = ()
    #: Dewey divisions, as the three digit strings `ddc.division` produces.
    ddc_divisions: Sequence[str] = ()


#: How many distinct headings the facet list will offer.
#:
#: A bound on the response rather than on the library: a book keeps every
#: heading it carries and shows them all, and this decides only how many the
#: filter panel offers to pick from. See `Shelf._heading_counts` for the
#: measurement.
#:
#: 500 because the panel is a list of chips and nobody reads a thousand of
#: them, and because at 120 characters a heading that is about 60 KB, which is
#: the same order as the listing payload beside it.
MAX_HEADING_FACETS = 500


@dataclass(frozen=True, slots=True)
class HeadingCount:
    """One distinct heading on a shelf, and how many Books carry it."""

    scheme: ClassificationScheme
    number: str
    label: str | None
    book_count: int


@dataclass(frozen=True, slots=True)
class DivisionCount:
    """One Dewey division on a shelf, and how many Books fall in it."""

    division: str
    book_count: int


class Shelf:
    """The Books one Member may see, narrowed but not yet read.

    Immutable: every narrowing returns a new Shelf, so a half-built one cannot
    be handed to two callers and mutated by one of them. The viewer is carried
    rather than re-passed, because a narrowing that took a viewer could be
    given a different one than the query was built for.

    **A Shelf may have no viewer at all**, which is what
    `seen_by_the_public` builds and is the only way that happens. `_viewer`
    rather than `_viewer_id` is what the two per-member narrowings read, and
    it raises rather than returning None: see its docstring for what the
    silent version answered.
    """

    __slots__ = ("_criteria", "_db", "_joined", "_query", "_viewer_id")

    def __init__(
        self,
        db: Session,
        query: Query[Book],
        viewer_id: int | None,
        criteria: tuple[ColumnElement[bool], ...],
        joined: bool = False,
    ) -> None:
        # Private by convention and by the absence of any other caller: the
        # three class methods below are the only ways in, and they are what
        # applies the predicate. A caller that builds one of these directly has
        # already decided to write its own privacy rule.
        self._db = db
        self._query = query
        # `int | None`, and None means there is no viewer rather than a viewer
        # whose id is unknown. Widened here and nowhere else: `seen_by` and
        # `trashed_by` still take a plain `int`, so no existing call site
        # loosens. See `seen_by_the_public` for why a sentinel id was refused.
        self._viewer_id = viewer_id
        # Kept beside the query rather than read back off it with
        # `Query.whereclause`, which returns the WHERE and **not** the FROM.
        # `select()` rebuilds a query from these, so reading them back would
        # have dropped the outer join `_with_read_status` adds and silently
        # widened the result. `_joined` is why it refuses instead.
        self._criteria = criteria
        self._joined = joined

    @classmethod
    def seen_by(cls, db: Session, viewer_id: int) -> Self:
        """The Books on the shelf that this Member may see.

        Public Books, plus their own Private ones, minus anything trashed.
        """
        predicate = visible_to(viewer_id)
        return cls(db, db.query(Book).filter(predicate), viewer_id, (predicate,))

    @classmethod
    def trashed_by(cls, db: Session, viewer_id: int) -> Self:
        """The mirror image: Books this Member may see and has trashed away.

        A separate way in rather than a flag, for the reason `in_trash_for` is
        a separate function from `visible_to`: a predicate that sometimes means
        "on the shelf" and sometimes means "in the trash" depending on an
        argument is one a caller can get backwards, and getting it backwards
        here would show every deleted Book in the Library.
        """
        predicate = in_trash_for(viewer_id)
        return cls(db, db.query(Book).filter(predicate), viewer_id, (predicate,))

    @classmethod
    def seen_by_the_public(cls, db: Session) -> Self:
        """The Books a reader with no account may see: on the shelf and public.

        **No ownership arm at all**, and that absence is the whole design.
        `visible_to(viewer_id)` is `deleted_at IS NULL AND (is_private IS false
        OR added_by_user_id = :viewer)`, and a public reader has no id to put
        in that second disjunct. Two other shapes were available and both were
        refused, 2026-08-28:

        * **A sentinel id** (`0`, `-1`). `added_by_user_id == 0` is a real
          comparison against a real column, so it is safe only while no account
          holds that id, and nothing enforces that. The leak is silent and
          answers 200.
        * **`visible_to(user_id: int | None)` with a branch inside it.** That
          loosens the type at every call site to serve one caller, and a `None`
          arriving somewhere by accident becomes a silent mode change.

        This one is safe **by construction** rather than by invariant: there is
        no value any input can take that makes a Private Book match, because
        the clause that could match one is not in the query. It fails safe in
        the other direction too, since an authenticated request wrongly routed
        through here sees **less** than it should, never more.

        It goes through the Shelf, so `TestTheShelfIsTheOnlyWayIn` keeps
        holding with no exemption and no allowlist entry. The property the rest
        of it rests on is pinned separately, by
        `tests/test_shelf.py::TestThePublicShelfHasNoOwnershipArm`.

        Nothing here decides whether the catalogue is published: that is
        `settings_store.public_catalogue_is_published`, and the router is what
        asks. This answers only which rows a public reader may be shown.
        """
        # Written out rather than composed from `visible_to`, because
        # composing it is exactly what cannot be done: this is that predicate
        # with its second disjunct removed, not that predicate with an
        # argument. `.is_(False)`, never `not Book.is_private`, which
        # evaluates the Column's Python truthiness and matches every row.
        criteria = (Book.deleted_at.is_(None), Book.is_private.is_(False))
        return cls(db, db.query(Book).filter(*criteria), None, criteria)

    @property
    def _viewer(self) -> int:
        """The Member this shelf was built for, or a refusal.

        The two per-member narrowings below read this rather than
        `_viewer_id`, and the difference is not defensiveness. With no viewer,
        `UserBook.user_id == None` compiles to `IS NULL`: the outer join in
        `_with_read_status` then matches nothing, so `status=unread` returns
        the **whole** public catalogue and every other status returns nothing,
        with no error anywhere. A wrong answer, not a failure.
        """
        if self._viewer_id is None:
            raise ValueError(
                "This shelf has no viewer, so it cannot be narrowed by one "
                "member's reading state. A public reader has no reading state."
            )
        return self._viewer_id

    def where(self, *criteria: ColumnElement[bool]) -> Shelf:
        """This shelf, narrowed further. The predicate is already on it.

        **Criteria must be over `Book`.** A clause naming another table adds it
        to the FROM of a query that joins nothing, which is the same cartesian
        product `select()` documents, on the more used method:
        `where(UserBook.rating > 3)` compiles to `FROM books, user_books`.
        Anything reaching another table wants `select()` with an explicit join,
        or a correlated exists, which is what `_unrated` and
        `_offered_for_discussion` are.
        """
        return Shelf(
            self._db,
            self._query.filter(*criteria),
            self._viewer_id,
            self._criteria + criteria,
            self._joined,
        )

    def matching(self, filters: BookFilters) -> Shelf:
        """This shelf, narrowed by everything `GET /api/books` was asked for.

        The whole chain in one place rather than inlined in a route handler,
        which is where it was and where three of these clauses carried a
        paragraph of reasoning that nothing but that handler could reach.
        """
        shelf = self

        if filters.collection_id is not None:
            shelf = shelf.where(Book.collection_id == filters.collection_id)
        if filters.unfiled:
            shelf = shelf.where(Book.collection_id.is_(None))

        if filters.ownership is not None:
            shelf = shelf.where(Book.ownership == filters.ownership)

        if filters.format is not None:
            shelf = shelf.where(Book.format == filters.format)

        if filters.lending is not None:
            shelf = shelf.where(Book.lending == filters.lending)

        if filters.series is not None:
            shelf = shelf.where(Book.series_name == filters.series)

        # One id is one bound parameter, and SQLite has a ceiling on those:
        # `SQLITE_LIMIT_VARIABLE_NUMBER`, measured per environment rather than
        # assumed, is **250,000** in the shipped image (SQLite 3.53.2) and in
        # the container the suites run in, which CI and the repository's test
        # runner pin to one digest (3.51.2). Every runtime that runs the suite
        # therefore agrees with production, and the suite can reach the
        # boundary production has.
        #
        # The one place that differs is a bare `uv run` on a developer's
        # machine: SQLite 3.50.4, **32,766**. The suites are not run there
        # anyway, but it is worth the sentence, because a
        # debugging session on this query can raise `OperationalError` at
        # 32,767 rows for a clause neither CI nor production would refuse, and
        # the obvious conclusion from that is the wrong one.
        #
        # Against a Library catalogue of a few thousand Books, of which one
        # author holds a fraction, every one of these numbers is far away. If
        # that stops being true the fix is a temporary table, not a bigger IN.
        if filters.author_ids is not None:
            shelf = shelf.where(Book.id.in_(filters.author_ids))

        if filters.location is not None:
            shelf = shelf.where(Book.location == filters.location)

        if filters.q:
            # **Escaped, and the escape character declared.** A reader searching
            # for `100%` means the four characters, and an unescaped `%` in a
            # LIKE pattern means "anything", so that search used to match every
            # title containing `100`. `_` is the same bug one character wide.
            #
            # SQLite has no default LIKE escape, so `escape=` is not optional
            # here: without it a `\%` in the pattern is a literal backslash
            # followed by a wildcard, which is the bug again with an extra
            # character. `sru.py` states the same rule at `_LIKE_ESCAPE` and
            # this is the same escape, spelled once per module because a shared
            # helper would put a search detail in a module neither owns.
            #
            # Found by the SRU work, which needed the rule for its own masks
            # and noticed this door had never had it. It is a wrong answer
            # rather than a denial of service: measured on SQLite, a pattern of
            # 400 alternating masks over 200 rows costs the same as five.
            escaped = filters.q
            for special in ("\\", "%", "_"):
                escaped = escaped.replace(special, "\\" + special)
            like = f"%{escaped}%"
            shelf = shelf.where(
                or_(
                    Book.title.ilike(like, escape="\\"),
                    Book.author.ilike(like, escape="\\"),
                    Book.isbn.ilike(like, escape="\\"),
                )
            )

        if filters.status is not None:
            shelf = shelf._with_read_status(filters.status)

        if filters.unrated:
            shelf = shelf._unrated()

        if filters.discuss:
            shelf = shelf._offered_for_discussion()

        for tag_id in filters.tag_ids:
            shelf = shelf.where(Book.tags.any(Tag.id == tag_id))

        # **Headings narrow, divisions widen, and the two are deliberately not
        # the same operator.**
        #
        # A heading is ANDed, one clause each, exactly as a tag is: asking for
        # "Mental health" and "Stress management" together means the Books
        # carrying both, and that is what selecting two chips in a filter panel
        # has always meant here.
        #
        # A division is ORed, and the reason is what a division *is*. It is a
        # shelf location, and a Book has essentially one, so ANDing two of them
        # returns only the Books carrying two Dewey numbers that fall in
        # different divisions: a question nobody means to ask. A browse facet
        # whose every multiple selection returns the empty set is worse than one
        # that disagrees with the filter beside it. Argued in
        # `docs/decisions.md`.
        for scheme, number in filters.headings:
            shelf = shelf.where(
                Book.classifications.any(
                    (Classification.scheme == scheme)
                    & (Classification.number == number)
                )
            )

        if filters.ddc_divisions:
            shelf = shelf.where(
                Book.classifications.any(
                    (Classification.scheme == ClassificationScheme.DDC)
                    & _looks_like_a_notation(Classification.number)
                    & _division_key(Classification.number).in_(
                        [division[:2] for division in filters.ddc_divisions]
                    )
                )
            )

        return shelf

    def _with_read_status(self, status: ReadStatus) -> Shelf:
        """Narrowed to the Books this viewer has put in one reading state."""
        query = self._query.join(
            UserBook,
            (UserBook.book_id == Book.id) & (UserBook.user_id == self._viewer),
            isouter=True,
        )
        if status is ReadStatus.UNREAD:
            # A Book with no row has never been touched, which is unread.
            query = query.filter(
                or_(UserBook.status == ReadStatus.UNREAD, UserBook.id.is_(None))
            )
        else:
            query = query.filter(UserBook.status == status)
        # `joined=True`, which is what makes `select()` refuse rather than
        # rebuild this narrowing without its outer join and quietly return
        # every Book again.
        return Shelf(self._db, query, self._viewer_id, self._criteria, joined=True)

    def _unrated(self) -> Shelf:
        """Narrowed to the Books this viewer has not rated.

        A separate correlated exists rather than reusing the read status join:
        that join is conditional, and depending on it here would make this
        filter silently do nothing whenever no status filter was sent.

        `correlate(Book)` is load bearing. When the status filter **has** added
        its own UserBook join, SQLAlchemy otherwise auto-correlates UserBook
        out of this subquery too, leaving it with no FROM clause at all and
        raising rather than filtering. Naming the one table to correlate
        against keeps UserBook inside the subquery where it belongs.
        """
        rated = (
            self._db.query(UserBook.id)
            .filter(UserBook.book_id == Book.id, UserBook.user_id == self._viewer)
            .filter(UserBook.rating.isnot(None))
            .correlate(Book)
        )
        return self.where(~rated.exists())

    def _offered_for_discussion(self) -> Shelf:
        """Narrowed to the Books somebody has offered to talk about.

        **Anybody's** flag, not the viewer's, which is the same choice
        `discuss_with` on the payload makes and for the same reason: the filter
        has to select exactly the Books that carry the marker the grid draws,
        or pressing it hides half of them.

        `correlate(Book)` for the reason spelled out on `_unrated`: with a
        status filter also in play, SQLAlchemy would otherwise pull UserBook
        out of this subquery and leave it with no FROM clause.
        """
        offered = (
            self._db.query(UserBook.id)
            .filter(UserBook.book_id == Book.id)
            .filter(UserBook.wants_to_discuss.is_(True))
            .correlate(Book)
        )
        return self.where(offered.exists())

    def count(self) -> int:
        """How many Books are on this shelf.

        `order_by(None)` because an ORDER BY on a count is work SQLite does and
        throws away, and because a sort clause naming a joined column would
        make the count refuse to run.
        """
        return self._query.with_entities(func.count(Book.id)).order_by(None).scalar() or 0

    def all(
        self,
        *order: UnaryExpression[Any],
        load: Loading = Loading.NOTHING,
    ) -> list[Book]:
        """Every Book on this shelf."""
        query = self._query.options(*_LOADING_OPTIONS[load])
        if order:
            query = query.order_by(*order)
        return query.all()

    def first(self, *, load: Loading = Loading.NOTHING) -> Book | None:
        """One Book from this shelf, or None.

        Used where the narrowing is an id, which is how `dependencies.py`
        resolves a single Book without writing the predicate itself. **None
        here becomes 404, never 403**: a 403 confirms the id exists, which is
        exactly what privacy withholds.
        """
        return self._query.options(*_LOADING_OPTIONS[load]).first()

    def page(
        self,
        offset: int,
        limit: int,
        *order: UnaryExpression[Any],
        load: Loading = Loading.NOTHING,
    ) -> tuple[list[Book], int]:
        """One page of this shelf, and how many Books it was cut from.

        Counted before paging: `total` is how many rows match the filters, not
        how many are on this page. Counted from the query **without** the eager
        loading options, so a `selectinload` does not issue its statement for a
        count that discards the rows.
        """
        total = self.count()
        books = (
            self._query.options(*_LOADING_OPTIONS[load])
            .order_by(*order)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return books, total

    def classification_facets(self) -> tuple[list[HeadingCount], list[DivisionCount]]:
        """Every heading on this shelf and every Dewey division, each with a count.

        **This is the query the house rule was written for.** The guard in
        `tests/test_shelf.py` names it in so many words: "every DDC number in
        the library, with a count" publishes what is on every member's Private
        Books without returning one of them. `classifications` carries no
        member, so nothing about a row says who may see it, and a facet list
        built with a bare `db.query` would disclose the subject headings of
        other people's private reading. Built through `select()`, so the
        viewer's predicate is applied by construction.

        Two lists rather than two methods, because they are drawn in one panel
        and a caller wanting one always wants the other. Two statements, not
        one: a division count is not derivable from the heading counts, for the
        reason on `_division_counts`.
        """
        return self._heading_counts(), self._division_counts()

    def _heading_counts(self) -> list[HeadingCount]:
        """The most carried headings on this shelf, with how many Books carry each.

        Grouped on scheme and number and **not** on label, with the caption
        picked with `max`. The unique constraint is on book, scheme and number,
        so a caption is per Book rather than per heading: two catalogues can
        supply the same GND number with different words, and grouping on the
        label as well would split one heading into two facet rows carrying one
        Book each. `max` is a representative rather than a judgement, and the
        halves it chooses between are the same assertion.

        A plain `count` rather than a count of distinct Books, because that same
        constraint makes one row per Book per heading already.

        **Capped, unlike `/tags` and `/locations`, and the difference is real
        rather than an oversight.** Those two are bounded by what people write:
        a curated vocabulary of about a hundred tags, and however many shelves a
        house has. This is bounded by what catalogues supply, which is up to
        eight rows per book of up to 120 characters. Against the constants in
        this tree and the per record rates measured on 2026-08-24 (2.03 LCSH per
        Library of Congress record, 2.9 GND per DNB record), a 5,000 book
        library reaches 40,000 rows and roughly 13 MB in one uncached response.
        That is a panel nobody can use as well as a payload nobody should send.

        **Ordered by count to choose what survives the cap**, which is the one
        ordering that makes a truncated facet list still worth having: the
        headings most of the library shares are the ones worth offering as a
        filter, and a heading on one book is reachable from that book. `number`
        breaks the tie so the cap is deterministic rather than SQLite's choice.
        Presentation order is the caller's and the router re-sorts.
        """
        rows = (
            self.select(
                Classification.scheme,
                Classification.number,
                func.max(Classification.label),
                func.count(Classification.book_id).label("book_count"),
            )
            .join(Classification, Classification.book_id == Book.id)
            .group_by(Classification.scheme, Classification.number)
            .order_by(func.count(Classification.book_id).desc(), Classification.number)
            .limit(MAX_HEADING_FACETS)
            .all()
        )
        return [
            HeadingCount(
                scheme=ClassificationScheme(scheme),
                number=number,
                label=label,
                book_count=count,
            )
            for scheme, number, label, count in rows
        ]

    def _division_counts(self) -> list[DivisionCount]:
        """Dewey divisions on this shelf, with how many Books fall in each.

        **`count(distinct book_id)`, and the distinct is load bearing.** A Book
        classified at both `004` and `005.133` carries two rows that project to
        the same division, and counting the rows would report it as two Books.
        That is also why this cannot be summed out of `_heading_counts`: those
        counts are per heading, and adding them double counts exactly the Books
        a catalogue described most precisely.
        """
        rows = (
            self.select(
                _division_key(Classification.number),
                func.count(func.distinct(Classification.book_id)),
            )
            .join(Classification, Classification.book_id == Book.id)
            .filter(
                Classification.scheme == ClassificationScheme.DDC,
                _looks_like_a_notation(Classification.number),
            )
            .group_by(_division_key(Classification.number))
            .all()
        )
        return [
            DivisionCount(division=f"{key}0", book_count=count) for key, count in rows
        ]

    def select(self, *columns: Any) -> Query[Any]:
        """A query over other columns, already narrowed to this shelf.

        For the rows that are not Books: an author index, a location list, a
        series list, a Tag count, a page of Quotes. Every one of those
        publishes a name and a count, which is a disclosure rather than a slow
        query, and which is why they need this rather than a bare `db.query`.

        **The FROM is anchored at `books`**, so a join is written outward from
        Book (`select(...).join(book_tags, book_tags.c.book_id == Book.id)`)
        rather than inward to it.

        That fixes the direction and **not** the presence of the join. A caller
        that names another table and forgets to join it still gets a cartesian
        product: measured, this method with no join compiles to `FROM books,
        tags`, two FROMs, exactly as the bare `db.query(...)` it replaced did.
        Stated because a seam that is silent about its limit gets read as
        having none.

        Ordering, grouping and further filtering are the caller's: they are
        presentation, and there is nothing about them this module knows.

        **Refused on a shelf narrowed by read status**, which is the one
        narrowing that adds a join rather than a clause. Rebuilding from the
        clauses alone would drop that join and hand back every Book on the
        shelf instead of the unread ones, which is a wrong answer rather than
        an error. No caller needs both today; the guard is here so that the
        first one that does gets an exception rather than a listing.
        """
        if self._joined:
            raise ValueError(
                "select() cannot rebuild a shelf narrowed by read status: that "
                "narrowing is a join, and only its clauses are carried here"
            )
        # `cast` because `Session.query` is overloaded per column arity and a
        # `*args` call resolves to the untyped fallback. The rows a caller gets
        # back are therefore `Any`, which is what the one `.tuples()` call site
        # (`authorship.py`, the author index) narrows explicitly rather than
        # trusting.
        query: Query[Any] = self._db.query(*columns).select_from(Book)
        return query.filter(*self._criteria)


def whole_table_for_uniqueness(db: Session, *columns: Any) -> Query[Any]:
    """Every row in `books`, invisible ones included, for a uniqueness check.

    **This is not an escape hatch, it is a different rule.** The ISBN is unique
    across the whole table and so is a copy group token, so a clash with a Book
    the caller cannot see is still a clash. Filtering these would miss the row
    that is actually going to collide and turn a 409 into a 500, or clear a
    group token another Member's Private copy still needs.

    It sees **trashed** rows too, which is the trap soft deletion introduces:
    a number is held by a Book in the bin until that Book is purged.

    Four callers, all of them writes deciding whether a value is already taken:
    the ISBN walk in `_create_book`, the two halves of the copy group check in
    `_normalise_copy_group`, and the import's `taken_isbns`. A fifth would be
    worth a hard look, because "I need to see everything" is what somebody
    writes just before disclosing everything, and
    `tests/test_shelf.py::test_the_named_ways_past_a_viewer_have_the_callers_they_claim`
    is what makes adding one a decision rather than an edit.

    Named rather than a comment because a comment is something a reader has to
    notice. The five `# visible_to exempt:` comments this replaced were audited
    by a test that counted them, which is the shape of a rule nothing owns.
    """
    query: Query[Any] = db.query(*(columns or (Book,)))
    return query


def rereading_filtered_rows(db: Session, book_ids: Collection[int]) -> Query[Book]:
    """The Books at these ids, unfiltered, to populate relationships on rows a
    caller already has in hand.

    **Not a visibility question.** These ids came out of a query that applied
    the predicate, and this re-reads the same rows to fill a collection on the
    objects already loaded. Filtering here would answer a question nobody
    asked, and it takes ids rather than arbitrary criteria so it cannot quietly
    become a way to read the table.

    One caller: `serialisation.books_to_out`.
    """
    return db.query(Book).filter(Book.id.in_(book_ids))
