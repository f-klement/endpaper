"""Tests for backend/pending_headings.py: what a harvest raises, and what a confirm writes.

The routes and the harvest are `tests/routers/test_books_pending_headings.py` and
`tests/routers/test_imports_harvest.py`. What is here is the module's own rules,
driven on a Book in the session.
"""

from catalogue import Heading
from enums import ClassificationScheme
from models import Book, Classification, Harvest, PendingHeading
from pending_headings import confirm, discard, pending_on, raise_on
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK


def a_book_and_a_run(db) -> tuple[Book, Harvest]:
    run = Harvest(base_url="http://10.0.0.1/oai", metadata_prefix="marcxml")
    book = Book(title="Stoner")
    db.add_all([run, book])
    db.flush()
    return book, run


def dewey(*numbers: str) -> list[Heading]:
    return [Heading(ClassificationScheme.DDC, number) for number in numbers]


class TestRaising:
    def test_a_heading_the_book_already_carries_is_not_raised(self, db):
        book, run = a_book_and_a_run(db)
        book.classifications.append(Classification(scheme="ddc", number="004"))
        db.flush()

        raised = raise_on(book, dewey("004", "510"), run)

        assert (raised, [row.number for row in pending_on(book)]) == (1, ["510"])

    def test_a_heading_raised_twice_is_kept_once(self, db):
        book, run = a_book_and_a_run(db)

        raise_on(book, dewey("004"), run)
        raised = raise_on(book, dewey("004"), run)

        assert (raised, [row.number for row in book.pending_headings]) == (0, ["004"])

    def test_no_more_wait_at_once_than_a_book_may_carry(self, db):
        """A repository changing its headings on every run cannot grow the set
        without bound between two settlements."""
        book, run = a_book_and_a_run(db)
        raise_on(book, dewey(*(f"00{n}" for n in range(MAX_CLASSIFICATIONS_PER_BOOK))), run)

        raised = raise_on(book, dewey("999"), run)

        assert (raised, len(pending_on(book))) == (0, MAX_CLASSIFICATIONS_PER_BOOK)

    def test_the_room_is_the_ceiling_less_what_the_book_carries_and_what_waits(self, db):
        """Counting only the waiting rows would raise suggestions on a Book at the
        ceiling that the confirm then drops."""
        book, run = a_book_and_a_run(db)
        carried = MAX_CLASSIFICATIONS_PER_BOOK - 2
        book.classifications.extend(Classification(scheme="ddc", number=f"10{n}") for n in range(carried))
        raise_on(book, dewey("004"), run)

        raised = raise_on(book, dewey("510", "999"), run)

        assert (raised, [row.number for row in pending_on(book)]) == (1, ["004", "510"])

    def test_a_heading_left_out_for_room_is_raised_once_a_settlement_frees_it(self, db):
        book, run = a_book_and_a_run(db)
        carried = MAX_CLASSIFICATIONS_PER_BOOK - 2
        book.classifications.extend(Classification(scheme="ddc", number=f"10{n}") for n in range(carried))
        raise_on(book, dewey("004", "510", "999"), run)
        discard(book)

        assert raise_on(book, dewey("004", "510", "999"), run) == 1
        assert [row.number for row in pending_on(book)] == ["999"]

    def test_a_waiting_heading_the_book_also_carries_takes_one_slot(self, db):
        """A member may add the heading that waits; counting it twice would hold
        back a heading the record newly carries."""
        book, run = a_book_and_a_run(db)
        carried = MAX_CLASSIFICATIONS_PER_BOOK - 2
        book.classifications.extend(Classification(scheme="ddc", number=f"10{n}") for n in range(carried))
        raise_on(book, dewey("004"), run)
        book.classifications.append(Classification(scheme="ddc", number="004"))

        assert raise_on(book, dewey("510"), run) == 1

    def test_a_book_at_the_ceiling_is_raised_nothing(self, db):
        book, run = a_book_and_a_run(db)
        book.classifications.extend(
            Classification(scheme="ddc", number=f"10{n}") for n in range(MAX_CLASSIFICATIONS_PER_BOOK)
        )

        assert (raise_on(book, dewey("004"), run), book.pending_headings) == (0, [])


class TestConfirming:
    def test_a_row_the_schema_refuses_is_dropped_and_settled(self, db):
        """A restore writes these through Core, so a row may hold what no harvest could.

        A `ddc` number that is no notation fits its column on every engine, whereas
        an oversize label is refused by Postgres at the flush and stored only by
        SQLite, so the row would exist on one engine alone.
        """
        book, run = a_book_and_a_run(db)
        book.pending_headings.extend(
            [
                PendingHeading(harvest_id=run.id, scheme="ddc", number="004"),
                PendingHeading(harvest_id=run.id, scheme="ddc", number="Hello world"),
            ]
        )
        db.flush()

        changed = confirm(book, db)

        assert changed == ["004"]
        assert pending_on(book) == []
        assert all(row.settled_at is not None for row in book.pending_headings)

    def test_a_set_the_book_filled_up_after_the_raise_is_dropped_and_settled(self, db):
        """The one way a confirm meets the ceiling: headings given to the Book
        between the raise and the confirm. The Book the route answers shows it."""
        book, run = a_book_and_a_run(db)
        raise_on(book, dewey("004", "510"), run)
        book.classifications.extend(
            Classification(scheme="ddc", number=f"10{n}") for n in range(MAX_CLASSIFICATIONS_PER_BOOK)
        )
        db.flush()

        changed = confirm(book, db)

        assert (changed, len(book.classifications)) == ([], MAX_CLASSIFICATIONS_PER_BOOK)
        assert pending_on(book) == []
