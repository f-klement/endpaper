"""Tests for backend/importing.py: applying a parsed export to a Library.

`tests/routers/test_imports.py` covers the same rules over HTTP, and
deliberately: `TestAnotherMembersPrivateBook`, `TestStatusesArePersonal` and
`TestTagLimits` are there and stay there, along with status codes, payload
shapes and the Goodreads file quirks. **This file is the unit level home**,
where a rule can be driven without a request, a file upload or a status code in
the way. Three things it is the better place for:

**The private Book oracle.** A row whose ISBN belongs to a Book this Member
cannot see must be counted and never named. It is the one rule in this module
that is about privacy rather than about correctness, and getting it wrong
turns a 200 into a clean answer to "does a Book with this ISBN exist in this
house".

**That an import writes only the importing Member's reading record.** Two
Members importing their own exports of the same Book must not overwrite each
other.

**The measured limits**, which exist because each was once absent: the tag
caps, the truncate-before-the-cache-key ordering, and that the catalogue is
read once rather than three times per row.
"""

from collections import Counter
from typing import Any

import pytest
from sqlalchemy import event

import catalogue
import csv_import
from catalogue import Record
from enums import OwnershipStatus, ReadStatus, TagCategory
from importing import (
    _MARC_RECORD_FIELDS,
    Import,
    MarcIndex,
    OpdsImport,
    _CatalogueIndex,
    bounded_fields,
)
from models import TITLE_MAX, Book, Note, Tag, User, UserBook
from schemas.tag import MAX_TAG_NAME

HEADER = (
    "Title,Author,ISBN13,My Rating,Publisher,Number of Pages,"
    "Year Published,Date Read,Bookshelves,Exclusive Shelf,My Review\n"
)


def parse(*rows: str) -> csv_import.ParsedFile:
    return csv_import.parse((HEADER + "".join(r + "\n" for r in rows)).encode())


def row(
    title: str,
    *,
    isbn: str = "",
    shelf: str = "read",
    rating: int = 0,
    shelves: str = "",
    review: str = "",
) -> str:
    quoted = f'="{isbn}"' if isbn else '=""'
    return f'"{title}","An Author",{quoted},{rating},Pub,300,2000,,"{shelves}",{shelf},"{review}"'


@pytest.fixture
def member(db) -> User:
    u = User(username="reader", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def other(db, member) -> User:
    u = User(username="stranger", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def selects(fn) -> list[str]:
    """Every SELECT one call issues. **SELECTs, not statements**: the writes are
    deliberately excluded so the measurement below is about lookups."""
    from database import engine

    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements


class TestThePrivateBookOracle:
    """A row whose ISBN belongs to a Book this Member cannot see."""

    def test_it_is_counted_and_never_named(self, db, member, other):
        db.add(
            Book(
                title="Someone's Secret",
                isbn="9780441013593",
                added_by_user_id=other.id,
                is_private=True,
            )
        )
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(row("Whatever They Called It", isbn="9780441013593")),
            create_missing=True,
        )

        assert result.created == 0
        assert result.skipped == 1
        assert result.unmatched_titles == []

    def test_nothing_is_written_for_it(self, db, member, other):
        """Creating it would raise on the unique index, which aborts the whole
        transaction: a 5000 row import would silently write nothing."""
        db.add(
            Book(
                title="Someone's Secret",
                isbn="9780441013593",
                added_by_user_id=other.id,
                is_private=True,
            )
        )
        db.commit()

        Import.for_member(db, member.id).apply(
            parse(
                row("Whatever They Called It", isbn="9780441013593"),
                row("A Book That Is Fine", isbn="9780140449136"),
            ),
            create_missing=True,
        )

        titles = {book.title for book in db.query(Book).all()}
        assert titles == {"Someone's Secret", "A Book That Is Fine"}

    def test_the_rest_of_the_file_still_lands(self, db, member, other):
        """One unusable row must not throw the other four thousand away."""
        db.add(
            Book(title="Secret", isbn="9780441013593", added_by_user_id=other.id, is_private=True)
        )
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(
                row("Collides", isbn="9780441013593"),
                row("Fine One", isbn="9780140449136"),
                row("Fine Two", isbn="9780261102217"),
            ),
            create_missing=True,
        )

        assert result.created == 2
        assert result.skipped == 1

    def test_a_visible_book_with_the_same_isbn_is_matched_not_skipped(self, db, member):
        """The mirror case: the same ISBN, but on a Book the Member can see, is
        an ordinary match. Skipping it would make the privacy rule visible as a
        difference in behaviour."""
        db.add(
            Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id, is_private=True)
        )
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593")), create_missing=True
        )

        assert result.matched == 1
        assert result.created == 0
        assert result.skipped == 0


