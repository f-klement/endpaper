"""Tests for backend/deadline.py.

`covers` and `z3950` had each grown a private helper for "how long is left",
and `z3950` and `fetch` spelled the same subtraction inline: four sites, two
spellings of the clock. What is pinned here is the arithmetic, the clock it
reads, **the width of the door** and the vocabulary: the third is the one that
bought this module its shape, because a single narrowing function would have
made `z3950`'s ceiling satisfiable by construction and the refusal behind it
dead, and the fourth is there because a deadline and a duration are both
`float` and only the name tells them apart.
"""

import ast
import inspect
import time
from pathlib import Path
from types import ModuleType
from typing import Final

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




#: Words that make a name a length of time rather than a moment.
#:
#: **Two, and both are conventions with a count rather than spellings somebody
#: chose once.** `_SECONDS` ends nineteen module constants here under fifteen
#: distinct names, five of them `DEADLINE_SECONDS`; `timeout` is what the
#: standard library calls the slot a duration is spent in (`asyncio.wait`,
#: `asyncio.wait_for`) and what seven of this tree's own constants are called
#: under three names.
#:
#: **A third word is admissible only where the tree mandates it for one
#: meaning**, which `remaining` looked like and is not: `deadline.py` names it
#: for the figure `left` returns, and the same word binds two row counts in
#: `routers/books.py` and two schema fields in `schemas/book.py`. A word added
#: to make one site report, or to keep one quiet, is the signal this has
#: stopped being derived.
_DURATION_WORDS: Final = ("seconds", "timeout")


def _what_a_name_means(name: str) -> str | None:
    """`a duration`, `a moment`, or `None` where the name is about neither.

    **Duration first, and the constants depend on that order rather than the
    other way round.** A name carrying both words is a duration and is reported
    wherever it meets a deadline slot, rather than classified as a moment and
    read as agreeing with one. `SEARCH_DEADLINE_SECONDS` is that name, and this
    line is why the five `DEADLINE_SECONDS` constants keep theirs.
    """
    low = name.lower()
    if any(word in low for word in _DURATION_WORDS):
        return "a duration"
    return "a moment" if "deadline" in low else None


def _what_an_expression_means(node: ast.expr) -> str | None:
    """Only a bare name or an attribute says what it holds.

    A call, an arithmetic expression or a literal is left unclassified because
    nothing can be read off a name it does not have, not because its meaning is
    unclear: `opds.py`'s `min(ends, in_(fetch.TIMEOUT_SECONDS))` is the earlier
    of two moments and is correct where it stands. A rule that guessed from the
    words inside it would report that site and need an exemption for it.
    """
    if isinstance(node, ast.Name):
        return _what_a_name_means(node.id)
    if isinstance(node, ast.Attribute):
        return _what_a_name_means(node.attr)
    return None


def _dotted(path: Path) -> str:
    """`routers/opds.py` as `routers.opds`, which is how it is imported.

    **Not the stem.** Nine stems collide here and `opds` is three of them, so a
    table keyed on the basename holds whichever file the walk yielded last and
    answers for the wrong module. Found by the security seat against a first
    version that did exactly that: `opds.holdings`, the precedent this rule
    cites for its own name, resolved to `routers/opds.py` and was unresolvable.
    """
    return path.relative_to(BACKEND).with_suffix("").as_posix().replace("/", ".")


