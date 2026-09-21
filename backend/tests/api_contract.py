"""Every operation in the committed schema, asked hostile questions by a generator.

**One hand written class asks this of one route.**
`tests/routers/test_books_bulk.py::TestNoVerbTurnsAValueIntoA500` crosses every
`BulkAction` with a table of hostile values and asserts none of them is a 500. It is
driven off the enum, so it enumerates nothing and an eighth verb is covered the
day it arrives. What it covers is `POST /api/books/bulk`. The sentence its
ticket was written against, that a value nobody bounded is a 500 and nothing is
red, is true of every route that parses a value.

So this module asks the same question of all of them, off the schema rather than
off a list. Two properties, one test each, and no third:

1. **No generated request is a server error.** `not_a_server_error`.
2. **Every response matches the schema that declares it.**
   `response_schema_conformance`. The generated TypeScript client is built from
   the same file, so a divergence here is a frontend defect with a backend cause.

Two tests rather than one, at the cost of a second pass over every operation,
and not for the reason that first suggests itself. A combined failure would be
perfectly readable: `run_checks` runs every check against the response and
hypothesis reports distinct failures together, so both would be named. Two
reasons that do hold. **A server error ends the example before any check runs**,
so in a combined test every example an operation answers that way says nothing
at all about that operation's conformance, and `PATCH /api/books/{book_id}`
answers that way today. And **the verdict this module is read for is per
property over the whole surface**: two results say which of the two properties
the operations are failing, where one says only how many of them are red.

**What this does not cover, stated because a generator invites the opposite
assumption.**

* **The privacy rule.** Whether a member may see a book is decided in
  `shelf.py` and enforced by the four `ast` passes in `tests/test_shelf.py`.
  Nothing here expresses it, and a green run here is not evidence about it.
* **Which status a refusal uses.** An invisible book answers 404 and never 403,
  because a 403 confirms the id exists. `status_code_conformance` is
  deliberately absent from the checks: it asks only whether a status is
  documented, so it would accept either and read as though the rule were
  covered. The rule stays where it is.
* **Anything a recorded reason names.** A generator finds shapes. A defect that
  was found once and reasoned about is pinned in a named test, and this module
  replaces none of them.

**It runs as an ordinary member, never as an admin.** Every interesting failure
on an authorised route is authorisation shaped, and an admin token answers 200
where a member is refused, so an admin run would walk past exactly the responses
worth generating against. The cost is that an admin only route is exercised at
its refusal and not past it, which is the trade taken deliberately.

**It cannot be pointed at anything but this suite's own database**, and that is
structural rather than documented. The generator is handed the in process
application object and no base URL, so there is no address to aim at a
deployment, and `_refuse_a_database_the_suite_did_not_make` refuses at import
unless the engine holds a database `conftest` built for this worker. It
generates writes and one of the verbs is a delete.

**It is a tool rather than a gate, and the file name is what says so.** The
suite collects `test_*.py`; this is `api_contract.py`, so it is collected only
when somebody names it, and it sits in the test tree rather than beside the
other tools because most of what makes it safe is in `conftest.py`: the
throwaway database, the account fixtures, the refusal to reach the network over
HTTP. `refuse_smtp` and `refuse_name_lookups` below are the two parts that are
not, and each says which gap in that refusal it closes.

`schemathesis` is declared in the dev group, so the worker node's ordinary sync
installs it, and this goes to a worker node the way every suite here does rather
than to the development host.

**The invocation is deliberately not written out in `docs/testing.md`**, and the
reason is the publish gate rather than a rule about documents: the wrapper that
takes a run to a worker node lives under a directory the mirror strips, and a
published page may not name one. Nothing stops a reader of this docstring
running the module by naming it.

Making it a gate is one edit: this file is renamed so the collector finds it.
What stands in the way is what it reports. `docs/decisions.md` records the
divergences it finds today, and the ones still open would be a red suite the
moment this is collected.
"""

