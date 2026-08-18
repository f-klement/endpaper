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

# The backend is imported flat ("from models import Book"), the way uvicorn
# imports it with backend/ as the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402
from models import User  # noqa: E402
from ratelimit import login_limiter, register_limiter  # noqa: E402


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
    """Clear the login/registration counters between tests.

    They are process-global and deliberately survive requests, so without this
    a test that logs in repeatedly would start tripping the limiter partway
    through the suite, and which test failed would depend on ordering.
    """
    login_limiter.reset()
    register_limiter.reset()


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
def covers_dir() -> Path:
    from config import COVERS_DIR

    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    return COVERS_DIR


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
        token = create_access_token(user.id, user.username)
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
