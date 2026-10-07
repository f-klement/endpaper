"""Shared fixtures.

The application modules read their configuration at import time (DATA_DIR is
resolved once, and database.py builds the engine on import), so the environment
has to be pointed at a throwaway directory *before* anything imports them. That
is what the module-level block below does. It must stay above any application
import in the test suite.
"""

import atexit
import contextlib
import datetime
import hashlib
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from hypothesis import settings as hypothesis_settings

# ── The register this session checks, read before this session does anything ──
#
# **As early in this file as it can be, and that is the whole reason it is
# here rather than beside the rule it serves.** `_refuse_a_rewritten_register`
# compares this reading against one taken at the end, so everything between
# the two is covered and everything before the first is not. Taken from
# `pytest_sessionstart` the window held every `pytest_configure` and this
# file's own module scope, so a self heal written four lines above the rule
# forbidding it reddened nothing.
#
# **It is also what puts the reading in every process.** A hook gated to the
# controller leaves a worker's copy of the global unset, so the arm that
# witnesses the arming ran in a worker and read a different copy from the one
# the refusal reads. Module scope runs wherever this file is imported, which
# is both.

#: `COVERAGE.md`, which this session checks and must not write.
_REGISTER = Path(__file__).resolve().parent / "COVERAGE.md"


def _register_reading(path: Path | None = None) -> str:
    """The document as one short string, or the word for not having one.

    Size beside the digest because a refusal naming two hashes says a file
    moved and nothing else, and the direction is usually the first question.

    **The module global is read here rather than defaulted into the
    signature.** A default is evaluated once, when this file is imported, so
    the arm that drives this against a document of its own would have been
    comparing two readings of the real register and finding them equal.
    Measured: the refusal never fired and the arm reported a pass.
    """
    target = _REGISTER if path is None else path
    if not target.exists():
        return "absent"
    content = target.read_bytes()
    return f"{len(content)} bytes, {hashlib.sha256(content).hexdigest()}"


#: That document as this process first saw it. Never `None` in a live run;
#: the refusal treats `None` as a guard somebody removed rather than as a
#: reason to pass.
_REGISTER_WAS: str | None = _register_reading()

# ── What the property based tests are allowed to spend ────────────────────────
#
# **The budget is the constraint the property tests were designed around, not a
# detail of them.** Hypothesis costs per example where every other test here
# costs per test, so the number below is what decides whether the suite stays
# inside the time the rest of the tree was sized for.
#
# **Two profiles, and a bare run loads the smaller one.** `suite` is what every
# run pays; `thorough` is for the run somebody starts on purpose when a property
# is suspected to be false and the suite has not found it.
# `HYPOTHESIS_PROFILE=thorough` selects it, and so does hypothesis's own
# `--hypothesis-profile thorough`, which wins over this and is why the budget
# guard counts what ran rather than reading the name below.
#
# **`database=None` is the one setting whose reason is local to this file.**
# Hypothesis's example database is a directory, and every xdist worker here is a
# separate process that would write to it, so turning it off is also what keeps
# them from contending over one. What it costs, and why `deadline` and the seed
# are set the way they are, is one decision with one home: see "Property based
# tests run in the ordinary suite, and the budget is a test rather than a
# number" in docs/decisions.md.
#
# The floor under these numbers, and the two guards that keep them honest, are
# in `tests/test_property_budget.py`. A number here with no guard on it is a
# number somebody can quietly drop to 1.

#: Every profile this tree registers, and what one property costs under it.
#:
#: One table rather than a call per profile, so the guard can walk the names
#: instead of being given a list of them that drifts.
PROPERTY_PROFILES: dict[str, int] = {"suite": 200, "thorough": 2_000}

for _profile, _examples in PROPERTY_PROFILES.items():
    hypothesis_settings.register_profile(
        _profile,
        max_examples=_examples,
        database=None,
        deadline=None,
        print_blob=True,
    )

#: Which of them this run is using. An unknown name is an error from
#: `load_profile`, which is the right answer: a typo that silently ran the
#: small profile would be a deep run nobody got.
ACTIVE_PROPERTY_PROFILE = os.environ.get("HYPOTHESIS_PROFILE", "suite")
hypothesis_settings.load_profile(ACTIVE_PROPERTY_PROFILE)

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


