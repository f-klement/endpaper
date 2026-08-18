"""Tests for backend/schema.py: the Alembic runner and its legacy adoption.

The risky case is not a fresh install, it is a database that has been running
since before Alembic existed. These tests build such a database on purpose and
then check it is adopted without losing data.
"""

import pytest
from sqlalchemy import inspect, text

import models  # noqa: F401  (registers the tables on Base.metadata)
import schema
from database import Base, engine


def drop_everything() -> None:
    """A truly empty database, `alembic_version` included.

    That table is not part of Base.metadata, so `drop_all` leaves it behind and
    Alembic would believe the absent schema was already at head.
    """
    Base.metadata.drop_all(bind=engine)
    with engine.connect() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        connection.commit()


def build_pre_alembic_database() -> None:
    """Recreate the oldest shape still plausibly in the wild.

    Built by migrating to the baseline and then removing `alembic_version`,
    rather than from `Base.metadata`: the metadata describes *today's* schema,
    which has moved on since. Using it would produce a database claiming to be
    pre-Alembic while already carrying every later column, and the migration
    under test would then be asked to add columns that exist.
    """
    drop_everything()
    # The BASELINE specifically, not head: this is meant to be the schema as it
    # stood before Alembic, which is exactly what the baseline describes.
    schema.upgrade_to(schema.BASELINE_REVISION)
    with engine.connect() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        connection.commit()

    with engine.connect() as connection:
        connection.execute(text("DROP INDEX IF EXISTS uq_user_books_user_book"))
        connection.execute(
            text("INSERT INTO users (username, password_hash, is_admin) VALUES ('kim','x',1)")
        )
        connection.execute(text("INSERT INTO books (title) VALUES ('An Old Book')"))
        connection.execute(
            text("INSERT INTO user_books (user_id, book_id, status) VALUES (1,1,'unread')")
        )
        connection.execute(
            text("INSERT INTO user_books (user_id, book_id, status) VALUES (1,1,'read')")
        )
        connection.commit()


@pytest.fixture(autouse=True)
def restore_schema():
    """Leave the database as the rest of the suite expects to find it."""
    yield
    drop_everything()
    schema.upgrade_to_head()


def current_revision() -> str | None:
    with engine.connect() as connection:
        row = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return row


def table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


class TestEmptyDatabase:
    def test_creates_every_table(self):
        drop_everything()

        schema.upgrade_to_head()

        assert {"books", "users", "tags", "loans", "notes", "user_books", "book_tags"} <= (
            table_names()
        )

    def test_records_the_revision(self):
        drop_everything()
        schema.upgrade_to_head()
        assert current_revision() is not None


class TestAdoptingAPreAlembicDatabase:
    """The migration path for an installation that predates Alembic."""

    def test_is_adopted_and_brought_to_head(self):
        """Stamping at the baseline is the intermediate step, not the result.

        An unmanaged database is recognised, stamped at the revision matching
        its actual shape, and then upgraded the rest of the way like any other.
        """
        build_pre_alembic_database()
        assert "alembic_version" not in table_names()

        schema.upgrade_to_head()

        assert current_revision() is not None
        assert current_revision() != schema.BASELINE_REVISION, (
            "expected the adopted database to be upgraded past the baseline"
        )

    def test_gains_the_columns_added_after_the_baseline(self):
        # Proof the adopted database really did run the later revisions rather
        # than merely being labelled as current.
        build_pre_alembic_database()

        schema.upgrade_to_head()

        columns = {column["name"] for column in inspect(engine).get_columns("books")}
        assert {"page_count", "language", "categories"} <= columns
        assert "settings" in table_names()

    def test_keeps_existing_data(self):
        # The whole point. A migration that empties someone's catalogue is
        # worse than no migration.
        build_pre_alembic_database()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            assert connection.execute(text("SELECT title FROM books")).scalar() == "An Old Book"
            assert connection.execute(text("SELECT username FROM users")).scalar() == "kim"

    def test_applies_the_missing_unique_index(self):
        build_pre_alembic_database()

        schema.upgrade_to_head()

        indexes = {index["name"] for index in inspect(engine).get_indexes("user_books")}
        assert "uq_user_books_user_book" in indexes

    def test_collapses_duplicate_status_rows_keeping_the_latest(self):
        # The unique index cannot be created while duplicates remain, and the
        # most recent row is the status the member last chose.
        build_pre_alembic_database()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM user_books")).scalar() == 1
            assert connection.execute(text("SELECT status FROM user_books")).scalar() == "read"


