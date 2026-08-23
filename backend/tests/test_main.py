"""Tests for backend/main.py: app wiring, seeding and the ad-hoc migration."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import main
from database import Base, engine
from models import Tag


class TestSeedTags:
    def test_seeds_every_predefined_tag(self, db):
        assert db.query(Tag).count() == len(main.PREDEFINED_TAGS)

    def test_is_idempotent(self, db):
        """seed_tags() runs on every boot: a restart must not duplicate rows."""
        before = db.query(Tag).count()
        main.seed_tags()
        main.seed_tags()
        db.expire_all()
        assert db.query(Tag).count() == before

    def test_restores_a_tag_someone_deleted(self, db):
        db.query(Tag).filter(Tag.name == "Fantasy").delete()
        db.commit()
        main.seed_tags()
        assert db.query(Tag).filter(Tag.name == "Fantasy").count() == 1

    def test_every_predefined_tag_has_a_known_category(self):
        assert {category for _, category in main.PREDEFINED_TAGS} == {"type", "genre", "age"}

    def test_predefined_tag_names_are_unique(self):
        names = [name for name, _ in main.PREDEFINED_TAGS]
        assert len(names) == len(set(names))


class TestAppWiring:
    def test_every_router_is_registered(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for expected in (
            "/auth/login",
            "/api/books",
            "/api/loans",
            "/api/settings/login-image",
            "/api/stats",
            "/api/users",
        ):
            assert expected in paths

    def test_the_cover_route_exists(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert "/covers/{book_id}.{extension}" in paths

    def test_covers_are_registered_before_the_spa_catch_all(self):
        """A catch-all mounted at / swallows every path below it, /covers
        included, so the order these two are registered in is load-bearing.

        The SPA mount exists only when a built frontend is present, which it is
        not under test, hence the guard.
        """
        from starlette.routing import Mount

        routes = list(main.app.routes)
        spa = [
            index
            for index, route in enumerate(routes)
            if isinstance(route, Mount) and route.path == "/"
        ]
        if not spa:
            return
        routers = [
            index
            for index, route in enumerate(routes)
            if type(route).__name__ == "_IncludedRouter"
        ]
        assert max(routers) < spa[0]

    def test_covers_are_served_by_a_router_not_a_static_mount(self):
        """This is a security property, not a wiring preference.

        A StaticFiles mount has no dependencies, so nothing authenticated or
        authorized that path, and cover files are named by book id. Any member
        could read another member's private book cover by counting integers.
        Serving them through a route is what puts `book_for_read` in the way.
        """
        from starlette.routing import Mount

        mounts = [
            route.path
            for route in main.app.routes
            if isinstance(route, Mount) and route.path == "/covers"
        ]
        assert mounts == []

    def test_a_cover_requires_authentication(self, client):
        """Every other path 401s without an identity. This one used to answer
        from disk."""
        assert client.get("/covers/1.jpg").status_code == 401

    def test_openapi_schema_builds(self, client):
        """Catches unresolvable response models across every route at once."""
        assert client.get("/openapi.json").status_code == 200

    def test_docs_are_served(self, client):
        assert client.get("/docs").status_code == 200

    def test_no_cors_headers_by_default(self, client):
        """The API and the compiled frontend are served from one origin, so no
        cross-origin request happens in a normal deployment and no allowance is
        made for one.

        This replaced `allow_origins=["*"]` with `allow_credentials=True`,
        which let any site on the internet make authenticated calls to the API
        on a signed-in member's behalf. Set CORS_ORIGINS to opt back in for a
        genuinely separate frontend host.
        """
        res = client.get("/auth/config", headers={"Origin": "http://example.com"})
        assert res.headers.get("access-control-allow-origin") is None

    def test_cors_origins_setting_is_read_from_the_environment(self, monkeypatch):
        """The middleware is wired at import, so this checks the setting the
        wiring consumes rather than restarting the app."""
        import config

        monkeypatch.setenv("CORS_ORIGINS", "https://books.example.com, https://other.example")
        assert config.cors_origins() == [
            "https://books.example.com",
            "https://other.example",
        ]

    def test_cors_origins_defaults_to_empty(self, monkeypatch):
        import config

        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        assert config.cors_origins() == []


class TestInitDb:
    def test_creates_the_tables_and_seeds(self, db):
        # alembic_version has to go too: it is not part of Base.metadata, so
        # drop_all leaves it behind and Alembic would believe the (now absent)
        # schema is already at head and create nothing.
        Base.metadata.drop_all(bind=engine)
        with engine.connect() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
            connection.commit()

        main.init_db()

        assert db.query(Tag).count() == len(main.PREDEFINED_TAGS)

    def test_creates_the_covers_directory(self):
        from config import COVERS_DIR

        main.init_db()
        assert COVERS_DIR.is_dir()


class TestHealthz:
    """The probes used to request `/`, which the SPA mount answers from disk."""

    def test_it_reports_ok(self, client):
        res = client.get("/api/healthz")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

    def test_it_needs_no_token(self, client):
        """A probe holds none, and the only thing disclosed is that the service
        is up, which anyone can tell by connecting."""
        assert "authorization" not in client.headers
        assert client.get("/api/healthz").status_code == 200

    def test_it_touches_the_database(self, client, monkeypatch):
        """Otherwise it answers 200 for a pod whose volume never mounted, which
        is exactly the failure the probes exist to catch."""

        def broken(*args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("disk I/O error"))

        monkeypatch.setattr(Session, "execute", broken)

        with pytest.raises(OperationalError):
            client.get("/api/healthz")

    def test_it_reaches_the_storage_as_well_as_the_database(self, client, monkeypatch):
        """Measured during a total NFS outage: this endpoint answered 200 for 39
        hours while the volume was unresponsive. `SELECT 1` on an already-open
        SQLite handle is served from the page cache and crosses no wire, so a
        stat of the data directory is what actually reaches the mount."""
        import main

        monkeypatch.setattr(main, "storage_is_reachable", lambda: False)

        assert client.get("/api/healthz").status_code == 503

    def test_a_stat_that_never_returns_is_a_failure_not_a_hang(self, monkeypatch):
        """A hung NFS call blocks in uninterruptible sleep and never errors, so
        storage death can only ever surface as a timeout. Without an internal
        clock the handler simply stops answering, which some probes read as a
        hang rather than a failure and which makes the diagnosis harder."""
        import threading

        import main

        release = threading.Event()
        monkeypatch.setattr(main, "STORAGE_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr("main.os.stat", lambda _path: release.wait())
        monkeypatch.setattr(main, "_pending_stat", None)
        try:
            assert main.storage_is_reachable() is False
            # The stuck call is not re-queued behind itself: a backlog of stats
            # that will never run is not a second opinion.
            assert main.storage_is_reachable() is False
        finally:
            release.set()

    def test_an_unreadable_data_directory_is_a_failure(self, monkeypatch):
        import main

        monkeypatch.setattr("main.os.stat", _raise_oserror)
        monkeypatch.setattr(main, "_pending_stat", None)

        assert main.storage_is_reachable() is False


def _raise_oserror(_path):
    raise OSError("stale file handle")


class TestTheOverdueTicker:
    """The lifespan wiring, not the digest. What the digest does is pinned in
    `tests/test_notifications.py`.

    The ticker is reached through the module (`notifications.ticker()`), which
    is what lets these replace it without touching the loop the real one would
    sit in for an hour.
    """

    async def _run_lifespan(self, monkeypatch, *, enabled: str) -> list[str]:
        import asyncio

        import main
        import notifications

        started: list[str] = []

        async def fake_ticker() -> None:
            started.append("started")
            # Long enough that the lifespan's cancel is what ends it, which is
            # the half of the wiring a started-only assertion would miss.
            await asyncio.sleep(3600)

        monkeypatch.setattr(notifications, "ticker", fake_ticker)
        monkeypatch.setenv("ENABLE_OVERDUE_TICKER", enabled)

        async with main.lifespan(main.app):
            # One turn of the loop, or the task is created and never scheduled.
            await asyncio.sleep(0)
        return started

    async def test_it_starts_a_ticker(self, monkeypatch):
        assert await self._run_lifespan(monkeypatch, enabled="true") == ["started"]

    async def test_shutdown_cancels_it_rather_than_leaving_it_pending(self, monkeypatch):
        """Without the await after the cancel, the interpreter can exit while
        the task is between statements, which surfaces as "Task was destroyed
        but it is pending" on every container stop."""
        import asyncio

        before = len(asyncio.all_tasks())
        await self._run_lifespan(monkeypatch, enabled="true")

        assert len(asyncio.all_tasks()) == before

    async def test_it_starts_nothing_when_switched_off(self, monkeypatch):
        """A background task waking on a timer inside a suite that drops every
        table between tests is a source of order-dependent failures, which is
        why `conftest.py` sets this."""
        assert await self._run_lifespan(monkeypatch, enabled="false") == []

    def test_the_suite_runs_with_it_switched_off(self):
        import config

        assert config.overdue_ticker_enabled() is False

    def test_it_ticks_hourly(self):
        """Hourly rather than daily, so a one day interval is honoured within
        an hour of a book coming due rather than at whatever time the container
        last restarted."""
        import notifications

        assert notifications.TICK_SECONDS == 3600


