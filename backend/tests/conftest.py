"""Shared fixtures.

The application modules read their configuration at import time (DATA_DIR is
resolved once, and database.py builds the engine on import), so the environment
has to be pointed at a throwaway directory *before* anything imports them. That
is what the module-level block below does. It must stay above any application
import in the test suite.
"""

import atexit
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# ── Environment must be set before the app is imported ────────────────────────

def _fastest_scratch() -> str | None:
    """A tmpfs to put the test database on, or None to take the default.

    `/dev/shm` is memory on every Linux container this suite runs in, and the
    default temp directory is the container's overlay filesystem, which is a
    real disk. Every test drops and recreates twelve tables and seeds 105 tags,
    so the run is tens of thousands of writes that are deleted immediately, and
    doing them against a disk is why the suite measured 0.68 cores across two
    workers rather than being CPU bound.

    Falls back silently when the path is missing or not writable, because a
    suite that refuses to run somewhere unusual is worse than one that runs a
    little slower. macOS has no `/dev/shm` and is the case that hits this.
    """
    shm = Path("/dev/shm")
    if not shm.is_dir():
        return None
    try:
        # `mkstemp`, not a path built from the pid. /dev/shm is world writable
        # with the sticky bit, and a pid is guessable, so writing to a
        # predictable name follows a symlink somebody else planted and truncates
        # whatever it points at with the test user's rights. `mkstemp` creates
        # with O_EXCL and answers the same question, which is only ever "can
        # this user write here".
        handle, name = tempfile.mkstemp(dir=shm)
        os.close(handle)
        os.unlink(name)
    except OSError:
        return None
    return str(shm)


_TMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="endpaper-tests-", dir=_fastest_scratch()))


# **Removed at exit.** `_TMP_DATA_DIR` lives on tmpfs, which is RAM, and nothing
# was cleaning it: measured on the development host, eleven leftover directories
# at 180K each, three per run (the controller and two xdist workers) and never
# reclaimed. Harmless per run and unbounded over a day, on a machine that also
# runs etcd. `atexit` rather than a fixture, because it has to fire for the
# controller process too, which owns a directory but runs no tests.
atexit.register(shutil.rmtree, _TMP_DATA_DIR, True)
os.environ["DATA_DIR"] = str(_TMP_DATA_DIR)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DATA_DIR / 'test.db'}"
# Durability is meaningless for a database dropped after every test, and the
# fsync it buys was most of this suite's runtime. See database._synchronous.
os.environ["SQLITE_SYNCHRONOUS"] = "OFF"
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
# The backend is imported flat ("from models import Book"), the way uvicorn
# imports it with backend/ as the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

# **Removed, not defaulted, and every one of them.** A value in the shell that
# happens to run the suite wins over the stored one everywhere `in_force` is
# consulted, so `GET /api/settings` reports the environment's value and any test
# asserting on the stored one is asserting about something it never set.
#
# **That makes a masking test pass vacuously rather than fail**, which is why
# this is a loop over the table rather than a list of names. It read
# `os.environ.pop("GOOGLE_BOOKS_API_KEY", None)` and nothing else, and
# `TestEverySecretSettingIsMasked` had already passed vacuously for that key
# once before the pop was added. The mail and Telegram settings reopened it:
# this deployment's `.env` really does set `MAIL_PASSWORD` and
# `TELEGRAM_BOT_TOKEN`, so with the token exported the walk stores
# `secret-value-N-telegram_bot_token`, the response carries a mask of the
# environment's token instead, and "the stored value is absent" is true whether
# or not anything is masked at all. It would have passed with `mask()` deleted.
#
# Reading `_ENV_OVERRIDES` rather than restating it means a credential added
# there is disarmed here the moment it is added, which is the only version of
# this that stays correct.
for _pinned in config._ENV_OVERRIDES.values():
    os.environ.pop(_pinned, None)

# Every test that wants one sets it for itself with `monkeypatch.setenv`, which
# is unaffected by this.

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


@pytest.fixture(scope="session")
def _schema_once() -> None:
    """Build the schema once per worker, not once per test.

    Each xdist worker is a separate process with its own `mkdtemp` directory and
    its own database file, so this runs once per worker and they cannot collide.
    """
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_database(_schema_once: None) -> Iterator[None]:
    """Empty every table and reseed the predefined tags, on one connection.

    **Deletes rows; does not rebuild the schema.** Measured in the CI pod with
    the database on tmpfs and `synchronous=OFF`: a drop, create and seed costs
    **58.8ms**, this costs **3.1ms**, and it is the difference between a suite
    that spends a third of its time on DDL and one that does not.

    Two designs were rejected to get here, and the reasons are worth keeping.

    **A transaction rolled back per test** is faster still (0.8ms) and was built,
    reviewed and abandoned. It binds every session to one connection through a
    savepoint, and savepoints on a shared connection are **one stack, not one per
    session**: a session that opened its savepoint first and rolls back destroys
    the committed work of every session that committed after it. Measured against
    the real app, that turns a privacy test into a vacuous one, because a test
    asserting "another member gets 404" gets its 404 just as readily when the
    book was never written. It also held a write lock for a whole test rather
    than a statement, and one unguarded `connection.close()` in its teardown
    could wedge an xdist worker for the rest of a run: observed once in thirty,
    as 423 failures and 121 errors.

    **Keeping the seeded tags** rather than reseeding is faster again (1.0ms) and
    is wrong: `backup.restore` deletes and reinserts the tags table and
    `_repair_seeded_tags` rewrites `is_predefined`, so a test can legitimately
    mutate a predefined tag.

    Order matters: children before parents, because the foreign keys are real
    and enforced. `Base.metadata.sorted_tables` is dependency ordered, so
    reversing it deletes children first.

    Ids still restart at 1, which the `covers_dir` fixture depends on, because
    nothing here uses `AUTOINCREMENT`: SQLite reuses the highest free rowid, and
    an empty table has none taken.
    """
    _empty_and_reseed()
    yield


def _empty_and_reseed() -> None:
    """One connection, one transaction, no DDL and no second session.

    `seed_tags()` is not called: it opens its **own** session against the engine,
    which is a second connection, and the whole point of this shape is that the
    reset never needs one. The tags are inserted here from the same list, so a
    tag added to `PREDEFINED_TAGS` reaches the suite without touching this.
    """
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
        # From the metadata, not `Tag.__table__`. A declarative class types that
        # attribute as the wider `FromClause`, which has no `insert`, which is
        # the same trap `backup.py` documents for `delete()`.
        connection.execute(
            Base.metadata.tables["tags"].insert(),
            [
                {"key": key, "name": name, "category": category, "is_predefined": True}
                for key, name, category in main.PREDEFINED_TAGS
            ],
        )


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