import collections
import os
import smtplib
import socket
from pathlib import Path
from typing import Any

import pytest
import respx
import schemathesis
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import response_schema_conformance
from sqlalchemy.engine import make_url

import main
from database import SessionLocal, engine
from models import Book
from tests.conftest import _TMP_DATA_DIR

BACKEND = Path(__file__).resolve().parent.parent

#: The committed schema, which is what this module is about.
#:
#: Read from the file rather than from `main.app.openapi()` on purpose. The file
#: is what the client generator turns into TypeScript and what CI diffs against
#: a fresh generation, so it is the artefact a divergence reaches a reader
#: through. `TestTheCommittedSchemaDescribesTheAppUnderTest` holds the two
#: together, which is this module's own premise and is checked rather than
#: assumed.
SCHEMA_PATH = BACKEND.parent / "frontend" / "openapi.json"

#: Examples per operation.
#:
#: **Not the hypothesis profile's number**, which `conftest.PROPERTY_PROFILES`
#: owns and which is sized for one property over one function. There are over a
#: hundred operations here and each example is a request against a real
#: database, so the profile's figure would put this module an order of magnitude
#: above the rest of the suite.
#: `TestTheBudgetIsInForce` measures what actually ran rather than reading this,
#: because `max_examples` is an upper bound that several other things lower.
EXAMPLES_PER_OPERATION = 20

#: The methods an operation can be written under, which is what separates one
#: from the other keys an OpenAPI path item carries (`parameters`, `summary`).
HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _refuse_a_database_the_suite_did_not_make() -> None:
    """Refuse at import unless the engine holds a throwaway database.

    **The threat is not this module, it is the suite around it.** `conftest`
    resolves `DATA_DIR` and `DATABASE_URL` in a module level block above every
    application import, and an import that moves above that block points the
    whole suite at the real database. Everything else in the tree writes a
    handful of rows when that happens. This module generates writes across every
    operation the schema declares, and one of the verbs is a delete.

    So what is accepted is the two shapes `conftest._database_url` can produce: a
    SQLite file inside the scratch directory it removes at exit, or a database
    that same function **created**, per worker, through
    `scripts.postgres_database.create_if_absent`.

    **Restated here rather than imported, and the property is what is checked
    rather than the string.** Calling that function again would create a database
    as a side effect of asking a question. So each arm checks the property that
    makes its shape disposable, and the second arm is the one that needed saying:
    `conftest` appends the worker suffix and creates the database **only when
    `PYTEST_XDIST_WORKER` is set**, and with no xdist it hands the engine the
    asked URL verbatim. A name in `ENDPAPER_TEST_DATABASE_URL` is therefore not
    on its own evidence that anything here made the database, which is why this
    asks for the suffix instead.
    """
    url = engine.url
    # **The arm that covers the failure named above**, and the only one that
    # could: `conftest` sets `DATABASE_URL` after it has decided, and
    # `database.py` builds the engine when it is first imported. An application
    # import above that block therefore leaves the engine on the shell's value
    # and the variable on `conftest`'s, and nothing else in this function can
    # tell the two apart. `make_url` rather than a string compare, because
    # `str(URL)` masks the password and would differ from the variable it is
    # being compared against.
    if url != make_url(os.environ["DATABASE_URL"]):
        raise RuntimeError(
            f"the engine holds {url!r}, which is not the DATABASE_URL conftest set. "
            "Something imported an application module above conftest's environment "
            "block, so the engine was built from whatever the shell carried. This "
            "module generates writes over every operation in the schema, deletes "
            "included."
        )
    if url.get_backend_name() == "sqlite":
        database = Path(url.database or "").resolve()
        if not database.is_relative_to(_TMP_DATA_DIR.resolve()):
            raise RuntimeError(
                f"the engine holds {database}, which is outside the scratch directory "
                f"{_TMP_DATA_DIR} that conftest built and removes at exit. This module "
                "generates writes over every operation in the schema, deletes included, "
                "so it refuses to run against a database nothing is going to throw away."
            )
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    asked = os.environ.get("ENDPAPER_TEST_DATABASE_URL")
    if not asked or not worker or not (url.database or "").endswith(f"_{worker}"):
        raise RuntimeError(
            f"the engine holds the {url.get_backend_name()} database "
            f"{url.database!r}, which is not one conftest created for this worker. "
            "On a server the suite's database is ENDPAPER_TEST_DATABASE_URL with the "
            "xdist worker appended, made by scripts/postgres_database.py; a serial run "
            "is handed the asked URL verbatim, so it is somebody's database rather "
            "than a throwaway. This module generates writes over every operation in "
            "the schema, deletes included."
        )


