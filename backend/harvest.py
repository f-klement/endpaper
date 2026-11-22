"""What a harvester can see change: the OAI-PMH datestamp and the tombstone.

## Two properties, and this module is the only writer of either

1. **Every write that changes what a harvested record contains moves
   `Book.oai_datestamp`**, a child row's included: a heading, a link, a tag on
   the book or a tag renamed. A write to a withheld column of `books`, or an ORM
   write to one of a child row, moves nothing, since a moving datestamp tells a
   harvester that something it cannot see changed. A bulk UPDATE of a child
   table moves its Books whatever columns it sets.
2. **Every record a harvester could have seen that it can no longer see answers
   as a deleted header** (`deletedRecord` is `persistent`, the owner's decision). A
   Book that leaves `Shelf.seen_by_the_public` by any route gets an
   `OaiTombstone`, and one that comes back loses it and has its datestamp moved.
   **None is written before the provider first served a request**
   (`settings_store.oai_has_served`, the owner's decision): no harvester could
   have seen a record that left before then, and a tombstone for it would publish
   an id and a date nobody outside was ever shown.

## One mechanism, so a write path added later cannot forget it

Session events, registered at import on `sqlalchemy.orm.Session` and so on every
session in the process. `models.py` imports this module at its foot, so any
process that can name a Book has them.

| door | what it sees |
|---|---|
| `before_flush`, `after_flush_postexec` | the unit of work: every ORM write |
| `do_orm_execute` | a bulk INSERT, UPDATE or DELETE given to `Session.execute` |

`routers/books.delete_tag`'s association delete is one of the second kind.
A bulk INSERT into a child table is followed by the book id each row names; **one
whose Books its parameters do not name, an INSERT from a SELECT, is refused**
rather than missed. `wholesale` is the one way past both
doors, and `backup.restore` is its one caller, since a restore replaces every
row and is settled afterwards as a whole.

**What neither door sees**: SQL written as text, and a statement run on a
`Connection` rather than through the `Session`. `tests/test_harvest.py` reads the
application tree for a text write to these tables, for driver SQL, and for a
`Connection` taken anywhere but here and in the migration runner.

## Leaving the public view is read off the Shelf, never restated

Which Books a harvester sees is `Shelf.seen_by_the_public`, so the flush asks it
for the ids before and after rather than reading `is_private` and `deleted_at`
here: a second spelling of the rule would drift from the first. Which columns
can move a Book is read off it too (`Shelf.public_columns`). The cost is two
SELECTs by primary key per flush that deletes a Book or changes one of those
columns; any other edit, and a flush that only creates Books, asks nothing,
since a new id carries no tombstone (see `wholesale` for why that holds after a
restore too).

**A tombstone is written only for a Book that was public before the write.** One
for a Book that never was would publish the id of a private Book.

## What "contains" means is derived from the column boundary

`schemas.public.PublicBookOut` is what a harvested record may carry (`oai.py`
builds `oai_dc` from it, and `marc.py` is pinned to it), so the watched columns
are its fields, read off it rather than listed. A field naming nothing on `Book`
is refused at the first flush and in the suite, so a new public field cannot go
unwatched.
"""

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from types import UnionType
from typing import Any, Final, cast, get_args

from sqlalchemy import Table, delete, event, func, insert, inspect, select, text, tuple_, update
from sqlalchemy.orm import InstanceState, Mapper, ORMExecuteState, Session, UOWTransaction, class_mapper
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.elements import BindParameter

import dialect
from enums import SettingKey
from models import Book, OaiTombstone, Setting, datestamp_now

#: `PublicBookOut` fields computed from a column rather than mapped to one.
_DERIVED: Final[dict[str, str]] = {"authors": "author"}

#: `Session.info` keys. Per session, so two requests never share a flush's state.
_PENDING: Final = "harvest_pending"
_SUSPENDED: Final = "harvest_suspended"

#: The two tables as `Table`: the declarative attribute is typed as a bare
#: `FromClause`, which no DML constructor accepts.
_BOOKS: Final = cast(Table, Book.__table__)
_TOMBSTONES: Final = cast(Table, OaiTombstone.__table__)


class BulkInsertRefused(RuntimeError):
    """A bulk INSERT into a child table whose Books cannot be read from the statement."""


