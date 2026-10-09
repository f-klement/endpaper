"""Deciding a tag from a name, how many one Book may carry, and who may be told
one exists.

One rule and every writer. `Mint` answers a name with the Tag the Library
already has or mints the one it does not; `Naming` is that answer with a
viewer on it, which is what a writer handed a name somebody typed asks;
`attach` puts a Tag on a Book without ever exceeding `MAX_TAGS_PER_BOOK`. The
one other module that decides a tag is `main.py`, for the seeded vocabulary.
`tests/test_tags.py::TestNothingElseDecidesATagFromAName` is what says so, over
every module under `backend/` but the tests and the generated migrations, and it
states what its two instruments do not see.

**And one rule and every reader**, which is `Vocabulary` and is newer than the
rest of this file. The writes had an owner and the reads had none, and a
vocabulary any member can extend, read by anybody with no viewer in the
question, published the name of a tag minted off somebody's Private Book on
every page load. `Vocabulary` is where that question is answered now; its own
docstring carries what it closes and what it leaves open, and
`tests/test_tags.py::TestNothingElseDecidesWhoMaySeeATag` is the counterpart
guard, over the same corpus and with the same instrument as the shelf rule.

**"Decides", not "writes", and the eight letters are the whole difference.**
A write that constructs nothing is a write no guard reading constructions can
see: `bulk_insert_mappings(Tag, ...)` and `db.execute(Tag.__table__.insert(), ...)`
each put a name in this table without ever calling the model. That is the
family, and it is stated rather than armed. Its one live member decides nothing
either, which is a separate fact: `backup.restore` reinserts an archive's own
rows, names included, so it is a deliberate non minter like the seeder rather
than an instance of the hole.

**A module rather than two hand converged copies, which is what this was.**
`routers/books.create_tag` and `importing.Import._apply_tags` each resolved a
name against the whole table, each folded in Python on both sides for the same
measured reason, and each docstring pointed at the other saying so. Two copies
of one rule is the state a third copy makes permanent, and these two had already
disagreed once while both claiming to agree: `_first_wins` carries that pair.

**The fold is Python's on both sides, never the database's.** SQLite's `lower()`
is ASCII only: measured, `lower('Ästhetik')` is `'Ästhetik'` there and
`'ästhetik'` here, so a stored Tag carrying a non-ASCII capital never matched,
the insert then hit the binary `unique=True` on `tags.name` with a name already
present, and the two callers paid differently for it. The route answered **500**
to `{"name": "Ästhetik"}` whenever that tag existed; the import raised
`IntegrityError` and **took the whole file with it**, so a member with one German
shelf name imported nothing, every time.
`tests/test_house_rules.py::TestNoDatabaseFoldIsComparedAgainstAPythonFold` is
the guard, and `docs/decisions.md` carries the reasoning under "SQLite folds case
in ASCII and Python does not".

**Nothing here commits, and that is the one thing about this module's shape that
is not negotiable.** `create_tag` commits and an import must not: `Import.apply`
commits once at the end of the file, so a commit in the middle of five thousand
rows is a half applied import with no way back. The commit therefore stays with
the caller, which is also what lets a create path mint a tag inside the Book's
own transaction.

**`attach` queries for no Book**: it takes one somebody else resolved, and the
privacy rule is `shelf.py`'s, applied before that Book reaches this function.
**`Vocabulary` does query, through `Shelf`**, and that is the second half of
this module rather than an exception to the first: who may be told a tag exists
is a question about the Books carrying it, so it cannot be answered without
asking the Shelf. This file therefore carries entries in
`tests/test_shelf.py`'s fourth pass, one per statement, where it used to carry
none.
"""

import logging
from collections.abc import Iterable
from typing import Final, Self, final

from sqlalchemy import func
from sqlalchemy.orm import Session

from enums import TagCategory
from models import Book, Tag, book_tags
from schemas.common import one_line_without_invisible_characters
from schemas.tag import MAX_TAG_NAME, known_key
from shelf import Shelf

logger = logging.getLogger("endpaper.tags")


