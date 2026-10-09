"""The cover backfill's fetch bound and its two deadlines.

`test_concurrency_bounds.py` reads where a bound is **built** and refuses one built
inside a route handler. It cannot see whether the pool this route submits to
outlives the request, and nothing static can tell a wall clock spent on a queue
position from one spent on a fetch, so both of those are held here.

**Four mutations were put to these arms by the seat that wrote them**, measured
2026-09-26 one at a time against a green baseline: the per book budget dropped from
the submit, the cursor spelled `batch[-1].id`, a queued fetch read for its answer
instead of cancelled, and the deadline check between waves disabled. The last was
**green** against the first version of the arm written for it, which is why that arm
reads a submission count rather than the reply.

**A non author pass then put its own at them and found three gaps, all closed here.**
The handler's collection loop decided cancel or read one offset at a time, so a
worker freed during a read started the next offset and a wave drained serially for a
budget a book: a correctness defect, not a guard gap, and
`test_a_wave_whose_slots_run_out_mid_way_examines_only_what_started` is the arm it
had no arm for. The prefix slice replaced by a filter over the outcomes that are not
`None` survived everything, so that pass's own arm is here under
`TestTheCursorNeverPassesABookTheRunNeverStarted`. And a pool built four waves wide
was green in every arm, which `TestThePoolsCapacityIsTheWaveItIsSubmittedIn` closes.

No claim is made about the shape this route replaced as a whole: what is measured is
those mutations, named where they landed.

**The pool is stood down per arm rather than contended for real.** A stand-in whose
one worker is already occupied is what "no slot came free" looks like from inside
the handler, and it is deterministic where two concurrent presses would be a race
between a test and a threadpool.

**What no arm here holds is the six.** The real pool's capacity under real
contention is not observed by anything in this file:
`TestTheFetchPoolOutlivesTheRequest` is the only arm that touches
`covers.FETCHES_AT_ONCE`, and what it reads off it is the pool's **lifetime**. The
number of slots is where `covers.MAX_CONCURRENT_FETCHES`' own comment argues it,
against two image services that publish no figure, so there is no second
derivation to assert it against and this file does not pretend otherwise.
"""

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest

import covers
import fetch
import ratelimit
import routers.books as books_router
from config import COVERS_DIR
from tests.helpers import JPEG_BYTES

#: How long a parked submission waits before it gives up.
#:
#: **A bounded park rather than an unbounded one**, so a handler that stops ending
#: its own wait fails an arm rather than hanging a suite worker on a queue nobody
#: drains. Ten times the largest deadline an arm sets, and `_deadline` asserts that
#: relation where it can actually be broken rather than beside this line.
_WAITED_PAST_EVERY_DEADLINE_SECONDS: Final = 5.0


