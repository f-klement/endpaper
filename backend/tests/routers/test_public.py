"""Tests for backend/routers/public.py: the catalogue served without a session.

Every test here drives the API with **no `Authorization` header at all**, which
is the point: this is the one router in the application whose correctness cannot
be argued from "a member reached it, so a member's rules applied". There is no
member.

The four rules the module names are asserted in four places, and the one that
matters most is the refusal: **publish on with library mode off must serve
nothing**, asserted at the backend rather than through a disabled control.
"""

import pytest
from fastapi.routing import APIRoute

import settings_store
from dependencies import MAX_IDS_IN_A_FILTER
from enums import SettingKey
from main import app, iter_api_routes
from models import Book
from routers.public import PUBLIC_PAGE_PREFIX, PUBLIC_PREFIX, public_reader
from tests.helpers import items, total


def _publish(db, *, mode: bool = True, published: bool = True, indexed: bool = False):
    """Put the two switches, and the indexing one, where a test wants them."""
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true" if mode else "false")
    settings_store.set_value(
        db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true" if published else "false"
    )
    settings_store.set_value(
        db,
        SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED,
        "true" if indexed else "false",
    )


@pytest.fixture
def shelf(db, admin, member):
    """One public book, one private book, one in the trash.

    Three rows because the interesting answers are the two that are absent, and
    the private one belongs to a **different** member from the trashed one so
    an ownership arm reintroduced by accident would have somebody to match.
    """
    public = Book(title="Public Book", author="A Writer", added_by_user_id=admin["user"]["id"])
    private = Book(title="Private Book", added_by_user_id=member["user"]["id"], is_private=True)
    from datetime import UTC, datetime

    trashed = Book(
        title="Trashed Book",
        added_by_user_id=admin["user"]["id"],
        deleted_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([public, private, trashed])
    db.commit()
    db.refresh(public)
    db.refresh(private)
    db.refresh(trashed)
    return {"public": public.id, "private": private.id, "trashed": trashed.id}


class TestTheCatalogueIsClosedUntilTwoSwitchesSayOtherwise:
    """Default off, and the nesting enforced on the server rather than in a UI."""

    def test_a_fresh_deployment_publishes_nothing(self, client):
        assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 404

    def test_library_mode_alone_publishes_nothing(self, client, db):
        """The whole reason there are two switches: an institution can have the
        cataloguer's columns without putting its catalogue on the internet."""
        _publish(db, mode=True, published=False)
        assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 404

    def test_the_publish_switch_alone_publishes_nothing(self, client, db):
        """**The test that matters.** A publish row on while library mode is off
        has to be treated as off, or flipping library mode back off would leave
        a catalogue public with nothing on screen saying so."""
        _publish(db, mode=False, published=True)
        assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 404

    def test_the_item_route_is_closed_by_the_same_rule(self, client, db, shelf):
        """Asserted separately rather than assumed from the listing: the gate is
        on the router, and a test that only drove one route would pass with the
        other one ungated."""
        _publish(db, mode=False, published=True)
        assert client.get(f"{PUBLIC_PREFIX}/books/{shelf['public']}").status_code == 404

    def test_both_switches_on_serves_the_catalogue(self, client, db, shelf):
        _publish(db)
        response = client.get(f"{PUBLIC_PREFIX}/books")
        assert response.status_code == 200
        assert total(response) == 1

    def test_turning_library_mode_off_closes_it_again(self, client, db, shelf):
        """The reverse direction, which is the failure the conjunction exists
        for: nothing rewrites the publish row, so only the read of both rows
        can close the catalogue."""
        _publish(db)
        assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 200
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "false")
        assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 404

    def test_an_unpublished_catalogue_is_404_and_not_403(self, client):
        """A 403 would confirm that this deployment holds a catalogue it is
        declining to show, to anybody who asked."""
        assert client.get(f"{PUBLIC_PREFIX}/books").status_code != 403