#: Tags one Book may carry. Past this the picker on that Book is unusable and
#: the extra names are somebody else's filing system, not this shelf's.
#:
#: **Counted against the Book by every writer that adds one**, which is what
#: makes it a per Book number at all. It lived in `csv_import.py` and bound
#: exactly one writer, the CSV importer: measured, a 12 KB file of 200 rows
#: created 4032 Library wide tags and put 4000 of them on one Book, and with the
#: cap on the importer alone those same 4000 stayed reachable through
#: `POST /api/books/{book_id}/tags/{tag_id}`, one request at a time.
#:
#: **Three writers pass it, and none of them is somebody naming a tag.**
#: `folding._union_tags` carries a merged Book's list onto the keeper, the copy
#: route gives a new copy the source Book's list, and `backup.restore` reinserts
#: an archive's associations. Each reproduces a filing that already existed, so a
#: drop there loses a name rather than stopping one arriving.
MAX_TAGS_PER_BOOK: Final = 50

#: Distinct tags one Mint may invent. Measured on the file above: the cap stops
#: inventing rather than failing the import, because the Books in the file are
#: still worth having.
#:
#: **A budget a caller passes rather than a number this module applies**, so
#: that spending it is the import's business and a member typing one name into
#: the route is never refused by an import's history. `Mint` takes no budget by
#: default and the import is the only caller that passes this one.
MAX_NEW_TAGS_PER_IMPORT: Final = 200


def folded(name: str) -> str:
    """The key on which two tag names are one tag.

    `str.lower` and deliberately not `str.casefold`. The stored column is
    `unique=True` and binary, so this decides only which names this module
    treats as the same tag, and widening it to casefold would fold `Straße` onto
    `STRASSE` in a library holding both rows today. That is a data change and
    needs a migration, not an edit here.
    """
    return name.lower()


def tidy(raw: str) -> str | None:
    """The name as it will be stored, or None for one that normalises to nothing.

    **One normalisation for every writer, which is the asymmetry this module
    removes.** `TagCreate.tidy` ran `one_line_without_invisible_characters`
    because `"Fiction\\x00"` beside `"Fiction"` is two rows a member reads as
    one; `importing._apply_tags` ran `raw[:MAX_TAG_NAME]` with no normaliser and
    `csv_import._split_tags` only strips whitespace, so an upload could mint a
    tag the route would have refused.

    **What that normaliser removes is the control characters that are not
    whitespace, and no more.** A zero width space and a joiner survive it, which
    is a decision rather than a gap: a name in Arabic and Indic scripts carries a
    joiner, so removing one would change what somebody's name says.
    `schemas/common._CONTROL_CHARACTERS` is where that is argued and is the one
    place to change it.

    Normalised **before** the truncation, because the normaliser only ever
    shortens: truncating first cuts at a hundred characters and then hands back
    ninety eight. The cut can leave the trailing space the normaliser had just
    removed, so the ends are trimmed again after it.

    The truncation is the importer's need and costs the route nothing, since
    `TagCreate` refuses a longer name at the door.
    """
    return one_line_without_invisible_characters(raw)[:MAX_TAG_NAME].strip() or None


def _first_wins(rows: Iterable[Tag]) -> dict[str, Tag]:
    """Folded name to Tag, keeping the **lowest id** where two rows collide.

    A case differing pair is reachable on any database that met the fold defect
    above, because the route that had it created exactly that pair: the lookup
    missed and the binary index allowed both. So which of the two answers is not
    hypothetical, and before this module the two writers gave different answers.

    **Stability is not what decides it, and that is the trap.** A dict
    comprehension over the same `order_by(Tag.id)` is equally stable and keeps
    the **last** key written. Measured on a pair at ids 106 and 107: the import
    resolved it to 107 and the route to 106, while both docstrings claimed the
    ordering was what made them agree. `setdefault` is the half that makes the
    claim true.

    The lowest id is the row the Library has had longest, and the one Books
    tagged before the split are joined to. **Not the one every Book carrying
    that name is joined to**: a Book tagged through the broken route was joined
    to the second row, which is what the split was.
    """
    index: dict[str, Tag] = {}
    for tag in rows:
        index.setdefault(folded(tag.name), tag)
    return index


