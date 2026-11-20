"""Tests for backend/harvest.py: what moves a datestamp, and what writes a tombstone.

Every test puts the datestamp in the past first, by a write the module ignores
(`oai_datestamp` is not a harvested column), so a move is visible at the second
granularity the protocol serves.
"""

import ast
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, literal, select, update

import harvest
import settings_store
from enums import BookFormat, ClassificationScheme, LinkRelationship, RecordOrigin, SettingKey, TagCategory
from models import Book, Classification, OaiTombstone, OnlineLink, Tag, book_tags
from schemas.public import PublicBookOut
from tests.corpus import application_sources

TREE_GUARDS = {"TestNothingWritesPastBothDoors": ("application_sources",)}

BACKEND = Path(__file__).resolve().parents[1]
PAST = datetime(2001, 1, 1)

#: A value each harvested column of `books` can take. Keyed rather than derived,
#: and checked against `watched()` below, so a new public column fails here
#: until somebody says what to write into it.
NEW_VALUES = {
    "title": "Another Title",
    "subtitle": "Another Subtitle",
    "author": "Another Author",
    "isbn": "9780306406157",
    "year": 1999,
    "page_count": 321,
    "publisher": "Another Publisher",
    "description": "Another description",
    "categories": "Another category",
    "language": "de",
    "series_name": "Another Series",
    "series_index": 2.5,
    "cover_url": "https://covers.example/another.jpg",
    "format": list(BookFormat)[-1],
    "record_origin": RecordOrigin.DNB,
}


def _age(db, book_id: int) -> None:
    db.execute(update(Book).where(Book.id == book_id).values(oai_datestamp=PAST))
    db.commit()
    db.expire_all()


def _stamp_of(db, book_id: int) -> datetime:
    db.expire_all()
    return db.get(Book, book_id).oai_datestamp


def _tombstones(db) -> set[int]:
    db.expire_all()
    return {row.book_id for row in db.query(OaiTombstone)}


@pytest.fixture
def served(db):
    """The provider has answered a request, so a Book leaving is tombstoned."""
    settings_store.record_oai_service(db)


@pytest.fixture
def book(db, admin):
    row = Book(title="Chartreuse Windmill", added_by_user_id=admin["user"]["id"])
    db.add(row)
    db.commit()
    _age(db, row.id)
    return row.id


@pytest.fixture
def tag(db, book):
    row = Tag(name="windmills", category=TagCategory.CUSTOM)
    carrier = db.get(Book, book)
    carrier.tags.append(row)
    db.commit()
    _age(db, book)
    return row.id


class TestTheWatchedSetIsThePublicRecord:
    def test_every_public_field_is_watched(self):
        watched = harvest.watched().book_attributes
        assert {harvest._DERIVED.get(name, name) for name in PublicBookOut.model_fields} == set(watched)

    def test_every_watched_column_has_a_value_here(self):
        scalar = {name for name in harvest.watched().book_attributes if name in Book.__table__.columns} - {
            "id"
        }
        assert scalar == set(NEW_VALUES)