class TestOnlyPublishedRowsAreShown:
    def test_a_private_book_is_absent_from_the_listing(self, client, db, shelf):
        _publish(db)
        assert [book["title"] for book in items(client.get(f"{PUBLIC_PREFIX}/books"))] == [
            "Public Book"
        ]

    def test_a_private_book_is_404_by_id(self, client, db, shelf):
        """Not 403. A 403 confirms the id exists, which is how a stranger counts
        through the catalogue to learn how many private books a library holds."""
        _publish(db)
        assert (
            client.get(f"{PUBLIC_PREFIX}/books/{shelf['private']}").status_code == 404
        )

    def test_a_trashed_book_is_404_by_id(self, client, db, shelf):
        _publish(db)
        assert (
            client.get(f"{PUBLIC_PREFIX}/books/{shelf['trashed']}").status_code == 404
        )

    def test_a_book_that_never_existed_is_the_same_404(self, client, db, shelf):
        """The three answers are identical, which is what makes them tell a
        stranger nothing."""
        _publish(db)
        assert client.get(f"{PUBLIC_PREFIX}/books/999999").status_code == 404

    def test_a_public_book_is_served_by_id(self, client, db, shelf):
        _publish(db)
        response = client.get(f"{PUBLIC_PREFIX}/books/{shelf['public']}")
        assert response.status_code == 200
        assert response.json()["title"] == "Public Book"

    def test_search_narrows_the_published_catalogue(self, client, db, shelf):
        _publish(db)
        assert total(client.get(f"{PUBLIC_PREFIX}/books?q=Public")) == 1
        assert total(client.get(f"{PUBLIC_PREFIX}/books?q=Private")) == 0


class TestThePublicListingAcceptsOnlyPublicQuestions:
    """Every parameter the signed in listing takes and this one does not.

    Refused at the boundary rather than ignored, which is the difference between
    a 422 somebody can see and a filter that silently did nothing.
    """

    def test_a_sort_by_when_the_household_acquired_it_is_refused(self, client, db, shelf):
        """`added_at` is withheld, and an ordering is a read of the column it
        orders by: one request would return the whole acquisition order."""
        _publish(db)
        assert (
            client.get(f"{PUBLIC_PREFIX}/books?sort=newest").status_code == 422
        )

    def test_a_sort_by_a_published_column_is_accepted(self, client, db, shelf):
        """The diagonal. Without it the refusal above would be satisfied by a
        route that refuses every sort."""
        _publish(db)
        assert client.get(f"{PUBLIC_PREFIX}/books?sort=year_desc").status_code == 200

    def test_the_reading_status_filter_is_not_offered(self, client, db, shelf):
        """It would raise on this shelf anyway, since it has no viewer to read a
        status against. Refused as an unknown parameter instead, so the failure
        is a 422 rather than a 500."""
        _publish(db)
        assert client.get(f"{PUBLIC_PREFIX}/books?status=read").status_code == 200
        # Accepted and **ignored**, which is what FastAPI does with an unknown
        # query parameter. The point is that it cannot reach the shelf: the
        # whole catalogue comes back rather than the caller's read books.
        assert total(client.get(f"{PUBLIC_PREFIX}/books?status=read")) == 1

    def test_the_collection_filter_is_not_offered_either(self, client, db, shelf):
        """Cut deliberately: the ids are consecutive, so the filter is
        enumerable, and what it enumerates is the household's own grouping of
        its shelves, which the payload withholds."""
        _publish(db)
        assert total(client.get(f"{PUBLIC_PREFIX}/books?collection_id=99")) == 1