def _positional_names(tree: ast.AST) -> dict[str, list[str] | None]:
    """Each function in one module by name, with the names of its positional
    parameters. `None` where one module defines that name twice differently,
    which is the conservative direction: unresolved is a miss, never a report.
    """
    found: dict[str, list[str] | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            taken = [arg.arg for arg in node.args.posonlyargs + node.args.args]
            if taken[:1] in (["self"], ["cls"]):
                taken = taken[1:]
            found[node.name] = taken if found.get(node.name, taken) == taken else None
    return found


def _what_this_module_imported(
    tree: ast.AST, ours: set[str]
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Modules of ours by the alias bound here, then functions of ours the same way.

    **Both halves are needed and each covers what the other cannot.** Every
    importer of `deadline` writes `from deadline import in_, left`, so a rule
    reading only `module.function` calls resolves none of the sites the module
    exists for. And a call written `deadline.left(...)` resolves only through
    the module half.

    **A function is carried as the name it has where it is defined**, not the
    alias it is called by: `from covers import fetch_cover as store` then
    `store(...)` is not `covers.store`, and looking the alias up in the target
    module answers with a signature the call never reaches. Found by the
    security seat against the round that added this half; no live instance, and
    the first aliased import into a module that carries a deadline is what it
    would have cost.

    **A name is followed only where an `import` bound it and nothing else in the
    file did.** 181 bindings in the backend, under twenty one distinct names,
    carry the name of a top level module of ours, `covers`, `fetch`, `metadata`
    and `deadline` among them, so following a bare `covers.f(...)` on the name
    alone is one `covers = ...` away from answering for a module that is not
    there. A false report is how a guard earns an exemption and an exemption is
    how it dies.

    **What counts as bound is read off the grammar rather than listed.** A
    Store or Del context covers assignment, `for`, `with ... as` and the walrus;
    every other binder in Python spells its name as a plain string in a `name`
    or `rest` field, which is `def`, `class`, `except ... as` and all three
    `match` captures at once. Listing the statements instead is the enumeration
    this repository keeps paying for: the first version of this had two arms and
    was silent on `class covers:` and on `except Exception as covers:`, both
    measured. `ast.alias` is the one node excluded, because its `name` is what an
    import is reading rather than a rebinding of it.
    """
    modules: dict[str, str] = {}
    functions: dict[str, tuple[str, str]] = {}
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {
                alias.asname or alias.name: alias.name for alias in node.names if alias.name in ours
            }
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if node.module in ours:
                functions |= {
                    alias.asname or alias.name: (node.module, alias.name) for alias in node.names
                }
            modules |= {
                alias.asname or alias.name: f"{node.module}.{alias.name}"
                for alias in node.names
                if f"{node.module}.{alias.name}" in ours
            }
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            assigned.add(node.id)
        elif isinstance(node, ast.arg):
            assigned.add(node.arg)
        elif not isinstance(node, ast.alias):
            assigned |= {
                bound
                for field in ("name", "rest")
                if isinstance(bound := getattr(node, field, None), str)
            }
    return (
        {alias: name for alias, name in modules.items() if alias not in assigned},
        {alias: where for alias, where in functions.items() if alias not in assigned},
    )


def _words_crossed(
    tree: ast.AST, ours: dict[str, dict[str, list[str] | None]]
) -> list[tuple[int, str]]:
    """Every argument bound to a slot that means the other thing.

    **The keyword arm needs no resolution at all** and is the one with teeth
    against the standard library: `wait(timeout=deadline)` names its own
    parameter, whoever wrote `wait`.

    **The positional arm follows three shapes and nothing else**: a call to a
    function defined in this module, a call to one imported from a module of
    ours, and a call through a module alias an `import` bound here. A call on a
    value (`self.method(...)`, `row.get(...)`) is not followed, because the
    receiver is a name this cannot resolve.
    """
    local = _positional_names(tree)
    modules, functions = _what_this_module_imported(tree, set(ours))
    crossed: list[tuple[int, str]] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        bound: list[tuple[str, ast.expr]] = [
            (kw.arg, kw.value) for kw in call.keywords if kw.arg is not None
        ]
        func = call.func
        taken: list[str] | None = None
        if isinstance(func, ast.Name):
            taken = local.get(func.id)
            if taken is None and func.id in functions:
                where, called = functions[func.id]
                taken = ours[where].get(called)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in modules:
                taken = ours[modules[func.value.id]].get(func.attr)
        bound += list(zip(taken or [], call.args, strict=False))
        for slot, value in bound:
            means_slot = _what_a_name_means(slot)
            means_value = _what_an_expression_means(value)
            if means_slot and means_value and means_slot != means_value:
                crossed.append(
                    (
                        call.lineno,
                        f"{slot}={ast.unparse(value)} passes {means_value} to {means_slot}",
                    )
                )
    return crossed


class TestTheTwoWordsDoNotMix:
    """House rule: a name says a moment or a length of time, and a call may not
    swap one for the other.

    Both are `float`, so nothing but the name separates them and no type checker
    will ever report the swap. It reads correctly on either input, which is what
    makes the name the whole of the defence. `metadata._within_deadline` spends
    its argument at `asyncio.wait(timeout=)`: as a duration that bounds the fan
    out at 4.0s, and a `deadline.in_` result spent in the same slot is read as
    its own magnitude, measured 6,002,988 on the machine this was written on, so
    the bound moves to whatever the transports concede. **Which is 10.0s today
    rather than forever**, because `fetch.TIMEOUT_SECONDS` and
    `z3950.TIMEOUT_SECONDS` each cap one request, and it is forever the day an
    adapter ships without a ceiling of its own: the same correction
    `SEARCH_HARDER_DEADLINE_SECONDS` already makes about its own margin. Nothing
    raises either way. What an operator loses is one log line, "%d catalogue(s)
    missed the search deadline", which simply stops firing.

    **The partition is the tree's, not a new opinion.** Thirty two parameters are
    named `deadline` and every one of them carries a moment; two are named
    `deadline_seconds` and both carry a duration. `metadata._within_deadline` was
    the single crossing, which is why this is a rule rather than a convention
    somebody hopes holds.

    **Derived from the two vocabularies rather than from the shapes a duration
    can take.** An earlier draft asked whether the argument was a `_SECONDS`
    constant or a numeric literal, which is a list of spellings and would have
    needed a new arm for the next one. This asks only whether the two names
    agree, so it catches the swap from either end: renaming the parameter back
    reports the body at `timeout=deadline` **and** the call site at
    `_within_deadline(..., deadline_seconds)`.

    **What it cannot see**, stated rather than papered over.

    * **A duration whose name carries neither word.** Two shapes, both live.
      `deadline.py` mandates `remaining` for the figure `left` returns, seven
      sites in three modules, and the same word binds two row counts in
      `routers/books.py` and two schema fields in `schemas/book.py`, so
      `remaining` cannot join `_DURATION_WORDS` without reporting those. And
      eight module constants carry their unit instead of `_SECONDS`, in
      `accounts`, `auth`, `notifications` and two `schemas` modules, spelled
      `_TTL`, `_MINUTES`, `_HOURS` and `_DAYS`; five of them are plain `int`, so
      `deadline=BROKEN_AFTER_HOURS` type checks as well as passing here.
      **Renaming both ends to a word outside the vocabulary evades this rule
      entirely**, and that is the price of deriving from what the tree says
      rather than enumerating how a duration can be written.
    * **A value reaching a slot through anything but a name**, which is a
      `*args`, a dataclass field, or a local bound from an expression this
      cannot classify.
    * **The test tree**, which `_python_sources` excludes. The spies in
      `test_metadata.py` mirror this signature and are outside the walk.

    `TestTheDoorIsTwoFunctionsWide` guards the module's shape,
    `TestNoModuleWorksOutWhatIsLeftForItself` guards the arithmetic, and this
    one guards the vocabulary.
    """

    def test_no_call_passes_a_duration_where_a_moment_is_named(self):
        trees = {path: ast.parse(path.read_text()) for path in _python_sources()}
        ours = {_dotted(path): _positional_names(tree) for path, tree in trees.items()}
        offenders = [
            f"{path.relative_to(BACKEND)}:{line}: {why}"
            for path, tree in trees.items()
            for line, why in _words_crossed(tree, ours)
        ]

        assert offenders == [], (
            "a deadline and a duration are both floats and only the name tells "
            f"them apart; read this class's docstring: {offenders}"
        )

    @pytest.mark.parametrize(
        "source",
        [
            "wait(tasks, timeout=deadline)",
            "asyncio.wait_for(work, timeout=self.deadline)",
            "run(seconds=deadline)",
            "hold(deadline=budget_seconds)",
            "hold(deadline=fetch.TIMEOUT_SECONDS)",
        ],
    )
    def test_the_rule_reports_a_swap_in_either_direction(self, source: str):
        assert _words_crossed(ast.parse(source), {}) != []

    @pytest.mark.parametrize(
        "source",
        [
            "wait(tasks, timeout=deadline_seconds)",
            "hold(deadline=deadline)",
            "hold(deadline=self.deadline)",
            "association(deadline=min(ends, in_(TIMEOUT_SECONDS)))",
            "wait(tasks, timeout=0.05)",
            "get(url, timeout=budget)",
        ],
    )
    def test_a_name_that_agrees_or_says_nothing_is_not_reported(self, source: str):
        assert _words_crossed(ast.parse(source), {}) == []

    @pytest.mark.parametrize(
        "source",
        [
            "import metadata\nmetadata.hold(work, deadline_seconds)",
            "from metadata import hold\nhold(work, deadline_seconds)",
        ],
    )
    def test_the_positional_arm_follows_a_call_through_either_kind_of_import(self, source: str):
        """The arm the keyword one cannot cover: `_within_deadline`'s caller
        passes its budget positionally, so a parameter renamed back to `deadline`
        is reported at the call site as well as inside the body. Both spellings,
        because every importer of `deadline` uses the second one.
        """
        callee = {"metadata": _positional_names(ast.parse("def hold(searches, deadline): ..."))}

        assert _words_crossed(ast.parse(source), callee) != []

    @pytest.mark.parametrize(
        "rebinding",
        [
            "covers = open_the_box()",
            "for covers in shelves: pass",
            "def covers(): ...",
            "class covers: ...",
            "try: pass\nexcept Exception as covers: pass",
            "match row:\n    case {**covers}: pass",
        ],
    )
    def test_a_name_something_else_rebound_is_not_followed(self, rebinding: str):
        """181 bindings here, under twenty one distinct names, carry the name of a
        top level module of ours. A rule that followed the name alone would
        report a call on a value, and an exemption for that is how this rule
        would stop being one.

        **Six shapes because the first version read two**, and the security seat
        ran `class` and `except ... as` through it. What replaced the two arms
        is not six arms: it is the grammar's own `name` and `rest` fields, which
        every one of these but the first two spells its binding in.
        """
        callee = {"covers": _positional_names(ast.parse("def store(url, deadline): ..."))}
        shadowed = f"import covers\n{rebinding}\ncovers.store(url, deadline_seconds)"

        assert _words_crossed(ast.parse(shadowed), callee) == []

    def test_a_function_is_resolved_by_its_own_name_and_not_by_its_alias(self):
        """`from covers import fetch_cover as store` is not `covers.store`, and
        answering with that signature is a report against a function the call
        never reaches. Found by the security seat against the round that added
        the symbol import arm.
        """
        callee = {"covers": _positional_names(ast.parse("def store(url, deadline): ..."))}
        aliased = "from covers import fetch_cover as store\nstore(url, deadline_seconds)"

        assert _words_crossed(ast.parse(aliased), callee) == []

    def test_it_reads_the_modules_that_carry_a_deadline_and_the_one_that_defines_it(self):
        """Named rather than counted, for the reason the sibling rule gives: a
        widened exclusion walks past a module and leaves a count green.
        `deadline.py` is inside this walk where it is outside the other one,
        because the vocabulary rule has no exemption to make for the module that
        owns the word. `routers.opds` is named because the stem it shares with
        `opds` is what the first version of `_dotted` got wrong.
        """
        walked = {_dotted(path) for path in _python_sources()}

        assert {
            "authority",
            "covers",
            "deadline",
            "fetch",
            "metadata",
            "opds",
            "routers.opds",
            "z3950",
        } <= walked