@dataclass(frozen=True)
class _Watched:
    """What a harvested record reads, as the flush needs it."""

    #: Columns and collections of `Book`.
    book_attributes: frozenset[str]
    #: Each child class, and the attributes of it the record reads.
    children: dict[type, frozenset[str]]
    #: A child reached through an association table: `Tag` through `book_tags`.
    associations: dict[type, Table]
    #: Every table a bulk statement is followed on.
    tables: frozenset[str]
    #: The attributes of `Book` the public shelf reads: only a change to one of
    #: them can move a Book in or out of what a harvester sees.
    public_attributes: frozenset[str]


def _item_model(annotation: Any) -> Any:
    """`list[X]`, or `list[X] | None`, as `X`."""
    if isinstance(annotation, UnionType):
        annotation = next(arg for arg in get_args(annotation) if arg is not type(None))
    return get_args(annotation)[0]


@cache
def watched() -> _Watched:
    """Derived from `PublicBookOut` once, and refused where a field names nothing.

    Imported here rather than at the top: `models.py` imports this module at its
    foot, and `schemas` reaching back into a half built `models` is a cycle.
    """
    from schemas.public import PublicBookOut

    mapper = inspect(Book)
    book_attributes: set[str] = set()
    children: dict[type, frozenset[str]] = {}
    associations: dict[type, Table] = {}
    for name, info in PublicBookOut.model_fields.items():
        source = _DERIVED.get(name, name)
        book_attributes.add(source)
        if source in mapper.column_attrs:
            continue
        relationship = mapper.relationships.get(source)
        if relationship is None:
            raise RuntimeError(
                f"PublicBookOut.{name} names no column or relationship of Book, so no write "
                "could move the datestamp for it. Map it in harvest._DERIVED."
            )
        child = relationship.mapper
        fields = set(_item_model(info.annotation).model_fields)
        unmapped = fields - set(child.column_attrs.keys())
        if unmapped:
            raise RuntimeError(
                f"{sorted(unmapped)} on the public {source} name no column of {child.class_.__name__}"
            )
        children[child.class_] = frozenset(fields)
        if relationship.secondary is not None:
            associations[child.class_] = relationship.secondary  # type: ignore[assignment]
    tables = {Book.__tablename__}
    tables |= {_table_of(cls).name for cls in children}
    tables |= {table.name for table in associations.values()}
    return _Watched(
        frozenset(book_attributes), children, associations, frozenset(tables), _public_attributes(mapper)
    )


def _public_attributes(mapper: Mapper[Book]) -> frozenset[str]:
    """Read off `Shelf.public_columns`, never restated. A column of another
    table raises here, at the first call of `watched()`, rather than going unwatched."""
    import shelf

    return frozenset(mapper.get_property_by_column(column).key for column in shelf.Shelf.public_columns())


# ── Reading the shelf and writing the two columns ────────────────────────────


def _public_ids(session: Session, ids: Collection[int] | None) -> set[int]:
    """Which of `ids` a harvester sees now, or every such id for None. Asked of
    the Shelf, which is the rule's one home."""
    if ids is not None and not ids:
        return set()
    import shelf

    query = shelf.Shelf.seen_by_the_public(session).select(Book.id)
    if ids is not None:
        query = query.filter(Book.id.in_(list(ids)))
    return {row[0] for row in query.all()}


def _stamp(session: Session, ids: Collection[int], now: datetime) -> None:
    """Move the datestamp of every Book in `ids`: on the object where the session
    holds it, so the flush writes it and the object stays true, else in SQL."""
    rest: list[int] = []
    for book_id in ids:
        held = session.identity_map.get(identity_key(Book, book_id))
        if held is not None and held not in session.deleted:
            held.oai_datestamp = now
        else:
            rest.append(book_id)
    if rest:
        session.connection().execute(update(_BOOKS).where(_BOOKS.c.id.in_(rest)).values(oai_datestamp=now))


def _has_served(session: Session) -> bool:
    import settings_store

    return settings_store.oai_has_served(session)


def _tombstone(session: Session, ids: Collection[int], now: datetime) -> None:
    """A deleted header for each id, once the provider has served a request."""
    if ids and _has_served(session):
        _replace_tombstones(session, ids, now)


