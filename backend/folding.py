"""What becomes of everything pointing at a Book when two Books turn out to be one.

`fold` is the door. Behind it: which of `books`' child tables move to the
survivor, how each resolves a row the survivor already holds, which of them are
capped, and the order the writes happen in so the unique indexes hold.

**The set of tables is derived, not listed.** `TRANSFERS` declares one policy
per child of `books` and this module refuses to import when that set and
`models.children_of_books` disagree. Delete the check and a child table added to
the schema is cascade deleted on every merge with nothing red, which is the
state this module was written out of: ten hand written blocks in a route handler
with nothing relating them to `Book`'s ten child collections, and seven test
docstrings in seven files each independently warning that the cascade would
silently destroy one table.

**Here rather than in `routers/books.py`, and that is not the split ADR 0008
refuses.** That refusal is of a split by resource, which publishes helpers and
lets no caller stop knowing anything. This is a concept: a caller stops knowing
the ten tables, the four collision rules, the three ceilings, the single open
loan invariant and the ISBN release ordering. It also restores that ADR's own
rule that a router is the one place shallowness is correct, which 67 statements
of transfer policy had stopped being.
"""

import logging
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Table
from sqlalchemy.orm import Session

import custom_fields
import lending
import reading
from book_columns import FILLABLE_FROM_ANOTHER_ROW
from database import Base
from enums import BookIdentifierScheme, ClassificationScheme
from logvalues import clipped
from models import (
    Book,
    BookIdentifier,
    Classification,
    DigitalReference,
    Loan,
    Note,
    Quote,
    ReadingProgress,
    book_tags,
    children_of_books,
)
from schemas import (
    MAX_CLASSIFICATIONS_PER_BOOK,
    MAX_DIGITAL_REFERENCES_PER_BOOK,
    MAX_IDENTIFIERS_PER_BOOK,
)

logger = logging.getLogger("endpaper.folding")


# ── The Books in hand ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Fold:
    """The Books one merge is folding: the survivor, and the rows about to go.

    Private, like `_Transfer` below: `fold` is this module's whole door, and a
    name nothing outside calls is surface a reader has to learn for nothing.

    Handed to every `_Transfer.carry`, so a policy takes one argument and gets
    everything any of them needs. The ids sit beside the objects because most
    transfers query by id, while the tag union is the one that needs the
    losers' loaded collections.
    """

    db: Session
    keeper: Book
    losers: Sequence[Book]
    loser_ids: Sequence[int]


type Carry = Callable[[_Fold], None]


@dataclass(frozen=True)
class _Transfer:
    """What becomes of one child table's rows when the Book they point at loses.

    `table` is the `Table` object and not its name. A mistyped table is then an
    import error rather than a silent disagreement with the derived set, and the
    name the completeness check compares is read off the object.
    """

    table: Table
    carry: Carry


def _table(name: str) -> Table:
    """The `Table` of that name, and the same object the derivation sees.

    Read out of `Base.metadata` rather than off a class attribute, which is
    typed `FromClause` because a class may be mapped to a select. Identity is
    what the completeness check compares, so the two sides have to be one object
    rather than two readings of one name, and a name that is not in the schema
    fails this call rather than the check below.

    A name rather than the class, because two of these tables are owned by
    another module and naming their class here is the import that module's own
    guard refuses: see `reading.RECORDS_TABLE`.
    """
    return Base.metadata.tables[name]


# ── The four collision rules ──────────────────────────────────────────────────


def _union_tags(fold: _Fold) -> None:
    """A set union, since `book_tags` has no payload beyond the pair.

    **No ceiling, deliberately.** `tags.attach` holds `MAX_TAGS_PER_BOOK` against
    every writer naming a tag, and a merge names none: dropping one here would
    lose a name off a member's own shelf that nothing puts back.
    """
    existing = {tag.id for tag in fold.keeper.tags}
    for loser in fold.losers:
        for tag in loser.tags:
            if tag.id not in existing:
                fold.keeper.tags.append(tag)
                existing.add(tag.id)
        loser.tags.clear()


def _moves_wholesale(model: Any) -> Carry:
    """Every row travels: the table carries no uniqueness of its own to resolve.

    Assigned object by object rather than with a bulk UPDATE. A bulk update with
    `synchronize_session=False` leaves the session's loaded collections stale,
    and the delete that follows would cascade straight through them.
    """

    def carry(fold: _Fold) -> None:
        for row in fold.db.query(model).filter(model.book_id.in_(fold.loser_ids)).all():
            row.book_id = fold.keeper.id

    return carry


