"""`COVERAGE.md` states what the run reading it collected.

**The register is checked against the suite it describes, never recounted.** Its
headline, its shortfall and every row's count were maintained by hand until
2026-09-20, and on that day the headline was 102 out, one row 3 out and the
shortfall 99 out, on a tree whose last commit said all three had just been
recounted off one run with two instruments. Three parties recounted this file in
two days and each left a different figure wrong. The defect is none of those
numbers: it is that a register whose whole purpose is to be checkable was
maintained by retyping figures.

**The instrument is the run itself**, which is why nothing here shells out to a
second pytest and no figure is written down below. `session.items` is the
collection this process is executing, so a file's count cannot disagree with the
run unless something narrowed it, and the `whole_tree` fixture refuses the
comparison when that has happened.

**The descriptions are the point of the register and are never generated.** What
each file covers is what a person writes and is most of what the document is
worth. So the row set is read out of the document and only the column beside it
is recomputed, which is the arrangement the generated depth table in this
repository's architecture decisions already uses.

**Some of the collected files may appear in the register nowhere**, because the
publish gate strips them and a published file that points at a stripped path
fails the gate. How many is in the generated block and not in this sentence,
which is the rule this file exists to enforce, applied to itself. That number
is derived from the declaration an internal file carries, which the gate
refuses to publish, rather than from a list of names this published file could
not carry either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import pytest

from tests.test_house_rules import _test_sources
from tests.test_roster_counts import declares_itself_internal

TESTS = Path(__file__).resolve().parent
REGISTER = TESTS / "COVERAGE.md"

#: The generated block's fences, spelled as the depth table's are, because a
#: reader who has seen one should recognise the other.
BEGIN = "<!-- measured: begin -->"
END = "<!-- measured: end -->"

#: A row of the table: a backticked path in the first cell, a count in the
#: second. Both are matched inside their own cell, which is the distinction the
#: roster census had to learn the hard way: a number reached across a `|` is a
#: claim about the next column.
_ROW = re.compile(r"^\|[ \t]*`([^`]+)`[ \t]*\|[ \t]*(\d+)[ \t]*\|", re.MULTILINE)


def rows(text: str) -> list[tuple[str, int]]:
    """Every row of the register's table, in the document's own order."""
    return [(path, int(count)) for path, count in _ROW.findall(text)]


def split(text: str) -> tuple[str, str, str]:
    """The document either side of the generated block.

    A missing fence raises rather than yielding an empty block: a guard whose
    input has gone missing has stopped guarding, and this one would otherwise
    pass by comparing nothing with nothing.
    """
    if BEGIN not in text or END not in text:
        raise AssertionError(
            f"{REGISTER.name} carries no measured block. Expected {BEGIN} and {END}."
        )
    head, rest = text.split(BEGIN, 1)
    block, tail = rest.split(END, 1)
    return head, block, tail


def _files(number: int) -> str:
    return f"{number} file" if number == 1 else f"{number} files"


def _rows(number: int) -> str:
    return f"{number} row" if number == 1 else f"{number} rows"


@dataclass(frozen=True)
class Census:
    """What the running suite collected, by file.

    **Collected tests, not `def test_` lines**, which come to fewer: a
    parametrised case is one line and several tests. Collected is the unit the
    register's rows are stated in, and `test_the_census_counts_cases_rather_than
    _functions` is what says the difference is real.
    """

    counts: dict[str, int]
    #: Every file the collector would have reached, whether or not this run kept
    #: it. The two differ exactly when a run was narrowed.
    on_disk: frozenset[str]

    @classmethod
    def of(cls, session: pytest.Session) -> Census:
        counts: dict[str, int] = {}
        for item in session.items:
            where = Path(item.path).relative_to(TESTS).as_posix()
            counts[where] = counts.get(where, 0) + 1
        # The naming rule is read from the configuration rather than written
        # here. A project that renamed its test files would otherwise leave this
        # set empty and every completeness check passing on nothing.
        patterns = session.config.getini("python_files")
        return cls(
            counts=counts,
            on_disk=frozenset(
                path.relative_to(TESTS).as_posix()
                for path in _test_sources()
                if any(fnmatch(path.name, pattern) for pattern in patterns)
            ),
        )

    @property
    def complete(self) -> bool:
        return set(self.counts) == set(self.on_disk)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def unnamed(self, named: list[str]) -> list[str]:
        return sorted(set(self.counts) - set(named))


def render(census: Census, named: list[str]) -> str:
    """The block the register carries, from one run's own figures.

    Three numbers rather than one, because the register's whole arithmetic is
    the identity between them: the headline, less the tests in the files that
    cannot be named, is what the rows sum to. Rendering all three from one
    census makes that identity hold by construction, where the register used to
    state it and ask the reader to check.
    """
    unnamed = census.unnamed(named)
    shortfall = sum(census.counts[path] for path in unnamed)
    return (
        f"\n\n**{census.total} tests, in {_files(len(census.counts))}**, counted by the "
        "run that reads this line.\n"
        f"**The {_rows(len(named))} below sum to {census.total - shortfall}.**\n"
        f"The other {shortfall} tests are in {_files(len(unnamed))} this register may "
        "not name.\n"
    )


@pytest.fixture(scope="module")
def register() -> str:
    return REGISTER.read_text(encoding="utf-8")


@pytest.fixture
def census(request: pytest.FixtureRequest) -> Census:
    """This run, as a count per file.

    `request.session.items` under xdist is the **whole** collection rather than
    this worker's share of it: every worker collects the suite and the
    controller then hands out indices into that list. A share would report a
    fraction of the tree and be refused by `whole_tree` below, so the failure
    mode of being wrong about this is a guard that never runs, which is why the
    gate on it is not optional.
    """
    return Census.of(request.session)


@pytest.fixture
def whole_tree(census: Census) -> Census:
    """The census, or a skip when this run is not the whole suite.

    **A narrowed run must not be allowed to answer, in either direction.** Run
    one file and every other row reads as missing; run `-k` over a name and a
    file's own count is a fraction of its row. Both would be reported as a stale
    register, which is a guard that cries wolf until somebody deletes it.

    The gate is the file set rather than a flag, because a path, `-k`, a marker
    and a plugin each narrow a run by a different route, and enumerating them is
    the shape this repository keeps paying for.

    **Only the three count comparisons sit behind this**, and the rules about
    the file set do not, because this gate fails open: a `test_*.py` that
    collects nothing at all, an empty one or one skipped at module level, is on
    disk and not in the collection, so a **whole** suite run would read as
    narrowed and every rule behind it would skip for good with a message saying
    to run the whole suite. The rules that need no counts are therefore asked of
    the walk, where that file is present and has to carry a row or a
    declaration either way. Found by a security critic; no file in the tree
    collects nothing today, so it was latent.
    """
    if not census.complete:
        missing = sorted(census.on_disk - set(census.counts))
        pytest.skip(
            f"this run collected {len(census.counts)} of {len(census.on_disk)} test "
            "files, so the counts in the register cannot be checked against it. "
            f"Not collected: {missing}. On a whole suite run that list is a file "
            "collecting no test rather than a narrowed run."
        )
    return census


class TestEveryNumberInTheRegisterIsThisRunsOwn:
    def test_the_measured_block_is_what_this_run_collected(
        self, whole_tree: Census, register: str
    ) -> None:
        _, block, _ = split(register)
        named = [path for path, _ in rows(register)]

        assert block == render(whole_tree, named), (
            "COVERAGE.md's measured block is not what this run collected. That "
            "block is generated: replace the text between the fences with what "
            "follows, and read what moved rather than adjusting a figure by the "
            f"delta.\n{render(whole_tree, named)}"
        )

    def test_every_row_states_the_count_this_run_collected(
        self, whole_tree: Census, register: str
    ) -> None:
        wrong = [
            f"{path}: the register says {stated}, the run collected "
            f"{whole_tree.counts[path]}"
            for path, stated in rows(register)
            if path in whole_tree.counts and stated != whole_tree.counts[path]
        ]

        assert wrong == [], "\n".join(wrong)

    def test_every_row_names_a_file_the_tree_has(
        self, census: Census, register: str
    ) -> None:
        """The other direction, because the cheapest way to make the rule above
        go green is to delete the row it names.

        The depth table had the same hole and it was measured there: one row
        taken out of the first column left the whole file green with the
        module's own paragraph still beside it.
        """
        gone = sorted({path for path, _ in rows(register)} - census.on_disk)

        assert gone == [], (
            f"these rows name files the test tree does not have: {gone}. A file "
            "that is gone loses its row; one that was renamed keeps its "
            "description."
        )

    def test_no_file_is_given_two_rows(self, register: str) -> None:
        """A path written twice states a row count the table does not have.

        The block renders the number of rows beside what they sum to, and the
        sum is over distinct files, so two rows for one file leave the pair
        describing different tables while every other rule here passes.
        """
        named = [path for path, _ in rows(register)]
        twice = sorted({path for path in named if named.count(path) > 1})

        assert twice == [], f"these files carry more than one row: {twice}"

    def test_every_file_with_no_row_is_one_the_register_may_not_name(
        self, census: Census, register: str
    ) -> None:
        """The shortfall, derived rather than stated.

        **A count in the block would be satisfied by any files at all**, so one
        more added with no row could be absorbed by editing a digit. What makes
        this a partition instead: a collected file either carries a row or
        declares itself internal, and the publish gate holds the other end of
        that, refusing to publish a file carrying the declaration and refusing a
        stripped document that omits it.

        So a new test file has two honest destinations, a row here or the strip
        list, and one that took neither fails here by name.

        **Asked of the walk rather than of the collection**, so that a file
        collecting no test is still required to answer, and so that this rule,
        which is the only thing in the tree requiring a stripped test file to
        carry the declaration, cannot be switched off by narrowing a run.
        """
        named = {path for path, _ in rows(register)}
        undescribed = [
            path
            for path in sorted(census.on_disk - named)
            if not declares_itself_internal(TESTS / path)
        ]

        assert undescribed == [], (
            "these files are collected, carry no row in COVERAGE.md and are not "
            f"stripped from the published tree: {undescribed}. Give each one a "
            "row saying what it covers, which is the half of this register a run "
            "cannot write."
        )

    def test_nothing_collected_is_skipped_or_left_expected_to_fail(
        self, request: pytest.FixtureRequest
    ) -> None:
        """What lets the block say "tests" where the gate says "passed".

        Collected and passed differ by the skips plus the open recorded
        defects. The register states the two as one number, and this is the
        condition under which that is a fact about the tree rather than a
        simplification. It reads markers, so a `pytest.skip()` called inside a
        test body is not covered: the run's own summary line is where that one
        shows up.
        """
        marked = sorted(
            f"{Path(item.path).relative_to(TESTS).as_posix()}::{item.name} ({marker})"
            for item in request.session.items
            for marker in ("skip", "skipif", "xfail")
            if item.get_closest_marker(marker) is not None
        )

        assert marked == [], (
            "COVERAGE.md states one number for collected and for passed. These "
            f"tests would make the two differ: {marked}"
        )


class TestTheCensusMeasuresRatherThanAgrees:
    """Two diagonals, because every rule above compares the document with
    `counts` and would compare them just as happily if `counts` were a constant
    or a count of function definitions."""

    def test_the_census_counts_cases_rather_than_functions(
        self, whole_tree: Census
    ) -> None:
        """`test_dialect.py` is the witness because its cases are generated per
        dialect, so its collected count has always stood well above the number
        of functions in it. This file is parametrised nowhere and could not
        serve.
        """
        witness = "test_dialect.py"
        functions = len(
            re.findall(r"^\s*def test_", (TESTS / witness).read_text(), re.MULTILINE)
        )

        assert whole_tree.counts[witness] > functions, (
            f"{witness} collects {whole_tree.counts[witness]} tests from "
            f"{functions} functions; equal means the census has stopped counting "
            "cases and the register would now agree with the wrong instrument"
        )

    def test_the_walk_reads_a_tree_rather_than_the_collection(
        self, tmp_path: Path
    ) -> None:
        """`on_disk` comes from the shared tree walk and `counts` from pytest's
        own collection, and every rule above rests on those being two
        instruments: the completeness gate compares them, and a gate comparing
        one list with itself passes on any tree.

        Driven against a tree this test planted, because the assertion that
        suggests itself here, that the walk covers the collection, is the gate's
        own condition restated and therefore true by construction wherever the
        gate let a test run at all.
        """
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_planted.py").write_text("def test_nothing(): ...")
        (tmp_path / "tests" / "helpers.py").write_text("")

        found = {path.name for path in _test_sources(tmp_path)}

        assert found == {"test_planted.py", "helpers.py"}


class TestTheDocumentIsReadRatherThanAssumed:
    """The parser's own failure modes, all of which are silent ones.

    Each has a version where every rule above passes while reading nothing: no
    fences, a table whose shape moved, a padded column. A guard with no input
    cannot fail.
    """

    def test_a_register_with_no_fences_is_refused(self) -> None:
        with pytest.raises(AssertionError, match="no measured block"):
            split("# Backend test coverage\n\nNo block here.\n")

    def test_a_padded_row_is_read(self) -> None:
        assert rows("| `test_a.py`   |   327 | What it covers |\n") == [
            ("test_a.py", 327)
        ]

    def test_a_row_in_a_nested_directory_keeps_its_path(self) -> None:
        assert rows("| `routers/test_books.py` | 143 | Listing |\n") == [
            ("routers/test_books.py", 143)
        ]

    def test_a_number_in_the_third_column_is_not_read_as_the_count(self) -> None:
        """The cell boundary, which is the mistake the roster census made
        first: a number one column along is a claim about a different subject,
        and here it would silently become the row's count."""
        assert rows("| `test_a.py` | 12 | covers 34 cases |\n") == [("test_a.py", 12)]

    def test_a_table_whose_first_cell_is_not_a_path_yields_no_row(self) -> None:
        assert rows("| File | Tests | Covers |\n|---|---:|---|\n") == []

    def test_the_block_renders_every_figure_from_the_census(self) -> None:
        """The renderer driven against a tree this test built, so that the
        equality above compares the document with a measurement rather than
        with a constant."""
        census = Census(
            counts={"test_a.py": 10, "test_b.py": 5, "test_hidden.py": 2},
            on_disk=frozenset({"test_a.py", "test_b.py", "test_hidden.py"}),
        )

        block = render(census, ["test_a.py", "test_b.py"])

        assert "**17 tests, in 3 files**" in block
        assert "**The 2 rows below sum to 15.**" in block
        assert "The other 2 tests are in 1 file this register may not name." in block

    def test_one_file_is_not_written_as_files(self) -> None:
        assert _files(1) == "1 file"
        assert _files(2) == "2 files"

    def test_one_row_is_not_written_as_rows(self) -> None:
        """Unreachable while the table holds more than one row, and written
        because the block is prose: the day a register is down to one row is
        not the day to notice the sentence reads wrong."""
        assert _rows(1) == "1 row"
        assert _rows(2) == "2 rows"
