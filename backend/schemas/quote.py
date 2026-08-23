from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from models import QUOTE_NOTE_MAX, QUOTE_TEXT_MAX
from schemas.progress import MAX_PAGE
from schemas.user import UserOut


class QuoteCreate(BaseModel):
    """A passage somebody copied out of a book.

    `text` is the excerpt and nothing else. `note` is what the member wants to
    say about it, and it is a separate field so the excerpt stays a faithful
    transcription: fold the two together and the one string in this app that is
    supposed to be verbatim is where people put their own words.

    Both are bounded, and `text` more tightly than `NoteCreate.content`: see
    `models.QUOTE_TEXT_MAX`.
    """

    text: str = Field(min_length=1, max_length=QUOTE_TEXT_MAX)
    #: The page it is on, or absent. Bounded at both ends: a page number is an
    #: integer arriving from outside, and `ge=1` is not decoration either, since
    #: a book has no page zero and `ck_quotes_page_bounds` refuses one.
    page: int | None = Field(default=None, ge=1, le=MAX_PAGE)
    note: str | None = Field(default=None, max_length=QUOTE_NOTE_MAX)

    @field_validator("text")
    @classmethod
    def _an_excerpt_is_not_whitespace(cls, value: str) -> str:
        """Trim the ends, and refuse a passage that is only spaces.

        Three spaces pass `min_length=1` and then render as a blank card nobody
        can tell from a rendering fault, which is the defect `NoteCreate`
        documents its own `min_length` for. **Inner** whitespace is left alone,
        unlike `CollectionCreate.tidy`: a quote is often several lines and
        collapsing them would rewrite the passage.
        """
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A quote needs some text.")
        return cleaned

    @field_validator("note")
    @classmethod
    def _a_blank_remark_is_no_remark(cls, value: str | None) -> str | None:
        """Absent and empty are one state, so only one of them is stored.

        Otherwise the client has to treat `null` and `""` as the same thing at
        every call site that renders one, and eventually one of them will not.
        """
        cleaned = (value or "").strip()
        return cleaned or None


class QuoteOut(BaseModel):
    """One saved passage.

    `book_id` is here for the same reason `NoteOut` carries it, and it earns
    its place twice over in the cross-book listing, which is a flat list of
    quotes from many books.
    """

    id: int
    book_id: int
    user_id: int
    text: str
    page: int | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    author: UserOut | None = None
    model_config = {"from_attributes": True}


class QuoteWithBookOut(QuoteOut):
    """A quote plus enough of its book to render a row without a second fetch.

    Three scalars rather than a nested `BookOut`. `BookOut` carries the tags,
    the adder, the active loan and the caller's own reading state, which is
    work per row to render a title and a cover on a list whose rows are quotes.
    The book id is already on the row, so anybody wanting the rest follows it.
    """

    book_title: str
    book_author: str | None = None
    book_cover_url: str | None = None