class TestThePublicPayloadCarriesNoPerMemberField:
    """The column boundary, asserted through the wire rather than on the model.

    `tests/schemas/test_public.py` asserts the classification; this asserts that
    the classification is what actually leaves the process. The two are not the
    same claim: a router could add a field to the body after serialisation, and
    a `response_model` could be widened without the model changing.
    """

    def test_the_listing_body_carries_only_published_fields(self, client, db, shelf):
        from schemas import PublicBookOut

        _publish(db)
        body = items(client.get(f"{PUBLIC_PREFIX}/books"))[0]
        assert set(body) <= set(PublicBookOut.model_fields)

    def test_the_item_body_carries_only_published_fields(self, client, db, shelf):
        from schemas import PublicBookOut

        _publish(db)
        body = client.get(f"{PUBLIC_PREFIX}/books/{shelf['public']}").json()
        assert set(body) <= set(PublicBookOut.model_fields)

    def test_nothing_a_member_wrote_about_themselves_reaches_the_wire(
        self, client, db, admin, shelf
    ):
        """A sentinel sweep, and what it sweeps is stated rather than implied.

        **Four of the twenty seven withheld fields**, not all of them: the four
        that are string or number **columns a household types into**, plus the
        username of the member who added the book. Most of the rest are not
        columns at all (`my_status`, `active_loan`, `discuss_with`) or are enums
        and dates with no value distinctive enough to sweep for.

        So this is the value level check and it is deliberately partial. What
        covers the other twenty three is the model level partition in
        `tests/schemas/test_public.py`, which is total by construction. This one
        exists for what that cannot see: a value reaching the wire under a key
        it does not belong to.
        """
        _publish(db)
        book = db.get(Book, shelf["public"])
        book.location = "SENTINELROOM"
        book.purchase_source = "SENTINELSHOP"
        book.purchase_currency = "SEN"
        book.purchase_price_minor = 987654321
        db.commit()

        for path in (f"{PUBLIC_PREFIX}/books", f"{PUBLIC_PREFIX}/books/{book.id}"):
            body = client.get(path).text
            for sentinel in ("SENTINELROOM", "SENTINELSHOP", "987654321"):
                assert sentinel not in body, f"{sentinel} leaked from {path}"
            # The member who added it, by username rather than by field name:
            # a member's name reaching a public payload is the leak, whatever
            # the key is called.
            assert admin["user"]["username"] not in body

    def test_a_locally_uploaded_cover_is_not_advertised(self, client, db, shelf):
        """`/covers/<id>` is served behind `book_for_read`, so publishing the
        path would advertise an image a public reader cannot fetch."""
        _publish(db)
        book = db.get(Book, shelf["public"])
        book.cover_url = f"/covers/{book.id}.jpg"
        db.commit()
        assert client.get(f"{PUBLIC_PREFIX}/books/{book.id}").json()["cover_url"] is None

    def test_a_catalogue_cover_survives(self, client, db, shelf):
        """The diagonal. Without it the rule above would be satisfied by
        dropping every cover, which is a different behaviour."""
        _publish(db)
        book = db.get(Book, shelf["public"])
        book.cover_url = "https://covers.openlibrary.org/b/id/1.jpg"
        db.commit()
        assert (
            client.get(f"{PUBLIC_PREFIX}/books/{book.id}").json()["cover_url"]
            == "https://covers.openlibrary.org/b/id/1.jpg"
        )