def _deduplicated(
    model: Any,
    *,
    held: Callable[[Book], Iterable[Any]],
    key: Callable[[Any], Hashable],
    ceiling: int,
    absorb: Callable[[Any, Any], None] | None = None,
) -> Carry:
    """The three capped tables, whose unique index would refuse the flush.

    One algorithm rather than three copies of it: order the losers' rows by id,
    key them, resolve a row the survivor already holds, refuse past the ceiling,
    repoint what is left. Written out three times it was three chances for a
    ceiling to be forgotten and three `>=` comparisons to drift; a table that
    needs no ceiling does not reach this constructor at all.

    **`ceiling` is the constant that already binds the table's other writer**,
    passed in rather than restated. A merge takes up to 20 Books in one request
    carrying no rate limiter, so an uncapped move is a stored write nobody
    bounded: one request would put 8 x 19 = 152 headings on the survivor, which
    is then the baseline for the next merge, and every listing pays for it
    because `books_to_out` selectin loads these relationships onto every row of
    every page. An invariant stated "full stop" with one writer exempt from it
    is worse than a cap that admits it is soft.

    **Keeper first, then losers in id order**, so what survives is what was
    already stored. Same tie break as `classifications.add_headings`.

    `absorb` is what a repeat gives up before it goes, and the two tables
    without one are the difference worth reading: a caption where there was none
    is strictly more than before, and a second report of a file path is not.

    **The overflow is deleted and logged.** It is a loss: the value came from a
    Member or from a catalogue and nothing regenerates it. `clipped`, because
    SQLite does not enforce a VARCHAR length, so the value being named here is
    bounded by nothing this application controls.
    """

    def carry(fold: _Fold) -> None:
        kept = {key(row): row for row in held(fold.keeper)}
        for row in (
            fold.db.query(model)
            .filter(model.book_id.in_(fold.loser_ids))
            .order_by(model.id)
            .all()
        ):
            token = key(row)
            survivor = kept.get(token)
            if survivor is not None:
                if absorb is not None:
                    absorb(survivor, row)
                fold.db.delete(row)
                continue
            if len(kept) >= ceiling:
                logger.info(
                    "Book %s is at the %s ceiling; merge drops %s",
                    fold.keeper.id,
                    model.__tablename__,
                    clipped(token),
                )
                fold.db.delete(row)
                continue
            row.book_id = fold.keeper.id
            kept[token] = row

    return carry


def _absorb_heading(survivor: Classification, losing: Classification) -> None:
    """A losing heading fills the survivor's gaps before it goes.

    The keeper may hold `(ddc, 004, NULL)` from K10plus while the loser holds
    `(ddc, 004, "Informatik")` from the DNB, and deleting that row without
    taking its caption loses the caption for good: nothing re-enriches a
    survivor.

    **And its kind, on the same rule and for a sharper reason**: the loser's row
    may be the corrected one. Only a record that declares a `$2` ever sets it,
    so a merge dropping the half that had it would put a disc back among the
    subjects with nothing to see.
    """
    if survivor.label is None and losing.label is not None:
        survivor.label = losing.label
    if survivor.kind is None and losing.kind is not None:
        survivor.kind = losing.kind


def _carry_loans(fold: _Fold) -> None:
    """Loans move whole, and then the survivor is left with one open loan.

    Merging two Books that are both lent out used to give the survivor **two**,
    which the data model says cannot happen: `returned_at IS NULL` is the single
    active loan. Every later `POST /api/loans` on that Book then 409s forever,
    and the UI renders one `active_loan`, so there is no way to see or close the
    other.

    The earliest stays open, because it is the loan that has been out longest
    and is the one worth chasing. The rest are closed now: the Books they
    described have just become one Book, so they are not still out.

    Built from the objects in hand rather than by re-querying, because the
    repointing is not flushed yet, so a fresh query does not necessarily see the
    moved loans as belonging to the survivor. `lending.is_open`, not the column,
    for the same reason: this is the one caller that cannot ask
    `Loans.open_on`.
    """
    moved = fold.db.query(Loan).filter(Loan.book_id.in_(fold.loser_ids)).all()
    for loan in moved:
        loan.book_id = fold.keeper.id

    on_keeper = fold.db.query(Loan).filter(Loan.book_id == fold.keeper.id).all()
    open_loans = sorted(
        {loan.id: loan for loan in [*on_keeper, *moved]}.values(),
        key=lambda loan: (loan.loaned_at, loan.id),
    )
    still_open = [loan for loan in open_loans if lending.is_open(loan)]
    now = datetime.now(UTC).replace(tzinfo=None)
    for loan in still_open[1:]:
        lending.close(loan, now)