class TestATitleCollisionNeverReachesAnotherMembersPrivateBook:
    """The title side of the oracle, which nothing pinned.

    `TestThePrivateBookOracle` above pins the **ISBN** side, and both index
    builders read `Shelf.seen_by`, so the property holds by construction today:
    an invisible row is not in the dictionary, so no key can name it. That is
    exactly why it is written down. The natural way to make matching "more
    complete" is to widen the index past the viewer, and this is what refuses
    that change rather than something that is failing now.
    """

    def test_the_reading_history_index_does_not_hold_one(self, db, member, other):
        db.add(
            Book(
                title="Shared Title",
                author="Ann Author",
                added_by_user_id=other.id,
                is_private=True,
            )
        )
        db.commit()

        index = _CatalogueIndex.build(db, member.id)

        assert index.find_by(db, None, "Shared Title") is None

    def test_the_catalogue_transfer_index_does_not_hold_one(self, db, member, other):
        db.add(
            Book(
                title="Shared Title",
                author="Ann Author",
                added_by_user_id=other.id,
                is_private=True,
            )
        )
        db.commit()

        index = MarcIndex.build(db, member.id)
        fields = bounded_fields(Record(title="Shared Title", author="Ann Author"))

        assert index.holds(fields) is False

    def test_a_work_key_hit_keeps_an_invisibly_taken_isbn_out_of_the_refusals(
        self, db, member, other
    ):
        """The conjunction that decides how much the upload preview discloses.

        `would_refuse` is `not holds(...) and isbn_is_taken(...)`, and the two
        halves read different populations: the identity index is the Shelf, the
        ISBN set is the whole table. So a record whose ISBN an invisible Book
        holds is reported as refused only when the work key misses too, and every
        such report is one bit about a Book the member cannot see.

        **That makes the count a function of the key**, which is why it is pinned
        here: a future tightening of the fold moves records into this arm, and
        the size of that disclosure is not a free parameter of a refactor.

        **Its diagonal lives in another file**, which is worth saying because a
        reader will not look for it there: the True branch is
        `tests/routers/test_imports_marc.py::TestThePreviewCountsBothRefusals`,
        over the complementary shape. Alone, this arm would pass for a
        `would_refuse` that returned False unconditionally; the pair pins the
        conjunction.
        """
        db.add(
            Book(
                title="Someone's Secret",
                isbn="9780441013593",
                added_by_user_id=other.id,
                is_private=True,
            )
        )
        db.add(
            Book(
                title="Shared Title",
                author="Ann Author",
                added_by_user_id=other.id,
                is_private=False,
            )
        )
        db.commit()

        index = MarcIndex.build(db, member.id)
        fields = bounded_fields(
            Record(
                title="The Shared Title", author="Ann Author", isbn="9780441013593"
            )
        )

        assert index.would_refuse(fields) is False

    def test_a_visible_book_with_the_same_title_is_still_matched(
        self, db, member, other
    ):
        """The diagonal, so neither arm above passes by matching nothing at all."""
        db.add(
            Book(
                title="Shared Title",
                author="Ann Author",
                added_by_user_id=other.id,
                is_private=False,
            )
        )
        db.commit()

        fields = bounded_fields(Record(title="Shared Title", author="Ann Author"))

        assert _CatalogueIndex.build(db, member.id).find_by(
            db, None, "Shared Title"
        ) is not None
        assert MarcIndex.build(db, member.id).holds(fields) is True


