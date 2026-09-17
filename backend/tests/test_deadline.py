"""Tests for backend/deadline.py.

`covers` and `z3950` had each grown a private helper for "how long is left",
and `z3950` and `fetch` spelled the same subtraction inline: four sites, two
spellings of the clock. What is pinned here is the arithmetic, the clock it
reads and **the width of the door**: the last is the one that bought this
module its shape, because a single narrowing function would have made
`z3950`'s ceiling satisfiable by construction and the refusal behind it dead.
"""

import ast
import inspect
import time
from pathlib import Path
from types import ModuleType

import pytest

import deadline
from deadline import in_, left
from tests.test_house_rules import BACKEND, _python_sources


class TestADeadlineIsAnAbsoluteMonotonicTimestamp:
    def test_it_names_a_moment_that_many_seconds_ahead(self):
        before = time.monotonic()
        value = in_(8.0)

        assert before + 8.0 <= value <= time.monotonic() + 8.0

    def test_what_is_left_counts_down_to_it(self):
        assert 0 < left(in_(1.5)) <= 1.5

    def test_no_budget_is_none_rather_than_forever(self):
        """The callee's own default applies, which is not the same as an
        unbounded request and not the same as a spent one."""
        assert left(None) is None

    def test_a_spent_budget_is_negative_rather_than_clamped_to_zero(self):
        """Callers test `<= 0`, so clamping would still read as spent; what it
        would cost is the figure a log or a test needs to say by how much."""
        assert left(time.monotonic() - 1) < 0

    def test_it_reads_the_clock_late_enough_to_be_frozen(self, monkeypatch):
        """A frozen clock is how a boundary gets tested twice.

        `test_z3950.py::test_an_association_at_exactly_the_ceiling_is_allowed`
        patches `time.monotonic` on the stdlib module and needs this module to
        read it there at call time. `from time import monotonic` here would
        bind the real one at import and that fixture would go quietly green on
        a moving clock, testing nothing.
        """
        frozen = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: frozen)

        assert in_(6.0) == 1006.0
        assert left(1006.0) == 6.0


class TestTheDoorIsTwoFunctionsWide:
    """The ceiling and the clamp are not two spellings of one rule.

    `z3950.association` refuses a deadline further than `TIMEOUT_SECONDS` away,
    because the client's socket timeout is derived from it and a ceiling a
    caller can raise is not a ceiling. `opds.sync` caps each page at the
    smaller of the sync's end and one request's timeout. A narrowing function
    here expresses the second and not the first, and the failure is silent:
    `association(deadline=narrowed_to(TIMEOUT_SECONDS))` satisfies the ceiling
    by construction, the `raise` becomes unreachable, and the next reader
    deletes it as dead code with nothing going red.

    So this module composes nothing, and a third public name is where that gets
    argued again rather than assumed. **A door widens sideways as readily as it
    grows a name**, which is the second arm: `in_(seconds, ceiling=...)` is the
    same narrowing under a name already on the list, and the name set cannot
    see it. The ceiling itself is pinned where it lives, by
    `test_z3950.py::TestOneAssociationIsOneClock::
    test_an_association_cannot_be_opened_past_the_module_ceiling`.
    """

    def test_it_offers_exactly_in_and_left(self):
        """**Not `__module__ == "deadline"`**, which is a test about functions:
        a module level constant has no `__module__` at all, so a budget parked
        here, the one thing the module's last paragraph refuses, was invisible
        to the first version of this. Measured: `DEFAULT_SECONDS = 5.0` planted
        in the imported module left the set at `{"in_", "left"}`."""
        public = {
            name
            for name, value in vars(deadline).items()
            if not name.startswith("_")
            and not isinstance(value, ModuleType)
            and getattr(value, "__module__", deadline.__name__) == deadline.__name__
        }

        assert public == {"in_", "left"}, (
            "a name was added to the deadline door; read this class's "
            "docstring before keeping it"
        )

    def test_neither_of_them_takes_a_second_argument(self):
        """**A door widens sideways as readily as it grows a name**, and the
        name set cannot see it: `in_(seconds, ceiling=None)` is the narrowing
        this module refuses, spelled under a name already on the list. Found by
        the security seat, which ran it: the set arm above stayed green.

        `left` is protected by its two one argument overloads, which is an
        accident of typing rather than a rule, so both are asserted here.
        """
        taken = {
            name: list(inspect.signature(getattr(deadline, name)).parameters)
            for name in ("in_", "left")
        }

        assert taken == {"in_": ["seconds"], "left": ["deadline"]}


