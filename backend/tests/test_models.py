"""Tests for backend/models.py: constraints, defaults and relationships.

These exercise the ORM directly rather than through the API, because the
behaviour under test belongs to the schema.
"""

from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from database import Base
from enums import AuthorityProvenance, AuthorityScheme, ClassificationScheme
from models import (
    AUTHORITY_IDENTIFIER_MAX,
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
    switch_targets,
    visible_to,
)


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
