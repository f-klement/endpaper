"""Tests for backend/serialisation.py: assembling BookOut.

Exercised directly rather than through a route, because the behaviour under
test is the assembly: two of BookOut's fields are not columns, and both depend
on who is asking.
"""

import re

import pytest
from sqlalchemy import event

from enums import ClassificationScheme, ReadStatus
from models import Book, Collection, Loan, Tag, User, UserBook
from schemas import ClassificationOut
from serialisation import (
    book_to_out,
    books_to_out,
    loan_summary,
    match_subjects_to_tags,
    suggested_tag_ids,
)


@pytest.fixture
def two_books(db):
    books = [Book(title="Dune"), Book(title="Neuromancer")]
    db.add_all(books)
    db.commit()
    for book in books:
        db.refresh(book)
    return books


class TestMatchSubjectsToTags:
    def test_it_matches_case_insensitively(self):
        tags = [Tag(id=1, name="Fantasy")]
        assert match_subjects_to_tags(["EPIC FANTASY"], tags) == [1]

    def test_it_ignores_a_parenthetical_suffix_on_the_tag(self):
        """"Young Adult (13-18)" has to match a source saying "young adult"."""
        tags = [Tag(id=7, name="Young Adult (13 to 18)")]
        assert match_subjects_to_tags(["young adult fiction"], tags) == [7]

    def test_no_subjects_matches_nothing(self):
        assert match_subjects_to_tags([], [Tag(id=1, name="Fantasy")]) == []

    def test_an_unrelated_subject_matches_nothing(self):
        assert match_subjects_to_tags(["cookery"], [Tag(id=1, name="Fantasy")]) == []

    @pytest.mark.parametrize(
        ("subject", "tag"),
        [
            ("Software engineering", "War"),
            ("Outer Party", "Art"),
            ("thoughtcrime", "Crime"),
            ("Trous noirs (astronomie)", "Noir"),
            ("Gegenwartsliteratur ab 1945", "Art"),
        ],
    )
    def test_a_tag_name_inside_a_longer_word_is_not_a_match(self, subject, tag):
        """Five live false positives, four English and one German.

        A bare substring match read every one of these as a suggestion, and the
        web client pre-selects them, so they were written unless somebody
        unticked them. Measured 2026-08-24 over 12 English books and 10 German
        ISBNs: 12 of 32 suggestions were wrong, and all 5 of the German ones.
        """
        assert match_subjects_to_tags([subject], [Tag(id=1, name=tag)]) == []

    def test_a_tag_name_ending_in_punctuation_still_matches(self):
        """The boundary is a lookaround rather than `\b`, because `\b` after a
        `+` asserts that a word character follows."""
        assert match_subjects_to_tags(["C++ programming"], [Tag(id=1, name="C++")]) == [1]

    def test_a_plural_subject_no_longer_proposes_the_singular_tag(self):
        """What word boundaries cost, pinned rather than left to be
        rediscovered: `fiction classics` stopped proposing **Classic**, on 2 of
        12 live books. Allowing an optional trailing `s` recovers it and also
        recovers two wrong suggestions, which is why it was not taken."""
        assert match_subjects_to_tags(["fiction classics"], [Tag(id=1, name="Classic")]) == []


class TestSuggestedTagIds:
    """Two routes to one list, and they fail on opposite records."""

    TAGS = [Tag(id=1, name="Computing"), Tag(id=2, name="Fiction")]

    def _ddc(self, number: str) -> ClassificationOut:
        return ClassificationOut(scheme=ClassificationScheme.DDC, number=number)

    def test_an_english_caption_still_matches_by_name(self):
        assert suggested_tag_ids(["Computing"], [], self.TAGS) == [1]

    def test_a_german_record_resolves_through_its_number(self):
        """"004 Informatik" matches no English tag name, and this is the whole
        reason the number is stored."""
        assert suggested_tag_ids(["Informatik"], [self._ddc("004")], self.TAGS) == [1]

    def test_a_tag_found_by_both_routes_is_suggested_once(self):
        assert suggested_tag_ids(["Computing"], [self._ddc("004")], self.TAGS) == [1]

    def test_an_lcc_number_is_not_projected(self):
        """Only DDC has a division mapping short enough to ship."""
        entry = ClassificationOut(
            scheme=ClassificationScheme.LCC, number="QA76.73.P98"
        )
        assert suggested_tag_ids([], [entry], self.TAGS) == []

    def test_a_number_with_no_mapped_tag_suggests_nothing(self):
        assert suggested_tag_ids([], [self._ddc("040")], self.TAGS) == []

    def test_nothing_at_all_suggests_nothing(self):
        assert suggested_tag_ids([], [], self.TAGS) == []


