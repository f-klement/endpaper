"""One Member's reading of the Books in this Library, and the only place a
`user_books` row is read or written.

A Book is a shared fact and a reading of it is not. Status, rating, the two
dates and the offer to talk about it are one person's, held in `user_books`,
one row per (Member, Book). `shelf.py` owns which Books a Member may see;
this module owns what that Member has done with them.

It exists for the same reason `shelf.py` and `authorship.py` do. The rules were
real and the code that applied them was scattered: **five** get-or-create sites
in `routers/books.py` alone, all spelling the same query and the same `if None`
by hand, plus a sixth in `importing.py` and two batch reads in
`serialisation.py`. Three rules had no owner and were kept by everybody
remembering them.

## The three rules, which are the whole reason this is a module

**Absence means unread.** A row appears the first time somebody sets anything,
so a Book nobody has touched has no row rather than an `unread` one. Every read
has to treat a missing row as `ReadStatus.UNREAD`, and `Records.status_of` is
the one place that does. Its sharper half is that a row **created in this
request** has not been flushed, so the column default has not been applied and
`status` is still `None`: that case is not hypothetical, it is the whole
first-progress-on-a-new-Book path, and before it was handled the promotion in
`begin()` never fired at all.

**A reading record is private to its Member.** Every query below filters on
`user_id`, and it is applied by construction: a `Reading` is built from a
member id and there is no method that takes a different one. The Book being
visible says nothing about whose reading of it the caller may see, which is why
this is a separate rule from the Shelf's rather than a consequence of it. Two
Members reading the same public copy is the ordinary case here.

**The dates are derived from the status transition, never typed in.**
`_stamp_reading_dates` holds those rules and is private. Nobody fills in a date
field; everybody moves a Book to "reading" when they start it.

## Three writes, and only one of them is a reading event

`mark`, `begin` and `mark_each` stamp. `rate` and `offer_to_discuss` create the
row and deliberately **do not**, and that asymmetry is the thing a reader
arrives here suspecting is a bug.

It is not. Rating a Book is not a claim to have finished it just now, and
offering to talk about one says nothing about having read it: a Member can rate
a Book they abandoned years ago, and "ask me about this" is an invitation
rather than a status. Both are pinned:
`tests/routers/test_books_reading.py::TestRating::
test_rating_does_not_touch_the_reading_dates` and
`tests/routers/test_books_lending.py::TestAskMeAboutThisBook::
test_it_leaves_the_reading_status_alone`.

What they **do** share with the stamping writes is creating the row, because
absence means unread rather than absence of a Member.

## The interface

    reading = Reading.by(db, member.id)

    reading.mark(book.id, ReadStatus.READ)          # set a status, stamp the dates
    reading.mark_each(book_ids, status)             # the same, for a selection
    reading.begin(book.id)                          # promote from a standing start
    reading.rate(book.id, 5)
    reading.offer_to_discuss(book.id, True)

    records = reading.of(book_ids)                  # one statement for a page
    records = reading.everything()                  # this Member's whole record
    records.status_of(book.id)                      # absence means unread
    records.get(book.id)                            # the row, or None
    records.open(book.id)                           # the row, created if absent

    reading.finished_by_month(shelf)                # reporting, scoped to a shelf
    reading.rating_summary(shelf)

`by` is named like `Shelf.seen_by` and `Authorship.seen_by` and promises the
same thing: everything below is scoped to one Member at construction rather
than by each caller remembering to pass an id.

## Two named ways past a Member

Both are module functions rather than methods, for the reason
`whole_table_for_uniqueness` is: a way past the rule that is spelled as a
method on the scoped object reads like part of the scoped interface.

`discussers()` reads **everybody's** `wants_to_discuss`, which is the one
column on the table meant to be read by other people. A reader browsing the
shelf has to be able to see whose door to knock on, so this is the flag's
purpose rather than a leak. What the **feature** discloses is usernames and
nothing else, in particular not whether those Members have read the Book; what
the **function** hands back is ORM `User` rows, and the narrowing to what may be
published happens at its one call site. Its docstring says where.

`resolve_merge()` rewrites **every** Member's rows when two Books turn out to
be one. There is no viewer: the row belonging to somebody who is not the caller
still has to end up pointing at the surviving Book, or it is cascade deleted
with the loser and that Member silently loses their reading history.

`tests/test_reading.py::test_the_named_ways_past_a_member_have_the_callers_they_claim`
is what makes a third one a decision rather than an edit.

## What this module does not own

**Book queries.** `shelf.py` joins `user_books` in three places
(`_with_read_status`, `_unrated`, `_offered_for_discussion`) because those
narrow a listing of Books, and every query returning or counting Books goes
through the Shelf. That is the house rule, and it is why `shelf.py` is the one
other module allowed to import `UserBook`.

**The import's fill-the-gaps rule.** `importing.py` writes a status, a rating
and a finish date straight from a CSV row and never overwrites a local value,
because an export from another service is older evidence than something the
Member typed here. That is a different rule from this module's, so it stays
there; what it takes from here is the record itself, through `everything()`
and `Records.open`.
"""

