"""Tests for backend/schema.py: the Alembic runner and its legacy adoption.

The risky case is not a fresh install, it is a database that has been running
since before Alembic existed. These tests build such a database on purpose and
then check it is adopted without losing data.
"""

import json
import os
import random
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import BaseModel
from sqlalchemy import CheckConstraint, String, create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

import credentials
import filing
import models  # registers the tables on Base.metadata
import schema
import targets
from database import Base, engine
from dialect import SwappedRule
from enums import (
    AuthorityScheme,
    BookFormat,
    BookIdentifierScheme,
    ClassificationScheme,
)
from migrations.versions import (
    a6d3f92c7b14_a_nul_clause_on_two_glob_rules as a_nul_clause_on_two_glob_rules,
)
from migrations.versions import (
    b2e94f7c1a03_where_a_book_file_is_said_to_be as where_a_book_file_is_said_to_be,
)
from migrations.versions import (
    b8f4c1a7e309_bound_the_bytes_three_columns_never_had as bound_the_bytes,
)
from migrations.versions import (
    c7b0a3e5d281_what_a_store_calls_a_book as what_a_store_calls_a_book,
)
from migrations.versions import (
    f1c30ab27d84_store_the_shelf_key_beside_the_number as revision,
)
from migrations.versions import (
    f4a1c62d0b97_bind_every_text_ceiling_on_bytes_too as bind_every_text_ceiling,
)
from migrations.versions.b8f4c1a7e309_bound_the_bytes_three_columns_never_had import (
    AddedRule,
)
from schemas.opds import OpdsServerIn
from tests.test_filing import CORPUS
from tests.test_house_rules import BACKEND, _python_sources


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


class TestLendingToSomeoneWithoutAnAccount:
    """Revision d5c31b7a09fe, which rewrites the loans table.

    Batch mode rebuilds a SQLite table by reflecting it, and the partial unique
    index on `loans` is the thing most likely to come back subtly wrong: as a
    plain unique index it would forbid ever lending a book twice. So the
    migration drops it first and recreates it, and these tests check both the
    new column and the old rule.
    """

    PREVIOUS = "f2b8d6a03c17"

    def build_database_with_a_loan(self) -> None:
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO users (username, password_hash, is_admin) VALUES ('kim','x',1)")
            )
            connection.execute(
                text(
                    "INSERT INTO books (title, is_private, added_at, ownership) "
                    "VALUES ('Dune', 0, datetime('now'), 'owned')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO loans (book_id, loaned_to_user_id, loaned_by_user_id, "
                    "loaned_at) VALUES (1, 1, 1, datetime('now'))"
                )
            )
            connection.commit()

    def test_the_existing_loan_survives(self):
        self.build_database_with_a_loan()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM loans")).scalar() == 1
            assert (
                connection.execute(text("SELECT loaned_to_user_id FROM loans")).scalar() == 1
            )

    def test_the_borrower_name_column_arrives(self):
        self.build_database_with_a_loan()

        schema.upgrade_to_head()

        columns = {column["name"] for column in inspect(engine).get_columns("loans")}
        assert "loaned_to_name" in columns

    def test_a_loan_with_no_member_becomes_possible(self):
        self.build_database_with_a_loan()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO loans (book_id, loaned_to_name, loaned_by_user_id, "
                    "loaned_at, returned_at) "
                    "VALUES (1, 'the neighbour', 1, datetime('now'), datetime('now'))"
                )
            )
            connection.commit()
            assert connection.execute(text("SELECT COUNT(*) FROM loans")).scalar() == 2

    def test_naming_both_borrowers_is_refused_by_the_database(self):
        self.build_database_with_a_loan()

        schema.upgrade_to_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO loans (book_id, loaned_to_user_id, loaned_to_name, "
                    "loaned_by_user_id, loaned_at) "
                    "VALUES (1, 1, 'the neighbour', 1, datetime('now'))"
                )
            )

    def test_the_open_loan_index_is_still_partial(self):
        """A plain unique index would make a returned book unlendable for good."""
        self.build_database_with_a_loan()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(
                text("UPDATE loans SET returned_at = datetime('now') WHERE id = 1")
            )
            connection.execute(
                text(
                    "INSERT INTO loans (book_id, loaned_to_user_id, loaned_by_user_id, "
                    "loaned_at) VALUES (1, 1, 1, datetime('now'))"
                )
            )
            connection.commit()
            assert connection.execute(text("SELECT COUNT(*) FROM loans")).scalar() == 2

    def test_two_open_loans_on_one_book_are_still_refused(self):
        self.build_database_with_a_loan()

        schema.upgrade_to_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO loans (book_id, loaned_to_name, loaned_by_user_id, "
                    "loaned_at) VALUES (1, 'the neighbour', 1, datetime('now'))"
                )
            )

    def test_the_downgrade_drops_loans_it_cannot_represent(self):
        from alembic import command

        self.build_database_with_a_loan()
        schema.upgrade_to_head()
        with engine.connect() as connection:
            connection.execute(
                text("UPDATE loans SET returned_at = datetime('now') WHERE id = 1")
            )
            connection.execute(
                text(
                    "INSERT INTO loans (book_id, loaned_to_name, loaned_by_user_id, "
                    "loaned_at) VALUES (1, 'the neighbour', 1, datetime('now'))"
                )
            )
            connection.commit()

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        with engine.connect() as connection:
            remaining = connection.execute(text("SELECT id FROM loans")).scalars().all()
        assert remaining == [1]


class TestUpgradingStoredCovers:
    """Revision b8e2f04c17aa, which rewrites data rather than schema.

    The column validator applies to new writes, but it fires on a write, and a
    book enriched from Google last month is not going to be written again. Its
    cover would stay blocked by the browser for good.

    The second statement follows the same argument to its end: a legacy
    `data:` or `//host` value is refused on every new write and nothing
    rewrites an old row to find out.
    """

    PREVIOUS = "d5c31b7a09fe"

    def build_database_with_covers(self) -> None:
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        with engine.connect() as connection:
            for title, cover in (
                ("Insecure", "http://books.google.com/c.jpg"),
                ("Secure", "https://covers.openlibrary.org/b/isbn/1-L.jpg"),
                ("Uploaded", "/covers/3.jpg"),
                ("None", None),
                ("Script", "javascript:alert(1)"),
                ("Data", "data:image/svg+xml,<svg/>"),
                ("SchemeRelative", "//evil.invalid/x.jpg"),
                ("Traversal", "/covers/../api/books/export"),
                ("ShoutedScheme", "HTTPS://covers.openlibrary.org/b/isbn/2-L.jpg"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO books (title, cover_url, is_private, added_at, "
                        "ownership) VALUES (:t, :c, 0, datetime('now'), 'owned')"
                    ),
                    {"t": title, "c": cover},
                )
            connection.commit()

    def cover_of(self, title: str) -> str | None:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT cover_url FROM books WHERE title = :t"), {"t": title}
            ).scalar()

    def test_an_http_cover_is_upgraded(self):
        self.build_database_with_covers()

        schema.upgrade_to_head()

        assert self.cover_of("Insecure") == "https://books.google.com/c.jpg"

    def test_an_https_cover_is_untouched(self):
        self.build_database_with_covers()

        schema.upgrade_to_head()

        assert self.cover_of("Secure") == "https://covers.openlibrary.org/b/isbn/1-L.jpg"

    def test_a_locally_uploaded_cover_is_untouched(self):
        self.build_database_with_covers()

        schema.upgrade_to_head()

        assert self.cover_of("Uploaded") == "/covers/3.jpg"

    def test_a_book_with_no_cover_is_untouched(self):
        self.build_database_with_covers()

        schema.upgrade_to_head()

        assert self.cover_of("None") is None

    def test_an_uppercase_scheme_is_kept(self):
        """The match is case-insensitive on the scheme, exactly like
        `covers.is_renderable`. The two disagreeing about one row is the whole
        class of bug this release keeps finding."""
        self.build_database_with_covers()

        schema.upgrade_to_head()

        assert self.cover_of("ShoutedScheme") is not None

    @pytest.mark.parametrize(
        "title", ["Script", "Data", "SchemeRelative", "Traversal"]
    )
    def test_a_legacy_value_no_image_tag_should_load_is_nulled(self, title):
        """Nothing rewrites these rows, so nothing else would ever refuse them.
        `data:` is still listed in `img-src`, so such a row does not merely
        fail to load: it renders whatever it carries."""
        self.build_database_with_covers()

        schema.upgrade_to_head()

        assert self.cover_of(title) is None


class TestCollectionsAndTheIsbnIndexThatSurvivesThem:
    """Revision c2f95a80d417, which rewrites the books table.

    The rewrite is the point of these tests rather than the new column. Batch
    mode rebuilds a SQLite table by reflecting it, and `uq_books_isbn_single_copy`
    is a **partial** unique index: coming back plain, it would forbid a second
    copy of any title on every upgraded database, silently, since nothing else
    in the app would notice.

    `d5c31b7a09fe` had to drop and recreate `uq_loans_one_open_per_book` around
    exactly this step because that reflection was lossy. It is not lossy here on
    alembic 1.19.1 with SQLAlchemy 2.0.52, which is why this migration does no
    such dance, and which is what these tests hold. The suite's schema is the
    migrations', so this revision does run once per worker at session start, and
    it runs against an **empty** `books` table: a partial index coming back
    plain refuses nothing until a second copy of a title is written, so **no
    other test in the suite puts `books` through this migration carrying the
    rows the index exists to permit**, and the dependency bot automerges minor
    and patch releases of both libraries.
    """

    PREVIOUS = "b1e7c94a2d05"

    def build_database_with_two_copies(self) -> None:
        """A library holding two paperbacks of one title, before collections.

        Both rows carry the same ISBN and the same `copy_group`, which is the
        state the partial index exists to permit and a plain unique index would
        have refused.
        """
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO users (username, password_hash, is_admin) VALUES ('kim','x',1)")
            )
            for _ in range(2):
                connection.execute(
                    text(
                        "INSERT INTO books (title, isbn, copy_group, added_by_user_id) "
                        "VALUES ('Dune', '9780441013593', 'abc123', 1)"
                    )
                )
            connection.commit()

    def test_the_collection_column_arrives(self):
        self.build_database_with_two_copies()

        schema.upgrade_to_head()

        columns = {column["name"] for column in inspect(engine).get_columns("books")}
        assert "collection_id" in columns

    def test_existing_books_are_unfiled_rather_than_given_a_collection(self):
        """No backfill and no invented name: see the migration's docstring."""
        self.build_database_with_two_copies()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM books WHERE collection_id IS NOT NULL")
                ).scalar()
                == 0
            )
            assert connection.execute(text("SELECT COUNT(*) FROM collections")).scalar() == 0

    def test_the_copies_survive_the_table_rewrite(self):
        self.build_database_with_two_copies()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM books")).scalar() == 2

    def test_the_isbn_index_is_still_partial(self):
        """The regression this class exists for. A plain unique index here makes
        a second copy of any title impossible, on every database that upgraded."""
        self.build_database_with_two_copies()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO books (title, isbn, copy_group, added_by_user_id) "
                    "VALUES ('Dune', '9780441013593', 'abc123', 1)"
                )
            )
            connection.commit()
            assert connection.execute(text("SELECT COUNT(*) FROM books")).scalar() == 3

    def test_a_second_uncopied_book_with_one_isbn_is_still_refused(self):
        """The other half, and the reason the index was made partial rather than
        dropped: a re-scan of a book already on the shelf is still a collision."""
        self.build_database_with_two_copies()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO books (title, isbn, added_by_user_id) "
                    "VALUES ('Neuromancer', '9780441569595', 1)"
                )
            )
            connection.commit()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO books (title, isbn, added_by_user_id) "
                    "VALUES ('Neuromancer again', '9780441569595', 1)"
                )
            )

    def test_deleting_a_collection_unfiles_its_books_on_an_upgraded_database(self):
        """`ON DELETE SET NULL` reaches an upgraded database too. The constraint
        is added inside the batch rewrite, which is the step most likely to drop
        it, and `PRAGMA foreign_keys=ON` is what makes it do anything."""
        self.build_database_with_two_copies()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            # `name_folded` by hand: e7b3d02a5c94 made it NOT NULL, and the
            # `@validates` hook that fills it in only fires through the ORM.
            connection.execute(
                text("INSERT INTO collections (name, name_folded) VALUES ('Ebooks','ebooks')")
            )
            connection.execute(text("UPDATE books SET collection_id = 1"))
            connection.execute(text("DELETE FROM collections WHERE id = 1"))
            connection.commit()
            assert connection.execute(text("SELECT COUNT(*) FROM books")).scalar() == 2
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM books WHERE collection_id IS NOT NULL")
                ).scalar()
                == 0
            )


class TestWideningTheClassificationNumber:
    """Revision b7d41f0a2c95, which resizes a column rather than adding one.

    SQLite does not enforce a `VARCHAR` length, so nothing here would fail
    without the migration on this engine. What the batch rewrite can still get
    wrong is the table around the column: the unique index that stops
    enrichment depositing a second copy of every heading is rebuilt with it, and
    a rewrite that dropped it would be silent until two identical rows appeared.
    """

    HEADING = (
        "United States -- History -- Civil War, 1861-1865 -- "
        "Social aspects -- Juvenile literature"
    )

    def build_database_with_a_heading(self) -> None:
        """A database one revision back, holding a book and a short heading."""
        drop_everything()
        schema.upgrade_to("e2c74a91b5d8")
        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO books (title, is_private, added_at, ownership) "
                    "VALUES ('Clean Code', 0, datetime('now'), 'owned')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO classifications (book_id, scheme, number, label) "
                    "VALUES (1, 'ddc', '005.133', NULL)"
                )
            )
            connection.commit()

    def numbers(self) -> list[str]:
        with engine.connect() as connection:
            return list(
                connection.execute(
                    text("SELECT number FROM classifications ORDER BY id")
                ).scalars()
            )

    def test_the_column_takes_a_heading_no_call_number_would_reach(self):
        self.build_database_with_a_heading()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            # `sort_key` by hand, because this is raw SQL rather than the ORM:
            # `f1c30ab27d84` made the column NOT NULL and
            # `Classification._file_the_number` is what fills it everywhere else.
            connection.execute(
                text(
                    "INSERT INTO classifications "
                    "(book_id, scheme, number, label, sort_key) "
                    "VALUES (1, 'lcsh', :number, NULL, :sort_key)"
                ),
                {
                    "number": self.HEADING,
                    "sort_key": filing.sort_key_for("lcsh", self.HEADING),
                },
            )
            connection.commit()
        assert self.HEADING in self.numbers()

    def test_the_heading_already_stored_survives_the_rewrite(self):
        self.build_database_with_a_heading()

        schema.upgrade_to_head()

        assert self.numbers() == ["005.133"]

    def test_the_unique_index_survives_the_rewrite(self):
        """Batch mode rebuilds the table by reflecting it, and losing this index
        would let every re-run of enrichment deposit a second copy of a
        heading."""
        self.build_database_with_a_heading()

        schema.upgrade_to_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO classifications (book_id, scheme, number, label) "
                    "VALUES (1, 'ddc', '005.133', NULL)"
                )
            )

    def test_the_downgrade_deletes_a_row_the_narrow_column_could_not_hold(self):
        """A row the schema says cannot exist is worse than a row that is gone:
        narrowing a column with over-long values in it fails outright on a real
        database and keeps them silently on SQLite."""
        from alembic import command

        self.build_database_with_a_heading()
        schema.upgrade_to_head()
        with engine.connect() as connection:
            # `sort_key` by hand, because this is raw SQL rather than the ORM:
            # `f1c30ab27d84` made the column NOT NULL and
            # `Classification._file_the_number` is what fills it everywhere else.
            connection.execute(
                text(
                    "INSERT INTO classifications "
                    "(book_id, scheme, number, label, sort_key) "
                    "VALUES (1, 'lcsh', :number, NULL, :sort_key)"
                ),
                {
                    "number": self.HEADING,
                    "sort_key": filing.sort_key_for("lcsh", self.HEADING),
                },
            )
            connection.commit()

        command.downgrade(schema._alembic_config(), "e2c74a91b5d8")

        assert self.numbers() == ["005.133"]


class TestFoldingCollectionNamesOutsideAscii:
    """Revision e7b3d02a5c94, which merges rows in a live library.

    Nothing else in this tree deletes somebody's data on an upgrade, so what
    these tests defend is not the new column, it is the merge. The trap is that
    a book missed by the repoint does not fail and does not look wrong: the
    foreign key is off in a migration connection (`PRAGMA foreign_keys` is 0,
    because the `ON` listener lives on `database.engine` and Alembic builds its
    own), so `ON DELETE SET NULL` never fires, the id dangles, and the survivor
    being the lower id means the freed rowid is the one SQLite hands to the
    next collection created. The book then reads as filed under a shelf that
    did not exist when it was filed.
    """

    PREVIOUS = "b7d41f0a2c95"

    @staticmethod
    @contextmanager
    def _with_foreign_keys_off() -> Iterator[Connection]:
        """A connection with `PRAGMA foreign_keys=OFF`, discarded afterwards.

        AUTOCOMMIT because SQLite ignores the pragma inside a transaction, and
        the insert these tests need would then be refused by the very rule they
        are suspending.

        **`invalidate()` is the load bearing half.** `database.py` sets the
        pragmas on the `connect` event, which fires once per *physical*
        connection, not per checkout. A connection handed back to the pool with
        foreign keys off keeps them off for whoever checks it out next, and the
        suite runs `-n 2` with per-test distribution, so whether that next
        caller is `TestSqlitePragmas` is luck. It cost two failures in a full
        run that passed file by file. Invalidating drops the connection instead
        of returning it, so the next checkout is a fresh one the listener
        configures.
        """
        connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            yield connection
        finally:
            connection.invalidate()
            connection.close()

    #: Named apart because they are the pair, and because reading `Ästhetik`
    #: twice in an assertion is how a test ends up asserting nothing.
    UPPER = "Ästhetik"
    LOWER = "ästhetik"

    def build_database_with_a_colliding_pair(self) -> None:
        """A library holding both spellings, one book on each, one shelf beside.

        `Fiction` is there to prove the merge is selective: a collection with no
        case variant must come through untouched.

        **`Fiction` is inserted first, and the order is load bearing.** It puts
        the pair on ids 2 and 3, so the merge deletes the **highest** rowid.
        SQLite hands out `max(rowid) + 1`, so only the highest freed id is ever
        reused, and the freed-id test below can observe the reuse it is named
        for only when the loser is that one. With the pair on ids 1 and 2 the
        freed id was 2 while 3 still existed, the next insert took 4, and that
        test passed however the migration behaved.
        """
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO users (username, password_hash, is_admin) VALUES ('kim','x',1)")
            )
            for name in ("Fiction", self.UPPER, self.LOWER):
                connection.execute(
                    text("INSERT INTO collections (name) VALUES (:name)"), {"name": name}
                )
            for title, collection_id in (("Other", 1), ("Upper", 2), ("Lower", 3)):
                connection.execute(
                    text(
                        "INSERT INTO books (title, collection_id, added_by_user_id) "
                        "VALUES (:title, :collection_id, 1)"
                    ),
                    {"title": title, "collection_id": collection_id},
                )
            connection.commit()

    def collections(self) -> list[tuple[int, str, str]]:
        with engine.connect() as connection:
            return [
                (row[0], row[1], row[2])
                for row in connection.execute(
                    text("SELECT id, name, name_folded FROM collections ORDER BY id")
                )
            ]

    def names_only(self) -> list[tuple[int, str]]:
        """`collections()` reads `name_folded`, which a refused upgrade has not
        added, so the refusal tests need a query that predates the column."""
        with engine.connect() as connection:
            return [
                (row[0], row[1])
                for row in connection.execute(
                    text("SELECT id, name FROM collections ORDER BY id")
                )
            ]

    def shelf_of(self, title: str) -> int | None:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT collection_id FROM books WHERE title = :title"),
                {"title": title},
            ).scalar()

    def dangling_books(self) -> int:
        with engine.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM books WHERE collection_id IS NOT NULL "
                        "AND collection_id NOT IN (SELECT id FROM collections)"
                    )
                ).scalar_one()
            )

    def test_the_pair_becomes_one_collection(self):
        self.build_database_with_a_colliding_pair()

        schema.upgrade_to_head()

        assert [name for _id, name, _folded in self.collections()] == ["Fiction", self.UPPER]

    def test_the_lower_id_survives(self):
        """The tie-break, and it is not arbitrary: `_first_wins` in
        `importing.py` and `create_tag` in `routers/books.py` fold the same way
        and keep the same end. Two folding rules disagreeing about the winner
        is the defect `docs/decisions.md` records."""
        self.build_database_with_a_colliding_pair()

        schema.upgrade_to_head()

        assert self.collections()[1][:2] == (2, self.UPPER)

    def test_both_books_end_up_on_the_survivor(self):
        """The assertion the whole revision turns on. An implementation that
        deletes the loser without repointing leaves this book pointing at an id
        that is gone, and nothing raises."""
        self.build_database_with_a_colliding_pair()

        schema.upgrade_to_head()

        assert self.shelf_of("Upper") == 2
        assert self.shelf_of("Lower") == 2

    def test_no_book_points_at_a_collection_that_is_gone(self):
        """The second half of the same defect, and the one the first assertion
        cannot see. A dangling id is not a null: the deleted row is the higher
        rowid, which SQLite gives to the next insert, so the book silently
        joins whatever collection is created next."""
        self.build_database_with_a_colliding_pair()

        schema.upgrade_to_head()

        assert self.dangling_books() == 0

    def test_a_freed_id_is_not_reused_by_a_book_that_should_not_have_it(self):
        """The failure mode above, made visible.

        The merge frees the pair's higher id, which is the highest rowid in the
        table, so the next insert takes it back. A migration that deleted the
        loser without repointing would leave a book on that id, and this
        collection would inherit it. See the note on the fixture: the insertion
        order is what makes the freed id reachable at all.
        """
        self.build_database_with_a_colliding_pair()
        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO collections (name, name_folded) VALUES ('Later','later')")
            )
            connection.commit()
            later = connection.execute(
                text("SELECT id FROM collections WHERE name = 'Later'")
            ).scalar_one()
            # The point of the test: this is the id the merge freed. If it is
            # not, the count below is true for a reason unrelated to the
            # repoint and the test proves nothing.
            assert later == 3
            filed = connection.execute(
                text("SELECT COUNT(*) FROM books WHERE collection_id = :later"),
                {"later": later},
            ).scalar_one()

        assert filed == 0

    def test_a_group_of_more_than_two_merges_in_one_go(self):
        """Reachable, and not obviously so. A pair like "Ästhetik" and
        "ÄSTHETIK" could never coexist, because they differ in ASCII letters
        too and the old index caught that. Two accented letters make four
        spellings that the old index saw as four names and Python folds to one,
        so the repoint has to take a list of losers rather than a single id.
        """
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        with engine.connect() as connection:
            for index, name in enumerate(("ÄÖ", "äÖ", "Äö", "äö"), start=1):
                connection.execute(
                    text("INSERT INTO collections (name) VALUES (:name)"), {"name": name}
                )
                connection.execute(
                    text(
                        "INSERT INTO books (title, collection_id) VALUES (:title, :collection_id)"
                    ),
                    {"title": f"Book {index}", "collection_id": index},
                )
            connection.commit()

        schema.upgrade_to_head()

        assert [name for _id, name, _folded in self.collections()] == ["ÄÖ"]
        assert [self.shelf_of(f"Book {index}") for index in range(1, 5)] == [1, 1, 1, 1]
        assert self.dangling_books() == 0

    def test_a_collection_with_no_variant_is_untouched(self):
        self.build_database_with_a_colliding_pair()

        schema.upgrade_to_head()

        assert self.shelf_of("Other") == 1

    def test_the_fold_is_backfilled(self):
        self.build_database_with_a_colliding_pair()

        schema.upgrade_to_head()

        assert [folded for _id, _name, folded in self.collections()] == [
            "fiction",
            self.LOWER,
        ]

    def test_the_new_index_refuses_a_non_ascii_case_clash(self):
        """The rule is the index rather than the handler's check, which races.
        This is the pair that the old `lower(name)` index allowed."""
        self.build_database_with_a_colliding_pair()
        schema.upgrade_to_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text("INSERT INTO collections (name, name_folded) VALUES (:name, :folded)"),
                {"name": "ÄSTHETIK", "folded": self.LOWER},
            )

    def test_the_foreign_key_survives_the_table_rewrite(self):
        """`collections` is rebuilt to make `name_folded` NOT NULL, and it is
        the parent of `books.collection_id`. A rewrite that lost the constraint
        would leave `ON DELETE SET NULL` decorative on every upgraded database,
        which is the same class of regression `d5c31b7a09fe` had to work around
        for a partial index."""
        self.build_database_with_a_colliding_pair()
        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(text("DELETE FROM collections WHERE id = 2"))
            connection.commit()

        assert self.shelf_of("Upper") is None
        assert self.shelf_of("Lower") is None

    def test_the_id_index_survives_the_table_rewrite(self):
        self.build_database_with_a_colliding_pair()

        schema.upgrade_to_head()

        names = {index["name"] for index in inspect(engine).get_indexes("collections")}
        assert "ix_collections_id" in names
        assert "uq_collections_name_folded" in names

    def test_a_book_already_pointing_nowhere_stops_the_upgrade(self):
        """A dangling id cannot be written by the app: the delete route, the
        ORM and `ON DELETE SET NULL` under `PRAGMA foreign_keys=ON` each
        prevent it, which is why this test has to turn the pragma off to build
        one. Arriving with one means the rows were edited by hand, and the
        upgrade reports rather than guessing what they meant."""
        self.build_database_with_a_colliding_pair()
        with self._with_foreign_keys_off() as connection:
            connection.execute(
                text(
                    "INSERT INTO books (title, collection_id, added_by_user_id) "
                    "VALUES ('Nowhere', 9999, 1)"
                )
            )

        with pytest.raises(RuntimeError, match="does not exist"):
            schema.upgrade_to_head()

    def test_a_refused_upgrade_changes_nothing(self):
        """It has to leave the database exactly as it was found, because a
        failed revision here does not roll back on its own: Alembic's SQLite
        implementation sets `transactional_ddl = False`, so nothing wraps the
        revision, and pysqlite runs DDL outside the transaction it opens for
        DML. That is why both checks run before the first DDL statement.
        """
        self.build_database_with_a_colliding_pair()
        with self._with_foreign_keys_off() as connection:
            connection.execute(
                text(
                    "INSERT INTO books (title, collection_id, added_by_user_id) "
                    "VALUES ('Nowhere', 9999, 1)"
                )
            )

        with pytest.raises(RuntimeError):
            schema.upgrade_to_head()

        assert current_revision() == self.PREVIOUS
        columns = {column["name"] for column in inspect(engine).get_columns("collections")}
        assert "name_folded" not in columns
        assert [name for _id, name in self.names_only()] == [
            "Fiction",
            self.UPPER,
            self.LOWER,
        ]

    def test_the_downgrade_restores_the_old_index_and_cannot_un_merge(self):
        """Schema, not data. The losing rows and the names on them are gone, so
        a downgrade gives back the shape and not the shelves."""
        from alembic import command

        self.build_database_with_a_colliding_pair()
        schema.upgrade_to_head()

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        with engine.connect() as connection:
            definitions = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT sql FROM sqlite_master WHERE tbl_name = 'collections' "
                        "AND sql IS NOT NULL"
                    )
                )
            ]
        assert any("lower(name)" in definition for definition in definitions)
        assert not any("name_folded" in definition for definition in definitions)
        assert [name for _id, name in self.names_only()] == ["Fiction", self.UPPER]