@final
class Mint:
    """Every Tag this Library gains, and the index each one is deduplicated against.

    **`@final`, and it is load bearing rather than documentation.** `_index`
    is the whole tag table with no viewer, and what keeps that safe is that no
    name leaves this class:
    `tests/test_tags.py::TestNothingElseDecidesWhoMaySeeATag` enforces it by
    refusing any module outside this file that names the private state **on
    another object**, which lets a class reach its own `self._x` and is the
    only formulation that stays green, since `_db` is an ordinary private
    field name four other modules carry. A **subclass** reaching its own state
    writes `self._index` and inherits the slot, so it is reaching into a Mint
    through a receiver that rule must allow. Measured: a subclass in a router
    with a route over its rows passed the whole suite and served a member a
    tag off somebody else's private book.

    So subclassing is refused here, by the type checker the gate already runs,
    which closes the routes an `ast` walk cannot resolve as well: a class built
    by `type(...)`, and a subclass declared through an alias in another module.
    **Removing this decorator reopens that hole silently**, because the arm
    that would have caught it is the one this makes safe.

    One Mint per unit of work: a request, or an import. Within it the index is
    read **once**, on first use, and the reason is correctness before it is cost.
    The per name query it replaced was `func.lower(Tag.name) == key` against a
    key folded in Python, which is the module docstring's subject. That it also
    turns one query per unseen name into one query per import is the smaller
    half: a five hundred row export shares a handful of tags and looked each one
    up per row.

    **Read lazily**, so a caller that resolves no name pays nothing: an import
    told not to apply tags asks for none and issues no query, with no branch at
    the call site to keep in step with that.
    """

    # **Load bearing twice, and the second reason is the one that gets
    # deleted.** Beyond the memory it saves, this is what leaves an instance
    # with no `__dict__`, and `_index` is the whole tag table with no viewer.
    # Without this line `vars(mint)` hands that index to any caller holding a
    # Mint, spelling no attribute, so the rule in
    # `tests/test_tags.py::TestNothingElseDecidesWhoMaySeeATag` cannot see it
    # and `@final` does not help: neither needs a subclass. Measured.
    __slots__ = ("_budget", "_db", "_index", "minted")

    def __init__(self, db: Session, *, budget: int | None = None) -> None:
        self._db = db
        self._budget = budget
        self._index: dict[str, Tag] | None = None
        #: How many rows this Mint has inserted. The budget is spent against it.
        self.minted = 0

    @property
    def _by_folded_name(self) -> dict[str, Tag]:
        if self._index is None:
            self._index = _first_wins(self._db.query(Tag).order_by(Tag.id).all())
        return self._index

    def get_or_mint(self, raw: str) -> Tag | None:
        """That Tag, minting it if the Library has none. **Never commits.**

        None for a name that normalises to nothing, and None for one this Mint
        has no budget left to invent. **The caller is not told which**, because
        neither answer leaves it with a Tag and the two callers act the same way
        on both: the import moves to the next name and the route has a schema in
        front of it that refuses an empty name before this is reached.

        Flushed rather than committed, because the caller needs the id: `attach`
        deduplicates on it, and a row with no id yet compares equal to every
        other row with no id yet.

        **The match takes no viewer, and scoping it is the one repair that
        cannot be built here.** A name the viewer may not see would miss, fall
        to the minting branch below, and insert a name `tags.name` already
        holds: the column is `unique=True` and binary, so the insert raises
        inside the import's single commit and **takes the whole upload**, which
        is the incident this module's own docstring records. A guess differing
        only in case instead **succeeds**, and the Library gains the split pair
        `_first_wins` exists to repair. Both outcomes are worse than the one
        being repaired and neither withholds anything, since `create_tag`
        answers that same name with that same row in one request.

        So the viewer arrives one step later, on the decision to hand a matched
        Tag to a writer, which is `Naming`. Written here because the premise has
        arrived as a ticket twice.
        """
        name = tidy(raw)
        if name is None:
            return None

        key = folded(name)
        tag = self._by_folded_name.get(key)
        if tag is not None:
            return tag

        if self._budget is not None and self.minted >= self._budget:
            logger.info("Already invented %d tags; not minting %r", self.minted, name)
            return None

        tag = Tag(name=name, category=TagCategory.CUSTOM, is_predefined=False)
        self._db.add(tag)
        self._db.flush()
        self.minted += 1
        self._by_folded_name[key] = tag
        return tag


