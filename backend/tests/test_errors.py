"""Tests for backend/errors.py: content-negotiated error responses.

One app serves both a browser and a JSON API, so an error has two correct
forms. These check that each audience gets its own, and in particular that a
crash never returns a traceback to the caller.
"""

import ast
import asyncio
import importlib
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pg8000
import pytest
import respx
from fastapi import HTTPException
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from starlette.requests import ClientDisconnect

import main
from errors import AnswerUnhandledErrors, is_api_path, render_error_page
from tests.test_house_rules import BACKEND, _python_sources

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


@pytest.mark.answers_500(raises=(RuntimeError,))
class TestUnhandledExceptions:
    @pytest.fixture
    def exploding_route(self):
        """Add a route that raises, then remove it again.

        Registered directly on the app rather than mocked, so this exercises
        the real handler chain.

        **The removal is in a `finally`, and that is a guard rather than a style.**
        `main.app` is process wide, so a route left behind is visible to every
        later test in the worker, and one of them derives the app's whole handler
        population and refuses a handler no module declares:
        `tests/test_house_rules.py::TestTheRouteHandlerPopulationIsDerivedTwice`.
        After a bare `yield` the cleanup is skipped whenever the generator is
        closed rather than resumed, and the failure then lands in another file
        under a message about this app registering a route nobody wrote.
        `--dist loadfile` is not protection: it keeps one file's tests together, it
        does not keep two files apart.
        """
        import main

        @main.app.get("/boom-test", include_in_schema=False)
        def boom() -> None:
            raise RuntimeError("a secret internal detail")

        try:
            yield
        finally:
            main.app.routes[:] = [
                route
                for route in main.app.routes
                if getattr(route, "path", None) != "/boom-test"
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


class _Counted(BaseModel):
    count: int


@pytest.mark.answers_500(raises=(ResponseValidationError, ValidationError))
class TestAValidationErrorLogsNoValue:
    """Both validation errors carry the value that failed, in their message
    and in `input`, so a traceback of one writes member data to the log."""

    MARKER = "INPUT-VALUE-MARKER"

    @pytest.fixture
    def invalid_routes(self):
        """The same add, then remove in a `finally`, as `exploding_route`."""
        import main

        @main.app.get("/invalid-response-test", include_in_schema=False, response_model=_Counted)
        def invalid_response() -> Any:
            return {"count": self.MARKER}

        @main.app.get("/invalid-model-test", include_in_schema=False)
        def invalid_model() -> None:
            _Counted.model_validate({"count": self.MARKER})

        try:
            yield
        finally:
            main.app.routes[:] = [
                route
                for route in main.app.routes
                if getattr(route, "path", None)
                not in ("/invalid-response-test", "/invalid-model-test")
            ]

    @pytest.mark.parametrize(
        ("path", "kind"),
        [
            ("/invalid-response-test", "ResponseValidationError"),
            ("/invalid-model-test", "ValidationError"),
        ],
    )
    def test_the_log_names_the_type_and_where_and_never_the_value(
        self, client, invalid_routes, caplog, path, kind
    ):
        from fastapi.testclient import TestClient

        import main

        with (
            caplog.at_level(logging.DEBUG),
            TestClient(main.app, raise_server_exceptions=False) as safe_client,
        ):
            res = safe_client.get(path, headers=JSON)

        assert res.status_code == 500
        [line] = [record for record in caplog.records if "Unhandled error" in record.message]
        assert f": {kind} " in line.getMessage()
        assert "'count'" in line.getMessage()
        assert self.MARKER not in caplog.text


def postgres_shaped_error(marker: str) -> IntegrityError:
    """A unique violation as pg8000 hands one over: the server's fields as a dict.

    Built from `pg8000.IntegrityError`, the class pg8000 raises for SQLSTATE
    23505, with the field codes its `handle_ERROR_RESPONSE` keys them by, `D`
    the detail and `n` the constraint, because this suite runs on SQLite:
    Postgres puts the conflicting value in the detail, and pg8000 renders the
    dict whole. `test_errors_on_a_real_server.py` drives the same path against
    a live one.
    """
    original = pg8000.IntegrityError(
        {
            "S": "ERROR",
            "C": "23505",
            "M": 'duplicate key value violates unique constraint "uq_marker_probe"',
            "D": f"Key (email)=({marker}) already exists.",
            "n": "uq_marker_probe",
        }
    )
    return IntegrityError(
        "INSERT INTO users (email) VALUES (%s)", (marker,), original, hide_parameters=True
    )


@pytest.mark.answers_500(raises=(IntegrityError, PendingRollbackError))
class TestADatabaseErrorLogsNoRow:
    """`hide_parameters` keeps SQLAlchemy's bound values out; the driver's own
    message is the other half, and on Postgres it quotes the row."""

    MARKER = "DETAIL-VALUE-MARKER"

    @pytest.fixture
    def failing_routes(self):
        """The same add, then remove in a `finally`, as `exploding_route`."""
        import main

        @main.app.get("/postgres-shaped-test", include_in_schema=False)
        def postgres_shaped() -> None:
            raise postgres_shaped_error(self.MARKER)

        @main.app.get("/pending-rollback-test", include_in_schema=False)
        def pending_rollback() -> None:
            # SQLAlchemy's own wording, from `Session`'s transaction: the flush
            # error is quoted into this one's message, and wrapped by nothing.
            raise PendingRollbackError(
                "This Session's transaction has been rolled back due to a previous "
                "exception during flush. To begin a new transaction with this "
                "Session, first issue Session.rollback(). Original exception was: "
                f"{postgres_shaped_error(self.MARKER)}",
                code="7s2a",
            )

        @main.app.get("/sqlite-duplicate-test", include_in_schema=False)
        def sqlite_duplicate() -> None:
            from database import engine

            with engine.connect() as connection:
                for _ in range(2):
                    connection.execute(
                        text("INSERT INTO settings (key, value) VALUES ('probe_key', 'x')")
                    )

        try:
            yield
        finally:
            main.app.routes[:] = [
                route
                for route in main.app.routes
                if getattr(route, "path", None)
                not in ("/postgres-shaped-test", "/pending-rollback-test", "/sqlite-duplicate-test")
            ]

    def test_a_postgres_detail_never_reaches_the_log(self, client, failing_routes, caplog):
        with caplog.at_level(logging.DEBUG):
            res = client.get("/postgres-shaped-test", headers=JSON)

        assert res.status_code == 500
        [line] = [r for r in caplog.records if r.getMessage().startswith("Unhandled error")]
        assert "IntegrityError(IntegrityError) on uq_marker_probe" in line.getMessage()
        assert self.MARKER not in caplog.text

    def test_an_error_quoting_a_flush_error_never_reaches_the_log(
        self, client, failing_routes, caplog
    ):
        """`PendingRollbackError` is no driver error and wraps none: it quotes
        one. Logged by its type alone."""
        with caplog.at_level(logging.DEBUG):
            res = client.get("/pending-rollback-test", headers=JSON)

        assert res.status_code == 500
        [line] = [r for r in caplog.records if r.getMessage().startswith("Unhandled error")]
        assert ": PendingRollbackError\n" in line.getMessage()
        assert self.MARKER not in caplog.text

    def test_a_sqlite_message_is_left_out_with_the_rest(self, client, failing_routes, caplog):
        """SQLite names columns, never values, and is still left out: one rule
        for every engine."""
        with caplog.at_level(logging.DEBUG):
            res = client.get("/sqlite-duplicate-test", headers=JSON)

        assert res.status_code == 500
        [line] = [r for r in caplog.records if r.getMessage().startswith("Unhandled error")]
        assert "IntegrityError(IntegrityError)" in line.getMessage()
        assert "UNIQUE constraint failed" not in caplog.text


def _http_scope() -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": "/api/thing",
        "raw_path": b"/api/thing",
        "query_string": b"",
        "headers": [(b"accept", b"application/json")],
        "scheme": "http",
        "server": ("test", 80),
    }