class TestCustomFieldsOnABook:
    """Migration `f4a10c92b7d6`, checked as schema rather than as data.

    The suite creates its tables from `Base.metadata`, so nothing else here
    exercises this revision. What is worth pinning is the part of it that is
    not simply "two tables appeared": the uniqueness rule the feature is shaped
    around, and the two CHECKs that are the only thing enforcing a bound on a
    path that never sees a Pydantic model.
    """

    PREVIOUS = "e7b3d02a5c94"

    def _at_head(self) -> None:
        drop_everything()
        schema.upgrade_to_head()

    def test_both_tables_arrive(self):
        self._at_head()

        assert {"custom_fields", "custom_field_values"} <= table_names()

    def test_a_book_holds_one_value_per_field(self):
        """The shape of the feature, not an optimisation: without it a second
        row renders twice and no writer knows which one it is updating."""
        self._at_head()

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO custom_fields (name, kind) VALUES ('Calibre', 'url')")
            )
            connection.execute(text("INSERT INTO books (title) VALUES ('Solaris')"))
            connection.execute(
                text(
                    "INSERT INTO custom_field_values (book_id, field_id, value) "
                    "VALUES (1, 1, 'https://a.example/1')"
                )
            )
            connection.commit()

            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO custom_field_values (book_id, field_id, value) "
                        "VALUES (1, 1, 'https://b.example/2')"
                    )
                )

    def test_an_empty_value_is_refused_by_the_database(self):
        """A cleared field is an absent row, and this is what keeps that true
        on the one path with no Pydantic model in front of it: `backup.restore`
        inserts through Core."""
        self._at_head()

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO custom_fields (name, kind) VALUES ('Calibre', 'url')")
            )
            connection.execute(text("INSERT INTO books (title) VALUES ('Solaris')"))
            connection.commit()

            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO custom_field_values (book_id, field_id, value) "
                        "VALUES (1, 1, '')"
                    )
                )

    def test_a_value_past_the_bound_is_refused_by_the_database(self):
        """SQLite ignores a VARCHAR width: measured, a Core insert of 50,000
        characters into a `String(500)` stores 50,000. The CHECK is the bound."""
        self._at_head()

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO custom_fields (name, kind) VALUES ('Calibre', 'url')")
            )
            connection.execute(text("INSERT INTO books (title) VALUES ('Solaris')"))
            connection.commit()

            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO custom_field_values (book_id, field_id, value) "
                        "VALUES (1, 1, :value)"
                    ),
                    {"value": "x" * 501},
                )

    def test_a_kind_nobody_recognises_is_refused_by_the_database(self):
        """The one CHECK here that guards a 500 rather than a bad row.

        `CustomFieldOut.kind` is typed, so a row carrying anything else makes
        Pydantic raise while serialising the library wide definitions route:
        one restored row, and every member's settings page answers 500 for
        good. `backup.restore` inserts through Core and sees no Pydantic model,
        so this is the only place that can refuse it.
        """
        self._at_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text("INSERT INTO custom_fields (name, kind) VALUES ('X', 'link')")
            )

    def test_two_fields_cannot_share_a_name(self):
        self._at_head()

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO custom_fields (name, kind) VALUES ('Calibre', 'url')")
            )
            connection.commit()

            with pytest.raises(IntegrityError):
                connection.execute(
                    text("INSERT INTO custom_fields (name, kind) VALUES ('Calibre', 'text')")
                )

    def test_the_downgrade_drops_both_tables(self):
        """Honest rather than clever: the values live nowhere else, so a
        downgrade destroys them."""
        from alembic import command

        self._at_head()

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        assert not ({"custom_fields", "custom_field_values"} & table_names())


class TestKeyingTheSeededTags:
    """Revision c1f8a7e3d240, which decides which rows are still the seeded ones.

    The rule is one line and the whole feature rests on it: a row is keyed only
    where its name still matches the English seed name exactly. Everything else
    keeps a null key and is shown as typed, which is what stops the upgrade
    putting the curated word back over a name a household chose.
    """

    PREVIOUS = "b8e2f4c7a913"

    def build_database_with_tags(self) -> dict[str, int]:
        """A database one revision back, holding three tags and a tagged book.

        Seeded and untouched, seeded and renamed, and one the library invented.
        Returns the ids by name.
        """
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        names = {
            "Computing": "genre",
            "Stories": "type",
            "Holiday reads": "custom",
        }
        ids = {}
        with engine.connect() as connection:
            for name, category in names.items():
                connection.execute(
                    text("INSERT INTO tags (name, category) VALUES (:name, :category)"),
                    {"name": name, "category": category},
                )
                ids[name] = int(
                    connection.execute(
                        text("SELECT id FROM tags WHERE name = :name"), {"name": name}
                    ).scalar_one()
                )
            connection.execute(
                text(
                    "INSERT INTO books (title, is_private, added_at, ownership) "
                    "VALUES ('Dune', 0, datetime('now'), 'owned')"
                )
            )
            book_id = connection.execute(text("SELECT id FROM books")).scalar_one()
            # Tagged with both the keyed row and the renamed one: the second is
            # the case worth pinning, because an upgrade that lost it would
            # take the tag off a book to fix a display problem.
            for tag_id in (ids["Computing"], ids["Stories"]):
                connection.execute(
                    text("INSERT INTO book_tags (book_id, tag_id) VALUES (:b, :t)"),
                    {"b": book_id, "t": tag_id},
                )
            connection.commit()
        return ids

    def keys(self) -> dict[str, str | None]:
        """Every tag's key, by name."""
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT name, key FROM tags")).all()
        return {str(row[0]): row[1] for row in rows}

    def test_a_row_still_carrying_the_seeded_name_is_keyed(self):
        self.build_database_with_tags()

        schema.upgrade_to_head()

        assert self.keys()["Computing"] == "computing"

    def test_a_renamed_row_is_left_unkeyed(self):
        """The decision the ticket turns on: their word, not ours.

        "Stories" is the seeded **Fiction** row after somebody renamed it. It
        matches no seed name, so it gets no key and is an ordinary invented tag
        from here on.
        """
        self.build_database_with_tags()

        schema.upgrade_to_head()

        assert self.keys()["Stories"] is None

    def test_a_tag_the_library_invented_is_left_unkeyed(self):
        self.build_database_with_tags()

        schema.upgrade_to_head()

        assert self.keys()["Holiday reads"] is None

    def test_it_creates_and_deletes_no_row(self):
        """A rename over seeded rows is where a duplicated vocabulary comes
        from, so the count is asserted rather than assumed."""
        self.build_database_with_tags()

        with engine.connect() as connection:
            before = connection.execute(text("SELECT COUNT(*) FROM tags")).scalar_one()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            after = connection.execute(text("SELECT COUNT(*) FROM tags")).scalar_one()
        assert after == before

    def test_a_book_keeps_both_its_tags(self):
        """Including the renamed one, which is the row this migration decides
        to leave alone."""
        ids = self.build_database_with_tags()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            links = connection.execute(text("SELECT tag_id FROM book_tags")).scalars().all()
        assert sorted(links) == sorted([ids["Computing"], ids["Stories"]])

    def test_seeding_afterwards_does_not_duplicate_the_keyed_row(self):
        """The property `95b6a61d6668` exists to protect, restated for the key.

        `seed_tags()` still matches on name, so the keyed row is found and left
        alone. The renamed row is **not** matched, and Fiction is inserted
        beside it: that is the seeded tag coming back, not a duplicate of
        theirs.
        """
        import main

        self.build_database_with_tags()
        schema.upgrade_to_head()

        main.seed_tags()

        keys = self.keys()
        assert keys["Computing"] == "computing"
        assert keys["Stories"] is None
        assert keys["Fiction"] == "fiction"

    def test_two_rows_cannot_share_a_key(self):
        self.build_database_with_tags()
        schema.upgrade_to_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO tags (name, category, key) "
                    "VALUES ('Second', 'custom', 'computing')"
                )
            )

    def test_many_rows_may_share_a_null_key(self):
        """Which is the shape every invented tag has, so it is not incidental."""
        self.build_database_with_tags()
        schema.upgrade_to_head()

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO tags (name, category) VALUES ('Beach', 'custom')")
            )
            connection.execute(
                text("INSERT INTO tags (name, category) VALUES ('Loft', 'custom')")
            )
            connection.commit()

        assert self.keys()["Beach"] is None
        assert self.keys()["Loft"] is None

    def test_the_downgrade_drops_the_column(self):
        from alembic import command

        self.build_database_with_tags()
        schema.upgrade_to_head()

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        with engine.connect() as connection:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(tags)"))}
        assert "key" not in columns

    def test_a_downgraded_database_upgrades_again(self):
        """The keys are derived, so the round trip has to restore them."""
        from alembic import command

        self.build_database_with_tags()
        schema.upgrade_to_head()
        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        schema.upgrade_to_head()

        assert self.keys()["Computing"] == "computing"


class TestTheMigrationsAndTheModelsAgree:
    """What the suite builds and what production runs must be one schema.

    **This class exists because the two diverged and nothing could see it.**

    **The suite and a deployment both see the migrations**, for the reason
    `tests/conftest.py::_schema_once` gives. That does not make the two
    declarations one: `models.py` and the revisions are still two files saying
    the same thing, and only a comparison holds them together.

    What survives that correction is this class's whole reason: the two
    declarations are two copies and only a comparison holds them together.
    `author_identifiers.created_at` shipped as `nullable=True`
    in revision `a4c73e0b19d5` against a `Mapped[datetime]` that is NOT NULL,
    and the whole suite was green. It was found by a person reading the two
    files against each other, which is exactly the thing that does not scale.

    Compared per column on the two properties a migration can get wrong while
    still applying cleanly: **nullability** and **type**. Not on server defaults,
    which SQLite reflects as the literal SQL text it was given and which differ
    harmlessly between `func.now()` and `CURRENT_TIMESTAMP`.

    **And per named CHECK, on the expression itself**, which is the property
    that decides what a row is refused for and the one a column comparison
    cannot see at all. Before that arrived the two copies were compared where
    somebody had written a class for the table, `ck_digital_references_bounds`
    here and `ck_loans_one_borrower` in `tests/test_models.py`, or where a token
    scan below picked the constraint up, keyed on `AS BLOB` and on `char(0)`.
    Every enum list in the schema was outside all of them: `test_house_rules.py`
    asks of those only whether each column is bounded on both sides, never
    whether the two lists name the same values.

    **No count of what that left, deliberately.** A coverage figure here would
    be read as current and nothing recomputes it; what the gap was on the day
    this was written is in the commit that closed it.

    **Derived from the metadata and from reflection, so it enumerates nothing**
    and a constraint added to a model is compared the day it exists. What it
    refuses that a behavioural probe does not is any difference at all, on any
    column, with no fixture per table; what a probe refuses and this does not is
    two copies that agree with each other and are both wrong, which is why the
    probes below are not replaced by it.

    **The text comparisons below are not replaced either, and the reason is the
    instrument.** They read the DDL SQLite stored; this reads SQLAlchemy's
    parse of it. Two readings of one artefact are what say a parser that stopped
    recognising a clause is a parser and not a schema change, and no case they
    refuse is accepted here.

    **Still not compared**: indexes, foreign keys, uniqueness and server
    defaults. A revision that builds an index the model does not declare is
    invisible here.
    """

    @staticmethod
    def _reflected() -> dict[str, dict[str, tuple[bool, str]]]:
        """Every table the migrations build, as `{table: {column: (nullable, type)}}`."""
        drop_everything()
        schema.upgrade_to_head()
        inspector = inspect(engine)
        return {
            table: {
                column["name"]: (bool(column["nullable"]), str(column["type"]))
                for column in inspector.get_columns(table)
            }
            for table in inspector.get_table_names()
            if table != "alembic_version"
        }

    def test_every_table_has_the_same_columns_in_both(self):
        """**The likelier half of the class, and the first version was blind to
        it.** A forgotten `op.add_column` is a much commoner mistake than a
        forgotten `op.create_table`, and the two property comparisons below
        skip a column the migration never built, because there is nothing to
        compare it against. Driven verbatim against a reflected schema with one
        declared column removed, all three of the original cases passed.

        The `created_at` defect that prompted this class was a **property**
        mismatch, which is the one variant a `continue` cannot hide, so
        validating the guard on it alone made it look sound.

        Symmetric on both axes. A column the migration builds and the model does
        not declare is reported, and so is a **table** in that position: the
        loops walk `Base.metadata.sorted_tables`, so a migrated table nothing
        declares would otherwise be invisible from every direction, and
        `_reflected()` already has the set to compare against.
        """
        migrated = self._reflected()
        wrong: list[str] = []
        if undeclared := sorted(
            set(migrated) - {table.name for table in Base.metadata.sorted_tables}
        ):
            wrong.append(f"migrated but never declared: {undeclared}")
        for table in Base.metadata.sorted_tables:
            built = migrated.get(table.name)
            if built is None:
                # Reported by `test_the_migrations_build_every_table_the_models_declare`.
                continue
            declared = {column.name for column in table.columns}
            if missing := sorted(declared - set(built)):
                wrong.append(f"{table.name}: declared but never migrated: {missing}")
            if extra := sorted(set(built) - declared):
                wrong.append(f"{table.name}: migrated but never declared: {extra}")

        assert not wrong, "\n".join(wrong)

    def test_every_column_agrees_on_nullability(self):
        """A column absent from one side is `test_every_table_has_the_same_columns_in_both`."""
        migrated = self._reflected()
        wrong: list[str] = []
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                built = migrated.get(table.name, {}).get(column.name)
                if built is None:
                    continue
                if built[0] != bool(column.nullable):
                    wrong.append(
                        f"{table.name}.{column.name}: migration nullable="
                        f"{built[0]}, model nullable={bool(column.nullable)}"
                    )

        assert not wrong, "\n".join(wrong)

    def test_every_column_agrees_on_type(self):
        migrated = self._reflected()
        wrong: list[str] = []
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                built = migrated.get(table.name, {}).get(column.name)
                if built is None:
                    continue
                if built[1] != str(column.type):
                    wrong.append(
                        f"{table.name}.{column.name}: migration {built[1]}, "
                        f"model {column.type}"
                    )

        assert not wrong, "\n".join(wrong)

    def test_the_migrations_build_every_table_the_models_declare(self):
        """A model with no migration is the same defect facing the other way:
        the suite passes and the deployment has no table."""
        migrated = self._reflected()

        missing = {table.name for table in Base.metadata.sorted_tables} - set(migrated)

        assert not missing, f"declared but never migrated: {sorted(missing)}"

    def test_every_check_constraint_is_carried_by_both_copies(self):
        """The names, before the expressions, because the two fail differently.

        A constraint in `models.py` that no revision installs is the declaration
        describing a refusal no deployment makes. One installed that nothing
        declares is `custom_fields.kind` facing the other way: `create_all`
        builds the table without it and `--autogenerate` proposes dropping it.
        `test_house_rules.py` refuses both for an **enum** column; this refuses
        them for every column there is.
        """
        drop_everything()
        schema.upgrade_to_head()
        declared = _declared_checks()
        installed = _installed_checks()

        assert not sorted(set(declared) - set(installed)), (
            "models.py declares these and no revision installs them, so the "
            "declaration describes a constraint the deployment does not carry: "
            f"{sorted(set(declared) - set(installed))}"
        )
        assert not sorted(set(installed) - set(declared)), (
            "a revision installs these and models.py declares none of them, so "
            "`create_all` builds the table without them and `--autogenerate` "
            f"proposes dropping them: {sorted(set(installed) - set(declared))}"
        )

    def test_every_check_constraint_agrees_on_its_expression(self):
        """The text, which is the whole of what a CHECK is.

        **An equality, and over the pair rather than over a substring.** The
        containment form two classes below use passes an installed rule that
        appends to the model's, and passed a dropped floor once already:
        `_installed_check` carries that measurement. It also passes a rule
        installed on a different table, which is why the table is compared
        beside the text.

        A revision cannot import a constant, so each of these is a fact stored
        twice on purpose. This is what stands between the copies for all of
        them at once, rather than for the ones somebody wrote a class for.

        **The whitespace normalisation is safe for this schema and not in
        general**: no constraint here holds a string literal with internal
        whitespace, which is the caveat `_declared_constraint` states at its own
        site and this inherits.
        """
        drop_everything()
        schema.upgrade_to_head()
        declared = _declared_checks()
        installed = _installed_checks()

        wrong = [
            f"{name}:\n  model     ({declared[name][0]}): {declared[name][1]}\n"
            f"  installed ({installed[name][0]}): {installed[name][1]}"
            for name in sorted(set(declared) & set(installed))
            if declared[name] != installed[name]
        ]

        assert not wrong, (
            "these are not the constraint any revision installs, so models.py "
            "describes a schema nobody runs:\n" + "\n".join(wrong)
        )

    def test_both_readers_find_a_constraint_to_compare(self):
        """Anti vacuity, and only the case the two rules above cannot cover.

        **One reader going empty is already red**, because the names are
        compared in both directions: an empty `_installed_checks` leaves all 30
        declared names unmatched, and an empty `_declared_checks` leaves all 30
        installed ones. What passes both is the pair going empty together, which
        is one reflection API change away and reads exactly like a clean run.

        **No count, and deliberately not a floor.** A number here would be
        re-read as current and would go stale the first time a constraint is
        legitimately dropped, which is the instrument this tree has already
        recorded going stale in the direction that still passes.
        """
        drop_everything()
        schema.upgrade_to_head()

        assert _declared_checks(), "no model in this schema declares a CHECK"
        assert _installed_checks(), "the migrated schema carries no CHECK at all"


#: What a child process reports about the schema it ends up with.
#:
#: **Run as a child and not in this process**, because the thing under test
#: happens at **import** time: a module executing DDL of its own does it once,
#: when the suite's own `conftest` imported the application, and by the time any
#: fixture runs there is nothing left to observe.
#:
#: Written to a file rather than to stdout. `import main` configures logging, and
#: a handler on stdout would put log lines through the same pipe as the report.
_BOOT_PROBE: Final = """
import json, os, sys
sys.path.insert(0, os.environ["ENDPAPER_PROBE_BACKEND"])

if sys.argv[1] == "application":
    import main  # noqa: F401  init_db() runs at import, as it does at boot
elif sys.argv[1] == "revisions":
    import schema
    schema.upgrade_to_head()
else:
    # **Not a fall through to the revisions branch**, which is what this was and
    # is the one shape that makes the comparison vacuous: a renamed side would
    # take that branch too, both children would run the same code, and the test
    # would pass having compared a boot with itself.
    raise SystemExit(f"no probe named {sys.argv[1]!r}")

from sqlalchemy import inspect

from database import engine

inspector = inspect(engine)
shape = {
    table: {
        "columns": sorted(column["name"] for column in inspector.get_columns(table)),
        "indexes": sorted(str(index["name"]) for index in inspector.get_indexes(table)),
        "checks": sorted(
            (str(check["name"]), " ".join(str(check["sqltext"]).split()))
            for check in inspector.get_check_constraints(table)
        ),
    }
    for table in sorted(inspector.get_table_names())
}
with open(os.environ["ENDPAPER_PROBE_OUT"], "w") as out:
    json.dump(shape, out)
"""