class TestReadingRecordsArePersonal:
    def test_only_the_importing_members_row_is_written(self, db, member, other):
        book = Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id)
        db.add(book)
        db.commit()
        db.add(UserBook(book_id=book.id, user_id=other.id, status=ReadStatus.UNREAD))
        db.commit()

        Import.for_member(db, member.id).apply(parse(row("Dune", isbn="9780441013593")))

        theirs = db.query(UserBook).filter_by(user_id=other.id).one()
        mine = db.query(UserBook).filter_by(user_id=member.id).one()
        assert theirs.status == ReadStatus.UNREAD
        assert mine.status == ReadStatus.READ

    def test_an_existing_rating_is_never_overwritten(self, db, member):
        """Somebody who rated a Book here expressed a more recent opinion than
        an export from another service."""
        book = Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id)
        db.add(book)
        db.commit()
        db.add(UserBook(book_id=book.id, user_id=member.id, rating=5))
        db.commit()

        Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", rating=2))
        )

        assert db.query(UserBook).one().rating == 5

    def test_two_rows_for_one_book_do_not_take_the_import_down(self, db, member):
        """A rating on the first row and a status on the second.

        The first row's `open()` creates a record that is never flushed, because
        matching the second row is a dictionary lookup rather than a query. Its
        `status` is therefore still None, and reading that column raw raised
        `ValueError: None is not a valid ReadStatus`, which aborts the whole
        transaction: a 5,000 row file writes nothing. `Records.status_of` is the
        one place that knows about the unflushed row.
        """
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(
                row("Dune", isbn="9780441013593", shelf="", rating=4),
                row("Dune", isbn="9780441013593", shelf="read"),
            )
        )

        assert result.skipped == 0
        record = db.query(UserBook).one()
        assert record.rating == 4
        assert record.status == ReadStatus.READ

    def test_a_row_with_nothing_personal_leaves_no_marker(self, db, member):
        """A file that is a plain book list should not leave an "unread" marker
        on every Book it touched."""
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelf=""))
        )

        assert result.statuses_updated == 0
        assert db.query(UserBook).count() == 0


class TestCreatingBooks:
    def test_a_created_book_is_unknown_ownership(self, db, member):
        """An export says what someone read, not what is on the shelf."""
        Import.for_member(db, member.id).apply(
            parse(row("New One", isbn="9780140449136")), create_missing=True
        )

        assert db.query(Book).one().ownership == OwnershipStatus.UNKNOWN

    def test_a_file_listing_one_book_twice_creates_it_once(self, db, member):
        """`remember` keeps a freshly created Book findable by later rows, or
        the second row creates it again or raises on the ISBN index."""
        result = Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593"), row("Dune", isbn="9780441013593")),
            create_missing=True,
        )

        assert result.created == 1
        assert db.query(Book).count() == 1

    def test_gaps_are_filled_and_nothing_is_overwritten(self, db, member):
        book = Book(
            title="Dune", isbn="9780441013593", publisher="Real Publisher",
            added_by_user_id=member.id,
        )
        db.add(book)
        db.commit()

        Import.for_member(db, member.id).apply(parse(row("Dune", isbn="9780441013593")))
        db.refresh(book)

        assert book.publisher == "Real Publisher"
        assert book.year == 2000
        assert book.page_count == 300


class TestTheTagCaps:
    def test_a_long_tag_name_is_truncated_before_the_cache_key(self, db, member):
        """Truncating only at the insert made two tags sharing their first
        hundred characters both miss the cache, both miss the query, and the
        second insert violate the unique index, which took the import down."""
        shared = "x" * MAX_TAG_NAME
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelves=f"{shared}a,{shared}b")),
            apply_tags=True,
        )

        names = [t.name for t in db.query(Tag).filter(Tag.name.like("x%")).all()]
        assert names == [shared]

    def test_a_non_ascii_tag_already_in_the_library_is_reused(self, db, member):
        """The bug the per-name query had, and the reason the cache is now
        seeded from the table.

        SQLite's `lower()` is ASCII only and Python's is not: measured,
        `lower('Ästhetik')` is `'Ästhetik'` in SQLite and `'ästhetik'` in
        Python. The old lookup folded on the SQLite side and compared against a
        key folded on the Python side, so a stored Tag with a non-ASCII capital
        never matched, the import decided it was new, and the insert hit the
        binary unique index on `tags.name`.

        **That raised `IntegrityError` and took the whole file with it**: one
        German shelf name meant nothing imported at all, every time.
        """
        db.add(Tag(name="Ästhetik", category=TagCategory.CUSTOM, is_predefined=False))
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelves="Ästhetik")), apply_tags=True
        )

        assert result.matched == 1
        assert db.query(Tag).filter(Tag.name == "Ästhetik").count() == 1
        book = db.query(Book).one()
        assert [tag.name for tag in book.tags] == ["Ästhetik"]

    def test_a_tag_is_matched_case_insensitively(self, db, member):
        """The ordinary half of the same rule, which never broke: an existing
        `Bookclub` is reused for a file saying `bookclub`."""
        # A name the tag seeder does not own. Using "Fiction" made the fixture
        # itself violate the unique index, because `seed_tags` had already
        # created it: the test failed before reaching what it was testing.
        db.add(Tag(name="Bookclub", category=TagCategory.CUSTOM, is_predefined=False))
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelves="bookclub")), apply_tags=True
        )

        assert db.query(Tag).filter(Tag.name.in_(["Bookclub", "bookclub"])).count() == 1

    def test_it_stops_inventing_rather_than_failing(self, db, member):
        """Past the cap the Books in the file are still worth having."""
        many = ",".join(f"tag{n}" for n in range(csv_import.MAX_NEW_TAGS_PER_IMPORT + 20))
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelves=many)), apply_tags=True
        )

        assert result.matched == 1
        invented = db.query(Tag).filter(Tag.name.like("tag%")).count()
        assert invented <= csv_import.MAX_NEW_TAGS_PER_IMPORT

    def test_tags_are_off_unless_asked_for(self, db, member):
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelves="one,two"))
        )

        assert db.query(Tag).filter(Tag.name.in_(["one", "two"])).count() == 0