_refuse_a_database_the_suite_did_not_make()

schema = schemathesis.openapi.from_path(SCHEMA_PATH)
# **The application object, and no base URL.** This is the half of the database
# rule above that no assertion could give: a run against a deployment needs an
# address, and there is none to supply. The transport follows the app, so every
# generated request is served in process by the app `conftest` imported.
schema.app = main.app
# **Off, because this run carries a real token.** Left on, schemathesis fills the
# declared bearer scheme with a generated value, and almost every operation here
# declares that scheme: the run would then measure how the app answers a bad
# token, over and over, and reach no authorised code at all.
schema.config.generation.with_security_parameters = False

#: Requests per property, per operation.
#:
#: **Keyed on the property as well as the operation, because the two properties
#: run the same operations.** One counter summed over both would answer a
#: question about one test with a figure from two, and a budget halved would
#: read as a budget kept.
_requests: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

#: Responses the app produced, over both properties. The complement of
#: `_refused` rather than of `_requests`, which counts attempts.
_answered: collections.Counter[str] = collections.Counter()

#: Responses under 400. The witness that a generated path parameter ever named a
#: row that exists, which nothing else here can see: a 404 is a response and
#: counts as answered.
_reached: collections.Counter[str] = collections.Counter()

#: The suite's own network guard stopping an outbound call before the app could
#: answer, which is the harness rather than a finding, and is counted apart
#: because an operation that only ever refuses has been asked nothing.
_refused: collections.Counter[str] = collections.Counter()

#: Operations a property found a failure on, by where the failure surfaced.
#:
#: Read by `TestTheBudgetIsInForce`, which cannot use those operations:
#: hypothesis replays a failing example while it minimises it, so a red
#: operation's request count is mostly shrinking and says nothing about the
#: budget.
#:
#: **Two sites because the two failures arrive by different routes**, and each
#: has to be checkable on its own: a check failure is a `FailureGroup` out of
#: `validate_response`, and a server error is an exception out of the call
#: before any check has run. A single set is satisfied by either site working.
_failed: dict[str, set[str]] = {"call": set(), "check": set()}

#: Every attempt to leave this process, by whichever refusal caught it.
#:
#: **Recorded as well as raised, because raising is not reporting.**
#: `routers/auth.py::_send_quietly` catches `Exception` around a mail send, and
#: an `AssertionError` is one, so a refusal raised inside a request the app runs
#: as a background task is logged and the test stays green. A list the
#: application cannot reach is what makes the attempt visible.
_escapes: list[str] = []

