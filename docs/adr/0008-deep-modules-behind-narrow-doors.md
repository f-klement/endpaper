# Deep modules behind narrow doors

Decided 2026-08-26, after the refactor that produced `shelf.py` and `authorship.py`.

This records **why four existing modules are the target shape**, so the next review does not
re-litigate them and the next module has something to be measured against. It changes no
code. It exists because the same review that produced two new seams also proposed splitting
`routers/books.py` by resource, and the argument against that is the argument for these.

## The rule

**A module is judged by the ratio of what it does to what a caller must learn**, not by its
line count. A deep module has a small door and a lot of room behind it. A shallow one costs
a reader an import and a name and gives back a line they could have written.

Measured over the four this ADR names, plus the two the refactor added:

| Module | Lines | Public surface | Private |
|---|---|---|---|
| `metadata.py` | 3,217 | 5 functions, 2 classes | 74 functions |
| `covers.py` | 832 | 25 functions, 1 class | 2 |
| `dependencies.py` | 211 | 5 functions, 1 class | 1 |
| `shelf.py` | 533 | 3 functions, 3 classes | 0 |
| `authorship.py` | 382 | 2 classes | 0 |

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

Splitting `routers/books.py` by resource. Measured after both refactors: 3,144 lines, 47
routes, 33 private helpers, and only **7 of those 33 used by more than one section**. The
coupling is low enough that a split is mechanically easy, which is exactly why it is
tempting. It is refused because nothing becomes deeper: the same 47 handlers would do the
same work in eight files, no caller would stop knowing anything, and the public surface would
grow by seven helpers that are private today.

A router is the one place in this application where shallowness is correct. A handler's job
is to turn a request into a call and an exception into a status code, and a **route docstring
is API documentation**, served at `/docs`, `/redoc` and `/openapi.json` and shipped as doc
comments in the generated client. Making handlers thin is about code, not about prose: the
same session that added these two modules stripped 882 and 655 characters of served
description from two routes and had to put it back.

**What is worth extracting from that file is a concept, not a resource.** The two that were
found this way both paid: the many-Book query and author identity. One candidate remains and
is on the tracker rather than in this ADR, because it is work rather than a decision.

## The rejected alternative

Writing nothing, on the grounds that these four modules are fine and nobody is proposing to
change them. Refused because "nobody is proposing to change them" was untrue within the same
review, and because the argument for keeping them is the argument that decides the next
module. An unwritten rule gets re-argued at the price of a review round each time.
