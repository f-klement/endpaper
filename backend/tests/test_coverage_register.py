"""`COVERAGE.md` has a row for every test file it may name, and every test file runs.

**The rows are the register, and a person writes them.** What each file covers is
what a reader comes for, and no run can write it. So the document carries no
figure at all: a count beside a row moved on every branch that added a test,
which made the register red by construction until somebody rewrote the figure,
and nobody read the figures. The run prints its own totals.

**What is checked is the partition and that each file runs.** A test file in the
tree either has a row here or declares itself internal, because a published
register may not name a file the publish gate strips. And a test file the run
reached collects at least one test, or, named as needing a real server, ends
its own collection on SQLite; a file collecting nothing in silence is a row
describing tests that do not exist.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import pytest

from database import engine
from tests.corpus import suite_modules
from tests.declaration import declares_itself_internal

TREE_GUARDS = {
    "TestEveryTestFileHasARowAndRuns": ("suite_modules",),
    "TestTheCensusMeasuresRatherThanAgrees": ("suite_modules",),
    "TestWhatSilenceIsJudgedOn": ("suite_modules",),
}

TESTS = Path(__file__).resolve().parent
REGISTER = TESTS / "COVERAGE.md"

#: How a test file says it needs a real server: the three that do end their
#: own collection on SQLite. **A module skip is excused under this name and no
#: other**, so a file quarantined with one elsewhere is reported on the default
#: run rather than only by the nightly Postgres one.
SERVER_ONLY = "_on_a_real_server.py"

#: A row: a backticked path alone in the first cell. Read inside that cell, so a
#: path quoted in a description is not a row of its own.
_ROW = re.compile(r"^\|[ \t]*`([^`]+)`[ \t]*\|", re.MULTILINE)


def rows(text: str) -> list[str]:
    """The path of every row of the register's table, in the document's order."""
    return _ROW.findall(text)


@dataclass(frozen=True)
class Census:
    """What the running suite collected, by file, beside the tree it ran over."""

    #: Collected tests per file, from `session.items`.
    counts: dict[str, int]
    #: Every file in the tree whose name the collector reads as a test module,
    #: whether or not this run reached it.
    on_disk: frozenset[str]

    @classmethod
    def of(cls, session: pytest.Session) -> Census:
        counts: dict[str, int] = {}
        for item in session.items:
            where = Path(item.path).relative_to(TESTS).as_posix()
            counts[where] = counts.get(where, 0) + 1
        # The naming rule is read from the configuration rather than written
        # here. A project that renamed its test files would otherwise leave this
        # set empty and every rule below passing on nothing.
        patterns = session.config.getini("python_files")
        return cls(
            counts=counts,
            on_disk=frozenset(
                path.relative_to(TESTS).as_posix()
                for path in suite_modules()
                if any(fnmatch(path.name, pattern) for pattern in patterns)
            ),
        )


@dataclass(frozen=True)
class Silence:
    """The test files a run reached and collected nothing from, and the ones it cannot judge."""

    #: Reached, nothing deselected from it, no test collected, and its
    #: collection did not end on an engine that cannot run it. Each is a defect.
    empty: list[str]
    #: Not reached by this run, or narrowed inside by a deselection. A narrowed
    #: run says nothing about these, either way.
    unjudged: list[str]


def silence(
    census: Census,
    reached: Mapping[str, str],
    narrowed: Collection[str],
    *,
    on_sqlite: bool,
) -> Silence:
    """Which test files collected nothing, judged only where the run can answer.

    `reached` maps each test module this run collected to its collection's
    outcome, and `narrowed` holds the files it deselected a test from, both
    keyed like `census.on_disk`. **Reached is the run's own report**,
    not a comparison of file sets: a file collecting nothing is reached with no
    items, where a narrowed run never reaches the file at all. Comparing the two
    file sets instead is what let one file collecting nothing make a whole run
    read as narrowed and switch every count check off.

    **A module ending its own collection is excused on SQLite only, and only
    under a name ending `SERVER_ONLY`.** The files that need a real server skip
    themselves at module level there, and the pipeline's Postgres runs collect
    them. The same skip on Postgres, or under any other name, is a file
    switched off, and is reported.
    """
    empty: list[str] = []
    unjudged: list[str] = []
    for path in sorted(census.on_disk):
        collected = census.counts.get(path, 0)
        if path not in reached or path in narrowed:
            unjudged.append(path)
        elif collected == 0 and not (on_sqlite and reached[path] == "skipped" and path.endswith(SERVER_ONLY)):
            empty.append(path)
    return Silence(empty=empty, unjudged=unjudged)


def whole_run(args_source: pytest.Config.ArgsSource, option: argparse.Namespace) -> bool:
    """Whether this run asked for every test file, so every one must be reached.

    The suite's own `testpaths` with nothing on the command line narrowing them,
    which is how `test:backend` and `nightly:postgres` invoke it. **On such a run
    a file left unreached is not a narrowing anybody asked for**: a
    `collect_ignore`, a `pytest_ignore_collect` hook or a plugin dropping items
    switched it off, and the rule below would otherwise skip in silence.
    """
    return args_source is pytest.Config.ArgsSource.TESTPATHS and not any(
        getattr(option, name, None) for name in NARROWING_OPTIONS
    )


#: pytest's own names for the options that narrow a run, as `config.option`
#: carries them. A name pytest renamed would read as never set, so a narrowed
#: run would be judged whole: `test_each_narrowing_name_is_one_pytest_sets`.
NARROWING_OPTIONS = ("keyword", "markexpr", "deselect", "ignore", "ignore_glob", "lf", "stepwise")


@pytest.fixture(scope="module")
def register() -> str:
    return REGISTER.read_text(encoding="utf-8")


@pytest.fixture
def census(request: pytest.FixtureRequest) -> Census:
    """This run, as a count per file.

    `request.session.items` under xdist is the **whole** collection rather than
    this worker's share of it: every worker collects the suite and the
    controller hands out indices into that list.
    """
    return Census.of(request.session)


def _under_tests(root: Path, nodeid: str) -> str | None:
    """A node id's file keyed like `Census.on_disk`, or None outside the test tree.

    A node id is relative to the rootdir, which is the backend and not the tree.
    """
    whole = root / nodeid.split("::", 1)[0]
    return whole.relative_to(TESTS).as_posix() if whole.is_relative_to(TESTS) else None


@pytest.fixture
def reached(collected_modules: dict[str, str], request: pytest.FixtureRequest) -> dict[str, str]:
    """`collected_modules`, keyed by the path under the test tree."""
    keyed = {
        _under_tests(request.config.rootpath, nodeid): outcome
        for nodeid, outcome in collected_modules.items()
    }
    return {path: outcome for path, outcome in keyed.items() if path is not None}


@pytest.fixture
def narrowed(deselected_items: list[str], request: pytest.FixtureRequest) -> set[str]:
    """The files this run deselected a test from, keyed by the path under the test tree."""
    keyed = {_under_tests(request.config.rootpath, nodeid) for nodeid in deselected_items}
    return {path for path in keyed if path is not None}


class TestEveryTestFileHasARowAndRuns:
    def test_every_row_names_a_file_the_tree_has(self, census: Census, register: str) -> None:
        """A row whose file is gone describes nothing, and reads as coverage."""
        gone = sorted(set(rows(register)) - census.on_disk)

        assert gone == [], (
            f"these rows name files the test tree does not have: {gone}. A file "
            "that is gone loses its row; one that was renamed keeps its "
            "description."
        )

    def test_no_file_is_given_two_rows(self, register: str) -> None:
        """Two descriptions of one file drift apart, and one of them is wrong."""
        named = rows(register)
        twice = sorted({path for path in named if named.count(path) > 1})

        assert twice == [], f"these files carry more than one row: {twice}"

    def test_every_file_with_no_row_is_one_the_register_may_not_name(
        self, census: Census, register: str
    ) -> None:
        """A test file carries a row or declares itself internal.

        **Named, never absorbed into a count**: a count of the files with no
        row is satisfied by any file, so the next undescribed one lands by
        editing a digit. The publish gate holds the other end, refusing to
        publish a file carrying the declaration.

        **Asked of the walk rather than of the collection**, so a file
        collecting no test still has to answer, and narrowing a run cannot
        switch this off. It is the only rule in the tree requiring a stripped
        test file to carry the declaration.
        """
        named = set(rows(register))
        undescribed = [
            path for path in sorted(census.on_disk - named) if not declares_itself_internal(TESTS / path)
        ]

        assert undescribed == [], (
            "these files are in the test tree, carry no row in COVERAGE.md and "
            f"are not stripped from the published tree: {undescribed}. Give each "
            "one a row saying what it covers."
        )

    def test_every_test_file_this_run_reached_collects_a_test(
        self,
        census: Census,
        reached: dict[str, str],
        narrowed: set[str],
        request: pytest.FixtureRequest,
    ) -> None:
        """A file collecting nothing is a row describing tests that do not run.

        **Judged file by file, so a narrowed run hides nothing it reached.** A
        file this run did not reach, or narrowed inside, is left out and named
        in a skip; a file it reached is judged whatever else was narrowed.
        **On a whole run nothing may be left out**, so there the skip is a
        failure instead.

        **What it lets through**: a file under the server only name switched
        off by a module level skip on SQLite, which the nightly Postgres run
        reports (the one Postgres job that runs this arm), and, on a narrowed
        run, a file the collector was told to ignore.
        """
        config = request.config
        found = silence(census, reached, narrowed, on_sqlite=engine.dialect.name == "sqlite")

        assert found.empty == [], (
            f"these test files collected no test: {found.empty}. A file that "
            "collects nothing reads as coverage it does not give; give it a test "
            "or delete it with its row. A file that needs a real server ends its "
            f"name `{SERVER_ONLY}`, and only such a file may skip itself on SQLite."
        )
        assert not (found.unjudged and whole_run(config.args_source, config.option)), (
            f"this run asked for every test file and never reached, or narrowed "
            f"inside, these: {found.unjudged}. Something switched them off without "
            "a command line asking for it: a `collect_ignore`, an ignore hook or a "
            "plugin dropping items. Delete the file with its row, or make it run."
        )
        if found.unjudged:
            pytest.skip(
                f"this run did not reach {len(found.unjudged)} test files, or narrowed "
                f"inside them, so it cannot say whether they collect a test: "
                f"{found.unjudged[:5]}"
            )

    @pytest.mark.sqlite_only(reason="the default run is on SQLite, and a Postgres run skips the SQLite marks")
    def test_nothing_collected_is_skipped_or_left_expected_to_fail(
        self, request: pytest.FixtureRequest
    ) -> None:
        """A file whose every test carries a skip collects, and runs nothing.

        So the rule above would pass it, and this is what closes that. It reads
        markers, so a `pytest.skip()` called inside a test body is not covered:
        the run's own summary line is where that one shows up.
        """
        marked = sorted(
            f"{Path(item.path).relative_to(TESTS).as_posix()}::{item.name} ({marker})"
            for item in request.session.items
            for marker in ("skip", "skipif", "xfail")
            if item.get_closest_marker(marker) is not None
        )

        assert marked == [], f"these tests are collected and would not run: {marked}"


class TestTheCensusMeasuresRatherThanAgrees:
    """The instruments under the rules above, each re-derived once.

    Every rule above compares the document or the run with `counts`, `on_disk`
    and `reached`, and would compare them just as happily if any were a
    constant.
    """

    def test_the_census_counts_every_item_this_run_collected(
        self, census: Census, request: pytest.FixtureRequest
    ) -> None:
        """One `continue` planted in the loop of `Census.of` once took a whole
        run green with nothing red, so the transform is re-derived here."""
        collected = {Path(item.path).relative_to(TESTS).as_posix() for item in request.session.items}

        assert sum(census.counts.values()) == len(request.session.items)
        assert set(census.counts) == collected

    def test_the_census_drops_only_what_the_naming_rule_drops(
        self, census: Census, request: pytest.FixtureRequest
    ) -> None:
        """`on_disk` is the shared walk intersected with a pattern match, and a
        narrowing written into the match drops a file from every rule above."""
        patterns = request.session.config.getini("python_files")
        walked = {path.relative_to(TESTS).as_posix() for path in suite_modules()}
        named = {path for path in walked if any(fnmatch(Path(path).name, pattern) for pattern in patterns)}

        assert set(census.on_disk) == named, sorted(set(census.on_disk) ^ named)
        # Anti vacuity: with every walked file matching, the equality would hold
        # over a comprehension that filters nothing.
        assert walked - named

    def test_the_walk_reads_a_tree_rather_than_the_collection(self, tmp_path: Path) -> None:
        """`on_disk` and `reached` are two instruments, and a rule comparing one
        list with itself passes on any tree."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_planted.py").write_text("def test_nothing(): ...")
        (tmp_path / "tests" / "helpers.py").write_text("")

        found = {path.name for path in suite_modules(tmp_path)}

        assert found == {"test_planted.py", "helpers.py"}

    def test_the_run_reports_reaching_the_module_asking(self, reached: dict[str, str]) -> None:
        """A hook nobody calls reads as a run that reached nothing, which skips
        the rule above on every run: the silent direction. This module is
        running, so it was reached."""
        assert reached.get(Path(__file__).name) == "passed", sorted(reached)[:5]


