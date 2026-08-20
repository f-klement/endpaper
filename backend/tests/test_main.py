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
