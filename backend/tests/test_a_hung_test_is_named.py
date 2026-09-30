"""A test that hangs fails as a named test, and a short session is refused.

Three pieces make one mechanism and removing any one of them restores the old
behaviour in a different shape, so each has its own arm rather than one arm for
the feature:

* the per test ceiling in `pyproject.toml`, which turns a hang into a named
  failure instead of a job timeout naming nothing;
* `--timeout-method=signal`, which fails the test and leaves the worker alive,
  where the thread method calls `os._exit` and is indistinguishable from a crash;
* `--max-worker-restart=0`, which stops one worker death becoming nine.

and under all three, the reconciliation in `conftest.py`, which refuses a session
that reported fewer tests than it collected. That last one is the load bearing
half: a ceiling set too high still ends in a named refusal rather than in a run
that quietly lost fifteen tests.

**The diagonal for the ceiling cannot use this repository's own suite, and the
reason is the whole difficulty of this file.** The mutation that deletes the
timeout is exactly the mutation that makes the run unbounded, so from the
caller's side a caught mutant and a dead harness are the same thing. Measured:
with the ceiling armed, exit 1 in six seconds and a report naming the hanging
test; with it removed, exit 137, no report, and output ending in `Killed`.
Nothing in the second distinguishes the two.

So the inner run gets its own throwaway project with its own short ceiling, never
this repository's, and this file holds its termination in its own hands. The
verdict is read from the inner run's report and partitioned **three** ways and
never two: red for the right reason, green, and invalid, which is the outer bound
firing so that no report exists at all. Folding invalid into either of the others
is the defect this file exists to be about.

**What a green here does not prove.** The signal method cannot reach a hang that
blocks SIGALRM, one inside a C call that never returns to the interpreter, one
during collection or module import, or one in the controller itself. Each was
measured as exit 137 with no report. That is a deliberate narrowing and the
ceiling is a backstop rather than a bound on the hang population; the bound at a
site with a real deadline of its own belongs in that site's own fixture.
"""

from __future__ import annotations

import ast
import contextlib
import os
import shlex
import signal
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from tests import conftest
from tests.test_house_rules import _test_sources

_BACKEND = Path(__file__).resolve().parents[1]
_MANIFEST = _BACKEND / "pyproject.toml"

#: The inner project's own ceiling. Short, because every arm here pays it, and
#: nothing about this file's subject needs it to be long.
INNER_CEILING_SECONDS = 2.0

#: The wall clock this file allows an inner run before it signals the group.
#:
#: **Well above the inner ceiling on purpose.** Set close to it, this bound
#: becomes the thing that ends the run, and every arm then reports invalid
#: whatever the plugin did. It is the harness's own last resort and never the
#: mechanism under test.
OUTER_BOUND_SECONDS = 90.0

#: How long to wait for the parent between the two signals. Short: it is the
#: reap of a process that has just been signalled, not a deadline for work.
_REAP_SECONDS = 5.0

#: How long to spend collecting an already signalled run's output. Bounded for
#: the reason in `run_a_bounded_inner_pytest`, and short because by this point
#: the run is invalid whatever it says.
_DRAIN_SECONDS = 10.0


# ── Running pytest inside pytest, with termination in this file's hands ──────


@dataclass(frozen=True)
class InnerRun:
    """One inner pytest run, with the report it produced if it produced one."""

    exit_code: int
    output: str
    #: The text of the JUnit report, or None when the run wrote none.
    report: str | None
    #: False when the outer bound fired, which makes every other field a
    #: description of a run that was stopped rather than one that finished.
    bounded_itself: bool

    def cases(self) -> dict[str, tuple[str, str]]:
        """Every failing case in the report, as name to (tag, message).

        Reading the report rather than the output is settled policy here: a
        count is not a catch, a name is.
        """
        assert self.report is not None, "no report to read"
        found: dict[str, tuple[str, str]] = {}
        for case in ET.fromstring(self.report).iter("testcase"):
            for child in case:
                if child.tag in ("failure", "error"):
                    found[case.get("name", "")] = (child.tag, child.get("message") or "")
        return found