def _fetches_that_store(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Pretend every fetch works, writing the file the real one would, and record
    what it was asked.

    The file matters for the same reason it does in `test_books_covers.py`:
    candidacy is a file behind a book's id, so an arm about a second press reads
    the directory this writes rather than the column.

    The `budget` is recorded because a route that stopped passing one would
    otherwise be green everywhere: `covers.resolve_and_store` defaults it to
    `None`, which is the per hop bound rather than an error.
    """
    asked: list[dict[str, Any]] = []

    def fake(
        book_id: int, isbn: str | None, supplied: str | None, budget: float | None = None
    ) -> str:
        asked.append({"book_id": book_id, "budget": budget})
        (COVERS_DIR / f"{book_id}.jpg").write_bytes(JPEG_BYTES)
        return f"/covers/{book_id}.jpg"

    monkeypatch.setattr(covers, "resolve_and_store", fake)
    return asked


class _SlotsThatRunOut:
    """A stand-in for `covers.FETCHES_AT_ONCE` granting `at_most` fetches, ever.

    **One worker, so submissions are served in the order they were made**, and once
    the grant is spent a blocker is queued ahead of everything after it. Every later
    submission then stays PENDING, which is the state a wave queued behind another
    member's is in and the only state `Future.cancel` can answer for: a running
    fetch is not cancellable at all, here or in the pool this replaces.

    **Not a pool of zero workers**, which cannot be built, and not a `max_workers`
    of one with no blocker, which would run every submission in turn and starve
    nothing.
    """

    def __init__(self, at_most: int) -> None:
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="slots-that-run-out")
        self._left = at_most
        self._released = threading.Event()
        self._blocked = False
        self.asked = 0

    def submit(self, call: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.asked += 1
        if self._left > 0:
            self._left -= 1
            return self._pool.submit(call, *args, **kwargs)
        if not self._blocked:
            self._blocked = True
            self._pool.submit(self._released.wait, _WAITED_PAST_EVERY_DEADLINE_SECONDS)
        return self._pool.submit(call, *args, **kwargs)

    def close(self) -> None:
        self._released.set()
        self._pool.shutdown(wait=False, cancel_futures=True)


@pytest.fixture
def slots(monkeypatch):
    """Grant the route `at_most` fetches for the rest of the arm, then close up.

    Closing matters: the blocker holds a worker until it is released, and a suite
    worker that exits with one parked reports nothing about why.
    """
    made: list[_SlotsThatRunOut] = []

    def grant(at_most: int) -> _SlotsThatRunOut:
        pool = _SlotsThatRunOut(at_most)
        made.append(pool)
        monkeypatch.setattr(covers, "FETCHES_AT_ONCE", pool)
        return pool

    yield grant

    for pool in made:
        pool.close()


def _deadline(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Set the run's deadline, holding the relation the parked blocker rests on.

    `_WAITED_PAST_EVERY_DEADLINE_SECONDS` is justified as ten times the largest
    deadline any arm sets, and the arms set one by hand. Asserted here rather than
    beside that constant, because this is the edit that can break it: an arm
    setting 1.0 would let a parked submission give up before the handler's own
    deadline fired, and the arm would then be reporting on a released queue rather
    than on a starved one.
    """
    assert seconds * 10 <= _WAITED_PAST_EVERY_DEADLINE_SECONDS, (
        f"a deadline of {seconds}s leaves a parked submission's "
        f"{_WAITED_PAST_EVERY_DEADLINE_SECONDS}s less than ten times the largest an "
        "arm sets, so the park would end before the deadline it is meant to outlast. "
        "Raise the constant or lower this."
    )
    monkeypatch.setattr(books_router, "COVER_BACKFILL_DEADLINE_SECONDS", seconds)


def _books(headers, make_book, how_many: int) -> list[dict[str, Any]]:
    """`how_many` books with no cover behind them, in ascending id order."""
    return [make_book(headers, title=f"Book {at}") for at in range(how_many)]


class TestTheFetchPoolOutlivesTheRequest:
    """The defect in one observation, and the only arm here on the real pool.

    A pool built in the handler body and entered with `with` is shut down as the
    request ends, so a second press can only run on threads the first press never
    had. A pool the process holds hands the same workers back.
    """

    def test_a_second_press_runs_on_the_first_press_worker_threads(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """**Thread objects, not `threading.get_ident()`.** The interpreter recycles
        an identity once a thread has died, so a check on the numbers can report a
        match between a dead worker and a fresh one. The objects are held for the
        length of the arm, which is what keeps them from being reused.
        """
        seen: list[set[threading.Thread]] = []

        def fake(book_id, isbn, supplied, budget=None):
            seen[-1].add(threading.current_thread())
            return

        _books(admin["headers"], make_book, 2)
        # Patched **after** the books exist: adding a book resolves its own cover
        # through this same function, so a fake installed first would be recording
        # the add path and the backfill would have no candidate left to examine.
        monkeypatch.setattr(covers, "resolve_and_store", fake)

        for _ in range(2):
            seen.append(set())
            assert (
                client.post(
                    "/api/books/covers/backfill", headers=admin["headers"]
                ).status_code
                == 200
            )

        first, second = seen
        assert first, f"no fetch ran, so this arm measured nothing: {seen}"
        assert second, f"no fetch ran, so this arm measured nothing: {seen}"
        assert first & second, (
            "the second press ran on none of the first press's worker threads, which "
            "is what a pool built inside the handler and shut down with the request "
            f"looks like: {first} then {second}"
        )


class TestThePoolsCapacityIsTheWaveItIsSubmittedIn:
    """The two sites that have to agree, and nothing else reads both.

    The wave's width is `covers.MAX_CONCURRENT_FETCHES` read at request time; the
    pool's capacity is whatever it was built to at import. Nothing else joins them,
    so `ThreadPoolExecutor(covers.MAX_CONCURRENT_FETCHES * 4)` hands the pod four
    waves' worth of slots and is green in every other arm here: measured
    2026-09-26. That is the class this route's change exists to close, at a quarter
    strength.

    **This is an agreement between two sites in one module, not the value of the
    six.** The value has no second derivation, which this file's own docstring
    says; the agreement has one, and it is the constant the handler reads.
    """

    def test_the_pool_holds_exactly_one_waves_slots(self):
        pool = covers.FETCHES_AT_ONCE

        assert isinstance(pool, ThreadPoolExecutor), (
            f"the bound is a {type(pool).__qualname__}, which hands out fetch "
            "threads differently from the pool the handler submits waves to"
        )
        # Private, for `_built_to`'s reason in `test_concurrency_bounds.py`: the
        # capacity a pool was built to is not otherwise readable, and the public
        # alternative is to count the threads it happens to have started.
        assert pool._max_workers == covers.MAX_CONCURRENT_FETCHES, (
            f"the pod's pool holds {pool._max_workers} fetch slots where a wave is "
            f"{covers.MAX_CONCURRENT_FETCHES}, so the two have drifted and the "
            "bound is whichever is larger"
        )


class TestEveryBookIsBoundedAndNotOnlyEveryHop:
    def test_every_fetch_is_given_the_runs_per_book_budget(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """With no budget `covers.resolve_and_store` bounds a hop and not a book, so
        a book behind a service that blackholes every redirect costs a multiple of
        what a wave was meant to. The default is `None` and is not an error, so
        nothing but this reports a route that stops passing one."""
        _books(admin["headers"], make_book, 2)
        asked = _fetches_that_store(monkeypatch)

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 2
        assert [one["budget"] for one in asked] == [
            books_router.COVER_BACKFILL_BUDGET_SECONDS
        ] * 2


class TestTheRunIsBoundedInWallClockAndNotOnlyInBooks:
    def test_a_batch_that_never_gets_a_slot_answers_and_leaves_the_cursor_alone(
        self, client, admin, make_book, covers_dir, monkeypatch, slots
    ):
        """Nothing was examined, so nothing may be cleared and nothing may be spent
        at the image services.

        The cursor is asserted against a **non zero** `after_id`, because 0 is also
        what the end of the library answers: a run that lost the cursor and a run
        that finished the library are the same reply, and only a press that started
        partway through can tell them apart.
        """
        books = _books(admin["headers"], make_book, 3)
        asked = _fetches_that_store(monkeypatch)
        _deadline(monkeypatch, 0.1)
        slots(0)

        body = client.post(
            "/api/books/covers/backfill",
            params={"after_id": books[0]["id"]},
            headers=admin["headers"],
        ).json()

        assert body["examined"] == 0
        assert body["remaining"] == 2
        assert body["next_after_id"] == books[0]["id"]
        assert asked == []

    def test_a_wave_whose_slots_run_out_mid_way_examines_only_what_started(
        self, client, admin, make_book, covers_dir, monkeypatch, slots
    ):
        """One wave, one slot: the book that got the slot is examined and the two
        behind it are not.

        **This is the arm for where the wave's cancels sit.** The handler cancels
        every unstarted submission of a wave before reading any of them. Interleaved,
        the read of the first offset blocks for up to a whole
        `COVER_BACKFILL_BUDGET_SECONDS`, and the pool is process wide, so a worker
        freed during that read dequeues the next offset and starts it: its `cancel`
        answers False, it is waited for from its own start, and the wave drains
        serially. Measured that way at a 0.1s deadline and a 0.3s fetch: the whole
        wave examined, `remaining` 0, no cut reported, and 0.919s held against the
        0.400s the deadline claims. The counts are what say so here, so the arm needs
        no timing assertion.
        """
        spent_fetching = 0.3
        books = _books(admin["headers"], make_book, 3)
        slots(len(books))

        def fake(book_id, isbn, supplied, budget=None):
            time.sleep(spent_fetching)
            (COVERS_DIR / f"{book_id}.jpg").write_bytes(JPEG_BYTES)
            return f"/covers/{book_id}.jpg"

        monkeypatch.setattr(covers, "resolve_and_store", fake)
        monkeypatch.setattr(covers, "MAX_CONCURRENT_FETCHES", len(books))
        _deadline(monkeypatch, 0.1)

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 1
        assert body["next_after_id"] == books[0]["id"]
        assert body["remaining"] == 2

    def test_a_wave_that_overruns_the_deadline_is_counted_and_starts_no_successor(
        self, client, admin, make_book, covers_dir, monkeypatch, slots
    ):
        """The other way a run ends, and the only arm here that reaches the check
        between waves.

        The arms around this one expire the deadline while a wave is **queued**, so
        the cut happens at `Future.cancel` and the check at the top of the loop is
        never what stops the run. This arm expires it while a wave is **running**:
        the fetch cannot be cancelled and is waited for, so its book is counted, and
        what must not happen is a further wave being submitted afterwards.

        **What holds the check is the submission count, and the reply cannot.**
        Measured 2026-09-26 by disabling that check: the loop then submits every
        remaining wave and cancels each one where the wait has nothing left to give,
        so `examined`, the counts and the cursor all come back identical and this arm
        was green on the mutation it was written for. What differs is how many
        submissions the pod's pool was handed, which is what a run past its deadline
        must not be spending, and a submission is counted before anything can cancel
        it, so the count has no race in it where the reply does.

        **A real sleep, and it is a floor rather than a race.** The fetch sleeps
        longer than the deadline, so the deadline is spent by the time the wave is
        collected however loaded the node is; a slower node makes the margin larger.
        """
        spent_fetching = 0.15
        books = _books(admin["headers"], make_book, 4)
        pool = slots(len(books))

        def fake(book_id, isbn, supplied, budget=None):
            time.sleep(spent_fetching)
            (COVERS_DIR / f"{book_id}.jpg").write_bytes(JPEG_BYTES)
            return f"/covers/{book_id}.jpg"

        monkeypatch.setattr(covers, "resolve_and_store", fake)
        monkeypatch.setattr(covers, "MAX_CONCURRENT_FETCHES", 1)
        _deadline(monkeypatch, 0.1)
        assert spent_fetching > books_router.COVER_BACKFILL_DEADLINE_SECONDS, (
            "the fetch no longer outlasts the deadline set here, so this arm would "
            "be about a run that was never cut at all"
        )

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert pool.asked == covers.MAX_CONCURRENT_FETCHES, (
            f"the run handed the pod's pool {pool.asked} fetches where one wave is "
            f"{covers.MAX_CONCURRENT_FETCHES}, so it went on submitting waves past "
            "its own deadline and cancelled them at the far end"
        )
        assert body["examined"] == 1
        assert body["stored"] == 1
        assert body["next_after_id"] == books[0]["id"]
        assert body["remaining"] == 3

    def test_a_run_cut_short_advances_the_cursor_over_the_prefix_and_no_further(
        self, client, admin, make_book, covers_dir, monkeypatch, slots
    ):
        """Two books fetched, two never reached, and the cursor clears two.

        `batch[-1].id` would clear all four, and the two nobody fetched would come
        back only when the cursor wrapped to 0 at the end of the library.
        """
        books = _books(admin["headers"], make_book, 4)
        _fetches_that_store(monkeypatch)
        monkeypatch.setattr(covers, "MAX_CONCURRENT_FETCHES", 2)
        _deadline(monkeypatch, 0.5)
        slots(2)

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 2
        assert body["stored"] == 2
        assert body["next_after_id"] == books[1]["id"]
        assert body["remaining"] == 2

    def test_a_run_cut_short_never_reports_the_library_finished(
        self, client, admin, make_book, covers_dir, monkeypatch, slots
    ):
        """0 means "start over", so a cut answering 0 would leave the rest of the
        library unexamined until somebody pressed a whole pass later."""
        _books(admin["headers"], make_book, 4)
        _fetches_that_store(monkeypatch)
        monkeypatch.setattr(covers, "MAX_CONCURRENT_FETCHES", 2)
        _deadline(monkeypatch, 0.5)
        slots(2)

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert body["remaining"] > 0
        assert body["next_after_id"] != 0

    def test_the_next_press_resumes_at_the_first_book_the_cut_did_not_reach(
        self, client, admin, make_book, covers_dir, monkeypatch, slots
    ):
        """The other half of the cursor rule: nothing is skipped and nothing is
        fetched twice."""
        books = _books(admin["headers"], make_book, 4)
        asked = _fetches_that_store(monkeypatch)
        monkeypatch.setattr(covers, "MAX_CONCURRENT_FETCHES", 2)
        _deadline(monkeypatch, 0.5)
        slots(2)

        first = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()
        slots(4)
        second = client.post(
            "/api/books/covers/backfill",
            params={"after_id": first["next_after_id"]},
            headers=admin["headers"],
        ).json()

        assert second["examined"] == 2
        assert second["stored"] == 2
        assert second["remaining"] == 0
        assert second["next_after_id"] == 0
        assert [one["book_id"] for one in asked] == [book["id"] for book in books]


class _AWaveWhoseMiddleNeverStarted:
    """A wave in which a middle submission stayed queued and a later one ran.

    **Built rather than raced, and the shape is reachable.** The pool is process
    wide, so a worker freed by another member's fetch dequeues the next item of this
    wave while the handler is still walking it: measured on the real primitive by the
    evasion pass, 200 of 200 waves when the loop spends any time between two offsets,
    which is what reading a future does.
    """

    def __init__(self, pending_at: int) -> None:
        self.pending_at = pending_at
        self.asked = 0

    def submit(self, call: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        at = self.asked
        self.asked += 1
        made: Future[Any] = Future()
        if at == self.pending_at:
            return made
        made.set_running_or_notify_cancel()
        made.set_result(call(*args, **kwargs))
        return made


class TestTheCursorNeverPassesABookTheRunNeverStarted:
    """The prefix, which is the one thing a cursor may not overstate.

    Replacing the prefix slice with a filter over the outcomes that are not `None`
    survived every other arm here, measured 2026-09-26: the counts are identical
    whenever the unexamined books sit at the end. This arm is the case where they do
    not, and it needs no race and no sleep. Written by the evasion pass.
    """

    def test_a_wave_whose_middle_never_started_clears_only_the_prefix(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        books = _books(admin["headers"], make_book, 3)
        _fetches_that_store(monkeypatch)
        monkeypatch.setattr(covers, "MAX_CONCURRENT_FETCHES", 3)
        monkeypatch.setattr(
            covers, "FETCHES_AT_ONCE", _AWaveWhoseMiddleNeverStarted(pending_at=1)
        )
        _deadline(monkeypatch, 0.1)

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 1
        assert body["stored"] == 1
        assert body["next_after_id"] == books[0]["id"], (
            "the cursor passed a book no fetch ever started, so that book comes back "
            "only when the cursor wraps at the end of the library"
        )
        assert body["remaining"] == 2


class TestARunNeverDropsACoverItDidNotChoose:
    def test_a_run_that_re_resolves_an_unrenderable_stored_cover_keeps_it(
        self, client, admin, make_book, covers_dir, db, monkeypatch
    ):
        """What the `url != book.cover_url` guard in the run's own `record` buys.

        Not the `UPDATE`, which the unit of work elides for an equal value, measured
        with a cursor listener. `Book._store_covers_over_https` **drops** a value it
        finds unrenderable, `backup.restore` writes this column through Core where
        `@validates` does not fire, and `covers.resolve_and_store` answers with
        `supplied` when the download fails. So an unrenderable stored cover comes
        back equal to the column, and assigning it would null the only cover that row
        has, on a run that repaired nothing.

        The value is written here the way `restore` writes it, through Core.
        """
        from models import Book

        book = make_book(admin["headers"], title="Restored")
        stored = "//cdn.example/x.jpg"
        db.query(Book).filter(Book.id == book["id"]).update({"cover_url": stored})
        db.commit()
        monkeypatch.setattr(
            covers,
            "resolve_and_store",
            lambda book_id, isbn, supplied, budget=None: supplied,
        )

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 1
        assert body["unreachable"] == 1
        db.expire_all()
        assert db.query(Book).filter(Book.id == book["id"]).one().cover_url == stored


class TestTheDeadlineAndTheBudgetAreDerivedRatherThanChosen:
    """Their derivations, recomputed from their own sources.

    A number written down stops being re-derived and starts being copied, so the
    derivations that are arithmetic over constants in this tree are asserted. The
    proxy's read timeout, which is the third thing the deadline is sized against,
    is not here and is not named anywhere in this tree: it is a dependency default
    nobody in this deployment set.
    """

    def test_this_route_holds_a_connection_no_longer_than_its_sibling(self):
        """Little's law over this route's own limiter, on the **hold** rather than
        on the deadline.

        The hold is the deadline plus one `COVER_BACKFILL_BUDGET_SECONDS`, because
        waves are sequential and the check before each one is `left(ends) <= 0`: a
        wave admitted just under the deadline runs a full book after it. **One budget
        and not one per book of the wave**, which is true of the handler only while
        it cancels a wave's unstarted submissions before reading any of them;
        `test_a_wave_whose_slots_run_out_mid_way_examines_only_what_started` is what
        holds that, and this arm is green over the wrong figure without it.

        **Against the sibling route's hold rather than against the pool's size.**
        `IDENTIFIER_BACKFILL_DEADLINE_SECONDS` argues that hold down to a share of
        the pool and states the pool's own figure, which is a library default nobody
        here sets; a copy of it in this file would be its third home and would go
        stale against the two that argue from it. What this holds is that the route
        with the more expensive book does not hold a connection longer than the one
        whose share was argued, which is the comparison a rise in either figure has
        to survive.
        """
        ours = ratelimit.COVER_BACKFILL_LIMIT
        theirs = ratelimit.IDENTIFIER_BACKFILL_LIMIT
        assert (
            ours.max_attempts / ours.window_seconds
            == theirs.max_attempts / theirs.window_seconds
        ), (
            "the two backfills no longer admit presses at the same rate, so their "
            "holds cannot be compared directly and this arm has to carry the "
            f"arrival rate: {ours} against {theirs}"
        )

        hold = (
            books_router.COVER_BACKFILL_DEADLINE_SECONDS
            + books_router.COVER_BACKFILL_BUDGET_SECONDS
        )
        sibling = (
            books_router.IDENTIFIER_BACKFILL_DEADLINE_SECONDS + fetch.TIMEOUT_SECONDS
        )

        assert hold <= sibling, (
            f"a cover backfill run may hold a connection for {hold}s against the "
            f"identifier backfill's {sibling}s, which is the figure argued down to a "
            "share of the pool. At this route's own limiter that is "
            f"{ours.max_attempts / ours.window_seconds * hold} runs in flight from "
            "one member. **Either figure may have moved**: this route's deadline or "
            "budget grew, or the sibling's deadline was tightened, and in the second "
            "case the edit this is asking for is over there or it is an argument that "
            "these two holds need not be compared at all"
        )

    def test_a_cut_lands_on_a_wave_boundary_rather_than_mid_wave(self):
        """Whole books of budget, so no wave is abandoned half done in the case
        where every book spends its whole budget."""
        assert (
            books_router.COVER_BACKFILL_DEADLINE_SECONDS
            % books_router.COVER_BACKFILL_BUDGET_SECONDS
            == 0
        )

    def test_a_books_budget_is_whole_hops(self):
        """A budget that is not a multiple of `covers.TIMEOUT_SECONDS` buys a
        fraction of a hop it can never spend: `_hop_seconds` gives a hop the smaller
        of that timeout and what is left, so the remainder is time a walk holds a
        slot for and cannot finish a request in.

        **So moving the hop timeout is an edit to the budget**, and this arm is where
        that is noticed: `covers.TIMEOUT_SECONDS` at 5 reddens it on `12 % 5`, and
        the constant to change is `COVER_BACKFILL_BUDGET_SECONDS`, whose own comment
        says so.
        """
        assert (
            books_router.COVER_BACKFILL_BUDGET_SECONDS % covers.TIMEOUT_SECONDS == 0
        )
