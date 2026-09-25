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

import ast
import inspect
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import event

import catalogue
import csv_import
import importing
import marc
import tags
from catalogue import Record
from enums import OwnershipStatus, ReadStatus, TagCategory
from importing import (
    _MARC_RECORD_FIELDS,
    Import,
    MarcImport,
    MarcIndex,
    OpdsImport,
    _CatalogueIndex,
    _settle_one,
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

    def test_a_full_book_does_not_spend_the_budget(self, db, member):
        """The room check comes before the mint, and this is what it buys. A Book
        already at its ceiling that minted first would invent Library wide tags
        it is then refused, so a later Book in the same file loses tags to one
        that could not carry them."""
        book = Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id)
        db.add(book)
        for index in range(tags.MAX_TAGS_PER_BOOK):
            filler = Tag(name=f"filler {index}", category=TagCategory.CUSTOM)
            db.add(filler)
            book.tags.append(filler)
        db.commit()
        before = db.query(Tag).count()

        Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelves="one,two,three")),
            apply_tags=True,
        )

        assert db.query(Tag).count() == before

    def test_it_stops_inventing_rather_than_failing(self, db, member):
        """Past the cap the Books in the file are still worth having."""
        many = ",".join(f"tag{n}" for n in range(tags.MAX_NEW_TAGS_PER_IMPORT + 20))
        db.add(Book(title="Dune", isbn="9780441013593", added_by_user_id=member.id))
        db.commit()

        result = Import.for_member(db, member.id).apply(
            parse(row("Dune", isbn="9780441013593", shelves=many)), apply_tags=True
        )

        assert result.matched == 1
        invented = db.query(Tag).filter(Tag.name.like("tag%")).count()
        assert invented <= tags.MAX_NEW_TAGS_PER_IMPORT

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


def catalogued(title: str, *, author: str | None = None, isbn: str | None = None):
    """One record as `marc.read` would produce it."""
    return Record(source="marc", title=title, author=author, isbn=isbn)


def one_marc_file(*records: Record, skipped: int = 0) -> marc.ParsedMarc:
    return marc.ParsedMarc(records=records, skipped=skipped)


class TestTheMarcPrivateBookOracle:
    """A record whose ISBN belongs to a Book this Member cannot see.

    **The arm this file was missing.** It was reachable only through a route,
    where a status code and a file upload sit between the rule and the
    assertion, while the other two importers were driven here directly. The
    refusal is one function now, so the three arms are the same rule read three
    ways rather than three implementations, and this one closes the hole rather
    than replacing what is already in `tests/routers/test_imports_marc.py`.
    """

    def test_it_is_skipped_rather_than_raising_on_the_unique_index(self, db, member, other):
        db.add(Book(title="Hidden", isbn="9780552152976", is_private=True,
                    added_by_user_id=other.id))
        db.commit()

        result = MarcImport.for_member(db, member.id).apply(
            one_marc_file(catalogued("Small Gods", author="T Pratchett",
                                     isbn="9780552152976"))
        )

        assert (result.created, result.skipped) == (0, 1)

    def test_its_title_is_never_reported(self, db, member, other):
        db.add(Book(title="Hidden", isbn="9780552152976", is_private=True,
                    added_by_user_id=other.id))
        db.commit()

        result = MarcImport.for_member(db, member.id).apply(
            one_marc_file(catalogued("Small Gods", author="T Pratchett",
                                     isbn="9780552152976"))
        )

        assert result.unmatched_titles == []

    def test_the_rest_of_the_file_still_lands(self, db, member, other):
        """One record that cannot be acted on is counted and skipped, never a
        failed transfer."""
        db.add(Book(title="Hidden", isbn="9780552152976", is_private=True,
                    added_by_user_id=other.id))
        db.commit()

        result = MarcImport.for_member(db, member.id).apply(
            one_marc_file(
                catalogued("Small Gods", author="T Pratchett", isbn="9780552152976"),
                catalogued("Good Omens", author="T Pratchett"),
            )
        )

        assert (result.created, result.skipped) == (1, 1)

    def test_a_visible_book_with_the_same_isbn_is_matched_not_skipped(self, db, member):
        """The refusal is about what the Member cannot see, never about the
        ISBN being known."""
        db.add(Book(title="Small Gods", isbn="9780552152976", added_by_user_id=member.id))
        db.commit()

        result = MarcImport.for_member(db, member.id).apply(
            one_marc_file(catalogued("Small Gods", author="T Pratchett",
                                     isbn="9780552152976"))
        )

        assert (result.matched, result.created, result.skipped) == (1, 0, 0)