def run_a_bounded_inner_pytest(
    project: Path,
    sources: dict[str, str],
    *,
    ceiling: float | None = INNER_CEILING_SECONDS,
) -> InnerRun:
    """Write a throwaway project, run pytest over it, and never outlive it.

    **`start_new_session=True` and the signal goes to the group.** A bound that
    kills the parent does not kill the suite: pytest's own workers and anything a
    test spawned survive the parent and keep the node busy. This repository has
    already paid for that once, with an orphan at 8.6 GB for 53 minutes.

    **TERM before KILL.** A child given no chance to die cleanly leaves a partial
    report behind, which is the one input this file must not confuse with a real
    one.

    `ceiling=None` runs with no per test bound, which is the shape the outer
    bound exists for.
    """
    project.mkdir(parents=True, exist_ok=True)
    # Its own ini, so the inner run's configuration is this function's and never
    # this repository's. Reading the repository's value here would make every arm
    # below a tautology about the line it is supposed to be checking.
    (project / "pytest.ini").write_text("[pytest]\n")
    for name, body in sources.items():
        (project / name).write_text(body)

    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        f"--junitxml={project / 'report.xml'}",
    ]
    if ceiling is not None:
        argv += [f"--timeout={ceiling}", "--timeout-method=signal"]
    argv += sorted(sources)

    env = dict(os.environ)
    # The outer run's own flags reach a child through this variable, including
    # its ceiling. Inheriting them would let this repository's configuration
    # decide the inner run's verdict.
    env.pop("PYTEST_ADDOPTS", None)

    child = subprocess.Popen(
        argv,
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    bounded_itself = True
    try:
        output, _ = child.communicate(timeout=OUTER_BOUND_SECONDS)
    except subprocess.TimeoutExpired:
        bounded_itself = False
        _signal_the_group(child)
        try:
            # **Bounded, and the first version was not.** A grandchild inherits
            # the stdout pipe and holds it open after its parent is gone, so an
            # unbounded drain here blocks with the outer bound already spent,
            # in the file whose whole subject is that nothing may run forever.
            output, _ = child.communicate(timeout=_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            if child.stdout is not None:
                child.stdout.close()
            output = (
                "<the inner run's output could not be drained: something in its "
                "process group still holds the pipe open>"
            )

    report_path = project / "report.xml"
    report = report_path.read_text() if report_path.exists() else None
    return InnerRun(
        exit_code=child.returncode,
        output=output,
        report=report,
        bounded_itself=bounded_itself,
    )


def _signal_the_group(child: subprocess.Popen[str]) -> None:
    """TERM the whole group, then KILL it, and the KILL is unconditional.

    **The first version said this and did not do it.** It returned as soon as
    `child.wait()` succeeded, which is precisely the parent dying, so SIGKILL
    never reached the group: a parent that honours TERM while a grandchild
    ignores it left the grandchild running. That is the orphan shape this tree
    has already paid for once, at 8.6 GB for 53 minutes, rebuilt inside the
    guard for it. **Waiting on the parent says nothing about the group**, so
    nothing here is conditional on it.

    **The group id is `child.pid` rather than `os.getpgid(child.pid)`.** The
    child was started with `start_new_session=True`, which makes it the leader,
    so the two are equal while it lives; and this function is called exactly
    when it may already be gone, where `getpgid` raises.

    Every call tolerates the group having gone already.
    """
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, sig)
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=_REAP_SECONDS)


def require_a_report(run: InnerRun, what: str) -> None:
    """Refuse an inner run that produced no report, as invalid rather than green.

    A must red is not red until the run carrying it produced a test report: from
    the caller's side an unbounded run and a caught mutant are the same thing.
    """
    if not run.bounded_itself:
        pytest.fail(
            f"{what}: the inner run did not bound itself and this file's own bound "
            f"of {OUTER_BOUND_SECONDS}s signalled it, so there is no evidence either "
            f"way. Output tail: {run.output[-400:]!r}"
        )
    if run.report is None:
        pytest.fail(
            f"{what}: the inner run wrote no report, so its verdict cannot be read. "
            f"Exit {run.exit_code}. Output tail: {run.output[-400:]!r}"
        )


#: An inner project whose first test never returns on its own.
#:
#: **Termination is in the fixture's own hands and not in the mechanism under
#: test's.** A source that never answers is a good fixture against every mutant
#: that keeps the ceiling and an infinite loop against the one that drops it, so
#: the sleep is finite and far longer than the ceiling, and the outer bound sits
#: between the two.
A_TEST_THAT_HANGS = """\
import time


def test_it_hangs():
    time.sleep(60)


def test_it_passes_afterwards():
    assert True


def test_it_fails_for_real():
    raise AssertionError("an ordinary assertion")
"""