class Vocabulary:
    """Which Tags one Member may be told about, and which they may put on a Book.

    **The reading counterpart of `Mint`, and the seam this module was missing.**
    A Tag carries no member and `tags` has no foreign key to `books`, so nothing
    in a row says who may read it: the answer is whoever may read a Book that
    carries it. That is a question about the Shelf, asked here once, rather than
    a clause in each of the six routes that used to read the table whole.

    One Vocabulary per request. The Shelf query is read **lazily and once**, so
    a caller that asks nothing pays nothing, and the two questions below share
    it rather than each issuing their own.

    ## The two questions are different, and collapsing them was the trap

    `listable` is what the server **volunteers**: it hands back names nobody
    asked for, so the bar is that the name is already legible to this viewer.
    `writable` is asked about a Tag the caller **named by id**, so the bar is
    only that answering does not confirm a name they could not otherwise reach.

    One predicate cannot serve both. `listable` must hide a Tag no Book
    carries, because a name on nothing is a name and nothing else. `writable`
    must allow one, because a Tag just minted has no carrier: that is the state
    every freshly invented name is in for as long as it takes to attach it, and
    `Naming` asks this predicate of exactly such a row. A `writable` built on
    `listable` refuses the member who typed the name a moment ago, which is a
    false refusal no mutation sweep can see.

    ## What this closes, and what it does not

    **Closed: the broadcast.** No member learns from a page load that a Tag
    exists whose Books they cannot see.

    **A name somebody typed is not asked this question, and that separation
    is what closed the regression this gate used to carry.** Typing a name
    that collides with a hidden Tag answered 201 with that row and then 404 on
    the attach, silently on the scan form, where the chip went with it.
    `Naming` is what both name resolving writers ask now, so a name is
    resolved and refused in one gesture and this predicate stays the question
    it was written for, an id somebody guessed.
    `tests/routers/test_books_tags.py::TestANameTypedAgainstAHiddenTagIsNotAttached`
    pins it and carries the rest.

    **What that closed is the attach, which was the harm rather than the
    tell.** The CSV import matched by folded name against every row with no
    viewer and **completed** the attach, onto a Book that defaults to public:
    the name then counts for every member, so `listable` volunteers it to all
    of them, and on an instance publishing its catalogue it reaches a reader
    with no session. No member can undo that, since `delete_tag` is admin
    only.

    **Not closed: confirmation by guess, and nothing available closes it.**
    The name space is globally unique of necessity (`Mint._by_folded_name`),
    so **every** observable answer to "may I have this name" answers "does it
    exist". Refusing, attaching and dropping silently are three answers and
    each of them is one; so is a Book handed back without the name on it, so
    is a drop count, and so is `writable`'s own last arm, which lets a
    guessed **id** be attached when no Book carries that Tag and hands the
    name back on the Book. No number of them is written here, because the
    set is open and a count of it goes stale against the code the moment a door
    answers differently. The strongest is `create_tag`, which hands back the
    colliding row itself, in one request, with no rate limit on it. Closing
    this means tag identity ceasing to be global, which is a migration rather
    than an edit here.

    **Not addressed at all: `collections` and `custom_fields`**, which are the
    same shape and were measured live on this tree. This class takes a viewer
    and a `Shelf`, so a second vocabulary moves behind it without a second
    design round; nothing here is specific to `tags` but the entity.
    """

    __slots__ = ("_counts", "_db", "_viewer_id")

    def __init__(self, db: Session, viewer_id: int) -> None:
        self._db = db
        self._viewer_id = viewer_id
        self._counts: dict[int, int] | None = None

    @classmethod
    def seen_by(cls, db: Session, viewer_id: int) -> Self:
        """The vocabulary as it looks to this Member.

        Named to be asked the way `Shelf.seen_by` is asked, because it is the
        same question one level out and a reader who knows one should not have
        to learn the other.
        """
        return cls(db, viewer_id)

    @property
    def counts(self) -> dict[int, int]:
        """Tag id to how many of this Member's visible Books carry it.

        **Joined to `books` through the Shelf, like every other query that
        counts Books.** Without it the count included other members' Private
        Books and trashed ones, and the endpoint this feeds is fetched on
        nearly every page, so a member could watch somebody else's private
        additions accrue in a number their own listing said was zero.

        A tag id is absent rather than zero when nothing visible carries it,
        which is what makes `.get(id, 0)` the visibility arm below as well as
        the published count.
        """
        if self._counts is None:
            self._counts = dict(
                Shelf.seen_by(self._db, self._viewer_id)
                .select(book_tags.c.tag_id, func.count(book_tags.c.book_id))
                .join(book_tags, book_tags.c.book_id == Book.id)
                .group_by(book_tags.c.tag_id)
                .all()
            )
        return self._counts

    def listable(self) -> list[Tag]:
        """Every Tag this Member may be told exists, ordered for the client.

        Two arms, and the order is by category then name so the response is
        deterministic: the order a reader sees is the client's, which re-sorts
        with a collator because no SQL fold moves `Ä`.
        """
        counts = self.counts
        return [
            tag
            for tag in self._db.query(Tag).order_by(Tag.category, Tag.name).all()
            if _is_seeded(tag) or counts.get(tag.id, 0) > 0
        ]

    def writable(self, tag: Tag) -> bool:
        """Whether this Member may act on a Tag they have named by id.

        False means the route answers 404, which is the answer an id no row
        carries already gets: a Tag whose every Book is hidden from the caller
        becomes indistinguishable from one that is not there.

        **Four arms, in cost order, and the last two are why this is not
        `listable`.**

        1. Seeded. Its name is in `PREDEFINED_TAGS`, which the mirror
           publishes, so it discloses nothing that is not already public.
        2. A Book on this Member's shelf carries it, so they can already read
           the name off that Book.
        3. A **trashed Book this Member may see** carries it, which is their
           own trashed Books and everybody's trashed public ones.
           `in_trash_for` is the mirror of `visible_to` rather than an
           ownership test, so the set is wider than the arm's name used to
           say, and the reason it is still safe is unchanged: those are Books
           whose trash listing this Member is served, so they can read the
           name off one. Without this arm a member who trashes the last Book
           carrying a Tag they invented could never put it on another one, and
           a name only a trashed public Book carries would be lost to
           everybody at once.
        4. **No Book carries it at all.** Such a Tag names no Book, so allowing
           it discloses no Book, and this is the arm every create depends on:
           between minting a Tag and attaching it there is no carrier, and on
           the scan form that gap is as long as the form is open. The tell it
           leaves is in this class's own docstring under what is not closed.
        """
        if _is_seeded(tag):
            return True
        if self.counts.get(tag.id, 0) > 0:
            return True
        if self._carried_in_the_trash_this_member_sees(tag):
            return True
        return not self._carried_by_any_book(tag)

    def _carried_in_the_trash_this_member_sees(self, tag: Tag) -> bool:
        """Whether a trashed Book this Member may see carries this Tag.

        **Not "a Book this Member trashed", which is what this was called and
        is narrower than what it asks.** `Shelf.trashed_by` is
        `in_trash_for`, the mirror of `visible_to`: trashed, and public or
        theirs. So another member's trashed **public** Book answers True here,
        and that is correct rather than a leak, because this Member is served
        that Book in their own trash listing and can read the name off it. The
        arm would be a leak if the predicate were unscoped, which is the
        mistake the name invited.

        `Shelf.trashed_by` and not a flag on `seen_by`, for the reason that
        method gives: a predicate that means "on the shelf" or "in the trash"
        depending on an argument is one a caller can get backwards, and
        backwards here would answer this question over every member's trash,
        private Books included.
        """
        return bool(
            Shelf.trashed_by(self._db, self._viewer_id)
            .select(func.count(book_tags.c.book_id))
            .join(book_tags, book_tags.c.book_id == Book.id)
            .filter(book_tags.c.tag_id == tag.id)
            .scalar()
        )

    def _carried_by_any_book(self, tag: Tag) -> bool:
        """Whether any Book in the library carries this Tag, viewer or no viewer.

        **Deliberately unscoped, and it is the one question here that has to
        be.** Every other read in this class asks what this Member may see; this
        one asks whether there is anything to disclose at all, and scoping it
        would answer yes for a Tag the Member simply cannot see, which is the
        case arm 4 exists to separate. It returns a boolean and never a count,
        so nothing about how many hidden Books carry the Tag leaves this method.
        """
        return bool(
            self._db.query(func.count(book_tags.c.book_id))
            .filter(book_tags.c.tag_id == tag.id)
            .limit(1)
            .scalar()
        )