from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from enums import ReadStatus
from models import Book, User, UserBook
from shelf import Shelf

#: The statuses that mean a Book has not been picked up yet, so recording a
#: position in one is news rather than a correction.
#:
#: **DID_NOT_FINISH is in here and READ is not**, which is the asymmetry
#: `begin()` exists to get right. See its docstring.
_A_STANDING_START = (
    ReadStatus.UNREAD,
    ReadStatus.WANT_TO_READ,
    ReadStatus.DID_NOT_FINISH,
)


class Records:
    """The reading records one Member holds for a known set of Books.

    Loaded in **one** statement and created on demand, which is the pair of
    properties a caller cannot get from a bare query without writing both
    halves itself. A page of 25 Books costs one SELECT here, not 25, and the
    row a write needs is already in hand.

    Immutable in the set it covers and not in the rows: `open()` adds to the
    session and to this mapping, so a later `get()` in the same request sees
    what an earlier `open()` made. That is what lets `importing.py` walk five
    thousand CSV rows against one load.

    **`open()` refuses a Book this was not loaded for**, rather than creating a
    second row beside one it never saw. The unique index on
    `(user_id, book_id)` would catch it at flush time as a 500 in the middle of
    a write; refusing here makes it a programming error at the call site.
    `everything()` is loaded for every Book and refuses nothing.

    What this does **not** close: two concurrent requests that both find no row
    both insert one, and the second commit raises on the unique index. Present
    at all five call sites before this module existed and present here, moved
    from five places to one. Fixing it means a savepoint and a re-read on
    conflict, which changes behaviour under a load nobody has reported, so it
    is named rather than half-done.
    """

    __slots__ = ("_db", "_known", "_member_id", "_rows")

    def __init__(
        self,
        db: Session,
        member_id: int,
        rows: dict[int, UserBook],
        known: frozenset[int] | None,
    ) -> None:
        # Private by convention and by the absence of any other caller:
        # `Reading.of` and `Reading.everything` are the only ways in, and they
        # are what applies the member filter.
        self._db = db
        self._member_id = member_id
        self._rows = rows
        # `None` means "every Book", which is what `everything()` loaded.
        self._known = known

    def get(self, book_id: int) -> UserBook | None:
        """This Member's row for one Book, or None if they never touched it."""
        return self._rows.get(book_id)

    def status_of(self, book_id: int) -> ReadStatus:
        """What this Member has said about one Book. Absence means unread.

        Two absences, and the second is the one that bites. No row at all is a
        Book nobody has touched. A row `open()` made in this request has not
        been flushed, so SQLAlchemy has not applied the column default and
        `status` is still `None`: reading it raw there yields `None` rather
        than `unread`, and a membership test against the enum then quietly
        fails.
        """
        row = self._rows.get(book_id)
        if row is None or row.status is None:
            return ReadStatus.UNREAD
        return ReadStatus(row.status)

    def open(self, book_id: int) -> UserBook:
        """This Member's row for one Book, created and added if there is none.

        Creating rather than returning None because absence of a row means
        unread, not absence of a Member: the first thing anybody sets has to
        make the row.
        """
        if self._known is not None and book_id not in self._known:
            raise ValueError(
                f"book {book_id} was not loaded into this set of reading records, "
                "so whether a row already exists for it is unknown"
            )
        row = self._rows.get(book_id)
        if row is None:
            row = UserBook(user_id=self._member_id, book_id=book_id)
            self._db.add(row)
            self._rows[book_id] = row
        return row

    def __len__(self) -> int:
        """How many rows this Member actually has here. Not how many Books it
        was asked about, which is the number a caller usually has already."""
        return len(self._rows)


