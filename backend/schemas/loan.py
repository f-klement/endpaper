from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from schemas.user import UserOut

if TYPE_CHECKING:
    # See the note in book.py: these two modules reference each other, the
    # unquoted annotation relies on PEP 649 deferred evaluation, and
    # model_rebuild() in __init__ is what resolves it.
    from schemas.book import BookOut


#: Matches `loans.loaned_to_name` in the ORM. A longer name is a paste, not a
#: person.
MAX_BORROWER_NAME = 120


class LoanCreate(BaseModel):
    book_id: int
    #: A member of the household...
    loaned_to_user_id: int | None = None
    #: ...or somebody with no account at all. Exactly one of the two.
    loaned_to_name: str | None = Field(default=None, max_length=MAX_BORROWER_NAME)
    # Optional. Most household lending has no deadline, and demanding one would
    # make the common case worse to serve the rare one.
    due_at: datetime | None = None

    @model_validator(mode="after")
    def _exactly_one_borrower(self) -> LoanCreate:
        """Both or neither is a 422, never a loan nobody can be asked about.

        The database says the same thing (`ck_loans_one_borrower`). This layer
        exists so the caller gets a 422 naming the field rather than a 500 from
        a constraint violation.

        Whitespace is stripped first: a name of three spaces satisfies
        `IS NOT NULL` and identifies nobody.
        """
        name = (self.loaned_to_name or "").strip()
        if (self.loaned_to_user_id is not None) == bool(name):
            raise ValueError(
                "Name exactly one borrower: either loaned_to_user_id or loaned_to_name."
            )
        self.loaned_to_name = name or None
        return self


class LoanOut(BaseModel):
    id: int
    book_id: int
    # Exactly one of these two is set. `loaned_to` is the member's full record
    # and is None for an external borrower, whose name is all there is.
    loaned_to_user_id: int | None
    loaned_to_name: str | None = None
    loaned_by_user_id: int
    loaned_at: datetime
    # None while the book is still out. This is what marks a loan "active";
    # there is at most one such row per book.
    returned_at: datetime | None
    # Optional, and only meaningful while the loan is open. `is_overdue` is
    # computed rather than stored: a stored flag would be wrong from the moment
    # the deadline passed until something wrote to the row.
    due_at: datetime | None = None
    is_overdue: bool = False
    book: BookOut | None = None
    loaned_to: UserOut | None = None
    loaned_by: UserOut | None = None
    model_config = {"from_attributes": True}