class TestLoanSummary:
    def test_it_leaves_the_book_out(self, db, admin, member, two_books):
        """The caller is already holding the book this loan belongs to, and
        populating it would trigger a lazy load per book."""
        loan = Loan(
            book_id=two_books[0].id,
            loaned_to_user_id=member["user"]["id"],
            loaned_by_user_id=admin["user"]["id"],
        )
        db.add(loan)
        db.commit()

        assert loan_summary(loan).book is None

    def test_it_carries_an_external_borrower_name(self, db, admin, two_books):
        """Without this the badge on a book lent to a neighbour reads "Loaned
        to" and then nothing."""
        loan = Loan(
            book_id=two_books[0].id,
            loaned_to_name="the neighbour",
            loaned_by_user_id=admin["user"]["id"],
        )
        db.add(loan)
        db.commit()

        summary = loan_summary(loan)
        assert summary.loaned_to_name == "the neighbour"
        assert summary.loaned_to is None


class TestBooksToOut:
    def test_an_empty_page_costs_no_queries(self, db, admin):
        user = db.get(User, admin["user"]["id"])
        assert books_to_out([], user, db) == []

    def test_a_book_nobody_has_touched_reads_as_unread(self, db, admin, two_books):
        """A user_books row only appears once a status is set, so absence is
        the common case rather than an edge one."""
        user = db.get(User, admin["user"]["id"])

        out = book_to_out(two_books[0], user, db)

        assert out.my_status is ReadStatus.UNREAD
        assert out.my_rating is None
        assert out.active_loan is None

    def test_the_status_is_coerced_back_to_the_enum(self, db, admin, two_books):
        """The column is a plain VARCHAR. Assigning the str onto an enum-typed
        Pydantic field skips validation and serialises with a warning."""
        user = db.get(User, admin["user"]["id"])
        db.add(UserBook(user_id=user.id, book_id=two_books[0].id, status="read"))
        db.commit()

        out = book_to_out(two_books[0], user, db)

        assert out.my_status is ReadStatus.READ

    def test_two_accounts_see_the_same_row_differently(self, db, admin, member, two_books):
        """The reason a BookOut must never be cached across users."""
        them = db.get(User, member["user"]["id"])
        me = db.get(User, admin["user"]["id"])
        db.add(UserBook(user_id=me.id, book_id=two_books[0].id, status="read"))
        db.commit()

        assert book_to_out(two_books[0], me, db).my_status is ReadStatus.READ
        assert book_to_out(two_books[0], them, db).my_status is ReadStatus.UNREAD

    def test_a_page_costs_the_same_whatever_its_size(self, db, admin, two_books):
        """The N+1 this function exists to avoid, pinned by measurement rather
        than by reading. Listing 25 books cost 53 SELECTs once. It had already
        come back by a different door when this test was written: `BookOut`
        reads `book.tags`, which is lazy, so a page cost one more query per
        book on top of the constant three."""
        user = db.get(User, admin["user"]["id"])
        # Touch every column first. The rows expired at the last commit, so
        # otherwise the first call pays for reloading them and the measurement
        # is of the ORM's identity map rather than of this function.
        for book in two_books:
            _ = book.title

        statements: list[str] = []

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def record(conn, cursor, statement, *args):
            statements.append(statement)

        try:
            books_to_out(two_books, user, db)
            for_two = len(statements)
            statements.clear()
            books_to_out(two_books[:1], user, db)
            for_one = len(statements)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)

        assert for_two == for_one

    def test_the_number_in_the_docstring_is_the_number_it_costs(self, db, admin, two_books):
        """The count is stated in prose, and a number in prose goes stale.

        Three times in this repository a stated figure disagreed with the code,
        so the sentence a reader believes is read back here rather than
        trusted. The relative measurements below catch a new *per book* query;
        only this one catches a new constant one.

        The page holds no copy and no filed book, which are the two conditional
        statements the docstring accounts for separately, and the books were
        added by nobody, so no `added_by` row is lazily loaded.
        """
        user = db.get(User, admin["user"]["id"])
        for book in two_books:
            _ = book.title
        # A first call outside the measured window. The last commit left the
        # session needing a fresh savepoint, and the listener counts it.
        books_to_out(two_books, user, db)

        statements: list[str] = []

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def record(conn, cursor, statement, *args):
            statements.append(statement)

        try:
            books_to_out(two_books, user, db)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)

        stated = re.search(r"\*\*(\d+)\*\* statements", books_to_out.__doc__ or "")
        assert stated is not None, "books_to_out no longer states a count"
        assert len(statements) == int(stated.group(1))


