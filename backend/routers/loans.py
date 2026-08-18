from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from dependencies import CurrentUser, DbSession, Paging
from models import Book, Loan, User, visible_to
from schemas import LoanCreate, LoanOut, Page

router = APIRouter(prefix="/api/loans", tags=["loans"])


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
    query = db.query(Loan).join(Book, Loan.book_id == Book.id)

    # A loan of a book the caller cannot see would otherwise disclose its
    # title and who has it, straight through the loans list.
    query = query.filter(visible_to(current_user.id))

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
    loans = (
        query.options(
            joinedload(Loan.book), joinedload(Loan.loaned_to), joinedload(Loan.loaned_by)
        )
        .order_by(Loan.loaned_at.desc(), Loan.id.desc())
        .offset(paging.offset)
        .limit(paging.limit)
        .all()
    )

    return Page[LoanOut](
        items=[_to_out(loan) for loan in loans],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post("", response_model=LoanOut, status_code=status.HTTP_201_CREATED)
def create_loan(payload: LoanCreate, db: DbSession, current_user: CurrentUser) -> LoanOut:
    book = (
        db.query(Book)
        .filter(Book.id == payload.book_id, visible_to(current_user.id))
        .first()
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    borrower = db.get(User, payload.loaned_to_user_id)
    if borrower is None:
        raise HTTPException(status_code=404, detail="User not found")

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
        loaned_by_user_id=current_user.id,
        due_at=payload.due_at,
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return _loan_with_relations(loan.id, db)


@router.put("/{loan_id}/return", response_model=LoanOut)
def return_loan(loan_id: int, db: DbSession, current_user: CurrentUser) -> LoanOut:
    """Recording a return is a shelf action, not an ownership one, so any member
    may do it, for any book they can see."""
    loan = (
        db.query(Loan)
        .join(Book, Loan.book_id == Book.id)
        .filter(Loan.id == loan_id, visible_to(current_user.id))
        .first()
    )
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.returned_at is not None:
        raise HTTPException(status_code=400, detail="Loan already returned")

    loan.returned_at = datetime.now(UTC)
    db.commit()
    return _loan_with_relations(loan.id, db)
