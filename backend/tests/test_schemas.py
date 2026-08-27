"""Tests for backend/schemas.py: the Pydantic request/response contracts."""

from collections.abc import Iterable
from typing import Annotated, Any, Optional, get_args

import pytest
from pydantic import BaseModel, BeforeValidator, ValidationError

from enums import ReadStatus, TagCategory, TagKey
from schemas import (
    BookCreate,
    BookOut,
    BookStatusUpdate,
    LoanCreate,
    LoginRequest,
    NoteCreate,
    QuoteCreate,
    TagOut,
    TagStat,
    UserCreate,
    known_key,
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


def _unguarded(models: Iterable[Any]) -> list[str]:
    """Every field naming a `TagKey` that is not carrying `known_key`.

    The rule itself, as a function, so that the test asserting it is clean and
    the test proving it can fail run the identical code over different input. A
    guard whose self-test reimplements it proves nothing about the guard.

    **Both clauses have been wrong once, and both times the failure was passing
    clean**, which is the shape nobody notices. The annotation test was
    `annotation is TagKey | None`, which is False against an identical
    annotation because `TagKey | None` builds a fresh `UnionType` on every
    evaluation. The metadata test asked whether *a* before-validator existed,
    which a model bringing its own passes while still raising on the value this
    whole class is named for. Hence `entry.func is known_key`: the rule, not the
    shape of the rule.
    """
    return sorted(
        f"{model.__name__}.{name}"
        for model in models
        if isinstance(model, type) and issubclass(model, BaseModel)
        for name, field in model.model_fields.items()
        if TagKey in get_args(field.annotation) or field.annotation is TagKey
        if not any(
            isinstance(entry, BeforeValidator) and entry.func is known_key
            for entry in field.metadata
        )
    )


class TestEveryModelCarryingATagKeyAgreesAboutAnUnknownOne:
    """One rule, and it is a type rather than a habit.

    `known_key` exists because the tag list is one response for the whole
    vocabulary, drawn on nearly every page, so refusing a key a newer image
    wrote would take the page down over one translation. `TagStat` shipped as
    the bare enum and therefore **raised** where `TagOut` forgot: the same
    library, two answers, depending on which model the screen happened to draw.
    Both now annotate `KnownTagKey`, and this is what stops a third model being
    added without it.
    """

    UNKNOWN = "quantum_gardening"

    def test_tag_out_forgets_it(self):
        tag = TagOut(id=1, name="Computing", category=TagCategory.GENRE, key=self.UNKNOWN)
        assert tag.key is None

    def test_tag_stat_forgets_it_too(self):
        row = TagStat(name="Computing", category=TagCategory.GENRE, key=self.UNKNOWN, count=1)
        assert row.key is None

    def test_a_key_they_both_know_survives(self):
        assert TagOut(id=1, name="Computing", category=TagCategory.GENRE, key="computing").key
        assert TagStat(name="Computing", category=TagCategory.GENRE, key="computing", count=1).key

    def test_every_model_naming_a_tag_key_uses_the_shared_rule(self):
        """The third model, before it exists.

        One declaring the key itself would pass every test above, because those
        name the two models that exist, and would still raise on the value they
        exist to forgive.

        `AuthorOut.key` and `DuplicateGroup.key` are plain `str` and are not a
        tag key, so they are outside this by annotation rather than by name.
        """
        import schemas

        assert _unguarded(vars(schemas).values()) == []

    def test_the_rule_catches_every_way_of_writing_it_wrong(self):
        """The guard attacked rather than read, which is how both of its bugs
        were found.

        Five shapes, each a model somebody could plausibly write, and every one
        of them raises `ValidationError` on an unknown key, which is what makes
        being missed here a real hole rather than a technicality. The last is
        the shape an earlier version of this rule passed clean: reaching for
        `Annotated` and bringing a validator that is not the rule.
        """

        class Bare(BaseModel):
            key: TagKey = TagKey.FICTION

        class Nullable(BaseModel):
            key: TagKey | None = None

        class Optionally(BaseModel):
            key: Optional[TagKey] = None  # noqa: UP045  (the point is the spelling)

        class Annotated_(BaseModel):
            key: Annotated[TagKey | None, "a note, not a rule"] = None

        class OwnValidator(BaseModel):
            key: Annotated[TagKey | None, BeforeValidator(lambda value: value)] = None

        evasions = [Bare, Nullable, Optionally, Annotated_, OwnValidator]

        assert _unguarded(evasions) == [
            "Annotated_.key",
            "Bare.key",
            "Nullable.key",
            "Optionally.key",
            "OwnValidator.key",
        ]

        # And each of them really does raise, so the guard is not reporting
        # models that would have been fine.
        for model in evasions:
            with pytest.raises(ValidationError):
                model(key="quantum_gardening")

    def test_that_rule_is_watching_something(self):
        """A guard whose subject has been renamed passes by matching nothing."""
        import schemas

        guarded = [
            model.__name__
            for model in vars(schemas).values()
            if isinstance(model, type) and issubclass(model, BaseModel)
            for _name, field in model.model_fields.items()
            if TagKey in get_args(field.annotation)
        ]
        assert sorted(guarded) == ["TagOut", "TagStat"]


class TestSmallSchemas:
    def test_note_create_requires_content(self):
        with pytest.raises(ValidationError):
            NoteCreate()  # type: ignore[call-arg]  # omission is the point

    def test_note_content_may_not_be_empty(self):
        """An empty note used to be accepted, then rendered as a blank card
        indistinguishable from a rendering bug."""
        with pytest.raises(ValidationError):
            NoteCreate(content="")


class TestQuoteCreate:
    """The excerpt is verbatim, the remark is not, and both are bounded.

    The bounds are the interesting part. `text` takes 2,000 characters against
    `NoteCreate.content`'s 10,000, because this field holds somebody else's
    copyrighted words and because an unbounded free-text column reachable by
    any member is a stored denial of service, which this app has shipped once.
    """

    def test_it_requires_some_text(self):
        with pytest.raises(ValidationError):
            QuoteCreate()  # type: ignore[call-arg]  # omission is the point

    def test_whitespace_is_not_a_quote(self):
        with pytest.raises(ValidationError):
            QuoteCreate(text="   \n ")

    def test_the_excerpt_is_trimmed(self):
        assert QuoteCreate(text="  kept  ").text == "kept"

    def test_inner_whitespace_survives(self):
        """A quote is often several lines. Collapsing them, as
        `CollectionCreate.tidy` does for a name, would rewrite the passage."""
        assert QuoteCreate(text="one\n\ntwo").text == "one\n\ntwo"

    def test_a_blank_remark_becomes_no_remark(self):
        assert QuoteCreate(text="kept", note="  ").note is None

    @pytest.mark.parametrize("page", [0, -1, 100_001, 2**63])
    def test_a_page_outside_the_bounds(self, page):
        with pytest.raises(ValidationError):
            QuoteCreate(text="kept", page=page)

    def test_the_first_and_last_page_are_both_accepted(self):
        assert QuoteCreate(text="kept", page=1).page == 1
        assert QuoteCreate(text="kept", page=100_000).page == 100_000

    def test_the_excerpt_ceiling(self):
        assert QuoteCreate(text="x" * 2_000).text
        with pytest.raises(ValidationError):
            QuoteCreate(text="x" * 2_001)

    def test_the_remark_ceiling(self):
        assert QuoteCreate(text="kept", note="x" * 1_000).note
        with pytest.raises(ValidationError):
            QuoteCreate(text="kept", note="x" * 1_001)


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


class TestProgressCreate:
    """Exactly one unit per entry. The CHECK constraint says the same thing;
    this layer is what turns it into a 422 naming the fields."""

    def test_a_page_alone_is_valid(self):
        from schemas import ProgressCreate

        assert ProgressCreate(page=42).percent is None

    def test_a_percent_alone_is_valid(self):
        from schemas import ProgressCreate

        assert ProgressCreate(percent=40).page is None

    def test_both_is_rejected(self):
        from schemas import ProgressCreate

        with pytest.raises(ValidationError):
            ProgressCreate(page=42, percent=40)

    def test_neither_is_rejected(self):
        from schemas import ProgressCreate

        with pytest.raises(ValidationError):
            ProgressCreate(minutes=30)

    def test_page_zero_is_rejected(self):
        from schemas import ProgressCreate

        with pytest.raises(ValidationError):
            ProgressCreate(page=0)

    def test_a_percent_over_a_hundred_is_rejected(self):
        from schemas import ProgressCreate

        with pytest.raises(ValidationError):
            ProgressCreate(percent=101)

    def test_zero_minutes_is_rejected(self):
        from schemas import ProgressCreate

        with pytest.raises(ValidationError):
            ProgressCreate(page=10, minutes=0)


class TestSettingsUpdateWebhookUrl:
    def test_https_is_accepted(self):
        from schemas import SettingsUpdate

        assert (
            SettingsUpdate(overdue_webhook_url="https://box/hook").overdue_webhook_url
            == "https://box/hook"
        )

    def test_a_non_http_scheme_is_rejected(self):
        from schemas import SettingsUpdate

        with pytest.raises(ValidationError):
            SettingsUpdate(overdue_webhook_url="file:///etc/passwd")

    def test_an_empty_string_is_a_deliberate_clear(self):
        from schemas import SettingsUpdate

        assert SettingsUpdate(overdue_webhook_url="").overdue_webhook_url == ""