@pytest.fixture(scope="module")
def hung_inner_run(tmp_path_factory: pytest.TempPathFactory) -> InnerRun:
    """One armed inner run, shared by the arms that read the same evidence."""
    project = tmp_path_factory.mktemp("hung") / "armed"
    return run_a_bounded_inner_pytest(project, {"test_hangs.py": A_TEST_THAT_HANGS})


class TestAHangingTestArrivesAsANamedFailure:
    """The diagonal: plant the hang and watch it redden by name."""

    def test_the_hanging_test_is_named_in_the_report(self, hung_inner_run: InnerRun) -> None:
        require_a_report(hung_inner_run, "the armed run")
        cases = hung_inner_run.cases()
        assert "test_it_hangs" in cases, (
            f"the ceiling did not name the hanging test. Failing cases: {cases}"
        )
        tag, message = cases["test_it_hangs"]
        assert tag == "failure"
        assert "Timeout" in message, message

    def test_the_worker_survives_and_the_rest_of_the_run_reports(
        self, hung_inner_run: InnerRun
    ) -> None:
        """The signal method's whole point, and what makes it affordable.

        The thread method calls `os._exit` here instead: measured, nine restarts,
        the same test reported failed nine times, and 20 report entries for 13
        collected tests.
        """
        require_a_report(hung_inner_run, "the armed run")
        assert hung_inner_run.report is not None
        cases = {case.get("name") for case in ET.fromstring(hung_inner_run.report).iter("testcase")}
        assert cases == {"test_it_hangs", "test_it_passes_afterwards", "test_it_fails_for_real"}

    def test_a_slow_test_that_finishes_is_not_reddened(self, tmp_path: Path) -> None:
        """Ask whether the red above is for the reason it looks like.

        A ceiling that reddened everything slow would pass the arm above and be
        useless, so the other direction is asserted rather than assumed.
        """
        run = run_a_bounded_inner_pytest(
            tmp_path / "slow",
            {
                "test_slow.py": "import time\n\n\ndef test_slow_but_finite():\n"
                "    time.sleep(0.3)\n"
            },
            ceiling=5.0,
        )
        require_a_report(run, "the slow but finite run")
        assert run.cases() == {}, run.cases()
        assert run.exit_code == 0

    def test_the_red_survives_deleting_something_unrelated(self, tmp_path: Path) -> None:
        """Delete a line the plant does not depend on and check the red holds.

        Wave G's sharpest instrument: a guard reddened on a planted flip only
        because the graph happened to hold exactly one exemption, and deleting
        that unrelated line made the identical flip green. Here the unrelated
        thing is the other two tests in the inner project.
        """
        run = run_a_bounded_inner_pytest(
            tmp_path / "alone",
            {"test_hangs.py": "import time\n\n\ndef test_it_hangs():\n    time.sleep(60)\n"},
        )
        require_a_report(run, "the run with the plant alone")
        assert "test_it_hangs" in run.cases()


class TestTheInnerProjectIsNotDecidedByAnythingAboveIt:
    """The inner run's configuration is this file's, and nothing else's.

    Every arm above rests on that: an inner run that inherited this
    repository's ini would be asserting about the very line it is supposed to
    be checking, and one that inherited a stray ini from wherever the temporary
    directory happens to sit would fail for a reason nobody could see. The
    `pytest.ini` the harness writes is what stops both, because rootdir
    discovery stops at the nearest one.

    **That was reasoned and not proved**, which is the state this arm ends.
    """

    def test_a_hostile_ini_above_the_project_does_not_reach_it(
        self, tmp_path: Path
    ) -> None:
        """Planted directly above, and chosen so inheriting it would be silent.

        `python_files` is what decides whether a file is a test module at all,
        so a run that took the parent's would collect nothing and pass, which is
        the shape a green cannot be told from. `addopts` is there because it is
        the other half of the same question and composes rather than replaces.
        """
        (tmp_path / "pytest.ini").write_text(
            "[pytest]\npython_files = nothing_here_*.py\naddopts = --collect-only\n"
        )
        run = run_a_bounded_inner_pytest(
            tmp_path / "project",
            {"test_inherits_nothing.py": "def test_it_runs():\n    assert True\n"},
            ceiling=5.0,
        )
        require_a_report(run, "the run under a hostile parent ini")
        assert run.report is not None
        cases = [case.get("name") for case in ET.fromstring(run.report).iter("testcase")]
        assert cases == ["test_it_runs"], cases
        assert run.cases() == {}
        assert run.exit_code == 0