def _database_url() -> str:
    """SQLite unless something asked, out loud, for the other engine.

    **`ENDPAPER_TEST_DATABASE_URL` and not `DATABASE_URL`**, which is the same
    rule the `_ENV_OVERRIDES` loop below applies to every other setting: a value
    in the shell that happens to run the suite must not silently decide what the
    suite runs against. This name exists for one caller, the pipeline's
    `test:postgres` job, and a developer who exports it has said which engine
    they meant.

    **One database per xdist worker.** The workers share nothing else: each gets
    its own `mkdtemp` directory and, on SQLite, its own file. Against one server
    they would share a schema, and `clean_database` empties every table between
    tests, so worker two would delete worker one's rows mid test. The name is
    derived from `PYTEST_XDIST_WORKER` and the database is created here, before
    `main` is imported and runs the chain into it.

    **Created and checked through `scripts/postgres_database.py`, which the
    pipeline also calls.** A bare `CREATE DATABASE` here inherits whatever
    `template1` on that server carries, and the collation is what a POSIX bracket
    range in a CHECK constraint is read against, so a worker database made any
    other way is a database the charset rules were never measured on.
    """
    asked = os.getenv("ENDPAPER_TEST_DATABASE_URL")
    if not asked:
        return f"sqlite:///{_TMP_DATA_DIR / 'test.db'}"

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sqlalchemy.engine import make_url

    from scripts.postgres_database import create_if_absent, wrong_locale

    url = make_url(asked)
    worker = os.getenv("PYTEST_XDIST_WORKER")
    if worker:
        url = url.set(database=f"{url.database}_{worker}")
        create_if_absent(asked, str(url.database))
    rendered = url.render_as_string(hide_password=False)
    wrong = wrong_locale(rendered)
    assert wrong is None, f"{url.database} is not a database this schema was measured on: {wrong}"
    return rendered


os.environ["DATABASE_URL"] = _database_url()
# Durability is meaningless for a database dropped after every test, and the
# fsync it buys was most of this suite's runtime. See database._synchronous.
os.environ["SQLITE_SYNCHRONOUS"] = "OFF"

# **Unset rather than set, and by hand, which here is the exception and not the
# pattern.** `database.py` refuses either of these beside a URL that is not
# Postgres, and this suite's URL is SQLite unless one job asks otherwise. So a
# developer with one exported in their shell gets a collection error in every
# module that imports the database, carrying a message that is correct for a
# deployment and misleading here: it names a variable this file owns and they
# cannot change.
#
# **The two loops below derive their names and each says why a hand list goes
# stale. This is a hand list.** It stays one because the derivation that would
# replace it is wrong rather than merely unwritten: the population is the names
# `config.py` reads with a direct `os.getenv`, and popping all of them would pop
# `DATA_DIR`, `DATABASE_URL` and `SECRET_KEY`, which the lines above set on
# purpose. Add a name here when a direct read gains one the suite must not see.
for _unset_for_the_suite in ("DATABASE_SSL_MODE", "DATABASE_SSL_ROOT_CERT"):
    os.environ.pop(_unset_for_the_suite, None)

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

# **The same trap, for the credential feature's own variables**, and it needs
# its own loop because they are not settings rows: `_ENV_OVERRIDES` is keyed by
# `SettingKey`, and a catalogue credential is keyed by a target row.
# `credentials.ENV_VARIABLES` is read rather than restated, so a variable added
# there is disarmed here the moment it is added, and the per-source pins are
# generated from the same function the application uses.
import credentials  # noqa: E402
from enums import CatalogueSource, VerificationProvenance  # noqa: E402

for _key_variable in credentials.ENV_VARIABLES:
    os.environ.pop(_key_variable, None)
for _source in CatalogueSource:
    os.environ.pop(credentials.env_variable_name(_source.value), None)

# **No test may touch the machine's real keychain**, and on a developer's laptop
# one exists. `generate_key` writes, so without this a run would put a key into
# somebody's login keyring and `_from_keychain` would read whatever was already
# there, which is the vacuous pass above wearing a different hat. The failing
# backend is what a container has anyway; a test that wants a keychain installs
# a fake one with `keyring.set_keyring`.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"

# Every test that wants one sets it for itself with `monkeypatch.setenv`, which
# is unaffected by this.

from fastapi.testclient import TestClient  # noqa: E402

import accounts  # noqa: E402
import covers  # noqa: E402
import main  # noqa: E402
import metadata  # noqa: E402
import ratelimit  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402
from models import User  # noqa: E402
from tests.helpers import cover_resolver  # noqa: E402

# ── Moving the process off UTC, for anything that writes or reads a day ──────
#
# **Shared rather than per file, because the arm that needs it most is not the
# one that looks like it needs it.** A value written in the host's local frame
# and a value written in UTC are the **same string** on a process at UTC, and
# the pod this suite runs in sets no zone on an image carrying no zone data.
# So an arm that checks a stored timestamp's frame is inert there unless it
# moves the process first: measured, the defect of record planted back into
# `backup.build_archive` reddened nothing until the arm requested the fixture
# below. The development host is an hour east, which is why the same arm is
# armed on the one machine this repository forbids running a suite on.
#
# `tests/test_downloads.py` and `tests/test_backup.py` both use it.

#: A POSIX offset string and **not** a zone name, deliberately.
#:
#: `time.tzset` resolves a name such as `Asia/Tokyo` out of the zoneinfo
#: database, and a name it cannot resolve **silently becomes UTC**: measured,
#: `Area/Nowhere` gives an offset of zero and raises nothing. A zone name
#: would therefore make every arm below depend on files being installed in
#: whatever image it runs in, and the failure would be silent. A POSIX string
#: is read by the C library alone. The sign is inverted in that notation:
#: `-9` is nine hours **east**.
NINE_HOURS_EAST = "JST-9"

