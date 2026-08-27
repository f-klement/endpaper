# Deep modules behind narrow doors

Decided 2026-08-26, after the refactor that produced `shelf.py` and `authorship.py`.

This records **why three existing modules are the target shape**, so the next review does not
re-litigate them and the next module has something to be measured against. It changes no
code. It exists because the same review that produced two new seams also proposed splitting
`routers/books.py` by resource, and the argument against that is the argument for these.

## The rule

**A module is judged by the ratio of what it does to what a caller must learn**, not by its
line count. A deep module has a small door and a lot of room behind it. A shallow one costs
a reader an import and a name and gives back a line they could have written.

Measured over the three this ADR names, plus the two the refactor added and the one added after it:

| Module | Lines | Public surface | Private |
|---|---|---|---|
| `metadata.py` | 3,217 | 5 functions, 2 classes | 74 functions |
| `covers.py` | 832 | 25 functions, 1 class | 2 |
| `dependencies.py` | 211 | 5 functions, 1 class | 1 |
| `shelf.py` | 533 | 3 functions, 3 classes | 0 |
| `authorship.py` | 382 | 2 classes | 0 |
| `reading.py` | 575 | 2 functions, 2 classes | 3 |

`reading.py` is the fourth concept found the same way, added here rather than left to
the next reviewer to re-derive. Counted 2026-08-27: 575 lines behind two classes and two
functions. Its depth is what a caller stops knowing. Before it, five sites in
`routers/books.py` alone spelled the same get-or-create by hand, and three rules had no
owner: absence of a row means unread, a reading record is private to its member, and the
reading dates are derived from the status transition. It takes the same shape as the other
two the refactor added: two named functions read past a member rather than one general
escape hatch.

`metadata.py` is the clearest case and the one most often mistaken for a problem: **3,217
lines behind five public functions, and one importer.** Nothing outside it knows that a MARC
record has non-sorting delimiters, that Open Library subjects are not classifications, or how
sources are ranked. A reviewer proposing to split it is proposing to publish 74 private
functions.

`covers.py` is the counterexample that is still correct. Its surface is wide because it is a
library of small builders, and its depth is elsewhere: it is **the only module that knows an
image host**, and `middleware.py` derives the CSP's `img-src` from its `COVER_HOSTS` rather
than restating it. That derivation exists because the two were once written separately, a
German ISBN source was added to one and not the other, and **every cover on a German shelf
was blocked by the browser** while the stored record looked perfectly correct. Depth here is
a fact held in one place, not a small door.

## Why this is not an argument for fewer, larger files

`dependencies.py` is 211 lines. It is deep because of what asking it a question saves: before
it existed, fourteen endpoints decided access inline and **most of them decided nothing at
all**, so any signed-in member could delete, retag or re-cover anybody's Private Book. Its
depth is that a new endpoint gets the rule by asking for a book.

That is the same shape as `shelf.py`, which replaced a 681-line AST guard, and
`authorship.py`, which took the database half of a feature whose pure half had been extracted
years earlier and left its calling code in a route handler.

**So the test is not size in either direction.** It is whether the module lets a caller stop
knowing something.

## What this rules out

Splitting `routers/books.py` by resource. Measured at this ADR's own commit (`a1a2a1e`):
3,171 lines, 53 routes, 33 private helpers, and only **7 of those 33 used by more than one
section**. Re-measured 2026-08-27, after `reading.py` took the reading record out of it:
**3,030 lines, 53 routes, 32 private helpers**. The line and helper counts moved and the
argument did not, because it rests on the route count and on helper coupling rather than on
size.

This paragraph first said 3,144 lines and 47 routes. Both were wrong when it was written:
`grep -cE '^@router\.[a-z]+'` gives 53 at that same commit, and `wc -l` gives 3,171.
Corrected rather than carried, on the standing rule that a stated number says what it was
measured against.

The coupling is low enough that a split is mechanically easy, which is exactly why it is
tempting. It is refused because nothing becomes deeper: the same 53 handlers would do the
same work in eight files, no caller would stop knowing anything, and the public surface would
grow by seven helpers that are private today.

A router is the one place in this application where shallowness is correct. A handler's job
is to turn a request into a call and an exception into a status code, and a **route docstring
is API documentation**, served at `/docs`, `/redoc` and `/openapi.json` and shipped as doc
comments in the generated client. Making handlers thin is about code, not about prose: the
same session that added these two modules stripped 882 and 655 characters of served
description from two routes and had to put it back.

**What is worth extracting from that file is a concept, not a resource.** Three were found
this way and all three paid: the many-Book query, author identity, and the reading record.

The candidate this section used to hand to the tracker was the book-duplicate concept,
issue #74. It is **closed as refused**, and its closing comment points back here for the
reasoning, so this document is the record of that refusal rather than a pointer to pending
work. The argument is the one above: `_duplicate_key`, `_one_per_copy_group` and the merge
are two thin handlers over helpers no other section calls, so moving them publishes three
names and lets no caller stop knowing anything. Somebody proposing it again should start
here.

## A worked example of the test, in both directions

The frontend was measured the same way after the backend work, by ranking hooks on interface
width. Two came out at the top and **only one of them is a defect**, which is what makes the
pair worth recording.

`useLibrary` had **32** members, **15** of them writers, and eleven wrote one field each of a
single `BookFilters` object held in one `useState`. Adding a filter cost the interface, the
hook, the panel's props and the page. No caller stopped knowing anything. That is the shallow
case, and narrowing it to `update(patch)` took the interface to 21 and the panel's props from
ten callbacks to one.

`useBookActions` has **21** members, **15** of them actions, and looks like the same thing.
It is not, and the difference is one measurement: each setter calls a **different mutation**.
`setStatus` is `status.mutate`, `setRating` is `rating.mutate`, `updateDetails` is
`details.mutate`, and `setPrivacy`, `setOwnership` and `setCollection` are three more
endpoints again. They are fifteen distinct API operations that happen to be spelled like
field writes, not fifteen writes to one object.

**Collapsing them into `update(patch)` would hide which endpoint a caller is calling**, which
is the opposite of a caller stopping knowing something: it would make a caller stop knowing
something it needs. Refused, and recorded here rather than in a ticket because the next
reviewer ranking hooks by width will find it again and reach for the same fix.

**So width is a symptom, exactly as size is.** The question is what is behind the door: one
value, or fifteen operations.

## The rejected alternative

Writing nothing, on the grounds that these three modules are fine and nobody is proposing to
change them. Refused because "nobody is proposing to change them" was untrue within the same
review, and because the argument for keeping them is the argument that decides the next
module. An unwritten rule gets re-argued at the price of a review round each time.
