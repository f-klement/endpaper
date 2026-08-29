from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

import notifications
import settings_store
from auth import require_admin
from dependencies import CurrentUser, DbSession, Paging, RowId
from enums import LendingWillingness, SettingKey
from models import Book, Loan, User
from schemas import LoanCreate, LoanOut, MyOverdueOut, OverdueNotifyResult, Page
from serialisation import books_to_out
from shelf import Shelf

router = APIRouter(prefix="/api/loans", tags=["loans"])


def _to_out_many(loans: list[Loan], current_user: User, db: Session) -> list[LoanOut]:
    """Serialise a page of loans, with each book's per-member fields filled in.

    The nested `BookOut` used to come from a bare `model_validate`, so every
    book on the loans page reported `my_status: "unread"` and
    `active_loan: null` regardless of what the reader had actually done with
    it. Those two fields are computed per request by `books_to_out`, which is
    the only thing that knows how, so the books go through it here as well.
    """
    books = {loan.book.id: loan.book for loan in loans if loan.book}
    serialised = {
        out.id: out
        for out in books_to_out(list(books.values()), current_user, db)
    }

    results: list[LoanOut] = []
    for loan in loans:
        out = _to_out(loan)
        if loan.book is not None:
            out.book = serialised.get(loan.book.id)
        results.append(out)
    return results


def _to_out(loan: Loan) -> LoanOut:
    """Serialise a loan, computing `is_overdue` rather than reading it.

    A stored flag would be wrong from the moment the deadline passed until
    something happened to write to the row, which for a forgotten loan is
    exactly never. A returned loan is never overdue, however late it was: the
    field answers "chase this", not "was this late".
    """
    out = LoanOut.model_validate(loan)
    out.is_overdue = (
        loan.returned_at is None
        and loan.due_at is not None
        and loan.due_at < datetime.now(UTC).replace(tzinfo=None)
    )
    return out


def _loan_with_relations(loan_id: int, db: Session) -> LoanOut:
    loan = (
        db.query(Loan)
        .options(joinedload(Loan.book), joinedload(Loan.loaned_to), joinedload(Loan.loaned_by))
        .filter(Loan.id == loan_id)
        .first()
    )
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    return _to_out(loan)