@final
class Naming:
    """A name a Member typed, resolved to the Tag they may put on a Book.

    **One composition, asked by both writers that resolve a name.** The attach
    by name route and the CSV import each take a name out of a Member's own
    hands, so each asks the same three questions in the same order: what the
    name normalises to, which Tag the Library already has for it, and whether
    that Tag is this Member's to use. It is one class rather than a clause in
    each caller because two hand converged copies of one rule is the state
    this module exists to end, and `importing.py` held one of the two.

    **The viewer arrives here and not in the match**, one step later, on the
    decision to hand a matched Tag to a writer. `Mint.get_or_mint` carries why
    the match itself cannot be scoped, and it is the whole reason this class
    exists rather than a viewer argument on the Mint.

    **What is refused is the attach, which is the harm.** A name resolving to
    a Tag whose every Book is hidden was attached by the import, onto a Book
    that defaults to public, which made that name `listable` to every member
    permanently and with no member level undo. What is **not** refused is
    anything a Member already reaches: a seeded name, a name on their own
    shelf or in their own trash, a name no Book carries, and a name this unit
    of work has already handed them.

    **That last one is not a concession, and leaving it out is a false refusal
    in every ordinary upload.** `Vocabulary.counts` is read once per unit of
    work, so a Tag this import put on its own first Book is still absent from
    that count at the second row, while `_carried_by_any_book` is live and
    answers yes: from the second row on, the Member's own name would be
    refused off their own Book. **What puts a Tag in that population is
    having gained its first carrier inside this unit of work**, and the
    common member is the name the upload itself invents: a shelf name on two
    books is two rows carrying it, and the second is refused. A Tag the
    Library already held that no Book carried is the same case by another
    road, and is the rarer one. Recording what was allowed is also the true answer
    rather than a patch over a stale read: a Member who put the name on their
    own Book a moment ago can read it back off that Book.

    One Naming per unit of work, a request or an import, like the Mint and the
    Vocabulary it composes. Nothing here commits, for the reason the module
    docstring gives.
    """

    __slots__ = ("_allowed", "_mint", "_vocabulary")

    def __init__(self, mint: Mint, vocabulary: Vocabulary) -> None:
        self._mint = mint
        self._vocabulary = vocabulary
        #: Tag ids this unit of work has already handed to this writer.
        self._allowed: set[int] = set()

    @classmethod
    def for_member(cls, db: Session, member_id: int, *, budget: int | None = None) -> Self:
        """Names resolved as this Member, inventing at most `budget` of them.

        Named like `Import.for_member` and for the same reason: everything
        read is what this Member may see and everything written is theirs.
        """
        return cls(Mint(db, budget=budget), Vocabulary.seen_by(db, member_id))

    def tag(self, raw: str) -> Tag | None:
        """That Tag, minted if the Library has none, or None for a refusal.

        **The caller is not told which of the reasons applies**, and the two
        callers act the same way on all of them: the import counts the drop
        and moves to the next name, the route answers with the Book as it
        stands. A name that normalises to nothing, a spent mint budget and a
        Tag this Member may not use are one outcome here.

        A minted Tag is carried by no Book, so `writable` admits it on its
        last arm. That is the arm's live caller and the reason it cannot be
        narrowed to `listable`.
        """
        tag = self._mint.get_or_mint(raw)
        if tag is None:
            return None
        if tag.id in self._allowed or self._vocabulary.writable(tag):
            self._allowed.add(tag.id)
            return tag
        # **The name as submitted, never `tag.name`.** The stored row's
        # spelling is what the guess was folded onto, and handing that to a
        # log is handing over the exact casing of a name this Member was just
        # refused. What they sent is theirs already.
        #
        # `attach` and `get_or_mint` log their own drops for the reason
        # `classifications.add_headings` gives, and this is the third: a drop
        # with nowhere to read it off is a loss. The line rate is the
        # caller's, as it already is at those two.
        logger.info("Not this member's to use; dropping %r", raw)
        return None