class Reading:
    """What one Member has done with the Books in this Library.

    Cheap to build and built per request: it holds a session and an id and
    reads nothing until asked.
    """

    __slots__ = ("_db", "_member_id")

    def __init__(self, db: Session, member_id: int) -> None:
        self._db = db
        self._member_id = member_id

    @classmethod
    def by(cls, db: Session, member_id: int) -> Reading:
        """This Member's reading record.

        Named like `Shelf.seen_by` because it makes the same promise: the
        member filter is a property of construction, so there is no method
        below that can be given a different id than the object was built for.
        """
        return cls(db, member_id)

    # ── Reading ───────────────────────────────────────────────────────────────

    def of(self, book_ids: Collection[int]) -> Records:
        """This Member's records for these Books, in one statement.

        **Zero statements for an empty set**, which is the guard the export
        route used to write itself as `if books:` around the query.

        The ids are bound parameters, so this inherits SQLite's ceiling on
        those: **250,000** in the shipped image and in the container the suites
        run in, and **32,766** on a bare `uv run`, measured per environment
        rather than assumed. `Shelf.matching` carries the versions those came
        from and the reason a debugging session on a developer's machine can
        raise `OperationalError` where CI and production would not.

        Four callers, and two of them are the size of the library rather than
        of a page, which is worth naming because the sentence that used to be
        here claimed otherwise:

        | Caller | Bounded by |
        |---|---|
        | `_records_for` | one id |
        | `mark_each` | `BulkRequest.book_ids`, 500 by its schema |
        | `serialisation.books_to_out` | its own caller: see below |
        | `routers/books.py` `export_books` | **the visible library** |

        `books_to_out` is a page for `list_books`, `list_trash` and the loans
        list, and a copy group for `list_copies`, which is one row for almost
        every Book. It is every Book in a duplicate **group** for
        `list_duplicates`, which is unpaginated and backs a UI page: its own
        comment records 2,000 Books scanned, and what reaches here is the
        subset that grouped.

        So the real ceiling is a catalogue of 32,766 Books, and reaching it
        needs a developer running the suite outside its container against a
        library **sixteen times** the largest this endpoint has been measured
        against. If that stops being true the fix is a temporary table, not a
        bigger IN, which is the same answer `Shelf.matching` gives.
        """
        ids = frozenset(book_ids)
        rows: dict[int, UserBook] = {}
        if ids:
            rows = {
                row.book_id: row
                for row in self._db.query(UserBook).filter(
                    UserBook.user_id == self._member_id,
                    UserBook.book_id.in_(ids),
                )
            }
        return Records(self._db, self._member_id, rows, ids)

    def everything(self) -> Records:
        """This Member's whole reading record, whatever it covers.

        For a caller that will touch an unknown set of Books and cannot say in
        advance which: the import walks a CSV file and matches rows to the
        catalogue as it goes, so loading per row would be one SELECT per line.
        """
        rows = {
            row.book_id: row
            for row in self._db.query(UserBook).filter(UserBook.user_id == self._member_id)
        }
        return Records(self._db, self._member_id, rows, None)

    # ── Writing ───────────────────────────────────────────────────────────────

    def mark(self, book_id: int, status: ReadStatus) -> UserBook:
        """Set this Member's status for one Book and stamp the dates.

        Re-selecting the status already set is allowed and does nothing to the
        dates: a UI with pressable buttons makes it easy, and
        `_stamp_reading_dates` only stamps what is not already stamped.
        """
        return self._mark(self._records_for(book_id), book_id, status)

    def mark_each(self, book_ids: Sequence[int], status: ReadStatus) -> tuple[int, int]:
        """Set the same status across a selection. Returns (changed, unchanged).

        One statement for the whole selection rather than one per Book, and the
        same stamping the single-Book route uses, so a bulk "mark read"
        produces the same dates as marking them one at a time would.

        A Book already in that status is `unchanged` and is not touched at all.
        A Book with no row is `changed`, because the row it gets is a record
        where there was none.
        """
        records = self.of(book_ids)
        changed = unchanged = 0
        for book_id in book_ids:
            if records.get(book_id) is not None and records.status_of(book_id) is status:
                unchanged += 1
                continue
            self._mark(records, book_id, status)
            changed += 1
        return changed, unchanged

    def begin(self, book_id: int) -> UserBook:
        """Promote a Book to READING, but only from a standing start.

        Saying where you have got to in a Book is the same claim the READING
        button makes, arrived at from the other direction. A Book already
        READING needs no change, and one already READ is being re-read, which
        is a thing the progress log records and the status has no way to say.

        **DID_NOT_FINISH promotes, unlike READ.** It is a claim about the past,
        and a new position contradicts it: leaving it alone would have the
        shelf say "gave up on this" while the log says "reached page 240 this
        morning". Picking an abandoned Book back up is the case the status
        exists for. `finished_at` is already null for such a Book and stays
        null, because READING is not READ.

        The row is created either way, which is deliberate: recording a
        position is touching the Book even when the status was already right.
        """
        records = self._records_for(book_id)
        if records.status_of(book_id) in _A_STANDING_START:
            return self._mark(records, book_id, ReadStatus.READING)
        return records.open(book_id)

    def rate(self, book_id: int, rating: int | None) -> UserBook:
        """Rate a Book out of five, or clear the rating with None.

        **Does not touch the dates and does not touch the status.** Rating a
        Book is not a claim about having finished it just now: somebody can
        rate one they abandoned, or one they read before this catalogue
        existed. Pinned by `test_rating_does_not_touch_the_reading_dates`.
        """
        entry = self._records_for(book_id).open(book_id)
        entry.rating = rating
        return entry

    def offer_to_discuss(self, book_id: int, wants: bool) -> UserBook:
        """Offer to talk about a Book, or withdraw the offer.

        **Does not touch the dates or the status either**, and for a sharper
        reason than the rating: this is the one column here other people read,
        so making it imply a reading status would publish one. Wanting to talk
        about a Book is not a claim to have read it. Pinned by
        `test_it_leaves_the_reading_status_alone`.
        """
        entry = self._records_for(book_id).open(book_id)
        entry.wants_to_discuss = wants
        return entry

    # ── Reporting ─────────────────────────────────────────────────────────────
    #
    # Both take a Shelf rather than building their own query, because they are
    # a fact about this Member's reading **of the Books somebody may see**: an
    # aggregate over the whole table would count a private Book of somebody
    # else's, and a count is a disclosure. The Shelf must be the same Member's;
    # every caller builds both from `current_user` on the line above.

    def finished_by_month(self, shelf: Shelf) -> list[tuple[str, int]]:
        """How many Books this Member finished in each month, oldest first.

        `finished_at` rather than the status, which is what keeps a Book
        somebody gave up on out of "books finished this year":
        `_stamp_reading_dates` clears the date for DID_NOT_FINISH and leaves
        the status saying so.
        """
        rows = (
            shelf.select(
                func.strftime("%Y-%m", UserBook.finished_at).label("month"),
                func.count(UserBook.id).label("count"),
            )
            .join(UserBook, UserBook.book_id == Book.id)
            .filter(UserBook.user_id == self._member_id, UserBook.finished_at.isnot(None))
            .group_by("month")
            .order_by("month")
            .all()
        )
        return [(month, count) for month, count in rows]

    def rating_summary(self, shelf: Shelf) -> tuple[float | None, int]:
        """This Member's average rating, and how many Books it is drawn from.

        None and 0 when they have rated nothing: SQLite's AVG over no rows is
        NULL, and reporting 0.0 would claim an opinion nobody expressed.
        """
        average, rated = (
            shelf.select(func.avg(UserBook.rating), func.count(UserBook.id))
            .join(UserBook, UserBook.book_id == Book.id)
            .filter(UserBook.user_id == self._member_id, UserBook.rating.isnot(None))
            .one()
        )
        return average, rated

    # ── Internals ─────────────────────────────────────────────────────────────

    def _records_for(self, book_id: int) -> Records:
        """The one-Book case of `of()`, so every write shares its load."""
        return self.of((book_id,))

    def _mark(self, records: Records, book_id: int, status: ReadStatus) -> UserBook:
        """The row, stamped and set. The two orders are equivalent:
        `_stamp_reading_dates` reads `new_status` and the two dates, never the
        status it is replacing."""
        entry = records.open(book_id)
        _stamp_reading_dates(entry, status)
        entry.status = status
        return entry


