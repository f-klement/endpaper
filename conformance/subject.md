# Subject conformance cases

`cases/subject.json`, against `schema/subject.schema.json`, run by
`backend/tests/conformance/test_subject.py` and
`frontend/tests/conformance/subject.test.ts`.

[`README.md`](README.md) holds the directory's argument and the rules every
domain obeys. This file holds what is subject's alone.

## The invariant is an equality across two different functions

A subject arrives in a file a stranger wrote. `frontend/src/lib/bookRequest.ts`
bounds it before the request is built, and `backend/schemas/book.py` normalises
it again on the way into the column. The two are **not** the same function and
are not meant to be: the browser collapses whitespace and trims, the server
deletes the control characters that have no width as well.

What must hold is that the browser never changes the server's answer:

```
server(browser(x)) == server(x)
```

**So the value the browser sends is one the file stated**, and the subject that
lands in the column is the server's own answer about the file, reached one step
early. A browser rule wider than the server's does not let a bad value through,
it invents a value: it would store a subject the file never wrote and the server
would never have produced.

That is a different shape from ISBN, where one operation is implemented twice
and a case is an input and one answer. Here two different functions compose, and
no suite can run the other language.

## What a case is: one subject, recorded at three points

```json
{
  "id": "a-mark-at-the-start-is-kept-on-both-sides",
  "input": "\uFEFFFiction",
  "browser": { "kind": "kept", "value": "\uFEFFFiction" },
  "server": { "kind": "kept", "value": "\uFEFFFiction" },
  "why": "Measured 2026-09-30, against both implementations in this tree. ..."
}
```

| field | what |
|---|---|
| `id` | Lowercase and hyphens, unique in the file. It is what a failure is named after. |
| `input` | One subject, exactly as a file stated it. Never a list: see *Scope*. |
| `browser` | What the browser's bound answers. `kind` is `kept` or `dropped`. |
| `server` | What the server's per entry rule answers. `kind` is `kept`, `dropped` or `refused`. |
| `why` | Why the case is here. A measurement or a rule, never an opinion. |

`value` is the string when the kind is `kept` and `null` otherwise, which the
schema enforces.

**Pinning the intermediate is what makes the cross language property checkable
inside one language.** Three arms, none of which runs the other runtime:

| side | arm | what it holds |
|---|---|---|
| frontend | `boundCategories([input])` matches `browser` | the browser really does emit `browser.value` |
| backend, absolute | the server's rule over `input` matches `server` | the server's own answer about the raw entry |
| backend, the equality | where the browser kept: the server's rule over `browser.value` matches `server` | `server(browser(x)) == server(x)`, run in Python against a literal |

## The two arms lock each other

`README.md` says a case may not be edited to make a test pass. Here **two of the
three repairs somebody reaches for are closed mechanically** rather than by
asking, and the third is not closed at all. Widen the browser's collapse and the
frontend arm reddens; then try each repair in turn, measured 2026-09-30 over
this file:

| repair attempted | what reddens |
|---|---|
| edit `browser.value` to the widened output | the backend **equality** arm, on all seven mark cases: the server computes a different answer from that literal than from `input` |
| edit `server.value` to agree as well | the backend **absolute** arm, on the same seven: `server.value` no longer equals the server's answer about `input` |
| edit `input`, and regenerate both answers from the implementations as they now stand | **nothing**. See below: the guard dropping table binds ids, not content |

**The first two rows are measured, 7 of 7 each.** That is why the backend runner
is not optional: the frontend arm on its own is a golden file, and the next seat
greens it by editing data.

**The third row is the one nothing catches, and this file used to claim
otherwise.** The guard dropping table below **binds ids, not content**: its arms
are a row count, a check that no row names nothing, and a test that every id it
names exists. **None of them reads an input or either answer.** So a case
rewritten under its own id, with both answers regenerated from the
implementations as they now stand, passes every arm in both runners: it is not a
deleted case, it reads as a live one, the table still points at it, and it is no
longer the case its id says it is. Measured over the seven mark cases with the
collapse widened, and the rewrite validates, stays ASCII, keeps every id and
every outcome class, and clears the floor.

**So the extent is not claimed in either direction.** Two repairs are closed and
a third is open, and the open one is why the reason in each `why` is written to
be read rather than to be regenerated.

## Position is the axis, not presence