def _replace_tombstones(session: Session, ids: Collection[int], now: datetime) -> None:
    """A deleted header for each id, replacing any older one. Delete then insert
    rather than an upsert, which each engine spells its own way."""
    if not ids:
        return
    connection = session.connection()
    connection.execute(delete(_TOMBSTONES).where(_TOMBSTONES.c.book_id.in_(list(ids))))
    connection.execute(insert(_TOMBSTONES), [{"book_id": book_id, "datestamp": now} for book_id in ids])


def _clear_tombstones(session: Session, ids: Collection[int]) -> None:
    if ids:
        session.connection().execute(delete(_TOMBSTONES).where(_TOMBSTONES.c.book_id.in_(list(ids))))


def _settle(session: Session, before: set[int], after: set[int], now: datetime) -> None:
    """Tombstone what left the public view, and clear and restamp what came back.

    A Book that came back has its datestamp moved, or a harvester holding its
    tombstone would never fetch it again. The statements run on the connection,
    so neither door sees them.
    """
    _tombstone(session, before - after, now)
    returning = after - before
    _clear_tombstones(session, returning)
    if not returning:
        return
    session.connection().execute(
        update(_BOOKS).where(_BOOKS.c.id.in_(list(returning))).values(oai_datestamp=now)
    )
    for book_id in returning:
        held = session.identity_map.get(identity_key(Book, book_id))
        if held is not None:
            session.expire(held, ["oai_datestamp"])


# ── The unit of work ─────────────────────────────────────────────────────────


@dataclass
class _Pending:
    """What one flush carries from before it to after it."""

    now: datetime
    seen: set[int] = field(default_factory=set)
    before: set[int] = field(default_factory=set)


def _state(target: object) -> InstanceState[Any]:
    return cast(InstanceState[Any], inspect(target))


def _table_of(cls: type) -> Table:
    return cast(Table, class_mapper(cls).local_table)


def _changed(target: object, attributes: Collection[str]) -> bool:
    state = _state(target)
    return any(state.attrs[name].history.has_changes() for name in attributes)


def _column_to_books(table: Table) -> Any:
    """The column of `table` naming a Book, or None where it has none."""
    return next((fk.parent for fk in table.foreign_keys if fk.column.table is _BOOKS), None)


def _reached_through(table: Table) -> Table | None:
    """The association table a child table reaches its Books through, if any."""
    return next(
        (association for cls, association in watched().associations.items() if _table_of(cls) is table),
        None,
    )


def _book_ids(session: Session, table: Table, where: Any) -> set[int]:
    """The Books whose records the rows of `table` matching `where` are part of."""
    association = _reached_through(table)
    if table is _BOOKS:
        query = select(_BOOKS.c.id)
    elif association is not None:
        own = next(fk.parent for fk in association.foreign_keys if fk.column.table is table)
        inner = select(table.c.id) if where is None else select(table.c.id).where(where)
        query = select(_column_to_books(association)).where(own.in_(inner))
        where = None
    else:
        query = select(_column_to_books(table))
    if where is not None:
        query = query.where(where)
    return set(session.connection().execute(query).scalars())


def _books_of(session: Session, row: object, watch: _Watched) -> set[int]:
    """The Books whose record `row` is part of, before and after this write."""
    table = _table_of(type(row))
    if type(row) in watch.associations:
        identity = _state(row).identity
        return set() if identity is None else _book_ids(session, table, table.c.id == identity[0])
    key = _column_to_books(table).key
    history = _state(row).attrs[key].history
    named = {value for value in (*history.unchanged, *history.added, *history.deleted) if value is not None}
    # An expired row has no history for a column it was not written through:
    # read it, or a child edited after a commit would stamp nothing.
    return named or {value for value in (getattr(row, key),) if value is not None}


def _before_flush(session: Session, _context: UOWTransaction, _instances: object) -> None:
    if session.info.get(_SUSPENDED):
        return
    watch = watched()
    pending = _Pending(now=datestamp_now())
    touched = _new_rows(session, watch, pending) | _dirty_rows(session, watch, pending)
    touched |= _deleted_rows(session, watch, pending)
    _stamp(session, touched - _deleted_books(session), pending.now)
    pending.before = _public_ids(session, pending.seen)
    session.info[_PENDING] = pending


