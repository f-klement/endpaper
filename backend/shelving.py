"""Which named parts of the shelf one Member may be told exist, and which they
may file a Book into.

**The reading counterpart for `collections`, and the seam this table was
missing.** A Collection carries no member anybody may read, so nothing in a row
says who may be told about it: the answer is whoever may read a Book filed in
it. That is a question about the Shelf, asked here once, rather than a clause in
each of the routes that used to read the table whole.

**Not `collections.py`, and the name is load bearing rather than a preference.**
`pyproject.toml` puts the backend root on `sys.path`, so a top level module of
that name shadows the standard library package of the same name for every
importer in the process. Measured on a throwaway tree: the failure is
`ModuleNotFoundError: No module named 'collections.abc'`, raised at the import
of an unrelated module rather than anywhere near the new file, and 99 modules
here import the real one. `filing.py` is a different word for a different thing:
it is classification sort order, and nothing in it names a collection.

**Beside `tags.Vocabulary`, not behind it.** That class's docstring offers
itself as a base for this one. The offer is declined for two reasons measured on
this tree: its counts join the `book_tags` association table where a collection
is a scalar on `books`, and it has a seeded arm that has no counterpart here,
because nothing ships a collection. What the two share is a shape, a naming
convention and an instrument, which is a convention rather than a base class.
Generalise when the third arrives and the arms have stopped moving.
"""

from typing import Self, final

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Book, Collection
from shelf import Shelf, collections_any_book_is_filed_in


