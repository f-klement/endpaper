from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from models import BORROWER_NAME_MAX, names_exactly_one_borrower
from schemas.common import RowIdField, UtcDateTime, UtcDateTimeIn
from schemas.patron import LoanPatronOut
from schemas.user import UserOut

if TYPE_CHECKING:
    # See the note in book.py: these two modules reference each other, the
    # unquoted annotation relies on PEP 649 deferred evaluation, and
    # model_rebuild() in __init__ is what resolves it.
    from schemas.book import BookColumns


class LoanCreate(BaseModel):
    book_id: RowIdField
    #: A member of the library...
    loaned_to_user_id: RowIdField | None = None
    #: ...or somebody with no account at all...
    loaned_to_name: str | None = Field(default=None, max_length=BORROWER_NAME_MAX)
    #: ...or a registered patron. Exactly one of the three. Naming one is an
    #: admin's act alone, since the id leads to a person's contact details:
    #: `routers/loans.py::_refuse_an_unknown_borrower`.
    loaned_to_patron_id: RowIdField | None = None
    # Optional. Most library lending has no deadline, and demanding one would
    # make the common case worse to serve the rare one.
    due_at: UtcDateTimeIn | None = None

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
        if not names_exactly_one_borrower(
            self.loaned_to_user_id, self.loaned_to_name, patron_id=self.loaned_to_patron_id
        ):
            raise ValueError(
                "Name exactly one borrower: loaned_to_user_id, loaned_to_name or loaned_to_patron_id."
            )
        return self


class LoanOut(BaseModel):
    id: int
    book_id: int
    # At most one of these two is set: a loan to a patron, or one whose borrower
    # was erased, sets neither. `models.ONE_BORROWER_SQL` is the one place that
    # rule is spelled. `loaned_to` is the member's full record and is None for
    # an external borrower, whose name is all there is.
    loaned_to_user_id: int | None
    loaned_to_name: str | None = None
    #: Read off the row and never served: `to_patron` is what leaves.
    loaned_to_patron_id: int | None = Field(default=None, exclude=True)
    #: Set by `_says_whether_a_patron_has_it` and never by a caller. A patron
    #: is an admin's to read (`models.Patron`), and every member who sees a
    #: book reads its loan, hence a flag rather than the id.
    #:
    #: **A plain field and not a `computed_field`**, which pydantic marks
    #: `readOnly` in the schema; `frontend/tests/committedSchema.ts` refuses a
    #: keyword no reader of the schema models, and this one says nothing a
    #: reader needs. `model_config` below is what keeps it `required`.
    to_patron: bool = Field(
        default=False,
        description=(
            "Whether the borrower is a registered patron. A flag and not the id, so a "
            "member learns that a patron has the book and never which one. Without it "
            "a patron's loan and an erased borrower's would read alike, both naming nobody."
        ),
    )
    #: Who the patron is, for an admin alone and None for everyone else (owner,
    #: 2026-11-20). Filled per viewer by `serialisation.loan_patron`, never off
    #: the row, so a route that forgets it serves nobody's name rather than
    #: somebody's.
    patron: LoanPatronOut | None = None
    loaned_by_user_id: int
    loaned_at: UtcDateTime
    # None while the book is still out. This is what marks a loan "active";
    # there is at most one such row per book.
    returned_at: UtcDateTime | None
    # Optional, and only meaningful while the loan is open. `is_overdue` is
    # computed rather than stored: a stored flag would be wrong from the moment
    # the deadline passed until something wrote to the row.
    due_at: UtcDateTime | None = None
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
    #: The book this loan is of, when the caller asked for it.
    #:
    #: **`BookColumns`, not `BookOut`.** A loan payload has no viewer to answer
    #: for, and this was the wider type: `LoanOut.model_validate(loan)` builds
    #: the nested book off the ORM relationship, which cannot answer any of the
    #: twelve per viewer fields, so it took their defaults and every single loan
    #: route served a book reading `my_status: unread`, `copy_count: 1` and an
    #: empty `discuss_with` whoever asked. Nothing was red, because a default
    #: validates.
    #:
    #: The list route did not have that defect, and the way it avoided it is the
    #: argument for this type rather than against it: it ran every book on the
    #: page through `books_to_out` a second time, eight statements, to fill
    #: twelve fields no client reads. The only reader of this object takes
    #: `title`, `author` and `cover_url`.
    #:
    #: `BookOut` cannot be built this way at all now: its per viewer half is
    #: required and `BookOut.seen_by` is the one place it is supplied.
    book: BookColumns | None = None
    loaned_to: UserOut | None = None
    loaned_by: UserOut | None = None
    #: `json_schema_serialization_defaults_required`: the response schema marks
    #: every defaulted field required, which is the truth of a response, since
    #: the server always sends each one. Without it `to_patron` reaches the
    #: client typed optional, and a fixture or a component that omits it type
    #: checks and renders "Loaned to " with nobody after it.
    model_config = {"from_attributes": True, "json_schema_serialization_defaults_required": True}

    @model_validator(mode="after")
    def _says_whether_a_patron_has_it(self) -> LoanOut:
        """`to_patron` off the row's patron id, so no construction site can disagree with it."""
        self.to_patron = self.loaned_to_patron_id is not None
        return self


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