class TestTheSchemaTheApplicationBootsIsTheRevisions:
    """The premise every comparison between a model and a database rests on.

    **Three arms already state it and a module writing its own DDL is outside
    all three.** `tests/conftest.py::_schema_once` counts tables either side of
    its own `create_all` call, which says what **that call** built and nothing
    about a table built before it. `tests/test_house_rules.py` compares the
    stamp against the script directory's head, which a hand written stamp
    satisfies, and walks the source for a call named `create_all`, which a raw
    `execute` of a `CREATE` is not. Each arm names its own bound; the hole is
    the conjunction's, and it is the one an application acquires by executing
    DDL at import.

    **Asked of the artefact rather than of the source**, which is why it is not
    a fourth scan. A scan for a statement has to enumerate what one looks like,
    a `CREATE TABLE`, an `ALTER`, an `IF NOT EXISTS`, an f-string, and this tree
    has paid for that family repeatedly. Two boots are compared instead: one
    that imports the application the way uvicorn does, and one that runs the
    revisions and nothing else. Anything the application builds beyond migrating
    is a difference, whatever statement built it and whatever module holds it.

    **Both sides are children of this test, on their own SQLite files.** Neither
    touches the ambient database, so the comparison is between two boots rather
    than between a boot and whatever the suite happens to be holding, and it
    does not read a schema that a fixture rebuilt.

    **What it cannot see**, stated because a guard that reads thorough gets
    believed: DDL that leaves no trace in the schema, one issued lazily at
    request time rather than at boot, and a `create_all` or a
    `CREATE TABLE IF NOT EXISTS` that runs **after** the chain and finds every
    table already built. The last is the source arm's, which is why that arm
    covers something this does not and neither replaces the other.
    """

    #: Long enough that a slow node is not a failure, short enough that a child
    #: that hangs is reported rather than sitting on a worker until the run is
    #: killed. The whole test, both children, measured 4.43s on `builder`,
    #: which bounds either of them.
    TIMEOUT: Final = 180

    @staticmethod
    def _booted(how: str, root: Path) -> dict[str, Any]:
        """The schema one boot ends up with, reflected in a child process."""
        directory = root / how
        directory.mkdir()
        report = directory / "shape.json"
        environment = {
            **os.environ,
            "ENDPAPER_PROBE_BACKEND": str(BACKEND),
            "ENDPAPER_PROBE_OUT": str(report),
            "DATA_DIR": str(directory),
            "DATABASE_URL": f"sqlite:///{directory / 'probe.db'}",
            "SQLITE_SYNCHRONOUS": "OFF",
            "SECRET_KEY": "probe-secret-key-at-least-32-characters-long",
            "APP_ENV": "dev",
            "ENABLE_OVERDUE_TICKER": "false",
            # The machine running this may have a real one, and `generate_key`
            # writes. The failing backend is what a container has anyway.
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
        }
        # Both children are SQLite whatever this run is against, so the two
        # shapes are comparable on the engine the image ships with.
        environment.pop("ENDPAPER_TEST_DATABASE_URL", None)

        finished = subprocess.run(
            [sys.executable, "-c", _BOOT_PROBE, how],
            env=environment,
            capture_output=True,
            text=True,
            timeout=TestTheSchemaTheApplicationBootsIsTheRevisions.TIMEOUT,
        )

        assert finished.returncode == 0, (
            f"the {how} probe did not finish, so this rule measured nothing:\n"
            f"{finished.stderr[-2000:]}"
        )
        return dict(json.loads(report.read_text()))

    def test_a_boot_builds_nothing_the_revisions_do_not(self, tmp_path: Path):
        """The application's schema against the revisions' own.

        A difference here is a module building part of the schema itself, which
        makes `models.py` and a revision two descriptions of a third thing and
        every comparison between them an agreement about something a deployment
        does not carry.

        **The anti vacuity case is the first assertion rather than its own
        test**, which is the one place in this file that rule is bent and the
        reason is the instrument: two children that reported an empty schema
        would agree perfectly, and asking again costs another boot. `books` is
        named because a schema without it is not this application's, and a count
        is not, for the reason
        `test_both_readers_find_a_constraint_to_compare` gives.
        """
        application = self._booted("application", tmp_path)
        revisions = self._booted("revisions", tmp_path)

        assert "books" in revisions, (
            "the revisions probe reported a schema with no `books` table, so it "
            "reached neither the chain nor anything else this compares"
        )

        assert application.keys() == revisions.keys(), (
            "booting the application and running the revisions do not build the "
            "same tables, so something outside the chain builds part of the "
            f"schema.\n  only the boot: {sorted(set(application) - set(revisions))}"
            f"\n  only the chain: {sorted(set(revisions) - set(application))}"
        )

        differing = [
            f"{table}:\n  boot:  {application[table]}\n  chain: {revisions[table]}"
            for table in sorted(application)
            if application[table] != revisions[table]
        ]

        assert not differing, (
            "booting the application leaves a table in a shape the revisions do "
            "not build:\n" + "\n".join(differing)
        )


class TestTheEnvelopeConstraintOnAMigratedDatabase:
    """Revision `d9c1f47b2a06`, against the schema production runs.

    A batch rebuild on SQLite drops the table and recreates it from what
    SQLAlchemy reflected, so a revision that swaps one CHECK can silently take
    the other with it. `TestTheMigrationsAndTheModelsAgree` compares columns and
    would not see that; `tests/test_credentials.py::TestTheEnvelopeRuleAndIts
    ConstraintAgree` asserts the same refusals against a table it builds from
    `Base.metadata` on a throwaway engine, which is the models' declaration and
    not a database anybody runs. Its docstring says why it goes to that trouble:
    the `db` fixture is the migrations' schema and cannot answer a question
    about the declaration. This is the half a deployment carries.
    """

    @staticmethod
    def _envelope(version: str) -> str:
        """A shape the check admits, for one version, as a SQL literal."""
        return "'" + version + "." + "a" * 40 + ".b.c'"

    @staticmethod
    def _migrated() -> None:
        drop_everything()
        schema.upgrade_to_head()

    @staticmethod
    def _insert(source: str, envelope: str) -> str:
        return (
            "INSERT INTO catalogue_credentials (source, envelope) VALUES "
            f"({source}, {envelope})"
        )

    @pytest.mark.parametrize("version", credentials.KNOWN_VERSIONS)
    def test_every_version_this_build_recognises_is_storable(self, version):
        """Derived from the constant, not listed: `v2` is what this build writes
        and the arm that fails on a deployment if the revision is forgotten,
        since the constraint admitted `v1` alone and every write was an
        IntegrityError; `v1` is what an archive taken before the binding
        carries, and refusing it fails a whole restore."""
        self._migrated()

        with engine.connect() as connection:
            connection.execute(text(self._insert("'bne'", self._envelope(version))))
            connection.commit()

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM catalogue_credentials")
            ).scalar() == 1

    def test_a_plaintext_password_is_still_refused(self):
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(self._insert("'bne'", "'hunter2'")))

        assert "ck_catalogue_credentials_envelope" in str(refusal.value)

    def test_the_source_constraint_survived_the_rebuild(self):
        """The half a batch rebuild loses if reflection missed it.

        Both CHECKs are on one table and the revision swaps one of them, so the
        other is only still there because SQLAlchemy read it back out of the
        table's DDL. Nothing else in this suite would notice it gone: the model
        still declares it, and every write in the application comes through a
        validated path.
        """
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(
                text(self._insert("'../../books/5?'", self._envelope(credentials.VERSION)))
            )

        assert "ck_catalogue_credentials_source" in str(refusal.value)

    def test_the_upgrade_keeps_a_login_stored_under_the_older_scheme(self):
        """The upgrade path, as a migration rather than as prose.

        **It used to delete this row**, and the owner refused that on
        2026-09-07: a household upgrading may not lose its stored logins. The
        row is carried forward on the read path instead, where the key is
        already proven, so the migration widens the constraint and touches no
        data. The revision's docstring carries the whole argument.

        The asymmetry with the downgrade is deliberate and is stated there: it
        narrows the constraint, so a row the narrowed one cannot hold has to go
        or the whole downgrade fails on the copy.
        """
        from alembic import command

        drop_everything()
        command.upgrade(schema._alembic_config(), "c8b3e5017d4a")
        older = credentials._UNBOUND_VERSION
        with engine.connect() as connection:
            connection.execute(text(self._insert("'bne'", self._envelope(older))))
            connection.commit()

        command.upgrade(schema._alembic_config(), "d9c1f47b2a06")

        with engine.connect() as connection:
            kept = connection.execute(
                text("SELECT envelope FROM catalogue_credentials")
            ).scalars().all()
        assert len(kept) == 1
        assert kept[0].split(".")[0] == older

    def test_the_downgrade_clears_the_rows_it_narrows_past(self):
        """A `v2` row left in place fails the copy the batch rebuild performs,
        which takes the whole downgrade with it rather than reporting anything.
        A `v1` row must survive: it is what the narrowed constraint still
        admits, and taking it would lose a login the caller did not ask to lose.
        """
        from alembic import command

        self._migrated()
        older = credentials._UNBOUND_VERSION
        with engine.connect() as connection:
            connection.execute(
                text(self._insert("'bne'", self._envelope(credentials.VERSION)))
            )
            connection.execute(text(self._insert("'dnb'", self._envelope(older))))
            connection.commit()

        command.downgrade(schema._alembic_config(), "c8b3e5017d4a")

        with engine.connect() as connection:
            left = [
                row[0]
                for row in connection.execute(
                    text("SELECT source FROM catalogue_credentials")
                )
            ]

        assert left == ["dnb"]


class TestTheAuthorityIdentifierConstraintsOnAMigratedDatabase:
    """The four CHECKs and the unique index, against the schema production runs.

    `tests/test_models.py` asserts the same refusals against the `db` fixture,
    whose schema is the migrations' as well, so **this is not the other side of
    a pair**: both ask one database. What this adds is that it builds that
    database from nothing inside the test, through every revision in order,
    rather than inheriting what the import at session start left behind.

    `TestTheMigrationsAndTheModelsAgree` compares the two declarations
    structurally. This checks the half a column comparison cannot see: a CHECK
    is not a column property, and a migration that dropped one would still
    match. What holds a CHECK's two copies together for every enum column is
    `tests/test_house_rules.py::TestEveryEnumColumnIsConstrainedOrExemptWith
    AReason`.
    """

    @staticmethod
    def _migrated() -> None:
        drop_everything()
        schema.upgrade_to_head()

    @staticmethod
    def _insert(**overrides: object) -> str:
        row = {
            "author_key": "'kane sean p'",
            "scheme": "'gnd'",
            "identifier": "'1042243212'",
            "provenance": "'catalogue'",
            "created_by_user_id": "NULL",
        } | dict(overrides)
        return (
            "INSERT INTO author_identifiers "
            f"({', '.join(row)}) VALUES ({', '.join(str(v) for v in row.values())})"
        )

    def test_the_table_exists_at_head(self):
        self._migrated()

        assert "author_identifiers" in table_names()

    def test_a_subject_heading_scheme_is_refused_as_a_persons_identifier(self):
        """`ddc` for the reason its counterpart in `test_models.py` gives: the
        value was `viaf`, then `blbnb`, and both became members. A
        `ClassificationScheme` value cannot, because the two enums exist to keep
        a subject heading and a person apart."""
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(self._insert(scheme="'ddc'")))

        assert "ck_author_identifiers_scheme" in str(refusal.value)

    def test_the_national_scheme_downgrade_clears_the_rows_it_narrows_past(self):
        """Revision c9a5f27b3e41. A row the schema says cannot exist is worse
        than a row that is gone: narrowing a CHECK with rows that violate it
        fails outright on a real database and is accepted on SQLite, so the
        downgrade deletes them first.

        **The four older schemes must survive it**, which is the half a delete
        is easy to get wrong: the revision before this one narrows to `gnd`
        alone, and doing that work here would take rows the caller did not ask
        to lose.
        """
        from alembic import command

        self._migrated()
        with engine.connect() as connection:
            connection.execute(text(self._insert(scheme="'blbnb'", identifier="'000560463'")))
            connection.execute(
                text(
                    self._insert(
                        author_key="'stevenson robert louis'",
                        scheme="'isni'",
                        identifier="'0000000122831567'",
                    )
                )
            )
            connection.commit()

        command.downgrade(schema._alembic_config(), "d5e1b93a7c62")

        with engine.connect() as connection:
            left = [
                row[0]
                for row in connection.execute(
                    text("SELECT scheme FROM author_identifiers")
                )
            ]

        assert left == ["isni"]

    def test_a_provenance_that_is_neither_is_refused(self):
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(self._insert(provenance="'robot'")))

        assert "ck_author_identifiers_provenance" in str(refusal.value)

    def test_a_machine_assertion_may_not_name_a_person(self):
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(self._insert(created_by_user_id="1")))

        assert "ck_author_identifiers_asserter" in str(refusal.value)

    def test_an_empty_identifier_is_refused(self):
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(self._insert(identifier="''")))

        assert "ck_author_identifiers_bounds" in str(refusal.value)

    def test_one_spelling_may_not_carry_two_values_under_one_scheme(self):
        """The invariant the ÖNB `source` column would have deleted: it is what
        makes "an identifier cannot be retyped" enforceable below the
        application."""
        self._migrated()

        with engine.connect() as connection:
            connection.execute(text(self._insert()))
            connection.commit()
            with pytest.raises(IntegrityError) as refusal:
                connection.execute(text(self._insert(identifier="'9999'")))

        assert "UNIQUE constraint failed" in str(refusal.value)

    def test_created_at_is_not_nullable(self):
        """The column that shipped as `nullable=True` against a NOT NULL model
        and that the whole suite was blind to."""
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(text(self._insert(created_at="NULL")))

    def test_every_scheme_the_enum_offers_is_storable(self):
        """`AuthorityScheme` and `ck_author_identifiers_scheme` cannot separate.

        **The one drift `TestTheMigrationsAndTheModelsAgree` cannot see.** That
        class compares nullability and type per column and takes no view of a
        CHECK, so widening the enum without writing the revision leaves a value
        the application accepts and the deployment rejects, surfacing as an
        `IntegrityError` on somebody's first confirmation rather than as a red
        pipeline. `a4c73e0b19d5` says in prose that "the two have to be read
        against each other by a person"; this is that reading, mechanised for
        one constraint.

        **Driven off the enum rather than a written out list**, so a member
        added tomorrow is covered without anybody remembering this test exists.
        A list here would be the shape `CLAUDE.md` records as failing twice: a
        guard that enumerates something open.

        **Against the migrated database, never the models' declaration.**
        `models._scheme_check` derives its constraint from the same enum this
        test iterates, so asking the declaration whether it admits every member
        is asking the enum about itself. The revision writes its list out, and
        the installed DDL is the only copy that can disagree.

        Attacked rather than read, 2026-08-28. With `'isni'` removed from
        `d5e1b93a7c62._SCHEMES_AFTER` the failing test was this one, named:
        `FAILED tests/test_schema.py::TestTheAuthorityIdentifierConstraintsOn
        AMigratedDatabase::test_every_scheme_the_enum_offers_is_storable`,
        reporting `isni`. With a sixth member added to `AuthorityScheme` and no
        revision written, the same test failed naming that member.
        """
        self._migrated()

        refused: list[str] = []
        for scheme in AuthorityScheme:
            with engine.connect() as connection:
                try:
                    # A distinct key per scheme, so
                    # `uq_author_identifiers_key_scheme` cannot be what refuses
                    # the second row and be read as the CHECK doing it.
                    connection.execute(
                        text(
                            self._insert(
                                author_key=f"'{scheme.value} person'",
                                scheme=f"'{scheme.value}'",
                            )
                        )
                    )
                    connection.commit()
                except IntegrityError as refusal:
                    refused.append(f"{scheme.value}: {refusal}")

        assert not refused, (
            "the migrated ck_author_identifiers_scheme refuses a member "
            "AuthorityScheme offers:\n" + "\n".join(refused)
        )


class TestAnAddressPerMember:
    """Revision a3f7c1d94e82, which adds `users.email`.

    Nullable and with no fallback written into any row, which is the whole
    promise of it: a library upgrading past this revision must see no behaviour
    change, and a NULL address is what makes the mail sender keep using the
    household mailbox it already used.
    """

    PREVIOUS = "c9a5f27b3e41"

    def build_database_with_a_member(self) -> None:
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO users (username, password_hash, is_admin) VALUES ('kim','x',1)")
            )
            connection.commit()

    def test_the_column_arrives(self):
        self.build_database_with_a_member()

        schema.upgrade_to_head()

        columns = {column["name"] for column in inspect(engine).get_columns("users")}
        assert "email" in columns

    def test_it_is_nullable(self):
        """A NOT NULL column here would need a value for every existing row,
        and there is no address that would be right for one."""
        self.build_database_with_a_member()

        schema.upgrade_to_head()

        column = next(
            item
            for item in inspect(engine).get_columns("users")
            if item["name"] == "email"
        )
        assert column["nullable"] is True

    def test_the_column_is_as_wide_as_the_rule_allows(self):
        """The three places that bound an address agree, and nothing else makes
        them.

        `models.User.email` is `String(320)` as a literal, because importing
        `mailer.MAX_ADDRESS` there is an import cycle (`mailer` imports
        `settings_store`, which imports `models`). So the constant claimed to be
        the bound while `grep -rnF MAX_ADDRESS backend/tests/` returned nothing,
        and SQLite enforces no column width, which left three numbers agreeing
        by coincidence. This is the tie: the migrated column, the model, and the
        number the schema and `auth_backends` check against.
        """
        import mailer
        from models import User

        self.build_database_with_a_member()
        schema.upgrade_to_head()

        column = next(
            item
            for item in inspect(engine).get_columns("users")
            if item["name"] == "email"
        )
        # `isinstance` rather than a cast: that the column is a VARCHAR at all
        # is half the claim, and a cast would assert it without checking it.
        migrated = column["type"]
        declared = User.__table__.columns["email"].type
        assert isinstance(migrated, String)
        assert isinstance(declared, String)
        assert migrated.length == mailer.MAX_ADDRESS
        assert declared.length == mailer.MAX_ADDRESS

    def test_the_existing_member_survives_with_no_address(self):
        self.build_database_with_a_member()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT username, email FROM users")
            ).one()
        assert row.username == "kim"
        assert row.email is None

    def test_the_downgrade_drops_it(self):
        """Batch mode rebuilds the table to drop a column on SQLite, so this is
        the half of the migration that can silently take the row with it."""
        from alembic import command

        self.build_database_with_a_member()
        schema.upgrade_to_head()

        # Alembic directly: schema.py only ever moves forward, because the app
        # has no reason to downgrade itself at startup.
        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        columns = {column["name"] for column in inspect(engine).get_columns("users")}
        assert "email" not in columns
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1


@pytest.mark.usefixtures("restore_schema")
class TestTheSeededCatalogueTargetsMatchTheCode:
    """The ten rows the migrations write are the ten constants the code reads.

    **The migration writes literals rather than importing `targets.SEEDED`**,
    which is the rule `c1f8a7e3d240` states: a migration describes the data as it
    was on the day it ran, so a library upgrading in a year does not seed a
    roster that revision never saw. The cost of that rule is that the literal and
    the constant can disagree today, and this is what stops them.

    **So this compares a migrated database's rows against `targets.SEEDED`**,
    and there is no third copy to compare against: `models` describes the table
    and never its contents, and the literals exist nowhere but inside the
    revision, so reading them back out of a database is the only way to see
    them at all.
    """

    @staticmethod
    def _rows() -> dict[str, dict[str, object]]:
        drop_everything()
        schema.upgrade_to_head()
        with engine.connect() as connection:
            result = connection.execute(text("SELECT * FROM catalogue_targets"))
            return {row.source: dict(row._mapping) for row in result}

    def test_the_migration_seeds_the_whole_roster_and_nothing_else(self):
        assert set(self._rows()) == {source.value for source in targets.SEEDED}

    def test_every_seeded_row_says_what_the_constant_says(self):
        """Field by field, because a wrong index name is the failure that ships
        plausible MARC for an unrelated book rather than an error."""
        rows = self._rows()
        wrong: list[str] = []
        for source, target in targets.SEEDED.items():
            row = rows[source.value]
            expected: dict[str, object] = {
                "rank": target.rank,
                "transport": target.transport.value,
                "base_url": target.base_url,
                "reader": target.reader.value,
                "answers_lookup": target.answers_lookup,
                "answers_search": target.answers_search,
                "metered": target.metered,
                "needs_key": target.needs_key,
                "sru_version": target.sru_version,
                "query_parameter": target.query_parameter,
                "query_language": (
                    target.query_language.value if target.query_language else None
                ),
                "record_schema": target.record_schema,
                "isbn_index": target.isbn_index,
                "isbn_attribute": target.isbn_attribute,
                "title_index": target.title_index,
                "title_query_shape": (
                    target.title_query_shape.value if target.title_query_shape else None
                ),
                "lookup_records": target.lookup_records,
                "search_multiplier": target.search_multiplier,
                "search_cap": target.search_cap,
                "refuses_component_parts": target.refuses_component_parts,
                "requires_isbn_claim": target.requires_isbn_claim,
                "reads_author_identifiers": target.reads_author_identifiers,
                "timeout_seconds": target.timeout_seconds,
                "is_seeded": True,
            }
            for field, value in expected.items():
                stored = row[field]
                if isinstance(value, bool):
                    stored = bool(stored)
                if stored != value:
                    wrong.append(f"{source.value}.{field}: {stored!r} not {value!r}")
        assert not wrong, wrong

    def test_the_columns_the_migration_writes_are_every_column_there_is(self):
        """A column added to the model and not to the seed would be silently
        default filled, which is how a row comes to disagree with the code it was
        copied from."""
        row = next(iter(self._rows().values()))
        assert set(row) == {
            column.name
            for column in Base.metadata.tables["catalogue_targets"].columns
        }

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("requires_isbn_claim", 0),
            ("transport", "z3950"),
            ("isbn_index", "num=1 or num"),
            ("title_index", "a b"),
            # **These three discriminate and the four above do not**, which a
            # critic established by mutation rather than by reading: reverting
            # the index constraint to the ten character denylist it replaced
            # leaves `num=1 or num` and `a b` refused, so both fixtures were
            # cases the older version also caught. That is the shape this
            # repository names, a guard whose own test picked the covered case.
            #
            # A tab and a NBSP are CQL token separators the denylist never named,
            # so `dc.title<TAB>and<TAB>dc.title` is a two clause boolean written
            # through the column whose constraint exists to refuse exactly that.
            # Two spellings of the separator class, because one is a spelling and
            # two are a class.
            ("title_index", "dc.title\tand\tdc.title"),
            ("title_index", "dc.title\xa0and"),
            # `ck_catalogue_targets_use_attribute` had no SQL fixture at all:
            # `test_targets.py` covers this value, but only through
            # `__post_init__`, which is the arm a Core insert skips. Deleting the
            # constraint failed nothing.
            ("isbn_attribute", "7 @and @attr 1=4 anything"),
        ],
    )
    def test_a_restore_cannot_write_a_row_the_dataclass_would_refuse(
        self, column, value
    ):
        """`backup.restore` writes through Core, where no validator and no
        `__post_init__` fires, so these are CHECK constraints or they are
        nothing. The ÖNB row is the subject because a mistyped index there
        answers HTTP 200 with the whole catalogue rather than with an error.
        """
        self._rows()
        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    # The interpolation is a column name chosen by this loop, never a request value.
                    f"UPDATE catalogue_targets SET {column} = :value "
                    "WHERE source = 'oenb'"
                ),
                {"value": value},
            )

    def test_the_dnb_may_waive_the_isbn_claim_and_only_the_dnb(self):
        """The other half of the diagonal above: the constraint states one
        measured exception rather than refusing the column outright."""
        self._rows()
        with engine.connect() as connection:
            connection.execute(
                text(
                    "UPDATE catalogue_targets SET requires_isbn_claim = 0 "
                    "WHERE source = 'dnb'"
                )
            )
            connection.commit()