def _is_seeded(tag: Tag) -> bool:
    """Whether this row is one `seed_tags()` owns **and still names**.

    **`key`, not `is_predefined`, and the difference is the whole safety of the
    exemption.** What makes a seeded Tag safe to publish unasked is that its
    name is in this version's own seed list, which the mirror publishes. `key`
    is written by `seed_tags()` alone, is unique by `uq_tags_key`, and
    `Tag._drop_the_key_on_a_rename` clears it the moment the name stops being
    the seeded one.

    `is_predefined` **survives a rename**, so a household's own word on a
    renamed seeded row would ride into the exempt set under it, and nothing
    today would say so: no route renames a Tag, which is a fact about this
    version rather than a rule. Deriving from `key` needs no such premise,
    because the validator enforces it rather than a paragraph asking for it.

    **`known_key` and not `is not None`, which is the other half.** `tags.key`
    is a plain string column, so a library moved back to an older image holds
    keys that version has never heard of. Under a bare null check such a row is
    exempt and its name published, although that name is in no list this
    version ships, which is the opposite of the argument above.
    `schemas.tag.known_key` is the one function that already answers "as this
    version understands it", and `TagOut.key` runs it too, so what is exempt
    here and what is sent on the wire are decided by the same test rather than
    by two that agree today.

    The cost is stated rather than hidden: a renamed seeded row, and a row
    keyed by a newer version, leave the picker of a member no visible Book
    gives them, and `delete_tag` still refuses the first for being predefined.
    Typing the name returns the row and puts it back on a Book. The three
    writes that skip the validator are named in its own docstring, and each
    would leave a key describing a name the row no longer has; that is the
    residue of this derivation, not of the column choice.
    """
    return known_key(tag.key) is not None