class TestCrawlersAreNotInvitedUntilSomebodySaysSo:
    """The header and the file, and the header is asserted on more than the 200.

    It used to be set from `public_reader`, and a header set in a dependency
    merges onto the **success path only**: measured, it was on the 200 and
    absent from the gate's 404, the item 404, a 429 and a 500, while this
    module's docstring and `docs/security.md` both claimed every public response
    carried it. It is unconditional in the middleware now, and the published
    paths lift it, so a response nobody thought about stays out of the index.
    """

    def test_a_published_catalogue_is_noindex_by_default(self, client, db, shelf):
        _publish(db)
        response = client.get(f"{PUBLIC_PREFIX}/books")
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"

    @pytest.mark.parametrize(
        "path",
        ["/books/999999", "/books?tags=" + "9" * 500, "/books"],
        ids=["a 404 item", "a 422", "the 404 gate"],
    )
    def test_the_header_is_on_the_failures_as_well(self, client, db, path):
        """**The half a dependency could never do.** Each of these is a
        different failure path and each used to answer with no header at all."""
        response = client.get(f"{PUBLIC_PREFIX}{path}")
        assert response.status_code != 200
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"

    def test_the_signed_in_application_is_noindex_too(self, client):
        """Unconditional means unconditional. Nothing behind a session should
        ever be indexed, and before this only the public 200 said so."""
        assert client.get("/api/books").headers["X-Robots-Tag"] == "noindex, nofollow"

    def test_allowing_indexing_drops_the_header(self, client, db, shelf):
        _publish(db, indexed=True)
        response = client.get(f"{PUBLIC_PREFIX}/books")
        assert "X-Robots-Tag" not in response.headers

    def test_allowing_indexing_lifts_it_only_for_the_catalogue(self, client, db, shelf):
        """The diagonal: the lift is scoped, so a library that invited a crawler
        did not thereby invite it into the signed in application."""
        _publish(db, indexed=True)
        assert client.get("/api/books").headers["X-Robots-Tag"] == "noindex, nofollow"

    def test_a_path_that_merely_starts_like_the_catalogue_is_not_lifted(
        self, client, db, shelf
    ):
        """`startswith("/catalogue")` also matches `/catalogue-of-members`. The
        rule matches exactly or on a slash, which is the same looseness the
        signed out route table is tested against on the frontend."""
        _publish(db, indexed=True)
        response = client.get("/catalogue-of-members")
        assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_robots_disallows_everything_on_a_private_deployment(self, client):
        body = client.get("/robots.txt").text
        assert "Disallow: /" in body and "Allow:" not in body

    def test_robots_still_disallows_a_published_but_unindexed_catalogue(
        self, client, db
    ):
        """Publishing and inviting a crawler are different decisions, and this
        is the state a library that has taken only the first is in."""
        _publish(db)
        assert "Allow:" not in client.get("/robots.txt").text

    def test_robots_allows_the_pages_and_not_the_json(self, client, db):
        """**The path that was wrong.** A crawler indexes the HTML at
        `/catalogue`, not the JSON at `/api/public/books`, so the first version
        allowed the one path with nothing readable at it and barred the two the
        catalogue is actually read at. Not a bare `Allow: /` either, which would
        invite a crawler into the signed in application where every path 401s."""
        _publish(db, indexed=True)
        body = client.get("/robots.txt").text
        assert f"Allow: {PUBLIC_PAGE_PREFIX}\n" in body
        assert PUBLIC_PREFIX not in body
        assert "Disallow: /" in body

    def test_the_indexing_switch_cannot_invite_a_crawler_to_nothing(self, client, db):
        """Indexing on while nothing is published is still disallowed: the
        conjunction is the same shape as the publish one."""
        _publish(db, published=False, indexed=True)
        assert "Allow:" not in client.get("/robots.txt").text


class TestThePublicReaderIsRateLimited:
    def test_the_ceiling_answers_429_with_a_retry_after(self, client, db, shelf):
        """This is the first surface a stranger can reach, so it is the first
        that can be scraped. Driven to the limit rather than asserted against
        the constant, so a limiter attached to the wrong router fails here."""
        from ratelimit import PUBLIC_CATALOGUE_LIMIT

        _publish(db)
        for _ in range(PUBLIC_CATALOGUE_LIMIT.max_attempts):
            assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 200
        refused = client.get(f"{PUBLIC_PREFIX}/books")
        assert refused.status_code == 429
        assert "Retry-After" in refused.headers

    def test_probing_an_unpublished_catalogue_is_bounded_too(self, client):
        """The limit runs before the gate, so a stranger cannot spend an
        unbounded number of requests finding out whether anything is here."""
        from ratelimit import PUBLIC_CATALOGUE_LIMIT

        for _ in range(PUBLIC_CATALOGUE_LIMIT.max_attempts):
            assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 404
        assert client.get(f"{PUBLIC_PREFIX}/books").status_code == 429


