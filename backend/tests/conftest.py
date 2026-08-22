"""Shared fixtures.

The application modules read their configuration at import time (DATA_DIR is
resolved once, and database.py builds the engine on import), so the environment
has to be pointed at a throwaway directory *before* anything imports them. That
is what the module-level block below does. It must stay above any application
import in the test suite.
"""

import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# ── Environment must be set before the app is imported ────────────────────────

_TMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="endpaper-tests-"))
os.environ["DATA_DIR"] = str(_TMP_DATA_DIR)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DATA_DIR / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-characters-long"
os.environ.setdefault("ALLOW_REGISTRATION", "true")
# The suite exercises the startup secret guard explicitly in test_config.py;
# everywhere else it would just be noise, so the app boots in dev posture.
os.environ.setdefault("APP_ENV", "dev")
# The `client` fixture enters the app's lifespan, which starts the hourly
# overdue ticker. A background task waking on a timer inside a suite that
# drops and recreates every table between tests is a source of failures that
# depend on how long the run took. `notifications.run_digest` is driven
# directly instead, and the wiring is pinned in tests/test_main.py.
os.environ.setdefault("ENABLE_OVERDUE_TICKER", "false")
# **Removed, not defaulted.** A key in the shell that happens to run the suite
# wins over the stored one everywhere `google_books_api_key_from_env()` is
# consulted, so `GET /api/settings` would report the environment's key and any
# test asserting on the stored one would be asserting about a value it never
# set. `TestEverySecretSettingIsMasked` passed vacuously for this key that way,
# and this deployment really does have it set. Every test that wants it sets it
# for itself with `monkeypatch.setenv`, which is unaffected by this.
os.environ.pop("GOOGLE_BOOKS_API_KEY", None)

# The backend is imported flat ("from models import Book"), the way uvicorn
# imports it with backend/ as the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import covers  # noqa: E402
import main  # noqa: E402
import metadata  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402
from models import User  # noqa: E402
from ratelimit import (  # noqa: E402
    cover_backfill_limiter,
    import_limiter,
    login_limiter,
    metadata_limiter,
    register_limiter,
)


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Give every test an empty database with only the predefined tags seeded.

    Dropping and recreating is affordable here because the database is a
    SQLite file of a few kilobytes, and it keeps tests order-independent.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    main.seed_tags()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    """Clear every rate-limit counter between tests.

    They are process-global and deliberately survive requests, so without this
    a test that logs in or imports repeatedly would start tripping the limiter
    partway through the suite, and which test failed would depend on ordering.

    Every limiter belongs here. The import one was added later and its absence
    turned twelve unrelated import tests red, all of them passing on their own.
    """
    login_limiter.reset()
    register_limiter.reset()
    import_limiter.reset()
    metadata_limiter.reset()
    cover_backfill_limiter.reset()


@pytest.fixture(autouse=True)
def clear_metadata_cache() -> None:
    """Forget every cached ISBN lookup between tests.

    `metadata` caches by ISBN in the process, so without this the first test to
    look up an ISBN answers for every later one that uses the same number, and
    a mocked source that is supposed to be consulted is never called at all.
    Three lookup tests failed exactly that way when the cache was added.
    """
    metadata.clear_cache()


#: The real `covers.resolve_and_store`, captured before the fixture below
#: replaces it. tests/test_covers.py puts it back to exercise it for real
#: against a mocked transport; nothing else should need it.
REAL_RESOLVE_AND_STORE = covers.resolve_and_store


