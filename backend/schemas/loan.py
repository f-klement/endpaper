from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from schemas.user import UserOut

if TYPE_CHECKING:
    # See the note in book.py: these two modules reference each other, the
    # unquoted annotation relies on PEP 649 deferred evaluation, and
    # model_rebuild() in __init__ is what resolves it.
    from schemas.book import BookOut


class LoanCreate(BaseModel):
    book_id: int
    loaned_to_user_id: int
    # Optional. Most family lending has no deadline, and demanding one would
    # make the common case worse to serve the rare one.
    due_at: datetime | None = None


class LoanOut(BaseModel):
    id: int
    book_id: int
    loaned_to_user_id: int
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
