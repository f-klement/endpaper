"""The budget the generated tests run under, measured rather than declared.

**A property test that runs one example passes in the time a unit test takes
and asserts almost nothing, and nothing in a green suite tells the two apart.**
That is what this file is here to make loud: the example count is the only
thing standing between a property and a very expensive way of calling a
function once, and it lives in a settings object an unrelated edit can lower
without a single test turning red.

So the floor is here, the profiles are in `conftest.py`, and the two are
different numbers on purpose. The floor is what this suite refuses to go below;
a profile is what it currently spends. A guard that read the profile and
compared it against itself would pass at one example.

A lowered profile is only one of the ways the budget goes, so there are two
guards here and they catch different things.

**The count is executed, not read off the settings**, which is what catches a
profile lowered to one and anything else that changes what the run actually
does. It is measured inside a running test, because `max_examples` is an upper
bound and reading it proves only what was declared.

**An `ast` pass catches what a measurement cannot see**, which is a decorator
carrying `max_examples` or `phases` on one test: that lowers that test alone,
so every measurement in this file still reports the profile's number and
nothing fails. It is matched on the keyword rather than on the decorator's
name, for the reason `_lowers_the_budget` gives: the name has three spellings
here and the keyword has one.

**What neither catches is an `assume` that rejects nearly everything**, and it
is left to hypothesis rather than reimplemented: its own `filter_too_much`
health check is the thing that fails on that, and a second rule here would be a
worse copy of one that already exists.
"""

import ast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.conftest import ACTIVE_PROPERTY_PROFILE, PROPERTY_PROFILES
from tests.test_house_rules import BACKEND, _test_sources

#: The fewest examples any profile here may spend on one property.
#:
#: Not a target and not what any profile spends: it is the point below which a
#: property stops being one. **A judgement rather than a measurement**, and the
#: thing it is chosen against is written down so it can be argued with: below
#: roughly fifty examples the generators here stop reaching both sides of the
#: refusal each property is about as a matter of course, and the property
#: degrades into a slower spelling of a single case. What proves a generator
#: still reaches a class is not this number: it is the witness beside each
#: property, in `tests/strategies.py`.
EXAMPLE_FLOOR = 50

#: Where the tests live, which is the tree this file reads.
#:
#: **The walk is the shared one**, not an `rglob` of this directory.
#: `test_house_rules.py` owns what "a directory a tool owns" means, and a rule
#: here that recursed on its own would read the pipeline's `.uv-cache` as part
#: of this project the moment CI put one under `backend/`. That module's own
#: guard refuses a private walk, which is how this line was written the first
#: time and caught.
_TESTS = BACKEND / "tests"


class TestTheBudgetIsSpent:
    @pytest.mark.property
    def test_the_active_profile_really_runs_that_many_examples(self):
        """Counted from inside the test function, which is the only honest place.

        `max_examples` is an upper bound that several other things lower without
        touching it, so a test that reads the number has checked the declaration
        and not the run.
        """
        executed = 0

        @given(st.integers())
        def count_one_example(value: int) -> None:
            nonlocal executed
            executed += 1

        count_one_example()

        assert executed >= EXAMPLE_FLOOR, (
            f"{executed} examples ran, which is below the floor of "
            f"{EXAMPLE_FLOOR}. The profile this tree loaded is "
            f"{ACTIVE_PROPERTY_PROFILE!r}; a command line override or a "
            f"`settings()` on a test wins over it, so read the run before the "
            f"profile."
        )

    def test_every_profile_this_tree_registers_stands_above_the_floor(self):
        """The profile a deep run selects is as easy to lower as the default one."""
        for name in PROPERTY_PROFILES:
            spent = settings.get_profile(name).max_examples
            assert spent >= EXAMPLE_FLOOR, f"profile {name!r} spends {spent} examples"

    def test_the_deep_profile_is_deeper_than_the_one_the_suite_runs(self):
        """Otherwise there is one profile wearing two names, and the deep run is
        something somebody believes they did."""
        assert (
            settings.get_profile("thorough").max_examples
            > settings.get_profile("suite").max_examples
        )


#: The two settings keywords that lower how much a test actually runs.
#:
#: **Named, because the settings API is where the closed set lives.** Every
#: other keyword changes how hypothesis runs a test rather than how much:
#: `deadline`, `database`, `print_blob` and the health checks are all already
#: set by the profiles here, and a test overriding one of those is making a
#: local decision rather than spending less.
_KEYWORDS_THAT_LOWER_THE_BUDGET = ("max_examples", "phases")


def _decorator_names(node: ast.AST) -> list[str]:
    """Every decorator on a node, as the source that was written."""
    return [ast.unparse(decorator) for decorator in node.decorator_list]  # type: ignore[attr-defined]