class TestTheStoredShelfKey:
    """Revision f1c30ab27d84, which adds `classifications.sort_key` and fills it.

    Two things can go wrong and only one of them is loud. The loud one is the
    NOT NULL: a row the backfill missed fails the rebuild. The quiet one is a
    key that is filled in **wrongly**, because the revision carries its own copy
    of the filing rule rather than importing `filing`, which is the rule
    `a4c73e0b19d5`, `c9a5f27b3e41`, `c1f8a7e3d240` and `b7d4e6f01a95` each state:
    a migration describes the data as it was on the day it ran.

    The cost of that rule is a second statement of one rule, and this is what
    holds the two together today, exactly as
    `TestTheSeededCatalogueTargetsMatchTheCode` does for the seeded roster. The
    corpus is `tests/test_filing.py::CORPUS`, which reaches all twelve class
    shapes twice over: a shape it did not reach would be a shape the copy could
    get wrong in silence.
    """

    PREVIOUS = "b7d4e6f01a95"

    #: Numbers whose keys differ from the numbers, so a backfill that copied the
    #: number across would fail rather than pass. `BF75` pads to `BF 0075...`
    #: and `005.13/3` loses the segmentation prime.
    FILED = [
        ("lcc", "BF75"),
        ("lcc", "BF575.S75 E64 2022"),
        ("ddc", "005.13/3"),
        ("gnd", "4026894-9"),
    ]

    def build_database_one_revision_back(self) -> None:
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO books (title, is_private, added_at, ownership) "
                    "VALUES ('Clean Code', 0, datetime('now'), 'owned')"
                )
            )
            for scheme, number in self.FILED:
                connection.execute(
                    text(
                        "INSERT INTO classifications (book_id, scheme, number, label) "
                        "VALUES (1, :scheme, :number, NULL)"
                    ),
                    {"scheme": scheme, "number": number},
                )
            connection.commit()

    @staticmethod
    def stored() -> list[tuple[str, str, str]]:
        with engine.connect() as connection:
            return [
                (row.scheme, row.number, row.sort_key)
                for row in connection.execute(
                    text("SELECT scheme, number, sort_key FROM classifications ORDER BY id")
                )
            ]

    def test_a_row_written_before_the_column_existed_is_backfilled(self):
        """Not left null. A null files last under `nullslast`, so the book would
        stand at the end of every shelf order with nothing to see."""
        self.build_database_one_revision_back()

        schema.upgrade_to_head()

        assert self.stored() == [
            (scheme, number, filing.sort_key_for(scheme, number))
            for scheme, number in self.FILED
        ]

    def test_the_column_refuses_a_row_with_no_key(self):
        """The rebuild's whole point. Without NOT NULL a writer that skipped the
        derivation would store a null and nothing would say so."""
        self.build_database_one_revision_back()
        schema.upgrade_to_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO classifications (book_id, scheme, number, label) "
                    "VALUES (1, 'lcc', 'QA76', NULL)"
                )
            )

    def test_the_unique_index_survives_the_rewrite(self):
        """Batch mode rebuilds the table by reflecting it, and losing this index
        would let every re-run of enrichment deposit a second copy of a
        heading. `b7d41f0a2c95` pins the same property for its own rewrite."""
        self.build_database_one_revision_back()
        schema.upgrade_to_head()

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO classifications "
                    "(book_id, scheme, number, label, sort_key) "
                    "VALUES (1, 'lcc', 'BF75', NULL, 'x')"
                )
            )

    def test_the_downgrade_takes_the_column_away_and_keeps_the_rows(self):
        """Nothing is lost by dropping it: every value in it is derived from the
        two columns beside it."""
        from alembic import command

        self.build_database_one_revision_back()
        schema.upgrade_to_head()

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        with engine.connect() as connection:
            numbers = list(
                connection.execute(
                    text("SELECT number FROM classifications ORDER BY id")
                ).scalars()
            )
            columns = {
                column["name"] for column in inspect(engine).get_columns("classifications")
            }
        assert numbers == [number for _scheme, number in self.FILED]
        assert "sort_key" not in columns

    @pytest.mark.parametrize("scheme", [scheme.value for scheme in ClassificationScheme])
    def test_the_revisions_copy_of_the_rule_says_what_filing_says(self, scheme):
        """Over the corpus, which is where the copy can go wrong quietly.

        Parametrised over the enum rather than over the three schemes the copy
        names, so a fifth scheme is compared on the day it is added: the copy
        answers a scheme it does not name with the generic key, and this is what
        would notice if that stopped being right.
        """
        mismatches = [
            (number, revision._sort_key(scheme, number), filing.sort_key_for(scheme, number))
            for number in CORPUS
            if revision._sort_key(scheme, number) != filing.sort_key_for(scheme, number)
        ]

        assert mismatches == []

    def test_the_copy_and_the_rule_agree_on_a_generated_corpus(self):
        """So the hand written list cannot be the only evidence.

        Drawn from an alphabet of the characters that decide a branch: letters
        in both cases, digits, the point, the space and the segmentation prime.
        400 values, seeded, against the Library of Congress rule, which is the
        only one of the three with any branching to get wrong.
        """
        generator = random.Random(137)
        alphabet = "AZaz09. /"
        values = [
            "".join(generator.choice(alphabet) for _ in range(generator.randint(0, 14)))
            for _ in range(400)
        ]

        mismatches = [
            value
            for value in values
            if revision._sort_key("lcc", value) != filing.sort_key_for("lcc", value)
        ]

        assert mismatches == []


@pytest.mark.usefixtures("restore_schema")
class TestTheBookFormatColumnOnAMigratedDatabase:
    """`BookFormat` is closed in Python and open in the database, asserted.

    The enum's docstring says a new member needs no migration, and that claim
    is about the schema a deployment has rather than about `models.py`. So it
    is checked against a database built by `upgrade_to_head`, which is the one
    instrument that can see a check constraint a revision added and the model
    never declared.

    **Every case recomputes from `BookFormat` itself**, so a seventh member is
    covered the moment somebody writes it and a stale count cannot pass here.
    """

    @staticmethod
    def _migrated() -> None:
        drop_everything()
        schema.upgrade_to_head()

    @staticmethod
    def _format_column():
        return next(
            column
            for column in inspect(engine).get_columns("books")
            if column["name"] == "format"
        )

    def test_no_check_constraint_governs_the_column(self):
        """The whole of the claim. A migration adding one would make a new
        member a schema change, and the failure would land on a member's import
        rather than here."""
        self._migrated()

        governing = [
            constraint
            for constraint in inspect(engine).get_check_constraints("books")
            if "format" in str(constraint.get("sqltext", ""))
        ]

        assert governing == []

    def test_every_member_fits_the_width_the_column_declares(self):
        """Read off the migrated column rather than off the literal `20`.

        SQLite does not enforce a `VARCHAR` width, so nothing else in this file
        would notice a member too long for the column until the same schema ran
        on a database that does.
        """
        width = self._format_column()["type"].length
        assert width, "the column declares no width, so this asserts nothing"

        assert [one for one in BookFormat if len(one.value) > width] == []

    def test_every_member_the_enum_offers_is_storable(self):
        """The behavioural half, and the one a narrowed column breaks."""
        self._migrated()

        with engine.connect() as connection:
            for one in BookFormat:
                connection.execute(
                    text("INSERT INTO books (title, format) VALUES (:title, :format)"),
                    {"title": f"a book on {one.value}", "format": one.value},
                )
            connection.commit()
            stored = {
                row[0]
                for row in connection.execute(text("SELECT format FROM books")).fetchall()
            }

        assert stored == {one.value for one in BookFormat}


class TestANoteCarriesItsOwnVisibility:
    """Migration `a3d7f1b09c25`, as schema and as what it did to stored rows.

    Every revision runs once per worker at session start, so this one's effect
    on an **empty** `notes` table is exercised whether these tests exist or not.
    What nothing else reaches is its effect on stored rows: that a note written
    before the column existed still means what it meant, and that the
    downgrade's loss is the one the docstring admits to.
    """

    PREVIOUS = "d9c1f47b2a06"

    def _a_database_with_a_note(self) -> None:
        drop_everything()
        schema.upgrade_to_head()
        from alembic import command

        command.downgrade(schema._alembic_config(), self.PREVIOUS)
        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (username, password_hash, is_admin) "
                    "VALUES ('reader', 'x', 0)"
                )
            )
            connection.execute(text("INSERT INTO books (title) VALUES ('Dune')"))
            connection.execute(
                text(
                    "INSERT INTO notes (book_id, user_id, content) "
                    "VALUES (1, 1, 'written before the column existed')"
                )
            )
            connection.commit()

    def test_a_note_that_predates_the_column_stays_shared(self):
        """The migration's own claim: no stored row changes meaning. A note
        written into a shared library has been readable by the other members
        since it was saved, and running this must not take it off their
        screens."""
        self._a_database_with_a_note()

        schema.upgrade_to_head()

        with engine.connect() as connection:
            stored = [
                tuple(row)
                for row in connection.execute(text("SELECT content, is_private FROM notes"))
            ]
        assert stored == [("written before the column existed", 0)]

    def test_the_downgrade_loses_the_distinction_and_not_the_notes(self):
        """Stated in the revision rather than worked around: there is no second
        place the flag lives, so going back to a schema without the column
        makes every private note readable again."""
        from alembic import command

        drop_everything()
        schema.upgrade_to_head()
        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (username, password_hash, is_admin) "
                    "VALUES ('reader', 'x', 0)"
                )
            )
            connection.execute(text("INSERT INTO books (title) VALUES ('Dune')"))
            connection.execute(
                text(
                    "INSERT INTO notes (book_id, user_id, content, is_private) "
                    "VALUES (1, 1, 'what I actually thought', 1)"
                )
            )
            connection.commit()

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        columns = {column["name"] for column in inspect(engine).get_columns("notes")}
        assert "is_private" not in columns
        with engine.connect() as connection:
            stored = [
                tuple(row) for row in connection.execute(text("SELECT content FROM notes"))
            ]
        assert stored == [("what I actually thought",)]


class TestTheMigratedDatabaseCarriesTheBoundsItPromises:
    """Revision `b2e94f7c1a03`, and whether the model still describes it.

    **The migration is the schema everywhere, tests included, and that is the
    fact this class was first written with backwards.** `main.py` calls
    `init_db()` at **import** time and its comment says why: "Alembic owns the
    schema, including creating it from nothing. There is no create_all() here on
    purpose: two things that both create tables is how a database ends up in a
    shape no migration accounts for." `conftest` imports `main`, so the
    migrations have run before any fixture, and `_schema_once`'s `create_all`
    then finds every table already present and does nothing.

    So a `CheckConstraint` in `models.py` is by default a **description** of the
    revision rather than a second enforcement of it. Measured 2026-09-10, three
    ways: replacing this table's whole CHECK with a constant false expression in
    `models.py` alone failed **nothing**, and neither did zeroing one of its
    terms nor shrinking its byte budget. The imported model carried the mutation
    and the installed DDL did not.

    **By default, because a test can opt out of the ambient schema**, and one
    does: `test_credentials.py::TestTheEnvelopeRuleAndItsConstraintAgree`
    creates the model's own table on a throwaway `sqlite://` engine and probes
    it, so the models' declaration is enforced there rather than described.
    `test_the_model_declares_a_constraint_that_enforces_the_bound` below is that
    shape applied here, and it is what makes this table's model side a rule.

    That is the hole this class closes, and it is not the one the first draft
    thought it was. `TestTheMigrationsAndTheModelsAgree` compares columns,
    nullability and type, so a column **width** is covered there. Nothing
    compared **this** constraint's two copies, and there are two copies because
    a migration must not import a constant it would then change meaning with.
    """

    @staticmethod
    def _migrated() -> int:
        drop_everything()
        schema.upgrade_to_head()
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO books (title, ownership) VALUES ('A book', 'owned')")
            )
            connection.commit()
            book_id = connection.execute(text("SELECT id FROM books")).scalar()
        assert isinstance(book_id, int)
        return book_id

    @staticmethod
    def _insert(book_id: int, root: str, path: str) -> None:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO digital_references (book_id, root_label, relative_path)"
                    " VALUES (:book, :root, :path)"
                ),
                {"book": book_id, "root": root, "path": path},
            )
            connection.commit()

    def test_the_pair_bound_survived_into_the_migration(self):
        book = self._migrated()
        half = models.DIGITAL_REFERENCE_PATH_MAX // 2 + 1

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "r" * half, "p" * half)

        assert "ck_digital_references_bounds" in str(refusal.value)

    def test_a_null_carrying_value_cannot_walk_past_the_character_bound(self):
        """The arm the character inequality cannot supply on its own.

        SQLite's `length()` counts characters **up to the first NUL**, so this
        value reports a length of 1 and carries 10,002 bytes. Pydantic refuses a
        NUL and Pydantic is exactly what a restore does not run, which is what
        makes the byte arm the thing standing between an archive and an
        unbounded write.
        """
        book = self._migrated()
        past_the_byte_budget = 4 * models.DIGITAL_REFERENCE_PATH_MAX + 1

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "a\x00" + "x" * past_the_byte_budget, "p")

        assert "ck_digital_references_bounds" in str(refusal.value)

    def test_the_byte_arm_refuses_nothing_nul_free_the_character_arm_admits(self):
        """The other side, without which the test above is satisfied by a
        constraint that refuses everything.

        **Exactly on the boundary.** The widest legitimate pair spends the whole
        character budget on four byte characters in **both** halves, which is
        four times the budget. One ASCII character on the right leaves three
        bytes of slack, which is enough room for a mutation to shrink the
        multiplier and stay green.
        """
        book = self._migrated()
        widest = models.DIGITAL_REFERENCE_PATH_MAX - 1

        self._insert(book, "\U0001f600" * widest, "\U0001f600")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM digital_references")
            ).scalar() == 1

    def test_the_location_is_unique_in_the_migration_too(self):
        """The index that makes a re-import a refresh rather than a doubling.
        Declared `unique=True` on the model; only this says the revision creates
        it that way."""
        book = self._migrated()
        self._insert(book, "/books", "a.epub")

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "/books", "a.epub")

        # SQLite names the **columns** in a UNIQUE failure and not the index,
        # so this asserts the three that make up the location. Asserting the
        # index name instead passes on any unique index over any columns, which
        # is what a first draft of this did.
        assert "digital_references.book_id" in str(refusal.value)
        assert "digital_references.root_label" in str(refusal.value)
        assert "digital_references.relative_path" in str(refusal.value)

    def test_the_model_declares_a_constraint_that_enforces_the_bound(self):
        """The models' own table, built on a throwaway engine and probed.

        **This is the difference between the model's CHECK being a rule and
        being a comment.** Nothing in the ambient suite runs against the models'
        DDL, so a `CheckConstraint` there can say anything; a table created on an
        engine of this test's own cannot. The shape is
        `test_credentials.py::TestTheEnvelopeRuleAndItsConstraintAgree._accepted`,
        which got here first and states the reason at its own site.

        **Behaviour, where the comparison below is text**, and that is why both
        exist. This one closes the family a containment substring accepts, an
        installed constraint that appends to the model's and refuses nothing:
        such a constraint fails here at the first insert. The comparison closes
        what behaviour cannot see, a model and a revision that both enforce
        something sane and different.

        Through `Base.metadata.tables` rather than `__table__`, which the ORM
        types as a `FromClause`. Same object, and the name comes off the model.
        No `books` table is created beside it: SQLite checks a foreign key only
        with `PRAGMA foreign_keys` on, and this engine has it off.
        """
        engine = create_engine("sqlite://")
        Base.metadata.tables["digital_references"].create(engine)
        insert = text(
            "INSERT INTO digital_references (book_id, root_label, relative_path)"
            " VALUES (1, :root, :path)"
        )
        widest = models.DIGITAL_REFERENCE_PATH_MAX - 1

        over_the_byte_budget = {
            "root": "a\x00" + "x" * (4 * models.DIGITAL_REFERENCE_PATH_MAX),
            "path": "p",
        }
        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(insert, over_the_byte_budget)

        with engine.connect() as connection:
            connection.execute(
                insert,
                {"root": "\U0001f600" * widest, "path": "\U0001f600"},
            )
            assert connection.execute(
                text("SELECT count(*) FROM digital_references")
            ).scalar() == 1

    def test_the_model_still_describes_the_constraint_the_revision_installs(self):
        """The two copies of the CHECK, compared as text.

        This is what holds `ck_digital_references_bounds`'s two copies together.
        Without it the model's copy can say anything, because everything else
        runs on the revision's DDL: a constant false expression there fails
        nothing, measured.

        **Not the only such comparison in the tree**, and an earlier draft of
        this line claimed it was. `test_models.py::TestTheBorrowerRuleHasOneSpelling`
        reaches the same place for `loans` in two hops, pinning `ONE_BORROWER_SQL`
        to the model's `CheckConstraint` and then finding it in `sqlite_master`.
        That is the shape to copy, and it got here first.

        Compared against the DDL SQLite actually holds rather than against the
        revision's source, because that is the artefact both halves are supposed
        to describe and it cannot drift from what a deployment runs.

        **Containment, not equality, and here is what that accepts.** An
        installed constraint that appends to the model's text, `(<model> OR
        1=1)`, contains it and refuses nothing.

        **What closes that family here is the three behavioural probes above,
        not the plausibility of the accident.** A constraint refusing nothing
        fails `test_the_pair_bound_survived_into_the_migration` and
        `test_a_null_carrying_value_cannot_walk_past_the_character_bound` at
        once. The distinction is load bearing because this test is the obvious
        template for the other constraints, and one copied to a constraint with
        no behavioural sibling keeps the containment and loses the thing that
        was doing the work.

        **The whitespace normalisation is safe here and not in general**: this
        CHECK holds no string literal with internal whitespace, and the same
        generalisation inherits that caveat too.
        """
        self._migrated()
        table = Base.metadata.tables["digital_references"]
        declared = next(
            (
                " ".join(str(constraint.sqltext).split())
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
                and constraint.name == "ck_digital_references_bounds"
            ),
            None,
        )
        assert declared is not None, (
            "`models.DigitalReference` no longer declares "
            "`ck_digital_references_bounds`, so there is nothing to compare "
            "against the revision."
        )

        with engine.connect() as connection:
            installed = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name='digital_references'")
            ).scalar()

        assert declared in " ".join(str(installed).split()), (
            "`models.DigitalReference`'s CHECK is not the one the revision "
            "installs, so the model is describing a schema nobody runs.\n"
            f"  model:     {declared}\n"
            f"  installed: {installed}"
        )

    def test_the_revisions_bounds_are_the_models_bounds(self):
        """The two literals the revision keeps "in step with" `models.py`.

        A migration must not import a constant, because it describes the schema
        at one moment and would change meaning when the constant is retuned. The
        cost of that rule is a fact stored twice, and this is what stands
        between the copies.
        """
        assert where_a_book_file_is_said_to_be._PATH_MAX == (
            models.DIGITAL_REFERENCE_PATH_MAX
        )
        assert where_a_book_file_is_said_to_be._MAX_SIZE == (
            models.DIGITAL_REFERENCE_MAX_SIZE
        )


#: Every ceiling `f4a1c62d0b97` gave a byte arm, as `(table, column, others)`.
#:
#: **The character budget is deliberately not in this table.** It is read off
#: the column's own `String(n)` width, which is a different instrument from the
#: constraint text these cases are about: a probe built from the number the
#: constraint states would agree with a constraint that had drifted. Every one of
#: these columns is declared at exactly its ceiling, and
#: `test_the_column_width_is_the_ceiling` is what says so rather than leaving it
#: as the reason for a subtraction.
#:
#: `others` is what a bare insert needs beside the column under test: enough to
#: satisfy the table's other constraints and nothing more. Foreign keys are not
#: among them, because these run on an engine that has them off.
_TEXT_CEILINGS: tuple[tuple[str, str, dict[str, object]], ...] = (
    ("quotes", "text", {"book_id": 1, "user_id": 1}),
    ("quotes", "note", {"book_id": 1, "user_id": 1, "text": "a line"}),
    (
        "author_identifiers",
        "identifier",
        {"author_key": "borges-jorge-luis", "scheme": "gnd", "provenance": "catalogue"},
    ),
    ("custom_fields", "name", {"kind": "text"}),
    ("custom_field_values", "value", {"book_id": 1, "field_id": 1}),
    (
        "opds_servers",
        "name",
        {
            "base_url": "https://books.example/opds",
            "credential_key": "opds-0123456789abcdef",
        },
    ),
)

#: Which constraint each of those columns is bounded by.
#:
#: Two entries share one, which is why this is keyed on the column rather than
#: folded into the table above.
_CEILING_CONSTRAINTS: dict[tuple[str, str], str] = {
    ("quotes", "text"): "ck_quotes_text_bounds",
    ("quotes", "note"): "ck_quotes_text_bounds",
    ("author_identifiers", "identifier"): "ck_author_identifiers_bounds",
    ("custom_fields", "name"): "ck_custom_fields_name_bounds",
    ("custom_field_values", "value"): "ck_custom_field_values_bounds",
    ("opds_servers", "name"): "ck_opds_servers_name",
}


#: A byte arm, and a NUL clause, whatever case or spacing they are written in.
#:
#: **Folded, because SQL folds a function name and this file does not.** A scan
#: for `char(0)` never reaches `CHAR(0)` or `char (0)`, so a constraint spelled
#: that way would be in **neither** of the two sets below and the pair would
#: quietly stop covering it: measured, `INSTR(s, CHAR(0))` landed in neither.
#: The house rule in `test_house_rules.py` folds the same five names for the
#: same reason and records the measurement that found it.
_A_BYTE_ARM: Final = re.compile(r"\bas\s+blob\b", re.IGNORECASE)
_A_NUL_CLAUSE: Final = re.compile(r"\bchar\s*\(\s*0\s*\)", re.IGNORECASE)


def _declared_checks() -> dict[str, tuple[str, str]]:
    """Every named CHECK in `Base.metadata`, as `name -> (table, text)`."""
    declared: dict[str, tuple[str, str]] = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and isinstance(
                constraint.name, str
            ):
                declared[constraint.name] = (
                    table.name,
                    " ".join(str(constraint.sqltext).split()),
                )
    return declared


