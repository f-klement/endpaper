"""Tests for backend/patrons.py: the admin's search, and the one erasure."""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import patrons
from database import engine
from models import Book, Loan, Patron, User

ERASED_AT = datetime(2026, 11, 20, 9, 30)
LENT = datetime(2026, 3, 1, 10, 0)
DUE = datetime(2026, 3, 29, 10, 0)
RETURNED = datetime(2026, 3, 20, 16, 45)


@pytest.fixture
def lender(db) -> User:
    user = User(username="desk", password_hash="x")
    db.add(user)
    db.commit()
    return user


def _patron(db, card: str, name: str, email: str | None = None) -> Patron:
    patron = Patron(card_number=card, name=name, email=email)
    db.add(patron)
    db.commit()
    return patron


def _lend(db, lender: User, patron: Patron, *, returned: datetime | None = RETURNED) -> Loan:
    """A loan of a fresh book to `patron`, returned unless told otherwise."""
    book = Book(title=f"Lent to {patron.card_number}")
    db.add(book)
    db.flush()
    loan = Loan(
        book_id=book.id,
        loaned_to_patron_id=patron.id,
        loaned_by_user_id=lender.id,
        loaned_at=LENT,
        due_at=DUE,
        returned_at=returned,
    )
    db.add(loan)
    db.commit()
    return loan


class TestErase:
    def test_an_anonymised_loan_keeps_its_dates_and_loses_the_name(self, db, lender):
        patron = _patron(db, "C1", "Pat Lee")
        loan_id = _lend(db, lender, patron).id

        patrons.erase(db, [patron.id], ERASED_AT)
        db.commit()

        loan = db.get(Loan, loan_id)
        assert (loan.loaned_at, loan.due_at, loan.returned_at) == (LENT, DUE, RETURNED)
        assert (loan.loaned_to_patron_id, loan.loaned_to_user_id, loan.loaned_to_name) == (None, None, None)
        assert loan.borrower_anonymised_at == ERASED_AT

    def test_the_patron_row_is_gone(self, db, lender):
        patron = _patron(db, "C1", "Pat Lee")
        _lend(db, lender, patron)
        patron_id = patron.id

        patrons.erase(db, [patron_id], ERASED_AT)
        db.commit()

        assert db.get(Patron, patron_id) is None

    def test_an_open_loan_stays_open_and_is_anonymised(self, db, lender):
        """The book is still out, so the archive still needs to know it."""
        patron = _patron(db, "C1", "Pat Lee")
        loan_id = _lend(db, lender, patron, returned=None).id

        patrons.erase(db, [patron.id], ERASED_AT)
        db.commit()

        loan = db.get(Loan, loan_id)
        assert loan.returned_at is None
        assert loan.borrower_anonymised_at == ERASED_AT

    def test_another_patrons_loans_are_left_alone(self, db, lender):
        leaving = _patron(db, "C1", "Pat Lee")
        staying = _patron(db, "C2", "Sam Roe")
        _lend(db, lender, leaving)
        kept_id = _lend(db, lender, staying).id

        patrons.erase(db, [leaving.id], ERASED_AT)
        db.commit()

        kept = db.get(Loan, kept_id)
        assert (kept.loaned_to_patron_id, kept.borrower_anonymised_at) == (staying.id, None)
        assert db.get(Patron, staying.id) is not None

    def test_it_erases_several_at_once_and_counts_the_loans(self, db, lender):
        """The bulk path is the same function, not a second one."""
        first = _patron(db, "C1", "Pat Lee")
        second = _patron(db, "C2", "Sam Roe")
        _lend(db, lender, first)
        _lend(db, lender, first)
        _lend(db, lender, second)

        changed = patrons.erase(db, [first.id, second.id], ERASED_AT)
        db.commit()

        assert changed == 3
        assert db.query(Patron).count() == 0

    def test_nothing_named_is_nothing_done(self, db):
        _patron(db, "C1", "Pat Lee")

        assert patrons.erase(db, [], ERASED_AT) == 0
        assert db.query(Patron).count() == 1

    def test_a_delete_that_skips_it_is_refused_while_a_loan_names_the_patron(self, db, lender):
        """No `ondelete` on the foreign key, so no path leaves a loan pointing at nobody."""
        patron = _patron(db, "C1", "Pat Lee")
        _lend(db, lender, patron)

        db.delete(patron)
        with pytest.raises(IntegrityError):
            db.commit()


class TestAnErasedNameLeavesTheFile:
    @pytest.mark.sqlite_only(reason="reads the SQLite file")
    def test_the_name_is_not_in_the_file_after_a_checkpoint(self, db, lender):
        """`database.py` sets `secure_delete`; without it the row stays in the
        page's free space, and a copy of the volume still holds the name. The
        outcome, on whichever SQLite runs the suite; `test_database.py` holds
        the setting itself."""
        marker = b"Qzerasedpatron"
        name = marker.decode()
        patron = _patron(db, "C1", f"Pat {name}", email=f"{name}@example.org")
        _lend(db, lender, patron)
        assert marker in _the_checkpointed_file(), "the file never held the name, so its absence says nothing"

        patrons.erase(db, [patron.id], ERASED_AT)
        db.commit()

        assert marker not in _the_checkpointed_file()


def _the_checkpointed_file() -> bytes:
    """The database file once every committed page has left the WAL for it."""
    with engine.connect() as connection:
        busy = connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)")).first()
    assert busy is not None
    assert busy[0] == 0, "the checkpoint was blocked, so the file is not current"
    return Path(str(engine.url.database)).read_bytes()


class TestSearch:
    def test_it_matches_name_email_and_card_number(self, db):
        by_name = _patron(db, "C1", "Pat Lee")
        by_email = _patron(db, "C2", "Sam Roe", email="pat@example.org")
        by_card = _patron(db, "PAT9", "Kim Ode")
        _patron(db, "C4", "Ana Bo")

        found = {patron.id for patron in patrons.search(db, "pat", 20)}

        assert found == {by_name.id, by_email.id, by_card.id}

    def test_a_wildcard_is_matched_as_the_character_it_is(self, db):
        _patron(db, "C1", "Pat Lee")

        assert patrons.search(db, "%", 20) == []
        assert patrons.search(db, "_", 20) == []

    def test_the_limit_is_capped(self, db):
        for number in range(patrons.SEARCH_LIMIT_MAX + 1):
            db.add(Patron(card_number=f"C{number}", name="Pat"))
        db.commit()

        assert len(patrons.search(db, "Pat", 1000)) == patrons.SEARCH_LIMIT_MAX


class TestCardNumberTaken:
    def test_another_patrons_number_is_taken(self, db):
        _patron(db, "C1", "Pat Lee")

        assert patrons.card_number_taken(db, "C1")

    def test_a_patrons_own_number_is_not_taken_from_them(self, db):
        patron = _patron(db, "C1", "Pat Lee")

        assert not patrons.card_number_taken(db, "C1", other_than=patron.id)