class TestTheManifestKeepsAllThreePiecesArmed:
    """Each of the three is a way the fix silently becomes what it replaced."""

    @staticmethod
    def _addopts() -> list[str]:
        manifest = tomllib.loads(_MANIFEST.read_text())
        return shlex.split(manifest["tool"]["pytest"]["ini_options"]["addopts"])

    def test_every_test_is_bounded(self) -> None:
        assert any(opt.startswith("--timeout=") for opt in self._addopts()), self._addopts()

    def test_the_method_is_pinned_to_signal(self) -> None:
        """Left implicit, this is one flag or one platform away from a crash.

        The plugin's default behaves like the signal method on this platform
        today, which is exactly why it is written out: the thread method's
        failure looks like a crash rather than like a configuration mistake.
        """
        assert "--timeout-method=signal" in self._addopts(), self._addopts()

    def test_one_worker_death_cannot_become_nine(self) -> None:
        """xdist's default here is `numprocesses * 4`, so eight restarts.

        Measured at that default with a crash under `--dist loadfile`: ten
        workers consumed, one test reported failed ten times, 35 report entries
        for 31 collected tests and five tests never run.
        """
        assert "--max-worker-restart=0" in self._addopts(), self._addopts()

    def test_the_plugin_the_ceiling_needs_is_a_declared_dependency(self) -> None:
        manifest = tomllib.loads(_MANIFEST.read_text())
        dev = manifest["dependency-groups"]["dev"]
        assert any(entry.startswith("pytest-timeout") for entry in dev), dev

    def test_the_three_flags_are_on_the_command_line_and_not_in_ini_keys(self) -> None:
        """Which is what keeps the dependency and the bound self enforcing.

        With the plugin absent, `--timeout` on the command line is a usage error
        and the run refuses; an unknown ini key is a warning and the run proceeds
        unbounded. `--max-worker-restart` has no ini key at all.
        """
        ini = tomllib.loads(_MANIFEST.read_text())["tool"]["pytest"]["ini_options"]
        assert "timeout" not in ini
        assert "timeout_method" not in ini


# ── The ceiling is derived from the tree, not chosen against a distribution ──


@dataclass(frozen=True)
class DeclaredCeiling:
    site: str
    seconds: float


def declared_ceilings() -> list[DeclaredCeiling]:
    """Every ceiling this test tree declares for something it waits on.

    **Derived from what a call binds, not from a spelling.** The population is
    every `timeout=` keyword argument in a call, read off the syntax tree, with a
    module level numeric constant resolved through its binding so a site that
    names its ceiling is counted like one that writes the number.

    **The file set is the shared walk and not a recursion of this file's own.**
    A tree of Python walked here would read whatever the pipeline unpacks under
    `backend/`, which is green on every developer checkout and wrong in the one
    environment that matters. `tests/test_house_rules.py` holds that rule and
    enforces it on every other module, which is how this walk was caught.

    **What it leaves out, stated rather than left for the next reader.**

    * `@pytest.mark.timeout(n)`, which is a positional argument on a marker and
      is deliberately outside: a marked test overrides the global ceiling, so it
      is allowed to exceed it. That is the escape hatch, not a violation of it.
    * A ceiling whose value is computed, imported from another module, or passed
      positionally. Those are invisible here and the global would cut them.
    """
    found: list[DeclaredCeiling] = []
    for path in sorted(_test_sources()):
        tree = ast.parse(path.read_text(), str(path))
        constants: dict[str, float] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, int | float):
                    for target in targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = float(value.value)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            for keyword in call.keywords:
                if keyword.arg != "timeout":
                    continue
                value_node = keyword.value
                seconds: float | None = None
                if isinstance(value_node, ast.Constant) and isinstance(
                    value_node.value, int | float
                ):
                    seconds = float(value_node.value)
                elif isinstance(value_node, ast.Name):
                    seconds = constants.get(value_node.id)
                if seconds is not None:
                    site = f"{path.relative_to(_BACKEND)}:{call.lineno}"
                    found.append(DeclaredCeiling(site, seconds))
    return found