class TestTheModuleEveryoneTrustsImportsNothingOfOurs:
    def test_it_imports_the_standard_library_and_nothing_else(self):
        """`test_authority.py::test_nothing_here_can_touch_a_database` is an
        allowlist of **direct** imports, and `deadline` is now on it: whatever
        this module imports, `authority` imports too. Stdlib only is what keeps
        that allowlist worth what it says.
        """
        source = (BACKEND / "deadline.py").read_text()
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        assert imported <= {"time", "typing"}, sorted(imported)


def _modules_that_could_read_a_clock() -> list[Path]:
    """Every module of ours but `deadline.py`, which is the one that may.

    **`test_house_rules._python_sources`, not a walk of its own**, which is
    what keeps one definition of what vendored means. An exemption is a filter
    over it rather than a reason to copy it. The exclusion here is a path and
    not a basename for the reason `test_covers._our_modules` states.
    """
    return [
        path
        for path in _python_sources()
        if path.relative_to(BACKEND).as_posix() != "deadline.py"
    ]


def _works_out_what_is_left(tree: ast.AST) -> list[int]:
    """Line numbers where something subtracts the current time from a moment.

    `x - monotonic()` is "how long is left" whatever it is spelled against, and
    it is the expression both private helpers and both inline sites were.
    Elapsed time is `monotonic() - x`, the other way round, and is nobody's
    deadline; the asymmetry is what lets this rule report one and not the
    other.
    """
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Sub)
        and isinstance(node.right, ast.Call)
        and (
            (isinstance(node.right.func, ast.Attribute) and node.right.func.attr == "monotonic")
            or (isinstance(node.right.func, ast.Name) and node.right.func.id == "monotonic")
        )
    ]


class TestNoModuleWorksOutWhatIsLeftForItself:
    """House rule: `deadline.left` is the one place that subtraction happens.

    Four sites across three modules, two of them named helpers, and the fifth
    would have been as quiet as the first four.

    **Two shapes this does not catch**, neither hypothetical. A module that
    binds `now = time.monotonic()` on one line and subtracts it on the next.
    And a module that asks whether the budget is spent by **comparing** rather
    than subtracting, which is what `opds.py` did at `time.monotonic() >= ends`
    until this work rewrote it by hand: nothing keeps it rewritten. The teeth
    stop at the subtraction, on purpose, because the only clock comparison left
    in the backend is `metadata.py`'s cache TTL and an arm over that shape would
    carry a count in a file this rule has no opinion about.

    **The rule is shape only in both directions**, measured: spelling that same
    cache TTL as `expires_at - time.monotonic() < 0` makes this report
    `metadata.py`, correctly by shape and wrongly by meaning. It stays exemption
    free only while nobody writes a non deadline that way.
    `TestTheDoorIsTwoFunctionsWide` is the guard with teeth about the module's
    shape; this one is about its callers.

    **The other half, `in_`, is deliberately not guarded**, because
    `time.monotonic() + x` is spelled identically by a deadline and by a cache
    expiry: `metadata.py` stores a TTL that way and is right to. A rule over
    that shape would either report a correct site or carry a count in a file it
    has no opinion about.
    """

    def test_no_module_computes_its_own_remaining_time(self):
        offenders = [
            f"{path.relative_to(BACKEND)}:{line}"
            for path in _modules_that_could_read_a_clock()
            for line in _works_out_what_is_left(ast.parse(path.read_text()))
        ]

        assert offenders == [], (
            "this works out what is left of a deadline by hand; ask "
            f"deadline.left: {offenders}"
        )

    @pytest.mark.parametrize(
        "source",
        [
            "left = ends - time.monotonic()",
            "left = ends - monotonic()",
            "timeout = min(TIMEOUT, self.deadline - time.monotonic())",
        ],
    )
    def test_the_rule_reports_the_shapes_it_exists_for(self, source: str):
        assert _works_out_what_is_left(ast.parse(source)) == [1]

    @pytest.mark.parametrize(
        "source",
        [
            "spent = time.monotonic() - started",
            "cutoff = now - self._limit.window_seconds",
            "remaining = left(self.deadline)",
        ],
    )
    def test_measuring_elapsed_time_is_not_reported(self, source: str):
        assert _works_out_what_is_left(ast.parse(source)) == []

    def test_it_reads_every_module_that_carries_a_deadline(self):
        """A count is what a widened exclusion walks past: dropping `opds.py`
        from the walk leaves a `> 20` arm green, and `opds` is one of the five
        modules the rule exists for. Named, not counted, for the reason
        `test_adr_depth` gives about a row removed from a table.
        """
        walked = {path.relative_to(BACKEND).as_posix() for path in _modules_that_could_read_a_clock()}

        assert {"authority.py", "covers.py", "fetch.py", "opds.py", "z3950.py"} <= walked
        assert "deadline.py" not in walked
