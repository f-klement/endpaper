# Conformance cases

Rules that must give the same answer everywhere, written down once, in a format
no language owns.

```
conformance/
  cases/<domain>.json          the cases
  schema/<domain>.schema.json  the shape that domain's case file has to have
  <domain>.md                  what a case is in that domain, and what each one pins
```

| domain | cases | schema | runners | document |
|---|---|---|---|---|
| ISBN | `cases/isbn.json` | `schema/isbn.schema.json` | `backend/tests/conformance/test_isbn.py`, `frontend/tests/conformance/isbn.test.ts` | [`isbn.md`](isbn.md) |
| subject | `cases/subject.json` | `schema/subject.schema.json` | `backend/tests/conformance/test_subject.py`, `frontend/tests/conformance/subject.test.ts` | [`subject.md`](subject.md) |

A disagreement between two implementations of one domain is a failing test on
the side that is wrong.

**One document per domain, and it is not tidiness.** Each runner reads its own
document to find its guard dropping table, and it finds it by matching a header.
Two such tables in one file means the first match wins: adding the second domain
here would have made the ISBN runner read the subject table, which either fails
on the row count or, worse, passes against the wrong rows while the table it was
written to guard goes unchecked. That is a guard disarmed by a data change with
no diff to the guard, which this repository has already paid for once. A
document per domain makes each anchor unique by construction rather than by two
authors agreeing to differ.

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

An `id`, a `why`, and whatever the domain's own invariant needs in between.

| field | what |
|---|---|
| `id` | Lowercase and hyphens, unique in the file. It is what a failure is named after. |
| `why` | Why the case is here. A measurement or a rule, never an opinion. |

**The rest is the domain's**, and it is set by what the invariant is rather than
by symmetry with a neighbour. ISBN pins one function's answer, so a case is an
operation, an input and an expectation. Subject pins an equality across two
different functions, so a case is an input and both implementations' answers.
Each domain's document holds its own field table.

**`schema/<domain>.schema.json` is the enforceable version of that table**, and
both runners validate the case file against it before running a single case. A
renamed field, a missing `why`, an expectation of the wrong type: each fails
loudly rather than being read as something it is not, or skipped.

Uniqueness of `id` is asserted by the runners instead, because JSON Schema
cannot express uniqueness across a property of array items.

## Adding a case

1. Add it to `cases/<domain>.json`, with a `why` that says what was measured.
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

**An escape typed into a file through a tool that rewrites it is the trap the
rule guards against, one layer up.** Where a case turns on a character with no
width, get the escape onto disk by serialising the real character with a JSON
writer rather than by typing the six characters of the escape: a transport that
decodes `\u` on the way past leaves a file that reads correctly and pins the
wrong thing. The ASCII refusal above catches that, at import, by naming the
offending byte values.

## Rules

**The cases worth arguing about are added when a bug is found, not when a
function is written.** The value is in the edge cases nobody would invent, and
every non-ASCII case in `isbn.json` came out of one night's findings, each
carrying what was measured. Each file also holds the ordinary cases a
specification needs in order to be one. Those are the base rather than the
reason this directory exists, and the rule above is about the second kind.

**No case may reference a database.** These are pure functions of their input or
they are not conformance material. That is also what keeps the runners small
enough to be obviously correct.

**A case whose assertion can be made in one suite alone does not belong here.**
A rule with one implementation is tested where it lives; putting it here makes
this directory a second home for it and buys nothing, since no disagreement is
possible. Each domain's schema enforces this by requiring both sides' answers on
every case, so a case about one implementation cannot be expressed rather than
being refused by a reviewer who noticed.

**A case may not be edited to make a test pass.** Changing an expectation is
changing the protocol. It belongs in a commit that says so and that lands on
every implementation together. **This stays a rule rather than a mechanism**,
and a domain's shape can only ever close part of it: `subject.md` closes two of
the three repairs somebody reaches for and says which one it does not. **Both
runners read a case's input; what no guard over a case file does is hold an
expectation about it**, so a case rewritten under its own id is an edit no arm
can see.

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

## The floor

Each runner asserts its file holds at least a stated number of cases, on top of
the schema rejecting an empty array. A conformance suite that silently runs zero
cases is the failure mode that makes the whole idea theatre, and a loader that
quietly matched nothing would leave every assertion vacuous with the suite still
green. The same guard, for the same reason, is in
`frontend/tests/theme/palettes.test.ts` as "has rows this test can actually see".

**A floor is not what protects the cases that carry a reason.** It leaves the
difference between itself and the file's size deletable, and the cases worth
deleting to make a failure go away are exactly the ones this directory exists
for. Each domain's document names those by id in a guard dropping table, and
each runner binds its own document's table to its own case file, so deleting one
of them fails rather than passing.

Each runner also cross checks itself against its schema: the ISBN runner
compares its dispatch table against the schema's list of operations, and the
subject runner compares its outcome classifier against the schema's list of
outcome classes. An entry added to a specification and not wired into an
implementation fails there rather than going unexercised.
