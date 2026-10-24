"""Who may be told a Library wide vocabulary entry exists, for any vocabulary.

A Tag, a Collection and a custom field each carry no member, so nothing in the
row says who may read it: the answer is whoever may read a Book carrying it.
That rule was written three times, once per vocabulary, with three copies of
the same three reads and the arms in three orders. It is written here once,
parameterised by `Carrier`, which is how a Book carries an entry.
`tags.Vocabulary`, `shelving.Shelving` and `fields.Fields` are the arms: each
names its carrier and any arm of its own, and keeps what it alone publishes.

## The arms, in this order

1. **A Book this Member can see carries it**, through `Shelf.seen_by`. The
   Member can already read the entry off that Book.
2. **A deleted Book this Member may see carries it**, through
   `Shelf.trashed_by`: their own trashed Books and every Member's trashed
   public ones, which is `in_trash_for` and not an ownership test. A restore
   reinstates the carrier, so without this arm trashing the last carrier takes
   the entry off the page of the Member about to bring it back.
3. **The vocabulary's own arms**, in the order it gives them: the seeded
   names for tags, the definer for custom fields.
4. **No Book at all carries it**, through
   `shelf.entries_any_book_carries`. An entry nothing carries discloses no
   Book, and this is the arm every create depends on.

## Absent and hidden cost the same, and the order is what makes it so

**Arm 4 is last because it is the only arm that answers yes for an id no row
carries.** Every arm before it answers no to an absent id and to a hidden one
alike, so both run every arm. Put a vocabulary arm behind arm 4 and an absent
id stops at arm 4 where a hidden one goes on, and the two refusals separate
on a clock.

**Every arm reads a whole set, once and lazily, and never a single id.** So
the statements an arm issues do not depend on which id is asked, and a caller
asking nothing pays nothing. A vocabulary arm handed in must keep that.

**`resolve` asks the gate before it fetches the row, and always fetches.**
Written the other way round, `or` short circuits: an absent id never reaches
the arms and costs one statement where a hidden id costs several. Skipping the
fetch on a refusal would separate them the other way, by the one statement an
absent id spends finding nothing. `tests/test_disclosure.py` counts the
statements at every door that takes an id.

## What this does not close

**Confirmation by name.** Each vocabulary's name space is globally unique of
necessity, so a create answering a collision discloses the colliding entry.
The arms' docstrings say what each create hands back.
"""

from collections.abc import Callable
from enum import Enum
from typing import Any, Self, final

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Book, CustomFieldValue, book_tags
from shelf import Shelf, entries_any_book_carries


class Carrier(Enum):
    """How a Book carries an entry of one Library wide vocabulary.

    **The one fact about a vocabulary `Disclosure` needs**, because who may be
    told an entry exists is whoever may read a Book carrying it. Closed by the
    type: another vocabulary is a member here and a decision, never a column
    handed in from a call site, and `tests/test_disclosure.py` pins the set.

    **What crosses out of a carrying table is `entry` and nothing else**, plus
    a count of Books for a counted vocabulary. `onto_books` names the other
    column only as a join onclause.
    """

    #: A Tag, through the association table.
    BOOK_TAGS = "book_tags"
    #: A Collection, through the scalar on `books`.
    COLLECTION = "collection_id"
    #: A custom field, through the table of values.
    CUSTOM_FIELD_VALUES = "custom_field_values"

    @property
    def entry(self) -> Any:
        """The column holding the entry's id on the carrying row."""
        match self:
            case Carrier.BOOK_TAGS:
                return book_tags.c.tag_id
            case Carrier.COLLECTION:
                return Book.collection_id
            case Carrier.CUSTOM_FIELD_VALUES:
                return CustomFieldValue.field_id

    @property
    def onto_books(self) -> tuple[Any, Any] | None:
        """The table joined onto `books` to reach the entry, and on what. None
        when the entry is a column of `books` itself."""
        match self:
            case Carrier.BOOK_TAGS:
                return book_tags, book_tags.c.book_id == Book.id
            case Carrier.COLLECTION:
                return None
            case Carrier.CUSTOM_FIELD_VALUES:
                return CustomFieldValue, CustomFieldValue.book_id == Book.id

    @property
    def counted(self) -> bool:
        """Whether the vocabulary publishes how many visible Books carry an
        entry. A custom field does not, and `list_custom_fields` says why, so
        its visible read is a set of ids and computes no count to reach for."""
        return self is not Carrier.CUSTOM_FIELD_VALUES


