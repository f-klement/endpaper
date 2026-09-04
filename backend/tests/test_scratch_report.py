"""The scratch report says which filesystem the databases went to.

`conftest._fastest_scratch()` falls back from `/dev/shm` to disk **silently**,
and a run that took the fallback still passes. The only difference is how long
it takes, so the report is the whole mechanism for noticing, and a report that
goes quiet is the same defect one level up.

Three attempts were needed to get a line that prints at all: this project's
`addopts` carries `-q`, which drops `pytest_report_header` outright, and a
`write_line` from `pytest_configure` lands before the reporter starts writing.
Only the summary hook survives both. That is why this is pinned rather than
left to a reader to notice, and why the assertions are on the text.
"""

import sys
from pathlib import Path
from typing import Any

import pytest


def _conftest() -> Any:
    """The already-loaded conftest module.

    **Found rather than imported.** Importing it again would run its module
    level block a second time: another `mkdtemp`, another `DATABASE_URL`, and
    the suite's own scratch directory replaced underneath the tests still using
    it. Nothing would fail loudly.
    """
    here = str(Path(__file__).parent / "conftest.py")
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) == here:
            return module
    raise AssertionError(f"conftest is not loaded from {here}")


class FakeReporter:
    """Collects what the hook writes, in place of pytest's terminal reporter."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, line: str) -> None:
        self.lines.append(line)


@pytest.mark.parametrize(
    ("parent", "expected"),
    [
        ("/dev/shm", "tmpfs"),
        ("/tmp", "DISK, /dev/shm unavailable"),
        # Not a prefix test. A directory that merely starts with the right
        # characters is a different filesystem, and calling it tmpfs would
        # report the fast path on a run taking the slow one.
        ("/dev/shmem", "DISK, /dev/shm unavailable"),
    ],
)
def test_it_names_the_filesystem_the_databases_landed_on(
    monkeypatch: pytest.MonkeyPatch, parent: str, expected: str
) -> None:
    conftest = _conftest()
    monkeypatch.setattr(conftest, "_TMP_DATA_DIR", Path(parent) / "endpaper-x")
    reporter = FakeReporter()

    conftest.pytest_terminal_summary(reporter)

    assert len(reporter.lines) == 1
    assert reporter.lines[0] == f"endpaper scratch: {parent} ({expected})"


def test_the_hook_is_the_one_pytest_calls_under_this_project_s_settings() -> None:
    # `-q` is in addopts, so the two obvious hooks print nothing. If somebody
    # renames this back to `pytest_report_header`, the report silently stops
    # reaching a CI log and the fallback stops being visible again.
    conftest = _conftest()
    assert hasattr(conftest, "pytest_terminal_summary")
    assert not hasattr(conftest, "pytest_report_header")