class TestTheReview:
    def test_it_lands_as_a_note(self, db, member):
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", review="Loved it."))
        )

        assert db.query(Note).one().content == "Loved it."

    def test_re_running_does_not_append_it_again(self, db, member):
        """An import is not a reason to append the same paragraph every run."""
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()
        parsed = parse(row("Dune", isbn="9780441013593", review="Loved it."))

        Import.for_member(db, member.id).apply(parsed)
        Import.for_member(db, member.id).apply(parsed)

        assert db.query(Note).count() == 1


class TestTheCatalogueIsReadOnce:
    """Before the index existed a 5000 row file cost 25,001 **statements** and
    61 seconds, and only about 15% of that was SQLite: the rest was SQLAlchemy
    compiling the same queries five thousand times.

    That figure counted writes too, so nothing here derives a new total from
    it. What is measured below is the **slope in SELECTs**, which is the claim
    the module actually makes."""

    def test_the_per_row_cost_is_one_select(self, db, member):
        db.add_all(
            Book(title=f"Book {n}", isbn=f"978044101{n:04d}", added_by_user_id=member.id)
            for n in range(12)
        )
        db.commit()
        member_id = member.id

        def run(count):
            def work():
                Import.for_member(db, member_id).apply(
                    parse(*(row(f"Book {n}", isbn=f"978044101{n:04d}") for n in range(count)))
                )

            return work

        run(1)()  # warm up outside the measurement
        for_one = len(selects(run(1)))
        for_ten = len(selects(run(10)))

        # **One SELECT per extra row.** The index does not make the cost flat
        # and does not claim to: `find` still issues a `db.get` for a row it
        # matched, which is the one lookup that has to return a live object
        # rather than an id. What it removed is the ISBN query, the title query
        # and the status query, which were per row and are now per import.
        assert for_ten - for_one == 9, (for_one, for_ten)

    def test_the_match_index_is_scoped_and_the_isbn_set_is_not(self, db, member, other):
        """The module's most load-bearing property, and the two halves pull in
        opposite directions on purpose.

        **Both Books need an ISBN or this test proves nothing.** The first
        version gave them none, so `taken_isbns` was empty and the assertion
        reduced to `{"mine"} != set()`: true, and true for a reason unrelated
        to what it claimed.
        """
        theirs = "9780441013593"
        mine = "9780140449136"
        db.add(Book(title="Theirs", isbn=theirs, added_by_user_id=other.id, is_private=True))
        db.add(Book(title="Mine", isbn=mine, added_by_user_id=member.id))
        db.commit()

        index = _CatalogueIndex.build(db, member.id)

        # The match halves are scoped: another Member's Private Book is not
        # something this import may match against or fill gaps on.
        assert set(index.by_title) == {"mine"}
        assert set(index.by_isbn) == {mine}

        # `taken_isbns` is deliberately wider, because it answers the
        # uniqueness question rather than the visibility one. Without their
        # ISBN in here, creating a row for it raises on the unique index and
        # takes the whole import down.
        assert theirs in index.taken_isbns
        assert mine in index.taken_isbns


# ── OPDS ──────────────────────────────────────────────────────────────────────