def _carry_reading_records(fold: _Fold) -> None:
    """Delegated: `reading.py` owns every `user_books` row, merge included.

    Every Member's records and not just the caller's, and the keeper's own row
    wins a collision. `reading.resolve_merge` holds both rules, because a rule
    about who may read a reading record belongs to the module that owns the
    table rather than to whichever feature is writing it this time.
    """
    reading.resolve_merge(fold.db, fold.keeper.id, fold.loser_ids)


def _carry_custom_field_values(fold: _Fold) -> None:
    """Delegated: `custom_fields.py` owns the Library's own fields.

    The keeper's own value wins a collision, and `custom_fields.resolve_merge`
    holds that rule for the reason the reading records' is next door: the module
    that decides who may read a value decides what a merge does to it.
    """
    custom_fields.resolve_merge(fold.db, fold.keeper.id, fold.loser_ids)


# ── One policy per child of `books` ───────────────────────────────────────────

#: What a merge does to every table that points at `books`.
#:
#: **Completeness is checked below, correctness is not.** A `_Transfer` whose
#: carry does nothing passes the check, which the ten inline blocks this
#: replaced gave nobody the chance to write. That is the accepted cost: what it
#: replaces is silence, and a policy that loses rows is now a written decision
#: in a diff rather than a table nobody noticed. The per table behaviour is
#: guarded by the merge tests in `tests/routers/`, not from here.
TRANSFERS: Final[tuple[_Transfer, ...]] = (
    _Transfer(_table(book_tags.name), _union_tags),
    # Two rows for one Book often carry the same DDC number, and
    # `uq_classifications_book_scheme_number` would refuse the second on the
    # flush. Left out, the cascade on the loser's deletion takes them and a
    # merge silently drops the provenance of the row that lost.
    _Transfer(
        _table(Classification.__tablename__),
        _deduplicated(
            Classification,
            held=lambda book: book.classifications,
            key=lambda row: (ClassificationScheme(row.scheme).value, row.number),
            ceiling=MAX_CLASSIFICATIONS_PER_BOOK,
            absorb=_absorb_heading,
        ),
    ),
    # Notes carry their own history. A merge repoints every one of them whatever
    # its author or its visibility: a rule that skipped a private note here
    # would not hide it, it would delete it.
    _Transfer(_table(Note.__tablename__), _moves_wholesale(Note)),
    # Quotes move with the notes, or the cascade destroys passages somebody
    # typed out by hand. Page numbers travel unchanged and may now describe a
    # different printing, which is the standing cost of merging two rows that
    # were two editions: the alternative is refusing the merge.
    _Transfer(_table(Quote.__tablename__), _moves_wholesale(Quote)),
    # `uq_digital_references_location` would refuse the flush where the keeper
    # and a loser were catalogued from the same file, which is the **likely**
    # case rather than an edge: two rows for one Book are commonly two imports
    # of one library. A repeat is dropped and nothing is lost, because two
    # reports of one file are two accounts of the same thing.
    _Transfer(
        _table(DigitalReference.__tablename__),
        _deduplicated(
            DigitalReference,
            held=lambda book: book.digital_references,
            key=lambda row: (row.root_label, row.relative_path),
            ceiling=MAX_DIGITAL_REFERENCES_PER_BOOK,
        ),
    ),
    # **Only an exact repeat is a duplicate here**, which is the difference from
    # the headings above and the whole reason `uq_book_identifiers_book_scheme_value`
    # carries the value. Two Kindle entries a Member declared the same Book carry
    # two ASINs and both survive: that is the merge saying which editions were
    # folded together, where keying on the scheme alone would have made it an
    # `IntegrityError` instead of a fact.
    _Transfer(
        _table(BookIdentifier.__tablename__),
        _deduplicated(
            BookIdentifier,
            held=lambda book: book.identifiers,
            key=lambda row: (BookIdentifierScheme(row.scheme).value, row.value),
            ceiling=MAX_IDENTIFIERS_PER_BOOK,
        ),
    ),
    _Transfer(_table(Loan.__tablename__), _carry_loans),
    # Progress carries no uniqueness, so unlike the reading records below there
    # is nothing to resolve: two Members' readings of what turned out to be one
    # Book are two histories of one Book.
    _Transfer(_table(ReadingProgress.__tablename__), _moves_wholesale(ReadingProgress)),
    _Transfer(_table(reading.RECORDS_TABLE), _carry_reading_records),
    _Transfer(_table(custom_fields.VALUES_TABLE), _carry_custom_field_values),
)