@final
class Shelving:
    """The collections one Member may be told about, and file a Book into.

    One Shelving per request. Each of the three reads below is issued **lazily
    and once**, so a caller that asks nothing pays nothing, and a caller asking
    about one id pays for only the arms that id reaches.

    ## The two questions are kept apart, and here they take the same answer

    `listable` is what the server **volunteers**. `assignable` is asked about an
    id the caller **named**. `tags.Vocabulary` needs two predicates because its
    empty arm belongs to one question and not the other: a tag carrying no book
    is a transient, alive for the width of one request between minting it and
    attaching it, and a picker of a thousand names gains nothing from showing
    it.

    **For a collection the empty state is a destination rather than a gap**, so
    the arm belongs to both. A member makes "Sold" on the collections page
    before selling anything, and the only way to fill it is a picker reading
    this same list. Put the empty arm in the write question alone and the row a
    member made one request ago is gone from the page they made it on, the
    create still answers 201, and retyping the name reproduces it exactly: a
    loop rather than a recoverable state, and a false refusal no mutation sweep
    can see.

    So the two names below call one predicate, and the docstring on that
    predicate says what would separate them again.

    ## Three arms, in cost order

    1. **A Book this Member can see is filed here.** `Shelf.seen_by`, which is
       also the published count.
    2. **A deleted Book this Member may see is filed here.**
       `Shelf.trashed_by`, which is this Member's own trashed Books and every
       Member's trashed public ones. For the reason `Vocabulary` gives plus a
       stronger one: a restore reinstates the filing, so without this arm
       trashing the last Book on a shelf destroys the Member's own access to
       the shelf that Book comes back into. **Not "this Member's own trash",
       which is what this arm said until it was read against the predicate.**
       `in_trash_for` is not an ownership test and states so at its own site.
    3. **No Book at all is filed here.** Unscoped, a set of ids and never a
       count. A collection naming no Book discloses no Book.

    There is no fourth. `PREDEFINED_TAGS` makes the seeded arm safe for tags
    because the mirror publishes that list; nothing ships a collection, so
    nothing here is public by construction.

    **And no ownership arm.** `Collection.created_by_user_id` exists and is
    written, and no query in this tree reads it:
    `tests/test_house_rules.py::TestProvenanceColumnsAreNeverRead` reports any
    read of it anywhere, which makes the separation mechanical rather than
    intended, and `docs/decisions.md` records what it is for. Arm 3 covers what
    such an arm would mostly have been for, since a collection made one request
    ago carries nothing.

    ## What this does not cover, and it is not theoretical

    **A Member makes a shelf, files nothing on it, and somebody else files a
    private Book onto it.** Arm 1 fails for the author, arm 3 no longer holds
    because a Book now carries it, and the author loses a shelf they made.

    **Neither narrow nor intermittent, which is what this paragraph called it
    until it was measured.** Arm 3 admits every empty collection for every
    authenticated Member, so one request from any of them takes any empty
    collection away from everybody, its maker included. Six arms, 2026-09-30:
    an admin creates it and lists it, a Member files a private Book in, the
    admin's list is empty, the admin's rename answers 404, the admin retyping
    the name answers 201 carrying the same id, and the admin filing into that
    id answers 400.

    **That 201 then 400 pair is the "loop rather than a recoverable state" two
    sections up, verbatim**, and that loop is the argument the empty arm was
    admitted on. The arm took it off the maker of an empty shelf and handed it
    to every Member instead. The way back needs an admin, who has to retype the
    name to learn an id no list will show and then delete the row, which
    destroys the shelf rather than returning it.

    That is the price of not reading the provenance column, and it is written
    here rather than left to be discovered. Closing it is not a build seat's
    call: the ownership arm needs that column, and
    `tests/test_house_rules.py::TestProvenanceColumnsAreNeverRead` has no
    exemption slot, only the exit its own docstring names.

    ## The non monotonicity is the thing a reader will call a bug

    A collection is hidden while it holds one invisible Book and public again
    once that Book is destroyed. That reads backwards and it is correct: the
    rule tracks what there is to disclose, and when there is nothing left to
    disclose there is nothing left to withhold. The transition is observable:
    a Member watching this list sees a row vanish when a Book is filed into it
    and return when the last one is destroyed, which says a Book passed through
    a shelf whose name they can read. **State the mechanism and claim no bound
    on it**: it is the narrowest channel on the page and it is not zero.

    ## What this closes, and what it does not

    **Closed: the broadcast**, and the write. No Member learns from a page load
    that a collection exists whose Books they cannot see, and filing a Book into
    a guessed id is refused with the answer an unused id already gets.

    **Not closed: confirmation by guess, by name and by id.** The name space is
    globally unique of necessity (`uq_collections_name_folded`), `create_collection`
    answers a collision with the existing row rather than a 409, **and that row
    carries the stored spelling and not the typed one**, so a guess under the
    fold confirms the shelf and hands back its exact name; and
    `rename_collection` answers a taken name with a 409 and no row. Both need a
    different decision about the create's collision behaviour, which is a new
    status code on a route that declares 201 and is therefore a wire contract
    change and a separate ticket.

    **The residual is narrower than the tag one was and it no longer
    completes**, which is the sentence a reader of the tag rule would otherwise
    get wrong. Before this, a guessed collection name handed back the row and
    filing a Book into it then succeeded and returned the name, where the tag
    equivalent gives a row and then refuses at the attach. Now both refuse.

    **The ids stay enumerable.** `CollectionOut` publishes `id`, the column is a
    consecutive integer primary key, so a filtered list reading 1, 2, 5, 9 says
    that rows exist between them or were deleted. Narrower than a name, still a
    tell, and not closed here.
    """

    __slots__ = ("_carried", "_counts", "_db", "_trashed", "_viewer_id")

    def __init__(self, db: Session, viewer_id: int) -> None:
        self._db = db
        self._viewer_id = viewer_id
        self._counts: dict[int, int] | None = None
        self._trashed: frozenset[int] | None = None
        self._carried: frozenset[int] | None = None

    @classmethod
    def seen_by(cls, db: Session, viewer_id: int) -> Self:
        """The shelving as it looks to this Member.

        Named to be asked the way `Shelf.seen_by` and `Vocabulary.seen_by` are
        asked, because it is the same question one level out and a reader who
        knows one should not have to learn a third spelling.
        """
        return cls(db, viewer_id)

    @property
    def counts(self) -> dict[int, int]:
        """Collection id to how many of this Member's visible Books it holds.

        **Joined to `books` through the Shelf, like every other query that
        counts Books.** A raw count would publish, on a label every member can
        read, that somebody's private books exist and how many. It excludes
        trashed rows too, so deleting the last book on a shelf leaves the shelf
        reading 0 rather than claiming a book in the bin, and the trash arm
        below is what keeps the shelf itself listed while that is true.

        One grouped statement rather than a count per collection: this feeds the
        library filter, the book detail picker and the collections page, so an
        N+1 here would be an N+1 nearly everywhere.

        A collection id is absent rather than zero when nothing visible is filed
        in it, which is what makes `.get(id, 0)` the first arm below as well as
        the published count.
        """
        if self._counts is None:
            rows = (
                Shelf.seen_by(self._db, self._viewer_id)
                .select(Book.collection_id, func.count(Book.id))
                .filter(Book.collection_id.isnot(None))
                .group_by(Book.collection_id)
                .all()
            )
            self._counts = {
                collection_id: count
                for collection_id, count in rows
                if collection_id is not None
            }
        return self._counts

    def listable(self) -> list[Collection]:
        """Every collection this Member may be told exists, ordered for the client.

        Ordered case insensitively by name: "ebooks" sorting after "Zola"
        because of its first letter's byte value is the kind of ordering a
        reader reads as a bug. `func.lower` and not the stored fold, because
        this decides sort order and not uniqueness, and both orderings put
        `Ästhetik` past `z` anyway. Putting it where a German reader expects
        needs a collation. See `docs/decisions.md`.

        The table is read whole and the predicate is applied in the same
        statement's comprehension, which is what an allowlist entry can check
        and a reader can see.
        """
        return [
            row
            for row in self._db.query(Collection)
            .order_by(func.lower(Collection.name))
            .all()
            if self._may_be_told(row.id)
        ]

    def assignable(self, collection_id: int) -> bool:
        """Whether this Member may act on a collection they have named by id.

        False means 400 from the four book write doors, which is the answer an
        unknown id already gets there, and 404 from the rename, which is the
        answer an absent id already gets there. Either way the collection a
        Member may not be told about becomes indistinguishable from one that is
        not there.

        **Four callers and not five.** The delete is admin only and deliberately
        ungated, with the reason at its own site: an admin has no privilege over
        another member's private books, so refusing there would make a
        collection holding only those undeletable for good.

        **The same three arms as `listable`, and that is a result rather than a
        shortcut.** The two questions are separate names because they are
        separate questions, and the class docstring says which of the tag rule's
        arms would move if the empty case ever stopped being a destination.
        """
        return self._may_be_told(collection_id)

    def _may_be_told(self, collection_id: int) -> bool:
        """The one predicate both questions ask, three arms, in cost order.

        **In cost order and short circuiting, which is the whole statement
        budget.** Arm 1 is one grouped statement and answers for every
        collection a Member has books in, so the ordinary write path pays one
        query. Arms 2 and 3 fire only for a collection that arm did not admit.

        Keeping this one function rather than two is deliberate: two cooperating
        predicates over one question is the shape that drifts, and the seam
        between them is where the defect lands. If a later change puts the empty
        arm back into one question only, this splits, and the class docstring
        says what that change would have to be.
        """
        if self.counts.get(collection_id, 0) > 0:
            return True
        if collection_id in self._in_the_trash_this_member_sees:
            return True
        return collection_id not in self._carried_by_any_book

    @property
    def _in_the_trash_this_member_sees(self) -> frozenset[int]:
        """The collections holding a deleted Book this Member may see.

        **This Member's own trashed Books and every Member's trashed public
        ones**, which is `in_trash_for` and is stated in full there. The code
        was right and the name was wrong, in the one direction nothing would
        have caught: the arm exercising it used a private Book, which is the
        single case where "this Member's trash" and the real set agree.

        `Shelf.trashed_by` and not a flag on `seen_by`, for the reason that
        method gives: a predicate that means "on the shelf" or "in the trash"
        depending on an argument is one a caller can get backwards, and
        backwards here would answer this question over every member's trash.
        """
        if self._trashed is None:
            rows = (
                Shelf.trashed_by(self._db, self._viewer_id)
                .select(Book.collection_id)
                .filter(Book.collection_id.isnot(None))
                .distinct()
                .all()
            )
            self._trashed = frozenset(row[0] for row in rows if row[0] is not None)
        return self._trashed

    @property
    def _carried_by_any_book(self) -> frozenset[int]:
        """The collections some Book in the library is filed in, viewer or no viewer.

        The third arm's read, and the one question here that has to be
        unscoped: scoping it would answer "carries nothing" for a shelf full of
        Books this Member cannot see, which is exactly the case arm 3 exists to
        separate from an empty one. It lives in `shelf.py` with the other reads
        past a viewer rather than here, because it reads the `books` table and
        that is that module's rule whether or not the rows come back as Books;
        its docstring carries why nothing but a set of ids crosses the
        boundary.
        """
        if self._carried is None:
            self._carried = collections_any_book_is_filed_in(self._db)
        return self._carried