def _new_rows(session: Session, watch: _Watched, pending: _Pending) -> set[int]:
    """Stamp each new Book and return the Books each new child row joins."""
    touched: set[int] = set()
    for row in session.new:
        if isinstance(row, Book):
            row.oai_datestamp = pending.now
        elif type(row) in watch.children:
            touched |= _books_of(session, row, watch)
    return touched


def _dirty_rows(session: Session, watch: _Watched, pending: _Pending) -> set[int]:
    """Note each changed Book for the Shelf and return the Books whose record changed."""
    touched: set[int] = set()
    for row in session.dirty:
        # `dirty` holds a Book anything was assigned to, even its own value; one
        # with no net change cannot have left the public view, and asking the
        # Shelf about it would cost two SELECTs on a flush that wrote nothing.
        if isinstance(row, Book) and session.is_modified(row):
            _note_a_public_change(row, watch, pending)
            if _changed(row, watch.book_attributes):
                touched.add(row.id)
        elif type(row) in watch.children and _changed(row, watch.children[type(row)]):
            touched |= _books_of(session, row, watch)
    return touched


def _note_a_public_change(row: Book, watch: _Watched, pending: _Pending) -> None:
    """Note `row` for the Shelf where a column the public shelf reads changed.

    Any other change leaves it where it was, so asking would cost two SELECTs
    on every edit, a tag added or an identifier recorded, for no answer: the
    export and identifier backfill cost tests in `tests/routers/` measure it.
    """
    if _changed(row, watch.public_attributes):
        pending.seen.add(row.id)


def _deleted_rows(session: Session, watch: _Watched, pending: _Pending) -> set[int]:
    """Note each deleted Book for the Shelf and return the Books a deleted child left."""
    touched: set[int] = set()
    for row in session.deleted:
        if isinstance(row, Book):
            pending.seen.add(row.id)
        elif type(row) in watch.children:
            touched |= _books_of(session, row, watch)
    return touched


def _deleted_books(session: Session) -> set[int]:
    return {row.id for row in session.deleted if isinstance(row, Book)}


def _after_flush(session: Session, _context: UOWTransaction) -> None:
    pending = session.info.pop(_PENDING, None)
    if pending is None:
        return
    # A new Book is not asked about: its id was never issued before, a restore
    # included (`wholesale` raises the counter past every tombstone), so it
    # carries no tombstone to clear and has left nothing.
    _settle(session, pending.before, _public_ids(session, pending.seen), pending.now)


# ── A bulk statement through the session ─────────────────────────────────────


def _set_columns(statement: Update) -> set[str] | None:
    """The column names an UPDATE sets, or None where they cannot be read.

    `_values` is SQLAlchemy's own attribute, so a version that renames it reads
    None here and every affected Book is stamped: the wide direction.
    """
    values = getattr(statement, "_values", None)
    if not values:
        return None
    return {str(getattr(key, "key", key)) for key in values}


def _on_execute(state: ORMExecuteState) -> Any:
    """Follow a bulk INSERT, UPDATE or DELETE on a watched table. Anything
    else passes untouched."""
    table = _watched_table(state)
    if table is None:
        return None
    now = datestamp_now()
    if isinstance(state.statement, Insert):
        return _follow_insert(state, table, now)
    if table is not _BOOKS:
        return _follow_child_write(state, table, now)
    return _follow_book_write(state, now)


def _watched_table(state: ORMExecuteState) -> Table | None:
    """The watched table a bulk write targets, or None for anything else."""
    if not (state.is_update or state.is_delete or state.is_insert) or state.session.info.get(_SUSPENDED):
        return None
    # By name: an ORM statement's table is an annotated copy, never `is` the
    # metadata's own.
    name = getattr(getattr(state.statement, "table", None), "name", None)
    if name not in watched().tables:
        return None
    return Book.metadata.tables[name]


def _follow_child_write(state: ORMExecuteState, table: Table, now: datetime) -> Any:
    """A bulk UPDATE or DELETE of a child table: stamp every Book a row left or joined."""
    session, statement = state.session, state.statement
    where = getattr(statement, "whereclause", None)
    affected = _book_ids(session, table, where)
    keys = _moving_rows(session, table, statement, where)
    result = state.invoke_statement()
    _stamp(session, affected | _books_now_named(session, table, statement, keys), now)
    return result


