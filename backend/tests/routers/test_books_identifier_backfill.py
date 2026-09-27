"""Tests for the store identifier backfill on backend/routers/books.py.

  POST /api/books/{id}/enrich          the identifier branch, one book
  POST /api/books/identifiers/backfill the whole library, in batches

The subject is a Google Play Books import: that export carries a Google Books
volume id on every book and no ISBN anywhere, so an exact key is the only key
such a library has, and before this the only enrichment available to it was a
search by title and author.

Every outbound call is intercepted with respx, so the suite never touches the
network and never needs a real key. **The request counts below are the point of
this file**, not a detail of it: what the feature buys is measured here rather
than asserted in prose.
"""

import asyncio
from collections.abc import Awaitable

import httpx
import pytest
import respx

import sources
from tests.helpers import GOOGLE_BOOKS, silence_catalogues
from tests.routers.test_concurrency_bounds import _built_to, _the_bound

VOLUME_ID = "s7NIrgEACAAJ"
OTHER_VOLUME_ID = "abcdefghijkl"


#: How long a parked acquire waits here before it accuses the handler.
#:
#: **Ten times the largest deadline any arm below sets**, so it never fires while
#: the deadline is where it belongs, and it bounds the wait when it is not. What
#: ends a parked acquire is supposed to be the handler's own deadline; a
#: `asyncio.timeout` moved off the acquire and onto `google.volume` leaves nothing
#: ending it, and then these arms **hang instead of failing**. Measured
#: 2026-09-26, planting exactly that: a worker parked for nine minutes with no
#: verdict, and `-o faulthandler_timeout=60` dumped the tracebacks without
#: aborting it, so nothing in this repository bounded the wait. A test that hangs
#: is worse than one that is missing, because a missing one is visible in a count.
_WAITED_PAST_EVERY_DEADLINE_SECONDS = 5.0


async def _parked(waiting: Awaitable[bool]) -> bool:
    """Wait on something nothing here will ever complete, then accuse.

    **`AssertionError` and never `TimeoutError`.** The handler answers a
    `TimeoutError` out of its acquire by returning `None`, which is its own
    deadline firing, so a `wait_for` leaking one would be read as success by the
    thing under test.

    The raise happens inside the request and **`TestClient` re-raises it at the
    `client.post(...)` call with this message**, which is the behaviour to want:
    `raise_server_exceptions` is left at its default, so the arm fails saying what
    is wrong rather than asserting on a 500 whose cause is in a log.
    """
    try:
        return await asyncio.wait_for(waiting, _WAITED_PAST_EVERY_DEADLINE_SECONDS)
    except TimeoutError:
        raise AssertionError(
            f"the handler waited {_WAITED_PAST_EVERY_DEADLINE_SECONDS}s for a slot, "
            "past its own deadline: the deadline is not on the acquire"
        ) from None


class _SlotsThatRunOut:
    """A stand-in for the module level bound that grants `at_most` slots ever.

    **Not a semaphore, because a semaphore cannot express this.** `resolve`
    releases its slot in a `finally`, so a wave hands its slots back and the next
    wave takes them: an `asyncio.Semaphore(2)` starves nothing after the first
    wave. This grants a fixed number of acquires for the whole run and parks
    every later one, which is the state a batch queued behind somebody else's
    longer batch is in.

    It has exactly the two methods the handler uses. A parked `acquire` waits on
    an `Event` nothing sets, so it is cancellable and carries no timer of its own
    beyond `_parked`'s: what is supposed to end the wait is the handler's own
    deadline, which is the thing under test.
    """

    def __init__(self, at_most: int) -> None:
        self._left = at_most

    async def acquire(self) -> bool:
        if self._left > 0:
            self._left -= 1
            return True
        return await _parked(asyncio.Event().wait())

    def release(self) -> None:
        """Deliberately does not give the slot back. They ran out, which is what
        puts the next wave in the state these arms are about."""


class _SlotsThatCount:
    """The module level bound, plus the peak number of slots held at once.

    **The peak is the one deterministic observable the wave shape moves.**
    Whether a wave is six books or six lookups changes neither what a run
    examines nor where the cursor lands when slots are plentiful; it changes how
    many lookups a wave carries, and therefore how many books a deadline buys. A
    temporal arm was written and refused: separating the two needs a deadline
    tight enough to cut between their wave counts, which on a shared worker node
    is a coin toss rather than an assertion.

    **It has to yield after acquiring, and the first version did not.** A peak
    only exists if a wave's lookups are in flight together, and under respx they
    are not: the mocked transport answers without suspending, so each lookup ran
    acquire, request and release to completion before the next coroutine resumed
    and the peak read **1 under both shapes**. Measured 2026-09-26, on the arm
    below, which failed rather than passing: the first version's docstring claimed
    the overlap held "because `google.volume` awaits a transport", which is true of
    a real one and false of this suite's.

    So the yield restores what a real network gives for nothing. It is one loop
    iteration and no wall clock, which is the whole reason this is the observable
    rather than a duration.
    """

    def __init__(self, at_most: int) -> None:
        self._real = asyncio.Semaphore(at_most)
        self._held = 0
        self.peak = 0

    async def acquire(self) -> bool:
        got = await _parked(self._real.acquire())
        self._held += 1
        self.peak = max(self.peak, self._held)
        # Hand the loop to the wave's other lookups before this one can release.
        # Without it the peak is 1 whatever the wave shape is; see the docstring.
        await asyncio.sleep(0)
        return got

    def release(self) -> None:
        self._held -= 1
        self._real.release()