class _TakenIsbns:
    """An index that answers the one question the spine asks it."""

    def __init__(self, *taken: str) -> None:
        self._taken = set(taken)

    def isbn_is_taken(self, isbn: str | None) -> bool:
        return bool(isbn) and isbn in self._taken


def _refuse_to_create() -> Book:
    raise AssertionError("the spine created a Book it should have refused")


def _refuse_to_fill(book: Book) -> None:
    raise AssertionError("the spine filled gaps on a row it did not match")


class TestTheSpine:
    """`_settle_one` driven directly, with no database and no importer.

    The three behavioural classes above say each importer obeys the rule; these
    say what the rule is, in the one place it is now written.
    """

    def test_a_taken_isbn_is_counted_and_never_created(self):
        tally = importing._Tally()

        book = _settle_one(
            _TakenIsbns("9780552152976"),
            tally,
            None,
            isbn="9780552152976",
            unmatched_title="Small Gods",
            create=_refuse_to_create,
            fill_gaps=_refuse_to_fill,
            create_missing=True,
        )

        assert book is None
        assert (tally.unmatched_private, tally.created) == (1, 0)

    def test_a_taken_isbn_is_never_named(self):
        """The whole of the privacy rule: naming it answers "does a Book with
        this ISBN exist in this house"."""
        tally = importing._Tally()

        _settle_one(
            _TakenIsbns("9780552152976"),
            tally,
            None,
            isbn="9780552152976",
            unmatched_title="Small Gods",
            create=_refuse_to_create,
            fill_gaps=_refuse_to_fill,
            create_missing=True,
        )

        assert tally.unmatched == []

    def test_a_caller_that_asked_for_no_creations_still_reports_a_taken_isbn(self):
        """**The refusal is about the create, not about the ISBN.** With
        nothing to create, the title came off the caller's own file and telling
        them about it discloses nothing they did not upload. Pinned because a
        spine that hoisted the check out of the create arm would silently turn
        this row into a refusal and cost the CSV path its unmatched report."""
        tally = importing._Tally()

        _settle_one(
            _TakenIsbns("9780552152976"),
            tally,
            None,
            isbn="9780552152976",
            unmatched_title="Small Gods",
            create=_refuse_to_create,
            fill_gaps=_refuse_to_fill,
            create_missing=False,
        )

        assert (tally.unmatched, tally.unmatched_private) == (["Small Gods"], 0)

    def test_the_unmatched_report_stops_at_the_cap(self):
        tally = importing._Tally()
        for n in range(importing.MAX_UNMATCHED_REPORTED + 5):
            _settle_one(
                _TakenIsbns(),
                tally,
                None,
                isbn=None,
                unmatched_title=f"Title {n}",
                create=_refuse_to_create,
                fill_gaps=_refuse_to_fill,
                create_missing=False,
            )

        assert len(tally.unmatched) == importing.MAX_UNMATCHED_REPORTED

    def test_a_matched_row_fills_its_gaps_and_comes_back_for_the_tail(self):
        tally = importing._Tally()
        matched = Book(title="Small Gods")
        filled: list[Book] = []

        book = _settle_one(
            _TakenIsbns("9780552152976"),
            tally,
            matched,
            isbn="9780552152976",
            unmatched_title="Small Gods",
            create=_refuse_to_create,
            fill_gaps=filled.append,
            create_missing=True,
        )

        assert book is matched
        assert filled == [matched]
        assert (tally.matched, tally.unmatched_private) == (1, 0)


SPINE = "_settle_one"


