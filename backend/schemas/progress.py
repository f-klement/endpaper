from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from models import MAX_PAGE_NUMBER_IN_A_BOOK

#: A book with more pages than this is a typo. Re-exported from `models` rather
#: than restated: `ck_quotes_page_bounds` interpolates the same number into
#: SQL, and a CHECK that disagreed with a schema bound would answer 500 for
#: exactly the values between them.
MAX_PAGE = MAX_PAGE_NUMBER_IN_A_BOOK

#: A single sitting, in minutes. A day is the ceiling because anything past it
#: is a mistyped field rather than a long evening, and the number exists to
#: catch that rather than to adjudicate stamina.
MAX_MINUTES = 24 * 60


class ProgressCreate(BaseModel):
    """A position in a book, in exactly one unit.

    The database says the same thing (`ck_reading_progress_one_unit`). This
    layer exists so the caller gets a 422 naming the fields rather than a 500
    out of a constraint violation.
    """

    #: The page reached. For anything with pages.
    page: int | None = Field(default=None, ge=1, le=MAX_PAGE)
    #: 0 to 100, for an audiobook or a book whose page count nobody knows.
    percent: int | None = Field(default=None, ge=0, le=100)
    #: How long this sitting was. Optional, and independent of the unit.
    minutes: int | None = Field(default=None, ge=1, le=MAX_MINUTES)

    @model_validator(mode="after")
    def _exactly_one_unit(self) -> ProgressCreate:
        if (self.page is None) == (self.percent is None):
            raise ValueError("Give either page or percent, not both and not neither.")
        return self


class ProgressOut(BaseModel):
    """One recorded position.

    No derived percentage here, deliberately. It is a function of the book's
    `page_count`, which the client already holds, and recomputing it per row on
    the server would send the same fact twice with two chances to disagree.
    """

    id: int
    book_id: int
    recorded_at: datetime
    page: int | None = None
    percent: int | None = None
    minutes: int | None = None

    model_config = {"from_attributes": True}