async def _drive(inner: Any) -> list[dict[str, Any]]:
    """Run `AnswerUnhandledErrors` around `inner` and return what it sent."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Any) -> None:
        sent.append(message)

    await AnswerUnhandledErrors(inner)(_http_scope(), receive, send)
    return sent


@pytest.mark.answers_500(raises=(RuntimeError,))
class TestAnUnhandledErrorIsAnsweredInsideTheApp:
    """`AnswerUnhandledErrors` answers the 500 so Starlette never re-raises the
    exception to the server, and lets through what it must not swallow."""

    async def test_an_exception_before_the_response_is_answered_500_and_not_raised(self):
        async def inner(scope: Any, receive: Any, send: Any) -> None:
            raise RuntimeError("a route failed")

        sent = await _drive(inner)

        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 500

    @pytest.mark.parametrize(
        "error",
        [asyncio.CancelledError(), ClientDisconnect()],
        ids=["a cancellation", "a client that disconnected"],
    )
    async def test_it_passes_through(self, error):
        async def inner(scope: Any, receive: Any, send: Any) -> None:
            raise error

        with pytest.raises(type(error)):
            await _drive(inner)

    async def test_an_exception_after_the_response_started_is_raised(self):
        """A 500 can no longer be sent, and swallowing it would end a truncated
        body as though it were whole."""

        async def inner(scope: Any, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise RuntimeError("failed mid body")

        with pytest.raises(RuntimeError, match="failed mid body"):
            await _drive(inner)


#: A module that adds one failing route to the shipped app, so the shipped
#: server can be started on it: `uvicorn <module>:app`, the image's command with
#: the module's name changed and nothing else.
_SERVED = """
from typing import Any