def _follow_book_write(state: ORMExecuteState, now: datetime) -> Any:
    """A bulk UPDATE or DELETE of `books`: settle what left or came back, and
    stamp what stayed public where the statement sets a harvested column."""
    session, statement = state.session, state.statement
    affected = _book_ids(session, _BOOKS, getattr(statement, "whereclause", None))
    before = _public_ids(session, affected)
    result = state.invoke_statement()
    after = _public_ids(session, affected)
    _settle(session, before, after, now)
    columns = _set_columns(statement) if isinstance(statement, Update) else set()
    if columns is None or columns & watched().book_attributes:
        _stamp(session, affected & after, now)
    return result


def _moving_rows(session: Session, table: Table, statement: Any, where: Any) -> list[Any]:
    """The primary keys of the rows an UPDATE may move to another Book: every
    row it matches where it sets the column naming a Book, or where what it
    sets cannot be read. Read before the statement, since its own WHERE may
    no longer match once the rows have moved."""
    column = _column_to_books(table)
    if column is None or not isinstance(statement, Update):
        return []
    columns = _set_columns(statement)
    if columns is not None and column.key not in columns:
        return []
    keys = select(*table.primary_key.columns)
    return [tuple(row) for row in session.connection().execute(keys if where is None else keys.where(where))]


def _books_now_named(session: Session, table: Table, statement: Any, keys: list[Any]) -> set[int]:
    """The Books the rows `keys` name after the statement: where a moved row went.

    Where the column naming a Book is part of the key (`book_tags`), a moved
    row no longer has the key read before the statement, so it is found by the
    rest of its key instead. That can name Books the statement did not touch,
    which stamps too many: the wide direction.
    """
    if not keys:
        return set()
    column = _column_to_books(table)
    primary = list(table.primary_key.columns)
    if not table.primary_key.columns.contains_column(column):
        query = select(column).where(tuple_(*primary).in_(keys))
        return set(session.connection().execute(query).scalars())
    target = _literal_target(statement, column)
    if target is not None:
        return {target}
    return _named_by_the_rest_of_the_key(session, column, primary, keys)


def _named_by_the_rest_of_the_key(
    session: Session, column: Any, primary: list[Any], keys: list[Any]
) -> set[int]:
    """The Books naming a row whose key, less `column`, is one of `keys`'.
    Every Book the table names where the key is `column` alone."""
    rest = [index for index, key in enumerate(primary) if key is not column]
    query = select(column)
    if rest:
        query = query.where(
            tuple_(*(primary[i] for i in rest)).in_([tuple(k[i] for i in rest) for k in keys])
        )
    return set(session.connection().execute(query).scalars())


def _literal_target(statement: Any, column: Any) -> int | None:
    """The Book an UPDATE moves rows to, where it sets `column` to one bound
    value; None where it sets an expression or cannot be read."""
    values = getattr(statement, "_values", None) or {}
    for key, value in values.items():
        if str(getattr(key, "key", key)) == column.key and isinstance(value, BindParameter):
            return value.value if isinstance(value.value, int) else None
    return None


def _inserted_books(state: ORMExecuteState, column: Any) -> set[int] | None:
    """The Books a bulk INSERT's rows name, read off its parameters, or None
    where any row's Book cannot be read there: an INSERT from a SELECT."""
    statement = state.statement
    if getattr(statement, "select", None) is not None:
        return None
    parameters = state.parameters
    rows: list[Mapping[str, Any]] = (
        [] if not parameters else [parameters] if isinstance(parameters, Mapping) else list(parameters)
    )
    values = getattr(statement, "_values", None) or {}
    if values:
        rows.append(
            {str(getattr(key, "key", key)): getattr(value, "value", value) for key, value in values.items()}
        )
    named = [row.get(column.key) for row in rows]
    ids = {book_id for book_id in named if isinstance(book_id, int)}
    if not named or len(ids) < len(set(named)):
        return None
    return ids