@pytest.fixture(autouse=True)
def offline_covers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop every book that is added from reaching out for its cover.

    Adding a book now downloads its cover, and resolves one from the image
    services when none was supplied. Left alone that is two real HTTP requests,
    each with a six second timeout, on every one of the many tests that add a
    book, and the suite would depend on the network being there.

    The stand-in answers "no cover to be had", which leaves `cover_url` exactly
    as the request set it. That is what this app did before covers were stored,
    so the tests that are about something else see the behaviour they were
    written against.

    A test that is about the cover path patches this back over the top: the
    router calls `covers.resolve_and_store` through the module, and the later
    `monkeypatch` wins. The real function is exercised directly, against a
    mocked transport, in tests/test_covers.py.
    """
    monkeypatch.setattr(
        covers,
        "resolve_and_store",
        # The signature is mirrored rather than swallowed with **kwargs: a stub
        # that accepts anything keeps passing after the real one changes shape,
        # which is how a stub stops standing for the thing it replaces.
        lambda book_id, isbn, supplied, budget=None: None,
    )


@pytest.fixture(autouse=True)
def reset_cover_counts() -> None:
    """Cover outcome tallies are process-global, so a test asserting on them
    would otherwise read whatever earlier tests left behind."""
    covers.reset_counts()


# Image payloads and page-unwrapping helpers live in tests/helpers.py, which
# test modules import directly.


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def db() -> Iterator[object]:
    """A session for arranging state directly, bypassing the API."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def covers_dir() -> Iterator[Path]:
    """An empty covers directory, emptied again afterwards.

    Emptying matters because `clean_database` drops and recreates the tables,
    so book ids restart at 1 in every test, while cover files are named by book
    id and used to survive. One test's upload was then visible to the next as
    the cover of an unrelated book. Harmless while nothing read covers back,
    and immediately wrong once a route served them.
    """
    from config import COVERS_DIR

    def empty() -> None:
        if COVERS_DIR.is_dir():
            for entry in COVERS_DIR.iterdir():
                if entry.is_file():
                    entry.unlink()

    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    empty()
    yield COVERS_DIR
    empty()


# ── Authentication modes ──────────────────────────────────────────────────────
#
# Here rather than in one test module because two of them need the same setup:
# tests/test_auth_backends.py drives the backends directly, tests/routers/
# test_auth.py drives the same backends through the HTTP routes. `auth_mode()`
# reads the environment per call, so a monkeypatched variable is enough and no
# module has to be reimported.


@pytest.fixture
def ldap_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "ldap")
    monkeypatch.setenv("LDAP_URL", "ldap://directory.invalid")
    monkeypatch.setenv("LDAP_USER_BASE_DN", "ou=people,dc=example,dc=org")
    monkeypatch.setenv("LDAP_ADMIN_GROUP", "cn=librarians,ou=groups,dc=example,dc=org")


@pytest.fixture
def proxy_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy auth with no admin group configured, which is the default shape.

    No `PROXY_ADMIN_GROUP`: naming one is optional, and leaving it out is what
    the bootstrap rule in `upsert_directory_user` exists for.
    """
    monkeypatch.setenv("AUTH_MODE", "proxy")


# ── Account helpers ───────────────────────────────────────────────────────────

TEST_PASSWORD = "password123"


@pytest.fixture(scope="session")
def _password_hash() -> str:
    """Hash the shared fixture password once for the whole session.

    bcrypt is deliberately slow, and the account fixtures below are used by
    most tests. Hashing per test costs more than the rest of the suite
    combined. The real registration and hashing paths are still exercised
    end-to-end in tests/routers/test_auth.py and tests/test_auth.py.
    """
    from auth import hash_password

    return hash_password(TEST_PASSWORD)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_account(password_hash: str, username: str, *, is_admin: bool) -> dict:
    """Insert an account directly and mint a token for it."""
    from auth import create_access_token

    session = SessionLocal()
    try:
        user = User(username=username, password_hash=password_hash, is_admin=is_admin)
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_access_token(session, user.id, user.username)
        payload: dict[str, Any] = {
            "user": {"id": user.id, "username": user.username, "is_admin": user.is_admin},
            "access_token": token,
            "password": TEST_PASSWORD,
            "headers": auth_header(token),
        }
    finally:
        session.close()
    return payload


@pytest.fixture
def admin(_password_hash: str) -> dict:
    """An admin account, matching what the app grants the first signup."""
    return _make_account(_password_hash, "admin", is_admin=True)


@pytest.fixture
def member(_password_hash: str, admin: dict) -> dict:
    """A second, non-admin account. Depends on `admin` so it is never first."""
    return _make_account(_password_hash, "member", is_admin=False)


@pytest.fixture
def other_user(_password_hash: str, admin: dict) -> dict:
    """A third account, for 'some unrelated user' permission checks."""
    return _make_account(_password_hash, "other", is_admin=False)


# ── Domain helpers ────────────────────────────────────────────────────────────


@pytest.fixture
def make_book(client: TestClient):
    """Create a book via the API and return the response body."""

    def _make(headers: dict[str, str], **overrides) -> dict:
        payload = {"title": "Test Book", "author": "Test Author"} | overrides
        res = client.post("/api/books", json=payload, headers=headers)
        assert res.status_code == 201, res.text
        return res.json()

    return _make


@pytest.fixture
def user_count(db) -> int:
    return db.query(User).count()
