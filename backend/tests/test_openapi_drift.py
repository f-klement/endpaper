"""The committed OpenAPI document is the one this code produces.

`frontend/openapi.json` is a committed artefact, and the frontend tests read it
as the authority on what the API accepts, comparing what the client sends against
it.

**No count here**, deliberately. The figure this sentence carried was two,
copied out of a comment that has since gone, and a walk of that directory
finds more. A number nothing recomputes is read as current for exactly as
long as it sits there, which is the rule the configuration file beside this
one now states about its own removed durations.

Nothing re-derived that document, so an edit to it made every one of those
assertions pass while agreeing with nothing.

**This comparison used to run only after a push**, which put it minutes late
rather than before one. Measured 2026-09-21 over the last 300 pipelines on the
default branch: of 24 backend job failures, **4 failed before pytest ran**, on
this comparison. All four were a docstring edit in a router or a schema module,
because FastAPI puts a route's docstring into the schema description.

**So this is a tripwire for prose, and that is deliberate.** Editing a docstring
under `routers/` or `schemas/` reddens this file. The remedy is
`bun run api:generate`, which rewrites the committed document and the generated
client together. Regenerating to silence this test is the same act as changing
the API contract, so it is a thing to do on purpose.

**The generator runs as a subprocess rather than through `main.app.openapi()`
here.** The committed bytes are what that script writes, with a two space
indent, sorted keys and a trailing newline, and the app object inside a suite
run has been through the fixtures. Bytes against bytes is the same question the
generated client's own inputs answer.

**Not the question `tests/api_contract.py` asks**, which is whether the
committed schema and the running app agree about responses. This is the narrower
one of whether the committed file is the document this code produces at all.

**The comparison is exact and has no escape hatch**: no marker, no environment
switch, no normalising of whitespace or key order, and no tolerance for a
missing final newline. Whether one is ever added belongs to whoever owns the API
contract and not to whoever is trying to get a suite green, because every one of
those options turns a red into a silence.

Generation costs about 3.6s, measured three times on the development host. The
fixture below is module scoped so a run pays it once, and on a full run with
`--durations=12` this file reached none of the twelve slowest tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BACKEND = _REPO / "backend"
_GENERATOR = _BACKEND / "scripts" / "dump_openapi.py"
_COMMITTED = _REPO / "frontend" / "openapi.json"


def not_a_verdict(returncode: int, stdout: bytes) -> str | None:
    """Why this generation cannot be read as a verdict about drift, or None.

    **A generation that did not happen must not be reported as a drift.** The
    comparison would report a prefix relationship and send the reader to
    regenerate and commit a document the generator never wrote, which is the
    wrong defect and the wrong remedy in the one message they act on.

    **Exit 0 with no output is the live route rather than a hypothetical one.**
    `scripts/dump_openapi.py`'s entry point returns 0 unconditionally, so any
    `try` placed around its body produces exactly that pair, and checking only
    the exit status would pass it straight through.
    """
    if returncode != 0:
        return f"the schema generator exited {returncode}"
    if not stdout.strip():
        return "the schema generator exited 0 and wrote nothing"
    return None


def generate(generator: Path = _GENERATOR) -> bytes:
    """The document the generator writes, exactly as it writes it.

    **stdout only.** The generator replays the migrations against a throwaway
    database and logs that to stderr, so a call that merged the two streams
    would compare the log as part of the schema and never agree with the
    committed file.

    **`generator` is a parameter so the refusal below is reachable from a test.**
    Checking `not_a_verdict` as a function leaves its call site unchecked, and the
    call site is what a mutation removes: with this function callable against a
    stub, deleting the `assert` reddens two named arms instead of nothing.
    """
    result = subprocess.run(
        [sys.executable, str(generator)],
        cwd=_BACKEND,
        capture_output=True,
        check=False,
    )
    broken = not_a_verdict(result.returncode, result.stdout)
    assert broken is None, (
        f"{broken}, so nothing here is a verdict about drift:\n"
        f"{result.stderr.decode('utf-8', errors='replace')}"
    )
    return result.stdout


def first_difference(committed: bytes, produced: bytes) -> str | None:
    """Where two documents first disagree, or None when they agree.

    **A byte offset rather than a line diff.** The trailing newline and the
    indent are part of what is compared, and a line oriented diff reports a lost
    final newline as no change at all, which is exactly the edit a hand written
    fix to this file makes.
    """
    if committed == produced:
        return None
    for offset in range(min(len(committed), len(produced))):
        if committed[offset] != produced[offset]:
            return (
                f"first difference at byte {offset}: committed "
                f"{committed[offset : offset + 48]!r} against produced "
                f"{produced[offset : offset + 48]!r}"
            )
    shorter, longer = sorted((len(committed), len(produced)))
    which = "committed" if len(committed) > len(produced) else "produced"
    return (
        f"one document is a prefix of the other: {which} carries "
        f"{longer - shorter} more bytes, from byte {shorter}"
    )


@pytest.fixture(scope="module")
def produced() -> bytes:
    """One generation for the whole file.

    Module scoped because generation is the expensive part, and this project's
    `addopts` carries `--dist loadfile`, so a file's tests stay on one worker
    and pay it once rather than once per worker.
    """
    return generate()


class TestTheCommittedSchemaIsTheOneThisCodeProduces:
    def test_the_committed_document_is_byte_identical_to_a_fresh_generation(
        self, produced: bytes
    ) -> None:
        difference = first_difference(_COMMITTED.read_bytes(), produced)
        assert difference is None, (
            "frontend/openapi.json is not what this code produces. If the schema "
            "change was intended, regenerate the document and the client together "
            "with `bun run api:generate` and commit both. "
            f"{difference}"
        )

    def test_the_generation_is_a_whole_schema_document(self, produced: bytes) -> None:
        """A generation that is not empty and is still not a schema.

        **The empty case is refused upstream**, by `not_a_verdict` inside
        `generate`, so this arm is not what covers it and does not claim to. What
        it covers is output that arrived, is not empty, and is not a schema
        document: truncated JSON, a traceback on stdout, a bare `{}`. That is what
        makes a failure of the arm above a statement about drift.
        """
        document: Any = json.loads(produced)
        assert document["openapi"].startswith("3."), document["openapi"]
        assert document["paths"], "a schema with no paths"


class TestTheComparisonCanFail:
    """Both verdicts this file rests on are driven directly, not only through a real run.

    The arm above passes on a stale document too if the comparison is vacuous,
    and this repository has shipped a guard that went quiet because an input it
    compared was empty on every real call. So the comparison is exercised
    directly, and the identical pair below distinguishes a working comparison
    from one that refuses unconditionally.

    **The last two arms drive `generate` rather than `not_a_verdict`**, and that
    is the whole reason they exist. A pure function checked on its own leaves its
    call site unchecked: with the refusal tested only as a function, deleting the
    `assert` that applies it left every arm in this file green while the failure
    it prevents stayed reachable.

    **The mutations below were not chosen by whoever wrote the comparison.** An
    author picks the case their own code already handles, which is why the shapes
    here are the ones a real failure takes rather than the ones that were
    convenient: a changed value mid document, a key that only one side carries, a
    lost final newline, a generator that exits non zero, and a generator that
    exits 0 having written nothing.
    """

    def test_a_changed_value_is_reported(self) -> None:
        committed = b'{\n  "openapi": "3.1.0"\n}\n'
        assert first_difference(committed, committed.replace(b"3.1.0", b"3.0.0"))

    def test_a_key_only_one_side_carries_is_reported(self) -> None:
        committed = b'{\n  "a": 1,\n  "b": 2\n}\n'
        assert first_difference(committed, b'{\n  "a": 1\n}\n')

    def test_a_lost_trailing_newline_is_reported(self) -> None:
        """The edit a hand written fix to the committed file makes, and the one a
        line oriented diff calls no change."""
        committed = b'{\n  "a": 1\n}\n'
        assert first_difference(committed, committed.rstrip(b"\n"))

    def test_two_identical_documents_are_not_reported(self) -> None:
        committed = b'{\n  "a": 1\n}\n'
        assert first_difference(committed, committed) is None

    def test_a_generator_that_exits_non_zero_is_refused(self, tmp_path: Path) -> None:
        """Refused as a broken generator, never reported as a drift.

        **The `match` is load bearing and is the only thing separating this arm from the
        next one.** The stub writes nothing as well as exiting non zero, so with a bare
        `pytest.raises(AssertionError)` the empty output branch absorbs it and deleting
        the exit status branch is caught by nothing. Measured: loosened, that deletion
        reddens 0 arms instead of 1.
        """
        stub = tmp_path / "exits_one.py"
        stub.write_text("raise SystemExit(1)\n")
        with pytest.raises(AssertionError, match="exited 1"):
            generate(stub)

    def test_a_generator_that_exits_zero_and_writes_nothing_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The route the entry point's unconditional `return 0` leaves open.

        Unrefused, the comparison reports the committed document as the whole
        schema longer than the produced one and tells the reader to regenerate and
        commit both, which is a remedy they should not follow.
        """
        stub = tmp_path / "writes_nothing.py"
        stub.write_text("pass\n")
        with pytest.raises(AssertionError, match="wrote nothing"):
            generate(stub)
