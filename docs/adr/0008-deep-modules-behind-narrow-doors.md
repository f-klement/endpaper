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

Measured over the three this ADR names, plus the two the refactor added and the two added
after it:

| Module | Lines | Statements | Public surface | Per public name | Private |
|---|---|---|---|---|---|
| `metadata.py` | 3,202 | 926 | 5 functions, 2 classes | **132.3** | 74 functions |
| `covers.py` | 893 | 278 | 25 functions, 1 class | 10.7 | 2 |
| `dependencies.py` | 211 | 50 | 5 functions, 1 class | 8.3 | 1 |
| `shelf.py` | 533 | 114 | 3 functions, 3 classes | 19.0 | 0 |
| `authorship.py` | 382 | 80 | 2 classes | **40.0** | 0 |
| `reading.py` | 575 | 117 | 2 functions, 2 classes | 29.2 | 3 |
| `custom_fields.py` | 696 | 106 | 8 functions, 2 classes | 10.6 | 2 |
| `mailer.py` | 248 | 88 | 2 functions, 2 classes | 22.0 | 3 |

**The statement column was added because the line column hides the thing this ADR is about.**
Counted 2026-08-27 with `ast`, statements being every `ast.stmt` that is not a bare string, so
a docstring and a comment weigh nothing. At 696 lines against `shelf.py`'s 533,
`custom_fields.py` reads **larger**; at 10.6 statements per public name against 19.0 it is
half as deep per name, and the ADR's own claim is that line count is not the test.

**Statements is the figure to compare, and Lines is the one that rots fastest**, which is the
second reason for adding it: this table's `custom_fields.py` row was wrong by fourteen lines
within a day of being written, because a paragraph was added to a docstring.

**Statements is steadier than Lines and is not stable.** It moves with prose not at all and
with development freely: that same row's Statements went 94 to 105 inside one review round,
while its module was being fixed. So **every column here is a snapshot on the date in the
header**, and a figure that `ast` does not reproduce today means the module moved, not that
the tool disagrees. Re-measure before citing a row in an argument. Public names are top
level: a class counts once, its methods are behind its door.

**But the ratio separates two module shapes, not two depths, and `dependencies.py` is the
proof.** It sits at 8.3, lower than every other row including `custom_fields.py`, and this
document already argues at length that it is deep. The modules at the top of the column put a
**scoped object** behind one name (`Shelf`, `Reading`, `Authorship`), so their operations are
methods and do not count; the modules at the bottom are functions over a value the caller
already holds. `custom_fields.py` is the second kind on purpose: the scope is the `Book`
handed in, so there is no object to construct, and every operation takes it. Read the column
as "how much is behind each name a caller must learn", and then read it beside what the caller
stops having to know.

`custom_fields.py` is in the table because it is the first module written **against** this
rule rather than measured after the fact, and it is the widest door of the four the rule has
produced. It stays one module for the reason `covers.py` does: the depth is a fact held in one
place, which here is "who may read a custom field value", answered by every reader taking a
`Book` rather than a book id, and by `link_target` deciding on every read rather than once at
the write. Splitting the definitions from the values would publish the same ten names across
two files and let no caller stop knowing anything.

What the ratio **did** buy, and it is why the column is worth keeping: it is what retired the
batching class this module shipped with. `Values.of(db, books)` loaded a page of Books in one
statement, and three of the ten names existed to serve a caller the design refuses to have,
since these are served by their own route rather than on `BookOut`. A batch reader whose batch
caller is refused by design is three public names and a test measuring a path nothing runs.

`reading.py` is the fourth concept found the same way, added here rather than left to
the next reviewer to re-derive. Counted 2026-08-27: 575 lines behind two classes and two
functions. Its depth is what a caller stops knowing. Before it, five sites in
`routers/books.py` alone spelled the same get-or-create by hand, and three rules had no
owner: absence of a row means unread, a reading record is private to its member, and the
reading dates are derived from the status transition. It takes the same shape as the other
two the refactor added: two named functions read past a member rather than one general
escape hatch.

`mailer.py` is the narrowest row and the one whose boundary carries the most. Counted
2026-08-27: 248 lines behind `checked_config` and `send`, which puts it between
`dependencies.py` and `authorship.py` on this table's own ratio. The question it exists to
be the only answer to is "may this mail be attempted at all", and the refusals are what a
caller stops knowing: that a password with no encryption would cross the network in the
clear, that STARTTLS and implicit TLS are two protocols rather than two switches, that a
newline in an address is header injection, that the TLS context takes no parameter so
verification cannot be relaxed.

**The boundary is load bearing rather than tidy**, which is the reason this is a module and
not a function that moved. It is where blocking crosses into `asyncio.to_thread`: `smtplib`
has no async form, every FastAPI handler that reaches it is `async def`, and calling it
inline would stop the event loop for the length of an SMTP conversation.
`notifications.py` therefore holds the three senders and the digest, and knows about SMTP
only that it is not awaited directly. Folding the two together would put a blocking
protocol inside the module that also speaks HTTP, and would make `fetch.py`'s httpx shaped
guard look like it covers something it cannot.

`metadata.py` is the clearest case and the one most often mistaken for a problem: **3,202
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
