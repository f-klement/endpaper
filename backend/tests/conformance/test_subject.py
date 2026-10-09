"""The Python side of the shared subject conformance suite.

The cases live in `conformance/cases/subject.json`, outside both language trees,
and `frontend/tests/conformance/subject.test.ts` runs the same file.
`conformance/subject.md` holds what the invariant is and why a case carries both
implementations' answers rather than one expectation.

**The invariant is an equality across two different functions**, not one
function implemented twice:

    server(browser(x)) == server(x)

The browser collapses whitespace and trims; the server does that and deletes the
control characters that have no width. The two are not the same rule and are not
meant to be. What must hold is that the browser never changes the server's
answer, so the value the app sends is one the file stated.

**Two arms here and one in TypeScript, and none of them crosses a runtime.**
The TypeScript arm holds that `boundCategories` answers what a case's `browser`
field says. This file holds that the server's rule over the raw input answers
what `server` says, **and** that the server's rule over the `browser` value
answers the same thing. Compose the three and the property above holds, with the
literal in the case file carrying it across.

**The two arms lock each other, which is what makes this a guard rather than a
golden file.** Widen the browser and the TypeScript arm reddens; edit the
`browser` value to green it and the equality arm here reddens; edit `server` as
well and the absolute arm here reddens. `conformance/subject.md` carries the
measurement. `conformance/README.md` asks that a case may not be edited to make
a test pass, and in this domain that is mechanical rather than asked for.

**This file holds no subject expectation of its own.** Every expectation comes
out of the case file, and the only subject knowledge written here is which
function the server's rule is. What else is written here is the guards below,
which are expectations about the case file.

**The loader is copied from `test_isbn.py` rather than shared with it.** Two
independent readings of one rule, which is the arrangement this directory
already defends between the two languages; a shared loader is a single point
whose weakening is invisible in both domains at once. The ISBN loader is also
welded to guards that are ISBN's alone, and refactoring a heavily attacked file
to share sixty lines means re-verifying every one of them.

Three ways this could quietly stop testing anything, and what stops each:

* **The case file is missing, or has been emptied.** `_load()` raises at import,
  which pytest reports as a collection error and a non-zero exit. It never
  skips.
* **The case file has drifted from the format.** Every file is validated against
  `conformance/schema/subject.schema.json` before a single case runs.
* **The runner has drifted from the schema.** `test_every_outcome_class_the_schema_names_is_wired`
  compares the partition table against the schema's own list of outcome classes.
"""

import json
import re
from pathlib import Path
from typing import Any, Final

import pytest
from jsonschema import Draft202012Validator

from schemas.book import subject_for_storage

# backend/tests/conformance/test_subject.py -> the repository root.
_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = _ROOT / "conformance" / "cases" / "subject.json"
SCHEMA_PATH = _ROOT / "conformance" / "schema" / "subject.schema.json"
DOC_PATH = _ROOT / "conformance" / "subject.md"
CASES_DIR = _ROOT / "conformance" / "cases"


def _server_answer(entry: str) -> dict[str, Any]:
    """What the server does with one entry, in the case file's own vocabulary.

    **The real rule, not a copy of it.** `schemas.book.subject_for_storage` is
    what `BookCreate.one_subject_per_entry` calls, and it was lifted to module
    level so that this could ask it without building a request. Reimplementing
    the three steps here would make this file the rule's third home, which is
    the failure a shared case file exists to prevent.

    **Not `BookCreate.model_validate` either**: that runs every other validator
    on the model, so an unrelated failure would be reported here as a cross
    language divergence.
    """
    try:
        stored = subject_for_storage(entry)
    except ValueError:
        return {"kind": "refused", "value": None}
    if stored is None:
        return {"kind": "dropped", "value": None}
    return {"kind": "kept", "value": stored}


#: The partition, as a table from a pair of outcomes onto one class name.
#:
#: **A case's class is derived from what it says rather than declared in the
#: file**, so a case cannot be filed under a class it does not belong to, and a
#: pair nobody has thought about is classified nowhere and fails by name. That is
#: `book_columns.py`'s discipline: one partition over the whole population,
#: refused when a member is classified nowhere or twice. It is what this domain
#: has instead of the ISBN runner's operation dispatch, because every case here
#: runs the same pipeline and an `op` field would carry a guard that cannot fail.
#:
#: The two pairs missing here are the two the schema refuses: a browser that
#: drops what the server would have kept is a false refusal, and a server that
#: refuses what the browser sent costs the whole book.
OUTCOME_CLASSES: Final[dict[tuple[str, str], str]] = {
    ("kept", "kept"): "kept-by-both",
    ("kept", "dropped"): "dropped-by-the-server",
    ("dropped", "dropped"): "dropped-by-the-browser",
    ("dropped", "refused"): "refused-by-the-server",
}


