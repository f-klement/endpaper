"""The Python side of the shared accession number conformance suite.

The cases live in `conformance/cases/accession.json`, and
`frontend/tests/conformance/accession.test.ts` runs the same file. This file
holds no accession expectation of its own: it maps the specification's operation
names onto `accession.py` and guards the case file, as `test_isbn.py` does for
the ISBN domain, whose docstring says what each guard stops.

**And it holds the printing half of the symbology guard**:
`accession.LABEL_SYMBOLOGIES` against the case file's `symbologies`, while the
TypeScript runner holds the camera's half to the same list. `conformance/accession.md`
says why a mismatch has to fail at build time.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
from jsonschema import Draft202012Validator

import accession

# backend/tests/conformance/test_accession.py -> the repository root.
_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = _ROOT / "conformance" / "cases" / "accession.json"
SCHEMA_PATH = _ROOT / "conformance" / "schema" / "accession.schema.json"
DOC_PATH = _ROOT / "conformance" / "accession.md"

OPERATIONS: Final[dict[str, Callable[[Any], Any]]] = {
    "mint": accession.mint,
    "is-accession": accession.is_accession,
    "classify": accession.classify,
}

#: A floor, not a count: `test_isbn.py::MINIMUM_CASES` says why.
MINIMUM_CASES: Final = 15

#: The header of the guard dropping table in `conformance/accession.md`, the
#: anchor `test_isbn.py::_GUARD_TABLE_HEADER` explains.
_GUARD_TABLE_HEADER: Final = "| guard dropped | cases that catch it |"


def _load() -> dict[str, Any]:
    """The case file, validated. Raises rather than skipping, on every failure."""
    raw = CASES_PATH.read_bytes()
    if not raw.isascii():
        raise ValueError(f"{CASES_PATH} carries a non-ASCII byte; write it as a \\u escape")
    document: dict[str, Any] = json.loads(raw.decode("utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(document)]
    if errors:
        raise ValueError(f"{CASES_PATH} does not match its schema: {errors}")
    identifiers = [case["id"] for case in document["cases"]]
    duplicates = sorted({name for name in identifiers if identifiers.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids in {CASES_PATH}: {', '.join(duplicates)}")
    return document


DOCUMENT: Final = _load()
CASES: Final[list[dict[str, Any]]] = DOCUMENT["cases"]


def _guard_table_ids() -> set[str]:
    """Every case id the guard dropping table in `accession.md` names."""
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()
    body = lines[lines.index(_GUARD_TABLE_HEADER) + 2 :]
    rows = body[: next((at for at, line in enumerate(body) if not line.startswith("|")), len(body))]
    return {name for row in rows for name in re.findall(r"`([a-z0-9-]+)`", row)}


class TestTheCaseFileIsWorthRunning:
    def test_it_carries_enough_cases_to_be_a_specification(self):
        assert len(CASES) >= MINIMUM_CASES

    def test_every_operation_the_schema_names_is_wired(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert sorted(schema["$defs"]["operation"]["enum"]) == sorted(OPERATIONS)

    def test_every_operation_has_a_case(self):
        assert {case["op"] for case in CASES} == set(OPERATIONS)

    def test_every_case_the_guard_table_names_is_in_the_file(self):
        """Deleting a case that carries a reason fails here rather than passing."""
        named = _guard_table_ids()
        assert named, "the guard dropping table in accession.md names no case"
        assert named - {case["id"] for case in CASES} == set()


class TestWhatTheServerPrintsIsWhatTheCameraReads:
    def test_the_printable_symbologies_are_the_case_files(self):
        """The printing half of ticket 26's guard. A symbology printed and not
        in the file is a label the camera was never told to read."""
        assert sorted(accession.LABEL_SYMBOLOGIES) == sorted(DOCUMENT["symbologies"])


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_shared_accession_case(case: dict[str, Any]):
    actual = OPERATIONS[case["op"]](case["input"])
    assert actual == case["expect"], (
        f"{case['id']}: {case['op']}({case['input']!r}) gave {actual!r}, the shared "
        f"cases say {case['expect']!r}.\n{case['why']}"
    )