#: The offset `NINE_HOURS_EAST` must produce, asserted rather than assumed by
#: anything that wants to know the zone really moved.
NINE_HOURS = datetime.timedelta(hours=9)

#: A fixed instant to read an offset at, so the reading never depends on when
#: the suite ran or on a daylight saving boundary.
_A_FIXED_INSTANT = datetime.datetime(2026, 3, 13, 15, 30, tzinfo=datetime.UTC)


@contextlib.contextmanager
def at_zone(tz: str) -> Iterator[None]:
    """Run the body at `tz`, and put the variable and the C library back.

    **Both, because they are separate state.** The variable is what a later
    reader sees; the C library holds the parsed zone until something calls
    `tzset`. Putting one back without the other leaves them disagreeing.

    **`TZ` is kept out of `monkeypatch` on purpose.** A fixture's teardown
    runs before `monkeypatch`'s undo, since finalisers run in reverse setup
    order and `monkeypatch` is set up first, so `monkeypatch.setenv("TZ", ...)`
    restores the variable **last** and calls no `tzset`, leaving the library on
    whatever the teardown left. Measured with the host setting `TZ` to an
    offset its system zone does not share: the environment came back five
    hours east while the library was on the system zone, for every later test
    in that worker. A host that sets no `TZ` hides it, which is why it
    survived a green suite.

    **`time.tzname` is the witness and the offset alone is not**, because the
    two C libraries this runs on disagree about the variable after it changes.
    Measured on one instant, popping `TZ` and deliberately not calling
    `tzset`: the development host keeps the parsed zone and answers nine hours
    east, while the suite's container re-reads the variable and answers zero.
    An offset check is armed on one and **inert on the other**, and that plant
    took a container run green. `tzname` reported the stale zone on both.
    """
    before = os.environ.get("TZ")
    before_zone = time.tzname
    before_offset = _A_FIXED_INSTANT.astimezone().utcoffset()
    os.environ["TZ"] = tz
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()
        assert os.environ.get("TZ") == before, "this left TZ changed for every later test"
        assert (time.tzname, _A_FIXED_INSTANT.astimezone().utcoffset()) == (
            before_zone,
            before_offset,
        ), (
            "the variable was put back and the C library was not, so the two now "
            "disagree and every later test in this worker reads the wrong zone"
        )


@pytest.fixture
def east_of_greenwich() -> Iterator[None]:
    """Put the process nine hours east for one test."""
    with at_zone(NINE_HOURS_EAST):
        yield


# ── The session's own denominator, reconciled on the controller ───────────────
#
# **A verdict is a claim about a denominator, and this session had none.** The
# summary line counts what ran. Nothing anywhere compared it with what was
# collected, so a session that lost tests reported a smaller number rather than
# a failure.
#
# Measured on this base under `-n 2 --dist loadfile`, with one test killing its
# own worker mid file:
#
# | arrangement | report entries | collected | never ran | anything said so |
# |---|---|---|---|---|
# | worker restarts at their default | 35 | 31 | 5 | no |
# | `--max-worker-restart=0` | 16 | 31 | 15 | no |
#
# The default arrangement is worse than a silent reduction: under `--dist
# loadfile` the crashed item goes back on the queue, the replacement worker dies
# on it too, and a reader who checks the count sees it go **up**.
#
# **This is also what makes an existing comment true.** The note over
# `_WAITED_PAST_EVERY_DEADLINE_SECONDS` in
# `tests/routers/test_books_identifier_backfill.py` says a test that hangs is
# worse than one that is missing, because a missing one is visible in a count.
# It was not. The coverage register's census, which is the count a reader would
# reach for, builds its population from collection, and collection is complete
# before anything runs, so it is green on exactly the failure that sentence
# claims it would catch. No claim is made here about what else in the tree
# counts; what is checked is stated below.
#
# The per test ceiling in `pyproject.toml` bounds the hang. This bounds
# everything else that loses a test, and it is the half that makes the ceiling
# safe to get wrong: a ceiling set too high still ends in a named refusal rather
# than in a job timeout naming nothing.
#
# `tests/test_a_hung_test_is_named.py` is the guard over both halves.

#: Every nodeid this session collected, in collection order.
_COLLECTED: list[str] = []

#: Which hook supplied that population.
#:
#: **An empty population with tests reported is a check that was never armed**,
#: which is the shape this repository pays for: a guard whose arming is data
#: disarms with no diff and no tell. So the source is recorded and the empty
#: case is a refusal below rather than a silent pass.
_COLLECTED_FROM = "nothing"

#: Every nodeid that produced at least one terminal report.
_REPORTED: set[str] = set()

#: How many missing nodeids to name before summarising the rest. A truncated
#: session can be missing thousands, and a wall of them buries the count that
#: says how bad it is.
_MISSING_NAMES_SHOWN = 20

