"""Tests for backend/routers/sru.py: the gate in front of the protocol.

`tests/test_sru.py` drives `sru.respond` and owns everything the protocol does.
What is left here is the four things a route decides and a function over a query
string cannot: whether the endpoint exists at all, how fast a stranger may ask,
what the response is labelled as, and whether a crawler is invited.

Every test drives the API with **no `Authorization` header**, which is the point
of the module under test.
"""

import pytest
from fastapi.routing import APIRoute

import settings_store
from enums import SettingKey
from main import app, iter_api_routes
from models import Book
from ratelimit import PUBLIC_CATALOGUE_LIMIT
from routers.public import public_reader
from routers.sru import SRU_PREFIX, server_for


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
def book(db, admin):
    row = Book(title="Chartreuse Windmill", added_by_user_id=admin["user"]["id"])
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


class TestTheEndpointDoesNotExistUntilTheCatalogueIsPublished:
    """The ticket asks for one switch and this is gated on two.

    `public_catalogue_is_published` is library mode **and** the publish row, so
    the endpoint disappears when either is off. That is stricter than the ticket
    and is the only arrangement where the SRU surface and the JSON one cannot
    give different answers to "is anything published".
    """

    def test_a_fresh_deployment_serves_no_sru(self, client):
        assert client.get(SRU_PREFIX).status_code == 404

    def test_library_mode_alone_serves_no_sru(self, client, db):
        _publish(db, mode=True, published=False)
        assert client.get(SRU_PREFIX).status_code == 404

    def test_the_publish_switch_alone_serves_no_sru(self, client, db):
        _publish(db, mode=False, published=True)
        assert client.get(SRU_PREFIX).status_code == 404

    def test_turning_library_mode_off_closes_it_again(self, client, db):
        """The direction the conjunction exists for: nothing rewrites the
        publish row, so only a read of both rows can close the endpoint."""
        _publish(db)
        assert client.get(SRU_PREFIX).status_code == 200
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "false")
        assert client.get(SRU_PREFIX).status_code == 404

    def test_a_closed_endpoint_is_404_and_not_403(self, client):
        """A 403 would confirm that this deployment holds a catalogue it is
        declining to serve, to anybody who asked."""
        assert client.get(SRU_PREFIX).status_code != 403

    def test_a_search_is_closed_by_the_same_rule(self, client, db, book):
        """Asserted with parameters as well as without, because the gate is a
        router dependency and a test that only drove the bare path would pass
        with the search arm ungated."""
        _publish(db, mode=False, published=True)
        response = client.get(
            SRU_PREFIX, params={"operation": "searchRetrieve", "query": "Windmill"}
        )
        assert response.status_code == 404


class TestEverySruRouteIsGated:
    """The structural half, asserted against the **live route table**.

    What protects a route is the dependency FastAPI resolved, not the decorator
    somebody meant to write. Scoped by module rather than by path for the reason
    `tests/routers/test_public.py` records: a prefix test is evaded by a handler
    added at a path outside the prefix.
    """

    @staticmethod
    def _module_routes() -> list[APIRoute]:
        return [
            route
            for route in iter_api_routes(app.routes)
            if getattr(route.endpoint, "__module__", "") == "routers.sru"
        ]

    def test_there_are_routes_to_check(self):
        """A guard that inspects nothing reads as coverage."""
        assert len(self._module_routes()) >= 1

    def test_every_route_in_the_module_carries_the_gate(self):
        ungated = sorted(
            route.path
            for route in self._module_routes()
            if public_reader not in [d.call for d in route.dependant.dependencies]
        )
        assert ungated == [], (
            f"These SRU routes do not run `public_reader`: {ungated}. The gate "
            "is declared on the router and there is no exemption: it is what "
            "refuses an unpublished catalogue and what bounds the rate."
        )

    def test_nothing_in_the_module_writes(self):
        writing = [
            f"{route.path}:{sorted(route.methods or set())}"
            for route in self._module_routes()
            if (route.methods or set()) - {"GET", "HEAD"}
        ]
        assert writing == [], (
            f"These SRU routes accept a write: {writing}. A caller here has no "
            "account to attribute one to."
        )

    def test_the_route_is_not_in_the_openapi_schema(self):
        """`robots.txt` is the precedent: a document another institution's
        software fetches is not an operation this application's client calls,
        and a generated typed hook for it would be noise nothing imports."""
        assert all(not route.include_in_schema for route in self._module_routes())