class TestCopyCount:
    """`copy_count` is 1 for almost every book, and the number is what stops the
    grid looking like it has double-added something."""

    def test_a_book_with_no_group_reads_one(self, db, admin, two_books):
        user = db.get(User, admin["user"]["id"])
        assert book_to_out(two_books[0], user, db).copy_count == 1

    def test_two_rows_sharing_a_group_read_two(self, db, admin, two_books):
        for book in two_books:
            book.copy_group = "abc123"
        db.commit()
        user = db.get(User, admin["user"]["id"])

        assert book_to_out(two_books[0], user, db).copy_count == 2

    def test_it_counts_only_what_the_caller_may_see(self, db, admin, member, two_books):
        """A member who makes their own copy private does not thereby announce
        it on everybody else's card."""
        for book in two_books:
            book.copy_group = "abc123"
        two_books[1].is_private = True
        two_books[1].added_by_user_id = admin["user"]["id"]
        db.commit()
        them = db.get(User, member["user"]["id"])

        assert book_to_out(two_books[0], them, db).copy_count == 1

    def test_it_costs_exactly_one_extra_statement(self, db, admin, two_books):
        """The measurement behind the count in `books_to_out`'s docstring.

        Seven statements for a page of ordinary books, eight when something on
        it is a copy, and nothing at all for the overwhelming majority of pages
        where no book carries a group. A per-book query here would be the exact
        N+1 that module exists to avoid.

        Both pages are prepared before either is measured, and nothing commits
        in between. A commit inside the measured window makes the session open
        a fresh savepoint on its next statement, and that savepoint is counted
        as a query by the listener: the first version of this test read the
        difference as two.
        """
        pair = [Book(title="Dune", copy_group="abc123"), Book(title="Dune", copy_group="abc123")]
        db.add_all(pair)
        db.commit()
        user = db.get(User, admin["user"]["id"])
        for book in [*two_books, *pair]:
            _ = book.title

        statements: list[str] = []

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def record(conn, cursor, statement, *args):
            statements.append(statement)

        try:
            books_to_out(two_books, user, db)
            without = len(statements)
            statements.clear()
            books_to_out(pair, user, db)
            with_copies = len(statements)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)

        assert with_copies == without + 1


