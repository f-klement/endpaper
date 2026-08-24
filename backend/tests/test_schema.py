"""Tests for backend/schema.py: the Alembic runner and its legacy adoption.

The risky case is not a fresh install, it is a database that has been running
since before Alembic existed. These tests build such a database on purpose and
then check it is adopted without losing data.
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

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
    through this migration at all**, and `renovate.json` automerges minor and
    patch releases of both libraries.
    """

    PREVIOUS = "b1e7c94a2d05"

    def build_database_with_two_copies(self) -> None:
        """A household owning two paperbacks of one title, before collections.

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
            connection.execute(text("INSERT INTO collections (name) VALUES ('Ebooks')"))
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
            connection.execute(
                text(
                    "INSERT INTO classifications (book_id, scheme, number, label) "
                    "VALUES (1, 'lcsh', :number, NULL)"
                ),
                {"number": self.HEADING},
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
            connection.execute(
                text(
                    "INSERT INTO classifications (book_id, scheme, number, label) "
                    "VALUES (1, 'lcsh', :number, NULL)"
                ),
                {"number": self.HEADING},
            )
            connection.commit()

        command.downgrade(schema._alembic_config(), "e2c74a91b5d8")

        assert self.numbers() == ["005.133"]