#: Applied to both properties. The account and its book are built once per
#: operation and every example shares them, which is what makes a generated id
#: resolve at all; hypothesis warns about that because state then carries between
#: examples, and here it is the arrangement rather than an accident.
BUDGET = hypothesis_settings(
    max_examples=EXAMPLES_PER_OPERATION,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _ask(case, headers: dict[str, str], asked_by: str):
    """One generated request, or `None` when the harness refused to make it.

    The suite refuses outbound HTTP for every test, so a route that calls a
    catalogue is stopped before it answers. That is this harness and not a
    finding, so it is counted rather than failed, and the count is what
    `TestEveryOperationWasAskedSomething` reads: an operation reached only this
    way has been asked nothing and would otherwise be green.
    """
    label = case.operation.label
    _requests[asked_by][label] += 1
    try:
        # **The commonest failure this module has, and it never reaches
        # `_validate`.** `errors.unhandled_exception_handler` turns a bug into a
        # 500 body and the middleware re-raises so that a server can log, so in
        # process the exception arrives here rather than as a response.
        with _RecordingFailure(label, "call"):
            response = case.call(headers=headers)
    except respx.models.AllMockedAssertionError:
        _refused[label] += 1
        return None
    _answered[label] += 1
    if response.status_code < 400:
        _reached[label] += 1
    return response


def _labels_naming_a_row() -> set[str]:
    """Operations whose path carries an integer parameter.

    **Derived from the parameter's type rather than from its name or from the
    presence of a brace.** A path template is not evidence that anything in it
    is a row: `/covers/login_bg.{extension}` and the catalogue credential routes
    take a string that names a file suffix or a source. An integer in a path is
    a row id everywhere in this API, so the type is what separates the witness's
    subject from the rest, and no list of route names has to be kept.
    """
    found = set()
    for path, item in schema.raw_schema["paths"].items():
        for method, operation in item.items():
            if method.upper() not in HTTP_METHODS:
                continue
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "path":
                    continue
                if parameter.get("schema", {}).get("type") == "integer":
                    found.add(f"{method.upper()} {path}")
    return found


def _validate(case, response, checks) -> None:
    """The checks, with the operation remembered when one of them fails.

    A failing operation is replayed by hypothesis while it minimises the
    example, so its request count stops being a measurement of the budget. This
    is where the budget guard learns which counts to ignore, and it re-raises
    unchanged.
    """
    with _RecordingFailure(case.operation.label, "check"):
        case.validate_response(response, checks=checks)


def _labels() -> set[str]:
    """Every operation the loader built, by the label the tests are named for.

    An operation that failed to load is raised on rather than dropped: it is one
    nothing above tests, and a set that quietly shrinks is exactly the vacuity
    `TestTheCommittedSchemaDescribesTheAppUnderTest` exists to refuse.
    """
    found = set()
    for result in schema.get_all_operations():
        operation = result.ok() if hasattr(result, "ok") else None
        assert operation is not None, f"an operation failed to load: {result}"
        found.add(operation.label)
    return found


@pytest.fixture
def asked_by(request) -> str:
    """The property making the request, so one budget is not read as two.

    Taken off the running test rather than written into each call, because a
    literal per test is the name in two places and one of them drifts.
    `originalname` is the function's own name, where `name` carries the
    parametrised operation.
    """
    return request.node.originalname or request.node.name


class _RecordingFailure:
    """Records the operation when the block under it raises, whatever it raises.

    **A context manager rather than an `except` clause, because the clause is
    the thing that keeps being wrong.** It was written `except Exception` first,
    which caught nothing: `validate_response` raises `FailureGroup`, that
    derives from `BaseExceptionGroup`, and CPython promotes a subclass of it to
    `ExceptionGroup` never. `__exit__` is handed every exception class there is,
    so there is no set of classes here to be short of.

    What it does name is the **exclusion**: the suite's network guard refusing an
    outbound call is the harness rather than a failure, and `_ask` turns that
    into a refusal count of its own.
    """

    __slots__ = ("label", "site")

    def __init__(self, label: str, site: str) -> None:
        self.label = label
        self.site = site

    def __enter__(self) -> _RecordingFailure:
        return self

    def __exit__(self, kind: Any, value: Any, traceback: Any) -> None:
        if kind is not None and not issubclass(kind, respx.models.AllMockedAssertionError):
            _failed[self.site].add(self.label)


def _refuse_to_leave(what: str):
    """A stand in that records the attempt before it raises.

    Both halves matter and the recording is the one that is not obvious: see
    `_escapes`.
    """

    def refuse(target: Any = "", *args: Any, **kwargs: Any):
        _escapes.append(f"{what} {target}")
        raise AssertionError(
            f"a generated request tried to {what} {target}. This module is "
            "hermetic by construction and nothing outside this process is a "
            "throwaway."
        )

    return refuse


@pytest.fixture(autouse=True)
def refuse_smtp(monkeypatch):
    """No generated request opens a mail connection.

    **`respx` is not enough and the gap is the protocol.** The suite's autouse
    network guard patches httpx, and `mailer` opens `smtplib.SMTP` directly.
    Nothing reaches it on a member run, because `conftest` removes every mail
    variable and the route that could store a host is admin only, so what stops
    the socket there is which token the run carries. That is a property of the
    configuration rather than of the harness, and this module invites exactly
    the change that breaks it by naming an admin run as a trade somebody might
    take.
    """
    monkeypatch.setattr(smtplib, "SMTP", _refuse_to_leave("open a mail connection to"))
    monkeypatch.setattr(smtplib, "SMTP_SSL", _refuse_to_leave("open a mail connection to"))


@pytest.fixture(autouse=True)
def refuse_name_lookups(monkeypatch):
    """No generated request resolves a host name.

    **The second protocol gap, and `conftest` names it about a different
    caller.** respx refuses requests rather than lookups, and
    `fetch.PinnedTransport` resolves the name itself before httpx is involved,
    so a door that stores a host name reaches a real resolver under a mocked
    client. `cover_hosts_resolve_to_fixtures` closes that for covers by pinning
    one resolver; the OPDS door has its own, and on a member run it is out of
    reach only because storing a server is admin only.

    **The database's host is the exception and it is read rather than listed.**
    On SQLite there is none and nothing resolves at all; on a server the engine
    has to reach it, and that is the one name this process is entitled to.
    """
    allowed = {engine.url.host} - {None}
    real = socket.getaddrinfo
    refuse = _refuse_to_leave("resolve the host name")

    def guarded(host: Any = "", *args: Any, **kwargs: Any):
        if host in allowed:
            return real(host, *args, **kwargs)
        return refuse(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


@pytest.fixture
def contract_member(member):
    """An ordinary member, with one book of their own on the shelf.

    **Seeded because an empty database answers 404 to everything.** Path
    parameters are generated integers and hypothesis biases those toward small
    values, so a row at id 1 is what turns a book scoped operation from a walk
    through the not found branch into one that reaches the handler. One row
    rather than a fixture per resource: the point is that some generated id
    resolves, not that every table has a member.

    The row goes in through the ORM rather than through the API, because a
    `TestClient` here would start a second lifespan against the application the
    generator is already driving.
    """
    session = SessionLocal()
    try:
        session.add(Book(title="A seeded book", added_by_user_id=member["user"]["id"]))
        session.commit()
    finally:
        session.close()
    return member


@pytest.mark.property
@BUDGET
@schema.parametrize()
def test_no_generated_request_is_a_server_error(case, contract_member, asked_by):
    """The property the hand written class holds over one route, over all of them.

    **It usually fails through the traceback rather than through the check.**
    `errors.unhandled_exception_handler` turns a bug into a 500 body, and the
    middleware that calls it re-raises so that a server can log, so in process
    the exception reaches this test before any response does. The check stays
    because it is the property as stated, and because it is what would be left
    if the transport ever swallowed the re-raise.
    """
    response = _ask(case, contract_member["headers"], asked_by)
    if response is not None:
        _validate(case, response, [not_a_server_error])


@pytest.mark.property
@BUDGET
@schema.parametrize()
def test_every_response_matches_the_schema_that_declares_it(case, contract_member, asked_by):
    """The committed schema as a contract rather than as an artefact."""
    response = _ask(case, contract_member["headers"], asked_by)
    if response is not None:
        _validate(case, response, [response_schema_conformance])


class TestTheCommittedSchemaDescribesTheAppUnderTest:
    """The premise: the file read above and the app called above are one API.

    CI diffs the committed schema against a fresh generation on every push, so
    this is not that check arriving late. It is this module's own footing: every
    assertion above is about an operation read out of a file, and a file
    describing another version of the app makes all of them vacuous in a way no
    failure would announce.
    """

    def test_the_file_declares_the_operations_the_app_serves(self):
        live = {
            f"{method.upper()} {path}"
            for path, item in main.app.openapi()["paths"].items()
            for method in item
            if method.upper() in HTTP_METHODS
        }
        assert _labels() == live

    def test_it_found_operations_at_all(self):
        """The vacuity arm. Every assertion in this module is over a set the
        loader built, and an empty set passes all of them."""
        assert len(_labels()) > 100


class TestEveryOperationWasAskedSomething:
    """A generated test that made no request is green and empty.

    Two ways that happens here and neither is loud: the suite's network guard
    stops an operation's every example before the app answers, or a strategy
    hypothesis cannot satisfy leaves an operation with almost no examples. Both
    read as a pass, and the module would then describe a surface it never
    touched.
    """

    def test_every_operation_answered_at_least_once(self):
        """Ordering is load bearing: this reads counters the properties above
        fill, and pytest runs a module in definition order. `--dist loadfile`
        keeps a file on one worker, which is what makes the counters one set
        rather than two."""
        silent = sorted(label for label in _labels() if not _answered[label])
        assert not silent, (
            "these operations never produced a response, so nothing above is a "
            f"statement about them: {silent}. Refusals by the suite's network "
            f"guard: {({label: _refused[label] for label in silent})}"
        )

    def test_a_generated_path_parameter_named_a_row_that_exists(self):
        """The witness under `contract_member`'s seeded book.

        **An answer is not a reach.** A 404 is a response, so the test above is
        satisfied by an operation that spent every example walking the not found
        branch, and that is what a book scoped operation does against an empty
        database. The fixture seeds one row precisely so that some generated id
        resolves; without a witness, the day that stops working is a day this
        module still passes and tests the 404 path over and over.

        The claim is one operation and not all of them, because how far a member
        gets is a property of the route: an admin only route is a 403 whatever
        id it is given, and requiring every one of them to reach a row would be
        asserting something this module does not know.
        """
        naming_a_row = _labels_naming_a_row()
        assert naming_a_row, "no operation in the schema takes an integer path parameter"
        assert naming_a_row <= _labels(), (
            "these operations carry an integer path parameter and are not in the "
            f"set the tests ran over: {sorted(naming_a_row - _labels())}"
        )
        assert any(_reached[label] for label in naming_a_row), (
            f"none of the {len(naming_a_row)} operations taking a row id "
            "answered under 400, so no generated id ever named a row that "
            "exists and this module only exercised the not found branch"
        )


class TestNothingLeftTheProcess:
    """The refusals above raise, and raising is not the same as reporting.

    Two doors this module closes that `conftest` does not, both because the
    suite's network guard is respx and respx sees httpx: a mail connection, and
    a host name lookup. Each refusal raises inside the request that made it, and
    the application catches `Exception` in at least one place a generated
    request reaches, so the attempt is recorded here as well.
    """

    def test_no_generated_request_reached_outside_this_process(self):
        """Reads a module global the properties above fill, on the same terms as
        the counters: definition order, and `--dist loadfile` keeping the file on
        one worker."""
        assert _escapes == [], (
            "these attempts to leave the process were refused, and at least one "
            "of them may have been swallowed by the application rather than "
            f"failing: {_escapes}"
        )


class TestTheBudgetIsInForce:
    """`max_examples` is an upper bound, so the number that matters is measured.

    The same rule `tests/test_property_budget.py` holds over the tests
    hypothesis drives through `given`. It does not reach this module, because it
    finds a generated test by its `given` decorator and these are generated by
    `parametrize`, so the floor under them is here.

    **The maximum rather than the minimum, and that is the whole design of it.**
    How many requests an operation can make is a property of its own strategy: an
    operation that takes no parameter and no body has one request to make, and
    hypothesis stops once it has made it, whatever the budget says. A floor under
    every operation would therefore report those as unspent budget on a run where
    the budget was in force, which is a guard that cries wolf. What this refuses
    is the thing a per operation floor cannot see any better: a budget lowered
    for the module as a whole, by this constant, by a profile or by a command
    line override.

    **Over the operations that did not fail, because a failure moves the count
    in both directions.** A failing operation is replayed while hypothesis
    minimises the example, so its count is mostly replay and a budget lowered to
    one would still show a maximum above this constant. And once a failure has
    been found, `should_generate_more` stops generating at ten calls unless the
    failures keep arriving, so an operation that fails early and then answers
    reads **under** the budget on a run where the budget was in force. Neither
    direction is a measurement of anything, and dropping the shrink phase to
    flatten the first would cost the minimised example, which is what makes a
    failure here reportable at all. So the failures are excluded from the
    measurement rather than from the run, and `_failed` is what records them.
    """

    def test_every_call_that_raised_was_recorded(self):
        """The exact diagonal under the call site, derived from the counters.

        Every request is counted before it is made and every outcome is counted
        after, so the calls that raised are what the attempts have left once the
        refusals and the responses are taken off. That set has to be the one the
        recorder built, in both directions: a recorder that stopped firing is
        short, and one firing on a call that came back is long.
        """
        raised = {
            label
            for label in _labels()
            if sum(counts[label] for counts in _requests.values())
            - _refused[label]
            - _answered[label]
        }
        assert raised == _failed["call"], (
            f"{len(raised)} operations had a call raise and "
            f"{len(_failed['call'])} were recorded; the difference is "
            f"{sorted(raised ^ _failed['call'])}"
        )

    def test_a_run_with_failures_recorded_them(self, request):
        """The diagonal under `_failed`, without which the exclusion above is a
        line nothing exercises.

        Both ways a property here fails are exceptions the recording sites had
        to be written for, and both were wrong on the first attempt: a check
        failure raises a group deriving from `BaseException`, and a server error
        never reaches the check at all. An empty `_failed` on a run that had
        failures means both sites stopped, and the budget guard below is then
        reading replay traffic.

        **Both sites at once, which is what the test above narrows.** Requiring
        each of them to be non empty would be wrong: a run whose only failures
        are conformance failures has an empty call site and is correct. So the
        call site gets the exact diagonal, from the counters, and this covers
        the pair.

        `testsfailed` is this worker's count, and it is every failing report
        rather than the two properties'. The file is collected alone and
        `--dist loadfile` keeps it on one worker, so it counts this module's
        failures; it cannot tell which test they came from, which is why the
        message below says what it would mean rather than asserting it.
        """
        assert not request.session.testsfailed or _failed["call"] or _failed["check"], (
            f"{request.session.testsfailed} tests failed on this worker and no "
            "operation was recorded as failing. If any of them was one of the "
            "properties above, both recording sites have stopped catching and "
            "the budget below is measuring replays"
        )

    def test_some_operation_spent_the_whole_budget(self):
        spent = max(
            (
                count
                for counts in _requests.values()
                for label, count in counts.items()
                if label not in _failed["call"] | _failed["check"]
            ),
            default=0,
        )
        assert spent >= EXAMPLES_PER_OPERATION, (
            f"the busiest operation that did not fail made {spent} requests "
            f"under one property, against a budget of {EXAMPLES_PER_OPERATION}, "
            "so nothing here spent what this module says it spends"
        )