def _stamp_reading_dates(user_book: UserBook, new_status: ReadStatus) -> None:
    """Record when reading started and finished, from the status transition.

    Derived rather than typed in, because nobody fills in a date field but
    everybody moves a book to "reading" when they start it. Three rules, and
    each exists for a case that came up while writing them:

    * Only stamp what is not already stamped. Re-selecting the current status,
      which a UI with pressable buttons makes easy, must not move a date that
      already records something true.
    * Going straight to READ stamps both. Plenty of books are only marked once,
      after the fact, and a finish with no start reads like missing data.
    * Moving *back* to an earlier status clears the later date. Marking a book
      unread again and leaving a finish date behind would leave it counted in
      "books finished this year" forever.

    DID_NOT_FINISH needed no fourth rule, and that is worth stating rather than
    leaving to be rediscovered. It is a claim that reading **started**, so it
    stamps `started_at` alongside READING and READ, and it is not a finish, so
    the `else` below already clears `finished_at` for it. What it must never do
    is fall into the last branch: clearing `started_at` would erase the fact
    that the book was ever picked up, which is the one thing this status is for.

    It also touches no `reading_progress` row. How far somebody got before
    giving up is exactly the interesting part, and nothing here deletes it.
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    started = new_status in (
        ReadStatus.READING,
        ReadStatus.READ,
        ReadStatus.DID_NOT_FINISH,
    )
    if started and user_book.started_at is None:
        user_book.started_at = now

    if new_status is ReadStatus.READ:
        if user_book.finished_at is None:
            user_book.finished_at = now
    else:
        # Anything other than READ means it is not finished, whatever it was.
        # DID_NOT_FINISH included, and deliberately: a book somebody gave up on
        # must not be counted in "books finished this year".
        user_book.finished_at = None

    if new_status in (ReadStatus.UNREAD, ReadStatus.WANT_TO_READ):
        user_book.started_at = None


def discussers(db: Session, book_ids: Collection[int]) -> dict[int, list[User]]:
    """Who has offered to talk about each of these Books.

    **Not scoped to a Member**, unlike everything above, and that is the whole
    point of the flag: a reader browsing the shelf has to be able to see whose
    door to knock on. It discloses usernames and nothing else, in particular
    not whether those Members have read the Book.

    Scoped by the caller instead, to the Books it has already narrowed through
    the Shelf. Passing ids that came from anywhere else would publish who is
    interested in a Book the caller may not see.

    One statement for the page, joined to `users` so the names arrive with it.
    A per-Book query here is the exact N+1 the serialiser exists to avoid, and
    a lazy `user_book.user` read inside a loop is the same thing wearing a
    different coat.

    Ordered by username so a Book with three readers reads the same way twice.

    **Returns ORM `User` rows, which carry `password_hash`.** The narrowing to
    what may be published happens at the one call site,
    `serialisation._discussers`, which maps each row through `UserOut` before
    it reaches a payload. That is the same split every other row in this module
    takes and it is the reason this returns rows rather than a schema: a
    seam that owns a table has no business importing `schemas`. A second
    caller must map them too, and
    `test_the_named_ways_past_a_member_have_the_callers_they_claim` is what
    makes adding one a decision rather than an edit.
    """
    ids = frozenset(book_ids)
    if not ids:
        return {}
    rows = (
        db.query(UserBook.book_id, User)
        .join(User, User.id == UserBook.user_id)
        .filter(UserBook.book_id.in_(ids), UserBook.wants_to_discuss.is_(True))
        .order_by(User.username.asc())
        .all()
    )
    grouped: dict[int, list[User]] = {}
    for book_id, user in rows:
        grouped.setdefault(book_id, []).append(user)
    return grouped


def resolve_merge(db: Session, keeper_id: int, loser_ids: Collection[int]) -> None:
    """Fold every Member's reading records for the losing Books into the keeper.

    **Not scoped to a Member**, and it cannot be: the merge is one person's
    decision about the catalogue, and everybody else's reading of the Books
    being merged has to survive it. Left out, the losers' rows are cascade
    deleted with them and those Members silently lose their history.

    The records cannot simply move: `(user_id, book_id)` is unique, so a Member
    holding one on two of the merged rows would violate it. **The survivor's
    own row wins and the duplicate is dropped**, because that is the record
    attached to the Book that continues to exist.

    Built to be called before the flush, so it reads what is in the database
    rather than what the caller has already repointed.
    """
    ids = frozenset(loser_ids)
    if not ids:
        return
    on_keeper = {
        row.user_id for row in db.query(UserBook).filter(UserBook.book_id == keeper_id)
    }
    for row in db.query(UserBook).filter(UserBook.book_id.in_(ids)).all():
        if row.user_id in on_keeper:
            db.delete(row)
        else:
            row.book_id = keeper_id
            on_keeper.add(row.user_id)
