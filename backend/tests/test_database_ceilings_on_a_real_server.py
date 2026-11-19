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

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Final

import pytest
from httpx import Response
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

import cover_store
import covers
import database
import folding
import importing
import marc
import recognition
from catalogue import Heading, Link, Record
from classifications import add_headings
from database import engine, server_fields
from enums import ClassificationScheme
from errors import MetAnotherChange
from importing import Import, MarcImport, OpdsImport
from models import MAX_ONLINE_LINKS_PER_BOOK, Book, Classification, CoverImage, OnlineLink, UserBook
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from schemas.classification import ClassificationIn
from tests import test_folding
from tests.helpers import JPEG_BYTES, PNG_BYTES
from tests.routers.test_books_cover_images import _images_of, _shelve
from tests.routers.test_books_cover_images import _upload as _upload_cover_image
from tests.routers.test_imports import csv_bytes, goodreads_row
from tests.routers.test_imports import upload as upload_csv
from tests.routers.test_imports_marc import collection, field, library_mode, link_field, record, upload
from tests.test_importing import catalogued, held, one_marc_file, parse, row

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

    def test_a_heading_added_to_the_keeper_mid_merge_stays_within_the_ceiling(self, admin, make_book, db):
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


#: How long either side of a race below waits for the other before it fails,
#: so a harness that stops meeting its cycle fails rather than hanging the run.
_RACE_BOUND_SECONDS = 15