def held(title: str, *, author: str | None = None, isbn: str | None = None):
    """One record as `opds.entry_record` would produce it."""
    return Record(source="opds", title=title, author=author, isbn=isbn)


class TestAnOpdsSyncAssertsOwnership:
    """The one thing this route establishes that the other two importers cannot.

    A reading history says what somebody read and another institution's
    catalogue says what that institution holds. A member's own library server
    says what that member has, and if that did not reach `ownership` the route
    would have imported nothing worth having.
    """

    def test_a_created_book_arrives_owned(self, db, member):
        OpdsImport.for_member(db, member.id).apply([held("Small Gods")])

        assert db.query(Book).one().ownership == OwnershipStatus.OWNED

    def test_a_matched_book_nobody_answered_for_becomes_owned(self, db, member):
        db.add(
            Book(
                title="Small Gods",
                added_by_user_id=member.id,
                ownership=OwnershipStatus.UNKNOWN,
            )
        )
        db.commit()

        OpdsImport.for_member(db, member.id).apply([held("Small Gods")])

        assert db.query(Book).one().ownership == OwnershipStatus.OWNED

    def test_a_book_somebody_said_is_not_owned_is_left_alone(self, db, member):
        """`UNKNOWN` is the gap for this column. A person answered here, and a
        feed does not overrule a person."""
        db.add(
            Book(
                title="Small Gods",
                added_by_user_id=member.id,
                ownership=OwnershipStatus.NOT_OWNED,
            )
        )
        db.commit()

        OpdsImport.for_member(db, member.id).apply([held("Small Gods")])

        assert db.query(Book).one().ownership == OwnershipStatus.NOT_OWNED


class TestTheOpdsMatchingRuleIsTheOneImportUses:
    """ISBN where one exists, then the normalised title. Not `MarcIndex`'s rule."""

    def test_an_isbn_matches_before_a_title(self, db, member):
        db.add(Book(title="A different spelling", isbn="9780552152976",
                    added_by_user_id=member.id))
        db.commit()

        result = OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods", isbn="9780552152976")]
        )

        assert (result.matched, result.created) == (1, 0)

    def test_a_title_matches_case_insensitively_with_no_author_in_the_key(
        self, db, member
    ):
        """The difference from `MarcIndex`, which folds the author into the key.
        A record crediting nobody still matches a Book credited to someone."""
        db.add(Book(title="Small Gods", author="Terry Pratchett",
                    added_by_user_id=member.id))
        db.commit()

        result = OpdsImport.for_member(db, member.id).apply([held("SMALL GODS")])

        assert (result.matched, result.created) == (1, 0)

    def test_a_book_this_library_does_not_hold_is_created(self, db, member):
        result = OpdsImport.for_member(db, member.id).apply([held("Small Gods")])

        assert (result.matched, result.created) == (0, 1)

    def test_nothing_is_created_when_the_caller_asked_for_none(self, db, member):
        result = OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods")], create_missing=False
        )

        assert (result.created, result.unmatched_titles) == (0, ["Small Gods"])

    def test_a_feed_listing_one_book_twice_creates_it_once(self, db, member):
        result = OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods"), held("Small Gods")]
        )

        assert (result.created, result.matched) == (1, 1)


class TestFillingGapsAndNeverOverwriting:
    def test_an_author_this_catalogue_lacks_is_filled_in(self, db, member):
        db.add(Book(title="Small Gods", added_by_user_id=member.id))
        db.commit()

        OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods", author="Terry Pratchett")]
        )

        assert db.query(Book).one().author == "Terry Pratchett"

    def test_an_author_somebody_already_wrote_is_not_replaced(self, db, member):
        db.add(Book(title="Small Gods", author="T. Pratchett",
                    added_by_user_id=member.id))
        db.commit()

        OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods", author="Terry Pratchett")]
        )

        assert db.query(Book).one().author == "T. Pratchett"

    def test_an_isbn_is_never_written_onto_a_book_that_matched_on_its_title(
        self, db, member
    ):
        """`books.isbn` is unique across the whole table, so filling it can raise
        on a row this Member cannot see and abort the entire sync. The record
        matched on the weaker key, which is also where it is least likely to be
        about the same book."""
        db.add(Book(title="Small Gods", added_by_user_id=member.id))
        db.commit()

        OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods", isbn="9780552152976")]
        )

        assert db.query(Book).one().isbn is None


