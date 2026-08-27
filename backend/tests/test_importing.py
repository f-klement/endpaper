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

import pytest
from sqlalchemy import event

import csv_import
from enums import OwnershipStatus, ReadStatus, TagCategory
from importing import Import, _CatalogueIndex
from models import Book, Note, Tag, User, UserBook
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