class TestAWriteToTheRecordMovesItsDatestamp:
    @pytest.mark.parametrize("column", sorted(NEW_VALUES))
    def test_an_orm_write_to_a_harvested_column_moves_it(self, db, book, column):
        setattr(db.get(Book, book), column, NEW_VALUES[column])
        db.commit()
        assert _stamp_of(db, book) > PAST

    def test_a_bulk_update_of_a_harvested_column_moves_it(self, db, book):
        db.execute(update(Book).where(Book.id == book).values(title="Bulk"))
        db.commit()
        assert _stamp_of(db, book) > PAST

    def test_a_write_to_a_withheld_column_does_not(self, db, book):
        """A moving datestamp would tell a harvester something it cannot see changed."""
        db.get(Book, book).location = "Upstairs"
        db.flush()
        db.execute(update(Book).where(Book.id == book).values(location="Downstairs"))
        db.commit()
        assert _stamp_of(db, book) == PAST

    def test_adding_a_classification_moves_it(self, db, book):
        db.add(Classification(book_id=book, scheme=ClassificationScheme.DDC, number="004"))
        db.commit()
        assert _stamp_of(db, book) > PAST

    def test_editing_an_online_link_moves_it(self, db, book):
        link = OnlineLink(book_id=book, url="https://example.org/a", relation=LinkRelationship.RESOURCE)
        db.add(link)
        db.commit()
        _age(db, book)
        link.label = "Read online"
        db.commit()
        assert _stamp_of(db, book) > PAST

    def test_renaming_a_tag_moves_every_book_carrying_it(self, db, book, tag):
        db.get(Tag, tag).name = "mills"
        db.commit()
        assert _stamp_of(db, book) > PAST

    def test_a_bulk_delete_of_a_tag_link_moves_it(self, db, book, tag):
        """The shape of `routers/books.delete_tag`, which bypasses the unit of work."""
        db.execute(book_tags.delete().where(book_tags.c.tag_id == tag))
        db.commit()
        assert _stamp_of(db, book) > PAST

    @pytest.mark.parametrize("spelling", ["parameters", "values"])
    def test_a_bulk_insert_into_a_child_table_moves_it(self, db, book, spelling):
        row = {"book_id": book, "url": "https://example.org/b", "relation": LinkRelationship.RESOURCE}
        if spelling == "values":
            db.execute(insert(OnlineLink).values(**row))
        else:
            db.execute(insert(OnlineLink), [row])
        db.commit()
        assert _stamp_of(db, book) > PAST

    def test_a_bulk_update_moving_a_child_row_moves_the_book_it_joins(self, db, admin, book):
        """Read after the statement: its own WHERE no longer matches the moved row."""
        other = Book(title="Second Windmill", added_by_user_id=admin["user"]["id"])
        db.add(other)
        db.commit()
        _age(db, other.id)
        db.add(Classification(book_id=book, scheme=ClassificationScheme.DDC, number="004"))
        db.commit()
        db.execute(update(Classification).where(Classification.book_id == book).values(book_id=other.id))
        db.commit()
        assert _stamp_of(db, other.id) > PAST

    @pytest.mark.parametrize("spelling", ["a value", "an expression"])
    def test_a_bulk_update_moving_a_tag_link_moves_the_book_it_joins(self, db, admin, book, tag, spelling):
        """`book_tags` is keyed by the Book column it moves, so the key read
        before the statement no longer names the moved row after it."""
        other = Book(title="Second Windmill", added_by_user_id=admin["user"]["id"])
        db.add(other)
        db.commit()
        _age(db, other.id)
        target = other.id if spelling == "a value" else book_tags.c.book_id + (other.id - book)
        db.execute(update(book_tags).where(book_tags.c.book_id == book).values(book_id=target))
        db.commit()
        assert _stamp_of(db, other.id) > PAST

    def test_a_bulk_insert_naming_no_book_is_refused(self, db, book):
        """An INSERT from a SELECT: its Books cannot be read off the statement."""
        rows = select(literal(book), literal(ClassificationScheme.DDC.value), literal("1"))
        statement = insert(Classification).from_select(["book_id", "scheme", "number"], rows)
        with pytest.raises(harvest.BulkInsertRefused):
            db.execute(statement)


@pytest.mark.usefixtures("served")
class TestEveryRouteOutOfThePublicViewLeavesATombstone:
    def test_trashing_a_public_book(self, db, book):
        db.get(Book, book).deleted_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        assert _tombstones(db) == {book}

    def test_making_a_public_book_private(self, db, book):
        db.get(Book, book).is_private = True
        db.commit()
        assert _tombstones(db) == {book}

    def test_making_a_public_book_private_in_bulk(self, db, book):
        db.execute(update(Book).where(Book.id == book).values(is_private=True))
        db.commit()
        assert _tombstones(db) == {book}

    def test_deleting_a_public_book_as_a_merge_does(self, db, book):
        db.delete(db.get(Book, book))
        db.commit()
        assert _tombstones(db) == {book}

    def test_a_book_never_public_leaves_none(self, db, admin):
        """A tombstone for it would publish the id of a private Book."""
        private = Book(title="Diary", is_private=True, added_by_user_id=admin["user"]["id"])
        db.add(private)
        db.commit()
        private.title = "Diary, revised"
        db.commit()
        db.delete(private)
        db.commit()
        assert _tombstones(db) == set()

    def test_a_book_that_returns_loses_its_tombstone_and_moves(self, db, book):
        db.get(Book, book).is_private = True
        db.commit()
        _age(db, book)
        db.get(Book, book).is_private = False
        db.commit()
        assert _tombstones(db) == set()
        assert _stamp_of(db, book) > PAST