def _lowers_the_budget(node: ast.AST) -> list[str]:
    """The budget keywords any decorator on this node passes.

    **Matched on the keyword and not on the callee's name**, which is the
    version of this that works. Naming the callee means naming its import
    spelling, and `settings`, `hypothesis.settings` and the alias `conftest.py`
    itself uses are three spellings of one decorator: a rule that knew the
    first two missed the third, which is the one already in the tree for
    somebody to copy. The keyword is what the settings API calls the thing, so
    it is the part that does not depend on how the module was imported.

    The cost of the wider match is a decorator that is not `settings` and
    happens to take one of these names. There is none in the tree, and one
    arriving is worth the look.

    Read off the call's keywords rather than off its source text, so a value
    written as a name, an expression or a number is the same finding.
    """
    found: list[str] = []
    # `getattr`, because this is asked of the enclosing node too and a module
    # carries no decorators. A `ClassDef` and a `FunctionDef` both do.
    for decorator in getattr(node, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        found += [
            keyword.arg
            for keyword in decorator.keywords
            if keyword.arg in _KEYWORDS_THAT_LOWER_THE_BUDGET
        ]
    return found


def _is_generated(names: list[str]) -> bool:
    """Whether hypothesis supplies this function's arguments.

    Matched on the decorator call rather than on a list of import spellings:
    `given(...)` and `hypothesis.given(...)` are one decorator, and which of
    them a file writes is not a property of the test.
    """
    return any(name.split("(", 1)[0].split(".")[-1] == "given" for name in names)


class TestEveryGeneratedTestSaysSo:
    """The marker and the generated tests are one set, kept so by derivation.

    `-m property` is how the cost of these is measured against the rest of the
    suite and how somebody chasing an unrelated failure turns them off for one
    run. Both readings go quietly wrong the moment a generated test is missing
    the marker, and nothing else in the suite notices.
    """

    def _generated(self) -> tuple[list[tuple[str, str, bool, list[str]]], int]:
        """Every collected generated test in the tree, with whether it is marked.

        Only a function pytest would collect: one directly in a module or a
        class, named for collection. A `@given` function nested inside another
        function is a helper that its enclosing test calls, and pytest never
        sees it.
        """
        found: list[tuple[str, str, bool, list[str]]] = []
        modules = 0
        for path in sorted(_test_sources()):
            modules += 1
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for parent in ast.walk(tree):
                if not isinstance(parent, ast.Module | ast.ClassDef):
                    continue
                on_the_class = (
                    _decorator_names(parent) if isinstance(parent, ast.ClassDef) else []
                )
                for node in ast.iter_child_nodes(parent):
                    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                        continue
                    if not node.name.startswith("test"):
                        continue
                    own = _decorator_names(node)
                    if not _is_generated(own):
                        continue
                    marked = "pytest.mark.property" in own + on_the_class
                    lowered = _lowers_the_budget(node) + _lowers_the_budget(parent)
                    found.append(
                        (str(path.relative_to(_TESTS)), node.name, marked, lowered)
                    )
        return found, modules

    def test_the_walk_finds_the_tree_it_is_about(self):
        """**The vacuity arm, and it is the half that ages.** The assertion below
        is over a list, so a walk that finds nothing passes it while reporting
        that the rule holds everywhere. Both numbers here are floors rather than
        counts, because a count beside a growing tree is a figure somebody has to
        keep true and nobody does."""
        found, modules = self._generated()
        assert modules > 50, f"only {modules} test modules found under {_TESTS}"
        assert found, "no generated tests found at all, so the rule below is vacuous"

    def test_every_generated_test_carries_the_marker(self):
        found, _ = self._generated()
        missing = [f"{path}::{name}" for path, name, marked, _ in found if not marked]
        assert not missing, (
            "these tests take generated inputs and are not marked `property`, "
            f"so `-m property` under-reports them: {missing}"
        )

    def test_no_test_spends_less_than_the_profile_it_runs_under(self):
        """**The arm a measurement cannot reach.** Everything else here reads
        the settings the run as a whole is using, and a `settings()` on one
        test lowers that test alone: the profile is untouched, the executed
        count is untouched, and the test quietly stops exercising anything.

        Refused rather than checked against the floor, because a number here
        would be a second budget to keep true. A test that genuinely needs its
        own example count is a conversation, not an edit.
        """
        found, _ = self._generated()
        lowered = [
            f"{path}::{name} sets {keywords}"
            for path, name, _, keywords in found
            if keywords
        ]
        assert not lowered, (
            "these tests override the example budget for themselves, so no "
            f"measurement of the profile describes what they ran: {lowered}"
        )
