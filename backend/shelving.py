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

**The collection arm of `disclosure.Disclosure`**, which owns the rule, its
three reads and their order for every vocabulary. A collection adds no arm of
its own: nothing ships one, so nothing here is public by construction, and no
query reads who made it.
"""

from typing import Self, final

from sqlalchemy import func
from sqlalchemy.orm import Session

from disclosure import Carrier, Disclosure
from models import Collection


@final
class Shelving:
    """The collections one Member may be told about, and file a Book into.

    One Shelving per request, holding one `disclosure.Disclosure`.

    ## The two questions are kept apart, and here they take the same answer

    `listable` is what the server **volunteers**. `resolve` is asked about an
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

    So both names below ask `Disclosure.may_be_told`, and `resolve` says what
    would separate them again.

    ## The arms are `disclosure.Disclosure`'s

    A Book this Member can see is filed here; a deleted Book this Member may see
    is filed here; no Book at all is filed here. The second is stronger here
    than for a tag: a restore reinstates the filing, so without it trashing the
    last Book on a shelf destroys the Member's own access to the shelf that Book
    comes back into.

    No arm of its own. `PREDEFINED_TAGS` makes the seeded arm safe for tags
    because the mirror publishes that list; nothing ships a collection, so
    nothing here is public by construction.

    **And no ownership arm.** `Collection.created_by_user_id` exists and is
    written, and no query in this tree reads it except the archive:
    `tests/test_house_rules.py::TestProvenanceColumnsAreNeverRead` reports a
    read of it written in a module of the application corpus, and a Pydantic
    field named for it on any model that corpus defines, which makes the
    separation mechanical rather than intended for those two shapes.

    **The archive is the exception, because a whole table serialiser names no
    column.** `backup.py` selects every column of every table it archives, so
    the value is in the archive and past both instruments. The archive is
    admin only for that reason, which `docs/security.md` records.

    `docs/decisions.md` records what the column is for. The empty arm covers
    what such an arm would mostly have been for, since a collection made one
    request ago carries nothing.

    ## What this does not cover, and it is not theoretical

    **A Member makes a shelf, files nothing on it, and somebody else files a
    private Book onto it.** The visible arm fails for the author, the empty arm
    no longer holds because a Book now carries it, and the author loses a shelf
    they made.

    **Neither narrow nor intermittent, which is what this paragraph called it
    until it was measured.** The empty arm admits every empty collection for
    every authenticated Member, so one request from any of them takes any empty
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

    __slots__ = ("_db", "_rule")

    def __init__(self, db: Session, viewer_id: int) -> None:
        self._db = db
        self._rule = Disclosure.seen_by(db, viewer_id, Carrier.COLLECTION)

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

        **Through the Shelf, like every other query that counts Books.** A raw
        count would publish, on a label every member can read, that somebody's
        private books exist and how many. It excludes trashed rows too, so
        deleting the last book on a shelf leaves the shelf reading 0 rather than
        claiming a book in the bin, and the trash arm is what keeps the shelf
        itself listed while that is true. One grouped statement, because this
        feeds the library filter, the book detail picker and the collections
        page. Absent rather than zero when nothing visible is filed in it.
        """
        return self._rule.counts

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
            for row in self._db.query(Collection).order_by(func.lower(Collection.name)).all()
            if self._rule.may_be_told(row.id)
        ]

    def resolve(self, collection_id: int) -> Collection | None:
        """The collection at this id, or None for an id no row carries and for
        one this Member may not be told about alike.

        None means 400 from the four book write doors, which is the answer an
        unknown id already gets there, and 404 from the rename, which is the
        answer an absent id already gets there.

        **Four callers and not five.** The delete is admin only and deliberately
        ungated, with the reason at its own site: an admin has no privilege over
        another member's private books, so refusing there would make a
        collection holding only those undeletable for good.

        **The same arms as `listable`, and that is a result rather than a
        shortcut**: the class docstring says which of the tag rule's arms would
        move if the empty case ever stopped being a destination.
        """
        return self._rule.resolve(collection_id, self._row)

    def _row(self, collection_id: int) -> Collection | None:
        """The read `resolve` hands the rule, which asks it after the gate."""
        return self._db.get(Collection, collection_id)