def _planted(counts: dict[str, int], on_disk: set[str]) -> Census:
    return Census(counts=counts, on_disk=frozenset(on_disk))


class TestWhatSilenceIsJudgedOn:
    """`silence` driven against runs this file made up, so that neutering a
    predicate reds an arm of its own: on the live tree every answer is empty."""

    def test_a_reached_file_with_no_test_is_empty(self) -> None:
        found = silence(
            _planted({"test_a.py": 3}, {"test_a.py", "test_b.py"}),
            {"test_a.py": "passed", "test_b.py": "passed"},
            set(),
            on_sqlite=True,
        )

        assert (found.empty, found.unjudged) == (["test_b.py"], [])

    def test_a_file_the_run_did_not_reach_is_unjudged(self) -> None:
        found = silence(
            _planted({"test_a.py": 3}, {"test_a.py", "test_b.py"}),
            {"test_a.py": "passed"},
            set(),
            on_sqlite=True,
        )

        assert (found.empty, found.unjudged) == ([], ["test_b.py"])

    def test_a_file_narrowed_inside_is_unjudged(self) -> None:
        found = silence(
            _planted({"test_a.py": 3}, {"test_a.py", "test_b.py"}),
            {"test_a.py": "passed", "test_b.py": "passed"},
            {"test_b.py"},
            on_sqlite=True,
        )

        assert (found.empty, found.unjudged) == ([], ["test_b.py"])

    def test_a_server_only_module_ending_its_own_collection_is_excused_on_sqlite(self) -> None:
        pg = f"test_pg{SERVER_ONLY}"
        found = silence(_planted({}, {pg}), {pg: "skipped"}, set(), on_sqlite=True)

        assert (found.empty, found.unjudged) == ([], [])

    def test_a_server_only_module_ending_its_own_collection_elsewhere_is_empty(self) -> None:
        pg = f"test_pg{SERVER_ONLY}"
        found = silence(_planted({}, {pg}), {pg: "skipped"}, set(), on_sqlite=False)

        assert (found.empty, found.unjudged) == ([pg], [])

    def test_any_other_module_ending_its_own_collection_on_sqlite_is_empty(self) -> None:
        """A module skip is the one honest edit that quarantines a file, so it
        is excused only where the name says the file needs a server."""
        found = silence(_planted({}, {"test_isbn.py"}), {"test_isbn.py": "skipped"}, set(), on_sqlite=True)

        assert (found.empty, found.unjudged) == (["test_isbn.py"], [])

    def test_every_live_server_only_file_carries_the_name(self) -> None:
        """Anti vacuity for the name: a suffix nothing in the tree carries
        would excuse nothing, and every real server file would read as empty
        on SQLite. Measured the other way by the live rule."""
        assert any(path.name.endswith(SERVER_ONLY) for path in suite_modules())


