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
many-Book query through this module that is not narrowed to a viewer, and the
two cases **in this module** that must read past a viewer are two named
functions at the bottom of this file rather than a comment a reader has to
notice. They are not the only ways past a viewer in the backend: see "What this
module does not own" below, which names the third.

## The interface, in the order a caller meets it

    shelf = Shelf.seen_by(db, member.id)     # or trashed_by, for the trash
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
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Self

from sqlalchemy import func, nullslast, or_
from sqlalchemy.orm import Query, Session, joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression

from enums import BookFormat, BookSort, LendingWillingness, OwnershipStatus, ReadStatus
from models import Book, Tag, UserBook, in_trash_for, visible_to


class Loading(Enum):
    """Which relationships to fetch with the rows, rather than per row.

    An enum rather than an options list retyped at each call site. Measured at
    `5559d16`, the `joinedload(added_by) + selectinload(tags)` pair was written
    out verbatim **six** times (`dependencies.py:69,119`,
    `routers/books.py:836,1748,2359,2515`), plus once more with
    `joinedload(Book.collection)` beside it for the export, and a seventh caller
    that forgot it got the N+1 back with no error anywhere.

    `routers/loans.py:111` writes the same pair through `Loan.book` and is left
    alone: it eager-loads from a Loan rather than from a Shelf, so it is not a
    call site this enum can reach. Seven of eight, not eight of eight.

    Statement cost, which is the number that matters and the one
    `tests/test_shelf.py` pins for each of the three:

    * `NOTHING`: one statement.
    * `SERIALISED`: two. `added_by` is a many to one and rides on the row
      itself; `tags` is a collection and costs one more for the whole page,
      not one per Book.
    * `EXPORTED`: two as well. `collection` is another many to one, so it
      joins rather than adding a statement.
    """

    NOTHING = "nothing"
    SERIALISED = "serialised"
    EXPORTED = "exported"


_LOADING_OPTIONS: dict[Loading, tuple[Any, ...]] = {
    Loading.NOTHING: (),
    Loading.SERIALISED: (joinedload(Book.added_by), selectinload(Book.tags)),
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


def order_for(sort: BookSort) -> tuple[UnaryExpression[Any], ...]:
    """The ordering one `sort=` value asks for, with the tie broken.

    `Book.id` last so paging is stable: two Books with the same title would
    otherwise be free to swap between pages.
    """
    clauses = _SERIES_ORDER if sort is BookSort.SERIES else (_SORT_CLAUSES[sort],)
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


class Shelf:
    """The Books one Member may see, narrowed but not yet read.

    Immutable: every narrowing returns a new Shelf, so a half-built one cannot
    be handed to two callers and mutated by one of them. The viewer is carried
    rather than re-passed, because a narrowing that took a viewer could be
    given a different one than the query was built for.
    """

    __slots__ = ("_criteria", "_db", "_joined", "_query", "_viewer_id")

    def __init__(
        self,
        db: Session,
        query: Query[Book],
        viewer_id: int,
        criteria: tuple[ColumnElement[bool], ...],
        joined: bool = False,
    ) -> None:
        # Private by convention and by the absence of any other caller: the two
        # class methods below are the only ways in, and they are what applies
        # the predicate. A caller that builds one of these directly has already
        # decided to write its own privacy rule.
        self._db = db
        self._query = query
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
        # machine: SQLite 3.50.4, **32,766**. `CLAUDE.md` forbids running the
        # suites there anyway, but it is worth the sentence, because a
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
            like = f"%{filters.q}%"
            shelf = shelf.where(
                or_(Book.title.ilike(like), Book.author.ilike(like), Book.isbn.ilike(like))
            )

        if filters.status is not None:
            shelf = shelf._with_read_status(filters.status)

        if filters.unrated:
            shelf = shelf._unrated()

        if filters.discuss:
            shelf = shelf._offered_for_discussion()

        for tag_id in filters.tag_ids:
            shelf = shelf.where(Book.tags.any(Tag.id == tag_id))

        return shelf

    def _with_read_status(self, status: ReadStatus) -> Shelf:
        """Narrowed to the Books this viewer has put in one reading state."""
        query = self._query.join(
            UserBook,
            (UserBook.book_id == Book.id) & (UserBook.user_id == self._viewer_id),
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
            .filter(UserBook.book_id == Book.id, UserBook.user_id == self._viewer_id)
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
