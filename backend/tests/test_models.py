"""Tests for backend/models.py: constraints, defaults and relationships.

These exercise the ORM directly rather than through the API, because the
behaviour under test belongs to the schema.
"""

import ast
import itertools
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, String, delete, text
from sqlalchemy.exc import IntegrityError

import credentials
import filing
from database import Base
from enums import (
    AuthorityProvenance,
    AuthorityScheme,
    CatalogueSource,
    ClassificationScheme,
)
from models import (
    AUTHORITY_IDENTIFIER_MAX,
    CLASSIFICATION_NUMBER_MAX,
    CLASSIFICATION_SORT_KEY_MAX,
    ONE_BORROWER_SQL,
    OPDS_CREDENTIAL_PREFIX,
    AuthorIdentifier,
    Book,
    Collection,
    Loan,
    Note,
    Quote,
    Tag,
    User,
    UserBook,
    is_switch_target,
    names_exactly_one_borrower,
    new_opds_credential_key,
    note_visible_to,
    switch_targets,
    visible_to,
)

# One walk of the tree, shared, so a rule added here scans the corpus every
# other rule scans. See its docstring for why the exclusion lives there.
from tests.test_house_rules import _source_modules

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def user(db) -> User:
    u = User(username="reader", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def book(db) -> Book:
    b = Book(title="A Book")
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


class TestUser:
    def test_username_is_unique(self, db, user):
        db.add(User(username="reader", password_hash="y"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_is_admin_defaults_to_false(self, db, user):
        assert user.is_admin is False

    def test_created_at_is_populated_by_the_database(self, db, user):
        assert user.created_at is not None

    def test_is_test_account_defaults_to_false(self, db, user):
        """Nothing becomes switchable by being created the ordinary way."""
        assert user.is_test_account is False


class TestIsSwitchTarget:
    """What an admin may exchange a password for a session on.

    The predicate the whole feature turns on. A directory-backed account must
    never satisfy it in any mode: an admin who could mint a session for an LDAP
    or proxy member would be able to read that member's private books.
    """

    @staticmethod
    def _stored(db, **fields) -> User:
        """A committed row, because `auth_source` is a column default: on an
        object that has never been inserted it is still None, and the
        predicate would be answering about a row that does not exist."""
        account = User(**fields)
        db.add(account)
        db.commit()
        db.refresh(account)
        return account

    def test_an_admin_created_test_account_is_one(self, db):
        account = self._stored(
            db, username="tester", password_hash="x", is_test_account=True
        )
        assert is_switch_target(account) is True

    def test_nobody_is_not(self):
        assert is_switch_target(None) is False

    def test_an_ordinary_local_account_is_not(self, db, user):
        """It belongs to a real person, and this app is not asked to hold the
        opinion that an admin knows their password."""
        assert is_switch_target(user) is False

    def test_a_directory_account_is_not_even_when_flagged(self, db):
        """The flag alone does not decide it. A row that carries the flag and
        a directory source is not a shape this app writes, so if one exists it
        was hand-edited, and the answer is still no."""
        account = self._stored(
            db,
            username="tester",
            password_hash="x",
            is_test_account=True,
            auth_source="ldap",
        )
        assert is_switch_target(account) is False

    def test_a_test_account_with_no_password_is_not(self, db):
        """There would be nothing to check, which is the whole guarantee."""
        account = self._stored(
            db, username="tester", password_hash=None, is_test_account=True
        )
        assert is_switch_target(account) is False

    def test_an_admin_is_not_even_when_flagged(self, db):
        """Nothing writes this row today. If anything ever does, a token that
        overrides the proxy's own header would be an admin session that never
        passes the portal again, for as long as the token lives."""
        account = self._stored(
            db,
            username="tester",
            password_hash="x",
            is_test_account=True,
            is_admin=True,
        )
        assert is_switch_target(account) is False

    def test_the_query_predicate_selects_the_same_rows(self, db):
        """Two spellings of one rule, in two languages, which is a thing that
        drifts. Neither can be dropped, so this is what keeps them equal."""
        # Annotated because the values are of mixed type, which mypy otherwise
        # widens to `object` and then refuses to unpack.
        rows: list[dict[str, Any]] = [
            {"username": "target", "password_hash": "x", "is_test_account": True},
            {"username": "member", "password_hash": "x"},
            {"username": "no-hash", "password_hash": None, "is_test_account": True},
            {"username": "empty-hash", "password_hash": "", "is_test_account": True},
            {
                "username": "directory",
                "password_hash": "x",
                "is_test_account": True,
                "auth_source": "ldap",
            },
            {
                "username": "flagged-admin",
                "password_hash": "x",
                "is_test_account": True,
                "is_admin": True,
            },
        ]
        for fields in rows:
            self._stored(db, **fields)

        by_query = {user.username for user in db.query(User).filter(switch_targets())}
        in_python = {
            user.username for user in db.query(User) if is_switch_target(user)
        }

        assert by_query == in_python == {"target"}


class TestQuote:
    """A passage copied out of a book. Shaped after `Note`, plus a page."""

    def test_a_quote_needs_no_page(self, db, user, book):
        """The ordinary case for a line somebody remembers rather than looks up."""
        db.add(Quote(book_id=book.id, user_id=user.id, text="A line"))
        db.commit()
        assert db.query(Quote).one().page is None

    def test_page_zero_is_refused_by_the_database(self, db, user, book):
        """`ck_quotes_page_bounds`, not only `QuoteCreate`. A restore inserts
        through Core and never sees a Pydantic model, which is the same reason
        `ck_reading_progress_bounds` exists."""
        db.add(Quote(book_id=book.id, user_id=user.id, text="A line", page=0))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_a_page_past_the_ceiling_is_refused_by_the_database(self, db, user, book):
        db.add(Quote(book_id=book.id, user_id=user.id, text="A line", page=100_001))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_the_ceiling_is_the_one_the_schema_uses(self):
        """Two spellings of one number, so they cannot drift. A CHECK that
        disagreed with the schema bound would answer 500 for exactly the values
        between them."""
        from models import MAX_PAGE_NUMBER_IN_A_BOOK
        from schemas.progress import MAX_PAGE

        assert MAX_PAGE == MAX_PAGE_NUMBER_IN_A_BOOK

    def test_an_over_long_excerpt_is_refused_by_the_database(self, db, user, book):
        """`ck_quotes_text_bounds`, because `String(2000)` refuses nothing.

        SQLite ignores VARCHAR width: before the CHECK existed, a Core insert
        of 50,000 characters into this column stored 50,000, so the docstrings
        claiming the ceiling was "in the database and not only in the schema"
        described a rule that was not there. Only `backup.restore` reaches this
        table without `QuoteCreate`, so it was a false claim rather than a live
        hole; it is now neither.
        """
        db.add(Quote(book_id=book.id, user_id=user.id, text="x" * 2_001))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_an_excerpt_at_the_ceiling_is_stored(self, db, user, book):
        db.add(Quote(book_id=book.id, user_id=user.id, text="x" * 2_000))
        db.commit()
        assert len(db.query(Quote).one().text) == 2_000

    def test_an_over_long_remark_is_refused_by_the_database(self, db, user, book):
        """The same CHECK covers `note`, which is the field an over-long value
        is most likely to reach: it is optional, so nothing else looks at it."""
        db.add(Quote(book_id=book.id, user_id=user.id, text="ok", note="y" * 1_001))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_a_null_remark_satisfies_the_length_check(self, db, user, book):
        """`note IS NULL OR length(note) <= n`. Without the null branch the
        CHECK evaluates to NULL, which SQLite treats as passing, so this pins
        the branch rather than the outcome."""
        db.add(Quote(book_id=book.id, user_id=user.id, text="ok", note=None))
        db.commit()
        assert db.query(Quote).one().note is None

    def test_the_book_id_index_is_the_composite_and_only_the_composite(self):
        """No standalone `ix_quotes_book_id` beside `ix_quotes_book_page`.

        A composite leading with the same column serves every lookup a
        standalone one would, so shipping both is a second B-tree written on
        every insert for nothing. `reading_progress`, `user_books` and `loans`
        each keep a standalone `book_id` index because their composite leads
        with a different column or is partial; none of those reasons applies
        here, and this is what stops one being added back out of symmetry.
        """
        # From the metadata, not `Quote.__table__`: a declarative class types
        # that attribute as the wider `FromClause`, which has no `indexes`.
        # The same trap `backup.py` and `conftest.py` both document for
        # `insert` and `delete`.
        shapes = {
            tuple(column.name for column in index.columns)
            for index in Base.metadata.tables["quotes"].indexes
        }
        assert ("book_id", "page") in shapes, shapes
        assert ("book_id",) not in shapes, shapes

    def test_deleting_a_book_takes_its_quotes(self, db, user, book):
        """Cascaded like the notes beside them: a passage has no meaning
        without the book it came out of."""
        db.add(Quote(book_id=book.id, user_id=user.id, text="A line"))
        db.commit()

        db.delete(book)
        db.commit()

        assert db.query(Quote).count() == 0


class TestBook:
    def test_title_is_required(self, db):
        db.add(Book())
        with pytest.raises(IntegrityError):
            db.commit()

    def test_isbn_is_unique(self, db):
        db.add(Book(title="One", isbn="9780441013593"))
        db.commit()
        db.add(Book(title="Two", isbn="9780441013593"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_several_books_may_have_no_isbn(self, db):
        """SQL treats NULLs as distinct, which is what makes manual entries work."""
        db.add_all([Book(title="One"), Book(title="Two")])
        db.commit()
        assert db.query(Book).count() == 2

    def test_is_private_defaults_to_false(self, db, book):
        assert book.is_private is False

    def test_optional_metadata_starts_empty(self, db, book):
        assert (book.author, book.publisher, book.year, book.description) == (None, None, None, None)


class TestCollection:
    """A collection is a label on the shelf. It groups books and it hides none."""

    def test_the_name_is_unique_case_insensitively(self, db):
        db.add(Collection(name="Ebooks"))
        db.commit()
        db.add(Collection(name="EBOOKS"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_the_name_is_unique_outside_ascii_too(self, db):
        """Issue #77, as the test that failed before `name_folded` existed.

        The index used to be `lower(name)` evaluated by SQLite, which folds the
        26 ASCII letters and leaves every other letter alone, so this pair was
        two shelves while "Ebooks" and "EBOOKS" were one.
        """
        db.add(Collection(name="Ästhetik"))
        db.commit()
        db.add(Collection(name="ästhetik"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_the_fold_is_stored_beside_the_name(self, db):
        """The name is kept exactly as typed; the fold is what is compared."""
        shelf = Collection(name="Ästhetik")
        db.add(shelf)
        db.commit()

        assert shelf.name == "Ästhetik"
        assert shelf.name_folded == "ästhetik"

    def test_renaming_updates_the_fold(self, db):
        """Without this the validator can be deleted and every route test still
        passes: `create_collection` would keep working and `rename_collection`
        would leave a fold describing the name the shelf used to have."""
        shelf = Collection(name="Ebooks")
        db.add(shelf)
        db.commit()

        shelf.name = "Ästhetik"
        db.commit()

        assert shelf.name_folded == "ästhetik"

    def test_two_different_names_coexist(self, db):
        db.add_all([Collection(name="Ebooks"), Collection(name="Sold")])
        db.commit()
        assert db.query(Collection).count() == 2

    def test_a_book_starts_unfiled(self, db, book):
        assert book.collection_id is None

    def test_deleting_a_collection_unfiles_its_books_rather_than_deleting_them(
        self, db, book
    ):
        """A shelf label is not the books on it. This is the ORM path, which is
        the one the handler takes; the test below is the database's own rule."""
        shelf = Collection(name="Ebooks")
        db.add(shelf)
        db.commit()
        book.collection_id = shelf.id
        db.commit()

        db.delete(shelf)
        db.commit()
        db.refresh(book)

        assert db.query(Book).count() == 1
        assert book.collection_id is None

    def test_deleting_a_book_leaves_the_collection(self, db, book):
        shelf = Collection(name="Ebooks")
        db.add(shelf)
        db.commit()
        book.collection_id = shelf.id
        db.commit()

        db.delete(book)
        db.commit()

        assert db.query(Collection).count() == 1

    def test_the_database_unfiles_them_even_without_the_orm(self, db, book):
        """`ON DELETE SET NULL`, exercised through Core so the ORM's own
        nulling of loaded children cannot be what passes the test. A restore
        and a hand-run statement both reach the table this way, and a row left
        pointing at a destroyed collection would be a dangling foreign key.

        This is also what makes `PRAGMA foreign_keys=ON` load bearing here: the
        rule is decorative without it.
        """
        shelf = Collection(name="Ebooks")
        db.add(shelf)
        db.commit()
        book.collection_id = shelf.id
        db.commit()
        shelf_id, book_id = shelf.id, book.id
        # Detached before the delete, so the assertion below reads the row back
        # from the database rather than an instance the ORM nulled in memory.
        db.expunge_all()

        db.execute(delete(Collection).where(Collection.id == shelf_id))
        db.commit()

        assert db.get(Book, book_id).collection_id is None

    def test_a_collection_is_not_a_privacy_boundary(self, db, user):
        """The one thing this feature must never become. `visible_to` is not
        given a collection to consult, so filing a book changes nothing about
        who may see it: this pins that the predicate ignores the column."""
        shelf = Collection(name="Ebooks")
        db.add(shelf)
        db.commit()
        db.add(Book(title="Filed", collection_id=shelf.id))
        db.commit()

        assert db.query(Book).filter(visible_to(user.id)).count() == 1


class TestARenamedTagStopsBeingASeededOne:
    """The rule the whole bilingual vocabulary rests on, at the ORM.

    A row keeps `key` only while it still carries the seeded name, so a
    household that renamed one is shown their word rather than the curated one.
    The migration applies it to a database being upgraded and
    `backup._repair_seeded_tags` to one being restored; this is the third
    writer, and it exists so that whoever adds a rename route does not have to
    know the rule.

    These run against the **seeded rows the fixture already holds** rather than
    against tags of their own: `uq_tags_key` is unique and the whole vocabulary
    is present, so an invented `Tag(key="fiction", ...)` collides with the real
    Fiction row rather than testing anything. The two insert-order tests delete
    the row first, which is the state `seed_tags()` finds after somebody deletes
    a tag by hand.
    """

    def test_renaming_clears_the_key(self, db):
        tag = db.query(Tag).filter(Tag.name == "Fiction").one()
        assert tag.key == "fiction"

        tag.name = "Stories"
        db.commit()

        assert tag.key is None

    def test_seeding_keeps_the_key_it_was_given(self, db):
        """The insert order this has to survive, measured rather than assumed.

        SQLAlchemy assigns constructor kwargs in the order given and
        `seed_tags()` writes `Tag(key=..., name=...)`, so the key is already
        set when the name is first assigned. A validator without its
        `self.name is not None` clause reads that as a rename and ships the
        whole vocabulary unkeyed.
        """
        db.query(Tag).filter(Tag.name == "Computing").delete()
        db.commit()

        tag = Tag(key="computing", name="Computing", category="genre", is_predefined=True)
        db.add(tag)
        db.commit()

        assert tag.key == "computing"

    def test_the_other_kwarg_order_keeps_it_too(self, db):
        db.query(Tag).filter(Tag.name == "Physics").delete()
        db.commit()

        tag = Tag(name="Physics", category="genre", key="physics", is_predefined=True)
        db.add(tag)
        db.commit()

        assert tag.key == "physics"

    def test_writing_the_same_name_again_is_not_a_rename(self, db):
        """A no-op write must not cost a tag its translation."""
        tag = db.query(Tag).filter(Tag.name == "Fantasy").one()

        tag.name = "Fantasy"
        db.commit()

        assert tag.key == "fantasy"

    def test_renaming_a_tag_the_library_invented_changes_nothing(self, db):
        tag = Tag(name="Holiday reads", category="custom")
        db.add(tag)
        db.commit()

        tag.name = "Beach reads"
        db.commit()

        assert tag.key is None
        assert tag.name == "Beach reads"


class TestTagAssociation:
    def test_a_book_can_carry_several_tags(self, db, book):
        tags = db.query(Tag).limit(2).all()
        book.tags.extend(tags)
        db.commit()
        assert len(book.tags) == 2

    def test_a_tag_can_be_on_several_books(self, db):
        tag = db.query(Tag).first()
        for title in ("One", "Two"):
            b = Book(title=title)
            b.tags.append(tag)
            db.add(b)
        db.commit()
        assert db.query(Book).filter(Book.tags.any(Tag.id == tag.id)).count() == 2

    def test_tag_names_are_unique(self, db):
        db.add(Tag(name="Fantasy", category="genre"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_deleting_a_book_clears_its_tag_links_not_the_tags(self, db, book):
        tag = db.query(Tag).first()
        book.tags.append(tag)
        db.commit()
        db.delete(book)
        db.commit()
        assert db.get(Tag, tag.id) is not None


class TestCascades:
    def test_deleting_a_book_deletes_its_notes(self, db, book, user):
        db.add(Note(book_id=book.id, user_id=user.id, content="note"))
        db.commit()
        db.delete(book)
        db.commit()
        assert db.query(Note).count() == 0

    def test_deleting_a_book_deletes_its_loans(self, db, book, user):
        db.add(Loan(book_id=book.id, loaned_to_user_id=user.id, loaned_by_user_id=user.id))
        db.commit()
        db.delete(book)
        db.commit()
        assert db.query(Loan).count() == 0

    def test_deleting_a_book_deletes_its_read_statuses(self, db, book, user):
        db.add(UserBook(user_id=user.id, book_id=book.id, status="read"))
        db.commit()
        db.delete(book)
        db.commit()
        assert db.query(UserBook).count() == 0


class TestRelationships:
    def test_a_book_knows_who_added_it(self, db, user):
        b = Book(title="Mine", added_by_user_id=user.id)
        db.add(b)
        db.commit()
        assert b.added_by is not None
        assert b.added_by.username == "reader"

    def test_a_loan_distinguishes_lender_from_borrower(self, db, book):
        lender = User(username="lender", password_hash="x")
        borrower = User(username="borrower", password_hash="x")
        db.add_all([lender, borrower])
        db.commit()
        loan = Loan(
            book_id=book.id, loaned_by_user_id=lender.id, loaned_to_user_id=borrower.id
        )
        db.add(loan)
        db.commit()
        assert loan.loaned_by.username == "lender"
        assert loan.loaned_to is not None
        assert loan.loaned_to.username == "borrower"

    def test_a_returned_loan_records_the_return_time(self, db, book, user):
        loan = Loan(book_id=book.id, loaned_to_user_id=user.id, loaned_by_user_id=user.id)
        db.add(loan)
        db.commit()
        assert loan.returned_at is None

    def test_user_book_status_defaults_to_unread(self, db, book, user):
        ub = UserBook(user_id=user.id, book_id=book.id)
        db.add(ub)
        db.commit()
        assert ub.status == "unread"

    def test_a_note_exposes_its_author(self, db, book, user):
        note = Note(book_id=book.id, user_id=user.id, content="hi")
        db.add(note)
        db.commit()
        assert note.author.username == "reader"


class TestTheBorrowerRule:
    """Exactly one of `loaned_to_user_id` and `loaned_to_name` is set.

    In the database rather than only in `LoanCreate`, because the schema guards
    one writer and a restore, an import or the next endpoint added does not go
    through it. Same reasoning as the open-loan index above it.
    """

    def test_a_member_borrower_is_accepted(self, db, book, user):
        db.add(Loan(book_id=book.id, loaned_to_user_id=user.id, loaned_by_user_id=user.id))
        db.commit()
        assert db.query(Loan).count() == 1

    def test_a_named_borrower_is_accepted(self, db, book, user):
        db.add(
            Loan(book_id=book.id, loaned_to_name="the neighbour", loaned_by_user_id=user.id)
        )
        db.commit()
        assert db.query(Loan).one().loaned_to is None

    def test_naming_both_is_refused(self, db, book, user):
        db.add(
            Loan(
                book_id=book.id,
                loaned_to_user_id=user.id,
                loaned_to_name="the neighbour",
                loaned_by_user_id=user.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()

    def test_naming_neither_is_refused(self, db, book, user):
        db.add(Loan(book_id=book.id, loaned_by_user_id=user.id))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_a_whitespace_name_is_refused_by_the_database(self, db, book, user):
        """`'   '` satisfies IS NOT NULL and identifies nobody, so the loan
        would be a book that is out with nobody to ask for it back.

        `LoanCreate` strips whitespace, and `LoanCreate` is exactly the writer
        this constraint exists because you cannot rely on: a restore and an
        import both write rows without it.
        """
        db.add(Loan(book_id=book.id, loaned_to_name="   ", loaned_by_user_id=user.id))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_an_empty_name_is_refused_by_the_database(self, db, book, user):
        db.add(Loan(book_id=book.id, loaned_to_name="", loaned_by_user_id=user.id))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_a_name_with_spaces_around_it_is_still_accepted(self, db, book, user):
        # Only all-whitespace is refused. Trimming is the schema's job.
        db.add(Loan(book_id=book.id, loaned_to_name=" Ada ", loaned_by_user_id=user.id))
        db.commit()
        assert db.query(Loan).count() == 1


class TestTheBorrowerRuleHasOneSpelling:
    """The rule above, stated twice on purpose, and asked rather than read.

    `models.ONE_BORROWER_SQL` is the SQL and `models.names_exactly_one_borrower`
    is the Python. Everything else that used to state the rule now calls one of
    them: the CHECK constraint is built from the constant, `LoanCreate` applies
    the predicate, and the two documents point at both. What is left is the risk
    that the two spellings mean different things, which no amount of reading
    them side by side settles, because two careful readings are one instrument
    twice.

    So the database is **asked**: every pair below is written through the ORM,
    which applies no borrower rule of its own, and what the constraint did with
    it is compared against what the predicate says.

    **And the database that answers is the migrated one, not the declared one.**
    `main.init_db` runs `upgrade_to_head()` at import and the test session
    imports `main`, so `loans` is Alembic's table by the time
    `Base.metadata.create_all` runs and is skipped as already there. That is
    what makes this the strongest of the three arms rather than a restatement of
    the constraint: it asks what a database somebody actually migrated enforces.
    Measured, by mutating the constant and finding this class still green while
    a fresh in memory database built from the metadata accepted the row.
    `test_the_pairs_are_written_to_a_migrated_database` is what keeps that true.

    **A corpus somebody chose cannot exhibit a disagreement nobody thought of**,
    which is why the pairs below are not the whole of this class. They were all
    made of spaces once, and the two spellings parted on every whitespace
    character that is not one, and then on a name beginning with a NUL, with
    this class green through both. `test_the_two_spellings_agree_over_a_swept_alphabet`
    is the answer to that: an alphabet crossed with itself rather than a list of
    cases a person found interesting. The pairs stay because a named case fails
    with its own name in the report, where a sweep fails with a value.
    """

    #: Every shape a borrower pair can take, as `(is a member, the name)`.
    #:
    #: The whitespace rows are the ones worth having: `''` and `'   '` both
    #: satisfy `IS NOT NULL` and identify nobody, which is a book that is out
    #: with nobody to ask for it back.
    #:
    #: **The last four are whitespace that is not a space**, and they are here
    #: because a corpus made of spaces certified an agreement it could not see.
    #: SQLite's `trim()` strips the space character alone, so a tab is a name to
    #: the constraint; a predicate spelled `strip()` refuses one, and the two
    #: parted on every pair no case here contained. The three NUL rows are the
    #: same lesson one level down: `length()` counts to the first NUL, so
    #: `'\x00Ada'` is empty to SQLite and refused, and `'Ada\x00Ada'` is not.
    #: U+00A0 is in the list
    #: because `str.strip()` is a Unicode property where `trim()` is a
    #: character, so the difference is a category rather than three characters.
    PAIRS = [
        (False, None),
        (True, None),
        (False, "Ada"),
        (True, "Ada"),
        (False, ""),
        (False, "   "),
        (True, ""),
        (True, "   "),
        (False, " Ada "),
        (False, "\t"),
        (False, "\n"),
        (False, "\xa0"),
        (True, "\t"),
        (False, "\x00"),
        (False, "\x00Ada"),
        (False, "Ada\x00Ada"),
    ]

    @staticmethod
    def _database_accepts(db, book, user, member: bool, name: str | None) -> bool:
        """Whether the constraint lets this pair be stored.

        Through the ORM, which has no borrower rule of its own, so what answers
        is SQLite reading the constraint the migrations put on the table. See
        the class docstring for why that is not the same thing as the constant.

        **An accepted row is deleted again before returning**, and that is not
        tidiness: `uq_loans_one_open_per_book` refuses a second open loan of the
        same book, so a caller asking about several pairs in turn would read the
        second refusal onwards as the borrower rule. Measured, on the first run
        of the two tests below: two pairs the constraint accepts were reported
        as pairs it refuses.
        """
        loan = Loan(
            book_id=book.id,
            loaned_to_user_id=user.id if member else None,
            loaned_to_name=name,
            loaned_by_user_id=user.id,
        )
        db.add(loan)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False
        db.delete(loan)
        db.commit()
        return True

    @pytest.mark.parametrize(("member", "name"), PAIRS)
    def test_the_two_spellings_agree_on_every_pair(self, db, book, user, member, name):
        """One case per pair, so a disagreement names the pair that found it.

        A single case walking the table would pass with every arm but one
        deleted and would never say which pair it was watching.
        """
        stored = self._database_accepts(db, book, user, member, name)
        predicate = names_exactly_one_borrower(user.id if member else None, name)
        assert stored == predicate

    def test_neither_spelling_is_stricter_than_the_other(self, db, book, user):
        """The same claim as a set, in both directions, and it is not a
        duplicate of the cases above.

        Those are nine independent assertions and this is one sentence about
        all of them: which pairs one accepts and the other refuses. A pair
        appearing on either side is the rule having grown a second meaning,
        which is the state this class was written in and had to be corrected
        out of, and the direction it appears on says which side moved.
        """
        stricter = [
            (member, name)
            for member, name in self.PAIRS
            if names_exactly_one_borrower(user.id if member else None, name)
            and not self._database_accepts(db, book, user, member, name)
        ]
        laxer = [
            (member, name)
            for member, name in self.PAIRS
            if self._database_accepts(db, book, user, member, name)
            and not names_exactly_one_borrower(user.id if member else None, name)
        ]
        assert (stricter, laxer) == ([], [])

    def test_neither_spelling_accepts_everything(self, db, book, user):
        """Anti vacuity. Both assertions above hold over a predicate that
        answers True to everything and a constraint that refuses everything,
        which is what a broken driver looks like."""
        accepted = [pair for pair in self.PAIRS if self._database_accepts(db, book, user, *pair)]
        allowed = [
            (member, name)
            for member, name in self.PAIRS
            if names_exactly_one_borrower(user.id if member else None, name)
        ]
        assert 0 < len(accepted) < len(self.PAIRS)
        assert 0 < len(allowed) < len(self.PAIRS)

    #: What the sweep below crosses with itself.
    #:
    #: One entry per behaviour known to make the two spellings part, with the
    #: reason: a space, because `trim()` strips it; the six other ASCII
    #: whitespace characters and two Unicode ones, because `str.strip()` strips
    #: those and `trim()` does not; a NUL, because `length()` stops there; and
    #: two ordinary names, because a corpus of nothing but edge cases cannot
    #: show a rule that refuses everything.
    #:
    #: **This is the enumeration that is left, and it is stated rather than
    #: claimed closed.** Crossing it to length three finds a defect built from
    #: characters that are in it, which is how both known ones were found and is
    #: strictly more than a list of pairs can do. A fourth SQLite behaviour over
    #: a character nobody has added here would be invisible, and the answer when
    #: one turns up is a row here rather than a case in `PAIRS`.
    ALPHABET = (
        "",
        " ",
        "\t",
        "\n",
        "\r",
        "\x0b",
        "\x0c",
        "\x00",
        "\xa0",
        "\u3000",
        "a",
        "Ada",
    )

    def test_the_two_spellings_agree_over_a_swept_alphabet(self):
        """Every name the alphabet builds up to three pieces long, both arms.

        **A sweep rather than a longer list of pairs**, because the two defects
        this class has been corrected out of were both characters nobody thought
        to write down: a tab, then a leading NUL. A third will be the same
        shape, and a list of cases is exactly the instrument that cannot find
        it.

        Against a table built from `ONE_BORROWER_SQL` through `sqlite3`
        directly, rather than through the ORM: this arm is about the constant
        and wants no foreign key, no open loan index and no fixture between the
        constraint and the answer. The pairs above are what exercise the real
        migrated table.
        """
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE probe (loaned_to_user_id INTEGER, loaned_to_name TEXT, "
            f"CHECK ({ONE_BORROWER_SQL}))"
        )

        def accepted(user_id: int | None, name: str | None) -> bool:
            # `sqlite3.IntegrityError` and not SQLAlchemy's: this probe is a raw
            # connection, so the ORM's exception can never be raised here and
            # catching it would say the opposite of what the docstring above is
            # at pains to say.
            try:
                connection.execute("INSERT INTO probe VALUES (?, ?)", (user_id, name))
            except sqlite3.IntegrityError:
                return False
            connection.execute("DELETE FROM probe")
            return True

        names: set[str | None] = {
            "".join(pieces)
            for length in range(4)
            for pieces in itertools.product(self.ALPHABET, repeat=length)
        }
        names.add(None)
        disagreements = [
            (user_id, name)
            for name in sorted(names, key=lambda value: (value is not None, value or ""))
            for user_id in (None, 5)
            if accepted(user_id, name) != names_exactly_one_borrower(user_id, name)
        ]
        assert not disagreements, (
            f"{len(disagreements)} of {len(names) * 2} pairs: the predicate and "
            f"the constraint answer differently. First few: {disagreements[:5]}"
        )
        # Anti vacuity, both halves. A constraint that refused everything and a
        # predicate that agreed would satisfy the line above, and so would a
        # sweep that built no name carrying the characters it exists for.
        assert any(accepted(None, name) for name in names if name is not None)
        assert any(not accepted(None, name) for name in names if name is not None)
        assert {"\x00", "\t", " ", "\xa0"} <= names

    def test_a_borrower_of_one_tab_is_stored_and_nothing_here_refuses_it(
        self, db, book, user
    ):
        """The gap both spellings now agree on, pinned rather than left open.

        `trim()` strips the space character alone, so a name of one tab is a
        name to the constraint and the row is stored: a book that is out with
        nobody to ask for it back, which is what the trim clause was written to
        refuse. It is reachable only by a writer that does not go through
        `LoanCreate`, which strips on Python's rule, and those are the restore
        and the importer, which are exactly the writers the constraint exists
        for.

        **Not closed here**, and the reason is the shape of the fix rather than
        its size: SQL's whitespace is a list of characters and Python's is a
        Unicode property, so widening `trim()` to the four ASCII ones would
        close four holes and read as closing a category. It is filed with the
        measurement instead. This test is what stops it being rediscovered, and
        it fails if somebody widens the constraint, which is the point at which
        the record should be rewritten rather than kept.
        """
        assert self._database_accepts(db, book, user, False, "\t")
        assert names_exactly_one_borrower(None, "\t")

    def test_the_pairs_are_written_to_a_migrated_database(self, db):
        """Which of the two schemas the cases above are answered by.

        `create_all` takes `checkfirst`, so whichever of the two ran first owns
        the table and the other is silently a no op. A stamped
        `alembic_version` says the migrations ran, and therefore that the
        constraint under test is the one a real deployment carries. Were this to
        become `create_all`'s table, every case above would still pass and would
        quietly be comparing the declaration with itself.
        """
        stamped = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert stamped, (
            "The schema these cases are written against was not built by the "
            "migrations, so the constraint they exercise is the one declared "
            "in models.py rather than the one a deployment has."
        )

    def test_the_constraint_is_built_from_the_constant(self):
        """Not a copy of it. Reading it off the table is what would notice the
        text being inlined again, which is the state this constant replaced."""
        table = Base.metadata.tables["loans"]
        checks = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
            and constraint.name == "ck_loans_one_borrower"
        ]
        assert [str(check.sqltext) for check in checks] == [ONE_BORROWER_SQL]

    def test_the_migrated_database_carries_the_constant(self, db):
        """The fourth statement, which cannot call the constant.

        A revision records what was applied on a day, so one that imported a
        constant would change meaning whenever the constant did, and a database
        migrated last year would stop being the same database as one migrated
        tonight. It keeps its own copy for that reason, and the comment beside
        that copy used to assert it was identical to `models.py` with nothing
        behind the claim.

        **What is compared is the constraint the database carries, not the
        revision's source.** Comparing sources forbids the drift the copy exists
        to allow: the first change to the rule would go red, and the ways out
        would be editing a historical revision or deleting this test. The
        effective schema is what has to agree with the constant, and a later
        revision that drops and recreates the constraint is read here without an
        edit.

        Whitespace collapsed, because the DDL SQLite stores keeps the line
        breaks the constraint was written with.
        """
        wanted = " ".join(ONE_BORROWER_SQL.split())
        stored = db.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'loans'")
        ).scalar()
        collapsed = " ".join((stored or "").split())
        assert "ck_loans_one_borrower" in collapsed, collapsed
        assert wanted in collapsed, (
            "The constraint this database enforces is not `ONE_BORROWER_SQL`. "
            "The constant and whatever the migrations built have parted, so "
            f"the predicate is checked against a rule nobody stated:\n{collapsed}"
        )


class TestCoversAreStoredOverHttps:
    """Google Books serves its thumbnails over http, which is mixed content on
    an https page: blocked by the browser whatever the CSP says. Six paths
    write this column, so the upgrade lives on the column itself.
    """

    def test_an_http_cover_is_upgraded_on_the_way_in(self, db):
        db.add(Book(title="Dune", cover_url="http://books.google.com/c.jpg"))
        db.commit()
        assert db.query(Book).one().cover_url == "https://books.google.com/c.jpg"

    def test_an_update_is_upgraded_too(self, db, book):
        book.cover_url = "http://books.google.com/c.jpg"
        db.commit()
        assert book.cover_url.startswith("https://")

    def test_an_uppercase_scheme_is_upgraded_too(self, db, book):
        """A scheme is case-insensitive, and the one-shot data migration
        matches with SQLite's LIKE, which is too. A case-sensitive test here
        would leave the two disagreeing about the same row."""
        book.cover_url = "HTTP://books.google.com/c.jpg"
        db.commit()
        assert book.cover_url == "https://books.google.com/c.jpg"

    def test_a_locally_uploaded_cover_is_untouched(self, db, book):
        book.cover_url = "/covers/1.jpg"
        db.commit()
        assert book.cover_url == "/covers/1.jpg"

    def test_no_cover_stays_no_cover(self, db, book):
        book.cover_url = None
        db.commit()
        assert book.cover_url is None

    def test_a_url_no_image_tag_should_load_is_dropped(self, db, book, caplog):
        """The backstop for writers with no schema in front of them: an
        import, a restore. `BookCreate` answers a caller with a 422 instead."""
        with caplog.at_level("WARNING"):
            book.cover_url = "javascript:alert(1)"
            db.commit()

        assert book.cover_url is None
        assert "not renderable" in caplog.text

    def test_a_scheme_relative_url_is_dropped(self, db, book):
        book.cover_url = "//evil.invalid/x.jpg"
        db.commit()
        assert book.cover_url is None



class TestTheAuthorityIdentifierConstraints:
    """Attempted at the database, which is the point.

    `Authorship` refuses a retype and never writes a bad scheme, so every check
    here is an evasion of that module: a restore, a hand edit, or a future
    writer that forgets. A constraint nobody has tried to get past is a comment.

    **Each assertion names the constraint that fired**, not merely that an
    `IntegrityError` was raised. A test that accepts any refusal passes when a
    foreign key or a `NOT NULL` fires instead, which is the difference between
    knowing a mutation was noticed and knowing what noticed it.
    """

    @staticmethod
    def _row(db, **overrides: Any) -> AuthorIdentifier:
        row = AuthorIdentifier(
            **{
                "author_key": "kane sean p",
                "scheme": AuthorityScheme.GND,
                "identifier": "1042243212",
                "provenance": AuthorityProvenance.CATALOGUE,
            }
            | overrides
        )
        db.add(row)
        return row

    def test_a_subject_heading_scheme_is_refused_as_a_persons_identifier(self, db):
        """`ddc` is a `ClassificationScheme` member and will never be an
        `AuthorityScheme` one.

        **This test has now gone vacuous twice, and the third choice is meant to
        end that.** The value was `viaf` until `viaf` became a member on
        2026-08-28, then `blbnb` until `blbnb` became one later the same day.
        Both times it kept passing right up to the commit that made its subject
        legal and then failed loudly, which is the good outcome and an expensive
        way to learn the lesson: **a refusal test whose subject is a plausible
        future member is a countdown, not a guard.**

        `ddc` is neither. It is a Dewey number, and both enums' docstrings say
        why one column may never hold both: `4203576-4` is what a book is about
        and `118181505` is who wrote it, and a store that accepted the first
        here would make a heading and an author the same kind of row. That is a
        design decision rather than a fact about today's supply, so this cannot
        go vacuous without somebody reversing it.
        """
        self._row(db, scheme="ddc")
        with pytest.raises(IntegrityError) as refusal:
            db.commit()

        assert "ck_author_identifiers_scheme" in str(refusal.value)

    def test_every_scheme_the_enum_offers_is_accepted(self, db):
        """The other direction, and the one a widened enum breaks.

        **Which schema this runs against is not fixed, and saying otherwise
        would be the claim rather than the measurement.** `conftest._schema_once`
        builds with `create_all`, where `models._scheme_check` derives the
        constraint from `AuthorityScheme` and this passes by construction; but
        `tests/test_schema.py`'s `restore_schema` fixture replaces the schema
        with a **migrated** one for the rest of its worker, so on a run where
        the two files share a worker this is against the migration. Measured
        2026-08-28: with `'isni'` removed from `d5e1b93a7c62._SCHEMES_AFTER`,
        this test failed alongside the schema one.

        So the guard that can be relied on to separate the enum from the
        migration is
        `tests/test_schema.py::TestTheAuthorityIdentifierConstraintsOnAMigratedDatabase
        ::test_every_scheme_the_enum_offers_is_storable`, which rebuilds through
        `upgrade_to_head` itself. This one is here so the refusal above cannot
        be read as "no scheme but GND is storable", which is what it used to
        mean.
        """
        for scheme in AuthorityScheme:
            self._row(db, author_key=f"{scheme.value} person", scheme=scheme)
        db.commit()

        assert db.query(AuthorIdentifier).count() == len(AuthorityScheme)

    def test_the_two_scheme_enums_overlap_on_gnd_and_on_nothing_else(self):
        """What the refusal above now rests on, asserted rather than assumed.

        That test needs a value the closed set will never accept, and it has
        twice picked one that was accepted within the day. `ddc` is safe because
        a shelf notation is not a person, and this is the property that says so.

        **The first version of this asserted the two enums share nothing, and
        the suite refused it**, which is the reason it is worth having. They
        share `gnd`, deliberately: the Gemeinsame Normdatei is one file covering
        both subjects and people, the DNB writes both in the same MARC `$0`, and
        `4203576-4` and `118181505` are both GND numbers. What the two enums
        keep apart is the **column**, not the spelling.

        So the invariant is an exact overlap rather than an empty one, and it
        catches three things: a `ClassificationScheme` value arriving as a
        person's scheme, a person's scheme arriving as a subject one, and `gnd`
        being dropped from either side, which would leave the pair describing a
        split that no longer exists.
        """
        shared = {member.value for member in AuthorityScheme} & {
            member.value for member in ClassificationScheme
        }

        assert shared == {"gnd"}

    def test_a_provenance_that_is_neither_is_refused(self, db):
        self._row(db, provenance="robot")
        with pytest.raises(IntegrityError) as refusal:
            db.commit()

        assert "ck_author_identifiers_provenance" in str(refusal.value)

    def test_a_machine_assertion_may_not_name_a_person(self, db, user):
        """`ck_author_identifiers_asserter`. A row that says a catalogue said so
        while naming somebody is the shape an audit cannot read."""
        self._row(db, provenance=AuthorityProvenance.CATALOGUE, created_by_user_id=user.id)
        with pytest.raises(IntegrityError) as refusal:
            db.commit()

        assert "ck_author_identifiers_asserter" in str(refusal.value)

    def test_a_member_assertion_with_no_person_is_allowed(self, db):
        """The other direction is deliberately open, so a row whose author is
        gone still reads `member` rather than becoming a machine's."""
        self._row(db, provenance=AuthorityProvenance.MEMBER, created_by_user_id=None)
        db.commit()

        assert db.query(AuthorIdentifier).count() == 1

    def test_an_empty_identifier_is_refused(self, db):
        self._row(db, identifier="")
        with pytest.raises(IntegrityError) as refusal:
            db.commit()

        assert "ck_author_identifiers_bounds" in str(refusal.value)

    def test_an_identifier_past_the_bound_is_refused(self, db):
        """A stored denial of service bound: a catalogue response has no size
        cap anywhere in `metadata.py`."""
        self._row(db, identifier="9" * (AUTHORITY_IDENTIFIER_MAX + 1))
        with pytest.raises(IntegrityError) as refusal:
            db.commit()

        assert "ck_author_identifiers_bounds" in str(refusal.value)

    def test_one_spelling_may_not_carry_two_values_under_one_scheme(self, db):
        """What makes "refuse a retype" enforceable below the application: a
        differing assertion has no second row to land in."""
        self._row(db)
        db.commit()

        self._row(db, identifier="9999")
        with pytest.raises(IntegrityError) as refusal:
            db.commit()

        # SQLite names the **columns** for a unique index violation and not the
        # index, where it names a CHECK by its own name. Matching on the pair is
        # therefore the strongest form available here, and it is still specific:
        # a foreign key or a NOT NULL firing instead would not print it.
        assert (
            "UNIQUE constraint failed: author_identifiers.author_key, "
            "author_identifiers.scheme" in str(refusal.value)
        )

    def test_two_spellings_may_share_one_identifier(self, db):
        """Not unique on the identifier, because that is exactly the case a
        merge is usually made from."""
        self._row(db)
        db.commit()
        self._row(db, author_key="kane s")
        db.commit()

        assert db.query(AuthorIdentifier).count() == 2


class TestTheShelfKeyFitsItsColumn:
    """`CLASSIFICATION_SORT_KEY_MAX` is wider than the number column, and a
    bound that was not would be a column too narrow for its own values.

    SQLite does not enforce a `VARCHAR` length, so nothing truncates here today
    and nothing would go red on the engine this ships on. That is exactly why
    this is measured rather than left to the schema: the failure would arrive on
    a database that does enforce it, with a key silently cut short and a book
    filed under a class it does not belong to.
    """

    @staticmethod
    def _worst_number() -> str:
        """The longest admissible number whose key is longest.

        `filing.MAX_KEY_GROWTH` is reached by the shortest class prefix the rule
        matches, one letter and one digit, since everything after it is carried
        through verbatim. Padding that out to `CLASSIFICATION_NUMBER_MAX` is the
        longest key the column can be asked to hold.
        """
        return "Q1" + "x" * (CLASSIFICATION_NUMBER_MAX - 2)

    def test_the_widest_key_the_number_column_can_produce_still_fits(self):
        widest = max(
            len(filing.rule_for(scheme).sort_key(self._worst_number()))
            for scheme in ClassificationScheme
        )

        assert widest == CLASSIFICATION_SORT_KEY_MAX

    def test_the_column_is_declared_that_wide(self):
        """So the constant and the column cannot drift apart."""
        column = Base.metadata.tables["classifications"].c.sort_key

        assert isinstance(column.type, String)
        assert column.type.length == CLASSIFICATION_SORT_KEY_MAX

    def test_it_is_wider_than_the_number_it_files(self):
        """The sentence the constant exists for: a key is longer than its
        number, so reusing `CLASSIFICATION_NUMBER_MAX` here would be too
        narrow."""
        assert CLASSIFICATION_SORT_KEY_MAX > CLASSIFICATION_NUMBER_MAX


class TestAnOpdsServerNeverBorrowsACatalogueLogin:
    """`catalogue_credentials.source` holds two key spaces at once: a
    `CatalogueSource` value for a roster row, and an `OpdsServer.credential_key`
    for a household's own machine. If the two could collide, adding a server
    could hand it a catalogue's stored login and send it there.
    """

    def test_no_catalogue_source_is_spelled_with_the_opds_prefix(self):
        assert not [
            source
            for source in CatalogueSource
            if source.value.startswith(OPDS_CREDENTIAL_PREFIX)
        ]

    def test_a_generated_key_carries_the_prefix_and_is_a_safe_source(self):
        """Safe in `credentials.is_safe_source`'s sense, because this value
        becomes `catalogue_credentials.source`, which travels into a URL path."""
        key = new_opds_credential_key()

        assert key.startswith(OPDS_CREDENTIAL_PREFIX)
        assert credentials.is_safe_source(key)

    def test_two_keys_generated_in_a_row_differ(self):
        """Random rather than derived from the row id: SQLite reuses
        `max(rowid) + 1` after a delete, so a derived key would hand a new
        server the login of the one that used to have that id."""
        assert new_opds_credential_key() != new_opds_credential_key()

    def test_the_credential_key_column_refuses_what_is_not_a_source(self, db):
        """`ck_opds_servers_credential_key`, which is
        `ck_catalogue_credentials_source`'s rule over this column's name."""
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO opds_servers (name, base_url, credential_key) "
                    "VALUES ('x', 'http://h/opds', 'opds-../../books/5?')"
                )
            )

    @pytest.mark.parametrize("value", [source.value for source in CatalogueSource])
    def test_the_column_refuses_a_roster_catalogues_key(self, db, value):
        """**The guard above is on the enum and this one is on the column, and
        only the second covers the writer that matters.**

        `backup.restore` re-inserts this table through Core with no validating
        arm, so an archive decides this value. A row naming `bne` beside an
        address of its own makes `credentials.for_request` bind the library's
        sealed BNE login to that address and `header_for` send it: the plaintext
        reaching a host the archive chose, from an archive carrying no key.
        Parametrised over the whole roster rather than one member, so a source
        added later is covered without an arm being remembered.
        """
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO opds_servers (name, base_url, credential_key) "
                    "VALUES ('x', 'http://attacker.example/opds', :key)"
                ),
                {"key": value},
            )

    def test_the_column_admits_the_key_this_application_generates(self, db):
        """The control: a refusal that refused everything would pass the row
        above while making the feature impossible."""
        db.execute(
            text(
                "INSERT INTO opds_servers (name, base_url, credential_key) "
                "VALUES ('x', 'http://library.invalid/opds', :key)"
            ),
            {"key": new_opds_credential_key()},
        )

    def test_the_credential_key_column_refuses_a_path_hidden_behind_a_nul(self, db):
        """SQLite's `length` and `GLOB` stop at the first NUL, so the clause
        that catches this is `instr(credential_key, char(0)) = 0` and nothing
        else in the constraint sees past it."""
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO opds_servers (name, base_url, credential_key) "
                    "VALUES ('x', 'http://h/opds', 'opds-1' || char(0) || '../../books/5?')"
                )
            )

    @pytest.mark.parametrize(
        "address", ["file:///etc/passwd", "gopher://h/opds", "http://", ""]
    )
    def test_the_address_column_refuses_a_scheme_no_sync_would_fetch(self, db, address):
        """The last line for a write that never came through the route, which is
        what a restore is."""
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO opds_servers (name, base_url, credential_key) "
                    "VALUES ('x', :url, 'opds-abc')"
                ),
                {"url": address},
            )

    def test_the_name_column_refuses_an_empty_name(self, db):
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO opds_servers (name, base_url, credential_key) "
                    "VALUES ('', 'http://h/opds', 'opds-abc')"
                )
            )


class TestNoteVisibility:
    """`note_visible_to()` as SQL, against rows rather than by reading it."""

    def test_a_shared_note_is_visible_to_a_member_who_did_not_write_it(self, db, user, book):
        author = User(username="author", password_hash="x")
        db.add(author)
        db.flush()
        db.add(Note(book_id=book.id, user_id=author.id, content="shared"))
        db.commit()

        seen = db.query(Note).filter(note_visible_to(user.id)).all()
        assert [note.content for note in seen] == ["shared"]

    def test_a_private_note_is_visible_only_to_its_author(self, db, user, book):
        author = User(username="author", password_hash="x")
        db.add(author)
        db.flush()
        db.add(Note(book_id=book.id, user_id=author.id, content="mine", is_private=True))
        db.commit()

        assert db.query(Note).filter(note_visible_to(user.id)).all() == []
        assert [n.content for n in db.query(Note).filter(note_visible_to(author.id))] == ["mine"]

    def test_a_note_written_through_the_orm_is_shared_by_default(self, db, user, book):
        """The default is what keeps every stored note meaning what it meant:
        a note has always been readable by whoever can see its book."""
        db.add(Note(book_id=book.id, user_id=user.id, content="typed"))
        db.commit()
        assert db.query(Note).one().is_private is False


#: Local names that mean `models.Note`, per module, so a `from models import
#: Note as N` cannot walk out of the rule. The same evasion `test_shelf.py`
#: measured on `visible_to as _v`.
def _note_aliases(tree: ast.AST) -> set[str]:
    names = {"Note"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            for alias in node.names:
                if alias.name == "Note" and alias.asname:
                    names.add(alias.asname)
    return names


def _own_body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Every node inside `function` except its own annotations and anything
    inside a nested function.

    Without the nesting subtraction a helper defined inside a narrowed function
    would lend it its predicate, and a narrowed function defined inside an
    unnarrowed one would lend it back.

    **The annotations come out for a sharper reason.** The population rule below
    asks whether the body names `Note`, and a function's own `-> list[Note]` is
    an `ast.Name` under the same node: leave it in and every function in the
    population satisfies the rule by its own signature, which is a guard that
    has stopped asking anything.

    **Every argument, through `ast.walk` rather than `args.args`.** An
    `ast.arguments` node holds annotations in five buckets, and naming one of
    them made the verdict depend on how an argument was spelled: measured in
    process on one pass-through function, `note: Note` came out of the
    population and `*, note: Note`, `note: Note, /`, `*notes: Note` and
    `**kw: Note` each stayed in it. The direction was a false offender rather
    than a silent pass, so nothing got through, and it is still the enumerating
    shape this rule dropped once already.
    """
    nested = {
        inner
        for node in ast.iter_child_nodes(function)
        for inner in ast.walk(node)
        if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    skip = {node for outer in nested for node in ast.walk(outer)}
    annotations = [
        node.annotation for node in ast.walk(function.args) if isinstance(node, ast.arg)
    ]
    for annotation in [function.returns, *annotations]:
        if annotation is not None:
            skip |= set(ast.walk(annotation))
    return [node for node in ast.walk(function) if node not in skip and node is not function]


def _reads_and_returns_a_note(
    function: ast.FunctionDef | ast.AsyncFunctionDef, aliases: set[str]
) -> bool:
    """Whether this function **reaches for** an existing note and **returns**
    one.

    Two conditions, and the pair is what makes the rule structural instead of a
    list of call sites. `_repoint_relations` reads `Note` and returns nothing,
    because moving every note off a merged book is not a read for a viewer; it
    is out by its own signature rather than by being named here, and a version
    of it that started returning what it moves would walk in on the same day.

    **Reaching is "names `Note` other than to construct one", not a list of
    accessors.** The first draft asked for `query` or `select` by name, which is
    the enumerating shape this repository keeps paying for: `db.get(Note, id)`
    is the idiom used at nine live call sites under `backend/` and is exactly
    `_note_for_reading_back`'s shape, and it satisfied neither name. A function
    that never enters the population cannot move the population assertion
    either, so that hole was invisible from both arms. Constructing is excluded
    because `add_note` writes a `Note` and hands the read-back to a helper that
    is itself in the population; counting the constructor would put a function
    with no read in it and say nothing about the read.
    """
    annotation = function.returns
    if annotation is None:
        return False
    if not any(
        isinstance(node, ast.Name) and node.id in aliases for node in ast.walk(annotation)
    ):
        return False
    body = _own_body(function)
    constructed = {
        node.func for node in body if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return any(
        isinstance(node, ast.Name) and node.id in aliases and node not in constructed
        for node in body
    )


def _narrows_to_its_reader(
    function: ast.FunctionDef | ast.AsyncFunctionDef, aliases: set[str]
) -> bool:
    """Whether `note_visible_to` appears in this function's own body.

    **One accepted spelling, and the second one was cut rather than tightened.**
    The first draft also accepted a `Note.user_id` anywhere in the body, on the
    argument that restricting to the caller's own rows is equivalent. It does
    not check what the column is compared against, or that it is compared at
    all: `order_by(Note.user_id)` and `filter(Note.user_id != -1)` both read as
    narrowed. Both critic seats found that independently, and the arm was dead
    on arrival, since all three members of the population narrow with the
    predicate. A rule with one spelling is also the reason the predicate has one
    home: a second accepted way to say it is a second place for it to be said
    wrongly.
    """
    return any(
        isinstance(node, ast.Name) and node.id == "note_visible_to"
        for node in _own_body(function)
    )


class TestANoteReadIsNarrowedToItsReader:
    """House rule: a function that reads notes out of the database and hands
    them back must say which member is reading.

    **The population is stated as a shape, not as a list of names**: every
    function under `backend/` whose return annotation mentions `Note` and whose
    body names `Note` other than to construct one. That is what a rule about a
    per-row visibility can afford here and a per-**book** one could not:
    `visible_to` is applied by twenty-odd listings and needed `Shelf` to be a
    seam, and this predicate has three call sites in one router.
    `test_the_population_is_not_empty` asserts those three by name, so the
    figure in this sentence is recomputed by a test rather than copied.

    **What it does not see, listed rather than left to be found:**

    * a function returning `Any`, a `dict`, or a Pydantic model built out of
      notes, since the annotation is what puts it in the population;
    * a query built in one function and returned by another whose own
      annotation names nothing, which is the laundering path
      `test_shelf.py` closes for books with a second pass over `.join`;
    * `book.notes`, the relationship, which names no `Note` at all. Measured
      over the tree on 2026-09-10: no module under `backend/` outside the tests
      traverses it, so the rule's corpus is the whole of the live population
      today and this is a hole in what it would catch tomorrow rather than one
      it is standing over now;
    * `backup.py`, which reads every row of every table through a loop
      variable and names no model at a query at all. It is unfiltered on
      purpose and admin only for that reason, which is the same exemption
      `shelf.py`'s docstring already argues for books.
    """

    def test_every_function_returning_a_note_narrows_it(self):
        offenders = []
        for name, source in _source_modules().items():
            tree = ast.parse(source)
            aliases = _note_aliases(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not _reads_and_returns_a_note(node, aliases):
                    continue
                if not _narrows_to_its_reader(node, aliases):
                    offenders.append(f"{name}:{node.lineno}:{node.name}")
        assert sorted(offenders) == [], (
            "These functions read notes out of the database and return them "
            "without saying who is reading, so a private note reaches whoever "
            f"asked: {sorted(offenders)}"
        )

    def test_the_population_is_not_empty(self):
        """A rule over a corpus it cannot find passes forever.

        This is the arm that would have caught the guard being pointed at a
        tree where the predicate had been renamed, the router split, or the
        walk's exclusion widened until it reached nothing.
        """
        found = []
        for name, source in _source_modules().items():
            tree = ast.parse(source)
            aliases = _note_aliases(tree)
            found += [
                f"{name}:{node.name}"
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and _reads_and_returns_a_note(node, aliases)
            ]
        assert sorted(found) == [
            "routers/books.py:_note_for_edit",
            "routers/books.py:_note_for_reading_back",
            "routers/books.py:get_notes",
        ], sorted(found)

    def test_the_predicate_is_defined_where_this_rule_says_it_is(self):
        """The rule above is a name check, so the name is worth proving real: a
        typo in it would pass over a tree that had dropped the predicate."""
        assert "def note_visible_to(" in (BACKEND / "models.py").read_text()

    def test_a_query_that_forgot_the_predicate_is_reported(self):
        """The rule's own sensitivity check, on source this file owns rather
        than on the tree, so it keeps reporting after the tree is fixed."""
        source = (
            "from models import Note\n"
            "def get_notes(db) -> list[Note]:\n"
            "    return db.query(Note).filter(Note.book_id == 1).all()\n"
        )
        tree = ast.parse(source)
        aliases = _note_aliases(tree)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert _reads_and_returns_a_note(function, aliases)
        assert not _narrows_to_its_reader(function, aliases)

    def test_a_renamed_import_does_not_walk_out_of_the_rule(self):
        source = (
            "from models import Note as N\n"
            "def get_notes(db) -> list[N]:\n"
            "    return db.query(N).filter(N.book_id == 1).all()\n"
        )
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert _reads_and_returns_a_note(function, _note_aliases(tree))

    def test_a_function_that_moves_notes_without_returning_them_is_not_in_it(self):
        """`_repoint_relations`' shape. It reassigns every note on a merged
        book whatever its author, which is right, and it hands none back."""
        source = (
            "from models import Note\n"
            "def _repoint(db, losers) -> None:\n"
            "    for note in db.query(Note).filter(Note.book_id.in_(losers)).all():\n"
            "        note.book_id = 1\n"
        )
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert not _reads_and_returns_a_note(function, _note_aliases(tree))

    def test_a_primary_key_fetch_is_in_the_population(self):
        """`db.get(Note, id)`, which the first draft of the population rule
        could not see. It is the repository's own idiom for a fetch by id and
        it is the shape of the function that reads a note back after a write."""
        source = (
            "from models import Note\n"
            "def read_back(db, note_id) -> Note | None:\n"
            "    return db.get(Note, note_id)\n"
        )
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert _reads_and_returns_a_note(function, _note_aliases(tree))
        assert not _narrows_to_its_reader(function, _note_aliases(tree))

    def test_constructing_a_note_is_not_reaching_for_one(self):
        """`add_note`'s shape. It writes a row and hands the read back to a
        helper that is in the population itself, so counting the constructor
        would put a function with no read into the rule and say nothing about
        the read that follows."""
        source = (
            "from models import Note\n"
            "def add(db, book_id) -> Note | None:\n"
            "    note = Note(book_id=book_id, content='x')\n"
            "    db.add(note)\n"
            "    return read_back(db, note.id)\n"
        )
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert not _reads_and_returns_a_note(function, _note_aliases(tree))

    def test_a_bare_mention_of_the_author_column_is_not_a_narrowing(self):
        """What both critic seats found in the first draft, kept as an arm
        rather than as a paragraph. `Note.user_id` appearing somewhere in a body
        says nothing about what it is compared against, or whether it is
        compared at all."""
        source = (
            "from models import Note\n"
            "def get_notes(db, book_id) -> list[Note]:\n"
            "    return db.query(Note).filter(Note.user_id != -1)"
            ".order_by(Note.user_id).all()\n"
        )
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert _reads_and_returns_a_note(function, _note_aliases(tree))
        assert not _narrows_to_its_reader(function, _note_aliases(tree))

    def test_an_annotation_alone_does_not_satisfy_the_population_rule(self):
        """What `_own_body` dropping the annotations buys. A function whose only
        `Note` is its own return type reaches for nothing."""
        source = (
            "from models import Note\n"
            "def nothing(db) -> list[Note]:\n"
            "    return []\n"
        )
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert not _reads_and_returns_a_note(function, _note_aliases(tree))

    @pytest.mark.parametrize(
        "signature",
        [
            "note: Note",
            "*, note: Note",
            "note: Note, /",
            "*notes: Note",
            "**kw: Note",
        ],
    )
    def test_an_argument_annotation_is_not_a_body_mention_however_it_is_spelled(
        self, signature
    ):
        """An `ast.arguments` node holds annotations in five buckets, and a rule
        naming one of them decides the same function differently depending on
        how its arguments were written. Nothing in this class read an argument
        at all until this arm."""
        source = (
            "from models import Note\n"
            f"def pass_through({signature}) -> Note:\n"
            "    return note\n"
        )
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        assert not _reads_and_returns_a_note(function, _note_aliases(tree))

    def test_a_nested_helper_does_not_lend_its_predicate_to_its_parent(self):
        """What `_own_body` buys. Without it the inner function's call counts
        for the outer one, which is how a rule like this goes quiet."""
        source = (
            "from models import Note\n"
            "from models import note_visible_to\n"
            "def outer(db, viewer) -> list[Note]:\n"
            "    def inner():\n"
            "        return note_visible_to(viewer)\n"
            "    return db.query(Note).all()\n"
        )
        tree = ast.parse(source)
        outer = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "outer"
        )
        assert _reads_and_returns_a_note(outer, _note_aliases(tree))
        assert not _narrows_to_its_reader(outer, _note_aliases(tree))