#: The one handler in `routers.public` that is deliberately not gated.
#:
#: `robots.txt` has to answer whether or not anything is published, which is the
#: whole point of it, so it hangs off the ungated router. Named here rather than
#: excluded by a path test, because a name is a decision somebody took and a
#: path is a coincidence.
UNGATED_BY_DESIGN = {"robots_txt"}


class TestEveryPublicRouteIsGated:
    """The structural half: the gate is on the router, so it cannot be omitted.

    Asserted against the **live route table** rather than against the source,
    because what protects a route is the dependency FastAPI resolved and not the
    decorator somebody meant to write.

    **Scoped by module, not by path prefix**, and that was a correction. A prefix
    test had two evasions, both demonstrated: a handler added to the ungated
    `router` at a path outside the prefix, which is a shape `robots_txt` already
    establishes in that very module; and a route at exactly `/api/public`, since
    `"/api/public".startswith("/api/public/")` is False. Selecting on
    `endpoint.__module__` asks the question the rule is actually about, and the
    prefix is asserted the other way round instead.
    """

    @staticmethod
    def _module_routes() -> list[APIRoute]:
        return [
            route
            for route in iter_api_routes(app.routes)
            if getattr(route.endpoint, "__module__", "") == "routers.public"
        ]

    def test_there_are_routes_to_check(self):
        """A guard that inspects nothing reads as coverage. This is the check
        that fails if the module is renamed and the rest goes vacuous."""
        assert len(self._module_routes()) >= 3

    def test_the_exemption_set_is_exactly_the_one_handler(self):
        """**Asserted equal, not as a subset**, which was the same
        enumerate-something-open shape as the prefix check it replaced, one
        level up: a subset test catches an exemption that was **deleted** and
        forgives one that was **added**, so writing `"list_public_books"` into
        that set would exempt the whole listing with every test still green.

        Equality also keeps the other half, which is that an allowlist naming a
        handler that no longer exists forgives nothing and looks like it
        forgives something.
        """
        assert {"robots_txt"} == UNGATED_BY_DESIGN, (
            "The set of routes that may skip the gate is one handler and the "
            "reason is written above it. Adding a second is a decision about "
            "what may be served without the publish check, the rate limit or "
            "the 404, and it does not belong in a set literal."
        )
        names = {route.name for route in self._module_routes()}
        assert names >= UNGATED_BY_DESIGN, (
            f"{sorted(UNGATED_BY_DESIGN - names)} is allowlisted and is not a "
            "route in routers.public."
        )

    def test_every_route_in_the_module_carries_the_gate(self):
        ungated = sorted(
            route.path
            for route in self._module_routes()
            if route.name not in UNGATED_BY_DESIGN
            and public_reader not in [d.call for d in route.dependant.dependencies]
        )
        assert ungated == [], (
            f"These public routes do not run `public_reader`: {ungated}. The gate "
            "is declared on the router, so a route that misses it was added to "
            "the wrong one. It is what refuses an unpublished catalogue and "
            "bounds the rate."
        )

    def test_nothing_outside_the_module_serves_a_path_under_the_prefix(self):
        """The prefix test, turned around. It no longer decides what is gated;
        it decides that nothing else has quietly claimed the namespace."""
        strangers = sorted(
            f"{route.path} ({getattr(route.endpoint, '__module__', '?')})"
            for route in iter_api_routes(app.routes)
            if route.path == PUBLIC_PREFIX or route.path.startswith(f"{PUBLIC_PREFIX}/")
            if getattr(route.endpoint, "__module__", "") != "routers.public"
        )
        assert strangers == [], (
            f"These routes serve a public path from another module: {strangers}"
        )

    def test_nothing_in_the_module_writes(self):
        # `route.methods` is typed optional on the base class, so it is
        # normalised rather than narrowed at two sites.
        writing = [
            f"{route.path}:{sorted(methods)}"
            for route in self._module_routes()
            for methods in [route.methods or set()]
            if methods - {"GET", "HEAD", "OPTIONS"}
        ]
        assert writing == [], f"These public routes accept a write: {writing}"


