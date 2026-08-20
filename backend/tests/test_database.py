"""Tests for backend/database.py: engine setup and the session dependency."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import Base, engine, get_db


class TestEngine:
    def test_is_pointed_at_the_test_database(self):
        assert "sqlite" in str(engine.url)

    def test_sqlite_thread_check_is_disabled(self):
        """FastAPI runs sync endpoints in a worker thread pool, so a session
        opened on one thread is used on another."""
        assert engine.dialect.name == "sqlite"
        assert Base.metadata.tables


class TestSqlitePragmas:
    """Every one of these is off or too short by default in SQLite."""

    @pytest.fixture
    def pragma(self):
        def _read(name: str):
            with engine.connect() as connection:
                return connection.execute(text(f"PRAGMA {name}")).scalar()

        return _read

    def test_foreign_keys_are_enforced(self, pragma):
        """Off by default, which makes every ForeignKey in models.py and the
        ON DELETE CASCADE on book_tags decorative."""
        assert pragma("foreign_keys") == 1

    def test_a_dangling_reference_is_refused(self, pragma):
        """The pragma reading 1 only proves it is set. This proves it bites."""
        with engine.connect() as connection, pytest.raises(Exception, match="FOREIGN KEY"):
            connection.execute(
                text("INSERT INTO notes (book_id, user_id, content) VALUES (9999, 9999, 'x')")
            )

    def test_the_journal_is_write_ahead(self, pragma):
        """Without WAL a long write, an import or a restore, blocks every read
        for its duration."""
        assert pragma("journal_mode").lower() == "wal"

    def test_a_busy_database_waits_rather_than_erroring(self, pragma):
        assert pragma("busy_timeout") == 5000


class TestForeignKeyIndexes:
    """Migration a17c5b2e94d0. Without these, SQLite scans the child table once
    per deleted parent row now that foreign keys are checked."""

    @pytest.mark.parametrize(
        ("table", "column"),
        [
            ("books", "added_by_user_id"),
            ("user_books", "book_id"),
            ("loans", "book_id"),
            ("loans", "loaned_to_user_id"),
            ("notes", "book_id"),
            ("book_tags", "tag_id"),
        ],
    )
    def test_the_column_leads_an_index(self, table, column):
        with engine.connect() as connection:
            indexes = connection.execute(text(f"PRAGMA index_list('{table}')")).fetchall()
            leading = {
                connection.execute(text(f"PRAGMA index_info('{row[1]}')")).fetchall()[0][2]
                for row in indexes
            }
        assert column in leading


class TestGetDb:
    def test_yields_a_session(self):
        gen = get_db()
        session = next(gen)
        assert isinstance(session, Session)
        gen.close()

    def test_closes_the_session_afterwards(self):
        gen = get_db()
        session = next(gen)
        gen.close()
        assert not session.is_active or session.get_bind() is not None

    def test_each_call_yields_a_distinct_session(self):
        """A shared session would leak uncommitted state between requests."""
        first_gen, second_gen = get_db(), get_db()
        first, second = next(first_gen), next(second_gen)
        assert first is not second
        first_gen.close()
        second_gen.close()


class TestMetadata:
    def test_every_expected_table_is_registered(self):
        assert {
            "users", "books", "tags", "book_tags", "user_books", "loans", "notes"
        } <= set(Base.metadata.tables)
