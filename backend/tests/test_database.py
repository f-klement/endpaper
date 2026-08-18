"""Tests for backend/database.py: engine setup and the session dependency."""

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