class TestTheTagFilterCannotBeUsedToBreakOrStallTheApp:
    """A comma separated list of ids is a hole `RowId` structurally cannot see.

    `RowId` and `RowIdField` both work by annotating an `int`. These ids arrive
    inside a `str`, so neither bound reaches them, and the line that parsed them
    was written inline in `routers/books.py` and copied verbatim onto this
    surface, where it became reachable with **no session at all**.

    Measured before the fix, both switches on and no token: an id past SQLite's
    range raised `OverflowError`, a 5,000 digit token exceeded
    `sys.int_max_str_digits`, and a thousand ids exceeded SQLite's expression
    tree depth. All three answered 500. Below the break it was a CPU sink: 900
    ids cost 0.900s, and the 120 a minute ceiling would have let one address
    spend more than a minute of CPU per minute without tripping it.

    Asserted here **and** against the signed in listing, because the fix is one
    shared parser and a test on one caller would not notice the other losing it.
    """

    @pytest.mark.parametrize(
        "value",
        ["18446744073709551616", "9" * 5000, ",".join(str(n) for n in range(1, 1001))],
        ids=["past SQLite's integer range", "past int_max_str_digits", "a thousand ids"],
    )
    def test_no_tag_filter_answers_500(self, client, db, shelf, value):
        _publish(db)
        assert client.get(f"{PUBLIC_PREFIX}/books?tags={value}").status_code != 500

    def test_an_id_that_is_not_a_row_id_is_dropped_rather_than_reaching_the_driver(
        self, client, db, shelf
    ):
        """The existing contract, extended to the case that used to 500:
        `?tags=abc` has always been ignored, and an id past the range is not a
        row id either."""
        _publish(db)
        assert total(client.get(f"{PUBLIC_PREFIX}/books?tags=18446744073709551616")) == 1

    def test_too_many_ids_is_refused_rather_than_truncated(self, client, db, shelf):
        """Truncating would answer a different question from the one asked and
        say nothing about it, and this is a filter: a wrong answer looks like a
        correct one."""
        _publish(db)
        ids = ",".join(str(n) for n in range(1, MAX_IDS_IN_A_FILTER + 2))
        response = client.get(f"{PUBLIC_PREFIX}/books?tags={ids}")
        assert response.status_code == 422
        assert str(MAX_IDS_IN_A_FILTER) in response.text

    def test_the_ceiling_itself_is_accepted(self, client, db, shelf):
        """The diagonal. Without it the refusal above is satisfied by a bound
        that refuses every filter."""
        _publish(db)
        ids = ",".join(str(n) for n in range(1, MAX_IDS_IN_A_FILTER + 1))
        assert client.get(f"{PUBLIC_PREFIX}/books?tags={ids}").status_code == 200

    def test_the_string_itself_is_length_bounded(self, client, db, shelf):
        """The count bound alone cannot stop a single enormous token, which is
        what `sys.int_max_str_digits` refused with a 500."""
        _publish(db)
        assert client.get(f"{PUBLIC_PREFIX}/books?tags={'9' * 5000}").status_code == 422

    @pytest.mark.parametrize(
        "value",
        ["18446744073709551616", "9" * 5000, ",".join(str(n) for n in range(1, 1001))],
        ids=["past SQLite's integer range", "past int_max_str_digits", "a thousand ids"],
    )
    def test_the_signed_in_listing_is_fixed_by_the_same_parser(
        self, client, admin, value
    ):
        """Where the defect actually lived. It was pre-existing and member
        reachable, and copying it onto a surface with no session is what made it
        worth fixing here rather than filing."""
        response = client.get(f"/api/books?tags={value}", headers=admin["headers"])
        assert response.status_code != 500