class _SlotsThatNeverCome:
    """A real `asyncio.Semaphore(0)` behind a wait that accuses rather than hangs.

    The real class on purpose, because its own cancellation path is what the site
    comment in `routers/books.py` claims leaks no slot, and `wait_for` cancels a
    pending `acquire` exactly as the handler's deadline does.
    """

    def __init__(self) -> None:
        self._real = asyncio.Semaphore(0)

    async def acquire(self) -> bool:
        return await _parked(self._real.acquire())

    def release(self) -> None:
        self._real.release()


def volume_body(volume_id: str = VOLUME_ID, **info) -> dict:
    """One volume resource as `GET /volumes/{id}` returns it."""
    return {
        "id": volume_id,
        "volumeInfo": {
            "title": "Dune",
            "authors": ["Frank Herbert"],
            "publisher": "Chilton",
            "publishedDate": "1965-08-01",
            "pageCount": 412,
            "language": "en",
        }
        | info,
    }


@pytest.fixture
def google_enabled(client, admin):
    """Switch the feature on and store a key, as an admin would in Settings."""
    client.put(
        "/api/settings",
        json={"google_books_enabled": True, "google_books_api_key": "test-key"},
        headers=admin["headers"],
    )


@pytest.fixture
def catalogues():
    """Every catalogue silent, so a test says which one answers.

    `silence_catalogues` is registered **last**, per its own docstring: routes
    resolve in registration order and the first match wins.
    """
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def volume_route(mock, volume_id: str = VOLUME_ID, response=None):
    """Google answering for one volume id, with everything else silenced."""
    route = mock.get(f"{GOOGLE_BOOKS}/{volume_id}").mock(
        return_value=response or httpx.Response(200, json=volume_body(volume_id))
    )
    silence_catalogues(mock)
    return route


def imported_book(client, headers, make_book, volume_id: str = VOLUME_ID) -> dict:
    """A book as a Play Books import leaves it: a title, an author, no ISBN."""
    return make_book(
        headers,
        title="Dune",
        author="Frank Herbert",
        identifiers=[{"scheme": "google_books", "value": volume_id}],
    )


