"""The committed export against the lockfile it declares itself generated from.

**A vulnerability scanner reads `backend/requirements.txt` as a lockfile**, which
the pipeline configuration says in as many words, and nothing installs from it: the image and
the suite both run `uv sync --frozen`, and the pipeline's own audit regenerates a
fresh export rather than reading the committed one. So this file's only consumer is
a scanner, and a scanner reading a stale one audits a dependency set that is not
installed anywhere.

**Measured 2026-09-26, which is why this exists.** The committed export held 29
pins where the lock resolves 43, so **fifteen distributions were absent from what
the scanner read**, among them `cryptography`, `alembic`, `ldap3` and `pg8000`. Eight
more were pinned *newer* than the lock, including the SQLAlchemy, uvicorn and
starlette bumps a merge commit claims to have landed, so the export was generated
from a resolution this tree no longer has.

**Pure on purpose: it reads the two files rather than running the exporter.** A test
that shelled out would need a subprocess, a timeout and a bound on the child, and
the property is a comparison of two committed artefacts, which needs none of that.
The cost is that it holds the versions and the package set, not the hashes or the
markers.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
_LOCK = BACKEND / "uv.lock"
_EXPORT = BACKEND / "requirements.txt"

#: A pin at the start of a line, which is where the exporter writes one. A name is
#: normalised because the two files disagree on case and on the separator: the lock
#: says `sqlalchemy`, the export says `SQLAlchemy`, and both mean one distribution.
_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)")


def _normalised(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _exported() -> dict[str, str]:
    return {
        _normalised(found[1]): found[2]
        for line in _EXPORT.read_text().splitlines()
        if (found := _PIN.match(line))
    }


def _locked() -> dict[str, str]:
    """Every package the lock resolves, less the project itself.

    The project is excluded because the export is generated with
    `--no-emit-project`, so it is absent there by construction rather than missing.
    """
    lock = tomllib.loads(_LOCK.read_text())
    return {
        _normalised(package["name"]): package["version"]
        for package in lock["package"]
        if _normalised(package["name"]) != _project() and "version" in package
    }


def _project() -> str:
    return _normalised(_pyproject()["project"]["name"])


def _pyproject() -> dict:
    return tomllib.loads((BACKEND / "pyproject.toml").read_text())


def _declared() -> set[str]:
    """The runtime dependencies this project declares, by name.

    **Not the closure**, which is the honest limit of this file: the lock resolves
    the development set too and the export excludes it, so comparing whole sets
    would report every test tool as missing. What is asserted is that a dependency
    this project names for itself reaches the file a scanner reads.
    """
    return {_name_of(one) for one in _pyproject()["project"]["dependencies"]}


def _name_of(specifier: str) -> str:
    """The distribution name at the head of a dependency specifier.

    It raises rather than skipping. A specifier this cannot read would otherwise
    drop out of the declared set silently, and the declared set is the left hand
    side of the arm that found the drift, so a shape nobody anticipated has to be
    louder than a passing test.
    """
    head = re.match(r"^([A-Za-z0-9_.\-]+)", specifier)
    if head is None:
        raise AssertionError(f"not a dependency specifier: {specifier!r}")
    return _normalised(head.group(1))


class TestTheCommittedExportIsTheLockfileItClaimsToBe:
    def test_every_declared_dependency_reaches_the_export(self) -> None:
        """A scanner cannot report what the file it reads does not name.

        **This is the arm the drift was found by**, and it is stated over the
        declared set rather than the closure for the reason `_declared` gives.
        Measured against the export as committed before that regeneration: it names
        six of the fifteen, `alembic`, `cryptography`, `ldap3`, `mnemonic`, `pg8000`
        and `rapidfuzz`, so a transitive package missing alone is outside this arm
        and a **declared** one is not.
        """
        missing = sorted(_declared() - set(_exported()))

        assert missing == [], (
            "these are declared dependencies of this project and absent from "
            "requirements.txt, which a vulnerability scan reads as a lockfile, so it "
            "covers none of them. Regenerate with `uv export --no-dev "
            f"--no-emit-project -o requirements.txt`: {missing}"
        )

    def test_no_pin_disagrees_with_the_lock(self) -> None:
        """The versions, in both directions.

        **A pin newer than the lock is the interesting direction** and is what this
        was written for: it means an export survived a resolution that did not, so a
        bump is recorded in a file nothing installs from while the lockfile that does
        install still holds the old version.
        """
        locked, exported = _locked(), _exported()
        disagreeing = sorted(
            f"{name}: export {exported[name]}, lock {locked[name]}"
            for name in set(locked) & set(exported)
            if locked[name] != exported[name]
        )

        assert disagreeing == [], (
            "requirements.txt declares itself generated from uv.lock and disagrees "
            f"with it. Regenerate it, or bump the lock if these are intended: "
            f"{disagreeing}"
        )

    def test_the_export_names_nothing_the_lock_does_not_resolve(self) -> None:
        """The other direction, which a regeneration alone would hide."""
        extra = sorted(set(_exported()) - set(_locked()))

        assert extra == [], (
            "requirements.txt pins distributions uv.lock does not resolve, so it was "
            f"generated from a different project state: {extra}"
        )
