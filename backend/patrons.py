"""Patrons: finding one, and erasing one so that no loan keeps their name.

`models.Patron` says what the record is and the three rules that bind on it.
This module is where two of them are kept: the search an admin runs, and the
erasure. Who may call either is `routers/patrons.py`, which takes
`require_admin` on every route; nothing here reads a caller.

**One erasure, whatever asked for it** (owner, 2026-09-05). Deleting one
patron and any future bulk erasure, such as lapsed registrations, both call
`erase`, so there is one implementation to test rather than two that drift.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import CursorResult, delete, or_, select, update
from sqlalchemy.orm import Session

from models import Loan, Patron

#: The most rows one search returns. A search is how staff find the patron in
#: front of them, so a long list is a term that was too short; a cap also means
#: no single request can page the whole register out.
SEARCH_LIMIT_MAX: Final = 50

#: The LIKE escape character. SQLite has no default, so every pattern names it,
#: or a search for `50%` matches every card containing `50` (`shelf.py`,
#: `_searching`, states the same rule at its own site).
_LIKE_ESCAPE: Final = "\\"


def search(db: Session, term: str, limit: int) -> list[Patron]:
    """The patrons whose name, email or card number contains `term`, by name.

    Case insensitive on each engine's own rule, and `term` is matched as the
    characters it is: `%` and `_` are escaped rather than read as wildcards.
    """
    like = f"%{_escaped(term)}%"
    query = (
        select(Patron)
        .where(
            or_(
                Patron.name.ilike(like, escape=_LIKE_ESCAPE),
                Patron.email.ilike(like, escape=_LIKE_ESCAPE),
                Patron.card_number.ilike(like, escape=_LIKE_ESCAPE),
            )
        )
        .order_by(Patron.name, Patron.id)
        .limit(min(limit, SEARCH_LIMIT_MAX))
    )
    return list(db.scalars(query))


def _escaped(term: str) -> str:
    """`term` with LIKE's two wildcards and its escape character escaped."""
    for special in (_LIKE_ESCAPE, "%", "_"):
        term = term.replace(special, _LIKE_ESCAPE + special)
    return term


def card_number_taken(db: Session, card_number: str, *, other_than: int | None = None) -> bool:
    """Whether another patron already carries this card number.

    For a 409 that names the field. The unique index is what holds the rule
    against two requests racing; this only answers before it has to.
    """
    query = select(Patron.id).where(Patron.card_number == card_number)
    if other_than is not None:
        query = query.where(Patron.id != other_than)
    return db.scalar(query.limit(1)) is not None


def erase(db: Session, patron_ids: Collection[int], now: datetime) -> int:
    """Delete these patrons, taking each off every loan first. Returns the loans changed.

    **The loans stay, with their dates and their book**, and lose the borrower:
    `loaned_to_patron_id` is cleared and `borrower_anonymised_at` is stamped
    with `now`, naive UTC like every loan column. `ck_loans_one_borrower` admits
    a loan naming nobody only beside that stamp, so a loan cannot be left
    pointing at nobody by any other path, and the foreign key refuses deleting
    a patron a loan still names. An open loan is anonymised too: the book is
    still out, and the archive still needs to know it.

    Flushes and does not commit, so the caller decides the transaction and the
    two statements land together or not at all.
    """
    ids = sorted(set(patron_ids))
    if not ids:
        return 0
    # A DML statement's result is a cursor result; the session types it wider.
    anonymised = cast(
        CursorResult[Any],
        db.execute(
            update(Loan)
            .where(Loan.loaned_to_patron_id.in_(ids))
            .values(loaned_to_patron_id=None, borrower_anonymised_at=now)
            .execution_options(synchronize_session=False)
        ),
    )
    db.execute(delete(Patron).where(Patron.id.in_(ids)).execution_options(synchronize_session=False))
    db.expire_all()
    return anonymised.rowcount