def _follow_insert(state: ORMExecuteState, table: Table, now: datetime) -> Any:
    """A new Book is stamped by the flush, and a new row of a table
    reached through an association joins no record until it is associated. A
    child row naming its Book stamps that Book; one whose Book cannot be read
    from the statement is refused rather than missed."""
    column = _column_to_books(table)
    if table is _BOOKS or column is None:
        return None
    books = _inserted_books(state, column)
    if books is None:
        raise BulkInsertRefused(
            f"A bulk INSERT into {table.name} names its Books in no parameter harvest.py can read: "
            "give each row's book id as a value, or add the rows through the ORM."
        )
    result = state.invoke_statement()
    _stamp(state.session, books, now)
    return result


# ── A restore ────────────────────────────────────────────────────────────────


@contextmanager
def wholesale(session: Session) -> Iterator[None]:
    """Replace every row with both doors closed, then settle the result as a whole.

    A restore can change any record to anything, so afterwards every Book's
    datestamp is now and a harvester refetches all of them, and every id public
    before and not after is tombstoned. Settled from the two id sets rather than
    row by row, because the archive's own tombstones arrive in the same insert.

    **The provider has served if either side says so**, and the earlier moment is
    kept: the deployment's own harvesters saw what was public before, and the
    archive's saw what its tombstones name.

    **The Book id counter is raised past every tombstone.** The archive brings
    Books with their ids but not the counter, so on a fresh database the next
    Book would take the id of a record purged at head before the backup, and a
    harvester's record of that id would silently become a different work.
    """
    before = _public_ids(session, None)
    served_here = _first_served(session)
    session.info[_SUSPENDED] = True
    try:
        yield
    finally:
        session.info.pop(_SUSPENDED, None)
    now = datestamp_now()
    served = _keep_earliest_service(session, served_here)
    session.connection().execute(update(_BOOKS).values(oai_datestamp=now))
    after = _public_ids(session, None)
    if served:
        _replace_tombstones(session, before - after, now)
    _clear_tombstones(session, after)
    _raise_the_book_ids(session)


def _first_served(session: Session) -> str:
    """Read off the table rather than through `settings_store`, whose reads go
    through the identity map, which still holds the row the restore replaced."""
    return (
        session.connection()
        .execute(select(Setting.value).where(Setting.key == SettingKey.OAI_FIRST_SERVED.value))
        .scalar()
        or ""
    )


def _keep_earliest_service(session: Session, served_here: str) -> str:
    """Write back the earlier of this deployment's and the archive's first
    service, and return it ("" for never). Both are `datestamp_now` in ISO form,
    so the string order is the time order."""
    restored = _first_served(session)
    earliest = min((moment for moment in (served_here, restored) if moment), default="")
    if earliest != restored:
        key = SettingKey.OAI_FIRST_SERVED.value
        connection = session.connection()
        connection.execute(delete(Setting).where(Setting.key == key))
        connection.execute(insert(Setting).values(key=key, value=earliest))
    return earliest


#: Raise the Book id counter to at least `:highest`, per engine. SQLite keeps it
#: in `sqlite_sequence` (the table is `AUTOINCREMENT`), whose row exists only once
#: a Book was inserted, so it is added first where missing; Postgres keeps it in
#: the column's sequence, and `setval` never lowers it here.
_SQLITE_COUNTER_ROW: Final = (
    "INSERT INTO sqlite_sequence (name, seq) SELECT 'books', 0 "
    "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'books')"
)
_RAISE_THE_COUNTER: Final = {
    "sqlite": "UPDATE sqlite_sequence SET seq = MAX(seq, :highest) WHERE name = 'books'",
    "postgresql": (
        "SELECT setval(pg_get_serial_sequence('books', 'id'), GREATEST(:highest, "
        "(SELECT COALESCE(MAX(id), 0) FROM books), "
        "COALESCE(pg_sequence_last_value(pg_get_serial_sequence('books', 'id')::regclass), 0)))"
    ),
}


def _raise_the_book_ids(session: Session) -> None:
    highest = session.connection().execute(select(func.max(_TOMBSTONES.c.book_id))).scalar()
    if highest is None:
        return
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.execute(text(_SQLITE_COUNTER_ROW))
    connection.execute(text(dialect.for_bind(connection, **_RAISE_THE_COUNTER)), {"highest": highest})


event.listen(Session, "before_flush", _before_flush)
event.listen(Session, "after_flush_postexec", _after_flush)
event.listen(Session, "do_orm_execute", _on_execute)