class TestTheSharedGateGivesTheSharedLimit:
    def test_the_rate_limit_is_the_published_catalogue_own(self, client, db):
        """One published catalogue, one budget. A harvester and a browser
        reading the same records should not have two.

        The number is read from `PUBLIC_CATALOGUE_LIMIT` rather than written
        here, so raising the catalogue's limit does not leave this test pinning
        a number nothing else uses.
        """
        _publish(db)
        for _ in range(PUBLIC_CATALOGUE_LIMIT.max_attempts):
            assert client.get(SRU_PREFIX).status_code == 200
        refused = client.get(SRU_PREFIX)
        assert refused.status_code == 429
        assert "Retry-After" in refused.headers

    def test_the_limit_is_spent_by_the_json_catalogue_too(self, client, db):
        """The half that says it is one counter rather than two of the same
        size: requests to the JSON catalogue leave fewer for SRU."""
        _publish(db)
        for _ in range(PUBLIC_CATALOGUE_LIMIT.max_attempts):
            client.get("/api/public/books")
        assert client.get(SRU_PREFIX).status_code == 429

    def test_the_gate_is_rate_limited_before_it_is_answered(self, client):
        """Nothing is published, so every one of these is a 404 until the
        counter runs out. Probing whether a deployment has a catalogue is
        bounded the same way reading one is."""
        for _ in range(PUBLIC_CATALOGUE_LIMIT.max_attempts):
            assert client.get(SRU_PREFIX).status_code == 404
        assert client.get(SRU_PREFIX).status_code == 429


class TestWhatTheResponseIsLabelledAs:
    def test_the_media_type_is_xml(self, client, db):
        _publish(db)
        response = client.get(SRU_PREFIX)
        assert response.headers["content-type"].startswith("application/xml")

    def test_a_crawler_is_not_invited_even_when_the_catalogue_is_indexable(
        self, client, db
    ):
        """**Not in `middleware._INDEXABLE_PATHS`, deliberately.**

        Indexing is about the catalogue pages a person lands on. An SRU base URL
        is a machine interface: a search engine holding it has a URL nobody can
        read and this deployment gains nothing.
        """
        _publish(db, indexed=True)
        assert "noindex" in client.get(SRU_PREFIX).headers["X-Robots-Tag"]

    def test_robots_txt_does_not_allow_the_sru_path(self, client, db):
        """`robots.txt` allows the catalogue pages and disallows everything
        else, so this needs no entry of its own. Asserted rather than assumed,
        because "everything else" is a claim about a file that is generated."""
        _publish(db, indexed=True)
        assert SRU_PREFIX not in client.get("/robots.txt").text


class TestTheServiceAnswersARealRequest:
    def test_explain_is_what_a_bare_base_url_returns(self, client, db):
        _publish(db)
        body = client.get(SRU_PREFIX).text
        assert "explainResponse" in body
        # The qualified name is never a literal in the document: the context set
        # is an attribute and the index name is the element's text. Asserting
        # `"dc.title" in body` passed nothing and would have gone on passing
        # with `indexInfo` deleted.
        assert '<name set="dc">title</name>' in body

    def test_a_search_returns_marcxml(self, client, db, book):
        _publish(db)
        body = client.get(
            SRU_PREFIX, params={"operation": "searchRetrieve", "query": "Windmill"}
        ).text
        assert "http://www.loc.gov/MARC21/slim" in body
        assert "Chartreuse Windmill" in body

    @pytest.mark.parametrize(
        "params",
        [
            {"query": f"rec.id={2**63}"},
            {"query": f"dc.date>{2**63}"},
            {"query": "Windmill", "startRecord": str(2**63)},
        ],
        ids=["rec.id", "dc.date", "startRecord"],
    )
    def test_an_integer_the_database_cannot_hold_is_not_a_500(
        self, client, db, book, params
    ):
        """**The instrument that found this, kept.**

        Both review seats found it by driving the real app with no credentials,
        and neither the unit tests nor a reading of `respond` could have: the
        `OverflowError` is raised by the SQLite driver, well below this module,
        and `respond` catches only `SruError`. A test at the transport is the
        only one that sees the status code the client actually got.
        """
        _publish(db)
        response = client.get(SRU_PREFIX, params=params)
        assert response.status_code == 200, response.text
        assert "info:srw/diagnostic/1/" in response.text

    def test_a_hostile_query_is_a_200_with_a_diagnostic(self, client, db):
        """**The protocol's own rule, asserted at the transport.** An SRU client
        reads the body; a status code it did not expect is indistinguishable
        from a proxy having eaten the request."""
        _publish(db)
        response = client.get(
            SRU_PREFIX,
            params={"operation": "searchRetrieve", "query": "(" * 500},
        )
        assert response.status_code == 200
        assert "info:srw/diagnostic/1/13" in response.text


