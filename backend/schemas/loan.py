from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from models import names_exactly_one_borrower
from schemas.common import RowIdField
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
    book_id: RowIdField
    #: A member of the library...
    loaned_to_user_id: RowIdField | None = None
    #: ...or somebody with no account at all. Exactly one of the two.
    loaned_to_name: str | None = Field(default=None, max_length=MAX_BORROWER_NAME)
    # Optional. Most library lending has no deadline, and demanding one would
    # make the common case worse to serve the rare one.
    due_at: datetime | None = None

    #: "Yes, I know, lend it anyway."
    #:
    #: The only way past a book marked `lending = never`. Without it that book
    #: is a 409 rather than a loan. It is a field on the request and not a
    #: separate endpoint because it changes nothing about the loan that is
    #: created: the same row, reached by an extra deliberate step.
    #:
    #: Deliberately **not** stored. It says something about one request, not
    #: about the loan, and a library that lends a never-lent book to a
    #: sibling has not changed its mind about lending it to anybody else.
    acknowledge_not_lendable: bool = False

    @model_validator(mode="after")
    def _exactly_one_borrower(self) -> LoanCreate:
        """Both or neither is a 422, never a loan nobody can be asked about.

        **The rule itself is `models.names_exactly_one_borrower`, called rather
        than restated.** The database says the same thing through
        `models.ONE_BORROWER_SQL`, which is where that constraint's own text
        comes from. This layer exists so the caller gets a 422 naming the field
        rather than a 500 from a constraint violation, which is a different job
        from deciding what the rule is.

        **The strip happens before the question, not after**, because the
        predicate reads `''` the way SQL does: a value, and therefore a second
        borrower beside a member id. Normalising first is what turns a member
        plus an empty name into a member plus no name, which is what the column
        holds and what this route has always accepted. Asking first and
        normalising after would refuse it.

        **`strip()` here and `strip(" ")` in the predicate, deliberately.** This
        line decides what is fit to store and a name of one tab identifies
        nobody; the predicate answers what the constraint will accept, and
        SQLite's `trim()` strips spaces alone. So this layer is the stricter of
        the two on purpose, and a tab reaches the column only through a writer
        that does not come this way.
        """
        self.loaned_to_name = (self.loaned_to_name or "").strip() or None
        if not names_exactly_one_borrower(self.loaned_to_user_id, self.loaned_to_name):
            raise ValueError(
                "Name exactly one borrower: either loaned_to_user_id or loaned_to_name."
            )
        return self


class LoanOut(BaseModel):
    id: int
    book_id: int
    # Exactly one of these two is set, by `models.names_exactly_one_borrower`,
    # which is the one place that rule is spelled. `loaned_to` is the member's
    # full record and is None for an external borrower, whose name is all there
    # is.
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
    #: How many whole days past the deadline, and 0 when there is none.
    #:
    #: Read together with `is_overdue`, which is what tells 0 meaning "not
    #: overdue" apart from 0 meaning "overdue since this morning". A nullable
    #: field would have moved that same check into every caller and into the
    #: generated client's types for no gain.
    days_overdue: int = Field(default=0, ge=0)
    #: How long the book has been away, in whole days, stopping at the return.
    #:
    #: The one number that is meaningful for every loan: most lending here has
    #: no deadline, so a household reading only `days_overdue` has nothing to
    #: go on. Both come from `lending`, which is the only place either is
    #: computed.
    days_out: int = Field(default=0, ge=0)
    book: BookOut | None = None
    loaned_to: UserOut | None = None
    loaned_by: UserOut | None = None
    model_config = {"from_attributes": True}


class MyOverdueOut(BaseModel):
    """What the in app reminder tells one member, which is a number.

    **A count and no titles, and that is a design decision rather than a
    shortcut.** The banner it feeds says how many and links onward, which is the
    shape `UnconfirmedBanner` already uses on the same page. Titles would put
    catalogue content, including the reader's own private books, into a second
    response for no gain: the list one click away already renders them, already
    through the Shelf, and already knows how to page.

    **The list is `GET /api/loans/overdue`, not the loans list.** Both were once
    called the same thing here, and they are two different sets: only the first
    applies `overdue_for_viewer`, which is what this number is counted with.

    `enabled` is here so a household that switched the channel off sees nothing
    rather than a banner it cannot explain, and so the frontend does not have to
    read the admin-only settings record to find out.
    """

    enabled: bool
    count: int = Field(default=0, ge=0)