def _creates_outside_the_spine(source: str, spine: str = SPINE) -> list[str]:
    """Every Book construction in `source` on a path the spine does not hold,
    qualified by the class and function it sits in.

    A constructor is any function whose body contains a `Book(...)` call. Two
    ways out of the spine are reported and the second is why there are two:

    * **a call to a constructor that is not sheltered.** Sheltered means the
      call sits inside the spine's `create` argument and no other, which is
      what a `create=lambda: ...` is. The other arguments are not shelter:
      `fill_gaps` runs on the matched arm, past the refusal.
    * **a constructor nothing in the module calls or names.** An `apply` entry
      point is exactly such a function, so a bare `Book(` written straight into
      the import loop has no call site to catch and the first check sees
      nothing. **Named counts as well as called**, so handing the builder to
      the spine through a partial rather than a lambda is the same shelter.
      Without this one the pass was blind in the plainest spelling it exists
      to see, and its own blind spot list excused the hole.

    **The classes are nowhere in this function**, so a fourth importer is
    covered whatever it names things. **The constructor set is not derived from
    a property though**, and the pack that said otherwise was wrong: it matches
    the literal name `Book`, which is source text matching, so an import
    aliased to another name is invisible. That is the known cost of the one
    matched token here, and it is stated rather than bounded.

    **The rest of what it cannot see**, likewise stated:

    * one source at a time, so an importer written in another module is
      invisible to it;
    * a create that never constructs a `Book` at all: a helper elsewhere, a
      `merge`, a bulk insert, or an ORM call spelled some other way;
    * a call spelled other than `self.X(...)`, through another object or a
      module level name, still keys to the bare name, so two functions sharing
      that name share a verdict about whether anything calls them. **`_create`
      is the collision to expect**: all three importers use it and a fourth
      will copy it, which is why `self.X(...)` is keyed to its class;
    * whether the refusal inside the spine is right. It says the create is
      routed, and the behavioural classes above say what routing it buys.
    """
    tree = ast.parse(source)
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def qualified(node: ast.AST) -> str:
        parts: list[str] = []
        cursor: ast.AST | None = node
        while cursor is not None:
            if isinstance(cursor, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                parts.append(cursor.name)
            cursor = parents.get(id(cursor))
        return ".".join(reversed(parts)) or "<module>"

    constructors = [
        function
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "Book"
            for call in ast.walk(function)
        )
    ]
    constructor_names = {function.name for function in constructors}

    def owner(node: ast.AST) -> str | None:
        cursor: ast.AST | None = parents.get(id(node))
        while cursor is not None:
            if isinstance(cursor, ast.ClassDef):
                return cursor.name
            cursor = parents.get(id(cursor))
        return None

    sheltered: set[int] = set()
    named_builders: set[str] = set()
    for call in ast.walk(tree):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == spine
        ):
            # **Only the `create` argument shelters, because only `create`
            # sits behind the refusal.** `fill_gaps` runs on the matched arm,
            # where the predicate is never reached, so a Book minted through
            # that callable has gone round the rule while sitting inside the
            # spine call. Sheltering the whole call read as obvious and checked
            # nothing: the next reader's instinct is that the spine call is the
            # spine call, and it is not.
            #
            # **Reading the keyword alone cannot miss a legal call**, because
            # `_settle_one` declares `create` after a bare `*`, so there is no
            # positional spelling of it to overlook.
            #
            # **A builder the argument names rather than calls is sheltered
            # too**, which is what `create=partial(self._create, row, index)`
            # is: the same shelter, spelled without a call. Only the naming is
            # recorded here, because the no call site check below would
            # otherwise see a builder nothing calls and report a legal
            # spelling. A guard that reddens on correct code is what teaches
            # the next reader to weaken the rule instead of obeying it.
            for word in call.keywords:
                if word.arg != "create":
                    continue
                sheltered.update(id(node) for node in ast.walk(word.value))
                for node in ast.walk(word.value):
                    if (
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                    ):
                        here = owner(node)
                        named_builders.add(
                            f"{here}.{node.attr}" if here else node.attr
                        )

    def called(call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        if isinstance(call.func, ast.Name):
            return call.func.id
        return None

    def resolved(call: ast.Call) -> str | None:
        """A call keyed so that one class's method is not another's.

        **`self.X(...)` keys to the class it is written in**, because the bare
        name does not distinguish them and `_create` is the name every importer
        here already uses. A fourth one whose builder is called from another
        module has no local call site, and under the bare name it borrowed the
        three existing calls and went unreported. Anything else keys to its own
        name, which is the conservative answer: it can fail to exclude, never
        fail to report.
        """
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "self"
        ):
            here = owner(call)
            return f"{here}.{call.func.attr}" if here else call.func.attr
        return called(call)

    def own_key(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        here = owner(function)
        return f"{here}.{function.name}" if here else function.name

    everything_called = {
        resolved(call) for call in ast.walk(tree) if isinstance(call, ast.Call)
    } | named_builders

    return sorted(
        {
            qualified(call)
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and called(call) in constructor_names
            and id(call) not in sheltered
        }
        | {
            qualified(function)
            for function in constructors
            if own_key(function) not in everything_called
        }
    )


def _importers_that_never_reach_the_spine(source: str, spine: str = SPINE) -> list[str]:
    """Every class in `source` offering `apply` and never calling the spine.

    The population is again a property: a class with an `apply` method is what
    an importer is here, so the fourth one is covered without an arm. It sees
    nothing outside the source it is handed, and a class that reaches the spine
    on one path and not another looks clean to it.
    """
    tree = ast.parse(source)
    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        offers_apply = any(
            isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name == "apply"
            for item in node.body
        )
        if not offers_apply:
            continue
        reaches = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == spine
            for call in ast.walk(node)
        )
        if not reaches:
            missing.append(node.name)
    return sorted(missing)