class TestNoTombstoneBeforeTheFirstRequestServed:
    """Owner's decision on issue #176: a record that left before any harvester
    could have seen it publishes neither its id nor the day it left."""

    def test_a_book_leaving_before_the_provider_served_leaves_none(self, db, book):
        db.get(Book, book).is_private = True
        db.commit()
        assert _tombstones(db) == set()

    def test_a_book_leaving_after_it_leaves_one_with_the_switch_off(self, db, book, served):
        assert settings_store.get_bool(db, SettingKey.OAI_PROVIDER_ENABLED) is False
        db.get(Book, book).is_private = True
        db.commit()
        assert _tombstones(db) == {book}


class TestNothingWritesPastBothDoors:
    """The residual: text SQL and a bare `Connection` are invisible to the events.
    Read off the application modules, which leave out tests and migrations (a
    migration runs before any harvest).

    What these let through: a `Connection` reached under another name than the
    calls `connection()` and `connect()`, such as `engine.begin()` or
    `session.bind`, and text SQL built from a variable rather than a literal."""

    WATCHED = harvest.watched().tables

    #: Modules allowed a `Connection` of their own, and why.
    CONNECTION_TAKERS = {
        # The one writer past both doors, by design: it writes the two columns
        # the doors exist to keep, and must not trigger itself.
        "harvest.py": "the harvest's own statements",
        # The migration runner, which runs before any session exists and writes
        # through Alembic, which follows nothing.
        "schema.py": "Alembic and the legacy fixups",
        # Creates and checks the Postgres database; writes no table.
        "scripts/postgres_database.py": "the database itself, before any table",
    }

    def test_no_application_module_writes_these_tables_as_text(self):
        """Read as the call `text(...)` with a literal argument, so a docstring
        naming an UPDATE is not one."""
        verbs = ("UPDATE ", "INSERT INTO ", "DELETE FROM ")
        found = []
        for name, source in application_sources().items():
            for node in ast.walk(ast.parse(source, name)):
                if not (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "attr", getattr(node.func, "id", "")) == "text"
                ):
                    continue
                literal = " ".join(
                    arg.value
                    for arg in ast.walk(node)
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                ).upper()
                if any(f"{verb}{table.upper()}" in literal for verb in verbs for table in self.WATCHED):
                    found.append(f"{name}:{node.lineno}")
        assert found == []

    def test_no_application_module_runs_driver_sql(self):
        assert [name for name, source in application_sources().items() if "exec_driver_sql" in source] == []

    def test_no_application_module_takes_a_connection_of_its_own(self):
        """`session.connection()` or `engine.connect()`: a statement executed on
        either passes neither door."""
        found = []
        for name, source in application_sources().items():
            if name in self.CONNECTION_TAKERS:
                continue
            for node in ast.walk(ast.parse(source, name)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and (node.func.attr == "connection" or (node.func.attr == "connect" and not node.args))
                ):
                    found.append(f"{name}:{node.lineno}")
        assert found == []


def test_importing_models_alone_registers_the_events():
    """Any process that can name a Book has the listeners, a migration script or a
    one off job included, because `models.py` imports this module at its foot."""
    probe = (
        "import sys, models; from sqlalchemy import event; from sqlalchemy.orm import Session; "
        "h = sys.modules['harvest']; "
        "assert event.contains(Session, 'before_flush', h._before_flush); "
        "assert event.contains(Session, 'do_orm_execute', h._on_execute)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=BACKEND, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