from pydantic import BaseModel

import main


class Counted(BaseModel):
    count: int


@main.app.get("/invalid-response-test", include_in_schema=False, response_model=Counted)
def invalid_response() -> Any:
    return {"count": "SERVER-LOG-MARKER"}


app = main.app
"""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class TestTheServerLogsAValidation500Once:
    """The bar on the shipped start command, which `TestClient` cannot see:
    it has no uvicorn, and uvicorn is what logged the second copy."""

    def test_one_line_and_no_value_anywhere_in_the_server_output(self, tmp_path):
        (tmp_path / "served_probe.py").write_text(_SERVED)
        port = _free_port()
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(tmp_path), str(BACKEND)]),
            "DATA_DIR": str(tmp_path),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'served.db'}",
        }
        # A file rather than a pipe: the migration chain logs a line a revision
        # at startup, and a pipe nobody reads while polling would fill and stop
        # the server mid start.
        log = tmp_path / "server.log"
        with log.open("wb") as written:
            server = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn", "served_probe:app",
                    "--host", "127.0.0.1", "--port", str(port),
                ],
                cwd=BACKEND,
                env=env,
                stdout=written,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            answer = None
            deadline = time.monotonic() + 60
            # Passed through the suite's own router, which refuses every
            # request nobody mocked: this one is the point.
            with respx.mock(assert_all_called=False) as router:
                router.route(host="127.0.0.1").pass_through()
                while answer is None and time.monotonic() < deadline:
                    try:
                        answer = httpx.get(
                            f"http://127.0.0.1:{port}/invalid-response-test",
                            headers=JSON,
                            timeout=5,
                        )
                    except httpx.TransportError:
                        time.sleep(0.2)
        finally:
            # The group, so nothing the server started outlives the test.
            if server.poll() is None:
                os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait()
        output = log.read_text()

        assert answer is not None, output
        assert answer.status_code == 500
        assert output.count("Unhandled error serving GET /invalid-response-test") == 1, output
        assert "Exception in ASGI application" not in output
        assert "SERVER-LOG-MARKER" not in output
        assert "SERVER-LOG-MARKER" not in answer.text


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


def _schema() -> dict[str, Any]:
    """The document this API publishes.

    Generated from the app rather than read from `frontend/openapi.json`, which
    is the same document by another guard: `test_openapi_drift.py` holds the
    committed file byte identical to what `scripts/dump_openapi.py` writes.
    Asking the app is the same question with no second copy of where that file
    lives.
    """
    return main.app.openapi()


def _resolved(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """One `$ref` followed, which is as deep as FastAPI writes an error body."""
    reference = node.get("$ref")
    if not reference:
        return node
    found: Any = schema
    for step in reference.removeprefix("#/").split("/"):
        found = found[step]
    return found


def _statuses_whose_detail_is_not_a_sentence(schema: dict[str, Any]) -> set[int]:
    """Statuses this API's schema declares with an **array** `detail`.

    **Derived from the document rather than named**, and that is the whole
    guard: FastAPI declares `HTTPValidationError` for 422 on every operation
    that validates anything, and `HTTPException(422, detail="...")` sends a
    string into that declaration. Reading the property is what keeps this true
    if the envelope is ever renamed, moved, or given a second status.
    """
    found: set[int] = set()
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for status, response in operation.get("responses", {}).items():
                if not status.isdigit():
                    continue
                for media in response.get("content", {}).values():
                    detail = (
                        _resolved(schema, media.get("schema", {}))
                        .get("properties", {})
                        .get("detail", {})
                    )
                    if detail.get("type") == "array":
                        found.add(int(status))
    return found


@dataclass(frozen=True)
class _Module:
    """One backend module, as both the object and the tree that wrote it."""

    module: Any
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]


def _resolve(expression: ast.expr, module: Any) -> Any:
    """A dotted name read where the module that wrote it would read it.

    **Resolved rather than matched as text.** `422` and
    `status.HTTP_422_UNPROCESSABLE_CONTENT` are two spellings of one number and
    the next one written will be a third, so nothing here knows how a constant
    is spelled: it is looked up in the module's own globals.
    """
    steps: list[str] = []
    while isinstance(expression, ast.Attribute):
        steps.append(expression.attr)
        expression = expression.value
    if not isinstance(expression, ast.Name):
        return None
    found: Any = getattr(module, expression.id, None)
    for step in reversed(steps):
        found = getattr(found, step, None)
    return found


def _one_status(expression: ast.expr, module: Any) -> set[int] | None:
    """One status expression as the single number it names, or None."""
    if isinstance(expression, ast.Constant) and isinstance(expression.value, int):
        return {expression.value}
    number = _resolve(expression, module)
    return {number} if isinstance(number, int) else None


def _statuses_in(expression: ast.expr, context: _Module, seen: frozenset[str]) -> set[int] | None:
    """The statuses a **kwargs expression can carry, or None if unreadable.

    Three routes here answer `HTTPException(**_lookup_failure(result))`, so the
    number is one call away and a walk reading the argument alone cannot see it.
    Following the helper is what keeps those three inside the rule rather than
    inside its blind spot, and the recursion is bounded by `seen` because
    `_lookup_failure` returns `_no_sources()` from one of its branches.
    """
    if isinstance(expression, ast.Dict):
        for key, value in zip(expression.keys, expression.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "status_code":
                return _one_status(value, context.module)
        return None
    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name):
        name = expression.func.id
        if name in seen:
            return set()
        helper = context.functions.get(name)
        if helper is None:
            return None
        found: set[int] = set()
        for node in ast.walk(helper):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            carried = _statuses_in(node.value, context, seen | {name})
            if carried is None:
                return None
            found |= carried
        return found or None
    return None


def _status_of(call: ast.Call, context: _Module) -> set[int] | None:
    """The statuses this construction can answer with, or None if unreadable.

    A set rather than a number, because a construction handed a helper's
    mapping carries whichever status that helper chose. An unreadable one is
    reported by the caller rather than dropped: a guard that quietly skips what
    it cannot read has stopped guarding exactly where somebody was clever.
    """
    for keyword in call.keywords:
        if keyword.arg is None:
            return _statuses_in(keyword.value, context, frozenset())
    given = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "status_code"),
        call.args[0] if call.args else None,
    )
    return None if given is None else _one_status(given, context.module)


def _refusals() -> list[tuple[str, int, set[int] | None]]:
    """(file, line, statuses) for every `HTTPException` this backend builds.

    Constructions rather than `raise` statements, because several are built by
    a helper and returned: `dependencies._not_found` and its neighbours. A walk
    over `raise` alone reads clean over those and says so about nothing.

    The class is resolved rather than matched by name, so an alias at the
    import and a subclass both count, and a local variable that happens to be
    called `HTTPException` does not.
    """
    found: list[tuple[str, int, set[int] | None]] = []
    for path in _python_sources():
        where = path.relative_to(BACKEND).as_posix()
        module = importlib.import_module(where.removesuffix(".py").replace("/", "."))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        context = _Module(
            module=module,
            functions={
                node.name: node
                for node in tree.body
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            },
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            built = _resolve(node.func, module)
            if isinstance(built, type) and issubclass(built, HTTPException):
                found.append((where, node.lineno, _status_of(node, context)))
    return found


class TestTheDocumentEnumeratesNoRefusal:
    """The fact two published docstrings rest on, asserted rather than described.

    `routers/books.export_books` and `routers/backup.download_backup` both say,
    in prose the mirror publishes, that this document enumerates no refusal
    anywhere, and give that as the reason the 429 they can answer is not
    declared on them alone. **A described reason rots silently and an asserted
    one reddens**, so the day somebody declares a refusal on any operation,
    those two paragraphs stop being true and this says so by name.

    **This is a pin, not a policy.** It does not say declaring refusals is
    wrong; it says the two routes above are arguing from a property of the whole
    document, and that property has changed. The right answer to a red here may
    well be to declare them everywhere and rewrite both paragraphs.

    422 is excluded because FastAPI writes it from the route's own parameter
    validation rather than anybody declaring it, which is the distinction the
    class below turns on as well.
    """

    @staticmethod
    def _declared_keys() -> set[str]:
        """Every response key this document declares, spelled as it spells it.

        **The raw string, never `int`.** An OpenAPI response key is not always
        a number: `4XX`, `5XX` and `default` are all valid, and FastAPI writes
        whichever one a route hands it straight through. This walk filtered on
        `status.isdigit()` and therefore could not see any of them, so a
        refusal declared in the spelling the failure message below asks for
        left the arm green. Measured 2026-09-29 against a standalone app
        declaring `4XX` on one operation, `default` on a second and `429` on a
        third: the digit filter returned `[200, 429]`.
        """
        return {
            status
            for path in _schema()["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict)
            for status in operation.get("responses", {})
        }

    @staticmethod
    def _is_a_refusal(status: str) -> bool:
        """Whether one response key is a refusal, decided by what it is not.

        A plain success number is not, and 422 is not, for the reason the class
        docstring gives. **Everything else is**, which is what keeps a spelling
        this rule has never seen on the side that reddens: a ranged key,
        `default`, and whatever a later version of the specification adds. A
        ranged *success* such as `2XX` reddens it as well, so does `3XX`, and
        that is the direction a pin belongs on: the arm prints the key it
        found, so the answer is to read the two paragraphs again rather than
        to widen this.

        **Widening it is not local, and that is why the line is here rather
        than only at the other end.**
        `tests/test_declared_media_types.py::_carries_a_representation` steps
        over any response key that is not a plain number, and what makes that
        a safe skip rather than a silent one is that this rule reddens on such
        a key first. Allow a ranged key here and that walk goes quiet over the
        route carrying it.
        """
        return status != "422" and not (status.isdigit() and int(status) < 400)

    def test_the_document_declares_statuses_at_all(self) -> None:
        """The vacuity arm. An empty set, from a schema that failed to load or
        a walk that stopped matching the document's shape, satisfies the rule
        below over any tree at all."""
        assert len(self._declared_keys()) > 2, self._declared_keys()

    def test_no_declared_status_is_a_refusal(self) -> None:
        refusals = sorted(
            status for status in self._declared_keys() if self._is_a_refusal(status)
        )

        assert refusals == [], (
            f"This document now declares {refusals}, and two published route "
            "docstrings argue from it declaring none: `export_books` and "
            "`download_backup` each say their 429 is left undeclared because "
            "declaring one refusal on one operation would make it look "
            "deliberate and the rest accidental. Rewrite both paragraphs, or "
            "declare the refusals across the surface, which is what they say "
            "the whole decision is."
        )


class TestNoRefusalBorrowsAStatusTheSchemaTypesDifferently:
    """A hand raised refusal carries a sentence; 422 is declared as an array.

    `HTTPException(detail="...")` puts the string straight into `detail`, and
    the committed schema declares `detail` for 422 as an array of validation
    entries, because that is what FastAPI's own body validation sends. Four
    operations answered a string under that status until 2026-09-20, found by
    the schema driven run in `tests/api_contract.py`: the schema the TypeScript
    client is generated from, disagreeing with what the app sends.

    **Both ends are derived.** Which status is typed that way is read off the
    document, and which number a call was given is resolved in the module that
    wrote it, so neither a rename of the envelope nor a new spelling of the
    constant walks past this.

    What it does not say is that a refusal is **documented**. Four routes declare
    a `responses` entry since 2026-09-29 and every one of them declares only the
    media type of its own 200, so no refusal anywhere in this tree is documented
    and `response_schema_conformance` still has nothing to compare against one;
    `docs/decisions.md` records why declaring one was refused, and
    `routers/books.export_books` records why a 429 added that day was not the
    exception.
    """

    def test_the_schema_types_a_status_this_rule_can_be_about(self) -> None:
        """The vacuity arm at the schema end. An empty set makes the rule below
        pass over any code at all, and it goes empty by a rename of the
        envelope or by a schema that failed to load."""
        assert _statuses_whose_detail_is_not_a_sentence(_schema()), (
            "no status in this API's schema declares an array `detail`, so "
            "there is nothing for a hand raised refusal to contradict"
        )

    def test_the_walk_found_the_refusals_this_backend_writes(self) -> None:
        """The vacuity arm at the code end, as a floor rather than a count: the
        number moves with every route added, and a floor this far under it only
        fails when the walk has stopped finding them. 117 constructions on
        2026-09-20."""
        assert len(_refusals()) > 100, len(_refusals())

    def test_every_status_the_walk_read_resolved_to_a_number(self) -> None:
        """An unreadable status is a hole in the rule below, not a pass."""
        unreadable = [
            f"{where}:{line}" for where, line, statuses in _refusals() if statuses is None
        ]

        assert unreadable == [], (
            "the status these refusals were given could not be resolved, so the "
            f"rule below says nothing about them: {unreadable}"
        )

    def test_no_refusal_uses_one_of_those_statuses(self) -> None:
        typed = _statuses_whose_detail_is_not_a_sentence(_schema())
        borrowed = [
            f"{where}:{line} answers {sorted(statuses & typed)}"
            for where, line, statuses in _refusals()
            if statuses and statuses & typed
        ]

        assert borrowed == [], (
            "These build an HTTPException under a status the committed schema "
            f"declares with an array `detail` ({sorted(typed)}), so each sends a "
            "sentence where a client generated from that schema expects a list "
            "of entries:\n  " + "\n  ".join(borrowed) + "\n"
            "Use a status the schema does not type, which is what every other "
            "refusal in this tree does."
        )