A_FOURTH_IMPORTER_WRITING_THE_BRANCH_BY_HAND = '''
class OaiImport:
    def apply(self, records, *, create_missing=True):
        for record in records:
            self._apply_one(record, create_missing)

    def _apply_one(self, record, create_missing):
        book = self._index.find(self._db, record)
        if book is None and create_missing and self._index.isbn_is_taken(record.isbn):
            return
        if book is None and create_missing:
            self._mint(record)

    def _mint(self, record):
        book = Book(title=record.title)
        self._db.add(book)
        return book
'''

A_FOURTH_IMPORTER_ROUTED_THROUGH_THE_SPINE = '''
class OaiImport:
    def apply(self, records, *, create_missing=True):
        for record in records:
            self._apply_one(record, create_missing)

    def _apply_one(self, record, create_missing):
        _settle_one(
            self._index,
            self._tally,
            self._index.find(self._db, record),
            isbn=record.isbn,
            unmatched_title=record.title,
            create=lambda: self._mint(record),
            fill_gaps=lambda matched: _fill_oai_gaps(matched, record),
            create_missing=create_missing,
        )

    def _mint(self, record):
        book = Book(title=record.title)
        self._db.add(book)
        return book
'''

A_FOURTH_IMPORTER_BUILDING_A_BOOK_IN_ITS_OWN_LOOP = '''
class OaiImport:
    def apply(self, records, *, create_missing=True):
        for record in records:
            if create_missing:
                self._db.add(Book(title=record.title))
'''

A_FOURTH_IMPORTER_WHOSE_BUILDER_COLLIDES = '''
class OpdsImport:
    def apply(self, records):
        for record in records:
            self._apply_one(record)

    def _apply_one(self, record):
        _settle_one(
            self._index,
            self._tally,
            None,
            isbn=record.isbn,
            unmatched_title=record.title,
            create=lambda: self._create(record),
            fill_gaps=lambda matched: None,
            create_missing=True,
        )

    def _create(self, record):
        book = Book(title=record.title)
        self._db.add(book)
        return book


class OaiImport:
    def apply(self, records):
        harvest.drive(self, records)

    def _create(self, record):
        book = Book(title=record.title)
        self._db.add(book)
        return book
'''

A_FOURTH_IMPORTER_MINTING_ON_THE_MATCHED_ARM = '''
class OaiImport:
    def apply(self, records, *, create_missing=True):
        for record in records:
            self._apply_one(record, create_missing)

    def _apply_one(self, record, create_missing):
        _settle_one(
            self._index,
            self._tally,
            self._index.find(self._db, record),
            isbn=record.isbn,
            unmatched_title=record.title,
            create=lambda: self._mint(record),
            fill_gaps=lambda matched: self._mint_a_companion(record),
            create_missing=create_missing,
        )

    def _mint(self, record):
        book = Book(title=record.title)
        self._db.add(book)
        return book

    def _mint_a_companion(self, record):
        book = Book(title=record.title + " (companion)")
        self._db.add(book)
        return book
'''

A_FOURTH_IMPORTER_HANDING_ITS_BUILDER_OVER = '''
class OaiImport:
    def apply(self, records, *, create_missing=True):
        for record in records:
            self._apply_one(record, create_missing)

    def _apply_one(self, record, create_missing):
        _settle_one(
            self._index,
            self._tally,
            self._index.find(self._db, record),
            isbn=record.isbn,
            unmatched_title=record.title,
            create=functools.partial(self._mint, record),
            fill_gaps=lambda matched: None,
            create_missing=create_missing,
        )

    def _mint(self, record):
        book = Book(title=record.title)
        self._db.add(book)
        return book
'''


