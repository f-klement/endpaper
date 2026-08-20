"""Tests for backend/errors.py: content-negotiated error responses.

One app serves both a browser and a JSON API, so an error has two correct
forms. These check that each audience gets its own, and in particular that a
crash never returns a traceback to the caller.
"""

import pytest

from errors import is_api_path, render_error_page

HTML = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
JSON = {"Accept": "application/json"}


class TestIsApiPath:
    @pytest.mark.parametrize(
        "path", ["/api/books", "/api/books/1/notes", "/auth/login", "/openapi.json", "/docs"]
    )
    def test_api_paths(self, path):
        assert is_api_path(path) is True

    @pytest.mark.parametrize("path", ["/", "/book/12", "/scan", "/nonsense"])
    def test_spa_paths(self, path):
        assert is_api_path(path) is False


class TestWantsHtml:
    def test_a_browser_navigating_to_a_page(self, client):
        res = client.get("/definitely-not-a-route", headers=HTML)
        assert "text/html" in res.headers["content-type"]

    def test_a_browser_calling_the_api_still_gets_json(self, client):
        """Anything hitting /api is code, whatever its Accept header says."""
        res = client.get("/api/books/999999", headers=HTML)
        assert "application/json" in res.headers["content-type"]

    def test_a_fetch_call_gets_json(self, client):
        res = client.get("/api/books/999999", headers=JSON)
        assert "application/json" in res.headers["content-type"]


class TestErrorPage:
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 413, 422, 429, 500])
    def test_renders_every_handled_status(self, status_code):
        response = render_error_page(status_code)
        assert response.status_code == status_code
        assert b"Endpaper" in response.body

    def test_falls_back_for_an_unlisted_status(self):
        response = render_error_page(418)
        assert response.status_code == 418
        assert b"Something went wrong" in response.body

    def test_is_self_contained(self):
        """A failure in the asset pipeline is one of the things this page has
        to be able to report, so it must not depend on that pipeline."""
        body = bytes(render_error_page(404).body).decode()
        assert "<link" not in body
        assert "<script" not in body

    def test_offers_a_way_back(self):
        assert 'href="/"' in bytes(render_error_page(404).body).decode()

    def test_does_not_interpolate_untrusted_text(self):
        """Wording comes from a fixed table, never from the exception, so an
        internal message cannot be reflected into the page."""
        body = bytes(render_error_page(500).body).decode()
        assert "Traceback" not in body


class TestApiErrorsStayJson:
    def test_unknown_api_path_is_a_json_404(self, client):
        """Regression: unknown /api paths used to fall through to the SPA mount
        and return index.html with a 200, so a typo in a fetch() call looked
        like a successful request returning HTML."""
        res = client.get("/api/nonexistent", headers=HTML)
        assert res.status_code == 404
        assert "application/json" in res.headers["content-type"]

    def test_unknown_auth_path_is_a_json_404(self, client):
        res = client.get("/auth/nonexistent", headers=HTML)
        assert res.status_code == 404
        assert "application/json" in res.headers["content-type"]

    def test_the_detail_field_is_present(self, client):
        assert "detail" in client.get("/api/books/999999", headers=JSON).json()

    def test_validation_errors_keep_their_per_field_array(self, client, admin):
        """The client flattens this into one message, so the shape matters."""
        res = client.post("/api/books", json={"author": "No Title"}, headers=admin["headers"])
        assert res.status_code == 422
        assert isinstance(res.json()["detail"], list)

    def test_a_401_keeps_its_www_authenticate_header(self, client):
        res = client.get("/auth/me")
        assert res.status_code == 401
        assert "www-authenticate" in res.headers


class TestUnhandledExceptions:
    @pytest.fixture
    def exploding_route(self):
        """Add a route that raises, then remove it again.

        Registered directly on the app rather than mocked, so this exercises
        the real handler chain.
        """
        import main

        @main.app.get("/boom-test", include_in_schema=False)
        def boom() -> None:
            raise RuntimeError("a secret internal detail")

        yield
        main.app.routes[:] = [
            route for route in main.app.routes if getattr(route, "path", None) != "/boom-test"
        ]

    def test_returns_500_without_the_traceback(self, client, exploding_route):
        # raise_server_exceptions=False makes TestClient behave like a real
        # server: return the handler's response instead of re-raising.
        from fastapi.testclient import TestClient

        import main

        with TestClient(main.app, raise_server_exceptions=False) as safe_client:
            res = safe_client.get("/boom-test", headers=JSON)

        assert res.status_code == 500
        body = res.text
        assert "a secret internal detail" not in body
        assert "Traceback" not in body
        assert "RuntimeError" not in body

    def test_logs_the_failure(self, client, exploding_route, caplog):
        from fastapi.testclient import TestClient

        import main

        with TestClient(main.app, raise_server_exceptions=False) as safe_client:
            safe_client.get("/boom-test", headers=JSON)

        # The detail has to go somewhere, or the bug is invisible to operators.
        assert any("Unhandled error" in record.message for record in caplog.records)


class TestHttpExceptionHeaders:
    def test_a_429_keeps_retry_after(self, client, admin, monkeypatch):
        """Retry-After is actionable, so the JSON error handler must preserve
        headers the raiser set rather than dropping them."""
        from ratelimit import RateLimit, login_limiter

        monkeypatch.setattr(login_limiter, "_limit", RateLimit(max_attempts=1, window_seconds=60))
        client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 429
        assert "retry-after" in res.headers


class TestNonApiPaths:
    def test_a_browser_gets_the_html_page(self, client):
        """In production these paths reach the SPA mount and are answered with
        index.html so the client router can render its own 404. With no build
        present (here, and in dev) they 404, and a browser should still get a
        readable page rather than a JSON blob."""
        res = client.get("/some/deep/client/route", headers=HTML)
        assert res.status_code == 404
        assert "text/html" in res.headers["content-type"]

    def test_a_json_client_still_gets_json(self, client):
        res = client.get("/some/deep/client/route", headers=JSON)
        assert "application/json" in res.headers["content-type"]

    def test_routing_failures_reach_our_handler_at_all(self, client):
        """Regression: an unmatched path raises Starlette's HTTPException, not
        FastAPI's subclass. A handler registered only for the subclass never
        saw these, so every mistyped URL returned a bare JSON 404 no matter
        who asked."""
        assert b"Endpaper" in client.get("/nope", headers=HTML).content


class TestValidatorRejections:
    """A validator that raises `ValueError` must still produce a 422.

    Pydantic puts the **exception object** into the error entry's `ctx`, and
    `JSONResponse` cannot serialise that. Without the encode in the handler,
    a merely invalid request renders a TypeError and the caller gets a 500.
    """

    def test_a_rejected_tag_name_is_422_not_500(self, client, admin):
        res = client.post(
            "/api/books/tags", json={"name": "   "}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_a_rejected_isbn_is_422_not_500(self, client, admin):
        res = client.post(
            "/api/books",
            json={"title": "Dune", "isbn": "1234567890123"},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_the_body_is_readable_json(self, client, admin):
        res = client.post(
            "/api/books/tags", json={"name": "   "}, headers=admin["headers"]
        )
        assert isinstance(res.json()["detail"], list)