def the_global_ceiling() -> float:
    addopts = shlex.split(
        tomllib.loads(_MANIFEST.read_text())["tool"]["pytest"]["ini_options"]["addopts"]
    )
    for opt in addopts:
        if opt.startswith("--timeout="):
            return float(opt.split("=", 1)[1])
    raise AssertionError(f"the manifest declares no global ceiling: {addopts}")


class TestTheGlobalCeilingIsAFactAboutThisTree:
    """The value is derived, so a later test declaring a longer wait reddens.

    **Not asserted against any measured duration**, which would be a stale figure
    reddening on a slower node. The relation is to what the tree itself says a
    legitimate life is, and that does not move with the machine.

    **It is a floor and there is no upper term, so say so rather than imply
    both.** Nothing here stops the value being raised until it never fires;
    36000 and 360 are equally green. What makes a high ceiling safe is not this
    guard, it is the reconciliation: a session that loses a test to anything,
    including a bound that never fired, is refused by name.

    **And the floor is necessary rather than sufficient.** A test that
    legitimately spends its declared 300 and then does anything else at all is
    still cut by a global one second above it. The escape for that is the same
    one as for any other long test, a timeout marker at its own site.
    """

    def test_the_population_is_not_empty(self) -> None:
        """A walk that finds nothing is a guard that has stopped guarding.

        Without this the arm below is vacuously true the day the derivation
        stops matching anything, which is the shape a text derived population
        fails in every time.
        """
        assert declared_ceilings(), "no site in the test tree declares a ceiling"

    def test_the_global_is_strictly_above_every_ceiling_the_tree_declares(self) -> None:
        declared = declared_ceilings()
        largest = max(declared, key=lambda entry: entry.seconds)
        ceiling = the_global_ceiling()
        assert ceiling > largest.seconds, (
            f"the global ceiling is {ceiling}s and {largest.site} declares "
            f"{largest.seconds}s, so the global would cut a wait this tree says is "
            "legitimate. Raise the global above it, or move that site's bound onto "
            "the test with a timeout marker."
        )


# ── The reconciliation, which is the half that covers everything else ────────


class _Reporter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, line: str, **_: Any) -> None:
        self.lines.append(line)


class _PluginManager:
    def __init__(self, reporter: _Reporter | None) -> None:
        self._reporter = reporter

    def get_plugin(self, name: str) -> _Reporter | None:
        return self._reporter if name == "terminalreporter" else None


@dataclass
class _Option:
    collectonly: bool = False


class _Config:
    def __init__(
        self, reporter: _Reporter | None, *, collectonly: bool = False, worker: bool = False
    ) -> None:
        self.option = _Option(collectonly=collectonly)
        self.pluginmanager = _PluginManager(reporter)
        if worker:
            # What xdist sets on a worker's config and on nothing else.
            self.workerinput = {"workerid": "gw0"}


class _Session:
    def __init__(
        self,
        config: _Config,
        exitstatus: int,
        *,
        shouldfail: str | bool = False,
        shouldstop: str | bool = False,
    ) -> None:
        self.config = config
        # The session's own stop state, which is what the reconciliation asks
        # before it asks the status. Both carry a reason string when set.
        self.shouldfail = shouldfail
        self.shouldstop = shouldstop
        # **Already carrying the status when the hook is called**, which is what
        # the real session does: pytest sets `session.exitstatus` and then passes
        # the same value into `pytest_sessionfinish`. A stand in that starts at
        # zero makes every exempt arm assert against zero and pass for the wrong
        # reason, which is how the first draft of this file read.
        self.exitstatus = exitstatus


def _finish(
    monkeypatch: pytest.MonkeyPatch,
    *,
    collected: list[str],
    reported: set[str],
    exitstatus: int,
    collectonly: bool = False,
    worker: bool = False,
    shouldfail: str | bool = False,
    shouldstop: str | bool = False,
) -> tuple[_Session, _Reporter]:
    """Drive the reconciliation over a stated population.

    The population is set rather than produced, because a session cannot lose a
    test on purpose from inside itself. What the hooks that fill it do on a real
    run is covered by the arming arm below, which reads this very session's.
    """
    monkeypatch.setattr(conftest, "_COLLECTED", list(collected))
    monkeypatch.setattr(conftest, "_REPORTED", set(reported))
    monkeypatch.setattr(conftest, "_COLLECTED_FROM", "xdist")
    reporter = _Reporter()
    session = _Session(
        _Config(reporter, collectonly=collectonly, worker=worker),
        exitstatus,
        shouldfail=shouldfail,
        shouldstop=shouldstop,
    )
    conftest.pytest_sessionfinish(cast(pytest.Session, session), exitstatus)
    return session, reporter