def _undeclared(transfers: Sequence[_Transfer], children: set[Table]) -> set[Table]:
    """The symmetric difference between what is declared and what the schema has.

    Symmetric rather than one sided: a table added with no policy loses every
    row it holds on the first merge, and a policy left behind by a table that
    was removed is a claim about a merge nobody can read. Both are answered by
    editing `TRANSFERS`, so both belong in the same message.

    Takes its two sides rather than reading them, so the check below can be
    driven against a schema a test builds.
    """
    return {transfer.table for transfer in transfers} ^ children


#: Refused at import, not at the first merge.
#:
#: The failure this replaces is the silent destruction of Members' rows. A check
#: at the first merge fires in production, on somebody's library, after the
#: deploy; a check here fires on the machine of whoever added the table and
#: stops every test run until they declare something. `Base.metadata` is built
#: from code, so nothing in a database can make this fire at runtime and not in
#: the suite.
_UNDECLARED = _undeclared(TRANSFERS, children_of_books(Base.metadata))
if _UNDECLARED:
    raise RuntimeError(
        "TRANSFERS and the children of `books` disagree, so a merge either "
        "destroys rows nobody wrote a policy for or carries a policy for a "
        "table that no longer exists: "
        f"{sorted(table.name for table in _UNDECLARED)}. Every child of `books` "
        "is cascade deleted with a losing Book, so a new one loses every row it "
        "holds on the first merge and says nothing. Give it an entry in TRANSFERS."
    )


# ── The survivor's own columns ────────────────────────────────────────────────
#
# Asked rather than listed, for the reason `TRANSFERS` is: a hand written tuple
# of column names relates to `Book` through nothing, so a column added to the
# schema joins it only if somebody remembers. `book_columns` refuses to import
# when a column is classified nowhere, and its cells carry why each exclusion is
# an exclusion: `isbn` because it is unique and `fold` releases it in its own
# flush ahead of everything, `copy_group` because absorbing it would make the
# survivor a copy of the loser's siblings.


def _absorb_fields(keeper: Book, losers: Sequence[Book], isbn: str | None) -> None:
    """Fill the survivor's gaps from the rows about to disappear.

    `isbn` is passed because the losers have already been stripped of theirs by
    the time this runs, so the value cannot be read back off them. See the
    ordering in `fold`.
    """
    if keeper.isbn is None and isbn is not None:
        keeper.isbn = isbn

    for field in FILLABLE_FROM_ANOTHER_ROW:
        if getattr(keeper, field) is not None:
            continue
        for loser in losers:
            value = getattr(loser, field)
            if value is not None:
                setattr(keeper, field, value)
                break


# ── The door ──────────────────────────────────────────────────────────────────


def fold(db: Session, keeper: Book, losers: Sequence[Book]) -> None:
    """Fold the losing Books into the survivor. Everything but the delete.

    The survivor absorbs any column it lacks and every child row the losers
    hold; `TRANSFERS` is what each table does with a row the survivor already
    has. The caller deletes the losing rows afterwards, and has to expire them
    first: their loaded collections still list the rows just moved, and the
    cascade walks those collections rather than the database.

    **The ISBN is released in its own flush, before anything else.** It is
    unique, so the row it is being taken from has to let go first. Both UPDATEs
    in one executemany puts the set before the clear and trips the index. These
    rows are about to cease to exist, so releasing it costs nothing.

    Flushed between the absorb and the transfers, and again at the end, because
    every transfer is written to read the database as it stands rather than what
    a caller has already repointed.
    """
    absorbed_isbn = next((loser.isbn for loser in losers if loser.isbn), None)
    if keeper.isbn is None and absorbed_isbn is not None:
        for loser in losers:
            loser.isbn = None
        db.flush()

    _absorb_fields(keeper, losers, absorbed_isbn)
    db.flush()

    in_hand = _Fold(db=db, keeper=keeper, losers=losers, loser_ids=[book.id for book in losers])
    for transfer in TRANSFERS:
        transfer.carry(in_hand)
    db.flush()