def _option(**narrowing: object) -> argparse.Namespace:
    blank: dict[str, object] = {
        "keyword": "",
        "markexpr": "",
        "deselect": None,
        "ignore": None,
        "ignore_glob": None,
        "lf": False,
        "stepwise": False,
    }
    return argparse.Namespace(**(blank | narrowing))


class TestWhatAWholeRunIs:
    """`whole_run` against made up invocations, so a narrowing it stops
    reading reds an arm rather than refusing every narrowed run."""

    def test_the_testpaths_alone_are_a_whole_run(self) -> None:
        assert whole_run(pytest.Config.ArgsSource.TESTPATHS, _option())

    def test_files_named_on_the_command_line_are_not(self) -> None:
        assert not whole_run(pytest.Config.ArgsSource.ARGS, _option())

    @pytest.mark.parametrize(
        "narrowing",
        [
            {"keyword": "isbn"},
            {"markexpr": "property"},
            {"deselect": ["tests/test_isbn.py::test_x"]},
            {"ignore": ["tests/test_isbn.py"]},
            {"ignore_glob": ["*isbn*"]},
            {"lf": True},
            {"stepwise": True},
        ],
        ids=["k", "m", "deselect", "ignore", "ignore_glob", "lf", "stepwise"],
    )
    def test_a_command_line_narrowing_is_not(self, narrowing: dict[str, object]) -> None:
        assert not whole_run(pytest.Config.ArgsSource.TESTPATHS, _option(**narrowing))

    def test_each_narrowing_name_is_one_pytest_sets(self, request: pytest.FixtureRequest) -> None:
        """The arms above read a made up namespace, so this one holds its names
        to the namespace this pytest really builds."""
        assert [name for name in NARROWING_OPTIONS if not hasattr(request.config.option, name)] == []


class TestTheDocumentIsReadRatherThanAssumed:
    """The reader's own failure modes, each one that reads nothing in silence."""

    def test_a_padded_row_is_read(self) -> None:
        assert rows("| `test_a.py`   | What it covers |\n") == ["test_a.py"]

    def test_a_row_in_a_nested_directory_keeps_its_path(self) -> None:
        assert rows("| `routers/test_books.py` | Listing |\n") == ["routers/test_books.py"]

    def test_a_path_quoted_in_a_description_is_not_a_row(self) -> None:
        assert rows("| `test_a.py` | the sibling of `test_b.py` |\n") == ["test_a.py"]

    def test_a_table_whose_first_cell_is_not_a_path_yields_no_row(self) -> None:
        assert rows("| File | Covers |\n|---|---|\n") == []
