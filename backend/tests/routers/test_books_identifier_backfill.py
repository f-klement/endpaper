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

import httpx
import pytest
import respx

import sources
from tests.helpers import GOOGLE_BOOKS, silence_catalogues

VOLUME_ID = "s7NIrgEACAAJ"
OTHER_VOLUME_ID = "abcdefghijkl"


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

        assert (two, four) == (13, 13), (
            f"a batch of two costs {two} SELECTs and the next two cost {four}. "
            "Both are the same batch size, so the two figures must agree; they "
            "are taken twice because the second runs against a larger library, "
            "and a cost that grew with the library rather than with the batch "
            "would show up here and nowhere else. Eleven of the thirteen are "
            "fixed and are **not itemised**: what this pins is that the figure "
            "does not move, and `test_the_slope_is_one_statement_a_book` below "
            "is what says which part of it is per book."
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