def _until_another_session_waits_on_this_one(session: Session) -> None:
    """Return once some backend is blocked on a lock `session` holds.

    `pg_locks` rather than `pg_stat_activity`, which a transaction reads from a
    snapshot taken on its first look and so never sees the wait begin.
    """
    deadline = time.monotonic() + _RACE_BOUND_SECONDS
    while time.monotonic() < deadline:
        blocked = session.execute(
            text(
                "SELECT count(*) FROM pg_locks"
                " WHERE NOT granted AND pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        ).scalar_one()
        if blocked:
            return
        time.sleep(0.02)
    raise AssertionError("no session came to wait on a lock this one holds")


class TestAMarcImportDeadlockingWithAMergeAnswers409:
    """A MARC import locks each Book it adds a link to, in record order, until
    its one commit; a merge locks its keeper and then deletes its loser. An
    import holding the loser that reaches the keeper closes a cycle, and
    Postgres aborts whichever side started waiting first."""

    def test_an_import_aborted_for_a_deadlock_with_a_merge_answers_409_and_writes_nothing(
        self, client, admin, db, monkeypatch
    ):
        """The import waits first, so Postgres aborts the import and the merge
        commits. The import holds the loser before the merge starts and waits
        on the keeper before the merge reaches the loser, and Postgres runs its
        deadlock check one `deadlock_timeout` after a wait begins."""
        library_mode(db)
        owner = admin["user"]["id"]
        keeper = Book(title="Small Gods", isbn="9780552152976", added_by_user_id=owner)
        loser = Book(title="Pyramids", isbn="9780552134613", added_by_user_id=owner)
        db.add_all([keeper, loser])
        db.commit()
        keeper_id, loser_id = keeper.id, loser.id

        loser_held, keeper_held = threading.Event(), threading.Event()
        keep_links = importing._keep_links

        def keep_links_then_let_the_merge_in(book: Book, links, session: Session) -> None:
            keep_links(book, links, session)
            if book.id == loser_id and not loser_held.is_set():
                loser_held.set()
                assert keeper_held.wait(timeout=_RACE_BOUND_SECONDS)

        monkeypatch.setattr(importing, "_keep_links", keep_links_then_let_the_merge_in)

        def merge() -> None:
            assert loser_held.wait(timeout=_RACE_BOUND_SECONDS)
            with Session(bind=engine, autoflush=False) as session:
                kept, lost = session.get(Book, keeper_id), session.get(Book, loser_id)
                assert kept is not None
                assert lost is not None
                database.hold_book_ceilings(session, keeper_id)
                keeper_held.set()
                _until_another_session_waits_on_this_one(session)
                folding.fold(session, kept, [lost])
                session.expire(lost)
                session.delete(lost)
                session.commit()

        with ThreadPoolExecutor(1) as pool:
            merging = pool.submit(merge)
            res = upload(
                client,
                admin["headers"],
                collection(
                    record(
                        field("245", ("a", "Pyramids")),
                        field("020", ("a", "9780552134613")),
                        link_field("https://a.example/pyramids"),
                    ),
                    record(
                        field("245", ("a", "Small Gods")),
                        field("020", ("a", "9780552152976")),
                        link_field("https://a.example/small-gods"),
                    ),
                ),
            )
            merging.result(timeout=_RACE_BOUND_SECONDS)

        db.expire_all()
        assert res.status_code == 409
        assert db.get(Book, loser_id) is None
        assert db.query(OnlineLink).filter(OnlineLink.book_id == keeper_id).count() == 0


class TestAMergeDeadlockingWithAnotherWriterAnswers409:
    """A merge holds its keeper and then deletes its loser. A writer holding
    the loser that reaches for the keeper closes a cycle, and Postgres aborts
    whichever side started waiting first."""

    def test_a_merge_aborted_for_a_deadlock_answers_409_and_merges_nothing(self, client, admin, db):
        """The merge waits first, on the loser the writer holds, so Postgres
        aborts the merge and the writer commits. The writer reaches for the
        keeper once the merge is waiting, inside the one `deadlock_timeout`
        after which Postgres checks the merge's wait for a cycle."""
        owner = admin["user"]["id"]
        keeper = Book(title="Small Gods", isbn="9780552152976", added_by_user_id=owner)
        loser = Book(title="Pyramids", added_by_user_id=owner)
        db.add_all([keeper, loser])
        db.commit()
        keeper_id, loser_id = keeper.id, loser.id
        loser_held = threading.Event()

        def hold_the_loser_then_reach_for_the_keeper() -> None:
            with Session(bind=engine) as session:
                database.hold_book_ceilings(session, loser_id)
                loser_held.set()
                _until_another_session_waits_on_this_one(session)
                database.hold_book_ceilings(session, keeper_id)
                session.commit()

        with ThreadPoolExecutor(1) as pool:
            writing = pool.submit(hold_the_loser_then_reach_for_the_keeper)
            assert loser_held.wait(timeout=_RACE_BOUND_SECONDS)
            res = client.post(
                "/api/books/merge",
                json={"book_ids": [keeper_id, loser_id], "keep_id": keeper_id},
                headers=admin["headers"],
            )
            writing.result(timeout=_RACE_BOUND_SECONDS)

        db.expire_all()
        assert res.status_code == 409
        assert db.get(Book, loser_id) is not None


def _merge_on_another_connection(keeper_id: int, loser_id: int) -> None:
    """Fold the loser into the keeper and delete it, to its commit, as the
    merge door does, on a connection the import does not hold."""
    with Session(bind=engine, autoflush=False) as session:
        session.execute(text(f"SET LOCAL lock_timeout = '{_RACE_BOUND_SECONDS}s'"))
        kept, lost = session.get(Book, keeper_id), session.get(Book, loser_id)
        assert kept is not None
        assert lost is not None
        database.hold_book_ceilings(session, keeper_id)
        folding.fold(session, kept, [lost])
        session.expire(lost)
        session.delete(lost)
        session.commit()


class TestAnImportWhoseMatchedBookAMergeDeletedAnswers409:
    """An import reads its index before its first row, and a merge on another
    connection can then delete a Book the index matched and commit, with no
    lock cycle between them. The import loads a Book that is gone."""

    def test_the_import_answers_409_and_writes_nothing(self, client, admin, db, monkeypatch):
        """The merge runs to its commit between the index and the first row,
        where the import has only read and holds no row lock, so neither side
        waits. The row before the loser's creates a Book, which the 409's
        rollback takes back."""
        owner = admin["user"]["id"]
        keeper = Book(title="Small Gods", isbn="9780552152976", added_by_user_id=owner)
        loser = Book(title="Pyramids", isbn="9780552134613", added_by_user_id=owner)
        db.add_all([keeper, loser])
        db.commit()
        keeper_id, loser_id = keeper.id, loser.id
        build = recognition.Index.build

        def build_then_merge(*args):
            index = build(*args)
            _merge_on_another_connection(keeper_id, loser_id)
            return index

        monkeypatch.setattr(recognition.Index, "build", build_then_merge)

        res = upload_csv(
            client,
            admin["headers"],
            csv_bytes(
                goodreads_row("Mort", "read"),
                goodreads_row("Pyramids", "read", '="9780552134613"'),
            ),
            create_missing=True,
        )

        db.expire_all()
        assert res.status_code == 409
        assert db.get(Book, loser_id) is None
        assert db.query(Book).filter(Book.title == "Mort").count() == 0


class TestADefaultCsvImportWhoseMatchedBookAMergeDeletesAfterItsLoadAnswers409:
    """A default CSV import writes nothing before its one commit, so a matched
    Book a merge deletes after the import loaded it fails there, on the gap
    fill's UPDATE."""

    def test_the_import_answers_409_and_writes_nothing(self, client, admin, db, monkeypatch):
        """The merge commits inside the loser's gap fill, where the import has
        written nothing to the database and holds no row lock, so neither side
        waits. The status the keeper's row wrote is rolled back with the rest."""
        owner = admin["user"]["id"]
        keeper = Book(title="Small Gods", isbn="9780552152976", added_by_user_id=owner)
        loser = Book(title="Pyramids", isbn="9780552134613", added_by_user_id=owner)
        db.add_all([keeper, loser])
        db.commit()
        keeper_id, loser_id = keeper.id, loser.id
        fill = importing._fill_gaps

        def fill_then_merge(book: Book, *args) -> None:
            fill(book, *args)
            if book.id == loser_id:
                _merge_on_another_connection(keeper_id, loser_id)

        monkeypatch.setattr(importing, "_fill_gaps", fill_then_merge)

        res = upload_csv(
            client,
            admin["headers"],
            csv_bytes(
                goodreads_row("Small Gods", "read", '="9780552152976"'),
                goodreads_row("Pyramids", "read", '="9780552134613"'),
            ),
        )

        db.expire_all()
        assert res.status_code == 409
        assert db.get(Book, loser_id) is None
        assert db.query(UserBook).count() == 0


#: The keeper and the loser every case below merges, by ISBN.
_KEEPER_ISBN, _LOSER_ISBN = "9780552152976", "9780552134613"


@dataclass(frozen=True)
class _Shape:
    """One place an import meets a matched Book deleted after its load.

    `apply` runs the import on a session with `merge` patched in after the
    load; `met` says whether an error is the one the import meets there, so a
    case that stopped driving its shape fails."""

    apply: Callable[[Session, int, pytest.MonkeyPatch, Callable[[], None]], object]
    met: Callable[[BaseException | None], bool]


def _exactly(kind: type[Exception]) -> Callable[[BaseException | None], bool]:
    """That error and not a subclass: `NoResultFound` is an `InvalidRequestError`
    raised by the load, which is another shape."""
    return lambda error: type(error) is kind


def _a_foreign_key_violation(error: BaseException | None) -> bool:
    """By SQLSTATE, because the type is the driver's: pg8000 raises 23503 as
    `ProgrammingError`, and only 23505 as `IntegrityError`."""
    fields = server_fields(error) if isinstance(error, DBAPIError) else None
    return fields is not None and fields.get("C") == "23503"


def _csv(*rows: str, fill: bool):
    """A CSV import whose gap fill merges, after filling only when `fill`."""

    def apply(session, member_id, monkeypatch, merge):
        real = importing._fill_gaps

        def fill_then_merge(book: Book, *args) -> None:
            if fill:
                real(book, *args)
            merge()

        monkeypatch.setattr(importing, "_fill_gaps", fill_then_merge)
        return Import.for_member(session, member_id).apply(parse(*rows))

    return apply


def _marc_with_a_link(session, member_id, monkeypatch, merge):
    """A record carrying a link and nothing to fill, so the import's first
    write on the loser is `_keep_links`: its lock finds no row, its flush has
    nothing to send, and its refresh finds no Book."""
    monkeypatch.setattr(importing, "_fill_marc_gaps", lambda *args: merge())
    return MarcImport.for_member(session, member_id).apply(
        marc.ParsedMarc(
            records=(catalogued("Pyramids", isbn=_LOSER_ISBN),),
            skipped=0,
            links=((Link(url="https://a.example/pyramids"),),),
        )
    )


def _opds(session, member_id, monkeypatch, merge):
    """An entry from the member's own server naming the author the Book
    lacks, which its gap fill writes."""
    real = importing._fill_opds_gaps

    def fill_then_merge(book: Book, *args) -> None:
        real(book, *args)
        merge()

    monkeypatch.setattr(importing, "_fill_opds_gaps", fill_then_merge)
    return OpdsImport.for_member(session, member_id).apply(
        [held("Pyramids", author="Terry Pratchett", isbn=_LOSER_ISBN)]
    )


_SHAPES: dict[str, _Shape] = {
    "csv, a gap filled, at the commit": _Shape(
        _csv(row("Pyramids", isbn=_LOSER_ISBN), fill=True), _exactly(StaleDataError)
    ),
    "csv, a status only, at the commit": _Shape(
        _csv(row("Pyramids", isbn=_LOSER_ISBN), fill=False), _a_foreign_key_violation
    ),
    "csv, the Book named twice, the second load from the identity map": _Shape(
        _csv(row("Pyramids", isbn=_LOSER_ISBN), row("Pyramids", isbn=_LOSER_ISBN), fill=True),
        _exactly(StaleDataError),
    ),
    "marc, a link, at the refresh": _Shape(_marc_with_a_link, _exactly(InvalidRequestError)),
    "opds, a gap filled, at the commit": _Shape(_opds, _exactly(StaleDataError)),
}


class TestAMatchedBookAMergeDeletesAfterItsLoadRaisesMetAnotherChange:
    """The merge commits after the import loaded the loser, where the import
    holds no row lock on it, so neither side waits. Where the import then fails
    depends on what it writes on the gone row, and every importer answers each
    failure as the same race."""

    @pytest.mark.parametrize("shape", list(_SHAPES.values()), ids=list(_SHAPES))
    def test_the_failure_on_the_gone_row_becomes_met_another_change(self, db, member, monkeypatch, shape):
        owner = member["user"]["id"]
        keeper = Book(title="Small Gods", isbn=_KEEPER_ISBN, added_by_user_id=owner)
        loser = Book(title="Pyramids", isbn=_LOSER_ISBN, added_by_user_id=owner)
        db.add_all([keeper, loser])
        db.commit()
        keeper_id, loser_id = keeper.id, loser.id
        merged: list[bool] = []

        def merge_once() -> None:
            if not merged:
                merged.append(True)
                _merge_on_another_connection(keeper_id, loser_id)

        with database.SessionLocal() as session, pytest.raises(MetAnotherChange) as raised:
            shape.apply(session, owner, monkeypatch, merge_once)

        assert shape.met(raised.value.__cause__), repr(raised.value.__cause__)


#: A Book no case above holds, by ISBN.
_NEW_ISBN: Final = "9780552131063"

#: Each importer applying a file that names one new Book twice, as the gap fill
#: the second naming reaches and the run.
_EACH_IMPORTER_NAMING_ONE_NEW_BOOK_TWICE: Final = {
    "csv": (
        "_fill_gaps",
        lambda session, member_id: Import.for_member(session, member_id).apply(
            parse(row("Mort", isbn=_NEW_ISBN), row("Mort", isbn=_NEW_ISBN)),
            create_missing=True,
        ),
    ),
    "marc": (
        "_fill_marc_gaps",
        lambda session, member_id: MarcImport.for_member(session, member_id).apply(
            one_marc_file(catalogued("Mort", isbn=_NEW_ISBN), catalogued("Mort", isbn=_NEW_ISBN))
        ),
    ),
    "opds": (
        "_fill_opds_gaps",
        lambda session, member_id: OpdsImport.for_member(session, member_id).apply(
            [held("Mort", isbn=_NEW_ISBN), held("Mort", isbn=_NEW_ISBN)]
        ),
    ),
}


class TestABookTheImportCreatedIsNotAVanishedMatch:
    """A later row naming a Book this import created matches it, and the
    rollback after a failure takes that Book back on the server. It was not on
    the shelf when the import began, so the failure is raised unchanged: a
    resend fails the same way, and a 409 would ask for the file on every send."""

    @pytest.mark.parametrize(
        ("fill", "apply"),
        list(_EACH_IMPORTER_NAMING_ONE_NEW_BOOK_TWICE.values()),
        ids=list(_EACH_IMPORTER_NAMING_ONE_NEW_BOOK_TWICE),
    )
    def test_an_unrelated_failure_on_the_matching_row_is_raised_unchanged(
        self, member, monkeypatch, fill, apply
    ):
        def unrelated(*args):
            raise IntegrityError("planted", {}, Exception("planted"))

        monkeypatch.setattr(importing, fill, unrelated)

        with database.SessionLocal() as session, pytest.raises(IntegrityError):
            apply(session, member["user"]["id"])


def _holding(book_id: int, held: threading.Event, meanwhile: Callable[[Session], None]) -> None:
    """Hold `book_id`'s lock, wait for a request to queue behind it, run
    `meanwhile` and commit: another transaction's write landing while the
    request waits."""
    with Session(bind=engine) as session:
        database.hold_book_ceilings(session, book_id)
        held.set()
        _until_another_session_waits_on_this_one(session)
        meanwhile(session)
        session.commit()


def _racing(book_id: int, meanwhile: Callable[[Session], None], request: Callable[[], Response]) -> Response:
    """Send `request` while `_holding` holds `book_id`, and answer its response."""
    held = threading.Event()
    with ThreadPoolExecutor(1) as pool:
        holding = pool.submit(_holding, book_id, held, meanwhile)
        assert held.wait(timeout=_RACE_BOUND_SECONDS)
        response = request()
        holding.result(timeout=_RACE_BOUND_SECONDS)
    return response


class TestACoverSwapReadsTheShelfCoverUnderTheLock:
    """A swap loads the book before it takes the lock, so a shelf cover
    uploaded while it waited was read as the link it replaced, never demoted,
    and written over. SQLite's stale snapshot fails the write instead."""

    def test_a_cover_uploaded_while_the_swap_waited_is_kept_as_a_further_image(
        self, client, admin, make_book, covers_dir
    ):
        book_id = make_book(admin["headers"])["id"]
        chosen, front = JPEG_BYTES + b"chosen", JPEG_BYTES + b"front"
        [image] = _upload_cover_image(client, admin, book_id, chosen, "chosen.jpg").json()

        def upload_the_front(session: Session) -> None:
            cover_store.write(book_id, front)
            session.execute(
                update(Book).where(Book.id == book_id).values(cover_url=covers.replaced_url(book_id, "jpg"))
            )

        res = _racing(book_id, upload_the_front, lambda: _shelve(client, admin, book_id, image["id"]))

        assert res.status_code == 200, res.text
        kept = client.get(_images_of(book_id), headers=admin["headers"]).json()
        assert [client.get(held["url"], headers=admin["headers"]).content for held in kept] == [front]
        assert cover_store.cover_bytes(book_id) == chosen


class TestAShelfCoverUploadWritesNothingBeforeTheLock:
    """A swap writes the shelf cover's file under the book's lock. An upload
    that wrote first and waited only at its commit overwrote the swap's file,
    and each settled against a `before` the other had changed."""

    def test_the_upload_has_written_no_file_while_another_writer_holds_the_book(
        self, client, admin, make_book, covers_dir
    ):
        book_id = make_book(admin["headers"])["id"]
        seen: list[frozenset[object]] = []

        res = _racing(
            book_id,
            lambda _: seen.append(cover_store.on_disk(book_id)),
            lambda: client.post(
                f"/api/books/{book_id}/cover",
                files={"file": ("front.png", PNG_BYTES, "image/png")},
                headers=admin["headers"],
            ),
        )

        assert res.status_code == 200, res.text
        assert seen == [frozenset()]
        assert cover_store.cover_bytes(book_id) == PNG_BYTES


class TestAMergeHoldsItsLosersToo:
    """A merge that held only its keeper repointed a loser's images before a
    writer holding the loser committed, then waited at the loser's DELETE,
    whose cascade took the image the writer had added."""

    def test_an_image_added_to_the_loser_while_the_merge_waited_reaches_the_keeper(
        self, client, admin, make_book, db
    ):
        keeper_id = make_book(admin["headers"], title="Small Gods")["id"]
        loser_id = make_book(admin["headers"], title="Pyramids")["id"]

        res = _racing(
            loser_id,
            lambda session: session.add(CoverImage(book_id=loser_id, extension="png")),
            lambda: client.post(
                "/api/books/merge",
                json={"book_ids": [keeper_id, loser_id], "keep_id": keeper_id},
                headers=admin["headers"],
            ),
        )

        assert res.status_code == 200, res.text
        db.expire_all()
        assert db.query(CoverImage).filter(CoverImage.book_id == keeper_id).count() == 1


def _merge_returning_its_outcome(keeper_id: int, loser_id: int) -> str:
    """The merge door's transaction on its own connection, answering how it
    ended rather than raising: a deadlock is what the sort exists to stop."""
    with Session(bind=engine, autoflush=False) as session:
        kept, lost = session.get(Book, keeper_id), session.get(Book, loser_id)
        assert kept is not None
        assert lost is not None
        try:
            folding.fold(session, kept, [lost])
            session.expire(lost)
            session.delete(lost)
            session.commit()
        except MetAnotherChange:
            return "met another change"
        except DBAPIError as error:
            if fields := server_fields(error):
                return f"aborted {fields.get('C')}"
            raise
    return "merged"


class TestTwoMergesWithTheirKeepersSwappedQueueRatherThanDeadlock:
    """A merge that held its keeper first and then its losers held one Book
    while the other merge held the second, each waited on the other's, and
    Postgres aborted one. In ascending id the second merge waits on the first
    Book, then finds the Book the first deleted."""

    def test_one_merges_and_the_other_meets_its_change(self, admin, make_book, monkeypatch):
        first_id = make_book(admin["headers"], title="Small Gods")["id"]
        second_id = make_book(admin["headers"], title="Pyramids")["id"]
        holding: set[int] = set()
        counted = threading.Lock()
        hold = database.hold_book_ceilings

        def hold_then_let_the_other_take_its_first(db: Session, book_id: int) -> bool:
            # Each merge, once it holds its first Book, waits until the other
            # holds one too or queues behind it, so a cycle the order allows
            # is met every run rather than by luck.
            found = hold(db, book_id)
            with counted:
                first = id(db) not in holding
                holding.add(id(db))
            if first:
                _until_both_hold_or_one_waits(db, holding)
            return found

        monkeypatch.setattr(folding, "hold_book_ceilings", hold_then_let_the_other_take_its_first)

        with ThreadPoolExecutor(2) as pool:
            merges = [
                pool.submit(_merge_returning_its_outcome, first_id, second_id),
                pool.submit(_merge_returning_its_outcome, second_id, first_id),
            ]
            outcomes = sorted(merge.result(timeout=2 * _RACE_BOUND_SECONDS) for merge in merges)

        assert outcomes == ["merged", "met another change"]


def _until_both_hold_or_one_waits(session: Session, holding: set[int]) -> None:
    deadline = time.monotonic() + _RACE_BOUND_SECONDS
    while len(holding) < 2:
        blocked = session.execute(
            text(
                "SELECT count(*) FROM pg_locks"
                " WHERE NOT granted AND pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        ).scalar_one()
        if blocked:
            return
        if time.monotonic() > deadline:
            raise AssertionError("neither merge came to hold or wait")
        time.sleep(0.02)


def _delete(book_id: int) -> Callable[[Session], None]:
    """Another merge's DELETE of `book_id`, cascading as the merge door's does."""

    def meanwhile(session: Session) -> None:
        book = session.get(Book, book_id)
        assert book is not None
        session.delete(book)

    return meanwhile


class TestAWriterWhoseBookAMergeDeletedWhileItWaited:
    """The lock found no row, and the writer went on: a cover file named for
    the dead id, then a 500 at the stale UPDATE, the foreign key, or the
    merge's first read of the gone loser."""

    def test_a_shelf_cover_upload_answers_404_and_writes_no_file(self, client, admin, make_book, covers_dir):
        book_id = make_book(admin["headers"])["id"]

        res = _racing(
            book_id,
            _delete(book_id),
            lambda: client.post(
                f"/api/books/{book_id}/cover",
                files={"file": ("front.png", PNG_BYTES, "image/png")},
                headers=admin["headers"],
            ),
        )

        assert res.status_code == 404, res.text
        assert cover_store.on_disk(book_id) == frozenset()

    def test_a_further_image_upload_answers_404_and_keeps_no_row(
        self, client, admin, make_book, db, covers_dir
    ):
        book_id = make_book(admin["headers"])["id"]

        res = _racing(book_id, _delete(book_id), lambda: _upload_cover_image(client, admin, book_id))

        assert res.status_code == 404, res.text
        assert db.query(CoverImage).filter(CoverImage.book_id == book_id).count() == 0

    def test_a_swap_answers_404_and_writes_no_file(self, client, admin, make_book, covers_dir):
        book_id = make_book(admin["headers"])["id"]
        [image] = _upload_cover_image(client, admin, book_id).json()

        res = _racing(book_id, _delete(book_id), lambda: _shelve(client, admin, book_id, image["id"]))

        assert res.status_code == 404, res.text
        assert cover_store.on_disk(book_id) == frozenset()

    def test_a_merge_answers_409_and_merges_nothing(self, client, admin, make_book, db):
        keeper_id = make_book(admin["headers"], title="Small Gods")["id"]
        loser_id = make_book(admin["headers"], title="Pyramids")["id"]

        res = _racing(
            loser_id,
            _delete(loser_id),
            lambda: client.post(
                "/api/books/merge",
                json={"book_ids": [keeper_id, loser_id], "keep_id": keeper_id},
                headers=admin["headers"],
            ),
        )

        assert res.status_code == 409, res.text
        db.expire_all()
        keeper = db.get(Book, keeper_id)
        assert keeper is not None
        assert keeper.title == "Small Gods"