**Measured 2026-09-30**, over the seven shapes in this file that carry
ZERO WIDTH NO-BREAK SPACE, against two widenings of the browser:

| shape | collapse widened to JavaScript whitespace | trim widened to JavaScript whitespace |
|---|---|---|
| mark at the start | red | red |
| mark at the end | red | red |
| mark at both ends | red | red |
| mark followed by a space | red | red |
| mark mid word | red | **green** |
| a run of marks mid word | red | **green** |
| mark between two spaces | red | **green** |

**Only a mark at an edge catches the second widening, and the intuitive shape is
mid word.** A file carrying one such case would very likely carry the mid word
one and would miss that mutant entirely. A trim never reaches the middle of a
value, so an arm placed in the middle cannot observe a trim at all. Vary the
position deliberately: it is the axis, and the character alone is not.

## Scope: one entry, and nothing above it

**A case is one subject, never a list**, and that is load bearing rather than a
simplification. Above the entry the two implementations are **deliberately
unequal, in both directions**:

- over the width and over a separator bearing entry, the browser **drops** and
  the server **refuses** the whole request. That asymmetry is the entire purpose
  of the browser's bound;
- a repeated subject is **folded** by the browser and **kept twice** by the
  server;
- the count limit is a `maxItems` on the server and an early exit in the
  browser.

A case at that level would have to say "this side only", which is the per
implementation opt out `README.md` refuses by name. The per entry rule is the
clean seam, and it is where this file stops. Measured: the 120 character width
is the field's annotation rather than the validator, so it is above the seam
too. The list level rules stay in `frontend/tests/lib/bookRequest.test.ts`,
which is where they already are and where they can be tested.

**One asymmetry survives inside the seam and needs no exemption**, which is the
result worth having. An entry of nothing but the control characters the server
deletes is **kept** by the browser and **dropped** by the server. The equality
still holds, because the server's answer about the browser's value and about the
raw entry are both "nothing". The invariant covers the documented narrowing
without an opt out, and the schema keeps the mirror image of that pair
unexpressible: the browser may not drop what the server would have stored.

## The outcome partition

There is no operation choice here, so there is nothing for a dispatch table to
dispatch on and an `op` field would be a guard that cannot fail. The domain
appropriate replacement is a partition over the pair of outcomes, which each
runner derives from each case rather than reading from a list:

| class | browser | server |
|---|---|---|
| `kept-by-both` | kept | kept |
| `dropped-by-the-server` | kept | dropped |
| `dropped-by-the-browser` | dropped | dropped |
| `refused-by-the-server` | dropped | refused |

Every case falls in exactly one class and every class holds at least one case,
both asserted, and the classifier is cross checked against the schema's own list
of class names. A file that lost every refusal case reddens, and so does a case
whose pair of outcomes belongs to no class. This is the discipline
`backend/book_columns.py` keeps over the columns of `books`: one partition over
the whole population, refused when a member is classified nowhere or twice.

## The floor

The runners assert at least **14** cases. The file holds 19, and the floor sits
below that on purpose, so retiring a superseded case does not need a constant
moved in two languages. **It is not what protects the cases that carry a
reason**: the table below names 18 of the 19 by id, and deleting one of those
fails there rather than here. **Nor does the table protect their content**, only
their ids: see *The two arms lock each other*.

## What each case pins

Each rule dropped or widened in turn, measured 2026-09-30 against this tree, and
recording which cases notice. Every row is one change.

**A row records the cases that noticed when the row was measured, and adding a
case does not re-measure the rows above it.** That is how this table goes stale,
and neither runner can see it: the existence arm is a subset check over ids
rather than a per row equality, so a row short by an id is a measurement that has
stopped stating its measurement, not a guard that has stopped guarding. **Every
case added therefore owes a pass over the rows already here.**