def room_on(book: Book) -> bool:
    """Whether this Book may take another tag.

    **Asked before minting, where `attach` asks again after it.** The two are
    not one check twice: without this a Book already at its ceiling would spend
    an import's new tag budget on names it is then refused, so the next Book in
    the file loses tags to one that could not carry them. `attach` is what makes
    the ceiling true whoever writes, and this is what keeps the budget honest.
    """
    return len(book.tags) < MAX_TAGS_PER_BOOK


def attach(book: Book, tag: Tag) -> bool:
    """Put this Tag on this Book. False when the Book is full and did not take it.

    **Idempotent, and a Book already carrying the Tag answers True.** That is
    what lets a caller walking a file's tag column read False as "this Book is
    full" and stop, rather than asking again for every remaining name.

    The drop is logged, `classifications.add_headings`' rule: what is dropped is
    a name out of a member's own file and nothing regenerates it, so a silent
    drop is a loss with nowhere to read it off.

    **Adds no row itself and commits nothing.** `book_tags` carries no payload
    beyond the pair, so the association is the append and the caller's commit.
    """
    if any(carried.id == tag.id for carried in book.tags):
        return True
    if not room_on(book):
        logger.info(
            "Book %s already carries %d tags; dropping %r",
            book.id,
            len(book.tags),
            tag.name,
        )
        return False
    book.tags.append(tag)
    return True