SHELL_MARKER = "<title>Endpaper</title>"

# A browser navigating, and a script or a fetch asking for the same URL. The
# difference between them is what decides whether an unmatched path is answered
# with the shell, so both are named rather than written inline.
NAVIGATION = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
SCRIPT_LOAD = {"Accept": "*/*"}


@pytest.fixture
def spa(tmp_path) -> TestClient:
    """A directory shaped like a `vite build`: hashed assets, stable rest.

    Mounted through `main.mount_spa`, not a mount of our own: the point is to
    measure the wiring production uses, so swapping the class back for a plain
    StaticFiles fails here rather than passing against a private copy.
    """
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-Bx7Kd2p9.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text(f"<!doctype html>{SHELL_MARKER}")
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "sw.js").write_text("// service worker")
    (tmp_path / "registerSW.js").write_text("// registration")

    app = FastAPI()
    main.mount_spa(app, tmp_path)
    return TestClient(app)


class TestStaticCachePolicy:
    """What the built files say about being reused, measured on the wire.

    A real mount over a real directory, driven through a real client, rather
    than calling `cache_control_for` and trusting the wiring. Starlette answers
    some of these requests with a 304 built inside `file_response`, and a test
    of the function alone would never see one.
    """

    def test_the_shell_must_be_revalidated(self, spa):
        """The one that matters. With no policy the browser reuses the shell on
        a heuristic, and yesterday's shell names asset hashes this deploy has
        deleted: a 404 on `assets/index-<hash>.js` and a blank page after a
        release."""
        res = spa.get("/")
        assert res.status_code == 200
        assert res.headers["cache-control"] == "no-cache"

    def test_the_shell_is_the_same_by_its_own_name(self, spa):
        """`/` and `/index.html` are one file and must not disagree."""
        assert spa.get("/index.html").headers["cache-control"] == "no-cache"

    def test_the_shell_is_kept_rather_than_discarded(self, spa):
        """`no-cache`, not `no-store`. The difference is a 304 instead of a
        re-download: the copy stays, and only its freshness is asked about."""
        assert "no-store" not in spa.get("/").headers["cache-control"]

    def test_a_revalidated_file_answers_304_and_keeps_its_policy(self, spa):
        """Starlette builds the 304 itself, and copies only a fixed set of
        headers onto it. A 304 that dropped the policy would leave the next
        request reading from a cache entry with nothing on it."""
        first = spa.get("/index.html")
        second = spa.get("/index.html", headers={"If-None-Match": first.headers["etag"]})
        assert second.status_code == 304
        assert second.headers["cache-control"] == "no-cache"

    def test_a_hashed_asset_keeps_its_year(self, spa):
        """The regression that would be invisible until somebody said the app
        got slow. These names carry a content hash, so a changed file is a
        changed URL and nothing can be stale."""
        res = spa.get("/assets/index-Bx7Kd2p9.js")
        assert res.status_code == 200
        assert res.headers["cache-control"] == "public, max-age=31536000, immutable"

    @pytest.mark.parametrize("path", ["/manifest.json", "/sw.js", "/registerSW.js"])
    def test_a_stable_name_outside_assets_is_revalidated(self, spa, path):
        """These change their bytes every build and keep their names, exactly
        like index.html. sw.js has browser rules of its own on top, which are a
        second belt rather than a substitute for this one."""
        res = spa.get(path)
        assert res.status_code == 200
        assert res.headers["cache-control"] == "no-cache"