class TestLegacyFixups:
    def test_adds_is_private_to_a_database_that_predates_it(self):
        drop_everything()
        with engine.connect() as connection:
            connection.execute(
                text("CREATE TABLE books (id INTEGER PRIMARY KEY, title VARCHAR(500) NOT NULL)")
            )
            connection.execute(text("INSERT INTO books (title) VALUES ('Old Book')"))
            connection.commit()

        schema.apply_legacy_fixups()

        columns = {column["name"] for column in inspect(engine).get_columns("books")}
        assert "is_private" in columns

    def test_existing_rows_default_to_public(self):
        drop_everything()
        with engine.connect() as connection:
            connection.execute(
                text("CREATE TABLE books (id INTEGER PRIMARY KEY, title VARCHAR(500) NOT NULL)")
            )
            connection.execute(text("INSERT INTO books (title) VALUES ('Old Book')"))
            connection.commit()

        schema.apply_legacy_fixups()

        with engine.connect() as connection:
            assert connection.execute(text("SELECT is_private FROM books")).scalar() == 0

    def test_is_idempotent(self):
        build_pre_alembic_database()
        schema.apply_legacy_fixups()
        schema.apply_legacy_fixups()

        indexes = {index["name"] for index in inspect(engine).get_indexes("user_books")}
        assert "uq_user_books_user_book" in indexes

    def test_does_nothing_on_an_empty_database(self):
        drop_everything()
        schema.apply_legacy_fixups()
        assert "books" not in table_names()


class TestRepeatedBoots:
    def test_upgrading_twice_is_a_no_op(self):
        # init_db() runs this on every start, so it has to be safe to repeat.
        drop_everything()
        schema.upgrade_to_head()
        first = current_revision()

        schema.upgrade_to_head()

        assert current_revision() == first

    def test_data_survives_a_second_boot(self):
        drop_everything()
        schema.upgrade_to_head()
        with engine.connect() as connection:
            connection.execute(text("INSERT INTO books (title) VALUES ('Kept')"))
            connection.commit()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            assert connection.execute(text("SELECT title FROM books")).scalar() == "Kept"


class TestHyphenatingTheAgeTags:
    """Revision 95b6a61d6668, which renames data rather than changing schema.

    The rename is only safe because migrations run before `seed_tags()`. If it
    did not happen, seeding would match on the new name, find nothing, and
    insert a second row beside the old one.
    """

    # Spelled with an escape so this file holds no literal en dash of its own.
    OLD_NAME = "Children (0\u20138)"
    NEW_NAME = "Children (0-8)"

    def build_database_with_old_tag_names(self) -> int:
        """A database one revision back, holding a tagged book. Returns the tag id."""
        drop_everything()
        schema.upgrade_to("a7feb2db74ac")
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO tags (name, category) VALUES (:name, 'age')"),
                {"name": self.OLD_NAME},
            )
            tag_id = connection.execute(
                text("SELECT id FROM tags WHERE name = :name"), {"name": self.OLD_NAME}
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO books (title, is_private, added_at, ownership) "
                    "VALUES ('Dune', 0, datetime('now'), 'owned')"
                )
            )
            book_id = connection.execute(text("SELECT id FROM books")).scalar_one()
            connection.execute(
                text("INSERT INTO book_tags (book_id, tag_id) VALUES (:b, :t)"),
                {"b": book_id, "t": tag_id},
            )
            connection.commit()
        return int(tag_id)

    def tag_names(self) -> list[str]:
        with engine.connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM tags WHERE category = 'age'")
                )
            ]

    def test_renames_the_existing_row(self):
        self.build_database_with_old_tag_names()

        schema.upgrade_to_head()

        assert self.NEW_NAME in self.tag_names()
        assert self.OLD_NAME not in self.tag_names()

    def test_keeps_the_same_tag_id(self):
        """UPDATE, not delete-and-insert: book_tags references the id."""
        tag_id = self.build_database_with_old_tag_names()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            renamed = connection.execute(
                text("SELECT name FROM tags WHERE id = :id"), {"id": tag_id}
            ).scalar_one()
        assert renamed == self.NEW_NAME

    def test_a_book_keeps_its_tag(self):
        tag_id = self.build_database_with_old_tag_names()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            links = connection.execute(
                text("SELECT tag_id FROM book_tags")
            ).scalars().all()
        assert links == [tag_id]

    def test_seeding_afterwards_does_not_duplicate_it(self):
        """The whole point of doing this as a migration rather than by hand."""
        import main

        self.build_database_with_old_tag_names()
        schema.upgrade_to_head()

        main.seed_tags()

        assert self.tag_names().count(self.NEW_NAME) == 1

    def test_the_downgrade_puts_the_name_back(self):
        from alembic import command

        self.build_database_with_old_tag_names()
        schema.upgrade_to_head()

        # Alembic directly: schema.py only ever moves forward, because the app
        # has no reason to downgrade itself at startup.
        command.downgrade(schema._alembic_config(), "a7feb2db74ac")

        assert self.OLD_NAME in self.tag_names()