def _installed_checks() -> dict[str, tuple[str, str]]:
    """Every named CHECK the database in front of us carries, in the same shape.

    The other copy of `_declared_checks`, and deliberately the same return type:
    the comparison in `TestTheMigrationsAndTheModelsAgree` is then two dicts
    rather than a walk that could quietly visit one side only.

    **Read by reflection rather than off `sqlite_master`**, which is the other
    instrument in this file and is kept for the downgrade cases that need a
    clause and not a set. Reflection resolves a quoted constraint name, where the
    scan in `TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check`
    keys on the bare word and would read a legitimately quoted name as an absent
    constraint. Measured 2026-09-20 on the head schema: the two instruments
    return the same 30 clauses, which is an agreement between readers rather
    than a coverage figure, and is why both are kept.

    **An unnamed CHECK is refused below rather than skipped**, because
    `_declared_checks` skips one too and it would then be in neither copy.

    **Every table, not the ones a caller names**, so a constraint on a table
    nobody thought to list is compared rather than missed, and a constraint
    installed on a table that does not declare it is visible from this side.
    """
    inspector = inspect(engine)
    installed: dict[str, tuple[str, str]] = {}
    for table in inspector.get_table_names():
        for constraint in inspector.get_check_constraints(table):
            name = constraint.get("name")
            # **Refused rather than skipped**, because `_declared_checks` skips
            # an unnamed CHECK too: a constraint with no name would be in
            # neither dict and would be the one thing this rule cannot see. The
            # schema has none, and this is what stops the first one arriving
            # unexamined rather than being reported as a bound in a comment.
            assert isinstance(name, str), (
                f"{table} carries a CHECK with no name, which neither copy of "
                f"this comparison can address: {constraint['sqltext']}"
            )
            # A name is unique across this schema by convention, `ck_<table>_*`,
            # and `_declared_checks` is keyed the same way. Were two tables to
            # carry one name, that function would keep one of the two and the
            # comparison would pass over the other; this is where that shows.
            assert name not in installed, (
                f"`{name}` is installed on both {installed[name][0]} and {table}, "
                "so a comparison keyed on the name reads one of them only"
            )
            installed[name] = (table, " ".join(str(constraint["sqltext"]).split()))
    return installed


def _declared_constraint(table_name: str, constraint: str) -> str:
    """One CHECK as `models.py` declares it, whitespace normalised.

    Safe to normalise for every constraint in this schema: none holds a string
    literal with internal whitespace.

    **One copy, because there were three.** Two classes carried this expression
    verbatim and a third inlined it, which is the shape a name change goes stale
    against one caller at a time.
    """
    return " ".join(
        str(next(
            one
            for one in Base.metadata.tables[table_name].constraints
            if isinstance(one, CheckConstraint) and one.name == constraint
        ).sqltext).split()
    )


def _byte_armed_constraints() -> dict[str, str]:
    """Every CHECK in `Base.metadata` carrying a byte arm, by name.

    **Derived rather than listed**, so a ceiling given a byte arm later is
    covered by the two rules below with no edit here, and one given a byte arm
    that no revision installs fails rather than passing unexamined.
    """
    return {
        name: declared
        for name, (_, declared) in _declared_checks().items()
        if _A_BYTE_ARM.search(declared)
    }


class TestEveryTextCeilingIsInstalledWithItsByteArm:
    """`f4a1c62d0b97`, and whether every copy of it says the same thing.

    SQLite's `length()` on text counts characters up to the first NUL, so a
    ceiling written as a character inequality alone is not a ceiling on the one
    path it exists for: `backup.restore` inserts through Core and runs no
    Pydantic model. The arm that closes it is a byte budget of four times the
    character budget, four bytes being UTF-8's widest character.

    **Three rules, because no one of them is the guard.** The model's copy is a
    description of the revision and enforces nothing in the ambient suite, so
    `test_the_model_is_the_constraint_the_revision_installs` holds it against the
    installed DDL. Containment accepts an installed constraint that appends to
    the model's and refuses nothing, so
    `test_a_nul_carrying_value_is_refused` probes behaviour. And a constraint
    refusing everything passes that, so
    `test_the_widest_legitimate_value_is_stored` is the other side.

    **The behavioural pair runs on a throwaway engine**, which is what makes the
    model's own declaration a rule rather than a comment; the shape is
    `test_credentials.py::TestTheEnvelopeRuleAndItsConstraintAgree`, which got
    here first. Foreign keys are off on such an engine, which is why the tables
    these columns hang off are not created beside them.
    """

    @staticmethod
    def _probe(table_name: str) -> Connection:
        """This table alone, on an engine of this test's own, ready for a row."""
        throwaway = create_engine("sqlite://")
        Base.metadata.tables[table_name].create(throwaway)
        return throwaway.connect()

    @staticmethod
    def _ceiling(table_name: str, column: str) -> int:
        width = Base.metadata.tables[table_name].c[column].type
        assert isinstance(width, String) and width.length
        return width.length

    @pytest.mark.parametrize(("table_name", "column", "others"), _TEXT_CEILINGS)
    def test_the_column_width_is_the_ceiling(
        self, table_name: str, column: str, others: dict[str, object]
    ) -> None:
        """The two cases below read the budget off the width, so this is what
        says the width is the budget.

        A `String(n)` refuses nothing in SQLite and is there to document the
        column; where the two disagree, the probes would be aimed at a number
        the constraint does not use and would pass against a drifted bound.
        """
        declared = _byte_armed_constraints()[_CEILING_CONSTRAINTS[table_name, column]]

        assert f"length({column}) <= {self._ceiling(table_name, column)}" in declared or (
            f"length({column}) BETWEEN 1 AND {self._ceiling(table_name, column)}"
            in declared
        ), f"{table_name}.{column} is declared wider or narrower than it is bounded"

    @pytest.mark.parametrize(("table_name", "column", "others"), _TEXT_CEILINGS)
    def test_a_nul_carrying_value_past_the_byte_budget_is_refused(
        self, table_name: str, column: str, others: dict[str, object]
    ) -> None:
        """The class the character arm admits: `length()` reports 1 for this.

        **Named for what it actually pins.** The arm caps a NUL carrying value
        at the byte budget rather than refusing one, and a name saying otherwise
        is how the claim got into three docstrings before a critic measured it;
        `test_a_nul_carrying_value_under_the_byte_budget_is_stored` is the other
        side of that boundary.

        Sized off the byte budget rather than off some large number, so a
        mutation shrinking the multiplier is still refused here and has to be
        caught by the acceptance case instead. Both directions are wanted.

        **The refusal is checked by name**, because `pytest.raises(IntegrityError)`
        alone passes when the insert fails for an unrelated reason, such as a
        column this row forgot. The acceptance case sharing the same `others`
        closes that too, and one of the two should not be load bearing alone.
        """
        ceiling = self._ceiling(table_name, column)
        insert = Base.metadata.tables[table_name].insert()

        with (
            self._probe(table_name) as connection,
            pytest.raises(IntegrityError) as refusal,
        ):
            connection.execute(
                insert.values(**others, **{column: "a\x00" + "x" * (4 * ceiling)})
            )

        assert _CEILING_CONSTRAINTS[table_name, column] in str(refusal.value)

    @pytest.mark.parametrize(("table_name", "column", "others"), _TEXT_CEILINGS)
    def test_a_nul_carrying_value_under_the_byte_budget_is_stored(
        self, table_name: str, column: str, others: dict[str, object]
    ) -> None:
        """The boundary the docstrings now claim, asserted rather than described.

        A NUL carrying value reports a `length()` of 1 whatever it holds, so what
        stands between it and the disk is the byte arm alone: this one is exactly
        at the budget and is **stored**. That is the slack `models.py` records as
        accepted rather than closed with `instr(x, char(0)) = 0`, and it is
        pinned here so the prose cannot drift back to the stronger claim without
        something going red.

        **It is not an endorsement of the slack.** Closing it is a behaviour
        change with a migration of its own, and this case is what would have to
        be deleted to make that change, which is where the argument belongs.
        """
        ceiling = self._ceiling(table_name, column)
        table = Base.metadata.tables[table_name]
        at_the_budget = "a\x00" + "x" * (4 * ceiling - 2)

        with self._probe(table_name) as connection:
            connection.execute(table.insert().values(**others, **{column: at_the_budget}))

            assert connection.execute(
                text(f"SELECT count(*) FROM {table_name}")
            ).scalar() == 1

    @pytest.mark.parametrize(("table_name", "column", "others"), _TEXT_CEILINGS)
    def test_the_widest_legitimate_value_is_stored(
        self, table_name: str, column: str, others: dict[str, object]
    ) -> None:
        """The other side, without which a constraint refusing everything passes.

        **Exactly on the boundary.** The widest legitimate value spends the whole
        character budget on four byte characters, which is four times the budget
        and lands on the byte arm rather than under it. One ASCII character would
        leave three bytes of slack, which is room for a mutation to shrink the
        multiplier and stay green.
        """
        ceiling = self._ceiling(table_name, column)
        table = Base.metadata.tables[table_name]

        with self._probe(table_name) as connection:
            connection.execute(
                table.insert().values(**others, **{column: "\U0001f600" * ceiling})
            )

            assert connection.execute(
                text(f"SELECT count(*) FROM {table_name}")
            ).scalar() == 1

    @pytest.mark.parametrize("name", sorted(_byte_armed_constraints()))
    def test_the_model_is_the_constraint_the_revision_installs(self, name: str) -> None:
        """The two copies, compared against the DDL a migrated database holds.

        Against `sqlite_master` rather than against the revision's source,
        because that is the artefact both copies describe and it cannot drift
        from what a deployment runs.

        **Containment, not equality**, and what that accepts is an installed
        constraint appending to the model's. The behavioural pair above is what
        closes that family, which is why this is not the only rule here.

        **The whitespace normalisation is safe for these and not in general**:
        none of these constraints holds a string literal with internal
        whitespace.
        """
        drop_everything()
        schema.upgrade_to_head()
        declared = _byte_armed_constraints()[name]

        installed = self._installed()

        assert declared in installed, (
            f"`{name}` in models.py is not the constraint any revision installs, "
            f"so the model is describing a schema nobody runs.\n  model: {declared}"
        )

    def test_every_byte_armed_constraint_has_a_behavioural_case(self) -> None:
        """A ceiling given a byte arm and no probe would be held by containment
        alone, which an appending constraint satisfies.

        The whole set at once, so a new one has to be given a row in
        `_TEXT_CEILINGS` rather than inheriting a rule that cannot see it.
        `ck_digital_references_bounds` is probed by
        `TestTheMigratedDatabaseCarriesTheBoundsItPromises` instead, and is named
        here because that is where its cases live.

        **This is load bearing for a second reason, and a docstring giving one
        of two is the shape where a reviewer agrees with the comment and the hole
        survives.** The house rule in `test_house_rules.py` clears a ceiling when
        it finds a byte arm **anywhere** in the constraint's text, so an arm
        wrapped in a disjunction that binds on no row clears it there: measured,
        `(page IS NULL OR length(CAST(text AS BLOB)) <= 8000)` leaves that rule
        green. What refuses it is this side, because the constraint still carries
        `AS BLOB`, so it is still forced into a probe and the probe still inserts
        a value past the budget. The rule's `instr` branch has no such backstop,
        which is why that one had to be tightened to a top level conjunct instead.
        """
        probed = set(_CEILING_CONSTRAINTS.values()) | {
            "ck_digital_references_bounds",
            # Probed by `TestTheGlobRulesThatLearnedAboutNul` instead, and named
            # here because that is where its cases live. It is not in
            # `_TEXT_CEILINGS` because that table's cases require a column that
            # **admits** a NUL, and this one refuses one outright.
            "ck_opds_servers_base_url",
            # The four `b8f4c1a7e309` armed, probed by
            # `TestTheBoundsThisRevisionPutOnBytes`. None of them can be a row
            # in `_TEXT_CEILINGS` either: three refuse a NUL outright and the
            # fourth, `ck_catalogue_credentials_envelope`, has no `String(n)`
            # for that table to read a budget off. Their probe is a **lead
            # byte** rather than a NUL, which is the better instrument anyway:
            # it is the value the character arm cannot see at all.
            "ck_book_identifiers_bounds",
            "ck_catalogue_credentials_envelope",
            "ck_catalogue_targets_base_url",
            "ck_catalogue_targets_indexes",
        }

        assert set(_byte_armed_constraints()) == probed, (
            "these carry a byte arm that nothing probes: "
            f"{sorted(set(_byte_armed_constraints()) - probed)}"
        )

    PREVIOUS = "b2e94f7c1a03"

    @staticmethod
    def _installed() -> str:
        with engine.connect() as connection:
            return " ".join(
                " ".join(str(row[0]).split())
                for row in connection.execute(
                    text("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
                )
            )

    @staticmethod
    def _only_row(result: Any) -> int:
        """The id an insert just wrote. `inserted_primary_key` is optional to
        the type checker and never None for a single-row insert here."""
        key = result.inserted_primary_key
        assert key is not None
        return int(key[0])

    @classmethod
    def _installed_check(cls, name: str) -> str:
        """One named CHECK's expression, as the database holds it.

        **A whole clause rather than a substring, and that distinction caught a
        mutation the substring form did not.** Dropping the floor from a
        revision's `before`, leaving `length(identifier) <= 60`, is still
        contained in the installed `length(identifier) > 0 AND
        length(identifier) <= 60`, so a containment check passed on a downgrade
        that would have left the column accepting an empty identifier. Reading
        the constraint's own parentheses is what makes the comparison an
        equality.
        """
        sql = cls._installed()
        marker = f"CONSTRAINT {name} CHECK ("
        assert marker in sql, f"the migrated schema carries no {name}"
        start = sql.index(marker) + len(marker)
        depth = 1
        for position in range(start, len(sql)):
            if sql[position] == "(":
                depth += 1
            elif sql[position] == ")":
                depth -= 1
                if depth == 0:
                    return " ".join(sql[start:position].split())
        raise AssertionError(f"{name}'s CHECK is unbalanced in sqlite_master")


    @pytest.mark.parametrize(
        "rule", bind_every_text_ceiling._CEILINGS, ids=lambda rule: rule.constraint
    )
    def test_the_downgrade_puts_each_ceiling_back(
        self, rule: SwappedRule
    ) -> None:
        """`downgrade()`, run rather than read, and `before` checked against a
        schema this revision did not write.

        **The order of these three assertions is the whole test.** A first
        version ran the downgrade and compared the result with `before`, which is
        a tautology: `downgrade()` installs `before`, so any value is
        self-consistent and both a wrong ceiling and a dropped floor scored 42
        passed. What breaks the circle is asking the **previous** schema, built
        by other revisions entirely, whether `before` is what this one found.

        **And the comparison is an equality, which a second version was not.**
        With `before` matched as a substring the wrong ceiling failed and the
        dropped floor still passed, because `length(identifier) <= 60` is
        contained in `length(identifier) > 0 AND length(identifier) <= 60`. See
        `_installed_check`.

        `before` is load bearing and nothing else touches it. `drop_constraint`
        takes a name, so the upgrade never reads it and a wrong one breaks only
        the way back, in the one situation nobody is watching.

        Per constraint rather than in total, so a revision that put four back and
        lost the fifth fails here.
        """
        from alembic import command

        drop_everything()
        schema.upgrade_to(self.PREVIOUS)

        # The independent half: this schema is what the previous revisions
        # installed, so it is evidence about `before` rather than an echo of it.
        assert self._installed_check(rule.constraint) == " ".join(rule.before.split())

        schema.upgrade_to_head()
        assert self._installed_check(rule.constraint) == " ".join(rule.after.split())

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        assert self._installed_check(rule.constraint) == " ".join(rule.before.split())

    def test_the_upgrade_refuses_a_row_the_new_ceiling_cannot_hold(self) -> None:
        """The revision's own account of what it does to existing rows.

        It says "nothing, or it refuses to run", and that is a claim about a
        batch rebuild being `INSERT INTO new SELECT FROM old` with the new CHECK
        applied to the copy. Prose is the weakest rung, so this runs it: a value
        that `b2e94f7c1a03` accepts is planted, and the upgrade fails on it by
        name.

        **The row is one no application path can write**, which is the other half
        of that paragraph and is why refusing is the right answer rather than a
        hazard: `QuoteCreate` bounds the Python string, whose `len` counts past a
        NUL and reads 10,002 here.
        """
        drop_everything()
        schema.upgrade_to(self.PREVIOUS)
        tables = Base.metadata.tables
        with engine.connect() as connection:
            # Through the `Table` objects rather than raw SQL, so the models'
            # own column defaults apply: `users` has NOT NULL columns whose
            # value a hand written INSERT has to know, and this revision adds no
            # column, so today's metadata describes the previous schema exactly.
            book = self._only_row(
                connection.execute(
                    tables["books"].insert().values(title="A book", ownership="owned")
                )
            )
            member = self._only_row(
                connection.execute(
                    tables["users"].insert().values(username="a-member")
                )
            )
            connection.execute(
                tables["quotes"].insert().values(
                    book_id=book, user_id=member, text="a\x00" + "x" * 10_000
                )
            )
            connection.commit()

        with pytest.raises(IntegrityError) as refusal:
            schema.upgrade_to_head()

        assert "ck_quotes_text_bounds" in str(refusal.value)

        # **A failed batch rebuild leaves its scratch table behind**, and this
        # test found that rather than assuming it: without this line the next
        # case in this module dies on "table _alembic_tmp_quotes already
        # exists", because `drop_everything` works from `Base.metadata` and that
        # table is in no model. An operator retrying the upgrade meets the same
        # thing, which is why the revision's docstring now says so.
        with engine.connect() as connection:
            connection.execute(text("DROP TABLE IF EXISTS _alembic_tmp_quotes"))
            connection.commit()


    @pytest.mark.parametrize(
        "rule", bind_every_text_ceiling._CEILINGS, ids=lambda rule: rule.constraint
    )
    def test_the_revisions_text_is_the_models_text(
        self, rule: SwappedRule
    ) -> None:
        """The revision writes its SQL out rather than importing a constant, so
        the two copies are a fact stored twice and this is what stands between
        them.

        The `before` half is not compared: it describes the schema the revision
        found, which by definition is no longer the one `models.py` declares.
        `test_the_model_is_the_constraint_the_revision_installs` covers the
        `after` half against a database rather than against a string, and this
        covers it against the model, so a revision editing one table's text and
        not the other's fails one of the two.
        """
        declared = " ".join(
            str(next(
                one
                for one in Base.metadata.tables[rule.table].constraints
                if isinstance(one, CheckConstraint) and one.name == rule.constraint
            ).sqltext).split()
        )

        assert " ".join(rule.after.split()) == declared


class TestTheIdentifierBoundsSurvivedIntoTheMigration:
    """Revision `c7b0a3e5d281`, against the schema production runs.

    **The migration is the schema everywhere, tests included**, which is the
    fact `TestTheMigratedDatabaseCarriesTheBoundsItPromises` was first written
    with backwards and states in full. `main.py` calls `init_db()` at import,
    `conftest` imports `main`, and `create_all` then finds every table already
    there and does nothing. So the `CheckConstraint` in `models.py` is a
    **description** of this revision unless something reads the installed DDL,
    and this is what reads it.

    `TestTheMigrationsAndTheModelsAgree` compares columns, nullability and type.
    A CHECK is none of those, and neither is a unique index's key, so a
    revision that dropped either would still match there.
    """

    @staticmethod
    def _migrated() -> int:
        drop_everything()
        schema.upgrade_to_head()
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO books (title, ownership) VALUES ('A book', 'owned')")
            )
            connection.commit()
            book_id = connection.execute(text("SELECT id FROM books")).scalar()
        assert isinstance(book_id, int)
        return book_id

    @staticmethod
    def _insert(book_id: int, scheme: str, value: str) -> None:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO book_identifiers (book_id, scheme, value)"
                    " VALUES (:book, :scheme, :value)"
                ),
                {"book": book_id, "scheme": scheme, "value": value},
            )
            connection.commit()

    def test_the_table_exists_at_head(self):
        self._migrated()

        assert "book_identifiers" in table_names()

    def test_the_migration_and_the_model_agree_about_the_width(self):
        """Two copies of one number, because a revision must not import a
        constant it would then change meaning with. This is what stands between
        them."""
        assert what_a_store_calls_a_book._VALUE_MAX == models.BOOK_IDENTIFIER_MAX

    def test_a_value_past_the_ceiling_is_refused(self):
        book = self._migrated()

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "asin", "B" * (models.BOOK_IDENTIFIER_MAX + 1))

        assert "ck_book_identifiers_bounds" in str(refusal.value)

    def test_a_null_carrying_value_cannot_walk_past_the_character_bound(self):
        """The arm the character inequality cannot supply on its own.

        SQLite's `length()` counts characters **up to the first NUL**, so this
        value reports a length of 1 and carries 10,002 bytes. Pydantic refuses a
        NUL and Pydantic is exactly what a restore does not run, which is what
        makes this arm the thing standing between an archive and an unbounded
        write.

        **Refused outright rather than capped at a byte budget**, which is where
        this column parts company with `digital_references`: every value here is
        a token a machine wrote, so a NUL is never legitimate.

        **That refusal is tighter and it is not a byte bound.** With this arm and
        the character ceiling alone the constraint admitted 60 counted characters
        at 1,000,020 bytes, because a lead byte counts one and its continuation
        bytes count nothing. `b8f4c1a7e309` closed that with a budget of 240 and
        `TestTheBoundsThisRevisionPutOnBytes` is where the lead byte is refused;
        this case is still the NUL's own, which that budget caps rather than
        refuses on every other column that carries one.
        """
        book = self._migrated()

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "asin", "a\x00" + "x" * 10000)

        assert "ck_book_identifiers_bounds" in str(refusal.value)

    def test_a_nul_free_value_on_the_boundary_is_taken(self):
        """The other side, without which the two tests above are satisfied by a
        constraint that refuses everything.

        **Four byte characters throughout, because the ceiling counts code
        points and SQLite's `length()` counts them too.** An earlier version of
        this sentence claimed the value would also have failed a byte budget:
        60 four byte characters is 240 bytes and `4 * BOOK_IDENTIFIER_MAX` is
        240, so it passes one exactly. Since `b8f4c1a7e309` the column carries
        that budget, and this case is therefore the acceptance side of it as
        well: tightening the arm by one byte reddens here, which is why
        `TestTheBoundsThisRevisionPutOnBytes` probes the refusal and leaves the
        acceptance where it already was.
        """
        book = self._migrated()

        self._insert(book, "asin", "\U0001f4d6" * models.BOOK_IDENTIFIER_MAX)

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM book_identifiers")
            ).scalar() == 1

    def test_an_empty_value_is_refused(self):
        book = self._migrated()

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "asin", "")

        assert "ck_book_identifiers_bounds" in str(refusal.value)

    def test_every_scheme_the_enum_offers_is_storable(self):
        """`BookIdentifierScheme` and `ck_book_identifiers_scheme` cannot
        separate.

        The drift `TestTheMigrationsAndTheModelsAgree` cannot see, and its
        counterpart for the authority schemes states the argument in full: a
        member added without a revision is a value the application accepts and
        the deployment rejects, surfacing as an `IntegrityError` on somebody's
        first import rather than as a red pipeline.

        **Driven off the enum rather than a written out list**, so a member
        added tomorrow is covered without anybody remembering this test exists.

        **Against the migrated database, never the model's.** `models._scheme_
        check` derives the same constraint from the same enum, so a model built
        check can only ever agree with itself.
        """
        book = self._migrated()

        refused: list[str] = []
        for scheme in BookIdentifierScheme:
            try:
                # A distinct value per scheme, so
                # `uq_book_identifiers_book_scheme_value` cannot be what refuses
                # the second row and be read as the CHECK doing it.
                self._insert(book, scheme.value, f"V{scheme.value}")
            except IntegrityError:
                refused.append(scheme.value)

        assert refused == [], (
            "These members of BookIdentifierScheme are not storable on a "
            f"migrated database: {refused}. Write the revision that widens "
            "ck_book_identifiers_scheme."
        )

    def test_a_scheme_the_enum_does_not_offer_is_refused(self):
        """The other side of the derivation above, which alone is satisfied by
        a constraint that admits everything."""
        book = self._migrated()

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "kobo", "abc")

        assert "ck_book_identifiers_scheme" in str(refusal.value)

    def test_the_unique_key_carries_the_value_and_not_only_the_scheme(self):
        """The half a column comparison cannot see, and the half a merge
        depends on: two differing ASINs on one book are what folding two Kindle
        entries produces, and an index keyed on the scheme alone would answer
        that with an `IntegrityError`."""
        book = self._migrated()

        self._insert(book, "asin", "B00J4YQKHY")
        self._insert(book, "asin", "B00OTHER01")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM book_identifiers")
            ).scalar() == 2

    def test_the_same_assertion_twice_is_refused(self):
        book = self._migrated()

        self._insert(book, "asin", "B00J4YQKHY")

        with pytest.raises(IntegrityError) as refusal:
            self._insert(book, "asin", "B00J4YQKHY")

        # The columns rather than the index name: SQLite names the key's
        # columns in a UNIQUE violation and never the index that declared it,
        # so asserting the name here passes on any `IntegrityError` at all.
        assert "UNIQUE constraint failed" in str(refusal.value)
        assert "book_identifiers.value" in str(refusal.value)

    def test_the_downgrade_takes_the_table_and_nothing_else(self):
        """The table is the only place an identifier lives, so a downgrade can
        do nothing else. What it must not do is take the books with it."""
        from alembic import command

        book = self._migrated()
        self._insert(book, "asin", "B00J4YQKHY")

        command.downgrade(schema._alembic_config(), "f4a1c62d0b97")

        assert "book_identifiers" not in table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM books")).scalar() == 1