def _outcome_class(case: dict[str, Any]) -> str | None:
    return OUTCOME_CLASSES.get((case["browser"]["kind"], case["server"]["kind"]))


# A floor, not a count. It exists for the same reason `palettes.test.ts` asserts
# it has rows it can actually see: a loader that silently produced one case, or
# none, would make every assertion below vacuous while the suite stayed green.
# The schema's `minItems` rejects an empty array; this rejects a gutted file.
# `conformance/subject.md` carries why the number is below the file's size and
# what actually protects the cases that carry a reason.
MINIMUM_CASES = 14


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
    # rendered character is indistinguishable on screen from three others, and
    # an escape survives every editor, terminal and diff. **Load bearing in this
    # domain rather than merely tidy**, because every case here turns on a
    # character with no width at all: a file written through a transport that
    # decodes the escape on the way past reads correctly and pins something
    # else. Enforced on the bytes, before the decode, since `json.loads` turns
    # both spellings into the same string and cannot tell them apart afterwards.
    raw = CASES_PATH.read_bytes()
    if not raw.isascii():
        offending = sorted({byte for byte in raw if byte > 0x7F})
        raise ValueError(
            f"{CASES_PATH} contains {len(offending)} non-ASCII byte values. Write a "
            "character outside ASCII as a \\u escape, so the case file stays greppable "
            "and a character with no width can be read at all."
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


#: The header of the guard dropping table in `conformance/subject.md`.
#:
#: **Anchored on, and in a file of this domain's own.** The identical header
#: stands in `conformance/isbn.md`, and that is the reason the two are separate
#: documents: a first match over one shared file would have this runner reading
#: the other domain's rows, which either fails the count below or, worse, passes
#: against the wrong rows while the table it was written to guard goes
#: unchecked. That is a guard disarmed by a data change with no diff to the
#: guard, and the remedy recorded for it here is to select by the property the
#: subject depends on rather than by position. One document per domain is that
#: property: the anchor is unique by construction.
_GUARD_TABLE_HEADER: Final = "| guard dropped | cases that catch it |"

#: The one cell in that table naming no case, verbatim. `conformance/subject.md`
#: argues that the browser's fold, count limit and per entry width have no server
#: counterpart that answers the same way, so a case for them could only assert
#: about one implementation and the schema refuses to express one. Written out so
#: that a row emptied by accident is a failure while that row stays legal, which
#: a bare "some row has no ids" test cannot do.
_DELIBERATELY_UNCATCHABLE: Final = "**nothing, and that is the scope rule**"

#: How many rows that table has, asserted as an equality.
#:
#: **A floor here is not a weaker version of this, it is a hole.** With `>=`, the
#: table can grow and this stay put, and the two step deletion the row check
#: exists to stop is then back one row later: add a row, delete a row, delete the
#: case that row named, green at every step because a smaller count satisfies a
#: floor. `test_isbn.py` carries the same constant for the same reason and its
#: comment carries the history that bought it.
#:
#: **What this does not bound is which rows they are.** Swapping a row for one
#: that names a different real case keeps the count and satisfies both checks
#: below, and the case the old row protected is then named nowhere and deletes
#: green. Closing it needs the ids written here, which would be a third home for
#: a list that already has two, so the exclusion is stated rather than closed.
_GUARD_TABLE_ROWS: Final = 11


def _doc_guard_table() -> list[tuple[str, str, list[str]]]:
    """Rows of that table, as (what was dropped, the cell verbatim, the case ids in it).

    **The cell comes back verbatim as well as parsed**, because a row that yields
    no id because somebody emptied it and the one row that yields none by design
    are otherwise the same value, and the caller has to tell them apart.

    Read out of the Markdown rather than listed in this file: a list here would
    be a third home for the same fact. Returns nothing at all if the header moves
    or is reworded, which the caller treats as a failure rather than as an empty
    table.

    **The second column only.** The first names rules in prose, and a word in it
    could be shaped like a case id.
    """
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()
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


def _header_occurrences() -> int:
    """How many times the guard table's header stands in the document.

    **The split across documents makes the anchor unique between domains and
    does nothing within one.** Both runners take a `lines.index`, which is a
    first match, so a second table under the same header in this one document
    reproduces the defect the split closed one level down, and a table added
    **above** the first is the silent direction: the count still matches, the
    rows are somebody else's, and the table this runner was written to guard
    goes unread.

    **What this refuses that it should not**, stated rather than discovered: a
    fenced example of the table format, which would put the header in the
    document a second time legitimately. Neither conformance document has one,
    so this arms immediately rather than needing the tree cleaned up first.
    """
    return DOC_PATH.read_text(encoding="utf-8").splitlines().count(_GUARD_TABLE_HEADER)


CASES = _load()
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

#: The cases whose browser answer is a value, which is the population the
#: equality arm can run at all. A separate list rather than a skip inside the
#: arm: pytest reports a skip and a pass the same way to a reader scanning a
#: summary, and this suite's whole argument is that it never passes by running
#: nothing.
SENT_BY_THE_BROWSER = [case for case in CASES if case["browser"]["kind"] == "kept"]

#: Of those, the ones where the browser's value is not the input back.
#:
#: **This is the equality arm's real population and the count above is not.**
#: Where the browser returns the input unchanged the equality arm is character
#: for character the absolute arm, so it asserts nothing the other does not, and
#: a file of nothing but such cases would leave an arm of that many copies. A
#: count of what the browser **sends** cannot see that; a count of what it
#: **changes** can. **No figure is written here**, because it moves with every
#: case added and a count beside a rule goes stale against the rule.
TRANSFORMED_BY_THE_BROWSER = [
    case for case in SENT_BY_THE_BROWSER if case["browser"]["value"] != case["input"]
]


class TestTheCaseFileIsWorthRunning:
    """The guards that stop this suite passing while testing nothing."""

    def test_the_file_carries_enough_cases_to_be_a_specification(self):
        assert len(CASES) >= MINIMUM_CASES, (
            f"{CASES_PATH} holds {len(CASES)} cases, below the floor of {MINIMUM_CASES}. "
            "Either the file has been gutted or the floor needs raising with the reason."
        )

    def test_every_outcome_class_the_schema_names_is_wired(self):
        """The dispatch cross check, against the table's range and not the cases.

        What the cases happen to exercise is a different question and the arm
        below is that one. A class added to the specification and not wired here
        fails on this line rather than going unexercised.
        """
        declared = set(SCHEMA["$defs"]["outcomeClass"]["enum"])
        wired = set(OUTCOME_CLASSES.values())
        assert wired == declared, (
            "the partition table and the schema disagree about which outcome classes "
            f"exist: only in the schema {sorted(declared - wired)}, "
            f"only in this runner {sorted(wired - declared)}"
        )

    def test_every_case_falls_in_exactly_one_outcome_class(self):
        """A lookup in one table, so what this fails on is a pair it does not know.

        "At most one" holds by construction. "At least one" does not: the schema
        admits four pairs of outcomes and the table knows four, and a fifth
        arriving in either place without the other is what this catches.
        """
        unclassified = [
            f"{case['id']} ({case['browser']['kind']}/{case['server']['kind']})"
            for case in CASES
            if _outcome_class(case) is None
        ]
        assert unclassified == [], (
            f"cases in {CASES_PATH.name} whose pair of outcomes is classified nowhere: "
            f"{unclassified}. Either the pair is one the schema should refuse, or the "
            "partition has grown a class and this table has not."
        )

    def test_every_outcome_class_is_exercised_by_at_least_one_case(self):
        exercised = {_outcome_class(case) for case in CASES}
        missing = sorted(set(OUTCOME_CLASSES.values()) - exercised)
        assert missing == [], (
            f"outcome classes with no case: {missing}. A file that lost every refusal "
            "case would leave the separator rule pinned by nothing."
        )

    def test_the_equality_arm_has_a_population_it_is_not_a_copy_of(self):
        """The equality arm needs cases where the browser changed something.

        **Two vacuities, and only the second can actually occur here.** A file
        whose every case was dropped by the browser would leave the arm with
        nothing to run, which the first count below refuses. A file whose every
        kept case returns the input unchanged would leave the arm running, and
        every one of its assertions would be the absolute arm written twice:
        `server(browser(x))` is `server(x)` by substitution, not by measurement.

        The second is the one the shipped file is close to, so it is the one
        worth counting. Asserting only that something was sent is the count that
        cannot see it.
        """
        assert len(SENT_BY_THE_BROWSER) > 0, (
            f"no case in {CASES_PATH.name} has the browser keeping a value, so the "
            "equality arm would run over nothing and pass."
        )
        assert len(TRANSFORMED_BY_THE_BROWSER) > 0, (
            f"every case in {CASES_PATH.name} that the browser keeps returns the input "
            "unchanged, so every assertion of the equality arm is the absolute arm "
            "written a second time and the arm pins nothing of its own."
        )

    def test_the_guard_table_header_stands_exactly_once(self):
        found = _header_occurrences()
        assert found == 1, (
            f"the guard dropping table's header stands {found} times in {DOC_PATH}, and "
            "the extraction takes the first match. One document per domain makes this "
            "anchor unique between domains and not within one, so a second table here, "
            "above or below, silently moves which rows are guarded."
        )

    def test_every_case_the_document_names_still_exists(self):
        """The floor is a count, and a count cannot protect the cases that carry the reason.

        The cases worth deleting to make a failure go away are the ones this
        domain exists for, and every outcome class would still be exercised with
        them gone. `conformance/subject.md` names the load bearing cases by id in
        its guard dropping table, so binding that table to the case file makes
        deleting one of them a failure here, and makes a renamed case show up as
        a table pointing at nothing.

        The ids are read out of the document rather than listed here, because a
        list written in this file is a third place to keep the same fact in step.

        **Every row is checked, not just the set of ids they add up to, and the
        row count is an equality.** `test_isbn.py` carries what a floor here cost
        the first time.
        """
        rows = _doc_guard_table()
        assert len(rows) == _GUARD_TABLE_ROWS, (
            f"the guard dropping table in {DOC_PATH} yielded {len(rows)} rows against "
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
            f"rows of {DOC_PATH}'s guard dropping table name no case and are not the "
            f"one row allowed to: {silent}. A rule with no case is a rule that can be "
            "changed in silence, which is the whole argument the table makes."
        )

        known = {case["id"] for case in CASES}
        named = {identifier for _, _, identifiers in rows for identifier in identifiers}
        assert named <= known, (
            f"{DOC_PATH} names cases that are not in {CASES_PATH.name}: "
            f"{sorted(named - known)}. A case may not be deleted or renamed while the "
            "table that explains what it pins still points at it."
        )

    def test_every_domain_in_the_case_directory_has_a_runner_on_both_sides(self):
        """A domain added on one side only reads as a green suite on the other.

        That is the failure a second domain in this directory makes possible for
        the first time, so it is closed here rather than left for the third one.
        Membership is derived from what the repository versions rather than from
        a list, so a new domain is covered by the commit that creates its case
        file.

        **What this checks is that a runner file exists, not that it runs those
        cases.** A file named for a domain and reading another domain's cases
        passes here. Closing that would need this arm to parse two languages,
        and each runner's loader already fails loudly on a missing or drifted
        case file, which is the half that costs a silent pass.
        """
        domains = sorted(path.stem for path in CASES_DIR.glob("*.json"))
        assert domains, f"no case files at all in {CASES_DIR}"
        missing = [
            str(expected.relative_to(_ROOT))
            for domain in domains
            for expected in (
                _ROOT / "backend" / "tests" / "conformance" / f"test_{domain}.py",
                _ROOT / "frontend" / "tests" / "conformance" / f"{domain}.test.ts",
            )
            if not expected.is_file()
        ]
        assert missing == [], (
            f"conformance domains with no runner on one side: {missing}. A case file "
            "only one suite reads is a specification half the codebase does not answer to."
        )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_server_answers_what_the_case_says_about_the_raw_entry(case):
    """The absolute arm: the server's own answer about what the file stated.

    This is what stops the `server` field being edited to agree with a changed
    `browser` field. `conformance/subject.md` has the measurement over the three
    repairs.
    """
    actual = _server_answer(case["input"])
    assert actual == case["server"], (
        f"{case['id']}: the server's rule over {case['input']!r} gave {actual!r}, "
        f"the shared cases say {case['server']!r}.\n{case['why']}"
    )


@pytest.mark.parametrize(
    "case", SENT_BY_THE_BROWSER, ids=[case["id"] for case in SENT_BY_THE_BROWSER]
)
def test_the_server_answers_the_same_about_what_the_browser_sends(case):
    """The equality arm, and it is the whole instrument.

    `server(browser(x)) == server(x)`, run in Python against a literal, so
    neither suite has to cross a runtime. The TypeScript side holds that the
    literal really is what the browser emits; this holds that normalising it
    gives what normalising the file's own text would have given.

    A browser rule wider than the server's reddens here rather than letting a
    value through: it would send a subject the file never stated, and the server
    would never have produced it from the file.
    """
    sent = case["browser"]["value"]
    actual = _server_answer(sent)
    assert actual == case["server"], (
        f"{case['id']}: the browser sends {sent!r} for input {case['input']!r}, and "
        f"the server's rule over that gives {actual!r} rather than its own answer about "
        f"the input, {case['server']!r}. The browser has changed the server's answer.\n"
        f"{case['why']}"
    )