#: Whether a given exit status is a claim about the whole collection.
#:
#: **One partition over every member of `pytest.ExitCode`, refused at import
#: when a member is classified nowhere**, so a pytest that grows a status
#: reddens here instead of joining the reconciled set unnoticed.
#:
#: **This is half the exemption and not all of it**, and the half it is not was
#: bought by getting this wrong. An early stop does **not** reliably arrive as
#: `INTERRUPTED`: `-x` and `--maxfail` set `session.shouldfail`, which raises
#: `Session.Failed` and lands on `TESTS_FAILED`, so keying on the status alone
#: refuses the ordinary debugging run. `pytest_sessionfinish` below therefore
#: asks the session's own stop state **first**, and this table second. What each
#: one catches that the other does not is measured beside that check.
#:
#: What this table is for is the shape the ceiling exists for: the truncation
#: exits `TESTS_FAILED` with no stop flag set, because the crash items are real
#: failures, so it is reconciled rather than exempted.
_CLAIMS_THE_WHOLE_COLLECTION: dict[pytest.ExitCode, bool] = {
    pytest.ExitCode.OK: True,
    pytest.ExitCode.TESTS_FAILED: True,
    # **Classified but unreachable here, and the difference is the point.** The
    # terminal reporter sets this one inside its own `pytest_sessionfinish`
    # **hookwrapper, after the yield**, so every non wrapper implementation
    # including the one below has already run and been handed the status the
    # session had before it. Measured: `--max-warnings=1` over three passing
    # tests gives a process exit of 6 and an `exitstatus` of **0** at this hook.
    # Such a run is therefore reconciled, under `OK`, and never under this.
    #
    # It stays classified because the partition has to be total, and True is
    # what it would mean: the run completed. The first draft of this comment
    # claimed the hook receives it, which was the process exit code read as the
    # hook's argument. The code was right and the reason was the wrong shape.
    #
    # What the partition did buy is real and is not this: it refused at import
    # on a member no design document for this change knew about.
    pytest.ExitCode.MAX_WARNINGS_ERROR: True,
    # Stopped on purpose before the end: `-x`, `--maxfail`, a bare
    # `pytest.exit(reason)`, an interrupt. Short by request, and the caller
    # already knows.
    pytest.ExitCode.INTERRUPTED: False,
    # The run is not a verdict about anything.
    pytest.ExitCode.INTERNAL_ERROR: False,
    pytest.ExitCode.USAGE_ERROR: False,
    # Nothing was collected, so the two numbers agree at zero anyway.
    pytest.ExitCode.NO_TESTS_COLLECTED: False,
}

