"""Patrons: the admin's register of borrowers who are not members.

**Every route here is admin only, and the gate is on the router**, not on each
handler, so a route added to this file later cannot forget it. The gate runs
before the lookup, so a member asking about an id that does not exist is
answered 403 exactly as for one that does, and learns nothing about which ids
are taken. `models.Patron` says why this record is held to that.

**The search needs a term and returns a capped list**, never the register
whole: a search is how staff find the person in front of them.

**Every record carries the patron's open loans** (owner, 2026-11-20), so the
desk can see what somebody holds. `_records` fills them, read through
`Loans.seen_by` the admin, so a loan over a Book the admin may not see stays
off the record like everywhere else.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

import patrons
from auth import require_admin
from dependencies import DbSession, RowId
from lending import Loans
from models import Book, Patron, User
from refusals import refuses
from schemas import PatronCreate, PatronLoanOut, PatronOut, PatronSearch, PatronUpdate
from shelf import Shelf

router = APIRouter(prefix="/api/patrons", tags=["patrons"], dependencies=[Depends(require_admin)])


@refuses(status.HTTP_404_NOT_FOUND)
def _patron(patron_id: RowId, db: DbSession) -> Patron:
    """The patron with this id, or a 404. Reached only past the admin gate."""
    patron = db.get(Patron, patron_id)
    if patron is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patron not found.")
    return patron


PatronById = Annotated[Patron, Depends(_patron)]
#: The admin the router's gate already resolved; FastAPI caches the dependency,
#: so naming it again costs nothing.
Admin = Annotated[User, Depends(require_admin)]


def _records(db: Session, admin: User, rows: list[Patron]) -> list[PatronOut]:
    """These patrons' records with the loans each still holds, in two statements for them all."""
    held = Loans.seen_by(db, admin.id).open().to_patrons([row.id for row in rows])
    book_ids = {loan.book_id for loans in held.values() for loan in loans}
    titles = {
        book.id: book.title
        for book in Shelf.seen_by(db, admin.id).where(Book.id.in_(book_ids)).select(Book.id, Book.title)
    }
    records = [PatronOut.model_validate(row) for row in rows]
    for record in records:
        record.open_loans = [
            PatronLoanOut(
                id=loan.id,
                book_id=loan.book_id,
                # Indexed, not `.get`: `Loans.seen_by` is rooted at the same
                # Shelf, so every loan's book is here. A miss is a scope that
                # drifted, and a 500 says so where `.get` would list a titleless loan.
                title=titles[loan.book_id],
                loaned_at=loan.loaned_at,
                due_at=loan.due_at,
            )
            for loan in held[record.id]
        ]
    return records


def _refuse_a_taken_card(db: Session, card_number: str, other_than: int | None = None) -> None:
    """A 409 naming the field, where another patron already carries the number."""
    if patrons.card_number_taken(db, card_number, other_than=other_than):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Another patron already carries this card number."
        )


@router.post("/search", response_model=list[PatronOut])
def search_patrons(search: PatronSearch, db: DbSession, admin: Admin) -> list[PatronOut]:
    """The patrons whose name, email or card number contains the term, by name.

    A required term and a capped page, so no single request lists the register.
    A term blank once stripped is refused rather than matching everybody.

    **A POST with the term in its body**, not a GET with it in the query: a
    reverse proxy and a server both log a request line with its query, and a
    log keeps a name where `patrons.erase` cannot reach it.
    """
    return _records(db, admin, patrons.search(db, search.q, search.limit))


@router.post("", response_model=PatronOut, status_code=status.HTTP_201_CREATED)
def create_patron(payload: PatronCreate, db: DbSession, admin: Admin) -> PatronOut:
    """Register a patron. A card number another patron carries is a 409."""
    _refuse_a_taken_card(db, payload.card_number)
    patron = Patron(**payload.model_dump())
    db.add(patron)
    db.commit()
    db.refresh(patron)
    return _records(db, admin, [patron])[0]


@router.get("/{patron_id}", response_model=PatronOut)
def get_patron(patron: PatronById, db: DbSession, admin: Admin) -> PatronOut:
    """One patron's whole record, with the books they have out."""
    return _records(db, admin, [patron])[0]


@router.patch("/{patron_id}", response_model=PatronOut)
def update_patron(patron: PatronById, payload: PatronUpdate, db: DbSession, admin: Admin) -> PatronOut:
    """Change the fields sent; null clears an optional one. A taken card number is a 409."""
    changes = payload.model_dump(exclude_unset=True)
    if "card_number" in changes:
        _refuse_a_taken_card(db, changes["card_number"], other_than=patron.id)
    for field, value in changes.items():
        setattr(patron, field, value)
    db.commit()
    db.refresh(patron)
    return _records(db, admin, [patron])[0]


@router.delete("/{patron_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patron(patron: PatronById, db: DbSession) -> Response:
    """Erase a patron: their record goes, and every loan they had keeps its dates and loses their name.

    `patrons.erase`, the one erasure, so this and any bulk erasure cannot differ.
    """
    patrons.erase(db, [patron.id], datetime.now(UTC).replace(tzinfo=None))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