class TestTheGlobRulesThatLearnedAboutNul:
    """`a6d3f92c7b14`, and the distinction it exists to keep.

    SQLite's `GLOB` stops at the first NUL, exactly as `length()` does. Five
    CHECKs in this schema rest on `GLOB`; **three carried no NUL clause beside
    them, and only one of those three is defeated by that**. So the cases here
    are per constraint rather than parametrised over a class: a rule treating the
    three as one is the failure the revision was written to prevent.

    **`ck_catalogue_targets_indexes` is defeated**, because a negative charset
    rule reads the text up to the NUL and never sees the rest.
    **`ck_opds_servers_base_url` is not**, because a positive prefix can only
    fail under truncation; its defect was that nothing bounded the text after
    the prefix, and the ceiling is the fix that the NUL clause makes readable.
    **`ck_catalogue_credentials_envelope` is not defeated and is untouched.**
    Both its patterns end in `*`, which absorbs any suffix, so the clause matches
    the whole value whenever it matches the prefix before a NUL and truncation
    can only make it fail. Its other conjunct is a floor rather than a ceiling,
    and a NUL makes `length()` read shorter, so that is harder to satisfy rather
    than easier. `TestEveryGlobRuleIsToldAboutTheNul` derives that answer from
    the pattern, so the next `GLOB` constraint is not decided by whoever writes
    it.

    **Against the migrated schema, and the model's declaration is held to it** by
    `test_the_model_is_the_rule_a_migrated_database_carries` rather than probed
    separately. The migration is the schema everywhere, this suite included:
    `main.py` calls `init_db()` at import and `conftest` imports `main` first, so
    the `create_all` after it builds nothing and a `CheckConstraint` in
    `models.py` is installed by no run at all.
    """

    PREVIOUS = "c7b0a3e5d281"

    #: The revision these cases are about.
    #:
    #: **Named rather than reached with `upgrade_to_head`**, which is what the
    #: `after` comparisons here used to do and what went red the day a later
    #: revision rewrote one of these two constraints: `b8f4c1a7e309` gave
    #: `ck_catalogue_targets_indexes` a byte bound, so head stopped being this
    #: revision's `after` and the class was asserting that no revision had
    #: followed it. What each revision installed is its own question; the
    #: model's current text is held against head below.
    REVISION = "a6d3f92c7b14"

    @staticmethod
    def _migrated() -> None:
        """This revision's schema, which is no longer head.

        The behavioural cases below store values this revision's rules admit, so
        they run where those rules are the last word. A later revision narrowing
        one is that revision's case to move, which is what `b8f4c1a7e309` did to
        the envelope case at the foot of this class.
        """
        drop_everything()
        schema.upgrade_to(TestTheGlobRulesThatLearnedAboutNul.REVISION)

    @staticmethod
    def _at_previous() -> None:
        drop_everything()
        schema.upgrade_to(TestTheGlobRulesThatLearnedAboutNul.PREVIOUS)

    @staticmethod
    def _server(url: str, key: str = "opds-0123456789abcdef") -> tuple[str, dict[str, str]]:
        return (
            "INSERT INTO opds_servers (name, base_url, credential_key) "
            "VALUES ('a server', :url, :key)",
            {"url": url, "key": key},
        )

    @pytest.mark.parametrize(
        "rule",
        a_nul_clause_on_two_glob_rules._GLOB_RULES,
        ids=lambda rule: rule.constraint,
    )
    def test_the_revisions_text_is_the_schema_it_installs(
        self, rule: SwappedRule
    ) -> None:
        """`after` against the DDL a database **at this revision** carries.

        **Against a database rather than against `models.py`**, which is what
        this compared until a later revision rewrote one of these two
        constraints. The model is the newest revision's text by definition, so a
        comparison with it was really an assertion that this revision is still
        the last word, which is a fact about the chain rather than about these
        rules. `TestTheBoundsThisRevisionPutOnBytes` holds the model against
        head, and `test_dialect.py` holds the same chain on the other engine.

        The `before` half is not compared here: it describes the schema this
        revision found, and `test_the_downgrade_puts_each_rule_back` is what
        holds it, against a database built by other revisions entirely.
        """
        self._migrated()

        installed = TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check(
            rule.constraint
        )

        assert installed == " ".join(rule.after.split())

    _declared = staticmethod(_declared_constraint)

    @pytest.mark.parametrize(
        "rule",
        a_nul_clause_on_two_glob_rules._GLOB_RULES,
        ids=lambda rule: rule.constraint,
    )
    def test_the_model_is_the_rule_a_migrated_database_carries(
        self, rule: SwappedRule
    ) -> None:
        """The model's copy against the DDL, as an equality rather than a
        containment.

        **The model's declaration is installed by nothing**, so without this it is
        a comment: see this class's docstring for why `create_all` never runs.
        `_installed_check` is reused rather than copied because it is the only
        reading of `sqlite_master` here that is an equality: a containment passes
        a constraint appending to the model's, and it passed a dropped floor once
        already. See its own docstring.

        **At head rather than at this revision**, which is the opposite of the
        case above and is why the two are separate: the model is whatever the
        newest revision installed, so a revision that rewrites one of these
        constraints keeps this green and moves that one.
        """
        drop_everything()
        schema.upgrade_to_head()

        installed = TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check(
            rule.constraint
        )

        assert installed == self._declared(rule.table, rule.constraint)

    @pytest.mark.parametrize(
        "rule",
        a_nul_clause_on_two_glob_rules._GLOB_RULES,
        ids=lambda rule: rule.constraint,
    )
    def test_the_downgrade_puts_each_rule_back(
        self, rule: SwappedRule
    ) -> None:
        """`downgrade()` run rather than read, with `before` checked against a
        schema this revision did not write.

        **The order of the assertions is the test.** Running the downgrade and
        comparing the result with `before` is a tautology, since `downgrade()`
        installs `before`. What breaks the circle is asking the **previous**
        schema whether `before` is what this revision found. The shape is
        `TestEveryTextCeilingIsInstalledWithItsByteArm::test_the_downgrade_puts
        _each_ceiling_back`, which records why it is written this way.

        Per rule rather than in total, so a revision that put one back and lost
        the other fails here.
        """
        from alembic import command

        self._at_previous()
        installed = TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check

        assert installed(rule.constraint) == " ".join(rule.before.split())

        schema.upgrade_to(self.REVISION)
        assert installed(rule.constraint) == " ".join(rule.after.split())

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        assert installed(rule.constraint) == " ".join(rule.before.split())

    #: A NUL's position in the smuggled value, and the bytes that value holds.
    #:
    #: **Two positions, because `instr` is one based and `= 0` is what says
    #: "absent".** With only an embedded NUL in the population, `= 0` and
    #: `<= 1` are the same rule, and the second admits a value whose **first**
    #: byte is the NUL. A critic found that by mutation rather than by reading:
    #: the weakened constraint passed all sixteen cases here.
    SMUGGLED: Final = (
        ("embedded", "'bath.isbn' || char(0) || ' or 1=1'", 17),
        ("leading", "char(0) || 'bath.isbn or 1=1'", 17),
    )

    @pytest.mark.parametrize("column", ["isbn_index", "title_index"])
    @pytest.mark.parametrize(("where", "value", "bytes_stored"), SMUGGLED)
    def test_the_previous_schema_stored_a_smuggled_index_and_this_one_refuses_it(
        self, column: str, where: str, value: str, bytes_stored: int
    ) -> None:
        """The diagonal, and the only case that says the NUL is what was hiding
        the rest of the value.

        A refusal at head alone would pass on a constraint that refuses the same
        text without a NUL, which this one already did: `'bath.isbn or 1=1'` is
        refused by the rule as it stood. So the previous schema is asked the same
        question first, and it stores the row.

        Both columns and both positions: one spelling is a spelling, two are the
        rule. The value is a CQL boolean because that is what `sru.py` would
        build from it the day a row is read.
        """
        smuggled = (
            # The interpolation is a column name chosen by this loop, never a request value.
            f"UPDATE catalogue_targets SET {column} = {value} "
            "WHERE source = 'oenb'"
        )

        self._at_previous()
        with engine.connect() as connection:
            connection.execute(text(smuggled))
            connection.commit()
            stored = connection.execute(
                # The interpolation is a column name chosen by this loop, never a request value.
                text(f"SELECT length(CAST({column} AS BLOB)) FROM catalogue_targets "
                     "WHERE source = 'oenb'")
            ).scalar()
        assert stored == bytes_stored

        self._migrated()
        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(smuggled))

        assert "ck_catalogue_targets_indexes" in str(refusal.value)

    def test_a_legitimate_index_and_the_empty_one_are_still_stored(self) -> None:
        """The other side, without which a constraint refusing everything passes.

        The empty string specifically: `instr('', char(0))` is 0, and a NUL
        clause written so that it was not would refuse every unused index in the
        roster.
        """
        self._migrated()

        with engine.connect() as connection:
            connection.execute(
                text(
                    "UPDATE catalogue_targets SET isbn_index = 'bath.isbn', "
                    "title_index = '' WHERE source = 'oenb'"
                )
            )
            connection.commit()

            assert connection.execute(
                text("SELECT title_index FROM catalogue_targets WHERE source = 'oenb'")
            ).scalar() == ""

    def test_the_upgrade_refuses_a_row_carrying_a_smuggled_index(self) -> None:
        """The revision's "nothing, or it refuses to run" claim, run.

        A batch rebuild is `INSERT INTO new SELECT FROM old` with the new CHECK
        applied to the copy, so a row the previous schema accepted stops the
        upgrade by name rather than being silently carried or dropped. No seeded
        row can be this one: `targets._INDEX.fullmatch` validates every value
        `main.seed_catalogue_targets` writes.
        """
        self._at_previous()
        with engine.connect() as connection:
            connection.execute(
                text(
                    "UPDATE catalogue_targets SET isbn_index = "
                    "'bath.isbn' || char(0) || ' or 1=1' WHERE source = 'oenb'"
                )
            )
            connection.commit()

        with pytest.raises(IntegrityError) as refusal:
            schema.upgrade_to_head()

        assert "ck_catalogue_targets_indexes" in str(refusal.value)

        # A failed batch rebuild leaves its scratch table behind, and
        # `drop_everything` works from `Base.metadata`, which does not carry it.
        # Without this the next case dies on "table already exists", which reads
        # like a different fault.
        with engine.connect() as connection:
            connection.execute(text("DROP TABLE IF EXISTS _alembic_tmp_catalogue_targets"))
            connection.commit()

    def test_the_previous_schema_stored_a_megabyte_behind_a_nul(self) -> None:
        """The defect that is **not** truncation, measured rather than argued.

        A positive prefix GLOB cannot be defeated by a NUL, so this address
        satisfied the rule as it stood and the rule said nothing at all about the
        rest of it. `length()` reports 8 for the value stored here, which is why
        no character ceiling would have caught it either.
        """
        self._at_previous()
        statement, parameters = self._server("http://x\x00" + "y" * 1_000_000)

        with engine.connect() as connection:
            connection.execute(text(statement), parameters)
            connection.commit()
            characters, stored = connection.execute(
                text("SELECT length(base_url), length(CAST(base_url AS BLOB)) "
                     "FROM opds_servers")
            ).one()

        assert (characters, stored) == (8, 1_000_009)

    def test_an_address_hiding_a_payload_behind_a_nul_is_refused(self) -> None:
        """The same address against the migrated schema."""
        self._migrated()
        statement, parameters = self._server("http://x\x00" + "y" * 1_000_000)

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(statement), parameters)

        assert "ck_opds_servers_base_url" in str(refusal.value)

    def test_an_address_past_the_column_width_is_refused(self) -> None:
        """256 characters, one past `models.BASE_URL_MAX`, which is the width
        `String()` declares and the length the route's own model refuses beyond.
        A `String(n)` refuses nothing in SQLite, so this bound is the CHECK or it
        is nothing."""
        self._migrated()
        statement, parameters = self._server("http://x" + "y" * 248)

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(statement), parameters)

        assert "ck_opds_servers_base_url" in str(refusal.value)

    def test_the_widest_address_the_route_can_send_is_stored(self) -> None:
        """The other side of the byte arm, without which a constraint refusing
        everything would pass every case above.

        **Spent on four byte characters**, which is the widest a value of 255
        characters can be while still being the UTF-8 every writer here produces:
        999 bytes, under the byte arm rather than on it, because seven of the 255
        go on the scheme. An address of ASCII would leave three bytes of slack
        per character for a mutation to shrink the character ceiling into.

        `test_the_shipped_rule_stores_a_value_exactly_on_the_budget` is what sits
        on the byte arm; no value this column can legitimately hold does.
        """
        self._migrated()
        widest = "http://" + "\U0001f600" * 248
        statement, parameters = self._server(widest)
        assert len(widest) == 255

        with engine.connect() as connection:
            connection.execute(text(statement), parameters)
            connection.commit()
            characters, stored = connection.execute(
                text("SELECT length(base_url), length(CAST(base_url AS BLOB)) "
                     "FROM opds_servers")
            ).one()

        assert (characters, stored) == (255, 999)

    @staticmethod
    def _behind_a_lead_byte(total: int) -> bytes:
        """An address of exactly `total` bytes that `length()` reads as 9.

        `x'C0'` starts a sequence SQLite counts as one character and then skips
        every continuation byte after it, however many there are, so the
        character ceiling and the NUL clause both pass whatever `total` is and
        the byte arm is the only thing left facing it.
        """
        return b"http://x\xc0" + b"\x80" * (total - 9)

    def test_a_character_ceiling_alone_would_store_a_megabyte(self) -> None:
        """Why the byte arm is here, measured rather than argued.

        **`length()` skips continuation bytes without limit**, so a character
        ceiling bounds no bytes at all once the text is not valid UTF-8, and four
        bytes per character is a property of UTF-8 rather than of this column.

        **The instrument is the shipped rule with its byte arm removed, built
        from the revision's own text rather than typed out**, which is what keeps
        it the shipped rule: a hand written copy stops being one the day another
        arm is added, and then this pair goes on passing while saying nothing
        about the byte arm. Measured by a critic: a fourth arm added to both
        copies left every case here green.
        """
        after = next(
            rule.after
            for rule in a_nul_clause_on_two_glob_rules._GLOB_RULES
            if rule.constraint == "ck_opds_servers_base_url"
        )
        arm = f"AND length(CAST(base_url AS BLOB)) <= {4 * models.BASE_URL_MAX}"
        assert after.count(arm) == 1, "the byte arm is not the text this removes"
        without_the_arm = after.replace(" " + arm, "")
        # Both directions, so the name of this case is true by construction: the
        # byte arm is gone, and the character ceiling it is about is still here.
        # Without the second, dropping that ceiling from both copies leaves this
        # green under a name and a docstring about a rule nothing carries.
        assert "AS BLOB" not in without_the_arm
        assert f"length(base_url) <= {models.BASE_URL_MAX}" in without_the_arm

        probe = create_engine("sqlite://")
        with probe.connect() as connection:
            connection.execute(
                # The interpolation is a constraint text read off the live schema, never a request value.
                text(f"CREATE TABLE probe (base_url TEXT CHECK ({without_the_arm}))")
            )
            connection.execute(
                text("INSERT INTO probe VALUES (CAST(:raw AS TEXT))"),
                {"raw": self._behind_a_lead_byte(1_000_009)},
            )

            assert connection.execute(
                text("SELECT length(base_url), length(CAST(base_url AS BLOB)) "
                     "FROM probe")
            ).one() == (9, 1_000_009)

    def test_the_shipped_rule_refuses_one_byte_past_the_budget(self) -> None:
        """The boundary, so the budget is pinned rather than merely exceeded.

        **Sized off `BASE_URL_MAX` rather than written down.** A megabyte here
        would leave the number free: a critic widened the budget ninety eight
        fold in both copies and nothing went red, because anything between 1,021
        and 1,000,008 bytes was untested. This is the first value the arm
        refuses, and `test_the_widest_address_the_route_can_send_is_stored` is
        the other side.
        """
        self._migrated()
        statement, parameters = self._server("placeholder")

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(
                text(statement.replace(":url", "CAST(:url AS TEXT)")),
                {
                    **parameters,
                    "url": self._behind_a_lead_byte(4 * models.BASE_URL_MAX + 1),
                },
            )

        assert "ck_opds_servers_base_url" in str(refusal.value)

    def test_the_shipped_rule_stores_a_value_exactly_on_the_budget(self) -> None:
        """The other half of that boundary, which is what makes it one.

        Exactly `4 * BASE_URL_MAX` bytes and nine characters, so the byte arm is
        the only clause it is near, and it is **stored**. Without this the arm
        could be tightened to any number at all and only the case above would
        have to move.
        """
        self._migrated()
        statement, parameters = self._server("placeholder")

        with engine.connect() as connection:
            connection.execute(
                text(statement.replace(":url", "CAST(:url AS TEXT)")),
                {**parameters, "url": self._behind_a_lead_byte(4 * models.BASE_URL_MAX)},
            )
            connection.commit()

            assert connection.execute(
                text("SELECT length(base_url), length(CAST(base_url AS BLOB)) "
                     "FROM opds_servers")
            ).one() == (9, 4 * models.BASE_URL_MAX)

    def test_the_other_rules_on_these_tables_survived_the_rebuild(self) -> None:
        """The half a batch rebuild loses if reflection missed it.

        Both tables carry rules this revision does not name, and they are only
        still there because SQLAlchemy read them back out of the DDL: the three
        siblings on `catalogue_targets`, and on `opds_servers` the credential
        key's own constraint and the UNIQUE that stops two servers sharing a
        login.

        **The `opds_servers` pair is what this case is for.** Nothing else probes
        either against a migrated database, where
        `TestTheSeededCatalogueTargetsMatchTheCode::test_a_restore_cannot_write
        _a_row_the_dataclass_would_refuse` already covers the `catalogue_targets`
        side and fails alongside this one. Measured by a critic: deleting the
        transport CHECK from its revision reddens both.
        """
        self._migrated()
        statement, parameters = self._server("https://books.example/opds")

        with engine.connect() as connection:
            connection.execute(text(statement), parameters)
            connection.commit()

        with engine.connect() as connection, pytest.raises(IntegrityError) as reused:
            connection.execute(text(statement), parameters)
        assert "UNIQUE constraint failed" in str(reused.value)

        with engine.connect() as connection, pytest.raises(IntegrityError) as borrowed:
            connection.execute(
                text(
                    "INSERT INTO opds_servers (name, base_url, credential_key) "
                    "VALUES ('x', 'https://books.example/opds', 'bne')"
                )
            )
        assert "ck_opds_servers_credential_key" in str(borrowed.value)

        with engine.connect() as connection, pytest.raises(IntegrityError) as transport:
            connection.execute(
                text(
                    "UPDATE catalogue_targets SET transport = 'z3950' "
                    "WHERE source = 'oenb'"
                )
            )
        assert "ck_catalogue_targets_transport" in str(transport.value)

    def test_the_envelope_rule_is_deliberately_untouched(self) -> None:
        """The third GLOB rule, and the one this revision leaves alone.

        **A NUL clause on it would bound nothing**, because at this revision
        `envelope` is `Text` with no ceiling: the value below goes to disk whole
        while the constraint reads 47 characters of it, and refusing the NUL is a
        separate call about what may be in that column at all.

        **That exclusion was the right call and was not the end of it.**
        `b8f4c1a7e309` answered the separate call with a byte ceiling derived
        from what the two routes can seal, and
        `TestTheBoundsThisRevisionPutOnBytes` is where this value is refused. So
        this case runs at its own revision rather than at head, which is what
        `_migrated` is for, and it is still the thing that would have to be
        deleted to claim a NUL clause was ever the instrument here.

        **The byte figure is derived from the value rather than written down**,
        which is not a tautology: it says SQLite stored every byte of a value it
        measured as 47 characters. A literal here was wrong on its first
        writing, at twice the true figure, because the shape it was measured
        against held 100,000 characters and this one holds 50,000.
        """
        self._migrated()
        envelope = "v2." + "a" * 40 + ".b.c\x00" + "x" * 50_000

        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO catalogue_credentials (source, envelope) "
                    "VALUES ('bne', :envelope)"
                ),
                {"envelope": envelope},
            )
            connection.commit()
            characters, stored = connection.execute(
                text("SELECT length(envelope), length(CAST(envelope AS BLOB)) "
                     "FROM catalogue_credentials")
            ).one()

        assert (characters, stored) == (47, len(envelope.encode()))
        assert stored == 50_048


#: The AES-GCM authentication tag, in bytes.
#:
#: A property of the algorithm rather than of this application, which is why it
#: is the one number here that is written down: `cryptography`'s `AESGCM.encrypt`
#: appends a 128 bit tag and exposes no constant for it.
_GCM_TAG_BYTES: Final = 16