class TestTheOpdsPrivateBookOracle:
    """A record whose ISBN belongs to a Book this Member cannot see.

    Counted with the unusable records and never named, for the reason the
    module docstring gives: the difference between 200 and 500 would be a clean
    answer to "does a Book with this ISBN exist in this house".
    """

    def test_it_is_skipped_rather_than_raising_on_the_unique_index(self, db, member, other):
        db.add(Book(title="Hidden", isbn="9780552152976", is_private=True,
                    added_by_user_id=other.id))
        db.commit()

        result = OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods", isbn="9780552152976")]
        )

        assert (result.created, result.skipped) == (0, 1)

    def test_its_title_is_never_reported(self, db, member, other):
        db.add(Book(title="Hidden", isbn="9780552152976", is_private=True,
                    added_by_user_id=other.id))
        db.commit()

        result = OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods", isbn="9780552152976")]
        )

        assert result.unmatched_titles == []

    def test_the_rest_of_the_feed_still_arrives(self, db, member, other):
        """One record that cannot be acted on is counted and skipped, never a
        failed sync."""
        db.add(Book(title="Hidden", isbn="9780552152976", is_private=True,
                    added_by_user_id=other.id))
        db.commit()

        result = OpdsImport.for_member(db, member.id).apply(
            [held("Small Gods", isbn="9780552152976"), held("Good Omens")]
        )

        assert (result.created, result.skipped) == (1, 1)


class TestAnOpdsSyncWritesNothingPersonal:
    def test_no_reading_record_is_touched(self, db, member):
        OpdsImport.for_member(db, member.id).apply([held("Small Gods")])

        assert db.query(UserBook).count() == 0

    def test_the_result_reports_no_statuses_changed(self, db, member):
        result = OpdsImport.for_member(db, member.id).apply([held("Small Gods")])

        assert result.statuses_updated == 0


class TestOpdsValuesAreBoundedBeforeTheyAreMatched:
    def test_a_title_at_the_column_width_matches_itself_on_a_second_sync(self, db, member):
        """Matching on the incoming value and storing the bounded one is how the
        same feed synced twice fails to find itself."""
        record = held("T" * TITLE_MAX)

        first = OpdsImport.for_member(db, member.id).apply([record])
        second = OpdsImport.for_member(db, member.id).apply([record])

        assert (first.created, second.matched) == (1, 1)

    def test_a_title_the_column_cannot_hold_is_skipped_rather_than_filed_cut_short(
        self, db, member
    ):
        """The bound is `catalogue.Record`'s and it drops rather than truncates:
        half a title is an assertion nobody made. What reaches here is a record
        naming nothing, and it is counted where a person can see it."""
        result = OpdsImport.for_member(db, member.id).apply([held("T" * (TITLE_MAX + 1))])

        assert (result.created, result.skipped) == (0, 1)

    def test_an_empty_title_matches_nothing_rather_than_every_book(
        self, db, member
    ):
        """A record naming nothing must not be matched by `""`. The over long
        case is the test above; this one is the empty string it could also
        arrive as."""
        db.add(Book(title="Small Gods", added_by_user_id=member.id))
        db.commit()

        result = OpdsImport.for_member(db, member.id).apply([held("")])

        assert (result.created, result.matched, result.skipped) == (0, 0, 1)


#: The two sides a bound can have: a range has both, a text ceiling has the one.
#:
#: Values rather than labels, because the sweep's own guard is keyed on them.
CEILING, FLOOR = "ceiling", "floor"


