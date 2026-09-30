# ISBN conformance cases

`cases/isbn.json`, against `schema/isbn.schema.json`, run by
`backend/tests/conformance/test_isbn.py` and
`frontend/tests/conformance/isbn.test.ts`.

[`README.md`](README.md) holds the directory's argument, the rules every domain
obeys, and the measurement this whole directory came out of. This file holds
what is ISBN's alone.

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

**One operation, one runtime, one literal answer**, which is what lets both
runners run every case with no knowledge of each other. The subject domain is
not that shape and `subject.md` says why, which is the reason the field table
lives per domain rather than once.

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
