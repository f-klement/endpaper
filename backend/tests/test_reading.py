"""Tests for backend/reading.py: the seam every `user_books` row goes through.

Two kinds of test, the same split `test_shelf.py` uses.

`TestReadingIsTheOnlyWayIn` is the **house rule**, and it is one pass where the
Shelf's is three. The reason is not that this table matters less. It is that
the only module in the tree that reaches `user_books` from a query rooted
somewhere else is `shelf.py`, which is allowlisted anyway: its three Book
listing filters join the table, and that is the Shelf's rule rather than this
one. With that module named, an import of `UserBook` is a fair proxy for a
query over it, because there is nothing left that could hold one without
binding the name.

That reasoning was wrong in an earlier draft of this docstring, which said
"nothing filters on `UserBook` from another query" three lines above an
allowlist entry that exists precisely because `shelf.py` does. The proxy
survived the correction; the justification for it changed.

**The pass resolves an aliased import**, so `from models import UserBook as UB`
is caught. That is not a flourish: the first version keyed on
`alias.asname or alias.name`, which yields `{"UB"}` for exactly that line and
reports it clean. `test_shelf.py` resolves the same shape deliberately and has
two further passes behind it if the resolution ever misses; here there is no
backstop, so the one pass has to be right. `EVASIONS` pins it.

**What the proxy does not catch**, stated because a guard whose limits are
undocumented gets read as a guarantee it never made:

* `models.UserBook` reached through `import models`. Nothing this rule covers
  imports `models` as a module, and the same shape evades `test_shelf.py`'s
  import pass too, where it is caught by the query pass instead. Here it would
  not be.
* Raw SQL naming `user_books`. Invisible to any rule that reads names.
* `book.user_books` or `user.user_books`, the relationships on the two parent
  models. Those are a lazy load off a row somebody already holds, not a query
  a rule of this shape can see, and the Book they hang off has already been
  through the Shelf. The one to watch for is a loop over `book.user_books`
  reading somebody else's rating.

**A star import is caught, from every module that could launder the name.**
`from models import *` binds `UserBook`, and so does a star from any module
that has already imported it: measured at the tip, `UserBook` is in `dir()` of
all four of `models`, `shelf`, `reading` and `backup`. Those four are exactly
the allowlist, which is not a coincidence and is the point: the modules
permitted to hold the name are the modules a star can launder it through, so
expanding only `models` left the other three open while the docstring claimed
the shape was closed. `_STAR_SOURCES` is derived from the allowlist rather than
written out, so adding a fifth allowlist entry cannot reopen the hole.

The rest of the file tests behaviour.
"""

import ast
import importlib
from pathlib import Path

import pytest
from sqlalchemy import event

from enums import ReadStatus
from models import Book, User
from reading import Reading, discussers, resolve_merge
from shelf import Shelf

BACKEND = Path(__file__).resolve().parent.parent

#: Where `UserBook` may be imported.
#:
#: `models.py` defines it. `reading.py` owns it. `shelf.py` joins it in three
#: places to narrow a listing of Books, which is the Shelf's own rule and not
#: this one. `backup.py` names it in `_TABLES` so a restore cannot lose a
#: table, which is the same third-way-past-a-viewer `test_shelf.py` documents.
READING_RECORD_READERS = {"models.py", "reading.py", "shelf.py", "backup.py"}

#: The modules a `from ... import *` can bind `UserBook` through.
#:
#: **Derived from the allowlist, not written out.** A module allowed to import
#: the name re-exports it, so the set of modules a star can launder it through
#: is exactly the set allowed to hold it: measured at the tip, `UserBook` is in
#: `dir()` of all four. Deriving it means a fifth allowlist entry cannot reopen
#: the hole by being forgotten here. It assumes a top-level module, which every
#: entry is; a `routers/` path would need the dotted name instead.
_STAR_SOURCES = {name.removesuffix(".py") for name in READING_RECORD_READERS}