def _outside_each_bound() -> list[Any]:
    """Every side of every bound the importer's columns have, with what it must become.

    One case per **side**, not per field, and picked by which table names the
    field rather than by its type or by a list of names, so a field moving
    between the two tables gets the other probes and a table growing a name
    grows this. A range gets its floor as well as its ceiling: measured by a
    critic seat on 2026-09-19, deleting the `Ge` arm of `within_bounds` and
    leaving `Le` left the whole backend suite green, and what the floor costs is
    at `catalogue._NUMBER_RANGES`, a row `BookDetailsUpdate` answers 422 for and
    nobody can edit back.

    **Each case carries the value the belt must return, not merely that it must
    differ.** `!=` separates the belt from the identity and from nothing else:
    the same seat flipped the string arm from truncate to drop, which is the one
    policy `docs/decisions.md` cites this function as the home of, and the suite
    was green on all 7,540.

    **The text probe is inhomogeneous** because a homogeneous one hides the end
    a truncation was taken from: `("x" * n)[:c]` and `("x" * n)[-c:]` are the
    same string. That shape is load bearing, so it is asserted rather than
    described: `_is_outside` refuses a text probe whose two ends agree.
    """
    cases: list[Any] = []
    for name in _MARC_RECORD_FIELDS:
        if name in catalogue._NUMBER_RANGES:
            low, high = catalogue._NUMBER_RANGES[name]
            # Numbers drop rather than clamp: 2200 for a 9999 asserts a date
            # nobody supplied.
            cases.append(
                pytest.param(name, CEILING, high + 1, None, id=f"{name}_above_its_range")
            )
            cases.append(
                pytest.param(name, FLOOR, low - 1, None, id=f"{name}_below_its_range")
            )
        else:
            ceiling = catalogue._TEXT_CEILINGS[name]
            probe = "a" + "x" * ceiling
            # Strings truncate, at the ceiling and from the front: half a title
            # is still the book, and `books.title` is NOT NULL.
            cases.append(
                pytest.param(
                    name, CEILING, probe, probe[:ceiling], id=f"{name}_past_its_ceiling"
                )
            )
    return cases


def _inside_each_bound() -> list[Any]:
    """The same sides from within, for the diagonal: each has to survive whole.

    The widest value that fits rather than a comfortable one, so a bound off by
    one at either edge is a failure here rather than nowhere.
    """
    cases: list[Any] = []
    for name in _MARC_RECORD_FIELDS:
        if name in catalogue._NUMBER_RANGES:
            low, high = catalogue._NUMBER_RANGES[name]
            cases.append(pytest.param(name, CEILING, high, id=f"{name}_at_its_ceiling"))
            cases.append(pytest.param(name, FLOOR, low, id=f"{name}_at_its_floor"))
        else:
            ceiling = catalogue._TEXT_CEILINGS[name]
            cases.append(
                pytest.param(
                    name, CEILING, "a" + "x" * (ceiling - 1), id=f"{name}_at_its_ceiling"
                )
            )
    return cases


def _is_outside(name: str, side: str, probe: Any) -> bool:
    """Does the probe actually sit past the side of the bound its case claims?

    **The half of the sweep's shape a count cannot state.** A case counted
    against one side while carrying the other side's probe keeps every count
    intact and loses the arm it was named for. Both critic seats found that
    independently on 2026-09-19 and each wrote a different mutation for it: one
    changed `low - 1` to `high + 1` and left the id reading `_below_its_range`,
    the other replaced the floor case with a second copy of the ceiling case,
    id included. Both were green, and with the first in place deleting the `Ge`
    arm of `within_bounds` was no longer caught.

    Read off the same two tables as the probes, so it is a question about the
    case rather than a second copy of the answer.

    **A text probe has to be able to tell the two ends apart**, which is the
    second clause below and not a refinement of the first. Being past the
    ceiling is what makes a probe a probe; being inhomogeneous is what gives its
    assertion any power, because `("x" * n)[:c]` and `("x" * n)[-c:]` are the
    same string, so a truncation taken from the wrong end returns exactly what a
    correct one would. Measured by a critic seat on 2026-09-19: with the probe
    homogeneous, `len(probe) > ceiling` still held, every count and every
    `(name, side)` pair was intact, and truncating from the wrong end passed the
    whole backend suite, 7,548 tests.

    **The family, because it outlives this guard**: where a fixture's *shape* is
    what gives an assertion its discriminating power, the guard has to ask about
    the shape. A check that a probe is on the right side is not a check that it
    can tell the two sides apart, and the shape's reason otherwise lives in a
    docstring, which is the stated rung.
    """
    if name in catalogue._NUMBER_RANGES:
        low, high = catalogue._NUMBER_RANGES[name]
        return probe > high if side == CEILING else probe < low
    ceiling = catalogue._TEXT_CEILINGS[name]
    return len(probe) > ceiling and probe[:ceiling] != probe[-ceiling:]


def _is_at(name: str, side: str, probe: Any) -> bool:
    """The same question for the diagonal: is this the widest value that fits?"""
    if name in catalogue._NUMBER_RANGES:
        low, high = catalogue._NUMBER_RANGES[name]
        return probe == high if side == CEILING else probe == low
    return len(probe) == catalogue._TEXT_CEILINGS[name]


