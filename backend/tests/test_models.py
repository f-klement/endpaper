"""Tests for backend/models.py: constraints, defaults and relationships.

These exercise the ORM directly rather than through the API, because the
behaviour under test belongs to the schema.
"""

import ast
import re
import symtable
import textwrap
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from database import Base
from models import (
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


class TestEveryBookQueryIsFiltered:
    """House rule: every query returning or counting books applies
    `visible_to()`, or `in_trash_for()` for the trash views.

    Nothing else catches a breach. A missing filter returns other members'
    private books with a 200 and no error anywhere, and it is an easy thing to
    leave out: `list_tags` counted books without it for a while, and the tags
    endpoint therefore disclosed which tags existed only on somebody's private
    books.

    A statement may opt out with a `# visible_to exempt:` comment giving the
    reason. There are 5, in two groups, and `test_the_exemptions_are_still_the_known_ones`
    counts them so the list cannot grow quietly:

    * four about **uniqueness**, which is a table-wide rule. A clash with a
      book the caller cannot see is still a clash, so filtering the check would
      turn a 409 into a 500.
    * one in `serialisation`, which re-reads rows a caller already filtered in
      order to populate a relationship on the objects in hand.

    The number above is parsed out of this paragraph by that test, so prose and
    tree cannot drift. That is not a flourish: this round produced four
    separate stated numbers that disagreed with the code, in four files.
    """

    EXEMPTION = "visible_to exempt:"
    PREDICATES = ("visible_to(", "in_trash_for(")

    def _leaf_statements(self, scope):
        """Statements in one scope that contain no other statement.

        The unit to check is the whole chained expression, since the filter is
        several calls along from `query(Book)`. Checking a `for` or an `if`
        would swallow its entire body and pass on a predicate used elsewhere
        inside it.

        **Scope limited**: it does not descend into a nested function, which is
        visited in its own right with its own bindings. Without that, a
        statement inside a function would be checked twice, and the pass that
        did not hold its bindings would report it.
        """
        for node in self._statements_in(scope):
            if any(isinstance(child, ast.stmt) for child in ast.iter_child_nodes(node)):
                continue
            yield node

    def _statements_in(self, scope):
        """Every statement in one scope, not descending into a nested scope.

        A nested function is its own scope and is visited in its own right, so
        walking into it here would attribute its bindings to the parent.
        """
        pending = list(ast.iter_child_nodes(scope))
        while pending:
            node = pending.pop()
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                # Each of these opens a scope and is visited as one, a class
                # body included: skipping classes outright meant a query
                # written directly in one was never checked at all.
                continue
            if isinstance(node, ast.stmt):
                yield node
            pending.extend(ast.iter_child_nodes(node))

    def _queries_books(self, node) -> bool:
        """Whether this statement queries the books table at all.

        Both shapes count, and the second was invisible to this rule for as
        long as it existed. `query(Book)` returns rows; `query(Book.author)`
        returns a column out of the same rows, and leaking which authors,
        locations, series or collections exist is the same leak by a narrower
        door: the tag counts and the collection counts were each fixed for
        exactly that.

        Counted over the tree with this rule's own scoping, **14** leaf
        statements take the column form and none of them also takes the row
        form: six in `routers/books.py`, four in `routers/stats.py`, two in
        `routers/imports.py`, one in `routers/collections.py` and one in
        `serialisation.py`. Sixteen more take the row form. One of the fourteen
        (`routers/imports.py`, the ISBN uniqueness check) carried no exemption
        comment, because nothing had ever asked it for one.

        Two of the six in `routers/books.py` are `list_quotes`, and they are
        the reason the column form matters rather than an example of it. Its
        row half selects `Book.title`, `Book.author` and `Book.cover_url`
        beside a quote row, so without the predicate it would print a private
        book's title and cover next to a passage out of it. Its count half is
        spelled `count(Book.id)` rather than `count(Quote.id)` **so that this
        rule can see it at all**: the two are identical over an inner join on a
        primary key, and only the first is a statement this rule inspects.

        **What this rule does not see: the join-only form.** A statement whose
        `query()` names no `Book` and reaches the table through
        `.join(Book, ...)` is invisible here, whatever it selects. Measured
        over the tree, **10** statements take that shape:
        `routers/books.py:138`, `routers/loans.py:239`,
        `routers/stats.py:76,112,126,144`, `routers/loans.py:80`,
        `routers/books.py:625` and `notifications.py:140,171`. Every one is
        filtered, but only the first six carry the predicate inside the
        statement itself; `loans.py:80` and `books.py:625` both mutate a query
        built with `visible_to` in an *earlier* statement, and the two in
        `notifications.py` apply an explicit `Book.is_private` clause instead,
        because the overdue digest counts the private ones rather than hiding
        them.

        So **14** is the count of column-form statements this rule inspects,
        not the count of every query that derives from books, and a new
        join-only query gets no help from here.

        **The other blind spot: a child table carrying book-derived data.** A
        query over `classifications`, `quotes`, `notes` or `reading_progress`
        names no `Book` and is invisible here whatever it selects.
        `db.query(Classification)` in `routers/books.py:_repoint_relations` is
        the live example, and it is safe because its ids come from a set
        already filtered by `visible_to` in the same handler. The one to watch
        for is an **index** over such a table: "every DDC number in the library,
        with a count" is exactly the shape this rule was widened for (an author
        index, a series list, a location list, which publish a name and a
        count), and it can now be written without touching `Book` at all.
        `docs/data-model.md` and `docs/archive/implementation_plan.md` §30i both say library
        mode will show classifications, so that query is coming.

        Not widened to those tables today: it would cost an exemption on the
        merge statement above and move three stated numbers, to guard a query
        nobody has written yet. Named here instead, for the same reason the
        join-only paragraph exists: a guard whose limits are undocumented is
        read as a guarantee it never made.

        Widening `_queries_books` to catch `.join(Book, ...)` was measured
        rather than argued about: the inspected set goes from **30** statements
        to **40**, and the run reports **4** offenders that are all correct
        code (`notifications.py:140,171`, `routers/loans.py:80`,
        `routers/books.py:625`), so it buys ten more inspected statements at
        the price of four exemptions that
        exist only to silence it. Refused on that arithmetic, and recorded here
        because the next reader will have the same idea. `_masked` records its
        own blind spot the same way, and for the same reason: a guard whose
        limits are undocumented is read as a guarantee it never made.
        """
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if not (isinstance(func, ast.Attribute) and func.attr == "query"):
                continue
            for argument in call.args:
                if isinstance(argument, ast.Name) and argument.id == "Book":
                    return True
                # `Book.author`, `Book.id`, `func.count(Book.id)`: any column
                # of the table, however deep in the expression.
                if any(
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "Book"
                    for child in ast.walk(argument)
                ):
                    return True
        return False

    def _bindings(self, scope, table) -> tuple[set[str], set[str]]:
        """`(names bound to a predicate here, names bound to anything else)`.

        `routers/stats.py` applies the predicate six times and binds it once
        (`visible = visible_to(current_user.id)`), so the statements using it
        never contain the call. A purely textual rule reports all six, which is
        a rule that cries wolf on the file that gets it most right.

        **The second set comes from `symtable`, not from walking the AST.**
        Two earlier versions enumerated binding syntax and both enumerations
        were short: first only `ast.Assign`, then every `Name` in `Store`
        context plus parameters, which still could not see
        `except ValueError as visible`, `import os as visible` or a match
        capture pattern, because each of those carries its target as a plain
        `str` rather than as a `Name` node. There is nothing there to walk.

        `symtable` is the compiler's own answer to "what does this scope bind",
        so it covers those three, covers whatever Python binds next, and
        replaces the parameter walk with a flag. `is_imported()` is needed
        beside `is_assigned()`: `import os as visible` binds a name that
        reports `is_assigned() == False`, which is the shape that would have
        been missed by adopting this carelessly.

        **It is asked about a source with the predicate assignments masked
        out**, which is what makes it answer the right question. A symbol table
        is set valued: `visible` bound once by `visible_to(...)` and `visible`
        bound twice, the second time by a request value, are the same symbol
        with the same flags. Asking it directly therefore accepted every
        rebinding, which is the hole the previous version existed to close. So
        `_masked` blanks the predicate targets in the text first, and whatever
        `symtable` still reports as bound is bound by something else.
        """
        predicate = {
            target.id
            for node in self._statements_in(scope)
            for target in self._predicate_targets(node)
        }
        bound = {
            symbol.get_name()
            for symbol in table.get_symbols()
            if symbol.is_assigned() or symbol.is_parameter() or symbol.is_imported()
        }
        return predicate, bound

    def _predicate_targets(self, node):
        """The `Name` targets of a statement that assigns a predicate call."""
        if not isinstance(node, ast.Assign):
            return []
        call = node.value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and f"{call.func.id}(" in self.PREDICATES
        ):
            return []
        return [target for target in node.targets if isinstance(target, ast.Name)]

    def _masked(self, source: str) -> str:
        """The source with every predicate assignment's target blanked out.

        Replaced by underscores of **the same length**, so every line, column
        and line number is exactly where it was and the scope mapping still
        lines up. What comes back from `symtable` for this text is therefore
        "bound by something that is not one of those assignments", which is the
        question this rule actually asks.

        A source that already contains a name of only underscores would have a
        rebinding of *that* name missed. Stated rather than guarded, because
        the guard would cost more than the case is worth.

        Sliced as **bytes**, because `col_offset` is a UTF-8 byte offset rather
        than a character index. A line with an accent before the target would
        otherwise be cut in the wrong place, and the result is not a wrong
        answer but a `SyntaxError` out of the lint.
        """
        lines = source.splitlines(keepends=True)
        for node in ast.walk(ast.parse(source)):
            for target in self._predicate_targets(node):
                line = lines[target.lineno - 1].encode()
                width = target.end_col_offset - target.col_offset
                lines[target.lineno - 1] = (
                    line[: target.col_offset]
                    + b"_" * width
                    + line[target.end_col_offset :]
                ).decode()
        return "".join(lines)

    def _tables(self, source: str):
        """The module's symbol table, plus every nested one by AST position.

        Keyed on `(kind, name, lineno)`, which is what an `ast` scope node
        knows about itself. Both agree on the `def` or `class` line even when
        the definition is decorated, which was checked rather than assumed.

        `annotation` tables are skipped: PEP 649 gives every annotated scope an
        `__annotate__` child, and it binds nothing anybody wrote.
        """
        top = symtable.symtable(self._masked(source), "<rule>", "exec")
        nested: dict[tuple[str, str, int], symtable.SymbolTable] = {}

        def collect(table: symtable.SymbolTable) -> None:
            for child in table.get_children():
                if child.get_type() != "annotation":
                    nested[(child.get_type(), child.get_name(), child.get_lineno())] = child
                collect(child)

        collect(top)
        return top, nested

    def _table_for(self, node, top, nested):
        """The symbol table for one AST scope, or None if they disagree."""
        if isinstance(node, ast.Module):
            return top
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        return nested.get((kind, node.name, node.lineno))

    def _scopes(self, node, top, nested, inherited=frozenset()):
        """`(scope, names in scope)` for the module and every scope inside it.

        Inherited downward, because a closure really can read the enclosing
        function's local, and this rule is about what the interpreter would
        resolve rather than about where the characters sit.

        Recursion goes through the **immediately** nested scopes rather than
        through every scope anywhere below, or a nested one is visited twice:
        once here with its parent's bindings and once from the module with
        none, and the second pass reports what the first accepts.

        A **class body is a scope**, which is what `symtable` says too. It was
        skipped outright once, and a query written in one was then never
        checked at all.
        """
        table = self._table_for(node, top, nested)
        if table is None:
            # Nothing is known about this scope's bindings, so nothing is
            # accepted on their strength. `test_every_scope_has_a_symbol_table`
            # asserts this branch is unreachable over the real tree, so a
            # mismatch cannot quietly start accepting queries.
            predicate, other = set[str](), set[str]()
        else:
            predicate, other = self._bindings(node, table)
        # Rebinding wins over inheriting, which is what makes a parameter named
        # `visible` shadow the enclosing local rather than borrow its meaning.
        names = (inherited | predicate) - other
        yield node, names
        for child in self._nested_scopes(node):
            yield from self._scopes(child, top, nested, names)

    def _nested_scopes(self, scope):
        """Scopes opened directly in this one, not inside another one."""
        pending = list(ast.iter_child_nodes(scope))
        while pending:
            node = pending.pop()
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                # Not descended into: its own pass recurses, with its bindings.
                yield node
                continue
            pending.extend(ast.iter_child_nodes(node))

    def _filtered_with(self, node) -> set[str]:
        """Names handed **directly** to a `.filter(...)` or `.where(...)`.

        Being in scope is not enough: `.order_by(visible)` and `.limit(visible)`
        mention the name without filtering on it, and both used to pass. The
        predicate has to reach the clause that narrows the rows.

        Directly, and that is the second half. `filter(Book.author == visible)`
        uses the name as a **value** on one side of a comparison, which filters
        by whatever it holds rather than applying it as a predicate, and a walk
        of the argument counted it. A predicate is passed whole.
        """
        names: set[str] = set()
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if not (isinstance(func, ast.Attribute) and func.attr in {"filter", "where"}):
                continue
            names.update(
                argument.id for argument in call.args if isinstance(argument, ast.Name)
            )
        return names

    def _offenders(self, sources: dict[str, str]) -> list[str]:
        """The rule itself, over source text rather than over the tree.

        Separated so the guard tests drive **this** rather than its helpers.
        Asserting on the helpers individually is what let a branch of the
        previous version sit unreachable while every piece passed its own test.
        """
        offenders: list[str] = []
        for name, source in sources.items():
            lines = source.splitlines()
            tree = ast.parse(source)
            top, nested = self._tables(source)
            for scope, bound in self._scopes(tree, top, nested):
                for node in self._leaf_statements(scope):
                    if not self._queries_books(node):
                        continue
                    # The statement, plus the comment block immediately above
                    # it, which is where an exemption sits. Walked upward
                    # rather than a fixed number of lines, so the reason can be
                    # as long as it needs to be.
                    start = node.lineno - 1
                    while start > 0 and lines[start - 1].lstrip().startswith("#"):
                        start -= 1
                    window = "\n".join(lines[start : node.end_lineno])
                    if self.EXEMPTION in window:
                        continue
                    if any(predicate in window for predicate in self.PREDICATES):
                        continue
                    if self._filtered_with(node) & bound:
                        continue
                    offenders.append(f"{name}:{node.lineno}")
        return sorted(set(offenders))

    def test_no_unfiltered_book_query_reaches_the_database(self):
        backend = Path(__file__).resolve().parent.parent
        sources = {
            str(path.relative_to(backend)): path.read_text()
            for path in backend.rglob("*.py")
            if path.relative_to(backend).parts[0] not in {"tests", "migrations", ".venv"}
        }

        assert self._offenders(sources) == [], (
            "These statements query Book without visible_to() or in_trash_for(): "
            + ", ".join(self._offenders(sources))
        )

    def test_the_exemptions_are_still_the_known_ones(self):
        """A count, because an exemption is how the rule is opted out of.

        The docstring above says how many there are and what they are for, and
        a number written in prose is a number that goes stale. Adding one is
        allowed; adding one without saying why in both places is not, and the
        number in the prose is read back here rather than trusted.
        """
        backend = Path(__file__).resolve().parent.parent
        exempt: list[str] = []

        for path in backend.rglob("*.py"):
            relative = path.relative_to(backend)
            if relative.parts[0] in {"tests", "migrations", ".venv"}:
                continue
            for line in path.read_text().splitlines():
                if self.EXEMPTION in line:
                    exempt.append(str(relative))

        # Read back out of the class docstring, so the sentence a reader
        # believes and the list below cannot disagree.
        stated = re.search(r"There are (\d+), in two groups", self.__doc__ or "")
        assert stated is not None, "the class docstring no longer states a count"
        assert int(stated.group(1)) == len(exempt), (
            f"the docstring says {stated.group(1)} exemptions and the tree has "
            f"{len(exempt)}"
        )

        # By file rather than by line: a line number here would fail on any
        # edit above the exemption, which is a test that cries wolf.
        assert sorted(exempt) == [
            "routers/books.py",
            "routers/books.py",
            "routers/books.py",
            "routers/imports.py",
            "serialisation.py",
        ], exempt

    def _probe(self, source: str) -> list[str]:
        """Drive the whole rule over synthetic source.

        The guards below go through this rather than through a helper, because
        the previous version's helpers each passed their own test while the
        branch that used them was wrong.
        """
        return self._offenders({"probe.py": textwrap.dedent(source).strip()})

    def test_the_guard_would_notice_an_unfiltered_query(self):
        """A guard that cannot fail is not a guard. This pins that the shape it
        looks for is the shape the code actually uses."""
        assert self._probe(
            "books = db.query(Book).filter(Book.title == 'Dune').all()"
        ) == ["probe.py:1"]

    def test_the_guard_accepts_a_predicate_bound_to_a_local(self):
        """`routers/stats.py` binds it once and applies it six times. A rule
        that reported those six would be a rule people work around."""
        assert (
            self._probe(
                """
                def stats(db, user):
                    visible = visible_to(user.id)
                    return db.query(Book.id).filter(visible).all()
                """
            )
            == []
        )

    def test_a_binding_in_another_function_launders_nothing(self):
        """The hole, and it is not merely a loophole: delete the first function
        and the second is reported, so the verdict depended on code that could
        not run."""
        assert self._probe(
            """
            def elsewhere(db, user):
                visible = visible_to(user.id)
                return visible

            def leaky(db):
                return db.query(Book.author).filter(visible).all()
            """
        ) == ["probe.py:6"]

    def test_a_name_rebound_to_something_else_is_not_a_predicate(self):
        """One assignment made the name a predicate forever, whatever the next
        line did to it."""
        assert self._probe(
            """
            def leaky(db, request, user):
                visible = visible_to(user.id)
                visible = request.args["visible"]
                return db.query(Book).filter(visible).all()
            """
        ) == ["probe.py:4"]

    def test_every_way_of_rebinding_counts_not_only_assignment(self):
        """Reading `ast.Assign` alone closed one of six doors.

        A `for` target, `with ... as`, a walrus, an annotated assignment and an
        augmented one all rebind the name, and each shape was accepted. Binding
        **context** catches them together rather than one at a time.
        """
        shapes = {
            "a for target": "for visible in rows: pass",
            "a with binding": "with open(path) as visible: pass",
            "a walrus": "if (visible := request.args): pass",
            "an annotated assignment": "visible: str = request.args",
            "an augmented assignment": "visible += request.args",
        }
        for label, line in shapes.items():
            offenders = self._probe(
                f"""
                def leaky(db, request, user, rows, path):
                    visible = visible_to(user.id)
                    {line}
                    return db.query(Book).filter(visible).all()
                """
            )
            assert offenders == ["probe.py:4"], f"{label}: {offenders}"

    def test_the_three_bindings_an_ast_walk_cannot_see(self):
        """Each of these carries its target as a plain string, not a `Name`.

        `except ... as`, `import ... as` and a match capture pattern were all
        accepted by a `Store` context walk, because there is no `Store` node in
        any of them to find. This is why the rule asks `symtable` rather than
        enumerating syntax: two enumerations were already short.

        Written out rather than built by interpolation, because each shape is
        several lines with its own indentation.
        """
        shapes = {
            "except as": (
                "def leaky(db, user):\n"
                "    visible = visible_to(user.id)\n"
                "    try:\n"
                "        pass\n"
                "    except ValueError as visible:\n"
                "        pass\n"
                "    return db.query(Book).filter(visible).all()\n"
            ),
            "import as": (
                "def leaky(db, user):\n"
                "    visible = visible_to(user.id)\n"
                "    import os as visible\n"
                "    return db.query(Book).filter(visible).all()\n"
            ),
            "match capture": (
                "def leaky(db, user, thing):\n"
                "    visible = visible_to(user.id)\n"
                "    match thing:\n"
                "        case {'a': visible}:\n"
                "            pass\n"
                "    return db.query(Book).filter(visible).all()\n"
            ),
        }
        for label, source in shapes.items():
            offenders = self._offenders({"probe.py": source})
            assert len(offenders) == 1, f"{label} was accepted: {offenders}"

    def test_every_scope_has_a_symbol_table(self):
        """The rule's one permissive branch, asserted unreachable.

        A scope whose table cannot be found accepts nothing on the strength of
        its bindings, which is the safe direction but silent. This walks the
        real tree and proves the two agree on every scope in it, so the branch
        is a guard rather than a hole.
        """
        backend = Path(__file__).resolve().parent.parent
        unmatched: list[str] = []

        for path in backend.rglob("*.py"):
            if path.relative_to(backend).parts[0] in {"tests", "migrations", ".venv"}:
                continue
            source = path.read_text()
            top, nested = self._tables(source)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(
                    node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                ):
                    continue
                if self._table_for(node, top, nested) is None:
                    unmatched.append(
                        f"{path.relative_to(backend)}:{node.lineno} ({node.name})"
                    )

        assert unmatched == [], unmatched

    def test_a_parameter_shadows_an_inherited_predicate(self):
        """The case that contradicted the rule's own stated property.

        `visible` inside `inner` is the parameter, whatever the enclosing
        function bound. A rule about what the interpreter resolves has to see
        that; a rule about where the characters sit does not.
        """
        assert self._probe(
            """
            def outer(db, user):
                visible = visible_to(user.id)

                def inner(visible):
                    return db.query(Book).filter(visible).all()

                return inner(request.args)
            """
        ) == ["probe.py:5"]

    def test_a_query_in_a_class_body_is_checked_at_all(self):
        """It was not: the walk skipped `ClassDef` outright, so this shape was
        never examined rather than being examined and accepted."""
        assert self._probe(
            """
            class Report:
                rows = db.query(Book).all()
            """
        ) == ["probe.py:2"]

    def test_the_predicate_used_as_a_value_is_not_a_filter(self):
        """`filter(Book.author == visible)` filters **by** the name's contents.
        A predicate is passed whole, and a walk of the argument counted the
        comparison as one."""
        assert self._probe(
            """
            def leaky(db, user):
                visible = visible_to(user.id)
                return db.query(Book).filter(Book.author == visible).all()
            """
        ) == ["probe.py:3"]

    def test_mentioning_the_predicate_without_filtering_on_it_is_not_enough(self):
        """`order_by(visible)` narrows nothing, and passed."""
        assert self._probe(
            """
            def leaky(db, user):
                visible = visible_to(user.id)
                return db.query(Book).order_by(visible).all()
            """
        ) == ["probe.py:3"]

    def test_a_closure_may_use_the_enclosing_function_s_predicate(self):
        """The interpreter resolves it, so the rule does too. Reporting this
        would be a rule about where characters sit rather than about what
        runs."""
        assert (
            self._probe(
                """
                def outer(db, user):
                    visible = visible_to(user.id)

                    def inner():
                        return db.query(Book).filter(visible).all()

                    return inner()
                """
            )
            == []
        )

    def test_an_exemption_still_opts_out(self):
        assert (
            self._probe(
                """
                # visible_to exempt: the ISBN is unique across the whole table.
                taken = db.query(Book.isbn).all()
                """
            )
            == []
        )

    def test_the_guard_would_notice_a_query_for_one_column(self):
        """The narrower door, and the one this rule could not see.

        An author index, a location list and a series list are all built this
        way, and each of them publishes a name and a count. A private book
        reaching one of those is the same leak as a private book reaching a
        listing.
        """
        offending = "rows = db.query(Book.author).all()"
        node = next(self._leaf_statements(ast.parse(offending)))
        assert self._queries_books(node)

    def test_the_guard_would_notice_a_column_inside_a_function(self):
        """`func.count(Book.id)` is how every count in this app is written."""
        offending = "rows = db.query(func.count(Book.id)).all()"
        node = next(self._leaf_statements(ast.parse(offending)))
        assert self._queries_books(node)

    def test_the_guard_leaves_another_table_alone(self):
        """Or the rule would demand `visible_to` on every query in the app."""
        offending = "rows = db.query(Tag.name).all()"
        node = next(self._leaf_statements(ast.parse(offending)))
        assert not self._queries_books(node)