class TestEveryImporterCreatesThroughTheSpine:
    """The class this stops returning is **a fourth importer whose privacy
    branch is written by hand**.

    It was written by hand three times and the three agreed; the fourth is the
    one that would not, and an enumerated guard naming the three would have had
    nothing to say about it. Both passes below derive their population from the
    module, so the arm count does not move when an importer arrives.

    **The first pass is over every Book construction in the module, which is
    wider than the importers**, and the arm is named for that rather than for
    this class. A construction here that is not an importer's is still a Book
    on a path the spine does not hold.

    Deleting `_settle_one`'s `isbn_is_taken` call does not redden these: they
    are about the route, and `TestTheSpine` is about the rule. Both are needed
    and neither covers the other.
    """

    def test_no_book_is_constructed_off_the_spine(self):
        assert _creates_outside_the_spine(inspect.getsource(importing)) == []

    def test_every_class_offering_apply_calls_the_spine(self):
        assert _importers_that_never_reach_the_spine(inspect.getsource(importing)) == []

    def test_a_fourth_importer_writing_the_branch_by_hand_is_named(self):
        assert _creates_outside_the_spine(
            A_FOURTH_IMPORTER_WRITING_THE_BRANCH_BY_HAND
        ) == ["OaiImport._apply_one"]

    def test_a_fourth_importer_that_never_calls_the_spine_is_named(self):
        assert _importers_that_never_reach_the_spine(
            A_FOURTH_IMPORTER_WRITING_THE_BRANCH_BY_HAND
        ) == ["OaiImport"]

    def test_a_fourth_importer_building_a_book_in_its_own_loop_is_named(self):
        """**The arm the first version of this pass did not have.** It reported
        call sites of constructors and an `apply` entry point has none, so a
        bare `Book(` written straight into the import loop was green: the
        plainest spelling of the thing the guard exists to catch."""
        assert _creates_outside_the_spine(
            A_FOURTH_IMPORTER_BUILDING_A_BOOK_IN_ITS_OWN_LOOP
        ) == ["OaiImport.apply"]

    def test_a_fourth_importer_whose_builder_shares_a_name_is_still_named(self):
        """**The name alone used to flip the verdict.** `_create` is what all
        three importers call their builder and what a fourth will copy. Keyed
        by the bare name, a fourth one whose builder is driven from another
        module borrowed the three existing call sites and went unreported,
        while the same function called `_mint` was caught. The call site is
        keyed to the class it is written in, so the borrowing stops."""
        assert _creates_outside_the_spine(A_FOURTH_IMPORTER_WHOSE_BUILDER_COLLIDES) == [
            "OaiImport._create"
        ]

    def test_a_book_minted_on_the_matched_arm_is_named(self):
        """**Sitting inside the spine call is not the same as sitting behind
        the refusal.** `fill_gaps` runs only where a Book was already matched,
        so the privacy predicate is never reached on that path. A pass that
        sheltered every argument of the spine call reported this clean, which
        is the guard agreeing with its own name rather than with the rule."""
        assert _creates_outside_the_spine(
            A_FOURTH_IMPORTER_MINTING_ON_THE_MATCHED_ARM
        ) == ["OaiImport._apply_one"]

    def test_a_builder_handed_over_rather_than_called_is_clean(self):
        """`create=partial(self._mint, record)` is the same shelter spelled
        without a call, and the pass used to report it: the walk follows calls,
        so a builder that is only named had no call site and the no call site
        check fired. **A guard that reddens on a legal spelling is the half an
        author never looks for**, and it is a trap laid for whoever converts a
        lambda to a partial and reads the red as the guard being wrong."""
        assert _creates_outside_the_spine(A_FOURTH_IMPORTER_HANDING_ITS_BUILDER_OVER) == []

    def test_a_fourth_importer_routed_through_the_spine_is_clean(self):
        """The other half of the diagonal. Without it a pass that named every
        class it read would score both catches above and mean nothing."""
        assert _creates_outside_the_spine(A_FOURTH_IMPORTER_ROUTED_THROUGH_THE_SPINE) == []
        assert _importers_that_never_reach_the_spine(
            A_FOURTH_IMPORTER_ROUTED_THROUGH_THE_SPINE
        ) == []