class TestCollectionName:
    """The name is a projection of the row `collection_id` points at, batched
    for the page. Nothing writes it, so a rename is visible on the next fetch
    without anything being migrated."""

    def test_an_unfiled_book_carries_no_name(self, db, admin, two_books):
        user = db.get(User, admin["user"]["id"])
        out = book_to_out(two_books[0], user, db)

        assert out.collection_id is None
        assert out.collection_name is None

    def test_a_filed_book_carries_the_name(self, db, admin, two_books):
        shelf = Collection(name="Ebooks")
        db.add(shelf)
        db.commit()
        two_books[0].collection_id = shelf.id
        db.commit()
        user = db.get(User, admin["user"]["id"])

        assert book_to_out(two_books[0], user, db).collection_name == "Ebooks"

    def test_it_costs_exactly_one_extra_statement(self, db, admin, two_books):
        """The measurement behind the count in `books_to_out`'s docstring, and
        the reason the name is not read through `Book.collection`: a lazy
        relationship would issue one statement per filed book on the page.

        Prepared the same way as the copy-count measurement above, and for the
        same reason: a commit inside the measured window would be counted as a
        query when the session opens its next savepoint.
        """
        shelf = Collection(name="Ebooks")
        db.add(shelf)
        db.commit()
        filed = [
            Book(title="One", collection_id=shelf.id),
            Book(title="Two", collection_id=shelf.id),
        ]
        db.add_all(filed)
        db.commit()
        user = db.get(User, admin["user"]["id"])
        for book in [*two_books, *filed]:
            _ = book.title

        statements: list[str] = []

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def record(conn, cursor, statement, *args):
            statements.append(statement)

        try:
            books_to_out(two_books, user, db)
            without = len(statements)
            statements.clear()
            books_to_out(filed, user, db)
            with_collections = len(statements)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)

        assert with_collections == without + 1


class TestWhoWantsToBeAsked:
    """`discuss_with` is the one per-member field on this payload that is not
    scoped to the caller, and the reason is the whole feature: a marker only
    its owner can see is not a way to be asked about anything."""

    def test_nobody_offered_is_an_empty_list(self, db, admin, two_books):
        user = db.get(User, admin["user"]["id"])
        out = book_to_out(two_books[0], user, db)
        assert out.my_wants_to_discuss is False
        assert out.discuss_with == []

    def test_it_carries_another_members_offer(self, db, admin, member, two_books):
        me = db.get(User, admin["user"]["id"])
        them = db.get(User, member["user"]["id"])
        db.add(UserBook(user_id=them.id, book_id=two_books[0].id, wants_to_discuss=True))
        db.commit()

        out = book_to_out(two_books[0], me, db)

        assert out.my_wants_to_discuss is False
        assert [user.username for user in out.discuss_with] == ["member"]

    def test_it_does_not_bleed_between_books_on_a_page(
        self, db, admin, member, two_books
    ):
        me = db.get(User, admin["user"]["id"])
        them = db.get(User, member["user"]["id"])
        db.add(UserBook(user_id=them.id, book_id=two_books[1].id, wants_to_discuss=True))
        db.commit()

        first, second = books_to_out(two_books, me, db)

        assert first.discuss_with == []
        assert [user.username for user in second.discuss_with] == ["member"]

    def test_a_row_with_the_flag_off_is_not_listed(self, db, admin, two_books):
        user = db.get(User, admin["user"]["id"])
        db.add(
            UserBook(
                user_id=user.id,
                book_id=two_books[0].id,
                status=ReadStatus.READ,
                wants_to_discuss=False,
            )
        )
        db.commit()

        assert book_to_out(two_books[0], user, db).discuss_with == []


class TestDerivedPercent:
    """`page / page_count`, else the recorded percent, else nothing.

    Derived on every read rather than stored beside the position, so a metadata
    refresh that corrects a page count corrects every bar with it.
    """

    def test_a_page_against_a_known_count(self):
        from serialisation import derived_percent

        assert derived_percent(50, None, 200) == 25

    def test_a_page_with_no_count_derives_nothing(self):
        """Which is why an audiobook records a percent instead."""
        from serialisation import derived_percent

        assert derived_percent(50, None, None) is None

    def test_a_zero_page_count_is_treated_as_unknown(self):
        from serialisation import derived_percent

        assert derived_percent(50, None, 0) is None

    def test_a_recorded_percent_is_used_as_is(self):
        from serialisation import derived_percent

        assert derived_percent(None, 40, 200) == 40

    def test_nothing_recorded_derives_nothing(self):
        from serialisation import derived_percent

        assert derived_percent(None, None, 200) is None

    def test_a_page_past_the_count_clamps(self):
        """Provider page counts are off by one often enough that the last page
        computes past 100."""
        from serialisation import derived_percent

        assert derived_percent(205, None, 200) == 100