_UNCLASSIFIED_EXIT_CODES = set(pytest.ExitCode) - set(_CLAIMS_THE_WHOLE_COLLECTION)
if _UNCLASSIFIED_EXIT_CODES:
    raise RuntimeError(
        "this file partitions every pytest exit status into one that claims the "
        "whole collection and one that does not, and this pytest carries a status "
        f"it classifies nowhere: {sorted(code.name for code in _UNCLASSIFIED_EXIT_CODES)}"
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    """Take the population from the session, which is the path with no xdist.

    **After the whole of `pytest_collection_modifyitems`, rather than last
    inside it.** `trylast` orders an implementation only among the **non
    wrapper** ones, and the cache plugin registers that hook as a
    `wrapper=True, tryfirst=True` which applies the `--lf` deselection **after**
    the yield, so after every non wrapper implementation however late it asks to
    be. Measured under `-n 0 --lf` with one cached failure: taken in
    `modifyitems` the population is the whole file and the session runs one
    test, which is a false refusal naming the rest; taken here it is one and
    one. A `-k` filter is deselected in a non wrapper implementation and was the
    half `trylast` won, which is why the first version looked correct.

    **This is also where xdist takes the ids it sends**, so the two arms now read
    one definition of what was collected instead of two that can disagree.

    Under xdist this fires in each worker and **not on the controller**, which
    bypasses collection entirely. Measured: the controller records zero calls to
    this hook. The worker's copy is never read, because the reconciliation
    returns early there.

    **Guarded on there being items**, so a session that collected nothing leaves
    the source at its initial value rather than claiming to have filled the
    population with nothing.
    """
    global _COLLECTED_FROM
    if not _COLLECTED and session.items:
        _COLLECTED.extend(item.nodeid for item in session.items)
        _COLLECTED_FROM = "the session"


def pytest_xdist_node_collection_finished(ids: list[str]) -> None:
    """Take the population from the first worker to report its collection.

    Every worker collects the whole suite and the controller refuses a run whose
    workers disagree, so the first one is the session's population. Deselection
    is applied before this fires: measured under `-n 2 -k`, collected and
    reported agree at ten.

    **Naming a hook xdist owns is what keeps this arm armed.** With the plugin
    gone pytest refuses an unknown hook rather than running with this population
    empty, which is the same self enforcing shape as `-n 2` living in `addopts`.
    """
    global _COLLECTED_FROM
    if not _COLLECTED:
        _COLLECTED.extend(ids)
        _COLLECTED_FROM = "xdist"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Tick a nodeid off as having reported at all.

    Setup, call and teardown each arrive here, and a test that errors in setup
    or is skipped still reports. What never arrives is a test whose worker died
    while holding it, and a test the session never dispatched.
    """
    _REPORTED.add(report.nodeid)


def _refuse_the_short_session(session: pytest.Session, lines: list[str]) -> None:
    """Say it where a reader will see it, and make the status say it too.

    The terminal reporter is asked for by name rather than written to directly,
    because `addopts` carries `-q` and a bare print at session finish lands
    among the dots. Without a reporter, which is a run with `-p no:terminal`,
    stderr still carries it.
    """
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    for line in lines:
        if reporter is None:
            print(line, file=sys.stderr)
        else:
            reporter.write_line(line)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _refuse_a_rewritten_register(session: pytest.Session) -> None:
    """Refuse a run that wrote the document it was checking.

    **A guard that heals itself asserts nothing**, so the figures a run takes
    for `COVERAGE.md` are printed for a separate and deliberate invocation to
    apply, and nothing in the suite opens that file for writing. This is what
    makes that true rather than what says it.

    **Closed over the mechanism, not over the spelling.** A rule forbidding one
    way of writing a file is a list of the ways somebody has thought of, and
    the next one is written by somebody who has not read the list. Comparing
    the bytes either side of the run makes a write from a test, from a fixture,
    from a plugin or from a hook one failure with one name.

    **What it does not see, which is three things and not two.** A write that
    lands after this call. A write by a process this run did not start. And a
    write that lands **before** the baseline reading, which is why that
    reading is taken at this file's module scope rather than from a session
    hook: a hook runs after every `pytest_configure`, so a self heal written
    four lines above this rule would have reddened nothing.

    **Not even module scope closes the third**, and the sentence claiming any
    of them unreachable is deleted rather than narrowed. What is left is this
    file's own lines above the reading, and the import time code of any
    plugin pytest loads before a conftest. The window is as early as this
    file can make it and it is not empty.

    The frontend register carries the same rule in its own global setup,
    because a lesson learned in one half of a rule does not travel to the
    other.
    """
    now = _register_reading()
    if _REGISTER_WAS is None:
        # **A refusal, never a quiet return.** The reading is taken
        # unconditionally at module scope, so this state means somebody
        # removed it, and a guard that is not armed reporting a pass is the
        # whole failure this file is about. `test_coverage_register_writer`
        # blanks the global and drives this.
        _refuse_the_short_session(
            session,
            [
                f"this run never read {_REGISTER.name} before it began, so it "
                "cannot say whether it wrote one. That reading is taken at "
                "the module scope of this file and nothing makes it optional, "
                "so its absence is a guard that has been removed.",
            ],
        )
        return
    if now == _REGISTER_WAS:
        return
    _refuse_the_short_session(
        session,
        [
            f"{_REGISTER.name} changed while the run that checks it was "
            f"running, from {_REGISTER_WAS} to {now}. A run must not write the "
            "register it is checking: what a run measures is printed, and "
            "applying it is a separate invocation somebody makes on purpose.",
        ],
    )


#: Every nodeid this run dropped after collecting it.
#:
#: **One cause agnostic hook rather than a list of flags.** `-k`, `-m`,
#: `--deselect`, `--lf`, `--ff` and `--sw` all reach `pytest_deselected`, and
#: pytest's own hookspec requires a plugin dropping items to call it, so this
#: is not the enumeration the register's gate refuses.
_DESELECTED: list[str] = []


def pytest_deselected(items: list[pytest.Item]) -> None:
    _DESELECTED.extend(item.nodeid for item in items)


@pytest.fixture
def deselected_items() -> list[str]:
    """What this run dropped after collecting it, for the register's guard.

    **The register's file set gate cannot see a narrowing inside a file.** A
    `-k` leaving at least one test in every file changes no file's
    membership, so that gate opens and the count arms red on figures that are
    floors. That was loud and wrong, which is the cheaper direction, until
    those same two arms began printing a write: loud and wrong became loud,
    wrong and applicable by a tool that has no question to ask. This is what
    the write is withheld on.
    """
    return list(_DESELECTED)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Refuse a session that reported fewer tests than it collected.

    Named, so the refusal says which tests went missing rather than leaving a
    reader to diff two counts they do not have.
    """
    config = session.config
    if not hasattr(config, "workerinput"):
        # **Asked on the controller only, and that is not a narrowing.** The
        # register is one file every worker shares, so the controller's own
        # two readings span the whole run whichever process did the writing.
        # Asking in a worker as well would report the same fault once per
        # worker and leave each of them setting a status xdist does not read.
        #
        # **Before the reconciliation below, which returns early three ways.**
        # A run that rewrote the register has nothing to say about it however
        # it ended.
        _refuse_a_rewritten_register(session)
    if hasattr(config, "workerinput"):
        # An xdist worker. It collects the whole suite and runs a slice of it,
        # so its own denominator is short by construction and says nothing about
        # the session's. Without this the check fires in every worker on every
        # green run.
        return
    if config.option.collectonly:
        # Nothing was dispatched, so there is nothing to reconcile. Measured:
        # `--collect-only` exits OK carrying the full population and no reports,
        # which is a false refusal without this line.
        return
    if session.shouldfail or session.shouldstop:
        # **Stopped early on purpose, said by the session rather than by a
        # status.** `-x` and `--maxfail` set `shouldfail`; `--stepwise` sets
        # `shouldstop`. Each is assigned at exactly one site in the
        # distribution, neither is ever unset, and both are still true here.
        #
        # This is the instrument the status cannot replace. Measured on a five
        # test project, reading what this hook is handed: `-n 0 -x` arrives as
        # `TESTS_FAILED` with four tests unreported, so a status only rule
        # refuses the ordinary debugging run, and `--pdb` forces `-n 0`, so that
        # run is the reachable one rather than a corner. Under xdist the same
        # stop arrives as `INTERRUPTED`, which is the distributor re-raising and
        # not a property of stopping early. Asking the session makes the two
        # paths answer the same way.
        #
        # **Residue, and it is the price of this exemption rather than a fault
        # in it.** A genuine loss that shares a run with a deliberate stop is
        # swallowed here: measured, `-x` with a real failure **and** a test
        # dropped before it could report is silent under both `-n 0` and
        # `-n 2`, and that drop is exactly the shape this whole check exists
        # for. The version keyed on the status alone had the same hole, and
        # this one is **strictly wider**, because it also covers the failure
        # status with the flag set. Closing it needs a per item account of why
        # each test went unreported, which is a different mechanism rather than
        # a further condition here.
        return
    try:
        status = pytest.ExitCode(exitstatus)
    except ValueError:
        # A status pytest does not define, which `pytest.exit(reason,
        # returncode=N)` produces **only for an N outside the enum**. One
        # inside it is an ordinary status and reaches the table below, which
        # is the case the two comments about that call used to argue past
        # between them.
        return
    if not _CLAIMS_THE_WHOLE_COLLECTION[status]:
        # **And the status is the instrument the stop flags cannot replace**,
        # which is why both are here and neither was enough. Measured: an
        # interrupt, and a **bare** `pytest.exit(reason)` from inside a test,
        # set neither flag and arrive as `INTERRUPTED` with the rest of the
        # session unreported. Dropping this check for the flags alone turns
        # every `Ctrl-C` into a wall of names.
        #
        # **The claim is narrow on purpose, because the same call given a
        # `returncode` is a different thing.** `pytest.exit(reason,
        # returncode=1)` sets no flag either and arrives as `TESTS_FAILED`, so
        # it is reconciled and a loss inside it is refused by name. That is the
        # reachable middle between this branch and the `ValueError` one above,
        # and reading it as an ordinary run of the status it names is what a
        # caller choosing a status is asking for. Nothing in this tree calls it.
        return

    if not _COLLECTED and _REPORTED:
        _refuse_the_short_session(
            session,
            [
                f"endpaper reconciliation: {len(_REPORTED)} tests reported against an "
                "empty collected population, so nothing was reconciled: neither "
                "population hook fired",
            ],
        )
        return

    missing = [nodeid for nodeid in _COLLECTED if nodeid not in _REPORTED]
    if not missing:
        return

    shown = missing[:_MISSING_NAMES_SHOWN]
    lines = [
        f"endpaper reconciliation: collected {len(_COLLECTED)} from {_COLLECTED_FROM}, "
        f"{len(_REPORTED)} reported, {len(missing)} produced no report at all",
        *(f"endpaper reconciliation: missing {nodeid}" for nodeid in shown),
    ]
    if len(missing) > len(shown):
        lines.append(f"endpaper reconciliation: and {len(missing) - len(shown)} more")
    _refuse_the_short_session(session, lines)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """Say which filesystem the databases went to.

    **`_fastest_scratch()` falls back silently, and silent is the whole
    problem.** A run that cannot use `/dev/shm` still passes, still reports
    nothing, and differs only in how long it takes, which is the one signal
    nobody reads off a green pipeline. So one line per run, which turns "this
    suite is slow here" from something somebody has to go and measure into
    something the log already says.

    **Not `pytest_report_header`, and not a `write_line` from
    `pytest_configure`.** Both were tried and neither reaches a CI log here:
    `addopts` carries `-q`, which drops the header outright, and at configure
    time the reporter has not started writing. The summary hook is the one
    place that prints under this project's own settings. A diagnostic invisible
    under the settings it ships with is the same defect it exists to report.
    """
    where = _TMP_DATA_DIR.parent
    kind = "tmpfs" if str(where) == "/dev/shm" else "DISK, /dev/shm unavailable"
    terminalreporter.write_line(f"endpaper scratch: {where} ({kind})")


@pytest.fixture(scope="session")
def _schema_once() -> None:
    """The backstop under the schema, which builds nothing on a normal run.

    **The suite's database is the migrations'.** `main.py` calls `init_db()` at
    module level and `init_db` calls `upgrade_to_head()`; this file imports
    `main` above, so Alembic has built every table before any fixture runs and
    `create_all` finds them all present and does nothing. A `CheckConstraint` in
    `models.py` is therefore a **description** of the revision that installs it,
    and not a second enforcement of it.

    **This docstring is where that fact is explained.** It was written backwards
    here while two test files asserted it correctly, and the contradiction
    survived because nobody read the two against each other. Elsewhere the fact
    is pointed at rather than re-explained, except where a class states the
    consequence for its own cases.

    **It stays because of what it turns a broken premise into**, and the
    assertion below is what makes that true. Were the import order ever to
    change, this would build the models' schema instead and the suite would run
    green against a schema no deployment carries; refusing here says which
    fixture built what, rather than leaving a thousand `no such table` errors
    with no diagnosis.

    **Asserted by counting tables either side of the call, not by trusting the
    stamp.** `alembic_version` is not in `Base.metadata`, so a schema dropped and
    rebuilt from the models keeps a stamp at head and reads as migrated: found
    by two review seats independently on 2026-09-11, each with a mutation the
    other had not written. `tests/test_house_rules.py::TestEveryEnumColumnIs
    ConstrainedOrExemptWithAReason` holds the stamp and the source shape, and
    `tests/test_schema.py::TestTheSchemaTheApplicationBootsIsTheRevisions`
    compares two boots, which is the arm a module writing its own DDL was
    outside. No one of the four is the premise on its own.

    **What this one says is that THIS call built nothing.** It says nothing
    about a schema rebuilt from the models between the read above and the call
    below, which is a mutation of this fixture rather than of the suite around
    it, and nothing about one rebuilt after it: a revision doing so is covered by
    the source arm instead.

    Session scoped rather than per test: each xdist worker is a separate process
    with its own `mkdtemp` directory and its own database, a file on SQLite and
    one created by `_database_url` on Postgres, so this runs once per worker and
    they cannot collide.
    """
    from sqlalchemy import inspect as reflect

    before = set(reflect(engine).get_table_names())
    Base.metadata.create_all(bind=engine)
    built = set(reflect(engine).get_table_names()) - before
    assert not built, (
        f"`create_all` built {sorted(built)}, so the suite's schema is not the "
        "migrations'. Every rule comparing what models.py declares against what a "
        "database installs is then comparing the declaration with itself."
    )


@pytest.fixture(autouse=True)
def clean_database(_schema_once: None) -> None:
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

    Ids still restart at 1 **on SQLite**, which the `covers_dir` fixture depends
    on, because nothing here uses `AUTOINCREMENT`: SQLite reuses the highest free
    rowid, and an empty table has none taken. **Postgres does not**, measured:
    eighteen columns there default to `nextval(...)` and a DELETE does not touch
    a sequence. So every case that reads a literal id is a case that runs on one
    engine, which is why the pipeline's Postgres job selects rather than running
    the suite.
    """
    _empty_and_reseed()


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


def forget_any_encryption_key() -> None:
    """Remove the key file, wherever `CREDENTIAL_ENCRYPTION_KEY_FILE` points now.

    **`missing_ok` is not "do not raise", and that is the whole of this
    function.** It swallows `FileNotFoundError` and nothing else, so a key path
    whose parent is a regular file raises `NotADirectoryError`, and a test
    pointing it somewhere unreachable is exactly what
    `test_a_place_no_file_can_go_is_reported_rather_than_raising_an_oserror`
    does. Between them the two cover the whole of "there is no key here": the
    file is absent, or the directory it would be in is not a directory.

    **`NotADirectoryError` and not `OSError`, because the reason only holds for
    the reachable cases.** "A path this cannot reach holds no key" is true of
    these two and false of `PermissionError` and `IsADirectoryError`, which say
    the path **is** reachable, a key may be sitting on it, and the removal
    failed. Suppressing those would break the fixture's own first line, "No key
    survives a test, in either direction", and report nothing.
    """
    with contextlib.suppress(NotADirectoryError):
        credentials.key_file().unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def forget_the_encryption_key() -> Iterator[None]:
    """No key survives a test, in either direction.

    `DATA_DIR` is a temporary directory shared by the whole worker, so a key
    generated by one test is in force for every test after it: the next one
    would find a key it did not create and, worse, one that opens credentials it
    knows nothing about. Cleared before as well as after, because a test that
    fails part way through leaves one behind.

    **Whether this runs before or after a `monkeypatch` undo is not this
    fixture's to know**, which is why the work is behind a name that can be
    called directly: it read a key path still pointing under a regular file once,
    and the arrangement that put it there was an unrelated autouse fixture in
    this file taking `monkeypatch`.
    """
    forget_any_encryption_key()
    yield
    forget_any_encryption_key()


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    """Clear every rate-limit counter between tests.

    They are process-global and deliberately survive requests, so without this
    a test that logs in or imports repeatedly would start tripping the limiter
    partway through the suite, and which test failed would depend on ordering.
    The import limiter was added after this fixture and its absence turned
    twelve unrelated import tests red, every one of them passing on its own.

    **Membership is a property, not a list**: whatever is bound in
    `ratelimit`'s namespace and is a `SlidingWindowLimiter`. Naming them here
    is what let the import limiter go missing, and a list cannot close a class
    that grows.

    Two things it does not reach: a limiter another module constructs for
    itself, and one `ratelimit` holds inside a container rather than binding to
    a name. The second is **loud** rather than merely stated, because
    `tests/test_ratelimit.py` counts names bound against limiters constructed
    and a container makes those two disagree. The first is unwatched.
    """
    for limiter in list(vars(ratelimit).values()):
        if isinstance(limiter, ratelimit.SlidingWindowLimiter):
            limiter.reset()


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
def refuse_unmocked_network() -> Iterator[None]:
    """No test reaches the internet, whether or not it remembered to say so.

    **The suite had no such rule and it was one handler away from mattering.**
    Every outbound call in this app went through a handler that a test either
    wrapped in `respx.mock` or never triggered, so forgetting one was
    theoretical. `POST /authors/identifiers` then grew a lobid request, and
    **seven** existing tests that had never made one began making a real one: on
    a machine with no route they timed out, and on one with a route they would
    have reached a national library from a unit test.

    That seven is measured rather than counted by eye, and the eye was wrong.
    Nine tests call `confirm()` with no router of their own; making
    `authority.resolve` raise on entry and reading the failures back showed that
    two of the nine never get there, one refused at validation and one at the
    author lookup.

    An empty router refuses everything with `AllMockedAssertionError`.

    **It does not make those seven fail, and claiming so was this docstring's
    first draft.** `authority._lobid` catches bare `Exception` and re-raises
    `AuthorityUnavailable`, and the handler treats that as "the file was not
    reachable" and answers 201 with an empty `cross_references`. So the guard
    stops the request; it does not turn a forgotten mock into a red test. What
    it buys is that the suite is hermetic and fast, not that a missing mock is
    announced. A test that needs the call to *happen* still has to say so, and
    the ones added here assert on what came back rather than on a status alone.

    **Nested routers still work**, which is what makes it safe to add under
    hundreds of existing tests: a `with respx.mock(...)` inside a test pushes
    its own router and pops back to this one after. Verified on respx 0.23.1,
    all three ways: a bare request is refused, a nested route answers, and the
    refusal is back once the nested router exits.

    `assert_all_called=False` because this router declares no routes at all and
    the strict form would fail every test for not calling them.
    """
    with respx.mock(assert_all_called=False):
        yield


@pytest.fixture(autouse=True)
def cover_hosts_resolve_to_fixtures() -> Iterator[None]:
    """Every image service resolves to a fixed literal, for every test.

    `covers._client` goes through `fetch.pinned_client`, which resolves the name
    itself. Left alone that is a real DNS lookup of a real image service from a
    unit test, which `refuse_unmocked_network` cannot see: it refuses requests,
    not name lookups. Autouse rather than opt in for the same reason that
    fixture is: the tests reaching this are the many that add a book, not the
    few that are about covers.

    `tests/helpers.py` holds the map, because `silence_covers` registers its
    routes against the same addresses.

    **Sets and restores by hand rather than taking `monkeypatch`, and that is
    not style.** Requesting it here makes this the second autouse fixture in
    this file to do so, which moves when pytest builds the shared `monkeypatch`
    and therefore when it undoes: measured, adding the `monkeypatch` form put
    its undo **after** `forget_the_encryption_key`'s teardown, so that fixture
    read a `CREDENTIAL_ENCRYPTION_KEY_FILE` still pointing under the file
    `test_a_place_no_file_can_go_is_reported_rather_than_raising_an_oserror`
    creates, and `unlink(missing_ok=True)` raised `NotADirectoryError`, which
    `missing_ok` does not cover. One error, in a test this file has nothing to
    do with, from an autouse fixture that only reads a module attribute.

    A test wanting its own resolver still uses `monkeypatch.setattr`, which
    undoes to this value before this restores the shipped one.
    """
    shipped = covers.resolver
    covers.resolver = cover_resolver
    try:
        yield
    finally:
        covers.resolver = shipped


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
def password_hash() -> str:
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
        # Confirmed, because **every path that creates an account stamps one**:
        # registration under a policy that is off, an admin making a test
        # account, a directory sign in, and the migration for every row that
        # already existed. A fixture that skipped it would be the one account
        # shape the application never produces, and would make an unrelated test
        # fail the moment it turned the account policy on.
        # `tests/test_accounts.py` builds an unconfirmed account explicitly where
        # it needs one.
        accounts.record_verification(user, VerificationProvenance.NOT_REQUIRED)
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
def admin(password_hash: str) -> dict:
    """An admin account, matching what the app grants the first signup."""
    return _make_account(password_hash, "admin", is_admin=True)


@pytest.fixture
def member(password_hash: str, admin: dict) -> dict:
    """A second, non-admin account. Depends on `admin` so it is never first."""
    return _make_account(password_hash, "member", is_admin=False)


@pytest.fixture
def other_user(password_hash: str, admin: dict) -> dict:
    """A third account, for 'some unrelated user' permission checks."""
    return _make_account(password_hash, "other", is_admin=False)


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
