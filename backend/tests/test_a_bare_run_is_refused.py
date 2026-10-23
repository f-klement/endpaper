"""A run of this suite that nobody sanctioned refuses to start.

The rule is `pytest_configure` in `tests/conftest.py`; docs/testing.md says why
it exists. The refusal's two runs are the same command over this tree, differing
only in the variable, so the variable is the one thing either verdict can be
about.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from tests.conftest import SANCTIONED

BACKEND = Path(__file__).resolve().parent.parent

#: One process: `-n 0` on the command line wins over the worker count in
#: `addopts`.
_PYTEST = [sys.executable, "-m", "pytest", "-n", "0", "-p", "no:cacheprovider"]

#: Collection of this one file, which runs no test, so the sanctioned arm costs
#: one import of the conftest and no suite.
#: No `-q` of our own: `addopts` carries one, and a second drops the ids.
_COLLECT = ["--collect-only", "tests/test_a_bare_run_is_refused.py"]


def _inner_run(*args: str, sanctioned: bool) -> subprocess.CompletedProcess[str]:
    # **Every `PYTEST_` name dropped, not only the flags.** The outer run is an
    # xdist worker, and `PYTEST_XDIST_WORKER` names the Postgres database the
    # conftest derives; `ENDPAPER_TEST_DATABASE_URL` goes too, so the inner run
    # is SQLite on every engine and touches no server the outer one is using.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_")
        and key not in {SANCTIONED, "ENDPAPER_TEST_DATABASE_URL"}
    }
    if sanctioned:
        env[SANCTIONED] = "1"
    return subprocess.run(
        [*_PYTEST, *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_a_run_without_the_variable_refuses_and_with_it_proceeds() -> None:
    refused = _inner_run(*_COLLECT, sanctioned=False)
    allowed = _inner_run(*_COLLECT, sanctioned=True)

    assert refused.returncode == 4, refused.stdout + refused.stderr
    # **The runner is offered before the variable.** The reader at the moment
    # of the refusal follows the first instruction it is given, and on a shared
    # machine that has to be the runner rather than turning the guard off.
    # A line naming the runner with no `=1` ahead of it. A match within one
    # line, and a positive one, so nothing else reaching stderr can move it.
    first_the_runner = f"^(?:(?!{SANCTIONED}=1).)*suite runner"
    assert re.search(first_the_runner, refused.stderr, re.MULTILINE), refused.stderr

    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert "test_a_run_without_the_variable_refuses_and_with_it_proceeds" in allowed.stdout


def test_help_runs_without_the_variable() -> None:
    helped = _inner_run("--help", sanctioned=False)

    assert helped.returncode == 0, helped.stdout + helped.stderr