| guard dropped | cases that catch it |
|---|---|
| browser collapse, widened from whitespace-except-the-mark to JavaScript whitespace | `a-mark-at-the-start-is-kept-on-both-sides`, `a-mark-at-the-end-is-kept-on-both-sides`, `a-mark-at-both-ends-is-kept-on-both-sides`, `a-mark-followed-by-a-space-is-kept-on-both-sides`, `a-mark-mid-word-is-kept-on-both-sides`, `a-run-of-marks-mid-word-is-kept-on-both-sides`, `a-mark-standing-between-two-spaces-is-kept-on-both-sides` |
| browser trim, widened from a literal space to JavaScript whitespace | `a-mark-at-the-start-is-kept-on-both-sides`, `a-mark-at-the-end-is-kept-on-both-sides`, `a-mark-at-both-ends-is-kept-on-both-sides`, `a-mark-followed-by-a-space-is-kept-on-both-sides` |
| browser collapse, removed | `a-wrapped-subject-collapses-to-one-line-on-both-sides`, `padding-is-trimmed-on-both-sides`, `a-tab-run-becomes-one-space-on-both-sides`, `an-entry-of-nothing-but-spaces-is-dropped-by-both` |
| browser drop of a separator bearing entry | `a-separator-between-two-subjects-is-refused`, `a-bare-separator-with-no-spacing-is-refused` |
| browser drop of an emptied entry | `an-entry-of-nothing-but-spaces-is-dropped-by-both` |
| server deletion of the invisible characters | `a-nul-is-deleted-by-the-server-and-kept-by-the-browser`, `an-entry-of-nothing-but-deleted-controls-is-kept-by-the-browser-and-dropped-by-the-server`, `a-deleted-control-between-two-spaces-pins-the-order-of-the-two-steps` |
| server whitespace collapse | `a-wrapped-subject-collapses-to-one-line-on-both-sides`, `padding-is-trimmed-on-both-sides`, `a-tab-run-becomes-one-space-on-both-sides`, `u-001c-is-a-word-break-for-the-server-and-not-for-the-browser`, `u-0085-is-a-word-break-for-the-server-and-not-for-the-browser`, `an-entry-of-nothing-but-spaces-is-dropped-by-both`, `a-deleted-control-between-two-spaces-pins-the-order-of-the-two-steps` |
| server's two steps swapped, so the collapse runs before the deletion | `a-deleted-control-between-two-spaces-pins-the-order-of-the-two-steps` |
| server drop of an emptied entry | `an-entry-of-nothing-but-spaces-is-dropped-by-both`, `an-entry-of-nothing-but-deleted-controls-is-kept-by-the-browser-and-dropped-by-the-server` |
| server refusal of a separator bearing entry | `a-separator-between-two-subjects-is-refused`, `a-bare-separator-with-no-spacing-is-refused` |
| browser fold, count limit and per entry width | **nothing, and that is the scope rule** |

**One row is not a rule dropped but a rule reordered**, because the server's two
steps compose and the order is a third thing the two rows naming each step
cannot see. What that swap moves and what it leaves alone is in the case's own
reason, which is the one home for it.

**The last row is the scope rule showing through, not a hole in the cases.**
Those three rules have no server counterpart that answers the same way, so a
case here could only assert about one implementation, and the schema refuses to
express one. They are tested where they live.

**Of the ten rows that name a case, five are a browser rule and five a server
one**, the eleventh being the scope row above. That is not a bias either way: they
are the rows where a rule can be changed and the answer still change. A collapse
appears on both sides because the two engines disagree about what whitespace is,
which is the whole reason this domain is here.

## What this file does not close

**The separator is pinned by its behaviour, not by its spelling.** The browser
holds the character as a literal and the server reads it off
`google_books.CATEGORY_SEPARATOR`. The two separator cases fail if either side
stops refusing `;`, and they cannot see the server's constant changing value
with the browser's literal not following, except through the behaviour on `;`,
which reddens on the server side first. The mechanism is named; the extent is
not claimed.

**The frontend arm calls the browser's rule and the backend arm calls the
server's**, so what each pins is that implementation's answer. Neither arm
observes the other runtime, by construction: what carries the property across is
the literal in `browser.value`, and it is only as good as the run that last
measured it. That is what the equality arm is for, and it is why editing that
literal reddens the other side rather than passing.

**Only `browser.value` is read by two independent parties, and `server.value` is
not.** Both backend arms compare against that one field, so a change to the
server's rule is absorbed by regenerating it: measured, make the server delete
the mark as well and both arms redden on seven cases, then edit `server.value`
alone and everything is green again. **The backend pair is a golden file in that
direction, exactly as the frontend arm is on its own.** What catches some of it
is the outcome partition, which reddens when such a repair empties a class, and
a repair that crosses no class boundary is invisible to it. Closing this needs a
third party reading that field and there is no third implementation, so the
mechanism is named and nothing here claims to close it.