class TestWhatExplainSaysAboutWhereItIs:
    """`serverInfo` is built from the `Host` header, and from nothing else.

    The scope in `_request` names a server of `ignored.example`, which is what
    Starlette falls back to when it will not use the header. **Every assertion
    of `localhost` below is therefore also an assertion that the fallback was
    not taken**, and that matters: `scope["server"]` is the address this process
    is bound to, which behind a proxy is a deployment's internal listen address
    and not a thing a public document should carry.
    """

    @staticmethod
    def _request(host: str):
        from starlette.datastructures import Headers
        from starlette.requests import Request

        scope = {
            "type": "http",
            "scheme": "https",
            "server": ("ignored.example", 443),
            "path": SRU_PREFIX,
            "query_string": b"",
            "headers": Headers({"host": host}).raw,
        }
        return Request(scope)

    def test_an_ordinary_host_is_echoed(self):
        assert server_for(self._request("catalogue.example")).host == (
            "catalogue.example"
        )

    def test_a_port_in_the_host_header_is_reported(self):
        assert server_for(self._request("catalogue.example:8443")).port == 8443

    def test_a_missing_port_takes_the_scheme_default(self):
        assert server_for(self._request("catalogue.example")).port == 443

    @pytest.mark.parametrize(
        "host",
        [
            "catalogue.example<script>",
            "catalogue.example ",
            "a" * 300,
            "",
        ],
        ids=["markup", "space", "long", "empty"],
    )
    def test_anything_that_is_not_a_hostname_falls_back(self, host):
        assert server_for(self._request(host)).host == "localhost"

    def test_a_port_that_is_not_a_number_is_refused_with_its_host(self):
        """The whole header is one value: a port that is not one makes the
        name beside it untrusted too."""
        server = server_for(self._request("catalogue.example:notaport"))
        assert server.host == "localhost"
        assert server.port == 443

    def test_a_five_digit_number_that_is_not_a_port_takes_the_default(self):
        """**The case the digit bound alone does not cover.** `65536` matches
        `[0-9]{1,5}` and is not a port, so the pattern bounds what `int()` is
        handed and the range check is what decides."""
        assert server_for(self._request("catalogue.example:99999")).port == 443
        assert server_for(self._request("catalogue.example:99999")).host == (
            "catalogue.example"
        )

    def test_an_ipv6_literal_falls_back_rather_than_being_echoed(self):
        """Starlette accepts the bracketed form and this does not. Stated as a
        test rather than as a comment, because it is a behaviour a client on
        such a deployment will meet."""
        assert server_for(self._request("[::1]:443")).host == "localhost"

    def test_the_fallback_is_not_reached_by_the_ordinary_case(self):
        """Without this the whole class passes with the regex replaced by
        `False`, which would answer `localhost` to every real client."""
        assert server_for(self._request("catalogue.example")).host != "localhost"


class TestTheFallbackThisAvoids:
    """Starlette's own behaviour, pinned because a comment rests on it.

    `_HOST_HEADER` reads the header directly, and the stated reason is that
    `request.url` would answer with `scope["server"]` for a header Starlette will
    not use. That is a third party's behaviour and this repository has been
    caught before by a comment whose reason had quietly stopped being true, so
    the premise is asserted rather than described: an upgrade that changes it
    fails here and sends somebody back to that paragraph.

    It is deliberately **not** an assertion about `_HOST_RE` or any other private
    name. It asks the library what it does, not what it is made of.
    """

    def test_starlette_falls_back_to_the_bound_address_on_a_bad_host(self):
        request = TestWhatExplainSaysAboutWhereItIs._request(
            "catalogue.example<script>"
        )
        assert request.url.hostname == "ignored.example", (
            "Starlette no longer falls back to scope['server'] for a header it "
            "will not use. The reason `routers/sru.py` gives for reading the "
            "header directly needs re-reading; the code itself is unaffected."
        )

    def test_and_this_server_answers_localhost_for_the_same_request(self):
        """The pair. The first says the trap is real, this says we are out of
        it, and neither is evidence on its own."""
        request = TestWhatExplainSaysAboutWhereItIs._request(
            "catalogue.example<script>"
        )
        assert server_for(request).host == "localhost"