class TestTheSecondBoundHasOneConstructibleBypass:
    """`bounded_fields` bounds a record again, and this is the only thing that sees it.

    **The call changes nothing on any reachable path.** Every producer builds a
    `Record` through `__init__`, so `catalogue.Record.__post_init__` has already
    held every scalar to `_TEXT_CEILINGS` or `_NUMBER_RANGES`, and for all ten
    names those tables equal what `within_bounds` reads: the column width, the
    `BookCreate` `MaxLen` and the `Ge`/`Le`. So `within_bounds` is the identity
    over its whole reachable domain, not merely over a sample, and **no end to
    end test can tell it from `return value`**.

    **Which is why this file has to drive the bypass directly.** Measured by both
    critic seats on 2026-09-19, independently: with the coverage guard rewritten
    to ask `catalogue.py` and nothing left asking `within_bounds`, reducing that
    function to `return value` left the whole backend suite green. "Kept as belt"
    and "dead code" were the same tree. `importing.bounded_fields` names
    `object.__setattr__` on a built record as the constructible bypass; these are
    it.

    Driven over every side of every bound rather than over one field, because a
    bound applied to nine columns and not the tenth is the shape this repository
    keeps finding, and one side of a range and not the other is that argument
    again.
    """

    @pytest.mark.parametrize(
        "generate",
        (
            pytest.param(_outside_each_bound, id="outside"),
            pytest.param(_inside_each_bound, id="inside"),
        ),
    )
    def test_the_sweep_below_reaches_every_side_of_every_bound(self, generate):
        """What the two tests below cannot say about themselves: which sides they
        should have had, and how many of each.

        **Both generators branch on which table names the field, and a lost
        branch is green.** Measured by a critic seat on 2026-09-19: with the text
        arm of `_outside_each_bound` commented out, this file ran 60 tests rather
        than 67 and passed, seven ceilings gone, including every string the belt
        exists for. A parametrised guard is only as wide as its generator, and
        the generator was the one thing nothing asserted. The count lived in
        `tests/COVERAGE.md`, which is a register rather than a check.

        **Keyed on the side as well as the name, because a count is not a
        coverage.** Keyed on the name alone this was green when a floor case was
        replaced by a second ceiling case, and green when a floor case kept its
        id and took the ceiling's probe, which between them are both seats'
        mutations. The side is a case **value** rather than a label: the id
        echoes it for a readable failure and nothing here reads the id, so an id
        left behind by an edit misleads a person and not this test. What stops
        the second mutation is `_is_outside`, asserted per case below.

        Stated as the rule rather than as a number: a range has a ceiling and a
        floor and a text bound has a ceiling, read off the same two tables the
        generators read, so a field moving between them moves this too.
        """
        covered = Counter(case.values[:2] for case in generate())
        sides = Counter(
            (name, side)
            for name in _MARC_RECORD_FIELDS
            for side in (
                (CEILING, FLOOR) if name in catalogue._NUMBER_RANGES else (CEILING,)
            )
        )

        assert covered == sides

    @pytest.mark.parametrize(("name", "side", "probe", "expected"), _outside_each_bound())
    def test_a_field_widened_after_construction_is_held_to_its_bound(
        self, name, side, probe, expected
    ):
        assert _is_outside(name, side, probe), (
            f"{name}'s {side} case carries a probe that is not outside that side, "
            "or that cannot tell one end of a truncation from the other, so it "
            "cannot observe the arm it is counted as covering"
        )

        record = Record(source="dnb", title="A Title")
        object.__setattr__(record, name, probe)

        assert bounded_fields(record)[name] == expected

    @pytest.mark.parametrize(("name", "side", "inside"), _inside_each_bound())
    def test_a_field_inside_its_bound_is_projected_unchanged(self, name, side, inside):
        """The other half of the diagonal, and it is what makes the test above
        mean something: an equality against a derived value is still satisfied by
        a belt that rewrites everything, if nothing asserts what a value that
        fits comes back as."""
        assert _is_at(name, side, inside), (
            f"{name}'s {side} case is not the widest value that side admits, "
            "so a bound off by one there would pass"
        )

        fields: dict[str, Any] = {"source": "dnb", "title": "A Title", name: inside}
        record = Record(**fields)

        assert bounded_fields(record)[name] == inside