@router.get("", response_model=Page[LoanOut])
def list_loans(
    db: DbSession,
    current_user: CurrentUser,
    paging: Paging,
    active_only: bool = True,
    overdue_only: bool = False,
) -> Page[LoanOut]:
    # Rooted at the shelf and joined outward to `loans`, so the privacy
    # predicate is on the query by construction. A loan of a book the caller
    # cannot see would otherwise disclose its title and who has it, straight
    # through the loans list.
    query = Shelf.seen_by(db, current_user.id).select(Loan).join(Loan, Loan.book_id == Book.id)

    if active_only:
        query = query.filter(Loan.returned_at.is_(None))

    if overdue_only:
        # Filtered in SQL rather than by serialising the whole list and
        # discarding most of it, so `total` and the paging stay honest.
        # Implies active: a returned loan is closed, whenever it came back.
        query = query.filter(
            Loan.returned_at.is_(None),
            Loan.due_at.isnot(None),
            Loan.due_at < datetime.now(UTC).replace(tzinfo=None),
        )

    total = query.with_entities(func.count(Loan.id)).order_by(None).scalar() or 0

    # SQLite's CURRENT_TIMESTAMP has only second resolution, so loans recorded
    # in the same second tie on loaned_at. id breaks the tie and keeps both the
    # ordering and the paging stable.
    # The book's own relationships are loaded too. `LoanOut.book` is a
    # `BookOut`, which serialises the adding member, so joinedloading only
    # `Loan.book` left this endpoint at 53 statements for 25 loans: the exact
    # N+1 `docs/architecture.md` says was eliminated, surviving here.
    #
    # Three options, and each is here because dropping it alone was measured.
    # Over pages of 3 and 10 loans, with a distinct adder, lender and borrower
    # per loan, on 2026-08-29:
    #
    #     .joinedload(Book.added_by)   +3 and +10 on any page
    #     joinedload(Loan.loaned_to)   +3 and +10 on a page holding returned loans
    #     joinedload(Loan.loaned_by)   +3 and +10 on a page holding returned loans
    #
    # **The first row is the chain link, not the whole option, and the two cost
    # different amounts.** Dropping `.joinedload(Book.added_by)` and keeping
    # `joinedload(Loan.book)` lazy loads one member per loan: measured 14 for 3
    # and 21 for 10 against a baseline of 11, so +3 and +10. Dropping the entire
    # first option lazy loads the Book as well, two per loan, which is +6 and
    # +20. Both are real; they are answers to different questions. Written as a
    # bare `Book.added_by` this table did not say which, and two seats read it
    # two ways on the same afternoon.
    #
    # The last two are free while `active_only` holds, because `books_to_out`
    # fetches every ACTIVE loan over the page's books with both users
    # joinedloaded, and those are the same rows. `active_only=false` is the
    # page they are for: a returned loan is in no such fetch, so without them
    # `_to_out` lazy loads two users per row.
    #
    # A fourth, `joinedload(Loan.book).selectinload(Book.tags)`, was deleted in
    # the same measurement. `books_to_out` selectinloads `Book.tags` for every
    # book on the page whatever its shape, so the option spent one SELECT per
    # request repopulating a populated collection: measured at -1 statement in
    # both routes at both lengths. Nothing failed when it was deleted, which is
    # why the tests over these two routes now build a page whose every
    # relationship names a different row.
    loans = (
        query.options(
            joinedload(Loan.book).joinedload(Book.added_by),
            joinedload(Loan.loaned_to),
            joinedload(Loan.loaned_by),
        )
        .order_by(Loan.loaned_at.desc(), Loan.id.desc())
        .offset(paging.offset)
        .limit(paging.limit)
        .all()
    )

    return Page[LoanOut](
        items=_to_out_many(loans, current_user, db),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


#: The `detail.code` on the 409 a never-lent book answers with.
#:
#: A code beside the sentence rather than the sentence alone, because the
#: client has to *branch* on this one: it puts a confirmation in front of the
#: lend button and resends. Matching on the prose would break the moment the
#: prose was reworded or translated, and the two 409s this endpoint raises
#: (already out, never lent) mean entirely different things to the reader.
NOT_LENDABLE: Final = "not_lendable"


@router.post("", response_model=LoanOut, status_code=status.HTTP_201_CREATED)
def create_loan(payload: LoanCreate, db: DbSession, current_user: CurrentUser) -> LoanOut:
    """Record that a book has gone out.

    **A book marked `lending = never` is refused once, not forbidden.** Neither
    extreme is right here. Allowing it silently makes the field decorative, and
    a library that took the trouble to mark a copy would find the app had
    quietly ignored it. Forbidding it outright is worse: the same library
    lends that book to a sibling anyway, and an app that will not let them
    record what actually happened gets a loan kept in somebody's head instead,
    which is the one thing this table exists to replace.

    So the refusal costs one extra deliberate step: a 409 carrying
    `code: not_lendable`, then the same request again with
    `acknowledge_not_lendable`. The other two willingness values are not
    checked at all. `in_use` means "come back later", which is a conversation
    between two people rather than a rule, and `happy` is a yes.

    The flag is not stored: see `LoanCreate.acknowledge_not_lendable`.
    """
    book = Shelf.seen_by(db, current_user.id).where(Book.id == payload.book_id).first()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # Only a member has to exist. An external borrower is a name, checked by
    # `LoanCreate` (exactly one of the two is set) and by the CHECK constraint
    # behind it.
    if payload.loaned_to_user_id is not None and db.get(User, payload.loaned_to_user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")

    # A book the library said it does not lend. Refused once, then allowed:
    # see `_refuse_unless_acknowledged`.
    if (
        book.lending == LendingWillingness.NEVER
        and not payload.acknowledge_not_lendable
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "This book is marked as never lent. Send "
                    "acknowledge_not_lendable to lend it anyway."
                ),
                "code": NOT_LENDABLE,
            },
        )

    already_out = (
        db.query(Loan)
        .filter(Loan.book_id == payload.book_id, Loan.returned_at.is_(None))
        .first()
    )
    if already_out is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Book is already loaned out")

    loan = Loan(
        book_id=payload.book_id,
        loaned_to_user_id=payload.loaned_to_user_id,
        loaned_to_name=payload.loaned_to_name,
        loaned_by_user_id=current_user.id,
        due_at=payload.due_at,
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return _loan_with_relations(loan.id, db)


@router.get("/overdue", response_model=Page[LoanOut])
def list_overdue(db: DbSession, current_user: CurrentUser, paging: Paging) -> Page[LoanOut]:
    """The overdue loans themselves, for the page the banner links to (#102).

    **The same rule as the banner's count, because it is the same audience.**
    `notifications.overdue_for_viewer` is rooted at `Shelf.seen_by`, so a
    private book somebody else added cannot reach here, and `sees_every_loan`
    decides the rest: a member reads the loans they lent or borrowed, staff
    read every overdue loan on their shelf.

    **Not `list_loans(overdue_only=True)`, which is a wider set.** That one is
    rooted at the Shelf and stops there: it has no lender-or-borrower arm, so a
    member sees every overdue loan over a book they can see, housemates'
    included. Pointing this page at it would list more rows than the banner
    counted, which is the same fact disagreeing with itself on two screens.
    The loans page keeps that endpoint, because a loans list is a list of the
    household's loans by design.

    **Honours the in app channel's switch**, exactly as `my_overdue` does. That
    setting is spelled "show overdue loans in the app", and this page is what
    it shows; a page that went on listing them when the channel was off would
    make the switch a lie about half its surface. The loans page is not
    affected: a loan list is not the reminder channel.

    Declared **before** `/{loan_id}/return`, per the route-order rule: a literal
    first segment declared after a path parameter is a segment the parameter can
    swallow. `/overdue` and `/overdue/mine` cannot collide with each other,
    because they differ in segment count rather than in a parameter's value.

    Eager loading here and none in `overdue_for_viewer`, which is the seam that
    function's docstring describes: it hands out the query so the count caller
    can stay at one statement and no ORM objects, and a caller that renders
    titles adds the loads it needs.
    """
    if not settings_store.get_bool(db, SettingKey.OVERDUE_IN_APP_ENABLED):
        return Page[LoanOut](
            items=[], total=0, page=paging.page, page_size=paging.page_size
        )

    now = datetime.now(UTC).replace(tzinfo=None)
    query = notifications.overdue_for_viewer(db, current_user, now)
    # `order_by(None)` before counting: the query carries `due_at, id` for the
    # page below, and SQLite will not accept an ORDER BY over a bare COUNT.
    total = query.with_entities(func.count(Loan.id)).order_by(None).scalar() or 0

    # The same three options as `list_loans`, where the measurement behind them
    # is written down. `loaned_to` and `loaned_by` cost nothing here and cannot:
    # `overdue_for_viewer` returns only unreturned loans, so every row on this
    # page is already in the active loan fetch `books_to_out` makes. They stay
    # as the insurance that a change to that query does not arrive as an N+1,
    # and no test pins them, because there is nothing observable to pin.
    # `.joinedload(Book.added_by)` is pinned, at +3 and +10; dropping the whole
    # option, and so the Book with it, is +6 and +20.
    loans = (
        query.options(
            joinedload(Loan.book).joinedload(Book.added_by),
            joinedload(Loan.loaned_to),
            joinedload(Loan.loaned_by),
        )
        .offset(paging.offset)
        .limit(paging.limit)
        .all()
    )

    return Page[LoanOut](
        items=_to_out_many(loans, current_user, db),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/overdue/mine", response_model=MyOverdueOut)
def my_overdue(db: DbSession, current_user: CurrentUser) -> MyOverdueOut:
    """The in app reminder, for the member asking.

    #86. Every other channel needs something the household has to obtain first:
    a receiver they run, an SMTP account, a bot token. A household with none of
    those was told nothing at all, which is the problem the reminder feature was
    filed to solve. This is the one channel that works on a fresh install with
    nothing configured.

    Declared **before** `/{loan_id}/return`, per the route-order rule: a literal
    first segment declared after a path parameter is a segment the parameter can
    swallow.

    **Not admin only, and that is the point.** It is per member, and what each
    member may see is decided by `notifications.overdue_for_viewer`, which roots
    the query at `Shelf.seen_by`. A member reads the loans they are party to; an
    admin, and later a library's staff, read every overdue loan on their shelf.
    Neither arm can reach another member's private book, because the Shelf
    applies `visible_to` before either clause is added.

    A count and no titles. The banner it feeds says how many and links to
    `GET /api/loans/overdue`, which lists them **through this same function**.

    **It used to say the loans list, and that sentence was wrong on both
    halves.** The loans list is `list_loans`, which is rooted at the Shelf and
    applies no lender-or-borrower arm, so it is a wider set than this counts:
    for any non admin member the banner said one number and the screen it
    opened showed another. #102 moved the link and added the endpoint above,
    which is the one that shares this rule.
    """
    enabled = settings_store.get_bool(db, SettingKey.OVERDUE_IN_APP_ENABLED)
    if not enabled:
        return MyOverdueOut(enabled=False, count=0)
    now = datetime.now(UTC).replace(tzinfo=None)
    # `.count()`, not `len(...all())`. The query is handed out rather than the
    # rows precisely so this can be one statement and no ORM objects: against
    # 500 overdue loans the list form built 500 of them, on every library page
    # visit, to take their length.
    return MyOverdueOut(
        enabled=True,
        count=notifications.overdue_for_viewer(db, current_user, now).count(),
    )


@router.post("/overdue/notify", response_model=OverdueNotifyResult)
async def notify_overdue(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> OverdueNotifyResult:
    """Run the overdue digest now, and report what it sent.

    Declared **before** `/{loan_id}/return`, per the route-order rule: a
    literal first segment that comes after a path parameter is a segment the
    parameter can swallow. It does not today (the second segment differs, and
    so does the verb), and the ordering is what keeps that true when somebody
    adds `POST /{loan_id}/notify`.

    Admin only, for the same reason the settings behind it are: it posts
    catalogue content to a destination with no session behind it.

    This is what makes the feature testable by a person, and it is the endpoint
    an external cron would call instead of the in-process ticker. Running it by
    hand stamps `notified_at` exactly as a tick does, so a manual run also
    quiets the next scheduled one for the interval.
    """
    return OverdueNotifyResult(**await notifications.run_digest(db))


@router.put("/{loan_id}/return", response_model=LoanOut)
def return_loan(loan_id: RowId, db: DbSession, current_user: CurrentUser) -> LoanOut:
    """Recording a return is a shelf action, not an ownership one, so any member
    may do it, for any book they can see."""
    loan = (
        Shelf.seen_by(db, current_user.id)
        .select(Loan)
        .join(Loan, Loan.book_id == Book.id)
        .filter(Loan.id == loan_id)
        .first()
    )
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.returned_at is not None:
        raise HTTPException(status_code=400, detail="Loan already returned")

    loan.returned_at = datetime.now(UTC)
    db.commit()
    return _loan_with_relations(loan.id, db)
