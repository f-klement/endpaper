"""Tests for backend/schemas.py: the Pydantic request/response contracts."""

import pytest
from pydantic import ValidationError

from enums import ReadStatus
from schemas import (
    BookCreate,
    BookOut,
    BookStatusUpdate,
    LoanCreate,
    LoginRequest,
    NoteCreate,
    UserCreate,
)


class TestUserCreate:
    def test_accepts_a_username_and_password(self):
        assert UserCreate(username="kim", password="password123").username == "kim"

    def test_rejects_a_password_below_the_policy_floor(self):
        with pytest.raises(ValidationError):
            UserCreate(username="kim", password="short")

    def test_rejects_a_blank_username(self):
        with pytest.raises(ValidationError):
            UserCreate(username="   ", password="password123")

    @pytest.mark.parametrize(
        "payload", [{"username": "kim"}, {"password": "password123"}, {}]
    )
    def test_both_fields_are_required(self, payload):
        with pytest.raises(ValidationError):
            UserCreate(**payload)


class TestLoginRequest:
    """Login deliberately does NOT apply the registration password policy."""

    def test_accepts_a_password_shorter_than_the_registration_floor(self):
        # Accounts predating the policy have short passwords. Enforcing the
        # floor here would lock those members out of their own library.
        assert LoginRequest(username="kim", password="old").password == "old"

    def test_still_rejects_an_empty_password(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="kim", password="")


class TestBookCreate:
    def test_title_is_the_only_required_field(self):
        book = BookCreate(title="Just a Title")
        assert book.author is None
        assert book.is_private is False

    def test_missing_title_is_rejected(self):
        with pytest.raises(ValidationError):
            BookCreate(author="No Title")  # type: ignore[call-arg]  # omission is the point

    def test_year_is_coerced_from_a_numeric_string(self):
        assert BookCreate(title="x", year="1925").year == 1925

    def test_a_non_numeric_year_is_rejected(self):
        with pytest.raises(ValidationError):
            BookCreate(title="x", year="nineteen twenty five")

    def test_an_http_cover_is_upgraded(self):
        book = BookCreate(title="x", cover_url="http://books.google.com/c.jpg")
        assert book.cover_url == "https://books.google.com/c.jpg"

    def test_an_uploaded_cover_path_is_accepted(self):
        assert BookCreate(title="x", cover_url="/covers/1.jpg").cover_url == "/covers/1.jpg"

    def test_a_script_url_is_rejected(self):
        """This is the one schema a member supplies a cover URL through, and
        the value reaches an `<img src>`."""
        with pytest.raises(ValidationError):
            BookCreate(title="x", cover_url="javascript:alert(1)")

    def test_a_scheme_relative_url_is_rejected(self):
        with pytest.raises(ValidationError):
            BookCreate(title="x", cover_url="//evil.invalid/x.jpg")

    def test_a_data_url_is_rejected(self):
        with pytest.raises(ValidationError):
            BookCreate(title="x", cover_url="data:image/svg+xml,<svg/>")


class TestBookStatusUpdate:
    @pytest.mark.parametrize("status", ["unread", "reading", "read"])
    def test_accepts_the_three_known_statuses(self, status):
        assert BookStatusUpdate(status=status).status == status

    @pytest.mark.parametrize("status", ["Read", "READ", "abandoned", "", "dnf"])
    def test_rejects_anything_else(self, status):
        """Casing matters: the column stores the lowercase form."""
        with pytest.raises(ValidationError):
            BookStatusUpdate(status=status)


class TestBookOut:
    def test_defaults_leave_the_optional_relations_empty(self):
        book = BookOut(
            id=1,
            isbn=None,
            title="t",
            subtitle=None,
            author=None,
            publisher=None,
            year=None,
            description=None,
            cover_url=None,
            added_at="2026-01-01T00:00:00",
        )
        assert book.tags == []
        assert book.active_loan is None
        # A book nobody has touched has no user_books row, and absence means
        # unread, so the default is the value, not None.
        assert book.my_status is ReadStatus.UNREAD

    def test_the_forward_reference_to_loanout_is_resolved(self):
        """BookOut references LoanOut before it is defined; model_rebuild() at
        the bottom of schemas.py is what makes that work. Without it, building
        the schema raises PydanticUndefinedAnnotation."""
        schema = BookOut.model_json_schema()
        assert "LoanOut" in schema["$defs"]
        assert "active_loan" in schema["$defs"]["BookOut"]["properties"]


class TestSmallSchemas:
    def test_note_create_requires_content(self):
        with pytest.raises(ValidationError):
            NoteCreate()  # type: ignore[call-arg]  # omission is the point

    def test_note_content_may_not_be_empty(self):
        """An empty note used to be accepted, then rendered as a blank card
        indistinguishable from a rendering bug."""
        with pytest.raises(ValidationError):
            NoteCreate(content="")


class TestLoanCreate:
    """Exactly one borrower. The database says the same thing; this layer is
    what turns a violation into a 422 naming the field rather than a 500.
    """

    def test_a_member_alone_is_valid(self):
        assert LoanCreate(book_id=1, loaned_to_user_id=2).loaned_to_name is None

    def test_a_name_alone_is_valid(self):
        assert LoanCreate(book_id=1, loaned_to_name="Ada").loaned_to_user_id is None

    def test_both_is_rejected(self):
        with pytest.raises(ValidationError):
            LoanCreate(book_id=1, loaned_to_user_id=2, loaned_to_name="Ada")

    def test_neither_is_rejected(self):
        with pytest.raises(ValidationError):
            LoanCreate(book_id=1)

    def test_a_whitespace_name_counts_as_no_name(self):
        with pytest.raises(ValidationError):
            LoanCreate(book_id=1, loaned_to_name="   ")

    def test_a_name_is_trimmed(self):
        assert LoanCreate(book_id=1, loaned_to_name="  Ada  ").loaned_to_name == "Ada"

    def test_an_overlong_name_is_rejected(self):
        with pytest.raises(ValidationError):
            LoanCreate(book_id=1, loaned_to_name="x" * 121)
