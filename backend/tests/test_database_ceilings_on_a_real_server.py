"""What `database.hold_book_ceilings` holds against a live Postgres.

The lock is a row lock taken only on Postgres, so what it serialises, what it
blocks and what it costs are all properties of the server. On SQLite the
writers that count before they write race by design (SQLite serialises from a
transaction's first write, which they reach after counting), and nothing takes
a row lock for an edit to wait on.

**Skipped, at runtime, when the suite is on SQLite**, as
`test_database_tls_on_a_real_server.py` is and for the same reason. The
pipeline's `test:postgres` job names this file.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text, update
from sqlalchemy.orm import Session

import database
import importing
import marc
from catalogue import Heading, Link, Record
from classifications import add_headings
from database import engine
from enums import ClassificationScheme
from importing import MarcImport
from models import MAX_ONLINE_LINKS_PER_BOOK, Book, Classification, OnlineLink
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from schemas.classification import ClassificationIn
from tests import test_folding

if engine.dialect.name != "postgresql":
    pytest.skip(
        "The Book's ceiling lock is a Postgres row lock, and this run is on SQLite. "
        "The pipeline's test:postgres job is where this file runs.",
        allow_module_level=True,
    )

#: Reached through the module, because a `Test` class imported by name is
#: collected here a second time.
_merge_racing = test_folding.TestAMergeHoldsTheKeepersCeilings._merge_racing


class TestHoldingABooksCeilingsTakesNoSharedLockSlotPerBook:
    """A MARC import holds one Book's ceilings for every Book it adds a row to
    until its single commit. A lock taking an entry in Postgres's shared lock
    table per Book bounds how many Books one import can reach, and fails the
    whole import past it; a row lock is kept on the row. So holding many Books
    takes no more entries than holding one."""

    def test_holding_fifty_books_takes_as_many_lock_table_entries_as_holding_one(self, db):
        books = [Book(title=f"Book {index}") for index in range(50)]
        db.add_all(books)
        db.commit()
        ids = [book.id for book in books]

        with Session(bind=engine) as session:

            def entries() -> int:
                return session.execute(
                    text("SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid()")
                ).scalar_one()

            database.hold_book_ceilings(session, ids[0])
            after_one = entries()
            for book_id in ids[1:]:
                database.hold_book_ceilings(session, book_id)
            assert entries() == after_one
            session.rollback()


class TestAMergeHoldsTheKeepersCeilingsAgainstAWriterCountingFirst:
    """The races of `test_folding.py::TestAMergeHoldsTheKeepersCeilings` through
    the two writers that count before they write."""

    def test_a_heading_added_to_the_keeper_mid_merge_stays_within_the_ceiling(
        self, admin, make_book, db
    ):
        """The same race through the other capped writer, an enrichment's
        headings: without the merge's lock it counts 7, adds one, and the
        merge's commit carries the loser's past it to 9."""
        keeper, loser = make_book(admin["headers"]), make_book(admin["headers"])
        for index in range(MAX_CLASSIFICATIONS_PER_BOOK - 1):
            db.add(Classification(book_id=keeper["id"], scheme=ClassificationScheme.DDC, number=f"{index}00"))
        db.add(Classification(book_id=loser["id"], scheme=ClassificationScheme.DDC, number="990"))
        db.commit()

        def enrich(session: Session) -> object:
            book = session.get(Book, keeper["id"])
            assert book is not None
            add_headings(book, [ClassificationIn(scheme=ClassificationScheme.DDC, number="991")], session)
            session.commit()
            return None

        _merge_racing(keeper["id"], loser["id"], enrich)

        held = db.query(Classification).filter(Classification.book_id == keeper["id"]).count()
        assert held == MAX_CLASSIFICATIONS_PER_BOOK

    def test_a_link_an_import_adds_to_the_keeper_mid_merge_stays_within_the_ceiling(
        self, admin, make_book, db
    ):
        """The same race through a MARC import's link writer, which reaches a
        matched Book with its links already loaded: without the lock, or with
        the lock and that loaded list, it counts 7, adds one, and the merge's
        commit carries the loser's past it to 9."""
        keeper, loser = make_book(admin["headers"]), make_book(admin["headers"])
        for index in range(MAX_ONLINE_LINKS_PER_BOOK - 1):
            db.add(OnlineLink(book_id=keeper["id"], url=f"https://keeper.example/{index}"))
        db.add(OnlineLink(book_id=loser["id"], url="https://loser.example/"))
        db.commit()

        def import_links(session: Session) -> object:
            book = session.get(Book, keeper["id"])
            assert book is not None
            assert len(book.online_links) == MAX_ONLINE_LINKS_PER_BOOK - 1
            importing._keep_links(book, [Link(url="https://late.example/")], session)
            session.commit()
            return None

        _merge_racing(keeper["id"], loser["id"], import_links)

        held = db.query(OnlineLink).filter(OnlineLink.book_id == keeper["id"]).count()
        assert held == MAX_ONLINE_LINKS_PER_BOOK


class TestAMarcImportAddingNothingToABookLeavesItEditable:
    """A MARC import holds each Book it adds a heading or a link to until its
    one commit, and an edit to a held Book waits for that commit. A Book the
    file adds nothing to is not held."""

    def test_a_book_holding_the_records_heading_and_link_takes_an_edit_mid_import(
        self, db, member, monkeypatch
    ):
        """The edit runs in another session just before the import commits and
        gives up after a second, so a held Book fails this with a lock timeout
        rather than hanging the run."""
        book = Book(title="Small Gods", isbn="9780552152976", added_by_user_id=member["user"]["id"])
        book.classifications.append(Classification(scheme=ClassificationScheme.DDC, number="823.914"))
        book.online_links.append(OnlineLink(url="https://a.example/small-gods"))
        db.add(book)
        db.commit()
        book_id = book.id

        with Session(bind=engine) as importing_session:
            commit = importing_session.commit

            def edit_then_commit() -> None:
                with Session(bind=engine) as editing:
                    editing.execute(text("SET LOCAL lock_timeout = '1s'"))
                    editing.execute(update(Book).where(Book.id == book_id).values(title="Edited"))
                    editing.commit()
                commit()

            monkeypatch.setattr(importing_session, "commit", edit_then_commit)
            MarcImport.for_member(importing_session, member["user"]["id"]).apply(
                marc.ParsedMarc(
                    records=(
                        Record(
                            source="marc",
                            title="Small Gods",
                            isbn="9780552152976",
                            headings=(Heading(ClassificationScheme.DDC, "823.914"),),
                        ),
                    ),
                    skipped=0,
                    links=((Link(url="https://a.example/small-gods"),),),
                )
            )

        db.expire_all()
        edited = db.get(Book, book_id)
        assert edited is not None
        assert edited.title == "Edited"