class TestASessionThatLostATestIsRefusedByName:
    def test_the_missing_tests_are_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b", "t.py::c"],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.OK),
        )
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        said = "\n".join(reporter.lines)
        assert "t.py::b" in said and "t.py::c" in said, said

    def test_a_truncated_failing_run_is_refused_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The crash shape, which exits TESTS_FAILED because crash items are real.

        So the status this run carries is the one the exemption below lets
        through, and the check has to fire inside it.
        """
        session, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b"],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.TESTS_FAILED),
        )
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        # **The status alone says nothing here**, because the session already
        # carried it on the way in. What distinguishes a refusal from a pass on
        # this arm is that the refusal named the test that went missing.
        assert "t.py::b" in "\n".join(reporter.lines), reporter.lines

    def test_a_complete_session_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b"],
            reported={"t.py::a", "t.py::b"},
            exitstatus=int(pytest.ExitCode.OK),
        )
        assert session.exitstatus == pytest.ExitCode.OK
        assert reporter.lines == []

    def test_a_population_that_never_filled_is_refused_rather_than_passing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A guard whose arming is data disarms with no diff and no tell.

        Both population hooks failing leaves an empty collected set, against
        which every reported test is accounted for and the check is vacuously
        green. That is the one shape a mutation sweep cannot see, because it
        plants defects rather than removing an arm's subject.
        """
        session, reporter = _finish(
            monkeypatch,
            collected=[],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.OK),
        )
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        assert "empty" in "\n".join(reporter.lines)


