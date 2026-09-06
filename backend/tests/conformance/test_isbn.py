"""The Python side of the shared ISBN conformance suite.

The cases live in `conformance/cases/isbn.json`, outside both language trees,
and `frontend/tests/conformance/isbn.test.ts` runs the same file against the
same expectations. A disagreement between the two implementations is a failing
test on the side that is wrong, rather than a support ticket a year later.

**This file holds no ISBN expectation of its own.** Every expectation about an
ISBN comes out of the case file, and the only ISBN knowledge written here is the
mapping from a language neutral operation name onto this implementation's
spelling. What else is written here is the guards below, which are expectations
about the case file rather than about ISBNs. Adding a case is editing JSON;
changing an expectation is changing the protocol and belongs in a commit that
says so and that lands on both sides.

Three ways this could quietly stop testing anything, and what stops each:

* **The case file is missing, or has been emptied.** `_load()` raises at import,
  which pytest reports as a collection error and a non-zero exit. It never
  skips: a conformance suite that silently runs zero cases is the failure mode
  that makes the whole idea theatre.
* **The case file has drifted from the format.** Every file is validated against
  `conformance/schema/isbn.schema.json` before a single case runs, so a renamed
  field or a `parse` case expecting a boolean fails loudly instead of being
  read as something it is not.
* **The runner has drifted from the schema.** `test_every_operation_the_schema_names_is_wired`
  compares the dispatch table against the schema's own list of operations, so an
  operation added to the specification and not to this file fails here rather
  than being silently unexercised.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
from jsonschema import Draft202012Validator

import isbn

# backend/tests/conformance/test_isbn.py -> the repository root.
_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = _ROOT / "conformance" / "cases" / "isbn.json"
SCHEMA_PATH = _ROOT / "conformance" / "schema" / "isbn.schema.json"
README_PATH = _ROOT / "conformance" / "README.md"


def _string(value: str | None, op: str) -> str:
    """A second, independent check that the schema's per operation input rule holds.

    Four of the six operations are not null safe on either side. The schema says
    so with an `if`/`then` arm, and if that arm were deleted this would still
    raise rather than calling `normalise(None)` and reporting whatever came back.
    Two guards on one rule, because the schema is data and this is code. The
    TypeScript runner carries the same function for the same reason.
    """
    if value is None:
        raise TypeError(f"{op} takes a string, and this case gives a null input")
    return value


# The operations, in the specification's spelling, mapped onto this
# implementation's. Written out rather than derived from the names, because the
# point of the indirection is that neither language's naming owns the format.
OPERATIONS: dict[str, Callable[[str | None], Any]] = {
    "normalise": lambda value: isbn.normalise(_string(value, "normalise")),
    "is-valid-isbn10": lambda value: isbn.is_valid_isbn10(_string(value, "is-valid-isbn10")),
    "is-valid-isbn13": lambda value: isbn.is_valid_isbn13(_string(value, "is-valid-isbn13")),
    "isbn10-to-isbn13": lambda value: isbn.isbn10_to_isbn13(_string(value, "isbn10-to-isbn13")),
    "parse": isbn.parse,
    "is-valid": isbn.is_valid,
}

# A floor, not a count. It exists for the same reason `palettes.test.ts` asserts
# it has rows it can actually see: a loader that silently produced one case, or
# none, would make every assertion below vacuous while the suite stayed green.
# The schema's `minItems` rejects an empty array; this rejects a gutted file.
MINIMUM_CASES = 20


def _load() -> list[dict[str, Any]]:
    """The cases, validated. Raises rather than skipping, on every failure."""
    if not CASES_PATH.is_file():
        raise FileNotFoundError(
            f"conformance case file missing: {CASES_PATH}. This suite runs the shared "
            "fixtures in conformance/cases/, and refuses to pass by running none of them."
        )
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(
            f"conformance schema missing: {SCHEMA_PATH}. Without it a drifted case file "
            "cannot be told from a correct one."
        )

    # **The file stays ASCII, and this is what makes that a rule rather than a
    # request.** `conformance/README.md` asks for a `\u` escape because the
    # rendered character is indistinguishable on screen from three other digit
    # zeros, and an escape survives every editor, terminal and diff. Enforced on
    # the bytes, before the decode, since `json.loads` turns both spellings into
    # the same string and cannot tell them apart afterwards. One side is enough
    # to fail the pipeline: both runners read this one file.
    raw = CASES_PATH.read_bytes()
    if not raw.isascii():
        offending = sorted({byte for byte in raw if byte > 0x7F})
        raise ValueError(
            f"{CASES_PATH} contains {len(offending)} non-ASCII byte values. Write a "
            "character outside ASCII as a \\u escape, so the case file stays greppable "
            "and one digit zero can be told from another."
        )

    document = json.loads(raw.decode("utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # `iter_errors` rather than `validate`, so a file with four faults reports
    # four rather than whichever one the validator reached first.
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        detail = "\n".join(
            f"  at {'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"{CASES_PATH} does not match {SCHEMA_PATH.name}:\n{detail}")

    cases: list[dict[str, Any]] = document["cases"]
    identifiers = [case["id"] for case in cases]
    # JSON Schema cannot express uniqueness across a property of array items, so
    # the two runners assert it. A duplicated id is a case silently overwritten
    # in any implementation that keys on it.
    duplicates = sorted({name for name in identifiers if identifiers.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids in {CASES_PATH}: {', '.join(duplicates)}")
    return cases


#: The header of the guard dropping table in `conformance/README.md`. Anchored on
#: rather than inferred, because `README.md` holds a second two column table and a
#: walk over every `|` line reads both. That is not cosmetic: it was the first
#: version of this, and it made the anti vacuity count below pass on the six rows
#: of the other table while the guard table itself could have been deleted whole.
_GUARD_TABLE_HEADER: Final = "| guard dropped | cases that catch it |"

#: The one cell in that table naming no case, verbatim. `conformance/README.md`
#: argues at length that the browser's checksum regexes cannot be caught by any
#: case, because `Number("\u0660")` is `NaN` and the arithmetic refuses a non
#: ASCII digit whatever the regex admits. Written out so that a row emptied by
#: accident is a failure while that row stays legal, which a bare "some row has
#: no ids" test cannot do.
_DELIBERATELY_UNCATCHABLE: Final = "**nothing, and it cannot**"

#: How many rows that table has, asserted as an equality.
#:
#: **A floor here is not a weaker version of this, it is a hole.** With `>=`, the
#: table can grow to seven while this stays six, and the two step deletion the
#: row check exists to stop is then back one row later: add a row, delete a row,
#: delete the case that row named, green at every step because a smaller count
#: satisfies a floor. That is this repository's named trap, a literal six
#: bounded against a constant that had moved to seven.
#:
#: The cost is that adding a layer fails until this number moves in the same
#: commit. That is the point rather than the price: adding a layer to the table
#: is exactly the edit that should have to touch the guard.
#:
#: **What this does not bound is which rows they are.** A count fixes one axis.
#: Swapping a row for one that names a different real case keeps the count at
#: six and satisfies both checks below, and the case the old row protected is
#: then named nowhere and deletes green: one step, and the shape of an ordinary
#: documentation refactor rather than of an attack. Closing it needs the six ids
#: written here, which would be a third home for a list that already has two, so
#: the exclusion is stated rather than closed. **Moving a row out of that table
#: is moving a case out of anything's sight.**
_GUARD_TABLE_ROWS: Final = 6


def _readme_guard_table() -> list[tuple[str, str, list[str]]]:
    """Rows of that table, as (what was dropped, the cell verbatim, the case ids in it).

    **The cell comes back verbatim as well as parsed**, because a row that yields
    no id because somebody emptied it and the one row that yields none by design
    are otherwise the same value, and the caller has to tell them apart.

    Read out of the Markdown rather than listed in this file: a list here would
    be a third home for the same fact. Returns nothing at all if the header moves
    or is reworded, which the caller treats as a failure rather than as an empty
    table.

    **The second column only.** The first names functions, and `normalise` is a
    function name shaped exactly like a case id, so scanning the whole row would
    quietly compare a function against the case file and report it missing.
    """
    lines = README_PATH.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(_GUARD_TABLE_HEADER)
    except ValueError:
        return []

    rows: list[tuple[str, str, list[str]]] = []
    # Skip the header and the `|---|---|` separator beneath it, then read until
    # the table ends, which in Markdown is the first line that is not a row.
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        columns = [column.strip() for column in line.strip("|").split("|")]
        if len(columns) != 2:
            break
        identifiers = re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)*)`", columns[1])
        rows.append((columns[0], columns[1], identifiers))
    return rows


CASES = _load()
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


class TestTheCaseFileIsWorthRunning:
    """The guards that stop this suite passing while testing nothing."""

    def test_the_file_carries_enough_cases_to_be_a_specification(self):
        assert len(CASES) >= MINIMUM_CASES, (
            f"{CASES_PATH} holds {len(CASES)} cases, below the floor of {MINIMUM_CASES}. "
            "Either the file has been gutted or the floor needs raising with the reason."
        )

    def test_every_operation_the_schema_names_is_wired(self):
        declared = set(SCHEMA["$defs"]["operation"]["enum"])
        assert set(OPERATIONS) == declared, (
            "the dispatch table and the schema disagree about which operations exist: "
            f"only in the schema {sorted(declared - set(OPERATIONS))}, "
            f"only in this runner {sorted(set(OPERATIONS) - declared)}"
        )

    def test_every_case_the_readme_names_still_exists(self):
        """The floor is a count, and a count cannot protect the cases that carry the reason.

        29 cases against a floor of 20 leaves nine deletable, and the ones worth
        deleting to make a failure go away are the non-ASCII ones this directory
        exists for: every operation would still be exercised and both suites
        would stay green. `conformance/README.md` names the load bearing
        cases by id in its guard dropping table, so binding that table to the
        case file makes deleting one of them a failure here, and makes a renamed
        case show up as a table pointing at nothing.

        The ids are read out of the README rather than listed here, because a
        list written in this file is a third place to keep the same fact in step.

        **Every row is checked, not just the set of ids they add up to, and the
        row count is an equality.** The first version asserted `>= 4` against six
        rows and compared only the union: deleting the two `is_valid_isbn10` rows
        left four rows and a green guard, after which the two cases those rows
        named were named nowhere and could be deleted with the suite still green.
        A two step deletion, green at every step, of exactly the layers the
        README argues must not go in silence. The second version closed that and
        left `>=`, which reopened it one row later, since a table grown to seven
        satisfies a floor of six and can then be cut back to six a row poorer.
        """
        rows = _readme_guard_table()
        assert len(rows) == _GUARD_TABLE_ROWS, (
            f"the guard dropping table in {README_PATH} yielded {len(rows)} rows against "
            f"{_GUARD_TABLE_ROWS} expected. A row was deleted, taking the cases it named "
            "out of anything's sight; or a row was added and this number was not; or the "
            "extraction has stopped finding the table and this rule is vacuous."
        )

        silent = [
            dropped
            for dropped, cell, identifiers in rows
            if not identifiers and cell != _DELIBERATELY_UNCATCHABLE
        ]
        assert silent == [], (
            f"rows of {README_PATH}'s guard dropping table name no case and are not the "
            f"one row allowed to: {silent}. A layer with no case is a layer that can be "
            "deleted in silence, which is the whole argument the table makes."
        )

        known = {case["id"] for case in CASES}
        named = {identifier for _, _, identifiers in rows for identifier in identifiers}
        assert named <= known, (
            f"{README_PATH} names cases that are not in {CASES_PATH.name}: "
            f"{sorted(named - known)}. A case may not be deleted or renamed while the "
            "table that explains what it pins still points at it."
        )

    def test_every_operation_is_exercised_by_at_least_one_case(self):
        exercised = {case["op"] for case in CASES}
        assert exercised == set(OPERATIONS), f"operations with no case: {sorted(set(OPERATIONS) - exercised)}"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_conformance_case(case):
    """One shared case, run against this implementation.

    The assertion message carries the `why` because that is the only place the
    reason for a case lives, and a failure here is a divergence between two
    implementations rather than an ordinary broken test.
    """
    operation = OPERATIONS[case["op"]]
    actual = operation(case["input"])
    assert actual == case["expect"], (
        f"{case['id']}: {case['op']}({case['input']!r}) gave {actual!r}, "
        f"the shared cases say {case['expect']!r}.\n{case['why']}"
    )