def _payloads_that_reach_credential_put() -> list[type[BaseModel]]:
    """Every request body a route hands to `credentials.put`, found rather than
    listed.

    **Derived, because a list here would be the one thing the ceiling below
    cannot afford to be wrong about.** A third route sealing a pair would not be
    in a tuple, the derived ceiling would stay where it is, and the symptom is a
    500 on somebody's deployment: exactly the failure this whole derivation
    exists to prevent. So the routers are read for the call and the call's
    enclosing handler is read for its annotated body, the shape
    `test_shelf.py`'s four passes use.

    **Two refusals rather than a filter.** A handler reaching `credentials.put`
    through a helper of its own is invisible to this and is reported by
    `test_the_walk_finds_a_call_in_every_router_that_makes_one`, which counts the
    call sites off the text; and a body this cannot resolve to a Pydantic model
    with both halves of a login is reported rather than skipped, the third answer
    every reader in this tree keeps.
    """
    import ast
    import importlib
    from pathlib import Path

    found: list[type[BaseModel]] = []
    routers = Path(__file__).resolve().parent.parent / "routers"
    for path in sorted(routers.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = importlib.import_module(f"routers.{path.stem}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "put"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "credentials"
                for call in ast.walk(node)
            ):
                continue
            for argument in (*node.args.args, *node.args.kwonlyargs):
                annotation = argument.annotation
                if not isinstance(annotation, ast.Name):
                    continue
                declared = getattr(module, annotation.id, None)
                if (
                    isinstance(declared, type)
                    and issubclass(declared, BaseModel)
                    and {"username", "password"} <= set(declared.model_fields)
                ):
                    found.append(declared)
    return found


def _credential_api_bounds() -> list[tuple[int, int]]:
    """Each of those bodies as its `(username, password)` character bounds.

    **Read off `model_fields` rather than off the source text**, the rule
    `_opds_api_bounds` states, so a bound reintroduced as a literal in any
    spelling is still the number this compares. **The smallest where a field
    carries several**, because that is the one a request meets.
    """
    bounds: list[tuple[int, int]] = []
    for schema_model in _payloads_that_reach_credential_put():
        pair: dict[str, int] = {}
        for field, info in schema_model.model_fields.items():
            for meta in info.metadata:
                ceiling = getattr(meta, "max_length", None)
                if ceiling is not None:
                    pair[field] = min(pair.get(field, ceiling), ceiling)
        bounds.append((pair["username"], pair["password"]))
    return bounds


def _widest_envelope_this_application_writes() -> int:
    """The widest `credentials.seal` can return, in bytes, recomputed.

    **Every term read off the code that produces it**, so this is a derivation
    rather than a second copy of the number: the two routes' own bounds, the
    version string, the generation tag's width in hex, the nonce's width after
    base64url, and the ciphertext's. Only the GCM tag is a literal, and it is the
    one term that belongs to the cipher rather than to this application.

    **Four bytes per character is UTF-8's widest**, and the pair is sealed as
    `username:password` encoded, so the plaintext is bounded by the characters
    the routes accept rather than by their count.
    """
    plaintext = max(
        4 * username + len(":") + 4 * password
        for username, password in _credential_api_bounds()
    )
    ciphertext = plaintext + _GCM_TAG_BYTES
    separators = 3
    return (
        len(credentials.VERSION)
        + 2 * credentials._GENERATION_BYTES
        + len(credentials._b64(bytes(credentials._NONCE_BYTES)))
        + len(credentials._b64(bytes(ciphertext)))
        + separators
    )


@pytest.mark.usefixtures("restore_schema")
class TestTheBoundsThisRevisionPutOnBytes:
    """`b8f4c1a7e309`, and the four holes it closes, which are four holes.

    Three columns had no bound on what reaches the disk and one address column
    had no rule at all. **The cases here are per constraint rather than
    parametrised over the four**, because what each arm is the last line for
    differs: on `book_identifiers` and `catalogue_credentials` the byte arm is
    the only clause a lead byte cannot walk past; on `catalogue_targets`' two
    index columns the charset rule refuses a lead byte already and the new arm
    is a bound on **size**, which nothing stated; and on
    `catalogue_targets.base_url` every arm is new.

    **Saying that plainly is the point.** A probe pushing a lead byte at the
    index columns would be refused by the charset rule and would read as
    evidence about an arm it never reached, which is the shape
    `TestTheGlobRulesThatLearnedAboutNul` was written to avoid: a refusal at head
    alone says nothing about which clause did the refusing.

    **Against the migrated schema**, which is the copy that refuses a row:
    `main.py` calls `init_db()` at import and `conftest` imports it first, so
    `create_all` builds nothing and a `CheckConstraint` in `models.py` is
    installed by no run at all.
    """

    PREVIOUS: Final = "a6d3f92c7b14"

    @staticmethod
    def _migrated() -> None:
        drop_everything()
        schema.upgrade_to_head()

    @staticmethod
    def _at_previous() -> None:
        drop_everything()
        schema.upgrade_to(TestTheBoundsThisRevisionPutOnBytes.PREVIOUS)

    @staticmethod
    def _behind_a_lead_byte(prefix: bytes, total: int) -> bytes:
        """`prefix`, then a value of exactly `total` bytes that `length()` reads
        as `prefix` plus one.

        `x'C0'` starts a sequence SQLite counts as one character and then skips
        every continuation byte after it, however many there are, so every
        character arm in the constraint passes whatever `total` is and the byte
        arm is the only thing left facing it.
        """
        return prefix + b"\xc0" + b"\x80" * (total - len(prefix) - 1)

    @staticmethod
    def _drop_the_scratch_tables() -> None:
        """What a failed upgrade leaves behind, removed.

        **The scratch table a failed rebuild leaves is not the one that
        failed.** Measured 2026-09-20: a row that stops this revision's **last**
        operation leaves `_alembic_tmp_book_identifiers`, from its **first**. A
        first version of this dropped the failing table's alone and nine cases
        later in this module died on "table already exists", which reads like a
        different fault: `drop_everything` works from `Base.metadata` and no
        scratch table is in a model. An operator retrying the upgrade meets the
        same thing, which is why the revision says to drop it.

        **Derived from the revision rather than named**, because which one is
        left is an artefact of where the transaction ends rather than a rule:
        naming a table here would be a guess that was already wrong once.

        **In a `finally`**, because a failed assertion would otherwise leak the
        table and poison every later case in the module, which is the confusion
        this exists to prevent rather than to cause.
        """
        rebuilt = {rule.table for rule in bound_the_bytes._SWAPPED} | {
            added.table for added in bound_the_bytes._ADDED
        }
        with engine.connect() as connection:
            for table_name in sorted(rebuilt):
                connection.execute(
                    text(f"DROP TABLE IF EXISTS _alembic_tmp_{table_name}")
                )
            connection.commit()

    @staticmethod
    def _raw(statement: str, value: bytes, **other: object) -> None:
        """One insert or update whose bound value is raw bytes rather than text.

        The probes below are not Python strings: they are not valid UTF-8, which
        is the whole of the point, so they go in as `CAST(x'...' AS TEXT)`.
        """
        with engine.connect() as connection:
            connection.execute(
                text(statement.replace(":raw", f"CAST(x'{value.hex()}' AS TEXT)")),
                other,
            )
            connection.commit()

    # ── the two copies of each rule ────────────────────────────────────────

    @pytest.mark.parametrize(
        "rule", bound_the_bytes._SWAPPED, ids=lambda rule: rule.constraint
    )
    def test_the_revisions_text_is_the_models_text(self, rule: SwappedRule) -> None:
        """The revision writes its SQL out rather than importing from `models`,
        so the two copies are a fact stored twice and this is what stands
        between them.

        The `before` half is not compared: it describes the schema the revision
        found, which by definition is no longer the one `models.py` declares.
        `test_the_downgrade_puts_each_rule_back` is what holds that half.
        """
        assert " ".join(rule.after.split()) == self._declared(
            rule.table, rule.constraint
        )

    @pytest.mark.parametrize(
        "added", bound_the_bytes._ADDED, ids=lambda added: added.constraint
    )
    def test_the_added_rules_text_is_the_models_text(self, added: AddedRule) -> None:
        """The same comparison for the rule this revision adds rather than
        swaps. It has no `before` at all, which is why it is a second list."""
        assert " ".join(added.sqlite.split()) == self._declared(
            added.table, added.constraint
        )

    _declared = staticmethod(_declared_constraint)

    @pytest.mark.parametrize(
        ("table_name", "constraint"),
        [(rule.table, rule.constraint) for rule in bound_the_bytes._SWAPPED]
        + [(added.table, added.constraint) for added in bound_the_bytes._ADDED],
        ids=lambda value: value,
    )
    def test_the_model_is_the_rule_a_migrated_database_carries(
        self, table_name: str, constraint: str
    ) -> None:
        """The model's copy against the DDL, as an equality rather than a
        containment.

        `_installed_check` is reused rather than copied because it reads the
        constraint's own parentheses: a containment passes an installed rule
        that appends to the model's, and it passed a dropped floor once already.
        """
        self._migrated()

        installed = TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check(
            constraint
        )

        assert installed == self._declared(table_name, constraint)

    @pytest.mark.parametrize(
        "rule", bound_the_bytes._SWAPPED, ids=lambda rule: rule.constraint
    )
    def test_the_downgrade_puts_each_rule_back(self, rule: SwappedRule) -> None:
        """`downgrade()` run rather than read, with `before` checked against a
        schema this revision did not write.

        **The order of the assertions is the test.** Running the downgrade and
        comparing the result with `before` is a tautology, since `downgrade()`
        installs `before`. What breaks the circle is asking the **previous**
        schema whether `before` is what this revision found.
        """
        from alembic import command

        self._at_previous()
        installed = TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check

        assert installed(rule.constraint) == " ".join(rule.before.split())

        schema.upgrade_to_head()
        assert installed(rule.constraint) == " ".join(rule.after.split())

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        assert installed(rule.constraint) == " ".join(rule.before.split())

    @pytest.mark.parametrize(
        "added", bound_the_bytes._ADDED, ids=lambda added: added.constraint
    )
    def test_the_downgrade_takes_the_added_rule_away(self, added: AddedRule) -> None:
        """The other direction of an addition, which is a removal rather than a
        narrower rule. A downgrade leaving it behind would hand a rolled back
        deployment a constraint from a release it no longer runs."""
        from alembic import command

        self._at_previous()
        constraint = added.constraint
        assert f"CONSTRAINT {constraint} CHECK (" not in (
            TestEveryTextCeilingIsInstalledWithItsByteArm._installed()
        )

        schema.upgrade_to_head()
        assert TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check(constraint)

        command.downgrade(schema._alembic_config(), self.PREVIOUS)

        assert f"CONSTRAINT {constraint} CHECK (" not in (
            TestEveryTextCeilingIsInstalledWithItsByteArm._installed()
        )

    # ── book_identifiers.value: the budget that makes the ceiling exact ────

    @staticmethod
    def _a_book() -> int:
        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO books (title, ownership) VALUES ('A book', 'owned')")
            )
            connection.commit()
            book_id = connection.execute(text("SELECT id FROM books")).scalar()
        assert isinstance(book_id, int)
        return book_id

    def test_an_identifier_behind_a_lead_byte_is_refused_at_the_budget(self) -> None:
        """The class the character ceiling and the NUL clause both admit.

        One `x'C0'` and its continuation bytes are one counted character and as
        many bytes as somebody writes, and there is no NUL for `instr` to find,
        so this value satisfies every clause on the column except the one this
        revision added. **Sized at one byte past the budget rather than at some
        large number**, so a mutation shrinking the multiplier is still refused
        here and has to be caught by the acceptance case instead.
        """
        self._migrated()
        book = self._a_book()
        budget = 4 * models.BOOK_IDENTIFIER_MAX

        with pytest.raises(IntegrityError) as refusal:
            self._raw(
                "INSERT INTO book_identifiers (book_id, scheme, value) "
                "VALUES (:book, 'asin', :raw)",
                self._behind_a_lead_byte(b"", budget + 1),
                book=book,
            )

        assert "ck_book_identifiers_bounds" in str(refusal.value)

    # **The acceptance side of this budget is not here**, and copying it would
    # be the same fact in a second home:
    # `TestTheIdentifierBoundsSurvivedIntoTheMigration::test_a_nul_free_value_on
    # _the_boundary_is_taken` already stores sixty four byte characters at head,
    # which is 240 bytes and exactly the budget, so tightening the arm by one
    # byte reddens there.

    # ── catalogue_targets: two index columns and an address ────────────────

    @pytest.mark.parametrize("column", ["isbn_index", "title_index"])
    def test_an_index_name_past_the_bound_is_refused(self, column: str) -> None:
        """**ASCII rather than a lead byte, and the reason is this class's
        docstring.** The charset rule refuses anything outside `[A-Za-z0-9._]`
        already, so a wide value would be refused by a clause that was always
        there and would say nothing about this one. What was missing on these two
        columns was any bound on size at all, and this is the first value the new
        one refuses.
        """
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(
                text(
                    f"UPDATE catalogue_targets SET {column} = :value "
                    "WHERE source = 'oenb'"
                ),
                {"value": "a" * (models.TARGET_INDEX_MAX + 1)},
            )

        assert "ck_catalogue_targets_indexes" in str(refusal.value)

    @pytest.mark.parametrize("column", ["isbn_index", "title_index"])
    def test_an_index_name_exactly_on_the_bound_is_stored(self, column: str) -> None:
        """The other side, and the measurement that says the two units are one
        number on this column: the charset rule admits only characters SQLite
        stores in one byte, so a value at the bound in characters is at the bound
        in bytes."""
        self._migrated()
        widest = "a" * models.TARGET_INDEX_MAX

        with engine.connect() as connection:
            connection.execute(
                text(
                    f"UPDATE catalogue_targets SET {column} = :value "
                    "WHERE source = 'oenb'"
                ),
                {"value": widest},
            )
            connection.commit()
            counted, stored = connection.execute(
                text(
                    f"SELECT length({column}), length(CAST({column} AS BLOB)) "
                    "FROM catalogue_targets WHERE source = 'oenb'"
                )
            ).one()

        assert (counted, stored) == (models.TARGET_INDEX_MAX, models.TARGET_INDEX_MAX)

    @pytest.mark.parametrize(
        ("value", "why"),
        [
            ("file:///etc/passwd", "a scheme no sync may fetch"),
            ("gopher://example.invalid/0", "a scheme no sync may fetch"),
            ("https://", "a prefix with nothing after it"),
            ("x" * 300, "no scheme at all"),
            # **The only case that reaches the character ceiling.** The row
            # above fails the scheme rule first, so without this one deleting
            # `length(base_url) <= 255` from both copies left the whole suite
            # green: measured before this row existed. 258 characters, 258
            # bytes, a scheme the rule admits and no NUL, so the ceiling is the
            # only clause facing it.
            ("https://" + "x" * 250, "past the character ceiling, scheme and all"),
        ],
    )
    def test_an_address_this_column_never_had_a_rule_for_is_refused(
        self, value: str, why: str
    ) -> None:
        """The address rule, which this table carried none of.

        The sibling column has refused these since `b7d4e6f01a95`; this one
        accepted every row an archive named. Each case is a different clause, so
        deleting any one of the four reddens a named row rather than a count.
        """
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(
                text("UPDATE catalogue_targets SET base_url = :value WHERE source = 'oenb'"),
                {"value": value},
            )

        assert "ck_catalogue_targets_base_url" in str(refusal.value), why

    def test_an_address_hiding_a_payload_behind_a_nul_is_refused(self) -> None:
        """`instr` is what makes the character ceiling readable here, exactly as
        on the sibling column: without it `length()` stops at the NUL and the
        ceiling is a rule about the prefix."""
        self._migrated()

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(
                text("UPDATE catalogue_targets SET base_url = :value WHERE source = 'oenb'"),
                {"value": "http://x\x00" + "y" * 5_000},
            )

        assert "ck_catalogue_targets_base_url" in str(refusal.value)

    def test_an_address_behind_a_lead_byte_is_refused_at_the_budget(self) -> None:
        """The value neither the prefix nor the character ceiling can see.

        `length()` reads 9 whatever follows the lead byte and there is no NUL for
        `instr` to find, so the byte arm is the only clause facing it. Sized off
        `TARGET_BASE_URL_MAX` rather than written down: anything between the
        budget and a megabyte would otherwise be untested, which is the hole a
        critic drove a ninety eight fold widening through on the sibling column.
        """
        self._migrated()
        budget = 4 * models.TARGET_BASE_URL_MAX

        with pytest.raises(IntegrityError) as refusal:
            self._raw(
                "UPDATE catalogue_targets SET base_url = :raw WHERE source = 'oenb'",
                self._behind_a_lead_byte(b"http://x", budget + 1),
            )

        assert "ck_catalogue_targets_base_url" in str(refusal.value)

    def test_an_address_exactly_on_the_byte_budget_is_stored(self) -> None:
        """The other half of that boundary, which is what makes it one. Without
        it the arm could be tightened to any number at all and only the case
        above would have to move."""
        self._migrated()
        budget = 4 * models.TARGET_BASE_URL_MAX

        self._raw(
            "UPDATE catalogue_targets SET base_url = :raw WHERE source = 'oenb'",
            self._behind_a_lead_byte(b"http://x", budget),
        )

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT length(base_url), length(CAST(base_url AS BLOB)) "
                     "FROM catalogue_targets WHERE source = 'oenb'")
            ).one() == (9, budget)

    def test_the_widest_address_the_roster_can_hold_is_stored(self) -> None:
        """The acceptance side in characters, which the lead byte cases are not.

        255 characters of four bytes behind the scheme is the widest **valid**
        address the ceiling admits, and it is 999 bytes rather than 1,020: seven
        of its characters go on `http://` and are one byte each. So this holds
        the character ceiling from below and the case above holds the byte
        budget, and neither number can be moved without one of them going red.
        This is the pair `ck_opds_servers_base_url` carries on the sibling
        column.

        **That the eleven seeded rows pass is not asserted here.**
        `TestTheSeededCatalogueTargetsMatchTheCode::test_every_seeded_row_says
        _what_the_constant_says` compares every field of all eleven against a
        migrated head, so a seeded address this rule refused would fail the boot
        that writes it.
        """
        self._migrated()
        widest = "http://" + "\U0001f600" * 248
        assert len(widest) == models.TARGET_BASE_URL_MAX

        with engine.connect() as connection:
            connection.execute(
                text("UPDATE catalogue_targets SET base_url = :value "
                     "WHERE source = 'oenb'"),
                {"value": widest},
            )
            connection.commit()

            assert connection.execute(
                text("SELECT length(base_url), length(CAST(base_url AS BLOB)) "
                     "FROM catalogue_targets WHERE source = 'oenb'")
            ).one() == (models.TARGET_BASE_URL_MAX, 999)

    # ── catalogue_credentials.envelope: the ceiling, derived ───────────────

    def test_the_ceiling_is_what_the_two_routes_can_produce(self) -> None:
        """The constant against a derivation of it, so widening a route's bound
        fails here rather than at a 500 on somebody's deployment.

        **This is the rule that keeps the number honest.** `models.py` cannot
        import `schemas/settings.py`, so the ceiling is a literal there with its
        arithmetic in a comment, and a comment does not fail. Every term of the
        derivation is read off the code that produces it: see
        `_widest_envelope_this_application_writes`.
        """
        assert _widest_envelope_this_application_writes() == (
            models.CATALOGUE_ENVELOPE_MAX_BYTES
        )

    def test_the_derivation_is_what_seal_actually_returns(self) -> None:
        """The arithmetic against the function, rather than against itself.

        **Without this the helper and the constant agree and both can be
        wrong**: the helper rebuilds `seal`'s layout by hand, so a field added to
        an envelope would move the real width and neither number. This calls
        `credentials.seal` with the widest pair the routes admit and the key
        material directly, which needs no key source and no fixture.

        The four part shape is asserted beside the total, because a total alone
        passes on two errors that cancel.

        **`key=len`, because a bare `max` over strings is lexicographic**, which
        is not the criterion the helper uses and is not the criterion this is
        about. It picks the right pair today by accident, measured, and the two
        part company the moment a route's pair changes shape.
        """
        widest = max(
            (
                "\U0001f600" * username + ":" + "\U0001f600" * password
                for username, password in _credential_api_bounds()
            ),
            key=len,
        )

        envelope = credentials.seal(
            b"\x01" * 32, "dnb", "https://services.dnb.de/sru/dnb", widest
        )

        assert len(envelope.encode()) == models.CATALOGUE_ENVELOPE_MAX_BYTES
        assert [len(part) for part in envelope.split(".")] == [
            len(credentials.VERSION),
            2 * credentials._GENERATION_BYTES,
            len(credentials._b64(bytes(credentials._NONCE_BYTES))),
            models.CATALOGUE_ENVELOPE_MAX_BYTES
            - len(credentials.VERSION)
            - 2 * credentials._GENERATION_BYTES
            - len(credentials._b64(bytes(credentials._NONCE_BYTES)))
            - len("..."),
        ]

    def test_the_walk_finds_a_call_in_every_router_that_makes_one(self) -> None:
        """The premise `_payloads_that_reach_credential_put` rests on.

        It reads a handler's own annotated body, so a route that sealed a pair
        through a helper of its own would be invisible to it and the ceiling
        would go on being derived from one route fewer. This counts the call
        sites off the text and asks for a payload from each.

        **Counted rather than named**, because a list of route names is the
        enumeration this repository keeps replacing; what has to hold is that
        every call the routers make was reached.
        """
        import ast
        from pathlib import Path

        routers = Path(__file__).resolve().parent.parent / "routers"
        call_sites = sum(
            1
            for path in routers.glob("*.py")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "put"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "credentials"
        )

        assert call_sites, "no router calls `credentials.put`, so this walk is vacuous"
        assert len(_payloads_that_reach_credential_put()) == call_sites

    def test_no_router_reaches_the_module_by_a_name_this_walk_cannot_see(
        self,
    ) -> None:
        """The hole the count above cannot cover, closed as a rule.

        **Both halves key on the spelling `credentials.put`**, so an import that
        renames it hides a route from the resolver **and** from the counter at
        once and the count passes `0 == 0`. Measured by a critic against mutated
        copies of a router: `Annotated[...]` and a helper are both caught, and
        `from credentials import put` and `import credentials as creds` are both
        silent. The ceiling comparison is only a partial backstop, catching a
        hidden route when it is the **widest** one and not when it is narrower.

        **A rule rather than another pattern**, which is this repository's own
        answer to a guard that needs one more spelling: a router may reach this
        module as `import credentials` and no other way. `routers/opds.py`
        already imports `Credential` and `origin_of` by name, so what is refused
        is `put` among them, and any aliasing of the module itself.
        """
        import ast
        from pathlib import Path

        routers = Path(__file__).resolve().parent.parent / "routers"
        offenders: list[str] = []
        for path in sorted(routers.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module == "credentials":
                    offenders += [
                        f"{path.name}: `from credentials import {alias.name}`"
                        for alias in node.names
                        if alias.name == "put"
                    ]
                if isinstance(node, ast.Import):
                    offenders += [
                        f"{path.name}: `import credentials as {alias.asname}`"
                        for alias in node.names
                        if alias.name == "credentials" and alias.asname
                    ]

        assert not offenders, (
            "the ceiling on `catalogue_credentials.envelope` is derived from the "
            "routes that call `credentials.put`, and this walk finds them by that "
            "spelling. A router reaching the module by another name is a route "
            f"the ceiling is not derived from: {offenders}"
        )

    def test_nothing_outside_the_routers_seals_a_pair(self) -> None:
        """The other premise: the walk looks in `routers/` only.

        The counter above reads the same directory, so neither can tell you the
        walk is looking in the wrong place. A `credentials.put` in `backup.py` or
        `settings_store.py` would be invisible to both, and its pair would be
        bounded by nothing at all.

        `credentials.py` itself is excluded, being where the function lives.

        **`_python_sources()` rather than a walk of this file's own**, which is
        the rule `test_house_rules.py` owns and which a first version of this
        broke: a module that recurses `backend/` and decides for itself what
        vendored means reads the pipeline's dependency cache as ours, green where
        it is written and red where it is trusted. That walk already drops the
        tests and the migrations, so this only has to drop the routers.
        """
        import ast

        elsewhere: list[str] = []
        for path in _python_sources():
            if path.parent.name == "routers" or path.name == "credentials.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "put"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "credentials"
                ):
                    elsewhere.append(str(path.relative_to(BACKEND)))

        assert elsewhere == [], (
            "these seal a credential outside the routers, where the walk that "
            f"derives the envelope ceiling does not look: {sorted(set(elsewhere))}"
        )

    def test_the_two_address_columns_answer_with_the_same_number(self) -> None:
        """`TARGET_BASE_URL_MAX`'s whole argument, which was prose until now.

        It says the two address columns in this schema must not answer the same
        question with two numbers, then writes the number a second time three
        hundred lines from the first. A docstring cannot fail; this can.
        """
        assert models.TARGET_BASE_URL_MAX == models.BASE_URL_MAX

    @pytest.mark.parametrize("column", ["isbn_index", "title_index"])
    def test_the_index_bound_is_the_declared_width(self, column: str) -> None:
        """The one mutation that can part the declared width from the bound.

        **Narrow, and named rather than dressed up.** The column is declared
        `String(TARGET_INDEX_MAX)` and the constraint is built from the same
        constant, so the two are one number by construction; what this catches is
        a literal re-introduced in the column declaration, which is how
        `base_url` was written until this change. It is not evidence that the
        constraint says 64, which is
        `test_the_revisions_text_is_the_models_text`'s job.

        **These two are bounded in bytes and not in characters**, so the house
        rule over character ceilings never sees them, and the alternative was
        measured: adding `length(col) <= 64` beside the byte arm puts the
        constraint back in that rule's class and the rule then demands a budget
        of **256**, four times the true bound, because it cannot read a
        confinement wrapped in `(col = '' OR ...)`. `docs/decisions.md` carries
        the measurement.
        """
        declared = Base.metadata.tables["catalogue_targets"].c[column].type
        assert isinstance(declared, String)

        assert declared.length == models.TARGET_INDEX_MAX

    def test_the_widest_envelope_the_routes_can_write_is_stored(self) -> None:
        """The acceptance side, at exactly the ceiling rather than under it.

        Built in the shape `credentials.seal` returns, `<version>.<generation>.
        <nonce>.<ciphertext>`, at the width that derivation gives, so a bound
        tightened by one byte refuses a credential an admin could have typed and
        this goes red.
        """
        self._migrated()
        # Everything but the ciphertext, built from the same terms the
        # derivation reads rather than from its total: a literal for the header's
        # width here would be the one number in this file nobody could re-derive.
        header = ".".join((
            credentials.VERSION,
            "a" * (2 * credentials._GENERATION_BYTES),
            credentials._b64(bytes(credentials._NONCE_BYTES)),
        ))
        ciphertext = models.CATALOGUE_ENVELOPE_MAX_BYTES - len(header) - len(".")
        widest = f"{header}.{'c' * ciphertext}"
        assert len(widest.encode()) == models.CATALOGUE_ENVELOPE_MAX_BYTES

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO catalogue_credentials (source, envelope) "
                     "VALUES ('bne', :envelope)"),
                {"envelope": widest},
            )
            connection.commit()

            assert connection.execute(
                text("SELECT length(CAST(envelope AS BLOB)) FROM catalogue_credentials")
            ).scalar() == models.CATALOGUE_ENVELOPE_MAX_BYTES

    def test_an_envelope_behind_a_lead_byte_is_refused_at_the_ceiling(self) -> None:
        """One byte past the ceiling, in the shape that satisfies every other
        clause this constraint carries.

        The prefix keeps `length()` at 48, which clears the floor of 40, and the
        two dots after it keep the shape `GLOB` matches, so the byte arm is the
        only clause left. **That matters more here than elsewhere**: the floor and
        the shape share this constraint's name, so a refusal by name would
        otherwise be evidence about whichever clause happened to fire.
        """
        self._migrated()
        prefix = b"v2." + b"a" * 40 + b".b.c"

        with pytest.raises(IntegrityError) as refusal:
            self._raw(
                "INSERT INTO catalogue_credentials (source, envelope) "
                "VALUES ('bne', :raw)",
                self._behind_a_lead_byte(
                    prefix, models.CATALOGUE_ENVELOPE_MAX_BYTES + 1
                ),
            )

        assert "ck_catalogue_credentials_envelope" in str(refusal.value)

    def test_the_value_the_previous_revision_stored_whole_is_now_refused(
        self,
    ) -> None:
        """The exact value `a6d3f92c7b14` recorded going to disk, at head.

        `TestTheGlobRulesThatLearnedAboutNul::test_the_envelope_rule_is
        _deliberately_untouched` stores it at that revision, 50,048 bytes with
        `length()` reporting 47, and names this class as where it stops. Without
        this case that sentence pointed at nothing: the boundary pair below is a
        different shape at 2,826 bytes, and a reader would have taken a promise.
        """
        self._migrated()
        envelope = "v2." + "a" * 40 + ".b.c\x00" + "x" * 50_000

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(
                text("INSERT INTO catalogue_credentials (source, envelope) "
                     "VALUES ('bne', :envelope)"),
                {"envelope": envelope},
            )

        assert "ck_catalogue_credentials_envelope" in str(refusal.value)

    def test_a_nul_carrying_envelope_under_the_ceiling_is_capped_not_refused(
        self,
    ) -> None:
        """What the ceiling does to a NUL, pinned rather than described.

        **It bounds what a NUL can hide; it does not stop the hiding.** This
        value is 2,825 bytes with `length()` reporting 47 and it is **stored**,
        so a reader who takes "the byte count answers the NUL" to mean the column
        refuses a smuggled payload is wrong, and this is what says so.

        **That is the accepted outcome rather than an oversight.** Refusing the
        byte here would be a new rule about the column's contents, and a row
        carrying one is already inert. **By the generation tag rather than by the
        base64, on this value**: `unseal` reads the tag before it decodes
        anything and this one is forty `a`, so it raises `WrongKeyGeneration`. A
        row that got past the tag would be caught one step later, `unseal`
        catching `ValueError` and `binascii.Error` being one. Either way it is an
        unreadable credential and not a 500. This is
        `TestEveryTextCeilingIsInstalledWithItsByteArm::test_a_nul_carrying
        _value_under_the_byte_budget_is_stored`'s rule on a second column.
        """
        self._migrated()
        prefix = "v2." + "a" * 40 + ".b.c\x00"
        smuggled = prefix + "x" * (models.CATALOGUE_ENVELOPE_MAX_BYTES - len(prefix))

        with engine.connect() as connection:
            connection.execute(
                text("INSERT INTO catalogue_credentials (source, envelope) "
                     "VALUES ('bne', :envelope)"),
                {"envelope": smuggled},
            )
            connection.commit()

            assert connection.execute(
                text("SELECT length(envelope), length(CAST(envelope AS BLOB)) "
                     "FROM catalogue_credentials")
            ).one() == (47, models.CATALOGUE_ENVELOPE_MAX_BYTES)

    def test_a_blob_walks_every_glob_rule_and_not_the_byte_arm(self) -> None:
        """The storage class the charset rules cannot see, and the arm that can.

        **`GLOB` with a BLOB left operand never matches**, measured on sqlite
        3.46.1 and 3.50.4, so a refusal written `NOT GLOB` is satisfied by any
        blob at all and the confinement on these index columns is a claim about
        the TEXT storage class rather than about the column. `length()` on a blob
        counts bytes, so the arm this revision added is the one clause that still
        binds, and it is what refuses this value.

        **Nothing can write one today** and that is a fact about the writer:
        `backup.restore` binds `_parse_row`'s output from a strictly parsed JSON
        manifest, so every value it inserts is a `str`. Recorded here because the
        rule that clears these ceilings reads the charset clause, and what that
        clause is worth depends on a storage class nothing else states.
        """
        self._migrated()
        blob = b" " * (models.TARGET_INDEX_MAX + 1)

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(
                text(f"UPDATE catalogue_targets SET isbn_index = x'{blob.hex()}' "
                     "WHERE source = 'oenb'")
            )

        assert "ck_catalogue_targets_indexes" in str(refusal.value)

    def test_the_same_shape_one_byte_under_the_ceiling_is_stored(self) -> None:
        """The boundary from below, and the case that says the refusal above is
        the byte arm and not the shape or the floor: the two values differ by one
        continuation byte and by nothing else."""
        self._migrated()
        prefix = b"v2." + b"a" * 40 + b".b.c"

        self._raw(
            "INSERT INTO catalogue_credentials (source, envelope) VALUES ('bne', :raw)",
            self._behind_a_lead_byte(prefix, models.CATALOGUE_ENVELOPE_MAX_BYTES),
        )

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT length(envelope), length(CAST(envelope AS BLOB)) "
                     "FROM catalogue_credentials")
            ).one() == (48, models.CATALOGUE_ENVELOPE_MAX_BYTES)

    # ── what the upgrade does to a row that is already there ───────────────

    def test_the_upgrade_refuses_a_row_the_new_rule_cannot_hold(self) -> None:
        """The revision's own account of what it does to existing rows.

        It says "nothing, or it refuses to run", which is a claim about a batch
        rebuild being `INSERT INTO new SELECT FROM old` with the new CHECK
        applied to the copy. Prose is the weakest rung, so this runs it: an
        address `a6d3f92c7b14` accepts is planted, and the upgrade fails on it by
        name.

        **The row is one no application path can write**, which is why refusing
        is right rather than a hazard: `main.seed_catalogue_targets` writes
        `targets.SEEDED`, whose eleven addresses are all `http` or `https`, and
        the only other writer is a restore of an archive somebody edited by hand.
        """
        self._at_previous()
        with engine.connect() as connection:
            connection.execute(
                text("UPDATE catalogue_targets SET base_url = 'file:///etc/passwd' "
                     "WHERE source = 'oenb'")
            )
            connection.commit()

        try:
            with pytest.raises(IntegrityError) as refusal:
                schema.upgrade_to_head()

            assert "ck_catalogue_targets_base_url" in str(refusal.value)
        finally:
            self._drop_the_scratch_tables()



