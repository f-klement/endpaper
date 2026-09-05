"""Tests for backend/schema.py: the Alembic runner and its legacy adoption.

The risky case is not a fresh install, it is a database that has been running
since before Alembic existed. These tests build such a database on purpose and
then check it is adopted without losing data.
"""

import random
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import String, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

import filing
import models  # noqa: F401  (registers the tables on Base.metadata)
import schema
import targets
from database import Base, engine
from enums import AuthorityScheme, ClassificationScheme
from migrations.versions import (
    f1c30ab27d84_store_the_shelf_key_beside_the_number as revision,
)
from tests.test_filing import CORPUS


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
    such dance, and which is what these tests hold: `conftest.py` builds the
    schema with `create_all`, so **no other test in the suite puts `books`
    through this migration at all**, and the dependency bot automerges minor and
    patch releases of both libraries.
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
    `conftest.py` builds with `Base.metadata.create_all`, so every other test in
    this repository sees the **models**; a deployment only ever sees the
    **migrations**. `author_identifiers.created_at` shipped as `nullable=True`
    in revision `a4c73e0b19d5` against a `Mapped[datetime]` that is NOT NULL,
    and the whole suite was green. It was found by a person reading the two
    files against each other, which is exactly the thing that does not scale.

    Compared per column on the two properties a migration can get wrong while
    still applying cleanly: **nullability** and **type**. Not on server defaults,
    which SQLite reflects as the literal SQL text it was given and which differ
    harmlessly between `func.now()` and `CURRENT_TIMESTAMP`.
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


class TestTheAuthorityIdentifierConstraintsOnAMigratedDatabase:
    """The four CHECKs and the unique index, against the schema production runs.

    `tests/test_models.py` asserts the same refusals, and it asserts them
    against `create_all`, which is the schema **only the suite** ever has:
    `main.py` boots through `upgrade_to_head()`. The two paths had already
    drifted on `created_at`, which is the evidence that nothing was comparing
    them, so the refusals are checked here on the migrated shape as well.

    `TestTheMigrationsAndTheModelsAgree` compares the two structurally. This
    checks the half that a column comparison cannot see: a CHECK is not a
    column property, and a migration that dropped one would still match.
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

        **Against the migrated database, never the model's.** `conftest.py`
        builds with `create_all`, and `models._scheme_check` derives the same
        constraint from the same enum, so a model built check can only ever
        agree with itself. Only `schema.upgrade_to_head()` runs the revision.

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

    **So this compares a migrated database against `targets.SEEDED` and not
    against `models`**, which is the same reasoning
    `TestTheMigrationsAndTheModelsAgree` gives one class above: the suite builds
    with `create_all` and a deployment only ever sees the migrations.
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
                    f"UPDATE catalogue_targets SET {column} = :value "  # noqa: S608
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