def _imported_names(source: str) -> set[str]:
    """Every name one module imports, under both its spellings.

    **The imported name and the local alias**, not one or the other.
    `alias.asname or alias.name` is the idiom this started with and it is the
    wrong half here: `from models import UserBook as UB` binds `UB` and imports
    `UserBook`, and a rule asking "does this module reach the reading record"
    wants the second. `test_shelf.py` asks a different question, "which local
    names mean Book", and takes the first for that reason.

    **A star import is expanded, from any module on the allowlist.** Not from
    `models` alone: a module that imports `UserBook` re-exports it, so
    `from shelf import *` binds the name just as `from models import *` does,
    and measured at the tip `UserBook` is in `dir()` of all four allowlisted
    modules. `_STAR_SOURCES` is derived from `READING_RECORD_READERS` so the
    two cannot drift.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "*":
                # `dir()` is the right expansion only because none of these
                # modules declares an `__all__`; if one ever does, a star import
                # binds that list instead and this over-reports rather than
                # under-, which is the safe direction for a guard.
                if isinstance(node, ast.ImportFrom) and node.module in _STAR_SOURCES:
                    names |= set(dir(importlib.import_module(node.module)))
                continue
            names.add(alias.name)
            if alias.asname is not None:
                names.add(alias.asname)
    return names


def _source_modules() -> dict[str, str]:
    """Every backend module this rule applies to, keyed by relative path."""
    return {
        str(path.relative_to(BACKEND)): path.read_text()
        for path in BACKEND.rglob("*.py")
        if path.relative_to(BACKEND).parts[0] not in {"tests", "migrations", ".venv"}
    }


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


@pytest.fixture
def book(db, member) -> Book:
    b = Book(title="Solaris", added_by_user_id=member.id)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


#: Spellings that must be reported, and the one this rule started blind to.
#:
#: Asserted against the pass itself rather than against the tree, for the reason
#: `test_shelf.py::EVASIONS` exists: a rule with no test that fails when it is
#: weakened is not enforced, and this one was weakened by a single `or`.
EVASIONS = {
    "plain": "from models import UserBook\n",
    "beside other names": "from models import Book, UserBook, User\n",
    "aliased": "from models import UserBook as UB\n",
    "star": "from models import *\n",
    "star from a re-exporter": "from shelf import *\n",
}

#: Spellings that must **not** be reported, so the pass cannot be satisfied by
#: reporting everything.
NOT_OFFENCES = {
    "another model": "from models import Book\n",
    "a star from a module with no reading record in it": "from enums import *\n",
    "a name that merely contains it": "from models import UserBookmark\n",
}


class TestReadingIsTheOnlyWayIn:
    def test_no_module_but_the_reading_record_imports_user_book(self):
        offenders = sorted(
            name
            for name, source in _source_modules().items()
            if name not in READING_RECORD_READERS and "UserBook" in _imported_names(source)
        )
        assert offenders == [], (
            "These modules read the reading record directly instead of asking "
            f"`reading.py` for it: {offenders}"
        )

    @pytest.mark.parametrize("spelling", sorted(EVASIONS), ids=sorted(EVASIONS))
    def test_every_spelling_of_the_import_is_caught(self, spelling):
        assert "UserBook" in _imported_names(EVASIONS[spelling])

    @pytest.mark.parametrize("spelling", sorted(NOT_OFFENCES), ids=sorted(NOT_OFFENCES))
    def test_it_does_not_report_an_import_that_is_not_one(self, spelling):
        assert "UserBook" not in _imported_names(NOT_OFFENCES[spelling])

    def test_the_named_ways_past_a_member_have_the_callers_they_claim(self):
        """The same counting `test_shelf.py` does, and for the same reason.

        Growing either list is allowed; growing it without saying so here is
        not. **Call sites, not modules**: a second `discussers` call inside
        `serialisation.py` would leave a set of module names unchanged.
        """
        calls: dict[str, list[str]] = {"discussers": [], "resolve_merge": []}
        for name, source in _source_modules().items():
            if name == "reading.py":
                continue
            for node in ast.walk(ast.parse(source)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in calls
                ):
                    calls[node.func.id].append(f"{name}:{node.lineno}")

        assert len(calls["discussers"]) == 1, calls
        assert len(calls["resolve_merge"]) == 1, calls


class TestAbsenceMeansUnread:
    def test_a_book_nobody_touched_has_no_row(self, db, member, book):
        records = Reading.by(db, member.id).of([book.id])

        assert records.get(book.id) is None
        assert len(records) == 0

    def test_and_reads_as_unread(self, db, member, book):
        assert Reading.by(db, member.id).of([book.id]).status_of(book.id) is ReadStatus.UNREAD

    def test_a_row_created_in_this_request_also_reads_as_unread(self, db, member, book):
        """The trap, and the one worth a test of its own.

        A row `open()` has just added has not been flushed, so SQLAlchemy has
        not applied the column default and `status` is still None. Reading it
        raw yields None, and a membership test against the enum then quietly
        fails, which is how the promotion in `begin()` once never fired at all.
        """
        records = Reading.by(db, member.id).of([book.id])
        row = records.open(book.id)

        assert row.status is None
        assert records.status_of(book.id) is ReadStatus.UNREAD

    def test_opening_twice_makes_one_row(self, db, member, book):
        records = Reading.by(db, member.id).of([book.id])

        assert records.open(book.id) is records.open(book.id)

    def test_opening_a_book_that_was_not_loaded_is_refused(self, db, member, book):
        """Rather than inserting a second row beside one it never saw, which the
        unique index would catch at flush time as a 500 mid-write."""
        records = Reading.by(db, member.id).of([book.id])

        with pytest.raises(ValueError, match="not loaded"):
            records.open(book.id + 1)

    def test_the_whole_record_refuses_nothing(self, db, member, book):
        assert Reading.by(db, member.id).everything().open(book.id) is not None

    def test_an_empty_set_costs_no_statement(self, db, member):
        member_id = member.id

        assert _count(db, lambda: Reading.by(db, member_id).of([])) == []

    def test_a_page_costs_one_statement(self, db, member):
        """The N+1 this seam exists to stop: five books, one query, not five."""
        books = [Book(title=f"Book {n}", added_by_user_id=member.id) for n in range(5)]
        db.add_all(books)
        db.commit()
        ids = [b.id for b in books]
        member_id = member.id
        Reading.by(db, member_id).of(ids)  # warm up outside the counted window

        statements = _count(db, lambda: Reading.by(db, member_id).of(ids))

        assert len(statements) == 1


class TestAReadingRecordIsPrivateToItsMember:
    def test_another_members_status_is_not_readable(self, db, member, other, book):
        Reading.by(db, other.id).mark(book.id, ReadStatus.READ)
        db.commit()

        assert Reading.by(db, member.id).of([book.id]).status_of(book.id) is ReadStatus.UNREAD

    def test_another_members_rating_is_not_readable(self, db, member, other, book):
        Reading.by(db, other.id).rate(book.id, 5)
        db.commit()

        assert Reading.by(db, member.id).of([book.id]).get(book.id) is None

    def test_the_whole_record_is_one_members_only(self, db, member, other, book):
        Reading.by(db, other.id).mark(book.id, ReadStatus.READ)
        db.commit()

        assert len(Reading.by(db, member.id).everything()) == 0

    def test_marking_a_book_does_not_touch_another_members_row(
        self, db, member, other, book
    ):
        Reading.by(db, other.id).mark(book.id, ReadStatus.READ)
        db.commit()

        Reading.by(db, member.id).mark(book.id, ReadStatus.UNREAD)
        db.commit()

        assert Reading.by(db, other.id).of([book.id]).status_of(book.id) is ReadStatus.READ


class TestTheDatesComeFromTheTransition:
    def test_starting_stamps_the_start(self, db, member, book):
        row = Reading.by(db, member.id).mark(book.id, ReadStatus.READING)

        assert row.started_at is not None
        assert row.finished_at is None

    def test_going_straight_to_read_stamps_both(self, db, member, book):
        row = Reading.by(db, member.id).mark(book.id, ReadStatus.READ)

        assert row.started_at is not None
        assert row.finished_at is not None

    def test_re_selecting_the_same_status_does_not_move_the_date(self, db, member, book):
        reading = Reading.by(db, member.id)
        first = reading.mark(book.id, ReadStatus.READ).finished_at
        db.commit()

        assert reading.mark(book.id, ReadStatus.READ).finished_at == first

    def test_going_back_to_unread_clears_both(self, db, member, book):
        reading = Reading.by(db, member.id)
        reading.mark(book.id, ReadStatus.READ)
        db.commit()

        row = reading.mark(book.id, ReadStatus.UNREAD)

        assert row.started_at is None
        assert row.finished_at is None

    def test_giving_up_keeps_the_start_and_clears_the_finish(self, db, member, book):
        reading = Reading.by(db, member.id)
        reading.mark(book.id, ReadStatus.READ)
        db.commit()

        row = reading.mark(book.id, ReadStatus.DID_NOT_FINISH)

        assert row.started_at is not None
        assert row.finished_at is None


class TestMarkingASelection:
    @pytest.fixture
    def three(self, db, member) -> list[Book]:
        books = [Book(title=f"Book {n}", added_by_user_id=member.id) for n in range(3)]
        db.add_all(books)
        db.commit()
        return books

    def test_every_untouched_book_counts_as_changed(self, db, member, three):
        changed, unchanged = Reading.by(db, member.id).mark_each(
            [b.id for b in three], ReadStatus.READ
        )

        assert (changed, unchanged) == (3, 0)

    def test_a_book_already_in_that_status_is_left_alone(self, db, member, three):
        reading = Reading.by(db, member.id)
        stamped = reading.mark(three[0].id, ReadStatus.READ).finished_at
        db.commit()

        changed, unchanged = reading.mark_each([b.id for b in three], ReadStatus.READ)
        db.commit()

        assert (changed, unchanged) == (2, 1)
        untouched = reading.of([three[0].id]).get(three[0].id)
        assert untouched is not None
        assert untouched.finished_at == stamped

    def test_it_stamps_the_same_dates_the_single_book_route_does(self, db, member, three):
        Reading.by(db, member.id).mark_each([b.id for b in three], ReadStatus.READ)
        db.commit()

        records = Reading.by(db, member.id).of([b.id for b in three])
        finishes = [records.get(b.id) for b in three]
        assert all(row is not None and row.finished_at is not None for row in finishes)

    def test_it_costs_one_read_for_the_whole_selection(self, db, member, three):
        ids = [b.id for b in three]
        member_id = member.id
        Reading.by(db, member_id).of(ids)  # warm up outside the counted window

        statements = _count(
            db, lambda: Reading.by(db, member_id).mark_each(ids, ReadStatus.READ)
        )

        assert len(statements) == 1


class TestPickingABookUp:
    def test_it_promotes_an_untouched_book(self, db, member, book):
        row = Reading.by(db, member.id).begin(book.id)

        assert ReadStatus(row.status) is ReadStatus.READING
        assert row.started_at is not None

    def test_it_promotes_a_book_somebody_gave_up_on(self, db, member, book):
        reading = Reading.by(db, member.id)
        reading.mark(book.id, ReadStatus.DID_NOT_FINISH)
        db.commit()

        row = reading.begin(book.id)

        assert ReadStatus(row.status) is ReadStatus.READING
        assert row.finished_at is None

    def test_it_leaves_a_finished_book_finished(self, db, member, book):
        """A new position in a book already READ is a re-read, which the
        progress log records and the status has no way to say."""
        reading = Reading.by(db, member.id)
        reading.mark(book.id, ReadStatus.READ)
        db.commit()

        row = reading.begin(book.id)

        assert ReadStatus(row.status) is ReadStatus.READ
        assert row.finished_at is not None

    def test_it_creates_the_row_even_when_it_promotes_nothing(self, db, member, book):
        reading = Reading.by(db, member.id)
        reading.mark(book.id, ReadStatus.READING)
        db.commit()

        assert reading.begin(book.id) is not None


class TestTheTwoWritesThatAreNotReadingEvents:
    """The asymmetry a reader arrives at this module suspecting is a bug.

    Rating a book and offering to talk about one create the row and stamp
    nothing. Both are deliberate and both are pinned at the route as well
    (`test_books_reading.py`, `test_books_lending.py`); these pin the rule at
    the seam that owns it, so moving it again cannot lose it.
    """

    def test_rating_stamps_no_dates(self, db, member, book):
        row = Reading.by(db, member.id).rate(book.id, 5)

        assert row.started_at is None
        assert row.finished_at is None

    def test_rating_leaves_the_status_alone(self, db, member, book):
        reading = Reading.by(db, member.id)
        reading.mark(book.id, ReadStatus.WANT_TO_READ)
        db.commit()

        assert ReadStatus(reading.rate(book.id, 5).status) is ReadStatus.WANT_TO_READ

    def test_a_null_clears_the_rating(self, db, member, book):
        reading = Reading.by(db, member.id)
        reading.rate(book.id, 5)
        db.commit()

        assert reading.rate(book.id, None).rating is None

    def test_offering_to_discuss_stamps_no_dates(self, db, member, book):
        row = Reading.by(db, member.id).offer_to_discuss(book.id, True)

        assert row.started_at is None
        assert row.finished_at is None

    def test_offering_to_discuss_leaves_the_status_alone(self, db, member, book):
        Reading.by(db, member.id).offer_to_discuss(book.id, True)
        db.commit()

        assert Reading.by(db, member.id).of([book.id]).status_of(book.id) is ReadStatus.UNREAD

    def test_both_still_create_the_row(self, db, member, book):
        """Absence of a row means unread, not absence of a member, so the first
        thing anybody sets has to make it."""
        reading = Reading.by(db, member.id)

        reading.rate(book.id, 4)
        db.commit()

        assert reading.of([book.id]).get(book.id) is not None


class TestWhoWantsToTalkAboutIt:
    def test_it_reads_across_members(self, db, member, other, book):
        """The one column here meant to be read by other people."""
        Reading.by(db, other.id).offer_to_discuss(book.id, True)
        db.commit()

        assert [u.username for u in discussers(db, [book.id])[book.id]] == ["stranger"]

    def test_it_says_nothing_about_reading(self, db, member, other, book):
        Reading.by(db, other.id).offer_to_discuss(book.id, True)
        db.commit()

        assert Reading.by(db, member.id).of([book.id]).status_of(book.id) is ReadStatus.UNREAD

    def test_a_withdrawn_offer_disappears(self, db, member, other, book):
        Reading.by(db, other.id).offer_to_discuss(book.id, True)
        db.commit()
        Reading.by(db, other.id).offer_to_discuss(book.id, False)
        db.commit()

        assert discussers(db, [book.id]) == {}

    def test_it_is_ordered_by_username(self, db, member, other, book):
        Reading.by(db, other.id).offer_to_discuss(book.id, True)
        Reading.by(db, member.id).offer_to_discuss(book.id, True)
        db.commit()

        assert [u.username for u in discussers(db, [book.id])[book.id]] == [
            "reader",
            "stranger",
        ]

    def test_an_empty_set_costs_no_statement(self, db):
        assert _count(db, lambda: discussers(db, [])) == []


class TestMergingTwoBooksThatWereOne:
    @pytest.fixture
    def pair(self, db, member) -> tuple[Book, Book]:
        keeper = Book(title="Solaris", added_by_user_id=member.id)
        loser = Book(title="Solaris (1970)", added_by_user_id=member.id)
        db.add_all([keeper, loser])
        db.commit()
        return keeper, loser

    def test_a_record_on_the_loser_moves_to_the_keeper(self, db, member, pair):
        keeper, loser = pair
        Reading.by(db, member.id).mark(loser.id, ReadStatus.READ)
        db.commit()

        resolve_merge(db, keeper.id, [loser.id])
        db.commit()

        assert Reading.by(db, member.id).of([keeper.id]).status_of(keeper.id) is ReadStatus.READ

    def test_everybody_elses_record_moves_too(self, db, member, other, pair):
        """There is no viewer here. Left out, the row is cascade deleted with
        the loser and that member silently loses their history."""
        keeper, loser = pair
        Reading.by(db, other.id).mark(loser.id, ReadStatus.READING)
        db.commit()

        resolve_merge(db, keeper.id, [loser.id])
        db.commit()

        assert (
            Reading.by(db, other.id).of([keeper.id]).status_of(keeper.id) is ReadStatus.READING
        )

    def test_the_survivors_own_record_wins(self, db, member, pair):
        """`(user_id, book_id)` is unique, so a member holding a record on both
        cannot keep two. The keeper's is the record attached to the book that
        continues to exist."""
        keeper, loser = pair
        reading = Reading.by(db, member.id)
        reading.mark(keeper.id, ReadStatus.READING)
        reading.mark(loser.id, ReadStatus.READ)
        db.commit()

        resolve_merge(db, keeper.id, [loser.id])
        db.commit()

        assert len(reading.everything()) == 1
        assert reading.of([keeper.id]).status_of(keeper.id) is ReadStatus.READING

    def test_merging_nothing_is_not_a_query(self, db, member, pair):
        keeper_id = pair[0].id

        assert _count(db, lambda: resolve_merge(db, keeper_id, [])) == []


class TestReportingIsScopedToTheShelf:
    """An aggregate over the whole table would count somebody else's private
    book, and a count is a disclosure just as a title is."""

    def test_finished_by_month_counts_only_this_member(self, db, member, other, book):
        Reading.by(db, other.id).mark(book.id, ReadStatus.READ)
        db.commit()

        shelf = Shelf.seen_by(db, member.id)
        assert Reading.by(db, member.id).finished_by_month(shelf) == []

    def test_finished_by_month_excludes_a_private_book_of_somebody_elses(
        self, db, member, other
    ):
        hidden = Book(title="Hidden", added_by_user_id=other.id, is_private=True)
        db.add(hidden)
        db.commit()
        Reading.by(db, member.id).mark(hidden.id, ReadStatus.READ)
        db.commit()

        shelf = Shelf.seen_by(db, member.id)
        assert Reading.by(db, member.id).finished_by_month(shelf) == []

    def test_a_book_somebody_gave_up_on_is_not_finished(self, db, member, book):
        Reading.by(db, member.id).mark(book.id, ReadStatus.DID_NOT_FINISH)
        db.commit()

        shelf = Shelf.seen_by(db, member.id)
        assert Reading.by(db, member.id).finished_by_month(shelf) == []

    def test_finished_books_are_grouped_by_month(self, db, member, book):
        Reading.by(db, member.id).mark(book.id, ReadStatus.READ)
        db.commit()

        rows = Reading.by(db, member.id).finished_by_month(Shelf.seen_by(db, member.id))

        assert len(rows) == 1
        assert rows[0][1] == 1

    def test_no_ratings_is_none_and_zero(self, db, member, book):
        """Not 0.0, which would claim an opinion nobody expressed."""
        assert Reading.by(db, member.id).rating_summary(Shelf.seen_by(db, member.id)) == (
            None,
            0,
        )

    def test_the_average_is_over_this_members_ratings_only(self, db, member, other, book):
        Reading.by(db, member.id).rate(book.id, 4)
        Reading.by(db, other.id).rate(book.id, 2)
        db.commit()

        assert Reading.by(db, member.id).rating_summary(Shelf.seen_by(db, member.id)) == (
            4.0,
            1,
        )


def _count(db, work) -> list[str]:
    """The statements one call issues.

    Warm up outside the counted window before using this: a commit inside it
    makes the session open a fresh savepoint on its next statement, and the
    listener counts that savepoint as a query.
    """
    statements: list[str] = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def record(conn, cursor, statement, *args):
        statements.append(statement)

    try:
        work()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    return statements