class TestWhatOneImportedBookCosts:
    """The measurement, taken through the route rather than argued.

    Both arms enrich the same book from the same fixture data. What differs is
    how many third party requests it took and what came back.
    """

    def test_without_the_identifier_it_is_a_fan_out_and_a_title_match(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """The path this replaces: no ISBN, so every search catalogue is asked.

        The book carries no identifier at all, which is what a Play Books import
        looked like before `book_identifiers` existed and what a Kindle import
        still looks like.
        """
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        silence_catalogues(catalogues)

        res = client.post(
            f"/api/books/{book['id']}/enrich", headers=admin["headers"]
        )

        assert res.status_code == 200
        # **Derived from the roster rather than written down.** A literal here
        # would be a roster sized number in a test file, which is the shape
        # `tests/test_roster_counts.py` exists to refuse: it goes stale the day
        # a catalogue joins, and a smaller literal is a weaker assertion that
        # would pass on a fan out that had quietly shrunk.
        assert catalogues.calls.call_count == len(sources.DEFAULT_PLAN.searched)

    def test_with_the_identifier_it_is_one_request_and_an_exact_record(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        book = imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        res = client.post(
            f"/api/books/{book['id']}/enrich", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert res.json()["found"] is True
        assert res.json()["book"]["page_count"] == 412
        assert res.json()["book"]["google_books_id"] == VOLUME_ID
        assert catalogues.calls.call_count == 1

    def test_the_one_request_is_the_volume_endpoint(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        book = imported_book(client, admin["headers"], make_book)
        route = volume_route(catalogues)

        client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        assert route.call_count == 1
        assert route.calls[0].request.url.path.endswith(f"/volumes/{VOLUME_ID}")


def statements_for(client, url: str, headers: dict[str, str]) -> int:
    """SELECTs issued while one POST is served.

    `tests.helpers.select_count` is the same instrument for a GET and takes no
    body; this is the POST it does not cover.
    """
    from sqlalchemy import event

    from database import engine

    seen: list[str] = []

    def record(conn, cursor, statement, *rest):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        client.post(url, headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len([row for row in seen if row.lstrip().upper().startswith("SELECT")])


class TestWhatABatchCostsTheDatabase:
    """The per book database cost, measured at two sizes rather than one.

    **Two sizes, because one is a number and two are a slope**, which is
    `tests.helpers.select_count`'s own reason for the same shape. The slope is
    what says whether a library of nine hundred books is nine hundred
    statements or nine hundred times something.

    **One statement per book is expected and is not an N+1 to remove.**
    `_resolvable_volume_id` reads `book.identifiers` off the relationship rather
    than querying `book_identifiers`, which is what keeps this route out of
    `tests/test_shelf.py`'s fourth pass, and it is paid on a path that is about
    to make one HTTPS request per book. A statement against a local index beside
    a network round trip is not the cost worth removing; it would be if this ran
    on a listing, which is what `_books_to_out` batches for.
    """

    def _measure(self, client, headers, make_book, books: int) -> int:
        for _ in range(books):
            imported_book(client, headers, make_book)
        return statements_for(client, "/api/books/identifiers/backfill", headers)

    def test_one_statement_per_book_and_no_more(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        volume_route(catalogues)

        two = self._measure(client, admin["headers"], make_book, 2)
        # The first run recorded a volume on both books, so they stop being
        # candidates and the next measurement is over the two new ones only.
        four = self._measure(client, admin["headers"], make_book, 2)

        assert (two, four) == (12, 12), (
            f"a batch of two costs {two} SELECTs and the next two cost {four}. "
            "Both are the same batch size, so the two figures must agree; they "
            "are taken twice because the second runs against a larger library, "
            "and a cost that grew with the library rather than with the batch "
            "would show up here and nowhere else. Ten of the twelve are fixed "
            "and are **not itemised**: what this pins is that the figure does "
            "not move, and `test_the_slope_is_one_statement_a_book` below is "
            "what says which part of it is per book."
        )

    def test_the_slope_is_one_statement_a_book(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        volume_route(catalogues)

        one = self._measure(client, admin["headers"], make_book, 1)
        three = self._measure(client, admin["headers"], make_book, 3)

        assert three - one == 2, (
            f"one book costs {one} SELECTs and three cost {three}, a slope of "
            f"{(three - one) / 2} a book. One is the relationship read in "
            "`_resolvable_volume_id`; anything more is a second per book query "
            "that has appeared."
        )


class TestTheSingleBookBranch:
    def test_an_isbn_that_resolves_means_the_volume_is_never_asked(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """Exact keys in order: the free chain before the metered identifier.

        An ISBN is a key the whole roster answers to, so it is asked first and
        the volume endpoint is not asked at all when it produces a record.
        """
        book = make_book(
            admin["headers"],
            title="Dune",
            isbn="9780441013593",
            identifiers=[{"scheme": "google_books", "value": VOLUME_ID}],
        )
        # **Both registered before `silence_catalogues`**, which is that
        # helper's own rule: routes resolve in registration order, the first
        # match wins, and a route added after a catch-all is unreachable. Adding
        # this one afterwards is exactly how an earlier version of this test
        # passed for the wrong reason.
        volume = catalogues.get(f"{GOOGLE_BOOKS}/{VOLUME_ID}").mock(
            return_value=httpx.Response(200, json=volume_body())
        )
        catalogues.get(
            GOOGLE_BOOKS, params__contains={"q": "isbn:9780441013593"}
        ).mock(return_value=httpx.Response(200, json={"items": [volume_body()]}))
        silence_catalogues(catalogues)

        res = client.post(
            f"/api/books/{book['id']}/enrich", headers=admin["headers"]
        )

        assert res.json()["found"] is True
        assert volume.call_count == 0

    def test_an_isbn_nothing_answers_falls_through_to_the_volume(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """And it falls through rather than stopping, which is the point.

        A book can carry an ISBN no catalogue holds and a volume id Google does.
        Stopping at the first exact key would lose that book to a title search.
        """
        book = make_book(
            admin["headers"],
            title="Dune",
            isbn="9780441013593",
            identifiers=[{"scheme": "google_books", "value": VOLUME_ID}],
        )
        route = volume_route(catalogues)

        res = client.post(
            f"/api/books/{book['id']}/enrich", headers=admin["headers"]
        )

        assert route.call_count == 1
        assert res.json()["book"]["page_count"] == 412

    def test_a_miss_falls_through_to_the_title_search(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """A stale volume id must not cost the book its enrichment.

        This is the bound the task set: an import that died because a lookup
        failed would be worse than the title matching it replaces.
        """
        book = imported_book(client, admin["headers"], make_book)
        volume_route(catalogues, response=httpx.Response(404))

        res = client.post(
            f"/api/books/{book['id']}/enrich", headers=admin["headers"]
        )

        assert res.status_code == 200
        # One volume request, then the whole search roster, derived for the
        # reason the fan out above is.
        assert catalogues.calls.call_count == 1 + len(sources.DEFAULT_PLAN.searched)

    def test_google_switched_off_asks_nothing_and_still_searches(
        self, client, admin, make_book, catalogues
    ):
        """No key, so Google is not in the plan and the volume is not asked.

        The route does not fail: the rest of the roster still answers a title
        search. What must not happen is a request to Google on behalf of a
        library that has not switched it on.
        """
        book = imported_book(client, admin["headers"], make_book)
        route = volume_route(catalogues)

        res = client.post(
            f"/api/books/{book['id']}/enrich", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert route.call_count == 0

    def test_an_unresolvable_identifier_is_not_asked_about(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """A stored value that is not a volume id never becomes a URL.

        `book_identifiers` takes any opaque token, and `backup.restore` writes
        the table through Core with no Pydantic model, so the shape check is the
        server's own or it is nobody's.
        """
        book = imported_book(client, admin["headers"], make_book, "not-an-id")
        route = catalogues.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(200, json=volume_body())
        )
        silence_catalogues(catalogues)

        client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        assert all(
            "/volumes/not-an-id" not in str(call.request.url)
            for call in route.calls
        )


class TestTheBackfill:
    def test_resolves_a_library_of_imported_books(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        for _ in range(3):
            imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        res = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        )

        assert res.status_code == 200
        body = res.json()
        assert body["examined"] == 3
        assert body["enriched"] == 3
        assert body["remaining"] == 0
        assert body["next_after_id"] == 0

    def test_one_request_per_book(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """The headline. Three books, three outbound requests.

        The same three books enriched by title and author are three times the
        search roster, which `test_without_the_identifier_it_is_a_fan_out_and_a_title_match`
        measures.
        """
        for _ in range(3):
            imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        client.post("/api/books/identifiers/backfill", headers=admin["headers"])

        assert catalogues.calls.call_count == 3

    def test_the_counts_add_up_to_what_was_examined(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        imported_book(client, admin["headers"], make_book)
        imported_book(client, admin["headers"], make_book, OTHER_VOLUME_ID)
        volume_route(catalogues)
        catalogues.get(f"{GOOGLE_BOOKS}/{OTHER_VOLUME_ID}").mock(
            return_value=httpx.Response(404)
        )

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 2
        assert (
            body["enriched"] + body["not_found"] + body["unavailable"]
            + body["unresolvable"]
            == body["examined"]
        )
        assert body["not_found"] == 1

    def test_a_book_with_an_isbn_is_not_a_candidate(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """A free exact key exists, so a metered request would be a bill for nothing."""
        make_book(
            admin["headers"],
            title="Dune",
            isbn="9780441013593",
            identifiers=[{"scheme": "google_books", "value": VOLUME_ID}],
        )
        route = volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 0
        assert route.call_count == 0

    def test_running_it_twice_examines_nothing_the_second_time(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """Idempotent, because a resolved book records the volume it came from.

        Without that the same books are re-fetched on every press, which on a
        metered source is a bill that repeats.
        """
        imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        client.post("/api/books/identifiers/backfill", headers=admin["headers"])
        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 0

    def test_an_unresolvable_identifier_clears_the_cursor(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """A row that can never resolve must not park the run on itself.

        It is examined, counted with the volumes Google does not have, and the
        cursor moves past it. Left out of `examined` it would sit at the front
        of every subsequent batch for ever, which is the failure the cover
        backfill's own cursor was added for.
        """
        imported_book(client, admin["headers"], make_book, "not-an-id")
        volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 1
        assert body["unresolvable"] == 1
        assert catalogues.calls.call_count == 0

    def test_an_unresolvable_identifier_is_counted_apart(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """Not Google's answer, so not reported as one.

        Both are permanent and neither will resolve, which is the argument for
        one number; only one of them is something Google said, which is the
        argument against. **This is also what makes
        `_resolvable_volume_id`'s shape check observable**: `metadata.
        lookup_volume` refuses the same values, so with the two folded together
        deleting that check changed nothing any test could see.
        """
        imported_book(client, admin["headers"], make_book, "not-an-id")
        imported_book(client, admin["headers"], make_book)
        volume_route(catalogues, response=httpx.Response(404))

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["unresolvable"] == 1
        assert body["not_found"] == 1

    def test_a_two_hundred_carrying_no_volume_is_not_an_answer(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """A body with `volumeInfo` and no `id` is not a volume resource.

        Read as one it wrote nothing and **left the book a candidate**, so every
        press spent another metered request on it and reported a clean run. It
        is no volume, so no record came back, so it is a miss: the book stays a
        candidate, which is right, and the count no longer says it was enriched.
        """
        imported_book(client, admin["headers"], make_book)
        volume_route(
            catalogues,
            response=httpx.Response(200, json={"volumeInfo": {"title": "Dune"}}),
        )

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["enriched"] == 0
        assert body["not_found"] == 1

    def test_a_batch_reports_a_cursor_and_the_next_press_carries_on(
        self, client, admin, make_book, google_enabled, catalogues, monkeypatch
    ):
        import routers.books as books_router

        monkeypatch.setattr(books_router, "MAX_IDENTIFIER_BACKFILL", 2)
        for _ in range(3):
            imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        first = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()
        assert first["examined"] == 2
        assert first["remaining"] == 1
        assert first["next_after_id"] > 0

        second = client.post(
            f"/api/books/identifiers/backfill?after_id={first['next_after_id']}",
            headers=admin["headers"],
        ).json()
        assert second["examined"] == 1
        assert second["next_after_id"] == 0

    def test_an_outage_is_reported_as_one_and_not_as_a_miss(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """Transient and permanent are different things to do next.

        `not_found` says the identifier is stale; `unavailable` says press again.
        Collapsing them sends somebody to retype a book that was going to
        resolve on its own.
        """
        imported_book(client, admin["headers"], make_book)
        volume_route(catalogues, response=httpx.Response(503))

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["unavailable"] == 1
        assert body["not_found"] == 0

    def test_a_rate_limit_is_an_outage_rather_than_a_failure(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """429 must not lose the book: it is counted and stays a candidate."""
        imported_book(client, admin["headers"], make_book)
        volume_route(catalogues, response=httpx.Response(429))

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["unavailable"] == 1

        # Still a candidate, because nothing was written.
        again = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()
        assert again["examined"] == 1

    def test_without_a_key_it_refuses_rather_than_reporting_a_clean_run(
        self, client, admin, make_book, catalogues
    ):
        """A source with no usable key must not become a source that answers nothing.

        Zero examined is the answer a member cannot act on: it looks like a
        library with nothing to fix rather than one with a switch turned off.
        """
        imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        res = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        )

        assert res.status_code == 409
        assert "Google Books" in res.json()["detail"]

    def test_another_member_s_private_book_is_not_a_candidate(
        self, client, admin, member, make_book, google_enabled, catalogues
    ):
        """The privacy rule, on the one route here that reads a whole library."""
        make_book(
            member["headers"],
            title="Dune",
            is_private=True,
            identifiers=[{"scheme": "google_books", "value": VOLUME_ID}],
        )
        route = volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 0
        assert route.call_count == 0

    def test_an_asin_is_not_a_candidate(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """Amazon publishes no catalogue API, so an ASIN is not resolvable here.

        Counting one would report a library as repairable that is not.
        """
        make_book(
            admin["headers"],
            title="Dune",
            identifiers=[{"scheme": "asin", "value": "B00J4YQKHY"}],
        )
        route = volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 0
        assert route.call_count == 0

    def test_it_does_not_overrule_what_somebody_typed(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """The merge rule is the same one enrichment has everywhere here."""
        book = imported_book(client, admin["headers"], make_book)
        client.patch(
            f"/api/books/{book['id']}",
            json={"publisher": "A publisher somebody typed"},
            headers=admin["headers"],
        )
        volume_route(catalogues)

        client.post("/api/books/identifiers/backfill", headers=admin["headers"])

        after = client.get(
            f"/api/books/{book['id']}", headers=admin["headers"]
        ).json()
        assert after["publisher"] == "A publisher somebody typed"
        assert after["page_count"] == 412


class TestTheBatchIsBoundedInWallClockAndNotOnlyInBooks:
    """The half the structural guard in `test_concurrency_bounds.py` cannot see.

    That guard reads where the bound is built. It cannot tell a deadline spent
    on the slot from one spent on the request, and the difference is the whole
    case: a deadline threaded down to `fetch` bounds no waiter at all, and one
    around the `gather` loses every answer that already arrived and spends up to
    `MAX_IDENTIFIER_BACKFILL` metered requests for a 500.

    **Every arm here replaces the module level bound with a fresh object, and
    that is not tidiness.** `asyncio.Semaphore.acquire` calls `_get_loop()` only
    on the contended path, which is why an uncontended module level semaphore
    survives a suite that gives every test its own loop
    (`asyncio_default_fixture_loop_scope = "function"`). Contending the real one
    binds it to that test's loop and every later request in the same worker
    raises `RuntimeError: ... is bound to a different event loop`, and its
    `_value` is left decremented by the abandoned waiter. Testing a queue means
    contending it, so a fresh object per arm is the only safe way to do it.
    """

    @staticmethod
    def _deadline(monkeypatch, seconds: float) -> None:
        """Set the handler's deadline, holding the relation `_parked` rests on.

        `_WAITED_PAST_EVERY_DEADLINE_SECONDS` is justified as ten times the largest
        deadline any arm here sets, and five arms set one by hand. **Nothing held
        that relation, so it was prose**: an arm setting 6.0 would make every
        parked acquire accuse the handler of a defect it does not have, and the
        message it raises names the deadline's placement, so the reader would go
        looking at `resolve`. A false accusation from a guard is worse than a
        missing guard, and it is the direction an author does not check.

        Asserted where the deadline is set rather than beside the constant,
        because that is the edit that can break it.
        """
        assert seconds * 10 <= _WAITED_PAST_EVERY_DEADLINE_SECONDS, (
            f"a deadline of {seconds}s leaves _parked's "
            f"{_WAITED_PAST_EVERY_DEADLINE_SECONDS}s less than ten times the "
            "largest an arm sets, so a parked acquire would accuse the handler "
            "before its own deadline had fired. Raise the constant or lower this."
        )
        import routers.books as books_router

        monkeypatch.setattr(
            books_router, "IDENTIFIER_BACKFILL_DEADLINE_SECONDS", seconds
        )

    @staticmethod
    def _starved(monkeypatch, at_most: int = 0) -> None:
        """Stand the module level bound down to `at_most` slots, ever.

        A real `asyncio.Semaphore(0)` is what "no slot will ever come free"
        looks like and is used where that is the case, behind
        `_SlotsThatNeverCome`'s bounded wait. Where an arm needs the first wave
        to succeed and the second to starve, a semaphore cannot say it:
        `resolve` releases its slot in a `finally`, so a wave hands its slots
        back and the next wave takes them. `_SlotsThatRunOut` above grants a
        fixed number of acquires for the whole run and parks the rest, which is
        the shape a batch queued behind somebody else's longer batch is in.

        **Both park behind `_parked`**, so a deadline that stops ending the wait
        fails an arm rather than hanging a worker.
        """
        import routers.books as books_router

        monkeypatch.setattr(
            books_router,
            "_BACKFILL_LOOKUPS_AT_ONCE",
            _SlotsThatNeverCome() if at_most == 0 else _SlotsThatRunOut(at_most),
        )

    def test_a_batch_that_never_gets_a_slot_answers_and_spends_nothing(
        self, client, admin, make_book, google_enabled, catalogues, monkeypatch
    ):
        """The metered budget, which is what picks the deadline's site.

        A deadline on the slot makes no request it cannot keep. Spent around the
        `gather` instead, or on `asyncio.wait` cancelling the stragglers, every
        one of these books would have been asked for and charged, because
        `for_a_batch_backfill` charges the limiter before a slot is sought and a
        cancelled Google request is already paid for. So the assertion that
        matters here is the call count and not the status.
        """
        self._deadline(monkeypatch, 0.1)
        self._starved(monkeypatch)
        for _ in range(3):
            imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        res = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert catalogues.calls.call_count == 0
        body = res.json()
        assert body["examined"] == 0
        assert body["remaining"] == 3

    def test_a_run_that_gets_no_slot_leaves_the_cursor_where_it_stood(
        self, client, admin, make_book, google_enabled, catalogues, monkeypatch
    ):
        """Nothing was examined, so the cursor may not pass anything.

        `batch[-1].id` would clear all three, and they would come back only when
        the cursor wrapped to 0 at the end of the library.
        """
        self._deadline(monkeypatch, 0.1)
        self._starved(monkeypatch)
        for _ in range(3):
            imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill?after_id=0", headers=admin["headers"]
        ).json()

        assert body["next_after_id"] == 0
        assert body["remaining"] > 0

    def test_a_run_cut_short_advances_the_cursor_over_the_prefix_and_no_further(
        self, client, admin, make_book, google_enabled, catalogues, monkeypatch
    ):
        """Two books resolved, two never reached, and the cursor clears two.

        Waves of two over four books, with slots for one wave. The examined set
        is a prefix by construction rather than by `asyncio.Semaphore` happening
        to be FIFO, which CPython is today and promises nowhere.
        """
        import routers.books as books_router

        monkeypatch.setattr(books_router, "IDENTIFIER_BACKFILL_CONCURRENCY", 2)
        self._deadline(monkeypatch, 0.5)
        self._starved(monkeypatch, at_most=2)
        books = [
            imported_book(client, admin["headers"], make_book) for _ in range(4)
        ]
        volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 2
        assert body["enriched"] == 2
        assert body["next_after_id"] == books[1]["id"]
        assert body["remaining"] == 2

    def test_a_run_cut_short_never_reports_the_library_finished(
        self, client, admin, make_book, google_enabled, catalogues, monkeypatch
    ):
        """0 means "start over", so a cut answering 0 would lose the rest.

        A cut means at least one book of the batch has no outcome, so `examined`
        is at most `total - 1` and `remaining` is at least 1. This is the one
        way this change could lose books.
        """
        import routers.books as books_router

        monkeypatch.setattr(books_router, "IDENTIFIER_BACKFILL_CONCURRENCY", 2)
        self._deadline(monkeypatch, 0.5)
        self._starved(monkeypatch, at_most=2)
        for _ in range(4):
            imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert body["remaining"] > 0
        assert body["next_after_id"] != 0

    def test_the_next_press_resumes_at_the_first_book_the_cut_did_not_reach(
        self, client, admin, make_book, google_enabled, catalogues, monkeypatch
    ):
        """The other half of the cursor rule: nothing is skipped and nothing is
        done twice."""
        import routers.books as books_router

        monkeypatch.setattr(books_router, "IDENTIFIER_BACKFILL_CONCURRENCY", 2)
        self._deadline(monkeypatch, 0.5)
        self._starved(monkeypatch, at_most=2)
        for _ in range(4):
            imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        first = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()
        monkeypatch.setattr(
            books_router,
            "_BACKFILL_LOOKUPS_AT_ONCE",
            asyncio.Semaphore(books_router.IDENTIFIER_BACKFILL_CONCURRENCY),
        )
        second = client.post(
            f"/api/books/identifiers/backfill?after_id={first['next_after_id']}",
            headers=admin["headers"],
        ).json()

        assert second["examined"] == 2
        assert second["enriched"] == 2
        assert second["remaining"] == 0
        assert second["next_after_id"] == 0

    def test_a_wave_carries_a_full_six_lookups_and_not_whatever_six_books_hold(
        self, client, admin, make_book, google_enabled, catalogues, monkeypatch
    ):
        """A wave is filled by lookup, so unresolvable rows do not dilute it.

        Sliced off the batch instead, a wave holding k unresolvable rows ran
        `6 - k` requests and still spent one request's latency, so a half
        unresolvable library examined about half as many books per press inside
        the same deadline. `IdentifierBackfillOut`'s own docstring records a
        library whose rows are all unresolvable as real, because the candidate
        query narrows on carrying a `google_books` identifier and cannot narrow on
        its shape.

        **Two resolvable books with five unresolvable rows between them.** Sliced
        by book at a concurrency of two, no wave can hold more than one lookup;
        filled by lookup, the first wave holds both. The counts and the cursor are
        the same either way, which is why the peak is what this asserts.
        """
        import routers.books as books_router

        monkeypatch.setattr(books_router, "IDENTIFIER_BACKFILL_CONCURRENCY", 2)
        self._deadline(monkeypatch, 0.5)
        slots = _SlotsThatCount(2)
        monkeypatch.setattr(books_router, "_BACKFILL_LOOKUPS_AT_ONCE", slots)

        # The same volume id for both, as `test_resolves_a_library_of_imported_books`
        # does: what is under test is how the walk groups them, not what they are.
        imported_book(client, admin["headers"], make_book)
        for _ in range(5):
            imported_book(client, admin["headers"], make_book, "not-an-id")
        imported_book(client, admin["headers"], make_book)
        volume_route(catalogues)

        body = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        ).json()

        assert slots.peak == 2, (
            "a wave held one lookup where two were available, so the wave is "
            "sliced by book rather than filled by lookup. Read this together with "
            "`TestTheCountingStandInHoldsItsOwnPremise`: green there and red here "
            "is the handler, red in both is the stand-in's own yield"
        )
        assert body["examined"] == 7
        assert body["enriched"] == 2
        assert body["unresolvable"] == 5

    def test_a_library_of_unresolvable_rows_is_answered_rather_than_a_500(
        self, client, admin, make_book, google_enabled, catalogues
    ):
        """The empty case, which is a guard under `asyncio.wait` and free here.

        `asyncio.wait` raises `ValueError` on an empty set;
        `asyncio.gather()` returns `[]`. `metadata._within_deadline`'s docstring
        records this defect shipping once, when a library with every catalogue
        switched off turned a title search into a 500, so it is pinned rather
        than left to the shape of the code.
        """
        imported_book(client, admin["headers"], make_book, "not-an-id")
        volume_route(catalogues)

        res = client.post(
            "/api/books/identifiers/backfill", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert res.json()["unresolvable"] == 1


class TestTheDeadlineIsDerivedRatherThanChosen:
    """Its three derivations, recomputed from their own sources.

    A number written down stops being re-derived and starts being copied, so the
    two derivations that are arithmetic over constants in this tree are asserted
    rather than left in a comment. The third, half the proxy's measured read
    timeout, is not here: that figure is a dependency default nobody in this
    deployment set, this tree deliberately gives it no name, and an arm would be
    the third copy of it.
    """

    def test_a_member_pressing_flat_out_holds_four_of_the_pools_fifteen(self):
        """Little's law over this route's own limiter, on the hold and not on the
        deadline.

        **The hold is the deadline plus one `fetch.TIMEOUT_SECONDS`**, because
        waves are sequential and the check before each one is `left(ends) <= 0`:
        an acquire admitted just under the deadline runs a full request after it,
        and `fetch.get` bounds that whole walk with no retry on the path to it. So
        the figure is four, against the 9 the route held at a 90s life, which is
        the same quantity over that life rather than a different one.

        **Exactly four and not under it**, `0.1 x 40` being 4.0 in this tree's own
        floats: one second more on the deadline is 4.1 and red. That is the point
        of asserting the hold, and it is the same threshold the deadline had when
        this arm measured the wrong quantity, which is why the value 30 survives
        the correction.
        """
        import fetch
        import ratelimit
        import routers.books as books_router

        limit = ratelimit.IDENTIFIER_BACKFILL_LIMIT
        per_second = limit.max_attempts / limit.window_seconds
        hold = (
            books_router.IDENTIFIER_BACKFILL_DEADLINE_SECONDS + fetch.TIMEOUT_SECONDS
        )

        assert per_second * hold <= 4

    def test_a_cut_lands_on_a_wave_boundary_rather_than_mid_wave(self):
        """Whole waves of `fetch.TIMEOUT_SECONDS`, so no wave is thrown away
        half done in the case where every request times out."""
        import fetch
        import routers.books as books_router

        assert (
            books_router.IDENTIFIER_BACKFILL_DEADLINE_SECONDS
            % fetch.TIMEOUT_SECONDS
            == 0
        )


class TestTheCountingStandInHoldsItsOwnPremise:
    """`_SlotsThatCount` driven without the route, so a broken instrument says so.

    **The peak alone cannot tell a broken instrument from a broken handler.**
    Measured 2026-09-26, both ways: removing the yield with the handler untouched,
    and reverting the handler to slicing by book with the yield in place, each give
    a peak of 1 and therefore the identical message, which sends the reader to the
    router either way. That instrument has already been wrong in that direction
    once, which is what makes it the likely recurrence rather than a spare worry.

    This arm is the separation, and what it holds is narrower than that sentence
    wants to be. **It fails when the instrument's overlap is broken**, not whenever
    the instrument is wrong: measured 2026-09-26, setting `peak` to 2 in the
    constructor, an instrument lying about its own observable, is **green here and
    green in the route arm**, while capping the peak is red. So the pair says which
    to read, and neither arm claims the accounting is honest.

    **A flag set after the yield was proposed for this and is refused with a
    measurement.** Deleting the `await asyncio.sleep(0)` leaves the assignment
    below it standing, so the flag reads `True` in all three cases including the
    one it was proposed to catch: instrument intact peak 2 flag True, yield deleted
    peak 1 flag **True**, handler sliced peak 1 flag True. A premise held by a line
    that survives the edit it is watching for is not held.

    **And the obvious cheaper observable does not work either.** Counting acquires
    *entered* rather than slots *held* would need no yield, and reads 1 in every
    case: `asyncio.wait_for` on an uncontended semaphore completes without
    suspending in this tree's Python, so `gather` runs each lookup to completion
    before starting the next. Measured over four shapes. That is why the yield is
    load bearing and why it needs an arm rather than a comment.
    """

    async def test_two_concurrent_acquires_are_seen_as_two_slots_held(self):
        slots = _SlotsThatCount(2)

        async def hold() -> None:
            await slots.acquire()
            try:
                return None
            finally:
                slots.release()

        await asyncio.gather(hold(), hold())

        assert slots.peak == 2, (
            "`_SlotsThatCount` saw one slot held where two acquires really were "
            "concurrent, so its peak is not a fact about the handler and the arm "
            "that reads it is accusing the router for a defect in here. Its yield "
            f"after acquiring is what makes the overlap observable: peak {slots.peak}"
        )


class TestTheSlotsAreDerivedRatherThanChosen:
    """The other constant, which had no arm while the deadline had two.

    `test_concurrency_bounds.py` reads where the bound is built and that it is
    sized from this name. Nothing read the **value**: measured 2026-09-26, six
    raised to six hundred was green in both files, which is a bound that bounds
    nothing.

    **The arm is not a statement about the pod.** It holds this route's slots
    against one search fan out; what the two paths are doing together is a
    question with its own ticket.
    """

    #: The concurrent responses `fetch.MAX_RESPONSE_BYTES` is priced for.
    #:
    #: **A figure this repository states rather than derives**, in
    #: `_BACKFILL_LOOKUPS_AT_ONCE`'s own comment, against the 1.8 GB
    #: `fetch.py` records this pod being OOMKilled at. It is one literal here
    #: because it is one sentence there.
    _PRICED_FOR_AT_ONCE = 16

    def test_the_backfills_slots_leave_room_for_one_search_fan_out(self):
        """One search fan out spends one outbound response per source, and this
        route's own fan out has to fit beside it.

        **One fan out, which is not the pod's occupancy, and this arm claims only
        the first.** The eight is per fan out and the default search path admits
        four per member, `ratelimit.METADATA_LIMIT` over
        `metadata.SEARCH_DEADLINE_SECONDS`, so what is live on that path is a
        larger number this says nothing about. What it holds is that raising this
        route's bound cannot take the room one search needs, which is what stops
        the figure moving unnoticed.

        `len(sources.SEARCH_SOURCES)` rather than the eight the comment names:
        that set is built from `targets.SEEDED` by capability, so adding a
        searchable catalogue moves this arm rather than leaving a literal behind.

        **The bound's own size, not the constant it is expected to be built
        from.** Reading `IDENTIFIER_BACKFILL_CONCURRENCY` left this arm and all
        four structural ones green on
        `asyncio.Semaphore(MAX_IDENTIFIER_BACKFILL)`, which is fifty slots against
        a pod priced for sixteen and one identifier from the right expression:
        this file held the value and the other file held the placement, and
        nothing joined them. `_built_to` closes that by evaluating what the
        module's own source builds the bound to.
        """
        import routers.books as books_router

        name, _ = _the_bound(books_router)
        slots = _built_to(books_router, name)

        assert slots + len(sources.SEARCH_SOURCES) <= self._PRICED_FOR_AT_ONCE, (
            f"{name} is built to {slots} slots, and one search fan out spends "
            f"{len(sources.SEARCH_SOURCES)} of the {self._PRICED_FOR_AT_ONCE} "
            "concurrent responses this pod is priced for"
        )