class TestTheShellServesClientRoutes:
    """A deep link, a refresh and a bookmark, measured on the wire.

    `html=True` does not do this on its own, and for as long as it was assumed
    to, every client route but `/` answered 404 in production: measured in the
    running container at `/book/12`, `/settings` and `/quotes`, with a valid
    session. `docs/architecture.md` had been promising the opposite in the
    published documentation the whole time.
    """

    @pytest.mark.parametrize("path", ["/book/12", "/settings", "/quotes"])
    def test_a_client_route_gets_the_shell(self, spa, path):
        res = spa.get(path, headers=NAVIGATION)
        assert res.status_code == 200
        assert SHELL_MARKER in res.text

    def test_the_shell_carries_its_no_cache_wherever_it_is_served(self, spa):
        """Or a deep link caches the shell under its own URL, and the reader
        gets yesterday's bundle at `/book/12` and today's at `/`."""
        assert spa.get("/book/12", headers=NAVIGATION).headers["cache-control"] == "no-cache"

    def test_the_login_route_gets_the_shell(self, spa):
        """Called out because it is the recovery path from every ordinary 401:
        `endSession()` in the frontend sets `location.href = "/login"`. Without
        this, a token expiry in local or ldap mode, which is what the published
        image runs, lands the reader on a 404 error page instead of the form."""
        res = spa.get("/login", headers=NAVIGATION)
        assert res.status_code == 200
        assert SHELL_MARKER in res.text

    def test_a_client_route_may_contain_dots(self, spa):
        """So this cannot be keyed on the path looking like a filename, which
        is the usual shortcut: `/authors/J.R.R. Tolkien` is a real route."""
        res = spa.get("/authors/J.R.R. Tolkien", headers=NAVIGATION)
        assert res.status_code == 200
        assert SHELL_MARKER in res.text

    def test_a_fetch_for_an_unknown_path_still_gets_a_404(self, spa):
        """The same content negotiation the `Accept` header taught us, applied
        in the other direction: code asking for a path that is not there must
        be told so, not handed a page."""
        res = spa.get("/book/12", headers={"Accept": "application/json"})
        assert res.status_code == 404
        assert SHELL_MARKER not in res.text

    def test_an_api_path_is_refused_the_shell_by_this_mount_too(self, spa):
        """Belt and braces, and the braces are what is asserted here. `_fallback`
        claims `/api/*` and `/auth/*` before the mount ever sees them, so this
        cannot happen through the real app; `wants_html` refuses them anyway, so
        a future change to router order cannot turn an API typo into a 200 with
        HTML in it."""
        res = spa.get("/api/nope", headers=NAVIGATION)
        assert res.status_code == 404
        assert SHELL_MARKER not in res.text

    @pytest.mark.parametrize("headers", [SCRIPT_LOAD, NAVIGATION])
    def test_a_missing_asset_is_never_the_shell(self, spa, headers):
        """The failure this must not reintroduce. Asset names are content
        addressed, so a request for one that is missing means the client is
        holding a stale shell; answering it with HTML turns a clean 404 into a
        parse error inside a script tag. Asserted for a navigation as well as a
        script load, because the `Accept` test alone would rest on a header
        nobody here controls."""
        res = spa.get("/assets/missing.js", headers=headers)
        assert res.status_code == 404
        assert SHELL_MARKER not in res.text

    def test_a_write_to_a_client_route_is_not_the_shell(self, spa):
        """405 rather than 404, which is Starlette's answer for any method the
        mount does not serve and predates this: `get_response` raises it before
        the fallback runs, and the `except` re-raises anything that is not a
        404, so a write never reaches the shell branch at all.

        It *is* a page, and the docstring here used to say it was not. Behind
        the real error handlers a browser gets 405 with `content-type:
        text/html` and this app's error template, because the mount raises
        inside `ExceptionMiddleware` and `wants_html` renders it. What matters,
        and what is asserted, is that the page is not the shell: a write to a
        path that does not exist must not boot the app."""
        res = spa.post("/book/12", headers=NAVIGATION)
        assert res.status_code == 405
        assert SHELL_MARKER not in res.text

    def test_a_head_matches_the_get(self, spa):
        assert spa.head("/book/12", headers=NAVIGATION).status_code == 200

    @pytest.mark.parametrize(
        "path",
        ["/%2e%2e%2fmain.py", "/....//main.py", "/assets/%2e%2e%2f%2e%2e%2fmain.py"],
    )
    def test_an_escape_attempt_gets_the_shell_and_never_a_file(self, spa, path):
        """The containment check in `lookup_path` runs first, so an escaped path
        is simply not found, and a navigation to one then gets the shell like
        any other unmatched path. Recorded because the answer changed: before
        the fallback these were a 404, and what matters is that neither answer
        contains the file."""
        res = spa.get(path, headers=NAVIGATION)
        assert "CachePolicyStaticFiles" not in res.text
        assert res.status_code == 200
        assert SHELL_MARKER in res.text