#: A vocabulary's own arm: whether it admits this id. It reads a whole set,
#: lazily and once, so it costs the same statements whatever the id.
Arm = Callable[[int], bool]


@final
class Disclosure:
    """Which entries of one vocabulary one Member may be told exist.

    One per request or unit of work, like the `Shelf` it reads through. The
    reads are cached, so an entry a unit of work gives its first carrier is
    still in no set: an arm caller that needs the live answer records what it
    allowed, which is what `tags.Naming` does.
    """

    __slots__ = ("_arms", "_carried", "_carrier", "_db", "_trashed", "_viewer_id", "_visible")

    def __init__(self, db: Session, viewer_id: int, carrier: Carrier, *arms: Arm) -> None:
        self._db = db
        self._viewer_id = viewer_id
        self._carrier = carrier
        self._arms = arms
        self._visible: dict[int, int] | frozenset[int] | None = None
        self._trashed: frozenset[int] | None = None
        self._carried: frozenset[int] | None = None

    @classmethod
    def seen_by(cls, db: Session, viewer_id: int, carrier: Carrier, *arms: Arm) -> Self:
        """The vocabulary `carrier` reaches, as it looks to this Member."""
        return cls(db, viewer_id, carrier, *arms)

    @property
    def counts(self) -> dict[int, int]:
        """Entry id to how many of this Member's visible Books carry it.

        Absent rather than zero when nothing visible carries it. Refused for a
        vocabulary that publishes no count, so the number is never computed
        for one: `Carrier.counted` says which.
        """
        visible = self._on_the_shelf if self._carrier.counted else None
        if not isinstance(visible, dict):
            raise TypeError(f"{self._carrier.name} publishes no count")
        return visible

    def may_be_told(self, entry_id: int) -> bool:
        """Whether this Member may be told the entry at this id exists, or act
        on it by id. True for an id no row carries, which is arm 4."""
        if entry_id in self._on_the_shelf:
            return True
        if entry_id in self._in_the_trash_this_member_sees:
            return True
        if any(arm(entry_id) for arm in self._arms):
            return True
        return entry_id not in self._carried_by_any_book

    def resolve[Row](self, entry_id: int, fetch: Callable[[int], Row | None]) -> Row | None:
        """The row at this id, or None for an id no row carries and for one
        this Member may not be told about alike.

        `fetch` is the vocabulary's own read of its table by id. It runs after
        the gate and whatever the gate said, for the reason the module
        docstring gives.
        """
        may_be_told = self.may_be_told(entry_id)
        row = fetch(entry_id)
        return row if may_be_told else None

    @property
    def _on_the_shelf(self) -> dict[int, int] | frozenset[int]:
        """Arm 1: the entries a Book this Member can see carries. With the
        count when the vocabulary publishes one, as a set when it does not."""
        if self._visible is None:
            carrier = self._carrier
            shelf = Shelf.seen_by(self._db, self._viewer_id)
            if carrier.counted:
                query = shelf.select(carrier.entry, func.count(Book.id))
            else:
                query = shelf.select(carrier.entry)
            if carrier.onto_books is not None:
                query = query.join(*carrier.onto_books)
            query = query.filter(carrier.entry.isnot(None))
            if carrier.counted:
                self._visible = {
                    entry_id: count
                    for entry_id, count in query.group_by(carrier.entry).all()
                    if entry_id is not None
                }
            else:
                self._visible = frozenset(row[0] for row in query.distinct().all() if row[0] is not None)
        return self._visible

    @property
    def _in_the_trash_this_member_sees(self) -> frozenset[int]:
        """Arm 2: the entries a deleted Book this Member may see carries.

        `Shelf.trashed_by` and not a flag on `seen_by`: a predicate meaning
        "on the shelf" or "in the trash" by an argument is one a caller can get
        backwards, and backwards here reads every Member's trash.
        """
        if self._trashed is None:
            carrier = self._carrier
            query = Shelf.trashed_by(self._db, self._viewer_id).select(carrier.entry)
            if carrier.onto_books is not None:
                query = query.join(*carrier.onto_books)
            rows = query.filter(carrier.entry.isnot(None)).distinct().all()
            self._trashed = frozenset(row[0] for row in rows if row[0] is not None)
        return self._trashed

    @property
    def _carried_by_any_book(self) -> frozenset[int]:
        """Arm 4's read, and the one that has to be unscoped: scoped, it would
        answer "carries nothing" for an entry on Books this Member cannot see,
        which is the case arm 4 exists to separate from an unused one."""
        if self._carried is None:
            self._carried = entries_any_book_carries(self._db, self._carrier)
        return self._carried