class TestTheExemptionsAreKeyedOnWhatWasMeasured:
    """What this refuses that used to pass, asked in the other direction too.

    Three shapes are short on purpose and each was measured producing a false
    refusal before it was exempted: `-x`, `--maxfail=1` and `--collect-only`.
    Deselection is **not** among them, because it is applied before the workers
    report their collection.
    """

    def test_a_serial_early_stop_is_not_a_short_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`-x` and `--maxfail` with no xdist, which is the shape that was wrong.

        **The status here is `TESTS_FAILED`, not `INTERRUPTED`.** Both flags set
        `shouldfail`, which raises `Session.Failed` and lands on 1. An earlier
        version of this arm handed `INTERRUPTED` in by hand and so certified an
        exemption it never measured, while the real `-n 0 -x` was refused with
        every unrun test named. `--pdb` forces `-n 0`, so that is the ordinary
        debugging incantation rather than a corner.

        Measured on a five test project, reading what the hook is handed:
        `exitstatus=TESTS_FAILED`, `shouldfail='stopping after 1 failures'`,
        `shouldstop=False`, one test reported of five collected.
        """
        _, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b", "t.py::c"],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.TESTS_FAILED),
            shouldfail="stopping after 1 failures",
        )
        assert reporter.lines == []

    def test_the_same_stop_under_xdist_is_not_a_short_session_either(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And the two paths now answer the same way, which they did not.

        Measured, same project under `-n 2`: `exitstatus=INTERRUPTED`, because
        the distributor re-raises, and `shouldfail` set exactly as above. The
        status differs between the two paths and the session's own stop state
        does not, which is why the stop state is asked first.
        """
        _, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b", "t.py::c"],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.INTERRUPTED),
            shouldfail="stopping after 1 failures",
        )
        assert reporter.lines == []

    def test_a_stepwise_stop_is_not_a_short_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other flag, and the only thing in the distribution that sets it.

        Measured: `--stepwise` gives `shouldstop='Test failed, continuing from
        this test next run.'` with `shouldfail` false.
        """
        _, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b", "t.py::c"],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.INTERRUPTED),
            shouldstop="Test failed, continuing from this test next run.",
        )
        assert reporter.lines == []

    def test_a_stop_that_sets_neither_flag_is_not_a_short_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Which is why the status check survives beside the flags.

        **The flags alone are not the whole exemption**, and this is the arm
        that says so. Measured: an interrupt, and a **bare**
        `pytest.exit(reason)` from inside a test, set neither `shouldfail` nor
        `shouldstop` and arrive as `INTERRUPTED` with the rest of the session
        unreported. Replacing the status check with the flags would turn every
        `Ctrl-C` into a wall of names.

        **Bare, because the same call given a `returncode` is not this case.**
        `pytest.exit(reason, returncode=1)` also sets neither flag and arrives
        as `TESTS_FAILED`, so it is reconciled and a loss inside it is refused.
        The arm is written at the status this one was measured at rather than
        at the call, which is the wider thing it is tempting to say.
        """
        _, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b"],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.INTERRUPTED),
        )
        assert reporter.lines == []

    def test_collect_only_is_not_a_short_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b"],
            reported=set(),
            exitstatus=int(pytest.ExitCode.OK),
            collectonly=True,
        )
        assert session.exitstatus == pytest.ExitCode.OK
        assert reporter.lines == []

    def test_a_worker_reconciles_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A worker collects the whole suite and runs a slice of it.

        Its denominator is short by construction, so without this the check
        fires in every worker of every green run.
        """
        session, reporter = _finish(
            monkeypatch,
            collected=["t.py::a", "t.py::b"],
            reported={"t.py::a"},
            exitstatus=int(pytest.ExitCode.OK),
            worker=True,
        )
        assert session.exitstatus == pytest.ExitCode.OK
        assert reporter.lines == []

    def test_every_exit_status_pytest_defines_is_classified(self) -> None:
        """One partition over the enum, so a new status cannot arrive unnoticed.

        The module raises at import on a member classified **nowhere**, so this
        arm is not that check repeated. **Both sides are pinned here, and the
        exempt side is why.** The import check accepts any member that is
        present, so a future status added as False satisfies it and joins the
        exempt side in silence, which is the direction that loses a refusal
        rather than gaining one. Pinned in both directions, a new member has to
        be argued for in both.
        """
        table = conftest._CLAIMS_THE_WHOLE_COLLECTION
        assert set(table) == set(pytest.ExitCode)
        assert {status for status, claims in table.items() if claims} == {
            pytest.ExitCode.OK,
            pytest.ExitCode.TESTS_FAILED,
            # **Classified and unreachable at this hook**, which the comment at
            # the site states. The terminal reporter sets it in a session finish
            # hookwrapper after the yield, so this hook is handed the status the
            # session had before it: measured, `--max-warnings=1` over three
            # passing tests is a process exit of 6 and an `exitstatus` of 0.
            pytest.ExitCode.MAX_WARNINGS_ERROR,
        }
        assert {status for status, claims in table.items() if not claims} == {
            pytest.ExitCode.INTERRUPTED,
            pytest.ExitCode.INTERNAL_ERROR,
            pytest.ExitCode.USAGE_ERROR,
            pytest.ExitCode.NO_TESTS_COLLECTED,
        }


class TestTheseArmsPatchTheModuleTheSessionIsRunning:
    """Otherwise every arm above describes a second copy of the same file.

    `--import-mode=importlib` names a conftest after its path relative to the
    root, so `from tests import conftest` reaches the same object. That is a
    property of the import mode rather than of this file, so it is asserted here
    instead of assumed: a mode change would give these arms their own private
    copy, with empty populations and a monkeypatch nothing reads, and every one
    of them would stay green.
    """

    def test_the_module_under_these_arms_is_the_registered_conftest(
        self, pytestconfig: pytest.Config
    ) -> None:
        wanted = str(_BACKEND / "tests" / "conftest.py")
        registered = [
            plugin
            for plugin in pytestconfig.pluginmanager.get_plugins()
            if getattr(plugin, "__file__", None) == wanted
        ]
        assert registered == [conftest], registered


class TestTheReconciliationIsArmedInThisVeryRun:
    """The hooks are wired, measured against the session running this file.

    The arms above set the population by hand, which says nothing about whether
    anything fills it. This says it, and it says it on whichever arrangement the
    run actually used: `xdist` on the controller, the session with no workers,
    and a worker's own copy under xdist.
    """

    def test_the_population_was_filled(self) -> None:
        assert conftest._COLLECTED_FROM in {"xdist", "the session"}, conftest._COLLECTED_FROM
        assert conftest._COLLECTED, "nothing filled the collected population"

    def test_this_very_test_is_in_the_population(self) -> None:
        mine = "tests/test_a_hung_test_is_named.py"
        assert any(nodeid.startswith(mine) for nodeid in conftest._COLLECTED), (
            f"the population holds {len(conftest._COLLECTED)} ids and none from {mine}"
        )

    def test_reports_are_being_ticked_off(self) -> None:
        assert conftest._REPORTED, "nothing ticked a nodeid off as reported"
