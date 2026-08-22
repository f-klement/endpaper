"""Tests for backend/main.py: app wiring, seeding and the ad-hoc migration."""

import pytest
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
