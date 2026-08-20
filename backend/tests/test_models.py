"""Tests for backend/models.py: constraints, defaults and relationships.

These exercise the ORM directly rather than through the API, because the
behaviour under test belongs to the schema.
"""

import ast
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from models import (
    Book,
    Loan,
    Note,
    Tag,
    User,
    UserBook,
    is_switch_target,
    switch_targets,
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
    reason. There is one, and it is about the UNIQUE constraint on ISBN.
    """

    EXEMPTION = "visible_to exempt:"
    PREDICATES = ("visible_to(", "in_trash_for(")

    def _leaf_statements(self, tree):
        """Statements that contain no other statement.

        The unit to check is the whole chained expression, since the filter is
        several calls along from `query(Book)`. Checking a `for` or an `if`
        would swallow its entire body and pass on a predicate used elsewhere
        inside it.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.stmt):
                continue
            if any(isinstance(child, ast.stmt) for child in ast.iter_child_nodes(node)):
                continue
            yield node

    def _queries_books(self, node) -> bool:
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if not (isinstance(func, ast.Attribute) and func.attr == "query"):
                continue
            if any(isinstance(a, ast.Name) and a.id == "Book" for a in call.args):
                return True
        return False

    def test_no_unfiltered_book_query_reaches_the_database(self):
        backend = Path(__file__).resolve().parent.parent
        offenders: list[str] = []

        for path in backend.rglob("*.py"):
            relative = path.relative_to(backend)
            if relative.parts[0] in {"tests", "migrations", ".venv"}:
                continue
            source = path.read_text()
            lines = source.splitlines()

            for node in self._leaf_statements(ast.parse(source)):
                if not self._queries_books(node):
                    continue
                # The statement, plus the comment block immediately above it,
                # which is where an exemption sits. Walked upward rather than a
                # fixed number of lines, so the reason can be as long as it
                # needs to be.
                start = node.lineno - 1
                while start > 0 and lines[start - 1].lstrip().startswith("#"):
                    start -= 1
                window = "\n".join(lines[start : node.end_lineno])
                if self.EXEMPTION in window:
                    continue
                if any(predicate in window for predicate in self.PREDICATES):
                    continue
                offenders.append(f"{relative}:{node.lineno}")

        assert offenders == [], (
            "These statements query Book without visible_to() or in_trash_for(): "
            + ", ".join(offenders)
        )

    def test_the_guard_would_notice_an_unfiltered_query(self, tmp_path):
        """A guard that cannot fail is not a guard. This pins that the shape it
        looks for is the shape the code actually uses."""
        offending = "books = db.query(Book).filter(Book.title == 'Dune').all()"
        node = next(self._leaf_statements(ast.parse(offending)))
        assert self._queries_books(node)
        assert not any(predicate in offending for predicate in self.PREDICATES)
