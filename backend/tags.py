"""Deciding a tag from a name, and how many of them one Book may carry.

One rule and every writer. `Mint` answers a name with the Tag the Library
already has or mints the one it does not; `attach` puts a Tag on a Book without
ever exceeding `MAX_TAGS_PER_BOOK`. The one other module that decides a tag is
`main.py`, for the seeded vocabulary.
`tests/test_tags.py::TestNothingElseDecidesATagFromAName` is what says so, over
every module under `backend/` but the tests and the generated migrations, and it
states what its two instruments do not see.

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

**Nothing here queries for a Book.** `attach` takes a Book somebody else
resolved. The privacy rule is `shelf.py`'s and is applied before a Book reaches
this module, which is what keeps this file out of `tests/test_shelf.py`'s fourth
pass without an allowlist entry.
"""

import logging
from collections.abc import Iterable
from typing import Final

from sqlalchemy.orm import Session

from enums import TagCategory
from models import Book, Tag
from schemas.common import one_line_without_invisible_characters
from schemas.tag import MAX_TAG_NAME

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


class Mint:
    """Every Tag this Library gains, and the index each one is deduplicated against.

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