def _confinement_armed_constraints() -> dict[str, str]:
    """Every CHECK in `Base.metadata` that names a NUL and carries no byte arm.

    **The complement of `_byte_armed_constraints`, derived from the same two
    tokens**, so between them the two functions cover every constraint in this
    schema that says anything about how a value is encoded, and neither can be
    the one that quietly holds none.

    A ceiling cleared by a **byte arm** is held three times: by
    `test_the_model_is_the_constraint_the_revision_installs` and
    `test_every_byte_armed_constraint_has_a_behavioural_case`, both of which key
    on `AS BLOB`, and by the expression comparison in
    `TestTheMigrationsAndTheModelsAgree`, which keys on nothing and reads every
    constraint there is.
    A ceiling cleared by the other arm the house rule accepts, a
    NUL clause beside a charset rule confining the value to one byte per
    character, carries no `AS BLOB` and got neither: `ck_catalogue_credentials
    _source` and `ck_opds_servers_credential_key`, the two columns holding a
    sealed credential's key, rested on text alone.
    """
    return {
        name: declared
        for name, (_, declared) in _declared_checks().items()
        if _A_NUL_CLAUSE.search(declared) and not _A_BYTE_ARM.search(declared)
    }


#: One row per confinement armed constraint: the table, the column the arm is
#: about, what a row needs beside it, what the probe value must start with, and
#: the prefix a legitimate value at the ceiling is padded out from.
#:
#: **Fixtures rather than a register.** Which constraints are in the class is
#: derived above; what an insert into that table needs is not derivable, so it is
#: written out and the equality in
#: `test_every_confinement_armed_constraint_has_a_behavioural_case` is what stops
#: a new one inheriting a rule that cannot see it.
#:
#: **The widest value is built rather than written**, the rule `_TEXT_CEILINGS`
#: states at its own site: a probe carrying the number the constraint states
#: would agree with a constraint that had drifted. The pad is read off the
#: column's `String(n)`, so widening either column moves the boundary case with
#: it rather than leaving it short.
#:
#: **The prefix is what makes the refusal attributable**, and it is the column's
#: other rules rather than decoration. Both constraints name one column and
#: several clauses, so a refusal by constraint name says nothing about which
#: clause fired: a bare lead byte at `opds_servers.credential_key` fails
#: `GLOB 'opds-*'` as well as the charset rule, and would have read as evidence
#: about an arm it never reached. `opds-` in front of it satisfies every clause
#: but the one under test. `catalogue_credentials.source` has no prefix rule and
#: takes an empty one, which is the difference stated rather than a column left
#: blank.
_CONFINEMENT_PROBES: Final[
    tuple[tuple[str, str, str, dict[str, object], bytes, str], ...]
] = (
    (
        "ck_catalogue_credentials_source",
        "catalogue_credentials",
        "source",
        {"envelope": "v2." + "a" * 40 + ".b.c"},
        b"",
        "",
    ),
    (
        "ck_opds_servers_credential_key",
        "opds_servers",
        "credential_key",
        {"name": "The study", "base_url": "https://books.example/opds"},
        b"opds-",
        "opds-",
    ),
)


class TestEveryConfinementArmedConstraintIsProbedToo:
    """The arm that clears a ceiling without a byte budget, and what holds it.

    `TestEveryTextCeilingBindsOnBytesToo` clears a character ceiling on a byte
    arm **or** on a NUL clause beside a charset rule confining the value to one
    byte per character. The first has two backstops and both key on `AS BLOB`.
    The second had none: nothing compared either constraint against the DDL a
    migrated database carries, and `create_all` never runs, so the model's
    declaration installed nothing at all.

    **A gap rather than a live hole when it was found**, and saying which it was
    matters: both revisions were read by hand and each installed the model's text
    character for character. What was missing was anything that would have said
    so the day one of them stopped.

    **The probe is a lead byte rather than a NUL**, and on these two columns that
    is the value the arm exists to refuse: the charset rule is what makes the
    character ceiling a byte ceiling, so a value carrying one counted character
    and a thousand bytes is exactly what it must not admit. It is not a Python
    string, so it goes in as `CAST(x'...' AS TEXT)` in raw SQL.
    """

    @staticmethod
    def _probe(table_name: str) -> Connection:
        """This table alone, on an engine of this test's own, ready for a row."""
        throwaway = create_engine("sqlite://")
        Base.metadata.tables[table_name].create(throwaway)
        return throwaway.connect()

    def test_every_confinement_armed_constraint_has_a_behavioural_case(self) -> None:
        """The whole set at once, so a constraint that joins the class has to be
        given a row rather than inheriting a rule that cannot see it."""
        probed = {name for name, *_ in _CONFINEMENT_PROBES}

        assert set(_confinement_armed_constraints()) == probed, (
            "these rest on a NUL clause and a charset rule with no byte arm, and "
            "nothing probes them: "
            f"{sorted(set(_confinement_armed_constraints()) - probed)}"
        )

    @pytest.mark.parametrize(
        ("constraint", "table_name"),
        [(row[0], row[1]) for row in _CONFINEMENT_PROBES],
        ids=lambda value: value,
    )
    def test_the_model_is_the_constraint_the_revision_installs(
        self, constraint: str, table_name: str
    ) -> None:
        """The two copies, compared against the DDL a migrated database holds.

        An equality rather than a containment, for the reason `_installed_check`
        gives: a containment passes an installed rule that appends to the
        model's, and it passed a dropped floor once already.

        Two of the six fixture columns rather than all six, because the other
        four are the probe's and this case inserts nothing.
        """
        drop_everything()
        schema.upgrade_to_head()

        installed = TestEveryTextCeilingIsInstalledWithItsByteArm._installed_check(
            constraint
        )

        assert installed == _declared_constraint(table_name, constraint)

    @pytest.mark.parametrize(
        ("constraint", "table_name", "column", "others", "prefix", "widest"),
        _CONFINEMENT_PROBES,
        ids=lambda value: value if isinstance(value, str) else "row",
    )
    def test_a_lead_byte_is_refused_however_many_bytes_follow_it(
        self,
        constraint: str,
        table_name: str,
        column: str,
        others: dict[str, object],
        prefix: bytes,
        widest: str,
    ) -> None:
        """The behavioural half, which nothing asked of these two.

        One `x'C0'` and a thousand continuation bytes is one counted character,
        so every `length()` term on the column passes and the charset rule is the
        only clause facing it. That is the arm the house rule clears the ceiling
        on, asked of the engine rather than read off the text.

        **Behind this column's own prefix**, so the refusal is that clause's and
        not some other one's. See `_CONFINEMENT_PROBES`.
        """
        smuggled = prefix + b"\xc0" + b"\xbf" * 1_000
        columns = ", ".join([column, *others])
        placeholders = (f":{name}" for name in others)
        values = ", ".join([f"CAST(x'{smuggled.hex()}' AS TEXT)", *placeholders])

        with (
            self._probe(table_name) as connection,
            pytest.raises(IntegrityError) as refusal,
        ):
            connection.execute(
                text(f"INSERT INTO {table_name} ({columns}) VALUES ({values})"),
                others,
            )

        assert constraint in str(refusal.value)

    @pytest.mark.parametrize(
        ("constraint", "table_name", "column", "others", "prefix", "widest"),
        _CONFINEMENT_PROBES,
        ids=lambda value: value if isinstance(value, str) else "row",
    )
    def test_the_widest_legitimate_value_is_stored(
        self,
        constraint: str,
        table_name: str,
        column: str,
        others: dict[str, object],
        prefix: bytes,
        widest: str,
    ) -> None:
        """The other side, without which a constraint refusing everything passes.

        At the ceiling rather than under it, and every character of it inside the
        charset the rule names, so the value is exactly what the pair is supposed
        to admit and its bytes are its characters. The width comes off the
        column, never off the constraint: see `_CONFINEMENT_PROBES`.
        """
        table = Base.metadata.tables[table_name]
        declared = table.c[column].type
        assert isinstance(declared, String) and declared.length
        at_the_ceiling = widest + "a" * (declared.length - len(widest))

        with self._probe(table_name) as connection:
            connection.execute(
                table.insert().values(**others, **{column: at_the_ceiling})
            )

            counted, stored = connection.execute(
                text(f"SELECT length({column}), length(CAST({column} AS BLOB)) "
                     f"FROM {table_name}")
            ).one()

        assert (counted, stored) == (declared.length, declared.length)



def _opds_api_bounds() -> dict[str, int]:
    """Every `OpdsServerIn` field that names a column of `opds_servers`, and the
    length the API refuses past.

    **Read off `model_fields` and off the table**, never off the source text, so
    a bound reintroduced as a literal in any spelling is still the number this
    compares.

    **The smallest where a field carries several**, because that is the one a
    request meets. Taking the last would probe the looser of two annotations and
    the acceptance case would pass while testing nothing.
    """
    columns = Base.metadata.tables["opds_servers"].c
    bounds: dict[str, int] = {}
    for field, info in OpdsServerIn.model_fields.items():
        if field not in columns:
            continue
        for meta in info.metadata:
            ceiling = getattr(meta, "max_length", None)
            if ceiling is not None:
                bounds[field] = min(bounds.get(field, ceiling), ceiling)
    return bounds


class TestTheApiBoundIsTheCeilingAMigratedDatabaseInstalls:
    """What the route refuses past, against what the column refuses past.

    Each of these bounds is one number in three spellings: a constant in
    `models.py`, the CHECK a revision wrote out, and the `StringConstraints`
    the route validates with. The constant is the one home and a revision
    cannot import it, so something has to stand between them.

    **Behavioural, and against the migrated database.** Comparing the constant
    with itself proves nothing, and comparing constraint text only refuses the
    spellings it enumerates. These insert the widest value the route accepts
    and the first one it refuses, so a bound moved at either end goes red.

    **Sized off `model_fields` and off nothing else, which is what makes these
    not the duplicates they resemble.** Two classes above probe the same two
    columns and size every case off the constant or off the column width:
    `TestEveryTextCeilingIsInstalledWithItsByteArm` and
    `TestTheGlobRulesThatLearnedAboutNul`. So a bound moved in `schemas/opds.py`
    alone leaves every one of their cases green. Measured:
    `max_length=SERVER_NAME_MAX - 1` reddens the refusal case here and nothing
    else in either class.

    **Both bounded fields, walked rather than listed**, so a third bounded
    column on this table arrives at a red tripwire asking for its lead rather
    than passing unexamined.
    """

    #: What each field must start with for the column's **other** rules to pass,
    #: so length is the only thing under test. `base_url` has a scheme rule;
    #: a name is free text.
    LEADS: Final[dict[str, str]] = {"name": "", "base_url": "http://"}

    @staticmethod
    def _migrated() -> None:
        drop_everything()
        schema.upgrade_to_head()

    @classmethod
    def _row(cls, field: str, length: int) -> tuple[str, dict[str, str]]:
        """One insertable row with `field` at exactly `length` characters."""
        lead = cls.LEADS[field]
        values = {
            "name": "a server",
            "base_url": "http://books.example/opds",
            "credential_key": "opds-0123456789abcdef",
            field: lead + "x" * (length - len(lead)),
        }
        assert len(values[field]) == length
        return (
            "INSERT INTO opds_servers (name, base_url, credential_key) "
            "VALUES (:name, :base_url, :credential_key)",
            values,
        )

    def test_the_walk_finds_both_bounded_fields(self) -> None:
        """A tripwire. A walk that read `metadata` on a field carrying its
        ceiling elsewhere would collect no cases below at all, which says
        nothing on any tree and reads exactly like a clean run. The second
        assertion is what makes a field arriving without a lead red here rather
        than silently unprobed."""
        assert set(_opds_api_bounds()) == {"name", "base_url"}
        assert set(self.LEADS) == set(_opds_api_bounds())

    @pytest.mark.parametrize("field", sorted(_opds_api_bounds()))
    def test_the_widest_value_the_route_accepts_is_stored(self, field: str) -> None:
        """The API bound is at most the column's. Without this, a constant
        raised with no revision behind it leaves the route accepting a value
        every write then refuses with a 500."""
        self._migrated()
        statement, values = self._row(field, _opds_api_bounds()[field])

        with engine.connect() as connection:
            connection.execute(text(statement), values)
            connection.commit()

            assert connection.execute(
                # The interpolation is a column name off this table, never a
                # request value.
                text(f"SELECT length({field}) FROM opds_servers")
            ).scalar() == _opds_api_bounds()[field]

    @pytest.mark.parametrize("field", sorted(_opds_api_bounds()))
    def test_one_character_past_it_is_refused_by_this_columns_own_rule(
        self, field: str
    ) -> None:
        """The other side, and the half a bound alone is not: without it the API
        could be narrowed to anything and the case above would still pass.

        **The refusal is checked by name**, derived from the column rather than
        listed, because `pytest.raises(IntegrityError)` alone passes when the
        insert fails for an unrelated reason.
        """
        self._migrated()
        statement, values = self._row(field, _opds_api_bounds()[field] + 1)

        with engine.connect() as connection, pytest.raises(IntegrityError) as refusal:
            connection.execute(text(statement), values)

        assert f"ck_opds_servers_{field}" in str(refusal.value)
