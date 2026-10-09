# Conformance cases

Rules that must give the same answer everywhere, written down once, in a format
no language owns.

```
conformance/
  cases/isbn.json          the cases
  schema/isbn.schema.json  the shape a case file has to have
```

Two implementations run this file today: `backend/tests/conformance/test_isbn.py`
and `frontend/tests/conformance/isbn.test.ts`. A disagreement between them is a
failing test on the side that is wrong.

## Why this exists, with the measurement

`frontend/src/lib/isbn.ts` mirrors `backend/isbn.py` deliberately: the barcode
scanner has to decide within a video frame whether what it just read is a book,
and a network call per frame is not an option. Its docstring claimed the two
were "pinned to the same cases by tests on both sides". They were not.

**JavaScript's `\d` is ASCII only. Python's `str.isdigit()` is Unicode.**
Measured 2026-08-31, same inputs, both implementations:

| input | browser | server |
|---|---|---|
| `978` and nine ARABIC-INDIC DIGIT ZERO and `2` | `null` | the input back, verbatim |
| `978` and ten SUPERSCRIPT TWO | `null` | `ValueError` out of `int()` |

So for months the two disagreed about whether a string was an ISBN, silently, and
a book could be stored under an identifier no other client could ever match. It
was found by probing a route, not by a test. Nothing on either side would have
noticed.

**Both rows are closed now, by two separate changes.** The checksum predicates
gained their ASCII guards first, which is what stopped the crash and is why the
server answers `null` to both rows today. `normalise` gained one with this
directory, which is what makes the two implementations agree on the inputs the
predicates never see. Neither change was made because a test failed, which is
the argument for this directory rather than against it.

That is the whole argument. Two implementations drift by one edge case, the
failure is silent, and the repair a year later is a data migration.

## What a case is

Input, expected output, and a `why`. Nothing else.

```json
{
  "id": "parse-rejects-a-non-bookland-ean13",
  "op": "parse",
  "input": "4006381333931",
  "expect": null,
  "why": "A real EAN-13 that passes the modulus 10 check and is not a book..."
}
```

| field | what |
|---|---|
| `id` | Lowercase and hyphens, unique in the file. It is what a failure is named after. |
| `op` | The operation, in the specification's spelling. Each runner maps it onto its own naming in an explicit table. |
| `input` | A string, or null for the two operations that are null safe. |
| `expect` | What every implementation must answer. |
| `why` | Why the case is here. A measurement or a rule, never an opinion. |

**`schema/isbn.schema.json` is the enforceable version of that table**, and both
runners validate the case file against it before running a single case. A
renamed field, a missing `why`, a `parse` case expecting a boolean: each fails
loudly rather than being read as something it is not, or skipped.

Uniqueness of `id` is asserted by the runners instead, because JSON Schema
cannot express uniqueness across a property of array items.

## Adding a case

1. Add it to `cases/isbn.json`, with a `why` that says what was measured.
2. Run both suites. They read the same file, so a case that only one side
   satisfies is a divergence, and the divergence is the finding.
3. Fix the implementation that is wrong.

**Write a character outside ASCII as a `\u` escape**, which keeps the whole file
ASCII and is enforced rather than asked for: the Python runner refuses a case
file carrying a non-ASCII byte. Both `json.load` and `JSON.parse` decode them
identically, an escape survives every editor, terminal and diff that a literal
does not, and it is greppable. `"978\u0660"` says which character it is; the
rendered form does not, and it is indistinguishable on screen from three other
digit zeros.

## Rules

**The cases worth arguing about are added when a bug is found, not when a
function is written.** The value is in the edge cases nobody would invent, and
every non-ASCII case in `isbn.json` came out of one night's findings, each
carrying what was measured. The file also holds the ordinary cases a
specification needs in order to be one: a canonical ISBN-13, the ISBN-10
conversion, an X check digit, hyphens in the wrong places. Those are the base
rather than the reason this directory exists, and the rule above is about the
second kind.

**No case may reference a database.** These are pure functions of their input or
they are not conformance material. That is also what keeps the runners small
enough to be obviously correct.

**A case may not be edited to make a test pass.** Changing an expectation is
changing the protocol. It belongs in a commit that says so and that lands on
every implementation together.

**There is no per implementation opt out, and that is a deliberate refusal.**
Matrix's `complement` has exactly this problem at a much larger scale and solves
it with inverted build tags that exclude known broken tests per server. It has to:
a large ecosystem cannot block one homeserver's release on another homeserver's
bug. **Two implementations of one codebase's rules is a different problem from
many implementations of a public protocol**, and the escape hatch is where the
two designs part. Nothing here is allowed to skip a case it fails, so "Matrix
does it" is not an argument for adding one.

**The fixtures are the specification.** When a rule moves to TypeScript for good
and the Python side is deleted, the cases stay. They are the only artefact of
this that outlives the migration, which is also why this directory is published
rather than kept internal.

## What each case pins, and the asymmetry underneath it

Both implementations now guard ASCII twice: at the door (`normalise`) and in the
checksum predicates. Dropping each guard in turn, re-derived 2026-09-06 against
this tree rather than carried over, and recording which cases notice:

| guard dropped | cases that catch it |
|---|---|
| server `normalise` | `normalise-strips-non-ascii-digits`, `parse-strips-a-trailing-non-ascii-digit` |
| server `is_valid_isbn13` | `is-valid-isbn13-rejects-arabic-indic-digits`, `is-valid-isbn13-rejects-superscript-twos` |
| server `is_valid_isbn10` body | `is-valid-isbn10-rejects-a-non-ascii-body` |
| server `is_valid_isbn10` check character | `is-valid-isbn10-rejects-a-non-ascii-check-digit` |
| browser `normalise` | `normalise-strips-non-ascii-digits`, `parse-strips-a-trailing-non-ascii-digit` |
| browser `isValidIsbn13`, and both ISBN-10 regexes | **nothing, and it cannot** |

**The last row is a property of JavaScript, not a hole in the cases.** Widening
those regexes to `\p{Nd}` lets a non-ASCII digit through the shape test, and the
arithmetic then rejects it anyway: `Number("\u0660")` is `NaN`, and `NaN % 10 === 0`
is false. Python does not get that for free. `int("\u0660")` is `0` and
`int("\uff17")` is `7`, so a checksum computed over them passes.

**That asymmetry is the whole reason the two drifted.** The browser was correct by
accident of `Number()` while the server needed an explicit guard and did not have
one. Which is also why the four rows above that name only the server are not a
sign the cases are server biased: they are the rows where a guard can be removed
and the answer still change.

**The `parse` cases cannot substitute for the predicate cases.** Once the door is
closed, a non-ASCII string never reaches a checksum function through `parse`, so
dropping `is_valid_isbn10`'s body guard leaves every other case in the file
passing, and only `is-valid-isbn10-rejects-a-non-ascii-body` red. Stated as
every other case rather than as a count, because a count stops being re-derived
the moment a case is added. A case per layer, because a
layer with no case is a layer that can be deleted in silence.

## The floor

Each runner asserts the file holds at least twenty cases, on top of the schema
rejecting an empty array. A conformance suite that silently runs zero cases is
the failure mode that makes the whole idea theatre, and a loader that quietly
matched nothing would leave every assertion vacuous with the suite still green.
The same guard, for the same reason, is in `frontend/tests/theme/palettes.test.ts`
as "has rows this test can actually see".

Each runner also compares its own dispatch table against the list of operations
in the schema, so an operation added to the specification and not wired into an
implementation fails there rather than going unexercised.
