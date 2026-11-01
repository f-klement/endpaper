"""Tests for backend/shelf.py: the seam every many-Book query goes through.

Three kinds of test live here and they answer different questions.

`TestTheShelfIsTheOnlyWayIn` is the **house rule**, and it is what replaced
`TestEveryBookQueryIsFiltered` in `test_models.py`. That guard walked the AST of
every backend module and tracked scopes and bindings through `symtable`, because
the privacy predicate had no owner: a predicate could be applied anywhere, so the
only way to know it had been applied was to inspect every statement that might
have needed it, and five opt-out comments plus a test counting them held the
exceptions.

**This rule is smaller for one structural reason, not because it is cleverer.**
Outside `shelf.py` the correct number of Book queries is zero, so there is
nothing to decide: no predicate to find, no binding to follow, no scope to
resolve. Each `ast` pass asks one flat question. `_predicate_calls` is the
companion of `_imported_predicates`, so this file counts the two as one and calls
`_book_owned_offences` the fourth pass.

| Pass | Question | Allowed in |
|---|---|---|
| `_imported_predicates` | who imports `visible_to` / `in_trash_for` | `PREDICATE_IMPORTERS` |
| `_predicate_calls` | who **calls** one, under any name | `PREDICATE_IMPORTERS` |
| `_query_offences` | who builds a query naming `Book` | `QUERY_BUILDERS` |
| `_join_offences` | who reaches `books` through a join | `QUERY_BUILDERS`, `JOIN_CALLERS` |
| `_book_owned_offences` | who reads a Book-owned table at all | `QUERY_BUILDERS`, `BOOK_OWNED_READERS` |
| `_whole_book_calls` | who hands `Book` itself to a call | `QUERY_BUILDERS`, `WHOLE_BOOK_READERS` |
| `_raw_sql_offences` | who holds SQL naming `books` | `QUERY_BUILDERS`, `BOOKS_SQL_READERS` |
| `_relationship_offences` | who names a relationship into `Book` | `QUERY_BUILDERS`, `RELATIONSHIP_READERS` |

`_entity_aliases` resolves which local names mean the guarded entity first, so
an import alias, a rebinding or an `aliased()` entity is caught rather than
looked past. `_query_offences` and `_join_offences` hand it `Book`; the fourth
hands it `BOOK_OWNED`.

**The fourth pass is the newest and asks a blunter question than the other
three.** They ask whether a statement names `Book`, so a query over
`classifications` or `book_tags` is invisible to every one of them, whatever it
selects, and an *index* over such a table ("every DDC number in the library,
with a count") publishes a name and a count over every Member's Private Books.
That is the disclosure `list_tags` made and the reason this module exists.

**It reports every read and decides nothing.** No join, no scope, no viewer, no
Shelf: a statement naming one of those entities is the whole rule, and
`BOOK_OWNED_READERS` is where a person records why a given statement is safe.
**It is keyed on this codebase's own names, never on a library's**: which
entities, which tables, and the SQL keywords before a table name. What a
method is called plays no part, so no release of a library can move what this
reports; `docs/decisions.md` has the reason.
That is a deliberate retreat from five earlier versions which each tried to
recognise a correct query and were each demonstrated to leak by the following
review round, against an allowlist that did not move while they came and went.
The table in `BOOK_OWNED_READERS` is the record, and the block above it is what
to do when this rule turns your build red. **Do not reintroduce the cleverness**;
that comment exists because the instinct to is strong and was wrong five times.

The guarded set is half derived and half pinned, and the split is where an
earlier version was wrong. Which tables are **children** of `books` is a foreign
key, so `models.children_of_books` derives it. Whether a child has a viewer of its own
is **not** a foreign key to `users`: `collections`, `author_aliases` and
`author_identifiers` each carry a `created_by_user_id` that no query consults,
so that predicate would have dropped `classifications` out of the guard the day
somebody added `catalogued_by_user_id`. `BOOK_CHILDREN` is therefore pinned, and
a child added later fails a test until a person classifies it.

**It is wider than the old guard**, which was blind to a query reaching `books`
through `.join(Book, ...)` while naming no `Book` inside `query()`: its own
docstring recorded **10** such statements in the tree, and teaching it that shape
was costed at four fresh exemptions and refused. `_join_offences` sees them, and
here the same widening costs **one** allowlist entry, `notifications.py`, because
that is the only module in the tree taking the shape. The reason is the seam, not
the rule: once every legitimate query goes through one module, the exceptions are
few enough to name.

**The blind spots, because a guard whose limits are undocumented is read as a
guarantee it never made.** `EVASIONS` holds every shape that evaded an earlier
version of this rule, and each is asserted against the specific pass that must
catch it. **The counts are stated once, in that dict's own docstring, and a
test derives them from the dict**: this sentence used to carry its own copy and
was wrong in three consecutive review rounds. `BOOK_OWNED_EVASIONS` holds the
fourth pass's, and each of those is asserted to be
invisible to the other three as well, because a shape an older pass already
caught would prove nothing about the new one. What is *still* not caught:

* **A variable this resolver cannot trace back to `Book`.** It follows
  `X = Book`, `X = models.Book` and `X = aliased(Book)`, in both the plain and
  the annotated form, and unpacks a tuple target. It does not follow a value
  computed any other way: `backup.py` does `select(*columns)` over each table's
  columns in a loop, so no rule reading the arguments to a query can see which
  table it reads. Asserted separately by name instead, and listed in
  `INDIRECT_READERS` and `PARAMETERISED_READERS`.
* **Raw SQL the grammar in `_raw_sql_naming` does not recognise.** Every
  string literal but a docstring is read, wherever it sits, for `books` by
  `_raw_sql_offences` and for the guarded tables by the fourth pass, and a
  bare table name is read where a table is looked up by name. A string built
  from pieces at run time, with the keyword in one piece and the table in
  another, and a statement opening with a comment, are not.
* **A relationship into a book-owned table**, `Book.classifications` handed
  to a join off a non Book root, is the fourth pass's only when the statement
  names the entity too. A relationship into `Book` itself is
  `_relationship_offences`'s, off its owning class: `join(User.books_added)`
  and `Loan.book.has(...)` are reported, and `loan.book` on an instance is
  not. A to many one is reported off any receiver, `len(collection.books)`
  among them, because it loads every Book it collects.
* **A child table that carries a user.** `notes`, `quotes`, `user_books`,
  `reading_progress`, `loans` and `highlights` are outside the fourth pass on
  purpose: each has a viewer of its own. The figures that follow predate
  `highlights` and were not re-derived when it joined. Re-measured 2026-10-01 by running this pass over the
  tree with that entity set: **41 statements across 10 modules**, or 36 across 9
  outside `shelf.py`, against **27 across 7** for the book-owned tables, or 22
  across 6 outside it, out of the **98** modules `application_sources()` returns.
  **All four pairs are re-derived together, every time.** On this reading the
  user-carrying pair moved and the book-owned one did not: `routers/loans.py`
  fell from 2 to 1 when `_loan_with_relations` stopped building its own
  `db.query(Loan)` and asked `Loans.seen_by` instead. The reading before it
  moved the other way, when `fields.py` arrived with three reads of
  `custom_field_values` and none of a table carrying a member. **The halves
  move independently, and only a joint re-derivation can say so.**
  The module count has not moved and reads 98: it was 95 the day that figure
  was written, the tree reached 96 before that work began, `shelving.py` made
  it 97 and `fields.py` 98. Every number here is this pass's own output on one
  day; an earlier statement of it compared two different methods and neither
  number reproduced. All four are re-derived together rather than the ones a
  branch happens to move, because a comparison whose halves carry different
  dates is the drift this paragraph is already about: on 2026-09-17 they read
  45 across 9, 40 across 8, 25 across 5 and 20 across 4, over 89 modules.

  **The figure this replaces did not reproduce either**: the same method
  answers 49 across 8 at `0a8bb0b`, where the line above said 45 across 8. The
  module count is the half worth reading, and it went to 9 because `lending.py`
  arrived with 6 while `routers/loans.py` fell from 9 to 2,
  `routers/books.py` from 17 to 16, `notifications.py` from 6 to 5 and
  `serialisation.py` from 3 to 2.

  What holds those five tables is the per-row ownership `reading.py`, the
  routers and now `lending.py` apply. **That is a description of the tree, not a
  guarantee.** `routers/books.py:2495` is already a library-wide index over
  `quotes`, written correctly through the Shelf with a join, so the class is
  live on a user-carrying table and nothing here would catch it written wrong.

  **`lending.py` reads past a viewer**, which makes it the fourth module in the
  tree to: `shelf.py`'s named functions, `backup.py`, `notifications.py`'s
  digest, and now this. **The count of those functions is not repeated here**,
  and this line said two against a `shelf.py` that names three: the list is
  what this sentence is for, the number has one home, and a copy of it reds on
  nothing. One method does it, `Loans.open_on`, which takes Book
  ids and no viewer because every caller resolved its Books through the Shelf
  or through `dependencies.py` first. `Loans.for_a_channel` is **not** the
  second: it goes through `Shelf.seen_by_the_public`, which is a stricter
  predicate than `visible_to` with no ownership arm at all, so a request routed
  through it by mistake sees less rather than more.

  The cost is stated rather than left to be found. Before the door, a viewerless
  Loan query was a statement somebody had to justify at its call site; behind
  one it is a method call that looks like every other. What replaces that
  justification is that it cannot be reached without naming it, and that it
  takes ids rather than criteria, so it cannot quietly become a way to read the
  table. That is the same pair `shelf.rereading_filtered_rows` rests on.

  **A fifth module held a viewerless Loan read and no list in this file carried
  it.** `routers/loans._loan_with_relations` was `db.query(Loan)` keyed on an
  id. It was safe, measured: both callers resolved through a viewer first, one
  through the Shelf and one through `Loans.seen_by`. It was also invisible to
  every pass here by construction, because `loans` carries a user so the fourth
  pass does not walk it and the three above ask only about `Book`, which is
  what let it sit outside the inventory this bullet is. It asks
  `Loans.seen_by(...).rendered().with_id(...)` now. **The entry it would have
  taken was this paragraph, and a paragraph reds on nothing**, which is why the
  helper was changed rather than written down:
  `tests/routers/test_loans.py::TestTheSingleLoanHelperIsScoped` fails when the
  scope comes off.
* **A Python-side aggregate off a Shelf.** `Shelf.select()` is anchored at the
  filtered `books`, so counting its rows in Python is safe; counting the rows
  of an *allowlisted* book-owned read is not, which is why every entry in
  `BOOK_OWNED_READERS` carries a reason rather than a count.
* **`.select()` on any receiver is taken to be the Shelf's own method** by
  `_builds_a_query`, so pass 2 does not report `shelf.select(Book.author)`.
  The fourth pass makes no such exception, because it reads no method name:
  `shelf.select(Classification.number)` names the entity, and that is the
  whole of what it asks.
* Importing `Book` for a type annotation is not distinguished from importing
  it to build a listing, which is why the rules test what a statement does
  rather than that import. A call handed `Book` itself, the by key read
  `db.get_one(Book, book_id)`, is `_whole_book_calls`'s, and
  `WHOLE_BOOK_READERS` says why each one is safe.
* **A read through a relationship attribute.** `book.classifications` in
  Python issues a SELECT the ORM writes, and no rule reading source for a
  query call can see it. It is scoped by construction when the `Book` came
  from `dependencies.py` or a Shelf, which is why it is listed rather than
  chased, but a loop over an unfiltered list of Books would not be. A list
  of Books off a row that is not a Book, `collection.books`, is not scoped
  that way, and `_relationship_offences` reports it. The
  comparator form is the same hole: `Book.classifications.any(number="616")`
  names the relationship and a keyword, never the entity, so the fourth pass
  does not see it, and the tag and field rules are blind to it alike:
  `Book.tags.any(name=x)` names no `Tag`. Inside a statement that hands `Book`
  to a builder, passes 2 and 3 report it; under a root that does not,
  `db.query(func.count(Loan.id)).filter(Loan.book.has(Book.tags.any(name=x)))`,
  the relationship pass does, through `Loan.book`. Keying on every
  relationship name that targets a guarded entity was measured and refused:
  every `book.tags` in Python would then report.
* **An entity reached by a computed name.** `getattr(models,
  "Classification")` builds the name from a string, so no walk over names
  resolves it. That takes a line written to reach the entity indirectly,
  which is a deliberate act rather than a slip.
* **An allowlist entry added without thinking.** This rule now decides nothing
  about whether a query is safe, so a wrong entry is a hole it cannot see. That
  is the cost of the collapse and it is paid in review, which is why every
  entry carries an argument rather than a description.
* **`Query([Book], session=db)`**, constructing `orm.Query` directly. Not how a
  query is written anywhere in this codebase.
* **An implicit FROM through a clause, on `books` itself.**
  `db.query(Loan.id).filter(Book.is_private.is_(True))` compiles to
  `SELECT loans.id FROM loans, books WHERE ...`, and `.order_by(Book.title)`
  and `.group_by(Book.location)` do the same: a real cartesian read of `books`
  with no predicate. Not caught by passes 1 to 3, and **the reason is a cost,
  measured**: `Book` in a narrowing clause is **14 statements across 5 modules**
  outside `shelf.py` and off a shelf-rooted chain, and **22 across 9** counting
  those, measured 2026-09-17, against what the fourth pass carries, which is
  `BOOK_OWNED_READERS` and moves with the code: it lost three reads when the
  merge moved to `folding.py` and six when the three vocabularies' arms moved
  to `disclosure.py`, a shape rule taking each. That is what a count of hand
  classified statements does when the code moves. Extending the clause rule to
  `Book` means classifying every one of them by hand.

  That last pair said **7 across 3** until 2026-09-10 and both halves were
  wrong: an `ast` walk over `BOOK_OWNED_READERS` answered 10 across 4 before a
  table was added to the guard and 15 across 4 after, and the module count had
  never been 3. It is the entries that are compared, because every one of them
  is a statement somebody classified by hand, which is the cost the two figures
  in front of it are measuring.

  That number replaces an example, and the example was wrong. This bullet used
  to name `routers/stats.py`'s `join(User, Book.added_by_user_id == User.id)`
  as a correct caller no clause rule could separate. It is a **join** onclause,
  which such a rule would never have looked at. Corrected under this list's own
  closing sentence: a shape named here is a claim about the tree, and a claim
  about the tree is a measurement rather than an instance somebody remembered.

  **For the book-owned tables it is caught, and for free.**
  `shelf.select(Book.title).filter(Classification.number == "616.89")` is a
  statement naming a guarded entity, and that is all the rule asks, whatever
  the narrowing method is called. A clause built as a local first,
  `flagged = DigitalReference.missing_since.isnot(None)`, is reported where it
  is built, so the clause is classified and not only the query it ends up in.

Both critic seats reviewed the first eight of these and called that list
complete. Later rounds replaced, removed and added bullets as passes changed,
so the list carries no count. The list is the deliverable for everything the rules
do not catch: a shape that is named here has been decided about, and a shape
that is neither caught nor named is an oversight. **A shape listed here is a
claim about the tree and has to be re-measured, not re-read**: the entry above
about user-carrying tables carried a number that did not reproduce by any
method, and the entry this one replaced described a hole that a later round
closed in eight lines.

`TestOnlyTheShelfSaysWhatMayLeave` is the third, and it is a rule about the
other side of a query: it reports any construction of `shelf.Outbound` **that
names the type** outside `shelf.py`, so the fact that a row came off a shelf
with no viewer cannot be asserted by a caller that merely believes it. Every
other spelling is refused at run time by `Outbound.__post_init__`, which
`TestOnlyTheShelfCanMintOne` drives. Its own blind spots are listed on the
class, and the sweep it works with is `tests/test_nothing_private_leaves.py`.

The rest of the file tests the Shelf's behaviour.
"""

import ast
import builtins
import functools
import importlib
import inspect
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    Select,
    Table,
    event,
    func,
    literal,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import contains_eager

import ddc
import filing
import models
import shelf as shelf_module

# `Base` from `database`, which defines it, rather than from `models`,
# which re-exports it. mypy refuses an implicit re-export and is right to:
# the two would drift the day `models` stopped importing it.
from database import Base
from enums import BookSort, ClassificationScheme, ReadStatus, TagCategory
from models import (
    Book,
    Classification,
    Collection,
    Tag,
    User,
    UserBook,
    book_tags,
    children_of_books,
)
from shelf import (
    _MULTI_COLUMN_ORDERS,
    _SHELF_SORTS,
    _SORT_CLAUSES,
    BookFilters,
    Loading,
    Shelf,
    _division_key,
    _looks_like_a_notation,
    order_for,
    rereading_filtered_rows,
    whole_table_for_uniqueness,
)
from tests.bindings import SourceNames, assignments
from tests.corpus import application_sources
from tests.helpers import peak_rows, rows_at_the_engine

# The corpus lives beside the rules it measures, in `tests/test_filing.py`, and
# is read from here, from `tests/test_schema.py` and from `tests/test_backup.py`.
# One list, so a shape added for one reader is a shape every reader gets.
from tests.test_filing import CORPUS

TREE_GUARDS = {
    "TestOnlyTheShelfSaysWhatMayLeave": ("application_sources",),
    "TestTheModulesTheseRulesWalk": ("application_sources",),
    "TestThePublicShelfHasNoOwnershipArm": ("application_sources",),
    "TestTheSerialisersThatMayBuildAnOutboundPayload": ("application_sources",),
    "TestTheShelfIsTheOnlyWayIn": ("application_sources",),
}

BACKEND = Path(__file__).resolve().parent.parent

#: The predicates that decide which Books a Member may see. Every application of
#: one of these belongs behind the Shelf.
PREDICATES = ("visible_to", "in_trash_for")

#: Where each of those names is allowed to be imported.
#:
#: `models.py` defines them; `shelf.py` is the one consumer, which is the whole
#: point of this rule. Importing one anywhere else is how a caller opts out of
#: the seam without saying so.
PREDICATE_IMPORTERS = {"models.py", "shelf.py"}

#: Modules allowed to build a query over the books table.
#:
#: `shelf.py` and nothing else, which is what makes visibility a property of
#: construction rather than of remembering.
QUERY_BUILDERS = {"shelf.py"}

#: Modules allowed to reach `books` through `.join(Book, ...)` from a query
#: rooted somewhere else.
#:
#: One, and it is the deliberate exception this file already names:
#: `notifications.py` has no viewer and partitions on privacy rather than
#: filtering by it. Measured over the tree, it is the only module taking that
#: shape at all, which is why closing this blind spot costs one allowlist entry
#: rather than the four fresh exemptions the old guard costed the same widening
#: at and refused.
#:
#: **`lending.py` was added here on 2026-09-17 and taken out the same day.**
#: `Loans.for_a_channel` wrote `Book.is_private.is_(False)` onto a bare
#: `db.query(Loan)`, which is the join shape; it goes through
#: `Shelf.seen_by_the_public` instead, which is that audience already. The
#: entry would have exempted every future join in that module rather than the
#: one statement it was added for, which is the cost of a second name here.
JOIN_CALLERS = {"notifications.py"}

#: Modules that read every row of `books` without naming `Book` in the query,
#: so no rule of this shape can see them.
#:
#: One: `backup.py` iterates `_TABLES` and reads each through
#: `select(*columns)`, the columns of a table bound at run time. An archive
#: that omitted everyone else's Private Books would restore to a library
#: missing rows, which is the one thing a backup must never do, so it is
#: unfiltered on purpose and admin only for that reason.
#: `test_the_backup_is_the_third_way_past_a_viewer_and_says_so` is what holds
#: that, since this rule structurally cannot.
INDIRECT_READERS = {"backup.py"}

#: Modules that hand a reading call a name this pass cannot resolve to an
#: entity, so it cannot see what table they read.
#:
#: **Derived and then pinned, exactly as `BOOK_CHILDREN` is**, and for the
#: reason that constant gives: the first version of this was a set with one name
#: in it and one consumer, the diagonal below, which iterates the names already
#: present. It covered an entry rotting and not the set going short, so a second
#: module written in this style was invisible to the fourth pass with nothing
#: red and no record. An inclusion list is one of the four tells this repository
#: names; `_parameterised_reads` states the rule and this states the classification.
#:
#: Five, and they are five different things, which is why a person says which:
#:
#: * `backup.py` reads every row of every table through `select(*columns)`,
#:   on purpose: it is the archive, `INDIRECT_READERS` says why it is
#:   unfiltered, and `test_the_backup_is_the_third_way_past_a_viewer_and_says_so`
#:   holds it admin only.
#: * `folding.py` runs one transfer per child table of `books` and builds every
#:   query on the model its policy was constructed with, so the entity name is
#:   in an argument and never in a reading call. Its three merge statements used
#:   to be spelled out in `routers/books.py` and to carry entries above saying
#:   they were keyed on ids the route had resolved. That reason still holds and
#:   this rule can no longer check it, so it is checked by shape instead:
#:   `tests/test_folding.py::TestEveryReadIsBoundedToTheBooksBeingFolded` asks
#:   what each narrowing call is handed, and `READ_ROOTS` there carries the
#:   count that makes a new read somebody's decision, which is the half a shape
#:   rule cannot do.
#: * `serialisation.py` calls `db.query(entity)` where `entity` is an
#:   `aliased(ReadingProgress, ...)` bound two lines above. The table is fixed
#:   at import; only the spelling is indirect, and `reading_progress` carries a
#:   member of its own so it is outside `BOOK_OWNED_TABLES` anyway.
#: * `targets.py` calls `z3950.query(...)`, which is a Z39.50 client and not a
#:   `Session`. `_builds_a_query` matches `query` on any receiver on purpose,
#:   and its docstring says why, so a naming coincidence lands here rather than
#:   being excluded by a rule that would also excuse a real one.
#: * `shelf.py` calls `db.query(carrier.entry)` in `entries_any_book_carries`,
#:   the named way that reads past a viewer, with the column chosen by a
#:   `disclosure.Carrier`. What bounds it is the type, which names one id column
#:   per member, and the caller count in
#:   `test_the_named_ways_past_a_viewer_have_the_callers_they_claim`.
#:
#: `test_a_parameterised_reader_is_genuinely_invisible_to_this_pass` is what
#: stops an entry outliving the gap it describes.
PARAMETERISED_READERS = frozenset({"backup.py", "folding.py", "serialisation.py", "shelf.py", "targets.py"})

#: The entity the first three passes guard.
_BOOK = frozenset({"Book"})


def _child_names(metadata: MetaData) -> set[str]:
    """`models.children_of_books` by name, which is the unit both pins below use.

    The derivation is in `models.py` rather than here because a second reader
    needs it: `folding.TRANSFERS` refuses to import unless it declares a policy
    for every one of these tables. A copy of it in the test tree would be the
    same foreign key rule decided twice, and the copy is the one that would
    stop being maintained.
    """
    return {table.name for table in children_of_books(metadata)}


#: Every child of `books`, pinned rather than only derived.
#:
#: **The pin is the guard.** The next child added fails
#: `test_every_child_of_books_is_classified` until somebody says which half of
#: `BOOK_OWNED_TABLES` it belongs to, so a new table cannot default to
#: unguarded. That is the whole reason this constant exists beside a
#: derivation that could have produced it.
BOOK_CHILDREN = frozenset(
    {
        "access_requests",
        "book_identifiers",
        "book_tags",
        "classifications",
        "custom_field_values",
        "digital_references",
        "highlights",
        "kosync_documents",
        "loans",
        "notes",
        "online_links",
        "quotes",
        "reading_progress",
        "readwise_books",
        "user_books",
    }
)

#: The children whose rows have no viewer of their own.
#:
#: **Classified by hand, and an earlier version of this rule computed it: a
#: child with no foreign key to `users` was taken to have no viewer.** That
#: predicate is wrong in this schema and the counter-examples are already
#: documented in `models.py`. `collections.created_by_user_id` is "provenance
#: and nothing else. No query consults it" (`models.Collection`),
#: `author_aliases.created_by_user_id` says the same (`models.AuthorAlias`),
#: and so does `models.AuthorIdentifier`. Three tables, and they carry the
#: argument on their own.
#:
#: **Cited by class, because the line numbers that stood here were stale.**
#: Both sent a reader to an unrelated paragraph. **No numbers here either,
#: not even the right ones**: the first version of this sentence gave the
#: real sites and one of them moved in the same commit, because that commit
#: added lines above it. A line number in prose goes stale on the next edit
#: to the file it names and nothing reds. So a
#: `catalogued_by_user_id` on `classifications` would have
#: dropped it out of the guard silently, which is the failure this file exists
#: to prevent.
#:
#: **`books.added_by_user_id` is not a fourth example and was cited as one.**
#: It is the column `visible_to` and `in_trash_for` are built on, read at six
#: sites; `books` was excluded from the derivation because it is the parent
#: table, not because its user column is inert.
#:
#: A table here has no user to be scoped by, so its privacy is entirely the
#: Book's and the only correct scoping is the Shelf's. The rest have a
#: member on every row and their own ownership rule: `reading.py` owns
#: `user_books` and `reading_progress` the same way this module owns `books`,
#: and the routers own the rest per row.
#: `digital_references` is the fourth and it was classified by hand like the
#: rest. It carries no `added_by_user_id` **on purpose**: a column of that shape
#: is exactly the counter-example above, so a reference that is a claim about a
#: household's shelf would have looked, to a computed rule, like a row scoped to
#: the Member who filed it. Its privacy is the Book's entirely.
#: `book_identifiers` is the fifth and was classified by hand like the rest. A
#: row says what a store calls a Book and carries no member: which store the
#: file came from is not stored, and `models.BookIdentifier` says why. So there
#: is nothing on a row to scope it by and its privacy is the Book's entirely.
#: `online_links` is the sixth, for the same reason: what a catalogue said is
#: online, carrying no member (`models.OnlineLink`).
BOOK_OWNED_TABLES = frozenset(
    {
        "book_identifiers",
        "book_tags",
        "classifications",
        "custom_field_values",
        "digital_references",
        "online_links",
    }
)


def _book_owned_entities() -> tuple[frozenset[str], frozenset[str]]:
    """The Python names `BOOK_OWNED_TABLES` corresponds to, and what is left.

    A rule that reads source has to know the name the source writes, which is
    the mapped class for most tables and the module-level variable for an
    association table (`book_tags` is a `Table`, not a class, and no mapper
    owns it).

    The leftovers are returned rather than swallowed. A book-owned table with
    no name any module could refer to would drop out of the guard silently,
    which is the failure this whole file exists to make impossible, so
    `test_every_book_owned_table_has_a_name_this_rule_can_look_for` asserts the
    mapping is total instead.
    """
    remaining = set(BOOK_OWNED_TABLES)
    names = set()

    def take(name: str, table: Table) -> None:
        names.add(name)
        remaining.discard(table.name)

    for mapper in Base.registry.mappers:
        # `local_table` is typed `FromClause` because a class can be mapped to
        # a join or a select. Every model here maps to a `Table`, and the
        # isinstance is what says so rather than assuming it. A mapping that
        # was not a Table would leave its table in `remaining`, which
        # `test_every_book_owned_table_has_a_name_this_rule_can_look_for`
        # fails on: unguarded and silent is the one outcome not available.
        table = mapper.local_table
        if isinstance(table, Table) and table.name in remaining:
            take(mapper.class_.__name__, table)
    for attribute, value in vars(models).items():
        if isinstance(value, Table) and value.name in remaining:
            take(attribute, value)
    return frozenset(names), frozenset(remaining)


#: The entities the fourth pass guards, and the tables it could not name.
BOOK_OWNED, UNNAMEABLE_BOOK_OWNED = _book_owned_entities()

#: The archive's table list in `backup.py`, as every registry over the fourth pass keys it.
#:
#: One declaration naming every vocabulary and every child table, so it is
#: reported to each of the four registries the pass feeds. Written once here
#: rather than four times, so a comment edited inside the tuple is one key to
#: re-read and not four.
ARCHIVE_TABLES_DECLARATION: Final = (
    "_TABLES: tuple[tuple[str, Any, Table], ...] = tuple( (name, model, Base.metadata.tables[name]) for "
    'name, model in ( ("users", User), ("tags", Tag), # The library\'s own field definitions. No foreign '
    "key of its own, so it # could sit anywhere before the values that reference it; here beside # `tags`, "
    "which is the other library wide vocabulary. Deliberately # absent from `_REQUIRED_TABLES`: an archive "
    "taken before custom fields # existed restores with none, which is the state it was written in. "
    '("custom_fields", CustomField), # Before books, which carry a foreign key into it. Absent from # '
    "`_REQUIRED_TABLES` on purpose: an archive taken before collections # existed restores with none, which "
    'is exactly the state it was # written in. ("collections", Collection), ("books", Book), # Straight '
    "after the books they hang off, and deliberately absent from # `_REQUIRED_TABLES`: an archive taken "
    "before classifications existed # restores with none, which is the state it was written in. "
    '("classifications", Classification), # After both parents, `books` above and `custom_fields` further '
    "up. The # values are the half of the feature a member typed by hand, so an # archive that carried the "
    "definitions and not these would restore a # library with every field defined and every one of them "
    "empty, which # is the shape of failure `author_aliases` had. Absent from # `_REQUIRED_TABLES` for the "
    'same reason as the definitions. ("custom_field_values", CustomFieldValue), ("user_books", UserBook), # '
    "After user_books, which is the other per-member table, and before # loans purely to keep the reading "
    "rows together. Both parents # (users, books) are already inserted by this point, which is the # only "
    'ordering this tuple actually constrains. ("reading_progress", ReadingProgress), # Where each member\'s '
    "devices last were, after both parents. Absent from # `_REQUIRED_TABLES`, like every table added after "
    '`FORMAT_VERSION` 1. ("kosync_documents", KosyncDocument), # Which Book each of a member\'s Readwise '
    "books is, after both parents. # Absent from `_REQUIRED_TABLES`, like every table added after # "
    '`FORMAT_VERSION` 1. ("readwise_books", ReadwiseBook), ("loans", Loan), # After the loans it replaces '
    "for a digital copy. Both parents are # inserted by here. Absent from `_REQUIRED_TABLES` for the reason "
    '# `quotes` is: an older archive restores with no requests. ("access_requests", AccessRequest), '
    '("notes", Note), # After notes, which it is shaped after and has no relationship with. # Deliberately '
    "absent from `_REQUIRED_TABLES`: an archive taken before # quotes existed restores with none, which is "
    'the state it was written # in. ("quotes", Quote), # After the quotes it sits beside; both parents are '
    "inserted by here. # Absent from `_REQUIRED_TABLES` for the reason `quotes` is: an archive # taken "
    'before highlights existed restores with none. ("highlights", Highlight), # After the highlights whose '
    "deletions it remembers; its only foreign # key is `users`. An archive that left it out would restore a "
    "library # whose next import brings back every highlight a member deleted. # Absent from "
    '`_REQUIRED_TABLES` for the reason `quotes` is. ("deleted_highlights", DeletedHighlight), # After the '
    "quotes, which it sits beside for the same reason: its only # foreign key is `books`, which is long "
    "since inserted by here. # # **Uncapped on restore, like every other table here.** # "
    "`MAX_DIGITAL_REFERENCES_PER_BOOK` binds the two writers that add to a # library; this one reinstates a "
    "whole database rather than adding to # one, and refusing rows would produce a restore that silently "
    "differs # from the archive. The same bargain `classifications` records. # # Absent from "
    "`_REQUIRED_TABLES` for the reason `quotes` is: an archive # taken before this table existed restores "
    'with no references, which is # the state it was written in. ("digital_references", DigitalReference), '
    "# Beside the file references, which it hangs off the same parent as and # sits in the same position "
    "relative to: `books` is long since inserted # by here. A different claim about the same Book: a "
    "reference says where # a file is and this says what a store calls the edition. # # **Here on the day "
    "the table was created**, because the identical # omission for `author_aliases` was silent for months "
    "and cost a restore # that produced perfectly intact books with every merge undone. # "
    "`test_holds_every_table` reads the manifest against the metadata, so a # table left out of this tuple "
    "now fails rather than waiting to be # noticed after a restore. # # **Uncapped on restore, like every "
    "other table here.** # `MAX_IDENTIFIERS_PER_BOOK` binds the two writers that add to a # library; this "
    "one reinstates a whole database rather than adding to # one, and refusing rows would produce a restore "
    "that silently differs # from the archive. # # Absent from `_REQUIRED_TABLES` for the reason "
    "`digital_references` is: # an archive taken before this table existed restores with none, which # is "
    'the state it was written in. ("book_identifiers", BookIdentifier), # Beside the identifiers, the other '
    "catalogue fact hanging off a Book. # Absent from `_REQUIRED_TABLES` for their reason: an archive taken "
    '# before this table existed restores with none. ("online_links", OnlineLink), # The author merge '
    "decisions. Its only foreign key is `users`, which is # first in this tuple, so it could sit anywhere "
    "after that; it is here # beside the other tables that hold what members decided rather than # what the "
    "catalogue says. # # **It was missing until 2026-08-26**, and the symptom was silent: a # restore "
    "produced a library where every merged author had split back # into its spellings, with the books "
    "themselves perfectly intact, # because the merges were never written to `books` in the first place. # "
    'Nothing errored, and `docs/data-model.md` called this "the one stored # table in the feature" the '
    "whole time. `test_holds_every_table` now # asserts that the archive's **manifest** carries every table "
    "in the # metadata, so the next one cannot be forgotten the same way. The # manifest rather than this "
    "tuple, because `book_tags` is in the # manifest and deliberately not here: it has no model of its own "
    "and is # read straight from the table. # # Absent from `_REQUIRED_TABLES` for the reason `quotes` and "
    "# `classifications` are: an archive written before this restores with # no aliases, which is the state "
    'it was written in. ("author_aliases", AuthorAlias), # Beside the aliases, which it is keyed the same '
    "way as and shares its # only foreign key with. A different claim about the same spelling: an # alias "
    "says who two names mean and this says which record in an # external file one of them is. # # **Here on "
    "the day the table was created**, because the identical # omission for `author_aliases` was silent for "
    "months: a restore # produced a library whose books were perfectly intact and whose author # decisions "
    "had all vanished. `test_holds_every_table` reads the # manifest against the metadata, so a table left "
    "out of this tuple now # fails rather than waiting to be noticed after a restore. # # Absent from "
    "`_REQUIRED_TABLES` for the reason `author_aliases` is: an # archive written before this restores with "
    'none, which is the state it # was written in. ("author_identifiers", AuthorIdentifier), # The '
    "catalogue roster as rows. No foreign key of its own, so its # position here is free; beside `settings` "
    "because it is the same kind # of thing, a library wide configuration rather than anybody's data. # # "
    "**Here on the day the table was created**, for the reason the comment # above gives, and with one "
    "difference worth stating: nothing reads # these rows at runtime, so losing them costs no lookup. What "
    "it costs # is #130, which is the ticket that puts them on a screen, and # "
    "`main.seed_catalogue_targets` refills them on the next start anyway. # The reason to be in this tuple "
    "regardless is that an archive is # supposed to hold the library, and a row a household has edited is # "
    "theirs the moment #130 ships. # # Absent from `_REQUIRED_TABLES` for the reason `author_identifiers` "
    "is: # an archive written before this restores with none, which is the state # it was written in. "
    '("catalogue_targets", CatalogueTarget), # The sealed catalogue logins, straight after the rows they '
    "hang off. # No foreign key between them, so the position is free; here because # reading one without "
    "the other is meaningless. # # **This is the table that makes the archive safe to hand around, and # "
    "the one that makes a restore onto a new machine incomplete.** The # column holds ciphertext and the "
    "key is never in the database, so # `endpaper.json` carries a credential nobody can use without a key "
    "the # archive does not contain. That is the whole design and it is strictly # better than the "
    "plaintext this feature started as. # # **The same property is the trap on a machine nobody "
    "administers.** A # restore onto a new laptop, or onto the same one after a reinstall, # brings these "
    "rows back unreadable unless the person still has the # recovery phrase: the key lives in that "
    "machine's keychain or in a file # under `DATA_DIR`, and neither travels in the zip. \"Keep your key "
    'safe" # is not a plan for somebody who double clicked an installer, which is # why the phrase exists '
    "at all and why the settings screen says this # beside the field rather than only here. `RestoreResult` "
    "counts these # rows for the reason it counts `author_aliases`: silently restoring # none leaves a "
    "library whose sources look configured and answer with an # authentication error. # # Absent from "
    "`_REQUIRED_TABLES`, like every table added after # `FORMAT_VERSION` 1: an archive written before this "
    'restores with none, # which is the state it was written in. ("catalogue_credentials", '
    "CatalogueCredential), # The household's own OPDS servers, after the credential table their # "
    "`credential_key` points into. No foreign key in either direction, so # the position is free; here "
    "because the two are read together. # # **The address is the library's and the login is not in this "
    "row**, so # this table restores usefully where `catalogue_credentials` restores # unreadable: somebody "
    "who moves to a new machine gets their servers # back and types the passwords again, which is the same "
    "bargain the # comment above describes and a better one than losing the addresses # too. # # **An "
    "orphaned envelope is the failure this ordering does not # prevent**, and it does not need to: an "
    "archive holding a credential # whose server row is gone leaves a row `credentials.unreadable_sources` "
    "# reports and `DELETE /api/settings/catalogue-sources/{source}/credential` # removes, which is exactly "
    "why that route deliberately does not check # the roster. # # Absent from `_REQUIRED_TABLES`, like "
    "every table added after # `FORMAT_VERSION` 1: an archive written before this restores with none, # "
    'which is the state it was written in. ("opds_servers", OpdsServer), # The password reset requests, '
    "whose only foreign key is `users`, first # in this tuple. Here rather than beside the other per member "
    "tables # because it is not about the catalogue at all: it is the record of who # approved a member's "
    "way back into their account, which is the half of # that flow the member reads. # # **Carried rather "
    "than dropped**, and the pending rows come with it. An # archive already holds every password hash in "
    "the library, so a hash of # a code that stops working within the hour discloses nothing new, and a # "
    "restore that silently emptied this table would take away the record a # member is entitled to read "
    'back. # # **This module is the exception to "only a member starts a reset", and # it is named at every '
    "site that states the rule.** `restore` writes # these rows through `table.insert()` from the archive, "
    "so an archive # can carry an approved request. That widens nothing: a restore replaces # every "
    "password hash in the library in the same transaction, so # whoever can hand one to this route already "
    "holds every account. # # Absent from `_REQUIRED_TABLES`, like every table added after # "
    '`FORMAT_VERSION` 1. ("password_reset_requests", PasswordResetRequest), # Members\' own logins '
    "elsewhere, sealed. Its only foreign key is # `users`. **Carried for `catalogue_credentials`' reason "
    "and with its # cost**: the archive holds ciphertext and never the key, so a restore # onto a machine "
    "without that key brings each token back unreadable, # and its member enters it again on their account "
    "page. Absent from # `_REQUIRED_TABLES`, like every table added after `FORMAT_VERSION` 1. "
    '("member_logins", MemberLogin), ("settings", Setting), ) )'
)

# ── The allowlist, and how to add to it ──────────────────────────────────────
#
# **You are probably reading this because the build went red on a query you
# just wrote.** What follows is what is being asked of you. It is a decision,
# not a form to fill in, and it should take a few minutes.
#
# ## What the rule does
#
# `classifications`, `custom_field_values` and `book_tags` hang off a Book and
# carry no member of their own, so nothing about a row in them says who may
# read it: the answer is entirely "whoever may read its Book". The three passes
# above cannot see a query over them, because such a query names no `Book`
# anywhere. This pass reports **any** statement that reads one of these tables.
# It asks nothing about whether your query is scoped, joined or correct.
#
# ## Why it is this blunt, since your first instinct will be to fix that
#
# It used to ask. Five times, each version a little cleverer, and each was
# demonstrated to leak by the following review round:
#
# | Version | What it accepted | What got past it |
# |---|---|---|
# | 1 | any chain rooted at `Shelf.select()` | no join at all: `FROM books, classifications` |
# | 2 | ...that also joins the table | `join(Classification, Tag.id == Book.id)` |
# | 3 | ...whose onclause names `Book` | `join(Classification, Classification.book_id == Tag.id)` |
# | 4 | ...and names the entity too | `join(Classification, Classification.id == Book.id)` |
# | 5 | ...and names its foreign key | `!=`, `>`, `or_(...)` and three more |
#
# Every one was measured against a real database returning another member's
# private Book, and every one had passed a mutation matrix scoring above 95%.
# Meanwhile this allowlist did not move: **7 statements across 3 modules
# through all five versions**, including the two rounds that added narrowing
# clauses and write gating. The clever rule was the part that kept being
# wrong; the list of statements a human had looked at was the part that held.
#
# So the machinery is gone, on the owner's decision of 2026-08-27. There is no
# sixth version to wait for.
#
# ## What it costs, stated because it is a real cost
#
# A **new correct caller does not pass on its merits.** Writing a perfectly
# scoped index over `classifications` turns this build red and you have to come
# here. That is the trade: correctness of these statements is a human judgement
# recorded once, rather than a property re-derived on every run. Some entries
# below are correct, carefully written queries that the rule reports anyway,
# and they are on the list for exactly that reason. **They say so at their own
# line**, carrying the marker `Correct, and reported anyway`, so which ones
# they are is a grep and not a sentence up here, and that grep matches this
# paragraph too, which is what naming a marker costs. **Keep that marker on one
# line** in any entry that carries it: a copy split across a string
# concatenation is invisible to the grep this paragraph promises, which is what
# the first version of this replacement did to one of the two.
#
# There was a count in this paragraph and it was wrong five times: three for
# one review round while four other places said two, each correction noting the
# error and leaving the wrong number standing above it. The sixth reader
# deleted the number instead, which is the only version of this that cannot go
# stale, and it went stale again the moment a table was added to the guard.
#
# **It also reports plain Python**, and this is the case most likely to look
# like a bug rather than a rule. Any statement naming a guarded entity is
# reported, so `d.get(Classification.number)` is, because nothing here knows
# what the receiver is or whether a table is reached; the type handed to
# `isinstance` or `issubclass` is the exception, since they answer a bool.
# `_entity_aliases` not following `book = Book(...)` keeps `book.tags` out of
# it. The raw SQL arm refuses English that reads as a statement or a fragment,
# `"Delete the tags from a book"` and `"dropped %d rows from classifications"`,
# a foreign key's `"tags.id"`, and a table's name where a dict is looked up by
# it, `archive.get("classifications")`. If you have met one: it is not a
# bug, the answer is the same as for any other entry, and a reason saying
# "this is a message, not a query" or "a declaration, it reads no row" is a
# perfectly good one.
#
# ## What to do
#
# **First, decide whether the query is actually safe**, which means: can a
# member see a row here whose Book they could not see? Work through it in this
# order, because the first two are where the real answers are.
#
# 1. **Is it scoped to Books somebody already resolved?** A route that took a
#    `Book` through `dependencies.py`, or ids that came out of a `Shelf`, has
#    already had the privacy rule applied to it. This is what most of the list
#    below is.
# 2. **Does it publish a set of values rather than rows?** "Every DDC number in
#    the library, with a count" is the dangerous shape and the reason this pass
#    exists: it discloses what is on other people's private Books without ever
#    returning one. A `filter` on such a column is the same disclosure asked one
#    value at a time.
# 3. **If it is a join to `books`, do not trust the shape of it.** Read the
#    table above. Four spellings that look like a correct join are in it.
#    Run the query against two Books, one private, as the other member. That
#    is how every one of those five versions was broken, and it takes ten
#    minutes.
# 4. **If it writes rather than reads**, say so and move on. A `delete` or an
#    `insert` publishes nothing. So does a declaration run at import, such as a
#    table list or a mapping, which reads no row.
#
# **Then add an entry**, in the module's list, saying what the statement does
# and why that is safe. An entry is a pair: **the whole statement**, as the
# failure message prints it, which is its source with runs of whitespace
# flattened to one space, and the reason. The entries are in line order, so a
# new statement goes in the position its line number puts it, and moving a
# statement means moving its entry.
#
# **The statement and not a fragment of it, because a fragment names a token
# and the reason is about the query.** Keyed on a fragment, an entry could be
# satisfied by a neighbour that happened to contain it, and an edit that kept
# the token could drop the narrowing the reason rests on with nothing red.
# Measured over this table on 2026-09-20: 1 of the 17 entries was ambiguous,
# `func.count(DigitalReference.id)` in `routers/books.py`, which also matches
# the flagged reference count five entries above it, so those two reasons were
# interchangeable. `.one_or_none()`, the fragment that looks least distinctive,
# was not: it matched one statement. **Write the check the reasons are
# lined up by, rather than asking the next person to pick a good token.**
# `WHOLE_BOOK_READERS` below keys on a **call** as `ast.unparse` writes it,
# which is shorter; a key here is the whole statement, and a declaration's key
# is the whole declaration with the comments inside it. What makes that
# affordable is that `ruff format` owns the layout, so a statement is
# rewrapped only when its own text, its nesting, the formatter's version or the
# configured line length (110, in `pyproject.toml`) changes, and the first two
# are edits its entry should be re-read for anyway.
# **Flattening alone does not make a key independent of layout**: a
# break beside a bracket flattens to a space the joined line does not have, so
# `filter(\n    x\n)` keys as `filter( x )` and `filter(x)` as itself.
#
# Without that check the reasons were a list beside a list, lined up by
# counting and verified by nothing, which under this rule is the one fact
# stored twice with no enforcement left: the reasons **are** the guarantee now.
# A reason, not a restatement: "narrowed to a Book the route resolved" is a
# reason, "queries custom_field_values" is not. The entries are what the next
# person reads to see where the bar is, so an entry that does not carry an
# argument lowers it for everybody after you.
#
# **If you cannot write that sentence, the query is the thing to change**, not
# this list. Route it through `Shelf.select()` with a join to `books` and it is
# still reported, but it is at least a statement you can defend in one line.
#
# ## What not to do
#
# Do not add an entry to get a green build without reading step 1. Do not
# delete or weaken this test; if it is wrong, say why here in a comment beside
# the change. And do not reintroduce a rule that decides whether the join is
# correct: that is what the table above is a record of.
#
# ## The list
#
# Keyed by module, one entry per statement, and the count comes from `len()` so
# a reason and a count cannot drift apart.
BOOK_OWNED_READERS = {
    "backup.py": [
        (
            ARCHIVE_TABLES_DECLARATION,
            "a declaration, run once at import: the archive's table list, pairing each name with its model "
            "and its `Table`. It reads no row. `build_archive` and `restore` read and write these tables "
            "through the runtime bound columns `INDIRECT_READERS` names, and both are admin only.",
        ),
        (
            'manifest["tables"]["book_tags"] = [dict(row._mapping) for row in '
            "db.execute(book_tags.select())]",
            "reads the whole `book_tags` table into the archive manifest. Not "
            "scoped to anything and deliberately so: an archive that omitted "
            "another member's rows would restore a library missing them. Admin "
            "only, which is what holds it, and `backup.py` is already named "
            "above as the third way past a viewer.",
        ),
        (
            "db.execute(delete(book_tags))",
            "a write: a restore empties the association table before it inserts the archive's rows. It "
            "publishes nothing, and `restore` is admin only.",
        ),
        (
            'associations = tables.get("book_tags") or []',
            "a lookup in the uploaded archive, a dict of rows read off the file, and not in the database. "
            "The table's name is its key, which is the shape the raw SQL arm reads as a table looked up "
            "by name. The rows it finds are the restore's own input, and `restore` is admin only.",
        ),
        (
            "db.execute(book_tags.insert(), associations)",
            "a write: a restore inserts the association rows the archive carries. The rows come from the "
            "file the admin uploaded, and nothing is returned.",
        ),
    ],
    "custom_fields.py": [
        (
            "VALUES_TABLE = CustomFieldValue.__tablename__",
            "a name and not a read: the table's name as a string, published so `folding.TRANSFERS` can "
            "declare a merge policy without importing the value model. No row is read.",
        ),
        (
            "removed = db.query(CustomFieldValue).filter(CustomFieldValue.field_id == field.id).delete()",
            "deletes every value of a custom field the admin is removing, keyed "
            "on `field_id`. A write, and the count it returns describes rows "
            "that no longer exist.",
        ),
        (
            "rows = ( db.query(CustomFieldValue, CustomField) .join(CustomField, CustomField.id == "
            "CustomFieldValue.field_id) .filter(CustomFieldValue.book_id == book.id) "
            ".order_by(CustomFieldValue.field_id) .all() )",
            "reads one Book's values with their field definitions joined on. "
            "The function takes a `Book` object, never an id, which is the "
            "module's own privacy rule: a `Book` can only have come from "
            "`dependencies.py` or the Shelf.",
        ),
        (
            "row = ( db.query(CustomFieldValue) .filter( CustomFieldValue.book_id == book.id, "
            "CustomFieldValue.field_id == field.id, ) .one_or_none() )",
            "reads one `(book, field)` value to decide insert or update. Takes a `Book`, as above.",
        ),
        (
            "taken = {row.field_id for row in "
            "db.query(CustomFieldValue).filter(CustomFieldValue.book_id == "
            "keeper_id)}",
            "reads the keeper's field ids during a Book merge, to know which of "
            "the losers' values would collide. The ids came from a route that "
            "resolved every Book in the merge.",
        ),
        (
            "for row in ( db.query(CustomFieldValue) .filter(CustomFieldValue.book_id.in_(ids)) "
            ".order_by(CustomFieldValue.id) .all() ): if row.field_id in taken: db.delete(row) "
            "else: row.book_id = keeper_id taken.add(row.field_id)",
            "reads the losing Books' values in the same merge, to move them "
            "onto the keeper. Same ids, same route. **The loop body is part of "
            "the argument and so part of the key**: every row it reads is "
            "deleted or repointed on the spot, so this is a write that reads "
            "its own targets rather than a query with an audience.",
        ),
    ],
    "disclosure.py": [
        (
            "return book_tags.c.tag_id",
            "which column a carrier hands the vocabulary reads, chosen by the type. **The reads it feeds "
            "are already decided**: `Disclosure` puts it in `Shelf.seen_by(...).select(...)` and "
            "`Shelf.trashed_by(...).select(...)`, and `shelf.entries_any_book_carries`, the named way past "
            "a viewer, returns ids only and has its callers counted.",
        ),
        (
            "return CustomFieldValue.field_id",
            "which column a carrier hands the vocabulary reads, chosen by the type. **The reads it feeds "
            "are already decided**: `Disclosure` puts it in `Shelf.seen_by(...).select(...)` and "
            "`Shelf.trashed_by(...).select(...)`, and `shelf.entries_any_book_carries`, the named way past "
            "a viewer, returns ids only and has its callers counted.",
        ),
        (
            "return book_tags, book_tags.c.book_id == Book.id",
            "the join onto `books` a carrier's visible read takes. Only ever handed to `.join(...)` on a "
            "Shelf rooted query in `Disclosure`, so it narrows the Shelf's filtered `books` and cannot "
            "widen it.",
        ),
        (
            "return CustomFieldValue, CustomFieldValue.book_id == Book.id",
            "the join onto `books` a carrier's visible read takes. Only ever handed to `.join(...)` on a "
            "Shelf rooted query in `Disclosure`, so it narrows the Shelf's filtered `books` and cannot "
            "widen it.",
        ),
    ],
    "evidence.py": [
        (
            'changed.append("classifications")',
            "names the field a confirm changed, for the response that lists what moved. A label and not a "
            "lookup: the list holds field names, and the table's name is the field's.",
        ),
    ],
    "file_references.py": [
        (
            "return ( db.query(DigitalReference) .filter( DigitalReference.id == reference_id, "
            "DigitalReference.book_id == book.id, ) .first() )",
            "reads one reference so a route can flag or forget it. Narrowed to "
            "the `Book` its caller passed **as well as** to the id, and the "
            "pairing is the point: without it a reference id belonging to "
            "another Book would be reachable through a Book the caller can "
            "see. Takes a `Book` object, never an id, so the Book has been "
            "through `dependencies.py`, and a caller turns `None` into the "
            "404.",
        ),
        (
            "return ( db.query(DigitalReference) .filter(DigitalReference.book_id == book.id) "
            ".order_by(DigitalReference.id) .all() )",
            "reads one Book's references for the route that lists them. Takes "
            "a `Book` object and never an id, so the caller's "
            "`dependencies.book_for_read` has already applied the privacy rule; "
            "the argument `custom_fields.py` makes twice above.",
        ),
        (
            "at_this_location = db.query(DigitalReference).filter( DigitalReference.book_id == "
            "book_id, DigitalReference.root_label == payload.root_label, "
            "DigitalReference.relative_path == payload.relative_path, )",
            "looks up the reference at the location a client has just reported, "
            "to decide whether that is a refresh or a new row, and again after a "
            "concurrent report of the same location won the insert. Narrowed to "
            "the Book id its one caller, the report route, resolved through "
            "`dependencies`; the two payload values narrow it further and neither "
            "of them can widen it.",
        ),
        (
            "holder: int | None = ( Shelf.seen_by(db, member_id) .select(DigitalReference.book_id) "
            ".join(DigitalReference, DigitalReference.book_id == Book.id) .filter( "
            "DigitalReference.book_id != book_id, DigitalReference.root_label == "
            "payload.root_label, DigitalReference.relative_path == payload.relative_path, ) "
            ".order_by(DigitalReference.book_id) .limit(1) .scalar() )",
            "which other Book already holds the location a client is reporting, "
            "so the report can be refused naming it. Written through "
            "`Shelf.select()` and joined outward to `books`, so a private Book of "
            "another member contributes no row and the report goes ahead as if "
            "no Book held it. Returns one id, the lowest.",
        ),
        (
            "held = ( db.query(func.count(DigitalReference.id)) .filter(DigitalReference.book_id == "
            "reference.book_id) .scalar() )",
            "counts one Book's references against the per book ceiling, after "
            "the new one is inserted. Publishes no rows and no values, only how "
            "many that Book holds, and `reference` is built on the Book id the "
            "report route resolved through `dependencies`.",
        ),
        (
            "rows = ( Shelf.seen_by(db, member_id) .select(DigitalReference) "
            ".join(DigitalReference, DigitalReference.book_id == Book.id) .filter( "
            "DigitalReference.id.in_(asked), DigitalReference.root_label == payload.root_label, "
            ") .all() )",
            "resolves the references a sweep names, so the sweep can flag or "
            "refresh them. Written through `Shelf.select()` and joined outward to "
            "`books`, so an id on a Book the member may not see, and therefore "
            "may not write, resolves to no row. The request bounds the id list "
            "at `MAX_FILES_PER_LOOKUP`; the rows are written and only their ids "
            "are returned.",
        ),
        (
            "held = ( Shelf.seen_by(db, member_id) .select( DigitalReference.id, "
            "DigitalReference.book_id, DigitalReference.root_label, "
            "DigitalReference.relative_path, DigitalReference.partial_md5, Book.format, ) "
            ".join(DigitalReference, DigitalReference.book_id == Book.id) .filter( or_( "
            "DigitalReference.relative_path.in_(asked_paths), "
            "DigitalReference.partial_md5.in_(asked_digests), ) ) .all() )",
            "the references matching the files a client asked about, on the "
            "Books the member may see, for the lookup that tells a scan queue "
            "and a reading device which Book already holds a file. Written "
            "through `Shelf.select()` and joined outward to `books`, so a "
            "private Book of another member contributes no row and answers as "
            "no Book does. The request bounds the list it matches against at "
            "`MAX_FILES_PER_LOOKUP`.",
        ),
        (
            "return { book_id for (book_id,) in Shelf.seen_by(db, member_id) "
            ".select(DigitalReference.book_id) .join(DigitalReference, "
            "DigitalReference.book_id == Book.id) .filter(DigitalReference.partial_md5 "
            "== digest) .distinct() .limit(limit) .all() }",
            "which Books carry one digest on a file reference, for one member. "
            "Written through `Shelf.select()` and joined outward to `books`, so "
            "a private Book of another member contributes no row. It returns "
            "ids, at most `limit` of them; KOReader sync asks for two, only to "
            "decide whether exactly one Book holds the file.",
        ),
    ],
    "folding.py": [
        (
            "TRANSFERS: Final[tuple[_Transfer, ...]] = ( _Transfer(_table(book_tags.name), _union_tags), # "
            "Two rows for one Book often carry the same DDC number, and # "
            "`uq_classifications_book_scheme_number` would refuse the second on the # flush. Left out, the "
            "cascade on the loser's deletion takes them and a # merge silently drops the provenance of the "
            "row that lost. _Transfer( _table(Classification.__tablename__), _deduplicated( Classification, "
            "held=lambda book: book.classifications, key=lambda row: "
            "(ClassificationScheme(row.scheme).value, row.number), ceiling=MAX_CLASSIFICATIONS_PER_BOOK, "
            "absorb=_absorb_heading, ), ), # Notes carry their own history. A merge repoints every one of "
            "them whatever # its author or its visibility: a rule that skipped a private note here # would "
            "not hide it, it would delete it. _Transfer(_table(Note.__tablename__), "
            "_moves_wholesale(Note)), # Quotes move with the notes, or the cascade destroys passages "
            "somebody # typed out by hand. Page numbers travel unchanged and may now describe a # different "
            "printing, which is the standing cost of merging two rows that # were two editions: the "
            "alternative is refusing the merge. _Transfer(_table(Quote.__tablename__), "
            "_moves_wholesale(Quote)), # Highlights move whatever their author or sharing, as notes do: a "
            "rule # that skipped a private one would delete it. Nothing to resolve, because # "
            "`uq_highlights_member_source_key` does not name the Book. Unlike notes, # each moved one is "
            "private again: see `_carry_highlights`. _Transfer(_table(Highlight.__tablename__), "
            "_carry_highlights), # `uq_digital_references_location` would refuse the flush where the keeper "
            "# and a loser were catalogued from the same file, which is the **likely** # case rather than "
            "an edge: two rows for one Book are commonly two imports # of one library. A repeat is dropped "
            "after it gives the survivor what one # more look at that location may write: see "
            "`file_references.absorb`. _Transfer( _table(DigitalReference.__tablename__), _deduplicated( "
            "DigitalReference, held=lambda book: book.digital_references, key=lambda row: (row.root_label, "
            "row.relative_path), ceiling=MAX_DIGITAL_REFERENCES_PER_BOOK, absorb=file_references.absorb, ), "
            "), # **Only an exact repeat is a duplicate here**, which is the difference from # the headings "
            "above and the whole reason `uq_book_identifiers_book_scheme_value` # carries the value. Two "
            "Kindle entries a Member declared the same Book carry # two ASINs and both survive: that is the "
            "merge saying which editions were # folded together, where keying on the scheme alone would "
            "have made it an # `IntegrityError` instead of a fact. # # **A loser's `calibre_uuid` row is "
            "dropped like any other at the ceiling**, so # a keeper already carrying eight identifiers "
            "loses the uuid a re-import is # recognised by, and that record would be added once more. Not "
            "given a # preference, because keeping it means deleting one of the keeper's stored # rows "
            "instead, which is a loss of a fact too; the drop is logged. _Transfer( "
            "_table(BookIdentifier.__tablename__), _deduplicated( BookIdentifier, held=lambda book: "
            "book.identifiers, key=lambda row: (BookIdentifierScheme(row.scheme).value, row.value), "
            "ceiling=MAX_IDENTIFIERS_PER_BOOK, ), ), # Two rows for one Book imported from one MARC file "
            "carry the same links, # and `uq_online_links_book_url` would refuse the flush. A repeat URL is "
            "# dropped; its text and relation are the same record's. _Transfer( "
            "_table(OnlineLink.__tablename__), _deduplicated( OnlineLink, held=lambda book: "
            "book.online_links, key=lambda row: row.url, ceiling=MAX_ONLINE_LINKS_PER_BOOK, ), ), "
            "_Transfer(_table(Loan.__tablename__), _carry_loans), # Requests carry no uniqueness, so every "
            "row travels. Two open requests # from one member can result, which the holder answers like any "
            "other. _Transfer(_table(AccessRequest.__tablename__), _moves_wholesale(AccessRequest)), # "
            "Progress carries no uniqueness, so unlike the reading records below there # is nothing to "
            "resolve: two Members' readings of what turned out to be one # Book are two histories of one "
            "Book. _Transfer(_table(ReadingProgress.__tablename__), _moves_wholesale(ReadingProgress)), "
            "_Transfer(_table(reading.RECORDS_TABLE), _carry_reading_records), # A device's document names "
            "the file, not the Book, so the link follows the # Book that survives and nothing collides: the "
            "key is the member and the # document, which a merge does not touch. "
            "_Transfer(_table(KosyncDocument.__tablename__), _moves_wholesale(KosyncDocument)), # Which "
            "Book a member's Readwise book is follows the Book that survives, # for the KOReader document's "
            "reason: the key is the member and Readwise's # own book id, which a merge does not touch. "
            "_Transfer(_table(ReadwiseBook.__tablename__), _moves_wholesale(ReadwiseBook)), "
            "_Transfer(_table(custom_fields.VALUES_TABLE), _carry_custom_field_values), )",
            "a declaration, run once at import: the merge policy per child table. It reads no row. Every "
            "read a policy makes is bounded to the Books being folded, which "
            "`tests/test_folding.py::TestEveryReadIsBoundedToTheBooksBeingFolded` checks by shape.",
        ),
    ],
    "models.py": [
        (
            'book_tags = Table( "book_tags", Base.metadata, Column("book_id", Integer, '
            'ForeignKey("books.id", ondelete="CASCADE"), primary_key=True), Column("tag_id", Integer, '
            'ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True), Index("ix_book_tags_tag_id", '
            '"tag_id"), )',
            "the association table's declaration, run once at import. It reads no row; its name is the "
            "first argument, the position the raw SQL arm reads as a table looked up by name.",
        ),
        (
            'tags: Mapped[list[Tag]] = relationship("Tag", secondary=book_tags)',
            "the mapping that tells the ORM `Book.tags` runs through the association table. A declaration "
            "and not a query; a load through it starts from a `Book` somebody already resolved, which is "
            "the relationship attribute blind spot the module docstring names.",
        ),
    ],
    "recognition.py": [
        (
            "carrying = ( shelf.select(BookIdentifier.value, BookIdentifier.scheme, Book.id) "
            ".join(BookIdentifier, BookIdentifier.book_id == Book.id) "
            ".filter(BookIdentifier.scheme.in_(ladder.schemes)) )",
            "which Book a record carrying a store identifier or a Calibre uuid is, "
            "for one member alone. `shelf` is `Shelf.seen_by` the member and the "
            "join runs outward to `books`, so a private Book of another member "
            "contributes no row. The pairs never leave the process: they decide "
            "only which visible Books carry the identifier, and an add names at "
            "most one of them, as the 409's `book_id` on a Book the caller can "
            "already open.",
        ),
        (
            "carrying = carrying.filter(BookIdentifier.value.in_(narrow.values))",
            "narrows the statement above to one record's own identifiers, for an "
            "add. A clause on the same Shelf scoped join, so it can only remove "
            "rows the reason above already covers.",
        ),
    ],
    "routers/books.py": [
        (
            "db.execute(book_tags.delete().where(book_tags.c.tag_id == tag_id))",
            "deletes the association rows for a Tag being removed. A write, and "
            "reported for the `where` clause on it rather than for being one.",
        ),
        (
            "shelf = Shelf.seen_by(db, current_user.id).where( Book.id > after_id, "
            "Book.isbn.is_(None), Book.google_books_id.is_(None), "
            "Book.identifiers.any(BookIdentifier.scheme == "
            "BookIdentifierScheme.GOOGLE_BOOKS), )",
            "narrows the identifier backfill to Books carrying a store "
            "identifier, as a correlated EXISTS inside `Shelf.where` rather "
            "than a query of its own: the FROM is the Shelf's filtered `books` "
            "and this is a clause on it, so the visibility predicate applies to "
            "the candidate set by construction. It returns no identifier and "
            "counts none; what it publishes is a count of the caller's own "
            "Books, through `Shelf.page`, which is the shelf-wide total every "
            "paginated route here already answers with.",
        ),
        (
            "flagged = DigitalReference.missing_since.isnot(None)",
            "the narrowing clause of the missing references listing, built once and handed to the two Shelf "
            "rooted statements below. On its own it reads nothing; both of its uses are joined outward to "
            "`books` from a Shelf.",
        ),
        (
            "total = ( shelf.select(func.count(DigitalReference.id)) .join(DigitalReference, "
            "DigitalReference.book_id == Book.id) .filter(flagged) .scalar() or 0 )",
            "counts the flagged references on the Books the caller may see, for "
            "the shelf-wide listing. Written through `Shelf.select()` and joined "
            "outward to `books`, so the count is scoped by the same predicate as "
            "the rows: an unscoped total announces how many rows are hidden. "
            "**Correct, and reported anyway**, like the statistics page's tag counts, and the "
            "join is the load bearing half here rather than the filter, since "
            "`Shelf.select()` documents that a missing one is a cartesian "
            "product and not an error.",
        ),
        (
            "rows = ( shelf.select(DigitalReference, Book.title, Book.author, Book.cover_url) "
            ".join(DigitalReference, DigitalReference.book_id == Book.id) .filter(flagged) "
            ".order_by(DigitalReference.missing_since.desc(), DigitalReference.id.desc()) "
            ".offset(paging.offset) .limit(paging.limit) .all() )",
            "the rows of that same listing: every reference a client reported "
            "missing, on a Book the caller may see, with the three Book scalars "
            "a row renders. Scoped by the Shelf and by nothing else, which is "
            "this table's own rule: a reference carries no Member, so its "
            "visibility is its Book's entirely. The route's docstring states "
            "what that discloses, which is an unverified path on somebody's "
            "machine, and why a per reporter view would need a column the table "
            "deliberately does not have. Paginated, so it is bounded like every "
            "other many-book query here.",
        ),
        (
            "under = DigitalReference.root_label == root_label",
            "the narrowing clause of the per root listing, built once and handed to the two Shelf rooted "
            "statements below. On its own it reads nothing; both of its uses are joined outward to `books` "
            "from a Shelf.",
        ),
        (
            "total = ( shelf.select(func.count(DigitalReference.id)) .join(DigitalReference, "
            "DigitalReference.book_id == Book.id) .filter(under) .scalar() or 0 )",
            "counts the references under one root on the Books the caller may "
            "see, for the listing a folder sweep reads. Written through "
            "`Shelf.select()` and joined outward to `books`, so the total is "
            "scoped by the same predicate as the rows below it.",
        ),
        (
            "rows = ( shelf.select(DigitalReference) .join(DigitalReference, "
            "DigitalReference.book_id == Book.id) .filter(under) .order_by(DigitalReference.id) "
            ".offset(paging.offset) .limit(paging.limit) .all() )",
            "the rows of that listing: every reference under one root on a Book "
            "the caller may see. Scoped by the Shelf and by nothing else, the "
            "missing listing's rule for the same table, and paginated.",
        ),
        (
            "identifier = ( db.query(BookIdentifier) .filter( BookIdentifier.id == identifier_id, "
            "BookIdentifier.book_id == book.id, ) .first() )",
            "reads one store identifier so the route can remove it. Narrowed "
            "to a `Book` the dependency resolved **as well as** to the id, for "
            "the reason the digital reference entry above gives: without the "
            "pairing, an identifier id belonging to another Book would be "
            "reachable through a Book the caller does hold. The row it feeds "
            "is deleted and never serialised.",
        ),
    ],
    "routers/stats.py": [
        (
            "by_tag = ( shelf.select(Tag.name, Tag.category, Tag.key, "
            'func.count(book_tags.c.book_id).label("count")) .join(book_tags, Book.id '
            "== book_tags.c.book_id) .join(Tag, Tag.id == book_tags.c.tag_id) "
            ".group_by(Tag.id) .order_by(Tag.category, "
            "func.count(book_tags.c.book_id).desc(), Tag.name) .all() )",
            "Tag counts for the statistics page, written through "
            "`Shelf.select()` and joined to `books`. "
            # Kept on one line. The paragraph above points a grep at this
            # marker, and a copy split across a concatenation is invisible to
            # one: measured, the split cost this entry its line and the grep
            # answered one where the answer is two.
            "**Correct, and reported anyway**"
            ", which is the cost this list pays for not trying to recognise a "
            "correct join. Verified by reading the SQL: the FROM is the "
            "filtered `books` and the join is on `book_tags.book_id == books.id`.",
        ),
    ],
}


#: Every call outside the Shelf that is handed `Book` itself, and why it is safe.
#:
#: A by key read publishes one whole Book, so the question is where the key
#: came from. Keyed on the qualified name of the enclosing scope and the call,
#: in line order; `_whole_book_calls` says why the qualified name is needed.
WHOLE_BOOK_READERS: Final = {
    "importing.py": [
        (
            "Import._apply_one: self._db.get_one(Book, book_id)",
            "loads the Book `recognition` matched a CSV row to. The id is a `Seen` answer, which "
            "`recognition.Index` answers only from the rows it read off `Shelf.seen_by` the importing "
            "member and from the Books this import created, so it names a Book that member may open.",
        ),
        (
            "MarcImport._apply_one: self._db.get_one(Book, book_id)",
            "the same load for a MARC record, off the same `Seen` answer and the same Shelf scoped index.",
        ),
        (
            "OpdsImport._apply_one: self._db.get_one(Book, book_id)",
            "the same load for an OPDS entry, off the same `Seen` answer and the same Shelf scoped index.",
        ),
    ],
    "notifications.py": [
        (
            "count_private_overdue: db.query(Loan).join(Book, Loan.book_id == Book.id)",
            "a join, not a by key read: `JOIN_CALLERS` carries the reason this module reaches `books`.",
        ),
        (
            "count_overdue: db.query(Loan).join(Book, Loan.book_id == Book.id)",
            "the same join, for the count over every Book; `JOIN_CALLERS` again.",
        ),
    ],
}


#: Every statement outside the Shelf holding SQL that names `books`, and why it is safe.
#:
#: Raw SQL names no `Book`, so passes 2 and 3 cannot see it, and `books` is
#: not a book-owned table, so the fourth pass does not read it either. A
#: location index written as `text("SELECT location, count(*) FROM books ...")`
#: is the shape these rules exist for. Keyed on the whole statement, in line
#: order, as `BOOK_OWNED_READERS` is; `_raw_sql_naming` says which strings count.
BOOKS_SQL_READERS: Final = {
    "database.py": [
        (
            'db.execute( text("SELECT id FROM books WHERE id = :book FOR NO KEY UPDATE"), '
            '{"book": book_id}, )',
            "a row lock on one Book the caller already resolved, taken by id on Postgres. It returns the id "
            "it was handed and nothing else.",
        ),
    ],
    "models.py": [
        (
            'books = metadata.tables.get("books")',
            "the `books` table object out of a `MetaData`, for `children_of_books` to compare foreign keys "
            "against. Schema, not rows: no statement is issued.",
        ),
    ],
    "schema.py": [
        (
            'columns = {column["name"] for column in inspector.get_columns("books")}',
            "the column names of `books`, read off the schema at startup to decide whether a legacy "
            "database needs the column below. It reads no row.",
        ),
        (
            'connection.execute(text("ALTER TABLE books ADD COLUMN is_private BOOLEAN NOT NULL DEFAULT 0"))',
            "a schema change at startup, before any request is served. It reads no row.",
        ),
    ],
}


#: Every statement outside the Shelf naming a relationship into `Book` off its
#: owning class, or reading a to many one off an instance, and why it is safe.
#: `_relationship_offences` says which spellings count. Keyed on the whole
#: statement, in line order, as `BOOK_OWNED_READERS` is. `JOIN_CALLERS` is not
#: excluded: a module wide exemption would hide every later statement there.
RELATIONSHIP_READERS: Final = {
    "importing.py": [
        (
            "book = _settle_one( index.books.recognise(title=row.title, author=row.author, isbn=row.isbn), "
            "tally, load=lambda book_id: self._db.get_one(Book, book_id), unmatched_title=row.title, "
            "create=lambda: self._create(row, index), fill_gaps=lambda matched: _fill_gaps(matched, row), "
            "create_missing=create_missing, )",
            "`index.books` is the importer's `recognition.Index`, not a relationship: an attribute of "
            "`_CatalogueIndex` sharing the name, whose every candidate came from `Shelf.seen_by`.",
        ),
        (
            "index.books.remember(book)",
            "the same `recognition.Index`, told about a Book this importer has just created for its "
            "own member. It reads no row.",
        ),
    ],
    "lending.py": [
        (
            "RENDERED: Final[tuple[Any, ...]] = ( joinedload(Loan.book).joinedload(Book.added_by), "
            "joinedload(Loan.book).selectinload(Book.tags), "
            "joinedload(Loan.book).selectinload(Book.classifications), "
            "joinedload(Loan.book).selectinload(Book.identifiers), "
            "joinedload(Loan.book).selectinload(Book.online_links), joinedload(Loan.loaned_to), "
            "joinedload(Loan.loaned_by), )",
            "loader options, a declaration run once at import. They say how to load the Book of a loan "
            "a query already chose, and choose no row themselves. `Loans` applies them to a query it "
            "has already scoped, and `routers/loans.py` to the viewer scoped overdue query; a query "
            "they are handed to chooses the rows.",
        ),
    ],
    "notifications.py": [
        (
            "return ( lending.Loans.for_a_channel(db) .overdue(now) .as_query() "
            ".options(joinedload(Loan.book), joinedload(Loan.loaned_to)) "
            ".filter((Loan.notified_at.is_(None)) | (Loan.notified_at < cutoff)) "
            ".order_by(Loan.due_at, Loan.id) .all() )",
            "a loader option on a query `Loans.for_a_channel` already scoped to the public shelf. It "
            "says how to load the Book of each overdue loan and chooses no row itself.",
        ),
    ],
    "schemas/book.py": [
        (
            "shown = len(self.books)",
            "`self` is a `DuplicateGroup`, a response model, and `books` its list of members the "
            "endpoint already chose through the Shelf. Not a relationship: a field sharing the name.",
        ),
    ],
}


def _statement_at(source: str, line: int) -> str:
    """The source of the statement beginning at this line, whitespace flattened.

    So an entry in `BOOK_OWNED_READERS` can be tied to the statement it claims
    to describe, by equality: the entries are keyed on what this returns.
    Without that the reasons were a list beside a list, matched by position and
    checked by nothing: the one fact stored twice with no enforcement left.

    **The widest statement starting at that line**, so a query inside a `for`
    carries the loop with it. That is the unit the rule reports and the unit an
    entry is about: the one such entry in `custom_fields.py` says in its reason
    that the body deletes or repoints every row it reads, which is half of why
    that read is safe, so the key and the argument cover the same code.

    **What this returns is a key rather than source**, and a compound statement
    flattens to something no parser would take back. That costs nothing: it is
    only ever compared.
    """
    tree = ast.parse(source)
    widest = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.stmt)
            and node.lineno == line
            and (widest is None or (node.end_lineno or 0) > (widest.end_lineno or 0))
        ):
            widest = node
    if widest is None:
        return ""
    return " ".join((ast.get_source_segment(source, widest) or "").split())


def _entries_off_their_statements(source: str, lines: list[int], entries: list[tuple[str, str]]) -> list[str]:
    """Which allowlist entries are not keyed on the statement they sit against.

    **The comparison `BOOK_OWNED_READERS` is enforced by, in one place**, so the
    tree assertion and the witness below run the same rule: a fixture that
    exercises its own copy reports on a rule the tree is not read against.

    Equality and not containment. A fragment names a token and a reason is about
    the query, so an edit that keeps the token and drops the narrowing the
    reason rests on used to pass, and a fragment that is not distinctive could
    be satisfied by a neighbour.
    """
    off = []
    for line, (expected, _) in zip(lines, entries, strict=True):
        statement = _statement_at(source, line)
        if statement != expected:
            off.append(
                f"{line} is not the statement its allowlist entry is keyed on.\n"
                f"      entry expects: {expected}\n"
                f"      statement is:  {statement}"
            )
    return off


@functools.cache
def _backend_module_names() -> frozenset[str]:
    """Every dotted name an import of a module in this backend can spell.

    **Derived from `application_sources()`, never listed.** An inclusion list is
    one of the four tells this repository names, and this one would go stale
    the day somebody adds a module.

    **It is the import resolution this process performs, rather than an
    approximation of it.** `pyproject.toml` puts the backend root on
    `sys.path`, so a dotted name the corpus holds is the module an import of
    that name binds, whatever else on the path shares the name. That is also
    why `shelving.py` is not called `collections.py`: its own docstring
    records the shadowing that name would cause, and this is a second reason
    it must not be. **A module here named after something installed would stop
    the subtraction applying to imports written for the installed one, and the
    false refusal this subtraction exists to prevent would come back for that
    name.** Measured 2026-09-30: of the 99 names this returns, none collides
    with the 297 standard library names or with the 126 top level names
    installed in this environment.

    Parent packages are included because `routers` is importable even where
    the walk only ever saw `routers/books.py`.

    **What it leaves out is what `application_sources()` leaves out**: `tests/`,
    `migrations/` and anything a tool owns. An entity imported from a test
    helper therefore still loses its alias. No module under `backend/` outside
    those directories imports one that way, and the subtraction is the safe
    direction for a test helper in any case.

    Cached because `_entity_aliases` runs once per module inside loops over
    that corpus, and the derivation reads every file under `backend/`.

    **The cache is off the real filesystem, while the passes are driven
    against in memory corpora** by the registry plants, which hand the offence
    walk a dict of sources. A plant that invents a module resolves against the
    tree on disk and not against its own corpus, so an import from the
    invented module is treated as coming from outside this backend and its
    alias is subtracted: an arm expecting a report then fails loudly, and an
    arm expecting none passes for the wrong reason. No arm does either today.
    """
    names: set[str] = set()
    for path in application_sources():
        dotted = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        parts = dotted.split(".")
        names.update(".".join(parts[:cut]) for cut in range(1, len(parts) + 1))
    return frozenset(names)


def _entity_aliases(tree: ast.Module, roots: frozenset[str], module: str = "models") -> set[str]:
    """Every local name bound to one of `roots` in one module.

    Resolved rather than assumed, because `from models import Book as B` binds
    a name this rule would otherwise never look for.

    **One resolver for every rule in this file**, and it takes the entities and
    the module rather than naming `Book` and `models`, for the reason
    `tests/bindings.py` gives: a second implementation of "which names mean this
    thing" is a second thing to get the `AnnAssign` half of wrong. The imports and
    the plain rebindings are resolved there; what is this rule's own is the bare
    root seeding, the subtraction below and `aliased(...)`. `_BOOK` is
    what the three original passes hand it, `BOOK_OWNED` is what the fourth does,
    and `_OUTBOUND` with `module="shelf"` is what the fifth does. That fifth rule
    read the import and not the rebinding when it was written on its own, and
    `Mk = Outbound` walked past it.

    Three assignment forms are followed as well: `X = Book`, `X = models.Book`
    and `X = aliased(Book)`. The third is not hypothetical here,
    `serialisation.py` already builds queries on an `aliased(...)` entity.

    **Only those three, deliberately.** Following any assignment whose value
    merely mentions `Book` was measured against the tree and reports five false
    positives in `routers/books.py` (544, 571, 578, 3116, 3219), because
    `book = Book(...)` would make `book` an alias and
    `"; ".join(tag.name for tag in book.tags)` is then a join offence. The
    three literal forms give zero.

    **A root name the module binds from outside this backend is not this
    entity**, and that is a binding question rather than a spelling one. The
    seeding below starts from the bare root, because most modules use the plain
    name and never rebind it; a module importing the same name from elsewhere
    has a different object under it. `Collection` is the live case:
    `models.Collection` is a table and `collections.abc.Collection` is a typing
    protocol, and **five** modules outside the tests bind the bare name to the
    second one, `shelf.py` among them, counted off the `ast` and agreed by a
    grep. A rule matching the name would refuse one of those the first time it
    appeared in a reading call. Measured on this tree the subtraction moves no
    reported line for any entity set in use, and it removes the false alias
    from exactly those five modules; it is here for the refusal nobody looks
    for rather than for a miss.

    **Outside the backend, and not merely outside `models`: the difference was
    a tree wide hole.** `shelf.py`, `shelving.py` and `serialisation.py` each
    re-export these names at run time, so `from shelf import Book` bound the
    real entity under a name the earlier spelling struck out, and **every pass
    in this file went blind for that whole module, silently**. Measured
    2026-09-30 before the fix: that import with a `db.query(Book)` under it
    reported nothing where the same read imported from `models` reported one
    line, and `from shelving import Collection` left the collection rule green.
    A re-export is a spelling somebody writes by accident, so the miss is
    reached more cheaply than the false refusal the subtraction exists for.

    **What it costs, stated rather than bounded.** A module doing both, an
    `import models` reaching `models.Collection` **and** a `from collections.abc
    import Collection`, loses the qualified spelling too, because the qualified
    form is matched on the attribute name alone. No module does both today. The
    mechanism is what is written down; the extent is not claimed.
    """
    names = set(roots)
    resolved = SourceNames(tree)
    from_this_module = resolved.bound_to(*(f"{module}.{root}" for root in roots))
    # A relative import cannot leave this backend, so its unresolved leading dot
    # alone settles it.
    from_outside_the_backend = {
        binding.local
        for binding in resolved.bindings
        if binding.from_module is not None
        and not binding.from_module.startswith(".")
        and binding.from_module not in _backend_module_names()
    }
    names -= from_outside_the_backend - from_this_module
    names |= from_this_module

    # A second pass, because an alias may be assigned above or below the import
    # in file order and this rule does not care which.
    for node in ast.walk(tree):
        for target, value in assignments(node):
            if isinstance(target, ast.Name) and _is_guarded_entity(value, names):
                names.add(target.id)
    return names


def _is_guarded_entity(value: ast.expr, names: set[str]) -> bool:
    """Whether an assigned value rebinds a guarded entity under a new name.

    `X = Book`, `X = models.Book`, `X = aliased(Book)`, and nothing else.
    """
    if _names_entity(value, names):
        return True
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    # `aliased(...)` and `orm.aliased(...)`: the qualified spelling is the same
    # call and was not seen by a check that required a bare Name.
    named_aliased = (isinstance(func, ast.Name) and func.id == "aliased") or (
        isinstance(func, ast.Attribute) and func.attr == "aliased"
    )
    # Keyword arguments too: `aliased(element=Book)` passes Book by name.
    arguments = [*value.args, *(k.value for k in value.keywords)]
    return named_aliased and any(_names_entity(a, names) for a in arguments)


def _names_entity(node: ast.AST, aliases: set[str]) -> bool:
    """Whether an expression is a guarded entity itself, not a column of it.

    **`Classification.__table__` is the same entity**, and it is the Core
    handle every mapped class carries. Without this hop
    `T = CustomFieldValue.__table__` would not make `T` an alias, and
    `T.select()` would name nothing this file looks for.
    """
    if isinstance(node, ast.Attribute) and node.attr == "__table__":
        return _names_entity(node.value, aliases)
    if isinstance(node, ast.Name):
        return node.id in aliases
    return isinstance(node, ast.Attribute) and node.attr in aliases


def _entities_named_in(node: ast.AST, aliases: set[str]) -> set[str]:
    """Which guarded entities an expression names, model or column alike.

    Both shapes count. `query(Book)` returns rows; `query(Book.author)` returns
    a column out of the same rows, and publishing which authors, locations or
    series exist is the same leak by a narrower door. The attribute form also
    catches `models.Book`, which a name-only check would miss.
    """
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in aliases:
            found.add(child.id)
        elif isinstance(child, ast.Attribute) and child.attr in aliases:
            found.add(child.attr)
    return found


def _mentions_entity(node: ast.AST, aliases: set[str]) -> bool:
    """Whether an expression names a guarded model or any column of it."""
    return bool(_entities_named_in(node, aliases))


def _query_offences(source: str) -> list[int]:
    """Line numbers where this module builds a query over `books`.

    Five spellings start a query here: `query`, `select_from`, `with_entities`,
    the bare `select` imported from SQLAlchemy, and `sa`/`sqlalchemy.select`.
    The AST rather than a regex because the regex version of this rule was
    evaded four different ways: through a join, through `models.Book`, through
    an import alias, and through `sqlalchemy.select`.

    This is **not** the guard it replaced. That one walked scopes and tracked
    bindings through `symtable` in order to decide whether a predicate had been
    applied. Here the answer outside `shelf.py` is always zero, so there is no
    such decision to make: `_entity_aliases` resolves which names mean `Book`, and
    everything after that is a flat walk with no scopes and no exemption
    comments.

    `obj.select(...)` is deliberately not an offence. That is the Shelf's own
    method, and reporting it would report every correct caller.
    """
    tree = ast.parse(source)
    aliases = _entity_aliases(tree, _BOOK)
    select_names, module_names = _sqlalchemy_names(tree)
    offences = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _builds_a_query(node.func, select_names, module_names) and any(
            _mentions_entity(arg, aliases) for arg in node.args
        ):
            offences.append(node.lineno)
    return sorted(offences)


#: Methods that put columns or entities into a query's SELECT.
#:
#: **Taken as a family, not one at a time**, which is the lesson four rounds of
#: review kept teaching in different words. `select_from` was added because
#: `Shelf.select()` uses it; `with_entities` a round later because `Shelf.count()`
#: does; `add_columns` and `add_entity` the round after that, because they are
#: `with_entities` under other names and evade exactly as it did
#: (`db.query(Loan.id).add_columns(Book.location)` compiles to
#: `SELECT loans.id, books.location FROM loans, books`). Each was fixed as an
#: instance and the class was missed twice.
_QUERY_BUILDERS = frozenset({"query", "select_from", "with_entities", "add_columns", "add_entity"})

#: Methods that reach another table by joining it.
#:
#: The same family rule. `join` was covered and `outerjoin` was not, which cost a
#: round; then `join_from` was covered and `outerjoin_from` was not, which cost
#: another. An outer join reads **more** rows than an inner one, never fewer.
#: The `_from` pair name the FROM entity as well as the target, so both of their
#: first two arguments are positions `Book` can occupy.
_JOIN_METHODS = frozenset({"join", "outerjoin", "join_from", "outerjoin_from"})


def _sqlalchemy_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The local names in one module for SQLAlchemy's `select` and its package.

    Resolved from the imports, **the same way `_entity_aliases` resolves the
    model**, and for the same reason: a rule that lists spellings guards the
    spellings it thought of. Both holes this closes were measured, and the
    second is worse than a miss.

    `from sqlalchemy import select as sel` then `sel(Book.location)` was an
    unfiltered location index clean on every pass, and was listed as a blind
    spot on the grounds that resolving it would double the resolver to guard a
    spelling the tree does not use. It costs eight lines and it is shared.

    `import sqlalchemy as sq` was worse. The rule of the day excluded `sa` and
    `sqlalchemy` by name, so `sq.select(Tag.id).join_from(Tag, book_tags)` was
    read as **the Shelf's** method and forgiven, while the identical `sa.`
    spelling was caught. A hard-coded list did not just miss a shape there; it
    turned one into a licence. Both spellings are reported now for the ordinary
    reason, and `select_names` still earns its place in pass 2.

    **The package is matched by prefix, not by string**, which is the same
    lesson a third time. The first version of this function resolved the alias
    and then listed the path, so `from sqlalchemy.sql import select` and
    `from sqlalchemy.future import select` were clean on every pass and
    `import sqlalchemy.sql as sq` was forgiven as a Shelf again. `select` is
    re-exported from several modules of one package, and submodule imports are
    already an idiom here: `notifications.py` and `models.py` both import from
    `sqlalchemy.sql.elements`.
    """
    select_names: set[str] = set()
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_sqlalchemy(alias.name):
                    # `import sqlalchemy.sql` binds the top package, not the
                    # submodule, so the bound name is the part before the dot
                    # unless the import gave it one of its own.
                    module_names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and _is_sqlalchemy(node.module):
            for alias in node.names:
                if alias.name == "select":
                    select_names.add(alias.asname or alias.name)
    return select_names, module_names


def _is_sqlalchemy(module: str | None) -> bool:
    """Whether a dotted module path is SQLAlchemy or something inside it.

    The prefix, so no list of submodules has to be kept current. `None` is a
    relative import, which cannot reach the package.
    """
    return module is not None and (module == "sqlalchemy" or module.startswith("sqlalchemy."))


def _rooted_at_module(node: ast.expr, module_names: set[str]) -> bool:
    """Whether an attribute chain starts at one of these module names.

    `sqlalchemy.sql.select(...)` puts an `Attribute` where the two checks that
    consume this used to require a `Name`, so the dotted receiver got past both
    while `sq.select(...)` did not. Walking to the root closes the family
    rather than the two spellings that were measured, which is the rule this
    file has paid to learn twice: `outerjoin` without `outerjoin_from`, and
    `with_entities` without `add_columns`.
    """
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id in module_names


def _builds_a_query(func: ast.expr, select_names: set[str], module_names: set[str]) -> bool:
    """Whether this call is one that starts a query.

    `db.query(...)`, the bare `select(...)` `serialisation.py` imports from
    SQLAlchemy, and the `sa.select(...)` / `sqlalchemy.select(...)` spellings
    of the same thing.

    `obj.select(...)` on anything else is deliberately not one. That is the
    Shelf's own method, and treating it as a query builder reported every
    correct caller of the seam as an offender.
    """
    # `db.query(Book)`, `db.query(Book.author)`, `db.query(func.count(Book.id))`,
    # and `db.query(Tag.name).select_from(Book)`, which is the shape
    # `Shelf.select()` itself is built from: hand-rolling the seam without the
    # predicate has to be an offence, or the diff teaches the evasion.
    # `with_entities` for the same reason `select_from` is here: `Shelf.count()`
    # is itself `self._query.with_entities(func.count(Book.id))`, so it is a
    # spelling a reader of this seam has already met, and
    # `db.query(Loan).with_entities(Book.location)` compiles to
    # `SELECT books.location FROM books`, an unfiltered index.
    if isinstance(func, ast.Attribute) and func.attr in _QUERY_BUILDERS:
        return True
    if isinstance(func, ast.Name) and func.id in select_names:
        return True
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "select"
        and _rooted_at_module(func.value, module_names)
    )


def _join_offences(source: str) -> list[int]:
    """Line numbers where this module reaches `books` through a join.

    The shape the old guard was blind to and documented as such: a statement
    whose `query()` names no `Book` and gets to the table through
    `.join(Book, ...)` anyway, whatever it selects.
    """
    tree = ast.parse(source)
    aliases = _entity_aliases(tree, _BOOK)
    offences = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _JOIN_METHODS
        ):
            continue
        # Only the entity positions, never the whole call: the onclause of a
        # legitimate outward join mentions `Book` on one side
        # (`join(User, Book.added_by_user_id == User.id)` in `routers/stats.py`),
        # so walking every argument would report every correct caller.
        #
        # The keyword form `join(target=Book, onclause=...)` carries no
        # positional argument at all, so reading `args[0]` alone missed it.
        entity_positions = 2 if node.func.attr.endswith("join_from") else 1
        targets = [
            *node.args[:entity_positions],
            *(k.value for k in node.keywords if k.arg == "target"),
        ]
        if any(_mentions_entity(t, aliases) for t in targets):
            offences.append(node.lineno)
    return sorted(offences)


def _whole_book_calls(source: str) -> list[tuple[int, str]]:
    """Every call this module hands `Book` itself to, rather than a column of it.

    **The by key read**, `db.get(Book, book_id)` or `db.get_one(Book, book_id)`,
    which passes 2 and 3 cannot see: neither method starts a query or joins
    one, and the entity sits in an argument. Keyed on the entity alone, so no
    method name is consulted. A column, `Book.id`, is the other passes'
    business, and a row built in memory, `Book(...)`, puts the entity in the
    callee rather than in an argument.

    **A call to a Python builtin is not one**, `isinstance(x, Book)` and
    `getattr(Book, sort_key)` among them: the language's own names, which no
    library release moves, and none of them reads a row. A module that binds
    a builtin's name itself is read as calling its own. An entity computed at
    run time, `db.get(type(book), other_id)`, names nothing and passes; the
    id is the part a by key read has to justify, and this cannot see either.

    Each is returned with its key for `WHOLE_BOOK_READERS`: the enclosing
    classes and functions, then the call as `ast.unparse` writes it. The
    qualified name is what tells apart the three identical loads in
    `importing.py`, one per importer.
    """
    tree = ast.parse(source)
    aliases = _entity_aliases(tree, _BOOK)
    builtin = set(dir(builtins)) - _module_level_names(tree)
    found: list[tuple[int, str]] = []

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                inner = (*scope, child.name)
            if (
                isinstance(child, ast.Call)
                and not (isinstance(child.func, ast.Name) and child.func.id in builtin)
                and any(
                    _names_entity(argument, aliases)
                    for argument in [*child.args, *(keyword.value for keyword in child.keywords)]
                )
            ):
                found.append((child.lineno, f"{'.'.join(scope)}: {ast.unparse(child)}"))
            walk(child, inner)

    walk(tree, ())
    return sorted(found)


def _relationships_into(entity: type) -> dict[str, frozenset[str]]:
    """Every relationship whose target is this entity, keyed by the class that owns it.

    Read off the models' own mappers, as `_book_owned_entities` is, so a
    relationship added tomorrow is in the set without anybody editing this
    file.
    """
    found: dict[str, set[str]] = {}
    for mapper in Base.registry.mappers:
        for relationship in mapper.relationships:
            if relationship.mapper.class_ is entity:
                found.setdefault(mapper.class_.__name__, set()).add(relationship.key)
    return {owner: frozenset(keys) for owner, keys in found.items()}


#: Every relationship into `Book`, by the class that owns it.
RELATIONSHIPS_INTO_BOOK: Final = _relationships_into(Book)


def _to_many_keys_into(entity: type) -> frozenset[str]:
    """The key of every relationship into this entity that loads a list of them.

    Off the same mappers as `_relationships_into`, so a collection of Books
    a model gains tomorrow is read without anybody editing this file.
    """
    return frozenset(
        relationship.key
        for mapper in Base.registry.mappers
        for relationship in mapper.relationships
        if relationship.mapper.class_ is entity and relationship.uselist
    )


#: The relationships into `Book` that an instance can read many Books through.
TO_MANY_INTO_BOOK: Final = _to_many_keys_into(Book)


def _relationship_offences(source: str) -> list[int]:
    """Statement line numbers that name a relationship into `Book` off the class owning it,
    or read a list of Books off any instance.

    **The class qualified spelling, `User.books_added`, and never an instance's
    `loan.book`.** `db.query(User.username, func.count()).join(User.books_added)`,
    `db.query(Collection.name, func.count()).join(Collection.books)` and
    `db.query(func.count(Loan.id)).filter(Loan.book.has(...))` each count
    across every member's Books and name no `Book` anywhere a pass above reads.
    They are the ORM's idiomatic spellings of a join or a correlated EXISTS
    into `books`, so an author simplifying an explicit join lands on one.

    Keying on every relationship *name* was measured and refused, because every
    `book.tags` in Python then reports. This keys on the owning class, which an
    instance attribute never is: `_entity_aliases` resolves the owner's local
    names, so `models.Loan.book` and an alias of `Loan` count, and `loan.book`
    does not.

    **A to many relationship into `Book` is read off any receiver**, because
    an instance reaches through it every Book the row collects, other
    members' Private ones included: `len(collection.books)` counts a
    household wide collection, and `user.books_added` lazy loads every Book
    a member added. A scalar `loan.book` reaches the one Book its row
    already points at, which is why the scalar keys stay class only. The
    receiver is not resolved, so a schema's own `self.books` or an
    importer's `index.books` reports too and is registered with its reason:
    a receiver this cannot type is the read it must not guess past.

    **Not caught: an `association_proxy` or a hybrid property reaching Books.**
    The keys come from `mapper.relationships`, which lists neither, so
    `list(user.lent)` through a proxy over `loans` passes. None exists today,
    and adding one is a models change, a deliberate act.
    """
    tree = ast.parse(source)
    present = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    wanted = {owner: keys for owner, keys in RELATIONSHIPS_INTO_BOOK.items() if keys & present}
    owner_names = {owner: _entity_aliases(tree, frozenset({owner})) for owner in wanted}
    statements = _enclosing_statements(tree)
    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)):
            continue
        if node.attr in TO_MANY_INTO_BOOK or any(
            node.attr in keys and _names_entity(node.value, owner_names[owner])
            for owner, keys in wanted.items()
        ):
            statement = statements.get(id(node))
            found.add(statement.lineno if statement is not None else node.lineno)
    return sorted(found)


def _tables_of(entities: frozenset[str]) -> frozenset[str]:
    """The table names these entities map to, for the raw SQL arm.

    The same derivation `_book_owned_entities` makes in the other direction:
    a mapped class names its `local_table`, and an association table is the
    module level `Table` that names it.
    """
    tables = set()
    for mapper in Base.registry.mappers:
        if mapper.class_.__name__ in entities and isinstance(mapper.local_table, Table):
            tables.add(mapper.local_table.name)
    for attribute, value in vars(models).items():
        if attribute in entities and isinstance(value, Table):
            tables.add(value.name)
    return frozenset(tables)


#: The words a SQL statement opens with. SQL's, not a library's, so no release
#: of SQLAlchemy can move them.
_SQL_VERBS: Final = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "WITH",
    "ALTER",
    "CREATE",
    "DROP",
    "REPLACE",
    "PRAGMA",
)

#: The keywords a table name follows inside a statement.
_SQL_TABLE_KEYWORDS: Final = ("FROM", "JOIN", "UPDATE", "INTO", "TABLE")


def _raw_sql_naming(tables: frozenset[str], *, key_columns: bool = True) -> Callable[[str], bool] | None:
    """Whether a string is SQL naming one of these tables as an identifier.

    Three shapes, each read off SQL's grammar rather than off the call the
    string is handed to, so a statement kept in a module constant is read where
    it is written:

    * **A statement**: it opens with a verb in `_SQL_VERBS`, holds a keyword
      in `_SQL_TABLE_KEYWORDS` after that verb, and names the table anywhere
      as a word. A comma join, `FROM books b, classifications c`, and a schema
      qualified `public.classifications` are both a word. The keyword is what
      keeps `"Create the file's tags and put them on the books"`, a route's
      parameter description, from reading as a statement, and reading it
      after the verb is what keeps `"Update the tags on a book"` from being
      its own keyword.
    * **A fragment**: a keyword in `_SQL_TABLE_KEYWORDS` before the name,
      optionally quoted or schema qualified. A subquery, a join handed to
      `select_from` and the half of a statement split across a `+` all take
      this shape.
    * **A qualified column**, the whole string `classifications.number`, as
      `literal_column` takes it. `key_columns=False` leaves out the one column
      every child's foreign key spells this way, so the `books` arm reads
      `"books.location"` and not `"books.id"`.

    **Every shape in any case**, because SQL's keywords and an unquoted
    identifier are both case insensitive, and an arm reading upper case only
    let `text("book_id in (select book_id from classifications)")` through.
    The price is English: `"dropped %d rows from classifications"`, a log
    line, reads as a fragment and is refused, and so is English that opens
    with a verb and holds a keyword, `"Delete the tags from a book"`. A
    registry entry answers each. A SQL statement that opens with a comment is
    the false negative the first shape costs. The third reports a foreign key,
    `ForeignKey("tags.id")`, which is a declaration and is registered as one.
    A bare table name is not this function's: `_raw_sql_offences` reads it
    where a table is looked up by name.
    """
    if not tables:
        return None
    names = "|".join(re.escape(table) for table in sorted(tables))
    statement = re.compile(rf"^[\s(]*(?:{'|'.join(_SQL_VERBS)})\b", re.IGNORECASE)
    keyword = re.compile(rf"\b(?:{'|'.join(_SQL_TABLE_KEYWORDS)})\b", re.IGNORECASE)
    word = re.compile(rf"\b(?:{names})\b", re.IGNORECASE)
    qualifier = r"(?:[\"`]?\w+[\"`]?\.)?"
    fragment = re.compile(
        rf"\b(?:{'|'.join(_SQL_TABLE_KEYWORDS)})\s+{qualifier}[\"`]?(?:{names})\b", re.IGNORECASE
    )
    # `(?!id\b)` for the foreign key's spelling, `"books.id"`, and only that.
    which = r"\w+" if key_columns else r"(?!id\b)\w+"
    column = re.compile(rf"^[\"`]?(?:{names})[\"`]?\.{which}$", re.IGNORECASE)

    def naming(value: str) -> bool:
        opened = statement.search(value)
        return (
            (
                opened is not None
                and keyword.search(value, opened.end()) is not None
                and word.search(value) is not None
            )
            or fragment.search(value) is not None
            or column.search(value) is not None
        )

    return naming


def _docstrings(tree: ast.Module) -> set[int]:
    """The string nodes that are a module's, a class's or a function's docstring."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        ):
            found.add(id(node.body[0].value))
    return found


def _raw_sql_offences(source: str, tables: frozenset[str], *, key_columns: bool = True) -> list[int]:
    """Statement line numbers holding a string that is SQL naming one of these tables.

    **Every string literal in the module but a docstring**, wherever it sits:
    an argument, a module constant, one piece of an f-string. Reading only the
    strings handed to a call missed the commonest way raw SQL is written,
    which is a constant named once and executed elsewhere. `_raw_sql_naming`
    says which strings count.

    **A bare table name counts where a table is looked up by name**: the key
    of a subscript and the first argument of a call. That is how
    `Base.metadata.tables["classifications"]`, `table("classifications")` and
    a reflected `Table("classifications", MetaData(), ...)` reach a table with
    no entity and no SQL. The same string anywhere else is a dict key, a
    router tag or an archive entry, which this tree writes often and which
    reads nothing. At these two positions it still refuses some statements
    that read nothing, each registered with its reason; the decisions entry
    for this guard carries the count.
    """
    naming = _raw_sql_naming(tables, key_columns=key_columns)
    if naming is None:
        return []
    tree = ast.parse(source)
    owner = _enclosing_statements(tree)
    skipped = _docstrings(tree)
    looked_up: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            looked_up.add(id(node.slice))
        elif isinstance(node, ast.Call) and node.args:
            looked_up.add(id(node.args[0]))
    found = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
            and (naming(node.value) or (id(node) in looked_up and node.value in tables))
        ):
            statement = owner.get(id(node))
            found.add(statement.lineno if statement is not None else node.lineno)
    return sorted(found)


@functools.cache
def _table_name_aliases(tables: frozenset[str]) -> frozenset[str]:
    """Module level names in this backend whose value is one of these table names.

    `custom_fields.VALUES_TABLE` is one: a name read where the table is wanted,
    which `Base.metadata.tables[custom_fields.VALUES_TABLE]` turns into a read
    naming no entity and no SQL. Read off each module's `vars()` after import,
    so a name computed from `__tablename__` counts as surely as a literal.
    Dunder names are left out: `tags.__name__` is the string `"tags"`.
    """
    names = set()
    for dotted in _backend_module_names():
        module = importlib.import_module(dotted)
        names |= {
            attribute
            for attribute, value in vars(module).items()
            if isinstance(value, str) and value in tables and not attribute.startswith("__")
        }
    return frozenset(names)


#: The builtins that compare a type and return a bool, so an entity handed to
#: one reads nothing. Python's names, not a library's.
_TYPE_TESTS: Final = frozenset({"isinstance", "issubclass"})


def _names_types(node: ast.expr) -> bool:
    """Whether a type test's second argument only names types.

    A dotted name, or a tuple or a `|` union of them: `Book`, `models.Book`,
    `(Book, Loan)`, `Book | Loan`, and `None` inside a union, as
    `Book | None` spells an optional type. Anything else is an expression that
    runs, and `type(db.query(Classification).first())` runs a query, so
    skipping it whole would hide that read from every pass.
    """
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.Tuple):
        return all(_names_types(element) for element in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _names_types(node.left) and _names_types(node.right)
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _not_a_mention(tree: ast.Module) -> set[int]:
    """The nodes a name of the entity may sit in without being a read.

    An annotation, the callee of any call, and the type a type test is handed
    when `_names_types` says it only names one.
    `Mapped[list[Classification]]` and `-> Classification` describe a type,
    `Classification(book_id=...)` builds a row in memory, and
    `isinstance(row, Classification)` answers a bool: none reaches a table.
    The callee is skipped for every call and not only a constructor, so
    `Classification.__table__.select()` is still reported, through the
    receiver the callee is an attribute of. An import binds a name and holds
    no expression, so it needs no exclusion.
    """
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            skipped.add(id(node.func))
            # The type position only, and only when it names a type. The first
            # argument is a value, and
            # `isinstance(db.query(Classification).first(), Classification)`
            # reads a row there; so does `type(db.query(Classification).first())`
            # in the second.
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in _TYPE_TESTS
                and len(node.args) > 1
                and _names_types(node.args[1])
            ):
                skipped |= {id(child) for child in ast.walk(node.args[1])}
        for annotation in (getattr(node, "annotation", None), getattr(node, "returns", None)):
            if isinstance(annotation, ast.AST):
                skipped |= {id(child) for child in ast.walk(annotation)}
    return skipped


def _enclosing_statements(tree: ast.Module) -> dict[int, ast.stmt]:
    """Which statement each node belongs to.

    So a chain spread over five lines is reported once, at the statement, and
    an allowlist entry counts a thing a person wrote rather than a line the
    formatter chose. `routers/stats.py`'s Tag index is one statement over eight
    lines and three reading calls.
    """
    owner: dict[int, ast.stmt] = {}

    def walk(node: ast.AST, statement: ast.stmt | None) -> None:
        for child in ast.iter_child_nodes(node):
            here = child if isinstance(child, ast.stmt) else statement
            if here is not None:
                owner[id(child)] = here
            walk(child, here)

    walk(tree, None)
    return owner


def _book_owned_offences(source: str, entities: frozenset[str] = BOOK_OWNED) -> list[int]:
    """Statement line numbers where this module names one of these entities.

    **`entities` defaults to `BOOK_OWNED` and the default is the rule this file
    is about.** It is a parameter because `tests/test_tags.py` asks the same
    question of the tag vocabulary, which is reachable **from** books without
    being a child **of** books, so no foreign key puts it in the set above and
    a second copy of this walk would be a second instrument to keep in step.
    Passing anything else does not widen this file's rule: the callers below
    pass nothing.

    The fourth pass, and the one the other three cannot take: they all ask
    whether a statement names `Book`, and
    `db.query(Classification.number, func.count(Classification.id))
    .group_by(Classification.number)` names no `Book` at all.

    **It asks nothing about whether the query is correct.** There is no notion
    here of a join, a scope, a viewer or a Shelf. What decides safety is the
    allowlist, and `BOOK_OWNED_READERS` says why that is so and what it costs.

    **It is keyed on this codebase's own names and on no library's.** A
    statement is reported when an expression in it names a guarded entity or
    a module level name holding a guarded table's name
    (`_table_name_aliases`), or when a string in it is SQL naming a guarded
    table (`_raw_sql_offences`). What the
    method is called plays no part, so a release of SQLAlchemy that adds,
    renames or drops one cannot move what this reports. Left out of
    "expression": an import, an annotation, and the callee of a call, which is
    a row built in memory. So a clause built as a local and applied later is
    reported where it is built, and so is every write.

    What it lets through is in the module docstring's list of blind spots.
    """
    tree = ast.parse(source)
    tables = _tables_of(entities)
    aliases = _entity_aliases(tree, entities) | _table_name_aliases(tables)
    owner = _enclosing_statements(tree)
    passed_over = _not_a_mention(tree)

    def reads(node: ast.AST) -> bool:
        if id(node) in passed_over:
            return False
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            return node.id in aliases
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            return node.attr in aliases
        return False

    offences = set(_raw_sql_offences(source, tables))
    for node in ast.walk(tree):
        if reads(node):
            statement = owner.get(id(node))
            offences.add(statement.lineno if statement is not None else getattr(node, "lineno", 0))
    return sorted(offences)


def _module_level_names(tree: ast.Module) -> set[str]:
    """Everything bound at a module's top level: imports, defs, assignments.

    What a reading call is handed resolves to an entity when it is one of these
    and to a runtime value when it is not, which is the whole of the rule below.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            names |= {alias.asname or alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _parameterised_reads(source: str) -> list[int]:
    """Statements where a query builder is handed a name bound at runtime.

    **This pass's own walk with the argument test inverted.** `_book_owned_offences`
    reports a call to `_builds_a_query` whose argument names a guarded entity; a
    call whose argument names a **local** is one this pass structurally cannot
    see, because the table is chosen when the function runs.

    **A local anywhere in an argument, not a spelling of one.** Any `Name` in
    any argument, positional or keyword, that is not bound at module level
    reports the call: `db.query(model)`, `db.query(carrier.entry)`,
    `db.query(func.count(carrier.entry))`, `select(*columns)`,
    `db.query(cols[k])` and `db.query(getattr(model, name))` alike. `Book.id`
    and `func.count(Book.id)` name only imports and are the first three
    passes' business. A module level alias such as `COL = Carrier.BOOK_TAGS.entry`
    is bound at import and is not reported.

    Over-reporting is the safe direction and is what the pinned set is for: a
    receiver that is not a `Session` lands here too, which is how `targets.py`
    arrives, and being classified by a person costs a sentence where a rule
    narrow enough to exclude it would also excuse a real one.
    """
    tree = ast.parse(source)
    bound = _module_level_names(tree)
    select_names, module_names = _sqlalchemy_names(tree)
    owner = _enclosing_statements(tree)

    def runtime(argument: ast.expr) -> bool:
        return any(isinstance(node, ast.Name) and node.id not in bound for node in ast.walk(argument))

    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _builds_a_query(node.func, select_names, module_names)):
            continue
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        if any(runtime(argument) for argument in arguments):
            statement = owner.get(id(node))
            found.add(statement.lineno if statement is not None else node.lineno)
    return sorted(found)


#: Modules a `from ... import *` can launder a predicate out of.
#:
#: Derived from `PREDICATE_IMPORTERS` rather than written down, for the reason
#: `test_reading.py` derives its own from its allowlist: the set of modules that
#: may hold a predicate **is** the set a star can carry it out of, so a third
#: entry cannot reopen the hole by being forgotten here. Measured: `dir(models)`
#: and `dir(shelf)` both contain both predicates, and neither declares `__all__`,
#: which is what makes `dir()` the right expansion. If one ever does, a star
#: binds that list instead and this over-reports rather than under-, which is the
#: safe direction for a guard.
_STAR_SOURCES = {name.removesuffix(".py") for name in PREDICATE_IMPORTERS}


def _imported_predicates(source: str) -> set[str]:
    """Which visibility predicates one module imports, whatever it calls them.

    **`alias.name`, not `alias.asname or alias.name`, and that one word is the
    rule.** The question here is "does this module reach a predicate", and the
    answer to that is the name it imported; the local alias is the answer to a
    different question, "which local names mean this thing", which is what
    `_entity_aliases` asks. Measured against the expression this replaced:
    `from models import Book, visible_to` was reported and
    `from models import visible_to as _v` was not, so one rename evaded the guard
    entirely.

    **A star import is expanded, and this file used to assert the opposite.**
    `from models import *` binds `visible_to` exactly as a named import does, so
    a rule about reaching a predicate has to see it. An earlier version of this
    helper had a fixture asserting a star reports **nothing**, which put this
    file in silent disagreement with `test_reading.py`, whose rule expands a star
    for precisely this laundering path. `test_reading.py` was right and the
    fixture here was wrong; it is now in the positive parametrisation, and what
    the expansion changed is held by
    `test_the_superseded_expression_let_the_aliases_and_the_stars_past` rather
    than counted in this paragraph.

    `test_reading.py` also keeps the local alias, because its star expansion
    binds names rather than importing them; this one has no such second use, so
    it takes `alias.name` alone. Measured on 2026-08-28 against
    `from models import UserBook as UB`: `test_reading.py:86` and
    `test_custom_fields.py:141` both report `UserBook` and are **correct as they
    stand**. This file was the only one with the `asname or name` defect.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "*":
                if node.module in _STAR_SOURCES:
                    names |= set(dir(importlib.import_module(node.module)))
                continue
            names.add(alias.name)
    return names & set(PREDICATES)


def _predicate_calls(source: str) -> set[str]:
    """Every visibility predicate this module **calls**, however it named it.

    A companion to `_imported_predicates`, and it is the half that closes
    `import models` followed by `models.visible_to(1)`: that statement imports
    the module rather than the predicate, which is legal everywhere and which
    every rule reading import statements is therefore right to let past.

    Three shapes reach a predicate and all three are resolved here:

    * `visible_to(1)`, a bare call;
    * `models.visible_to(1)`, dotted, which binds no predicate name at all;
    * `from models import visible_to as vt` then `vt(1)`, resolved through the
      import that bound it.

    **Its blind spots, listed rather than left to be found**, which is the
    contract `TestTheShelfIsTheOnlyWayIn` states for its own rules.

    **No count is written here, and that is deliberate.** This paragraph stated
    one three times and was wrong three times: 13, then 5, then 11 against a
    table of 10. The shapes are generated as a product of two tuples in
    `test_the_two_rules_together_leave_exactly_the_dotted_indirections_open`,
    and those two tuples are asserted against **literals**, so a family or a
    spelling cannot leave the table quietly. The first attempt at that guard
    compared the generated keys against the identical generating expression and
    could not fail at all.

    Four indirection families defeat this pass, because it reads the callee and
    none of them puts a predicate there: rebinding to a local
    (`vis = visible_to` then `vis(1)`), `getattr`, a dict indexed at the call
    site, and `functools.partial`. Each can be written three ways, and the
    **spelling** decides whether anything catches it:

    * `from models import visible_to`, and `from models import *`, both bind a
      predicate name, so `_imported_predicates` reports the module whatever it
      then does with it. Every indirection written either way is caught.
    * `import models` and `models.visible_to` binds no predicate name and puts
      none in a callee. **These are the four shapes that escape both rules**,
      one per family.

    So the discriminator is `import models`. Two earlier versions of this
    sentence were wrong about that: one said the rebinding was the common factor
    and only `getattr` escaped, and the next missed the star spelling entirely,
    which at the time escaped as well. The star is now expanded by
    `_imported_predicates`, which is what makes the sentence true rather than
    nearly true. The set that escapes is the `escaping` literal in that test; it
    is not repeated here, because every time it has been repeated here it has
    been wrong.

    **Do not chase the remaining four with more arms.** Every one needs the value
    tracking the guard this file replaced carried through `symtable`, and the
    open set of ways to rebind a name is the shape that took another guard here
    four rewrites. What is left uncovered is a module that imports `models` and
    then reaches a predicate through an indirection, which is several statements
    of deliberate trouble and no way to write by accident.

    **Ruff refuses the star spelling independently**, and that is a second line
    rather than the reason this rule expands it. `backend/pyproject.toml` selects
    `F`, so `from models import *` is F403 and every name reached through it is
    F405; measured on a scratch file, 3 errors. Ruff is in the gate, so that
    spelling cannot reach `main` whatever this file says. It is expanded here
    anyway, because a guard whose blind spot list is right only because another
    tool happens to be configured a certain way is a guard that goes quiet when
    somebody edits a lint config.

    What it deliberately does **not** report is prose. The substring form this
    replaced failed on a docstring sentence explaining why the Shelf is used,
    which is the opposite of what a guard should do to a comment arguing for the
    rule it enforces.
    """
    tree = ast.parse(source)
    bound = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in PREDICATES
    }
    named = set(PREDICATES) | bound
    return {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name | ast.Attribute)
    } & named


def _registry_report(
    offences: Callable[[str], list[int]], registry: dict[str, list[tuple[str, str]]], excluded: set[str]
) -> list[str]:
    """Every module whose statements this pass reports and the registry does not hold.

    Counted per module, then each entry compared with its statement by
    equality, in line order, as `BOOK_OWNED_READERS` is.
    """
    sources = {name: source for name, source in application_sources().items() if name not in excluded}
    found = {name: lines for name, source in sources.items() if (lines := offences(source))}
    report = []
    for name in sorted(set(found) | set(registry)):
        lines = found.get(name, [])
        entries = registry.get(name, [])
        if len(lines) != len(entries):
            shown = "\n".join(f"      {name}:{line}  {_statement_at(sources[name], line)}" for line in lines)
            report.append(f"  {name}: {len(lines)} statements, {len(entries)} allowed\n{shown}")
            continue
        report += [f"  {name}:{one}" for one in _entries_off_their_statements(sources[name], lines, entries)]
    return report


@pytest.fixture
def user(db) -> User:
    u = User(username="reader", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def other(db, user) -> User:
    u = User(username="stranger", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def shelved(db, user) -> Collection:
    c = Collection(name="Shelved")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _trashed(**fields) -> Book:
    return Book(deleted_at=datetime.now(UTC).replace(tzinfo=None), **fields)


class TestTheShelfIsTheOnlyWayIn:
    """House rule: the visibility predicates are applied in exactly one module."""

    def test_no_module_but_the_shelf_imports_a_visibility_predicate(self):
        """Read with `ast` rather than matched as text.

        A regex over the source has to guess at import syntax, and the first
        version of this test guessed at the multi-line form only: it caught
        `    visible_to,` in a parenthesised list and sailed straight past
        `from models import Book, visible_to` on one line.
        """
        offenders = sorted(
            f"{name}:{predicate}"
            for name, source in application_sources().items()
            if name not in PREDICATE_IMPORTERS
            for predicate in _imported_predicates(source)
        )
        assert offenders == [], (
            f"These modules import a visibility predicate instead of asking the Shelf for one: {offenders}"
        )

    def test_no_module_but_the_shelf_builds_a_query_over_books(self):
        """The half that catches a query with no predicate at all, rather than
        one that imported the wrong thing."""
        offenders = sorted(
            f"{name}:{line}"
            for name, source in application_sources().items()
            if name not in QUERY_BUILDERS
            for line in _query_offences(source)
        )
        assert offenders == [], f"These statements build a query over books outside the Shelf: {offenders}"

    def test_only_the_named_exception_reaches_books_through_a_join(self):
        """The blind spot the old guard documented and this rule closes.

        A query rooted at another table that reaches `books` through
        `.join(Book, ...)` names no `Book` in `query()`, so a rule reading the
        arguments alone never sees it, whatever it selects. Measured over the
        tree, exactly one module takes that shape.
        """
        offenders = sorted(
            f"{name}:{line}"
            for name, source in application_sources().items()
            if name not in QUERY_BUILDERS | JOIN_CALLERS
            for line in _join_offences(source)
        )
        assert offenders == [], f"These statements reach books through a join outside the Shelf: {offenders}"

    def test_only_the_counted_calls_hand_the_book_entity_to_a_call(self):
        """The by key read, which neither pass above sees.

        `db.get_one(Book, book_id)` neither builds a query nor joins one, so
        the three importers' loads were on no list. Each is an entry with the
        reason its id is safe.
        """
        sources = application_sources()
        found = {
            name: keys
            for name, source in sorted(sources.items())
            if name not in QUERY_BUILDERS
            if (keys := [key for _, key in _whole_book_calls(source)])
        }
        allowed = {name: [key for key, _ in entries] for name, entries in WHOLE_BOOK_READERS.items()}
        assert found == allowed, (
            "A call outside the Shelf is handed `Book` itself. Say where its key "
            "came from in WHOLE_BOOK_READERS, keyed as printed here, or ask the "
            f"Shelf or `dependencies.py` for the Book instead: {found}"
        )

    def test_a_by_key_read_is_reported_and_a_column_or_a_new_row_is_not(self):
        """The one fact the walk rests on, against statements built here."""
        source = (
            "from models import Book\n"
            "def f(db, book_id):\n"
            "    db.add(Book(title='x'))\n"
            "    db.query(Loan).filter(Loan.book_id == Book.id)\n"
            "    return db.get(Book, book_id)\n"
        )
        assert _whole_book_calls(source) == [(5, "f: db.get(Book, book_id)")]

    def test_only_the_counted_statements_hold_sql_naming_books(self):
        """Raw SQL over `books` itself, which no other pass reads.

        The qualified column shape reads `"books.location"` and leaves out
        `"books.id"`: every child spells its foreign key that way, and each is
        a declaration.
        """
        report = _registry_report(
            lambda source: _raw_sql_offences(source, frozenset({"books"}), key_columns=False),
            BOOKS_SQL_READERS,
            QUERY_BUILDERS,
        )
        assert not report, (
            "A statement holds SQL naming `books`, and either is not in BOOKS_SQL_READERS or is not the "
            "statement its entry was written for.\n\n" + "\n".join(report) + "\n\n  Raw SQL over `books` "
            "has no privacy predicate unless you wrote one. Ask `Shelf` for the rows instead; if the "
            "statement reads no Book's data, add it to BOOKS_SQL_READERS with the reason."
        )

    def test_sql_naming_a_table_is_read_wherever_the_string_sits(self):
        """The one fact the raw SQL arm rests on: a string is read as SQL by its
        own grammar, not by the call it is handed to.

        The constant, the comma join and the schema qualified name are the three
        an earlier arm missed, because it read only a string inside a call and
        only a name straight after a keyword; the lower case subquery and the
        capitals are what an upper case arm missed. A log line and an error
        that read as a fragment are refused, the price `_raw_sql_naming`
        names. A route's description holds no keyword after its verb and is
        not SQL.
        """
        books = frozenset({"books"})
        constant = (
            'LOCATIONS = "SELECT location, count(*) FROM books GROUP BY location"\n'
            "def f(db):\n"
            "    return db.execute(text(LOCATIONS)).all()\n"
        )
        comma = (
            'def f(db):\n    return db.execute(text("SELECT c.number FROM classifications c, books")).all()\n'
        )
        qualified = 'def f(db):\n    return db.execute(text("select location from public.books")).all()\n'
        lowercase = (
            "def f(db, n):\n"
            '    return db.query(Loan).filter(text("book_id in (select id from books where location = :n)"))'
            "\n"
        )
        capitals = 'def f(db):\n    return db.execute(text("SELECT LOCATION FROM BOOKS")).all()\n'
        english = (
            "def f(n):\n"
            '    logger.info("dropped %d rows from books", n)\n'
            '    raise HTTPException(422, "cannot write into books")\n'
        )
        description = 'CREATE = Query(description="Create the file\'s tags and put them on the books")\n'
        assert _raw_sql_offences(constant, books) == [1]
        assert _raw_sql_offences(comma, books) == [2]
        assert _raw_sql_offences(qualified, books) == [2]
        assert _raw_sql_offences(lowercase, books) == [2]
        assert _raw_sql_offences(capitals, books) == [2]
        assert _raw_sql_offences(english, books) == [2, 3]
        assert _raw_sql_offences(description, books) == []

    def test_a_table_looked_up_by_name_is_read_and_a_name_used_as_a_key_is_not(self):
        """The bare table name, at the two positions a table is looked up by.

        A subscript's key and a call's first argument reach a table with no
        entity and no SQL. A dict key in a literal, a list element and a
        subscript being written to read nothing.
        """
        tables = frozenset({"classifications"})
        looked_up = (
            "def f(db):\n"
            '    a = Base.metadata.tables["classifications"]\n'
            '    b = table("classifications", column("number"))\n'
            '    c = Table("classifications", MetaData(), autoload_with=db.bind)\n'
        )
        keys = (
            "def f(n):\n"
            '    seen = {"classifications": n}\n'
            '    router = APIRouter(tags=["classifications"])\n'
            '    restored["classifications"] = n\n'
        )
        assert _raw_sql_offences(looked_up, tables) == [2, 3, 4]
        assert _raw_sql_offences(keys, tables) == []

    def test_only_the_counted_statements_reach_books_through_a_relationship(self):
        """A relationship into `Book`, named off the class that owns it.

        `join(User.books_added)` and `Loan.book.has(...)` reach `books` and
        name no `Book` where passes 2 and 3 look. `JOIN_CALLERS` is not
        excluded here, so its module's one such statement is registered.
        """
        report = _registry_report(_relationship_offences, RELATIONSHIP_READERS, QUERY_BUILDERS)
        assert not report, (
            "A statement names a relationship into `Book` off its owning class, and either is not in "
            "RELATIONSHIP_READERS or is not the statement its entry was written for.\n\n"
            + "\n".join(report)
            + "\n\n  A join or an EXISTS through one of these reads every member's Books, Private ones "
            "included. Ask `Shelf` for the rows instead; if the statement reads no Book, add it to "
            "RELATIONSHIP_READERS with the reason."
        )

    def test_a_relationship_off_its_class_is_reported_and_off_an_instance_is_not(self):
        """The one fact the relationship pass rests on, against statements built here."""
        source = (
            "import models\n"
            "from models import Loan, User\n"
            "def f(db, loan, x):\n"
            "    db.query(User.username, func.count()).join(User.books_added).all()\n"
            "    db.query(func.count(Loan.id)).filter(Loan.book.has(title=x)).scalar()\n"
            "    db.query(Loan).join(models.Loan.book).all()\n"
            "    print(loan.book.title)\n"
            "    db.query(Loan).join(Loan.loaned_to).all()\n"
        )
        assert _relationship_offences(source) == [4, 5, 6]

    def test_a_list_of_books_read_off_any_instance_is_reported(self):
        """A to many relationship into `Book` loads every Book it collects,
        whoever's they are, so the instance spelling counts for it; the scalar
        `loan.book` reaches one Book its row already names, and does not.

        The keys are the models' own, so the set holding both of today's is
        what says the derivation reads them rather than nothing.
        """
        assert {"books", "books_added"} <= TO_MANY_INTO_BOOK
        source = (
            "def f(collection, user, loan):\n"
            "    shown = len(collection.books)\n"
            "    titles = [b.title for b in user.books_added]\n"
            "    print(loan.book.title)\n"
        )
        assert _relationship_offences(source) == [2, 3]

    def test_a_type_test_passes_over_its_type_and_reads_its_value(self):
        """`isinstance` answers a bool about its second argument, and its first
        is any expression, a query among them. The second is passed over only
        while it names types: a query inside `type()` there runs too."""
        source = (
            "import models\n"
            "from models import Classification\n"
            "def f(db, row):\n"
            "    isinstance(row, Classification)\n"
            "    isinstance(db.query(Classification).first(), Classification)\n"
            "    isinstance(row, type(db.query(Classification).first()))\n"
            "    isinstance(row, (Classification, models.Classification))\n"
            "    issubclass(type(row), Classification | models.Classification)\n"
            "    isinstance(row, Classification | None)\n"
            "    isinstance(row, type(db.query(Classification).first()) | None)\n"
        )
        assert _book_owned_offences(source) == [5, 6, 10]

    def test_only_the_counted_statements_read_a_table_that_belongs_only_to_a_book(self):
        """The fourth pass, over the tables the three above structurally cannot
        see.

        `classifications`, `custom_field_values` and `book_tags` carry no
        member, so their privacy is entirely the Book's, and a query over one
        of them names no `Book` anywhere. An index is the shape that matters:
        "every DDC number in the library, with a count" publishes what is on
        every member's Private Books without returning one.

        **Every read is reported and the allowlist is what decides.** The
        failure message is the documentation most people will meet, so it
        carries the reason and the next step rather than a verdict.
        """
        sources = {
            name: source for name, source in application_sources().items() if name not in QUERY_BUILDERS
        }
        found = {name: _book_owned_offences(source) for name, source in sources.items()}
        found = {name: lines for name, lines in found.items() if lines}
        allowed = {name: len(entries) for name, entries in BOOK_OWNED_READERS.items()}
        counted = {name: len(lines) for name, lines in found.items()}

        report = []
        for name in sorted(set(found) | set(allowed)):
            lines = found.get(name, [])
            entries = BOOK_OWNED_READERS.get(name, [])
            body = sources.get(name, "").splitlines()
            if len(lines) != len(entries):
                # **The statement as an entry has to carry it**, flattened, not
                # the raw first line: this is the branch a new read arrives in,
                # and what it prints is what the person has to paste into the
                # table. A truncated source line was enough while an entry was a
                # fragment somebody picked out of it.
                shown = [
                    f"      {name}:{line}  {_statement_at(sources.get(name, ''), line)}"
                    for line in lines
                    if line - 1 < len(body)
                ]
                report.append(
                    f"  {name}: {len(lines)} reading statements, {len(entries)} allowed\n" + "\n".join(shown)
                )
                continue
            # The entries are positional, in line order, and each is keyed on
            # the whole statement rather than on a fragment of it, so a reason
            # cannot drift out from under the statement it describes as the
            # module is edited.
            report += [
                f"  {name}:{one}"
                for one in _entries_off_their_statements(sources.get(name, ""), lines, entries)
            ]
        if not report and counted == allowed:
            return

        raise AssertionError(
            "A statement reads a table that belongs only to a Book, and either "
            "is not on the allowlist or is not the statement the entry "
            "describing it was written for.\n\n"
            + "\n".join(report)
            + f"\n\n  The tables are {', '.join(sorted(BOOK_OWNED))}. They carry no "
            "member of their own, so nothing in a row says who may read it: the "
            "answer is whoever may read its Book. Publishing a set of values out "
            'of one of them ("every DDC number in the library, with a count") '
            "discloses what is on other members' Private Books without ever "
            "returning one.\n\n"
            "  This rule reports every read and asks nothing about whether yours "
            "is scoped or joined. Five versions that did ask were each shown to "
            "leak by the next review round, so the judgement is a person's and it "
            "is recorded once.\n\n"
            "  If your query is genuinely safe, and the usual reason is that it "
            "is scoped to Books somebody already resolved, add an entry to "
            "BOOK_OWNED_READERS in this file: the statement, exactly as printed "
            "above, and why it is safe. The entries are in line order and are "
            "keyed on the whole statement, so moving a statement means moving "
            "its entry and editing one means re-reading its reason. The comment "
            "block above the list is the checklist, including the four join "
            "spellings that look correct and are not. If you cannot write the "
            "reason in a sentence, change the query rather than the list."
        )

    def test_an_entry_is_keyed_on_its_whole_statement_and_not_a_token_in_it(self):
        """Equality, asserted against the comparison rather than against the table.

        The table is what the assertion above reads, so a fragment cannot be
        demonstrated by editing it. This hands the comparison a statement and
        two keys: the token a fragment would have been, and the statement.

        **What the containment check accepted is the point.** The fixture drops
        the narrowing and keeps the token, which is the shape a leak takes:
        measured on `routers/books.py` by deleting
        `.filter(DigitalReference.book_id == book.id)` from the per book
        reference count, the old check stayed green and this one names the line.
        Ambiguity was the smaller half: 1 of the 17 entries was a fragment of a
        second statement as well as of its own, `func.count(DigitalReference.id)`.
        """
        narrowed = (
            "def f(db, book):\n"
            "    return (\n"
            "        db.query(func.count(Reference.id))\n"
            "        .filter(Reference.book_id == book.id)\n"
            "        .scalar()\n"
            "    )\n"
        )
        widened = "def f(db, book):\n    return db.query(func.count(Reference.id)).scalar()\n"
        token = "func.count(Reference.id)"
        statement = _statement_at(narrowed, 2)
        assert token in statement
        assert token in _statement_at(widened, 2)

        assert _entries_off_their_statements(narrowed, [2], [(token, "why")])
        assert not _entries_off_their_statements(narrowed, [2], [(statement, "why")])
        # The entry written for the narrowed statement, against the widened one.
        assert _entries_off_their_statements(widened, [2], [(statement, "why")])

    #: Shapes that must be reported, and by which rule.
    #:
    #: **Asserted per rule, not with `or`.** The first version of this test used
    #: `not (_query_offences(...) or _join_offences(...))`, and its join fixture
    #: also named `Book.title` inside `query()`, so the query rule alone
    #: satisfied it: `_join_offences` could have been deleted outright and this
    #: test plus the whole-tree one would both still have passed. A rule with no
    #: test that fails when it is removed is not enforced.
    EVASIONS = {
        "join only": (
            "from models import Book, Loan\n"
            "def f(db):\n"
            "    return db.query(Loan).join(Book, Loan.book_id == Book.id).all()\n",
            "join",
        ),
        "outer join": (
            "from models import Book, Loan\n"
            "def f(db):\n"
            "    return db.query(Loan).outerjoin(Book, Loan.book_id == Book.id).all()\n",
            "join",
        ),
        "join by keyword": (
            "from models import Book, Loan\n"
            "def f(db):\n"
            "    return db.query(Loan).join(target=Book, onclause=Loan.book_id == Book.id).all()\n",
            "join",
        ),
        "qualified name": (
            "import models\ndef f(db):\n    return db.query(models.Book.location).all()\n",
            "query",
        ),
        "import alias": (
            "from models import Book as B\ndef f(db):\n    return db.query(B.location).all()\n",
            "query",
        ),
        "rebound name": (
            "from models import Book\nM = Book\ndef f(db):\n    return db.query(M).all()\n",
            "query",
        ),
        "aliased entity": (
            "from sqlalchemy.orm import aliased\n"
            "from models import Book\n"
            "E = aliased(Book)\n"
            "def f(db):\n    return db.query(E).all()\n",
            "query",
        ),
        "sqlalchemy select": (
            "import sqlalchemy as sa\n"
            "from models import Book\n"
            "def f(db):\n    return db.execute(sa.select(Book.location)).all()\n",
            "query",
        ),
        "select_from": (
            "from models import Book, Tag\n"
            "def f(db):\n    return db.query(Tag.name).select_from(Book).all()\n",
            "query",
        ),
        "with_entities": (
            "from models import Book, Loan\n"
            "def f(db):\n    return db.query(Loan).with_entities(Book.location).all()\n",
            "query",
        ),
        "join_from": (
            "import sqlalchemy as sa\n"
            "from models import Book, Loan\n"
            "def f(db):\n    return db.execute(sa.select(Loan.id).join_from(Loan, Book)).all()\n",
            "join",
        ),
        "annotated rebinding": (
            "from typing import Any\n"
            "from models import Book\n"
            "M: Any = Book\n"
            "def f(db):\n    return db.query(M.location).all()\n",
            "query",
        ),
        "annotated aliased entity": (
            "from typing import Any\n"
            "from sqlalchemy.orm import aliased\n"
            "from models import Book\n"
            "E: Any = aliased(Book)\n"
            "def f(db):\n    return db.query(E).all()\n",
            "query",
        ),
        "tuple rebinding": (
            "from models import Book, Tag\n"
            "M, N = Book, Tag\n"
            "def f(db):\n    return db.query(M.location).all()\n",
            "query",
        ),
        "aliased by keyword": (
            "from sqlalchemy.orm import aliased\n"
            "from models import Book\n"
            "E = aliased(element=Book)\n"
            "def f(db):\n    return db.query(E).all()\n",
            "query",
        ),
        "add_columns": (
            "from models import Book, Loan\n"
            "def f(db):\n    return db.query(Loan.id).add_columns(Book.location).all()\n",
            "query",
        ),
        "add_entity": (
            "from models import Book, Loan\ndef f(db):\n    return db.query(Loan).add_entity(Book).all()\n",
            "query",
        ),
        "outerjoin_from": (
            "import sqlalchemy as sa\n"
            "from models import Book, Loan\n"
            "def f(db):\n"
            "    return db.execute(\n"
            "        sa.select(Loan.id).outerjoin_from(Loan, Book, Loan.book_id == Book.id)\n"
            "    ).all()\n",
            "join",
        ),
        "qualified aliased": (
            "from sqlalchemy import orm\n"
            "from models import Book\n"
            "E = orm.aliased(Book)\n"
            "def f(db):\n    return db.query(E).all()\n",
            "query",
        ),
        "qualified rebinding": (
            "import models\nM = models.Book\ndef f(db):\n    return db.query(M.location).all()\n",
            "query",
        ),
        "select under an import alias": (
            "from sqlalchemy import select as sel\n"
            "from models import Book\n"
            "def f(db):\n    return db.execute(sel(Book.location)).all()\n",
            "query",
        ),
        "select from a package submodule": (
            "from sqlalchemy.sql import select\n"
            "from models import Book\n"
            "def f(db):\n    return db.execute(select(Book.location).distinct()).all()\n",
            "query",
        ),
        "dotted sqlalchemy receiver": (
            "import sqlalchemy.sql\n"
            "from models import Book\n"
            "def f(db):\n"
            "    return db.execute(sqlalchemy.sql.select(Book.location)).all()\n",
            "query",
        ),
    }

    @pytest.mark.parametrize("shape", sorted(EVASIONS))
    def test_the_rule_catches_the_shapes_that_defeated_its_earlier_versions(self, shape):
        """Every shape below was measured passing some earlier version of this
        rule clean, and each is a location or author index publishing a name and
        a count over every Member's Private Books.

        **The table below is the count**, and
        `test_the_evasion_table_counts_what_the_dict_holds` derives it from the
        dict rather than trusting it. Three review rounds in a row found a
        stated total disagreeing with this table or with `len(EVASIONS)`, so
        the number is no longer written anywhere a person has to remember to
        update.

        | Round | What broke the rule that round | Shapes |
        |---|---|---|
        | 1 | the two regexes both critics broke | 4 |
        | 2 | the `ast` pass that replaced them | 5 |
        | 3 | alias resolution, verifying shapes already listed | 0 |
        | 4 | `with_entities` and `join_from`, plus five binding forms | 7 |
        | 5 | `add_columns`, `add_entity`, `outerjoin_from` | 3 |
        | 6 | `qualified rebinding`, found by mutating the resolver | 1 |
        | 7 | `select under an import alias`, moved off the blind spots | 1 |
        | 8 | the package matched by string rather than by prefix | 2 |

        This paragraph said **sixteen** while the table below it summed to
        nineteen, because round 5 added three shapes and left the sentence
        alone. Recounted rather than adjusted, which is the standing rule here
        for a comment that claims "there are exactly N".

        **Round 6 came from attacking the rule, not reading it.** `M =
        models.Book` is resolved by `_names_entity`'s attribute arm, and
        nothing failed when that arm was reverted to a bare `Book` check: every
        listed shape wrote the rebinding unqualified, so a correct half of the
        resolver was untested. `_mentions_entity` has its own attribute arm and
        covered the direct `db.query(models.Book.location)` spelling, which is
        what made the gap invisible.

        **Round 7 is a blind spot that stopped being one.** `from sqlalchemy
        import select as sel` was listed as not caught, on the reasoning that
        resolving the function name would double the resolver to guard a
        spelling the tree does not use. `_sqlalchemy_names` is eight lines and
        is shared with the fourth pass, where the same hard-coded list was
        worse than a miss: it read `sq.select(...)` as the **Shelf's** method
        and forgave it. A listed blind spot is a claim about cost, and a cost
        is worth re-measuring when a second caller appears.

        **Round 8 is round 7 not going far enough**, which is this file's
        oldest mistake wearing new clothes. Resolving the alias but matching
        the package by string left `from sqlalchemy.sql import select` and
        `from sqlalchemy.future import select` clean on every pass, and
        `import sqlalchemy.sql as sq` forgiven as a Shelf, one round after that
        exact licence was written up as the reason not to hard-code a list.
        `select` is re-exported from several modules of one package, and
        `notifications.py` and `models.py` both already import from
        `sqlalchemy.sql.elements`. Matched by prefix now, and
        `_rooted_at_module` walks a dotted receiver to its root so
        `sqlalchemy.sql.select(...)` is caught with the other three rather than
        left as the next round's finding.

        Round 4's seven: `with_entities`, `join_from`, `annotated rebinding`,
        `annotated aliased entity`, `tuple rebinding`, `qualified aliased`,
        `aliased by keyword`.

        **Round 5 is rounds 2 and 4 repeating**, and is the reason
        `_QUERY_BUILDERS` and `_JOIN_METHODS` are now named frozensets with the
        rule written on them. Each earlier round fixed the method it was shown
        and left that method's siblings: `outerjoin` was added while
        `outerjoin_from` was not, `with_entities` while `add_columns` and
        `add_entity` were not. Fix the family, not the instance.

        Two of them are the same lesson twice, and it is the one worth keeping:
        `select_from` in round 2 and `with_entities` in round 4 are both
        spellings **this module uses in its own body**, `Shelf.select()` and
        `Shelf.count()` respectively. A seam that teaches a spelling has to
        catch that spelling, or the diff teaches the evasion it exists to
        prevent. The first was fixed as an instance; the class was missed and
        cost another round.
        """
        source, rule = self.EVASIONS[shape]
        reported = {"query": _query_offences, "join": _join_offences}[rule](source)
        assert reported, f"{shape} evades the {rule} rule"

    def test_the_rule_does_not_report_the_shelfs_own_callers(self):
        """`shelf.select(Book.author)` is the seam being used correctly, and an
        earlier version of this rule reported every one of them."""
        correct = (
            "from models import Book\n"
            "from shelf import Shelf\n"
            "def f(db, uid):\n"
            "    return Shelf.seen_by(db, uid).select(Book.author).all()\n"
        )
        assert _query_offences(correct) == []
        assert _join_offences(correct) == []

    #: Index shapes over a book-owned table, none of which names `Book`.
    #:
    #: Every one is "every heading in the library, with a count" in a different
    #: spelling, and every one is invisible to the three passes above: the
    #: parametrised test below asserts that invisibility as well as the catch,
    #: because a shape the old rules already caught would prove nothing about
    #: the new one. That is the mistake this file made once with `_join_offences`,
    #: whose fixture also named `Book` inside `query()`.
    BOOK_OWNED_EVASIONS = {
        "index with a count": (
            "from sqlalchemy import func\n"
            "from models import Classification\n"
            "def f(db):\n"
            "    return (db.query(Classification.number, func.count(Classification.id))\n"
            "        .group_by(Classification.number).all())\n"
        ),
        "distinct column": (
            "from sqlalchemy import select\n"
            "from models import Classification\n"
            "def f(db):\n"
            "    return db.execute(select(Classification.number).distinct()).all()\n"
        ),
        "whole entity, counted in python": (
            "from collections import Counter\n"
            "from models import Classification\n"
            "def f(db):\n"
            "    return Counter(c.number for c in db.query(Classification).all())\n"
        ),
        "join from another table": (
            "from sqlalchemy import func\n"
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return (db.query(Tag.name, func.count())\n"
            "        .join(book_tags, book_tags.c.tag_id == Tag.id)\n"
            "        .group_by(Tag.name).all())\n"
        ),
        "outer join from another table": (
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return db.query(Tag.name).outerjoin(book_tags, book_tags.c.tag_id == Tag.id).all()\n"
        ),
        "core select on the association table": (
            "from models import book_tags\ndef f(db):\n    return db.execute(book_tags.select()).all()\n"
        ),
        "select_from": (
            "from models import Classification, Tag\n"
            "def f(db):\n    return db.query(Tag.name).select_from(Classification).all()\n"
        ),
        "with_entities": (
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return db.query(Tag).with_entities(book_tags.c.tag_id).all()\n"
        ),
        "add_columns": (
            "from models import Classification, Tag\n"
            "def f(db):\n"
            "    return db.query(Tag.id).add_columns(Classification.number).all()\n"
        ),
        "add_entity": (
            "from models import Classification, Tag\n"
            "def f(db):\n    return db.query(Tag).add_entity(Classification).all()\n"
        ),
        "sqlalchemy select": (
            "import sqlalchemy as sa\n"
            "from models import CustomFieldValue\n"
            "def f(db):\n"
            "    return db.execute(sa.select(CustomFieldValue.value)).all()\n"
        ),
        "join_from": (
            "import sqlalchemy as sa\n"
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return db.execute(sa.select(Tag.id).join_from(Tag, book_tags)).all()\n"
        ),
        "outerjoin_from": (
            "import sqlalchemy as sa\n"
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return db.execute(\n"
            "        sa.select(Tag.id).outerjoin_from(Tag, book_tags)\n"
            "    ).all()\n"
        ),
        "import alias": (
            "from models import Classification as C\n"
            "def f(db):\n    return db.query(C.number).distinct().all()\n"
        ),
        "qualified name": (
            "import models\ndef f(db):\n    return db.query(models.Classification.number).all()\n"
        ),
        "rebound name": (
            "from models import Classification\n"
            "M = Classification\n"
            "def f(db):\n    return db.query(M.number).all()\n"
        ),
        "annotated rebinding": (
            "from typing import Any\n"
            "from models import Classification\n"
            "M: Any = Classification\n"
            "def f(db):\n    return db.query(M.number).all()\n"
        ),
        "aliased entity": (
            "from sqlalchemy.orm import aliased\n"
            "from models import Classification\n"
            "E = aliased(Classification)\n"
            "def f(db):\n    return db.query(E).all()\n"
        ),
        "join by keyword": (
            "from models import Classification, Tag\n"
            "def f(db):\n"
            "    return db.query(Tag).join(target=Classification, onclause=Tag.id == 1).all()\n"
        ),
        "qualified rebinding": (
            "import models\nM = models.Classification\ndef f(db):\n    return db.query(M.number).all()\n"
        ),
        # Round 7. Written through the door this rule tells authors to use, and
        # measured leaking against a real database rather than argued from the
        # source: `FROM books, classifications` with no join condition, so Bob
        # reads the DDC number of Alice's Private Book.
        "unjoined shelf select": (
            "from sqlalchemy import func\n"
            "from models import Classification\n"
            "def f(shelf):\n"
            "    return (shelf.select(Classification.number, func.count())\n"
            "        .group_by(Classification.number).all())\n"
        ),
        "a bare shelf select and nothing else": (
            "from models import Classification\n"
            "def f(shelf):\n    return shelf.select(Classification.number).all()\n"
        ),
        "unjoined shelf select through with_entities": (
            "from models import Book, Classification\n"
            "def f(shelf):\n"
            "    return shelf.select(Book.id).with_entities(Classification.number).all()\n"
        ),
        "core select through __table__": (
            "from models import Classification\n"
            "def f(db):\n"
            "    return db.execute(Classification.__table__.select()).all()\n"
        ),
        "__table__ rebinding": (
            "from models import CustomFieldValue\n"
            "T = CustomFieldValue.__table__\n"
            "def f(db):\n    return db.execute(T.select()).all()\n"
        ),
        "sqlalchemy under another module alias": (
            "import sqlalchemy as sq\n"
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return db.execute(sq.select(Tag.id).join_from(Tag, book_tags)).all()\n"
        ),
        # Round 8. `select` is re-exported from several modules of one package,
        # and a submodule import is already an idiom here.
        "select from a package submodule": (
            "from sqlalchemy.future import select\n"
            "from models import Classification\n"
            "def f(db):\n"
            "    return db.execute(select(Classification.label).distinct()).all()\n"
        ),
        "package submodule under an alias": (
            "import sqlalchemy.sql as sq\n"
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return db.execute(sq.select(Tag.id).join_from(Tag, book_tags)).all()\n"
        ),
        "dotted sqlalchemy receiver": (
            "import sqlalchemy.sql\n"
            "from models import Tag, book_tags\n"
            "def f(db):\n"
            "    return db.execute(\n"
            "        sqlalchemy.sql.select(Tag.id).join_from(Tag, book_tags)\n"
            "    ).all()\n"
        ),
        # Round 9. A join that is present and reaches nothing, and two shapes
        # that pin how `read` is compared against `joined`. All three were
        # clean, and none was named anywhere.
        "a join that does not reach books": (
            "from models import Book, Classification, Tag\n"
            "def f(shelf):\n"
            "    return (shelf.select(Classification.number)\n"
            "        .join(Classification, Tag.id == Book.id).all())\n"
        ),
        "a join whose target is not the entity read": (
            "from models import Classification, Tag\n"
            "def f(shelf):\n"
            "    return (shelf.select(Classification.number)\n"
            "        .join(Tag, Tag.id == Classification.id).all())\n"
        ),
        # One expression naming two entities, one joined and one not. The
        # shape matters: with the two in separate arguments, comparing by
        # intersection and comparing by subset give the same answer, so a
        # fixture written that way pins neither.
        # Round 10. A bare `db.query` joined to `books` correctly, and
        # therefore with no privacy predicate anywhere: the `list_tags`
        # disclosure in its original form. It was found by a mutation that
        # showed the rootedness test had stopped being pinned by anything;
        # that test is gone now and the shape is still worth holding.
        "a bare query joined to books, with no predicate": (
            "from sqlalchemy import func\n"
            "from models import Book, Tag, book_tags\n"
            "def f(db):\n"
            "    return (db.query(Tag.name, func.count())\n"
            "        .join(book_tags, book_tags.c.book_id == Book.id)\n"
            "        .group_by(Tag.name).all())\n"
        ),
        # Round 11. The onclause names the entity and `Book` and relates
        # neither: `classifications.id = books.id` reads whichever rows happen
        # to collide, which against a two-Book database is Alice's Private one.
        # Both critic seats reached this independently.
        "an onclause that names both and relates neither": (
            "from models import Book, Classification\n"
            "def f(shelf):\n"
            "    return (shelf.select(Classification.number)\n"
            "        .join(Classification, Classification.id == Book.id).all())\n"
        ),
        # The other half of the same rule, and it was unpinned: no fixture
        # named the entity's key in an onclause without also naming `Book`.
        "an onclause that names the key and relates to another table": (
            "from models import Classification, Tag\n"
            "def f(shelf):\n"
            "    return (shelf.select(Classification.number)\n"
            "        .join(Classification, Classification.book_id == Tag.id).all())\n"
        ),
        # Round 11 also. A narrowing clause reads the table as surely as the
        # SELECT list does, one value at a time, and `.like` enumerates.
        "a filter oracle on a shelf select": (
            "from models import Book, Classification\n"
            "def f(shelf):\n"
            "    return (shelf.select(Book.title)\n"
            '        .filter(Classification.number == "616.89").all())\n'
        ),
        "a filter oracle with no viewer at all": (
            "from models import Classification, Tag\n"
            "def f(db):\n"
            '    return db.query(Tag.name).filter(Classification.number.like("6%")).all()\n'
        ),
        # Round 12. `filter` and `order_by` were pinned by the two above;
        # `having` and `group_by` were not, because every other fixture that
        # used them also named the entity somewhere a different method would
        # catch. Removing the pair from the derived set left the suite green.
        # These two mention a guarded entity **only** inside the clause named.
        "a having clause and nothing else": (
            "from sqlalchemy import func\n"
            "from models import Book, Classification\n"
            "def f(shelf):\n"
            "    return (shelf.select(func.count())\n"
            "        .group_by(Book.id)\n"
            '        .having(Classification.number == "616.89").all())\n'
        ),
        "a group_by clause and nothing else": (
            "from sqlalchemy import func\n"
            "from models import Classification\n"
            "def f(shelf):\n"
            "    return (shelf.select(func.count())\n"
            "        .group_by(Classification.number).all())\n"
        ),
        "an order_by that reaches the table": (
            "from models import Book, Classification\n"
            "def f(shelf):\n"
            "    return shelf.select(Book.title).order_by(Classification.number).all()\n"
        ),
        "join_from re-roots the chain off books": (
            "from models import Tag, book_tags\n"
            "def f(shelf):\n"
            "    return shelf.select(Tag.name).join_from(Tag, book_tags).all()\n"
        ),
        "one expression, only one of its entities joined": (
            "from sqlalchemy import func\n"
            "from models import Book, Classification, CustomFieldValue\n"
            "def f(shelf):\n"
            "    return (shelf.select(\n"
            "        func.coalesce(CustomFieldValue.value, Classification.label))\n"
            "        .join(Classification, Classification.book_id == Book.id).all())\n"
        ),
        # Raw SQL, in the three spellings the first raw arm missed, and the two
        # names for a table that are not its entity: the name constant
        # `custom_fields` publishes, and a qualified column.
        "raw SQL held in a module constant": (
            'HEADINGS = "SELECT number, count(*) FROM classifications GROUP BY number"\n'
            "def f(db):\n"
            "    return db.execute(text(HEADINGS)).all()\n"
        ),
        "raw SQL with a comma join": (
            "def f(db):\n"
            '    sql = "SELECT c.number FROM books b, classifications c WHERE c.book_id = b.id"\n'
            "    return db.execute(text(sql)).all()\n"
        ),
        "raw SQL naming a schema qualified table": (
            'def f(db):\n    return db.execute(text("SELECT number FROM public.classifications")).all()\n'
        ),
        "the table reached by the name constant": (
            "import custom_fields\n"
            "from database import Base\n"
            "def f(db):\n"
            "    values = Base.metadata.tables[custom_fields.VALUES_TABLE]\n"
            "    query = select(values.c.field_id, func.count()).group_by(values.c.field_id)\n"
            "    return db.execute(query).all()\n"
        ),
        "a qualified column as a string": (
            'def f(db):\n    return db.execute(select(literal_column("classifications.number"))).all()\n'
        ),
    }

    @pytest.mark.parametrize("shape", sorted(BOOK_OWNED_EVASIONS))
    def test_the_fourth_pass_catches_an_index_over_a_book_owned_table(self, shape):
        """Each shape publishes a heading, a value or a tag over every Member's
        Private Books.

        Most name no `Book` at all. The three round 9 added do, in a join or an
        onclause, which is the point of them: naming `Book` somewhere is not
        the same as reaching `books`. The assertion below is what keeps that
        honest, by requiring every fixture here to be invisible to the three
        passes that do look for `Book`.
        """
        source = self.BOOK_OWNED_EVASIONS[shape]
        assert _book_owned_offences(source), f"{shape} evades the book-owned rule"
        assert _query_offences(source) == [], (
            f"{shape} is caught by an older pass, so it proves nothing about the fourth one"
        )
        assert _join_offences(source) == [], (
            f"{shape} is caught by an older pass, so it proves nothing about the fourth one"
        )

    def test_the_evasion_table_counts_what_the_dict_holds(self):
        """The round table in the docstring above is prose that claims a total.

        Three review rounds in a row found that total disagreeing with either
        the table under it or the dict itself, each time because a round added
        shapes and left a sentence alone. Parsed and compared rather than
        proof-read, which is the only fix that survives a fourth round.
        """
        docstring = self.test_the_rule_catches_the_shapes_that_defeated_its_earlier_versions.__doc__ or ""
        table = re.findall(r"^\s*\|\s*(\d+)\s*\|.*?\|\s*(\d+)\s*\|\s*$", docstring, re.MULTILINE)
        assert table, "the round table is gone from the docstring"
        assert [int(r) for r, _ in table] == list(range(1, len(table) + 1)), (
            f"the rounds are not numbered 1..N: {[r for r, _ in table]}"
        )
        assert sum(int(n) for _, n in table) == len(self.EVASIONS), (
            f"the table claims {sum(int(n) for _, n in table)} shapes and the dict holds {len(self.EVASIONS)}"
        )

    def test_a_correct_index_through_the_shelf_is_reported_too(self):
        """The cost of the rule, asserted rather than left in a comment.

        Both of these are correct. The FROM is the filtered `books`, the join
        is on the association table's foreign key, and neither can return a row
        of an invisible Book. Both are reported, and both are on the allowlist
        with that written beside them.

        **This test exists so the cost cannot be quietly removed.** The
        instinct on reading the rule is to make it recognise these two, and
        that instinct is what produced five versions, each shown to leak by the
        next review round. If somebody makes them pass, this fails and they
        have to come and argue with the table in `BOOK_OWNED_READERS`.
        """
        stats = (
            "from sqlalchemy import func\n"
            "from models import Book, Tag, book_tags\n"
            "def f(shelf):\n"
            "    return (shelf.select(Tag.name, func.count(book_tags.c.book_id))\n"
            "        .join(book_tags, Book.id == book_tags.c.book_id)\n"
            "        .join(Tag, Tag.id == book_tags.c.tag_id)\n"
            "        .group_by(Tag.name).all())\n"
        )
        headings = (
            "from sqlalchemy import func\n"
            "from models import Book, Classification\n"
            "from shelf import Shelf\n"
            "def f(db, uid):\n"
            "    return (Shelf.seen_by(db, uid)\n"
            "        .select(Classification.number, func.count(Book.id))\n"
            "        .join(Classification, Classification.book_id == Book.id)\n"
            "        .group_by(Classification.number).all())\n"
        )
        assert _book_owned_offences(stats), "a correct index stopped being reported"
        assert _book_owned_offences(headings), "a correct index stopped being reported"

    def test_a_root_name_bound_to_another_package_is_not_the_entity(self):
        """The false refusal half of the resolver, which no sweep can see.

        `collections.abc.Collection` and `models.Collection` are the same
        seven letters and different objects, and five modules outside the
        tests bind the first. A rule seeded from the bare root refuses the
        first one it meets in a reading call, which is a red nobody can
        explain from the statement it points at.

        **Three directions in one arm**, because a subtraction that fires on
        everything is as wrong as one that fires on nothing, and the middle
        case is where this was actually wrong.

        The third is the re-export, and it is the one that shipped broken.
        `shelving.py` does `from models import Book, Collection`, so
        `from shelving import Collection` binds the real table; keyed on the
        source not being `models`, the resolver struck the name out and the
        whole module went unreportable with nothing red. Keyed on the source
        being outside the backend corpus, it does not.
        """
        stdlib = (
            "from collections.abc import Collection\n"
            "def f(db, ids: Collection[int]):\n"
            "    return db.query(Collection).all()\n"
        )
        model = "from models import Collection\ndef f(db):\n    return db.query(Collection).all()\n"
        # The subject is the import's SOURCE being a module this backend has,
        # not anything inside it, so what arms this is `shelving.py` existing.
        # Renaming that file reddens this arm rather than quietly disarming it,
        # which is the direction a data dependency has to fail in.
        re_exported = "from shelving import Collection\ndef f(db):\n    return db.query(Collection).all()\n"
        entity = frozenset({"Collection"})

        assert _book_owned_offences(stdlib, entity) == []
        assert _book_owned_offences(model, entity) == [3]
        assert _book_owned_offences(re_exported, entity) == [3]

    def test_a_statement_is_reported_once_however_many_lines_it_takes(self):
        """An allowlist entry counts something a person wrote.

        `routers/stats.py`'s Tag index is one statement over eight lines with
        three reading calls in it. Counting calls or lines would make the
        allowlist a function of the formatter, and a reason written beside an
        entry would stop lining up with anything.
        """
        source = (
            "from sqlalchemy import func\n"
            "from models import Book, Tag, book_tags\n"
            "def f(shelf):\n"
            "    return (shelf.select(Tag.name, func.count(book_tags.c.book_id))\n"
            "        .join(book_tags, Book.id == book_tags.c.book_id)\n"
            "        .group_by(Tag.name)\n"
            "        .order_by(func.count(book_tags.c.book_id).desc())\n"
            "        .all())\n"
        )
        assert _book_owned_offences(source) == [4]

    def test_a_query_scoped_by_a_shelf_may_still_not_join_books_back_in(self):
        """Pass 3 reports `Book` in a join from every root, this one included.

        `aliased(Book)` joined into a query already rooted at a Shelf is a
        second, unfiltered copy of the table, so being scoped somewhere in the
        statement says nothing about it. The fourth pass used to carry an
        asymmetry here and no longer decides anything at all, but pass 3 still
        does, and this is what holds it.
        """
        source = (
            "from sqlalchemy.orm import aliased\n"
            "from models import Book\n"
            "from shelf import Shelf\n"
            "def f(db, uid):\n"
            "    other = aliased(Book)\n"
            "    return (Shelf.seen_by(db, uid).select(other.location)\n"
            "        .join(other, other.isbn == Book.isbn).all())\n"
        )
        assert _join_offences(source) != []

    def test_a_child_of_books_is_recognised_from_the_schema_alone(self):
        """The derived half, asked of a schema built here, because asking it of
        the real one only re-states the ten tables that already exist and would
        pass with the derivation replaced by that list."""
        metadata = MetaData()
        Table("books", metadata, Column("id", Integer, primary_key=True))
        Table("users", metadata, Column("id", Integer, primary_key=True))
        Table(
            "shelf_marks",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("book_id", Integer, ForeignKey("books.id")),
        )
        Table(
            "scribbles",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("book_id", Integer, ForeignKey("books.id")),
            Column("user_id", Integer, ForeignKey("users.id")),
        )
        Table("publishers", metadata, Column("id", Integer, primary_key=True))

        assert _child_names(metadata) == {"shelf_marks", "scribbles"}

    def test_every_child_of_books_is_classified(self):
        """The pinned half, and the one that stops a new table defaulting to
        unguarded.

        An earlier version of this rule computed the classification: a child
        with no foreign key to `users` was taken to have no viewer of its own.
        That predicate is wrong in this schema, and `models.py` already said so
        in three places. `collections.created_by_user_id` is "provenance and
        nothing else. No query consults it"; `author_aliases` and
        `author_identifiers` say the same. A `catalogued_by_user_id` on
        `classifications` would have dropped that table out of the guard with
        nothing failing.

        **`books.added_by_user_id` is not a fourth example**, and an earlier
        draft of this docstring called it one. It is the column `visible_to`
        and `in_trash_for` are built on, read at six sites; `books` is outside
        the derivation for being the parent table. Three counter-examples carry
        the argument, and the wrong fourth was in a published file.

        So the question the schema cannot answer is asked of a person, once,
        the first time a table appears.
        """
        derived = _child_names(Base.metadata)
        assert derived == BOOK_CHILDREN, (
            "A table gained or lost a foreign key to `books`. Add it to "
            "BOOK_CHILDREN, and to BOOK_OWNED_TABLES as well if its rows carry "
            "no member of their own, because a child that is in neither is not "
            f"guarded by anything here: {sorted(derived ^ BOOK_CHILDREN)}"
        )
        assert BOOK_OWNED_TABLES <= BOOK_CHILDREN, (
            f"BOOK_OWNED_TABLES names a table that is not a child of books: "
            f"{sorted(BOOK_OWNED_TABLES - BOOK_CHILDREN)}"
        )

    def test_every_parameterised_reader_is_classified(self):
        """The direction an inclusion list is blind in: the set going short.

        A module that hands a reading call a runtime name is one this pass
        cannot see. Which of those is a hole and which is a coincidence is a
        person's answer, asked once, the first time a module appears, exactly as
        `test_every_child_of_books_is_classified` asks it of a new table.
        """
        derived = {name for name, source in application_sources().items() if _parameterised_reads(source)}
        assert derived == set(PARAMETERISED_READERS), (
            "a module started or stopped handing a reading call a name bound at "
            "runtime. This pass cannot see what table it reads, so say which it "
            "is beside PARAMETERISED_READERS and how it is guarded instead: "
            f"{sorted(derived ^ set(PARAMETERISED_READERS))}"
        )

    def test_the_derivation_sees_a_runtime_entity_and_not_an_imported_one(self):
        """The rule, driven against two statements built here, because asking it
        of the tree only restates the modules that already answer."""
        runtime = "def carry(db, model):\n    return db.query(model).all()\n"
        attribute = "def carry(db, carrier):\n    return db.query(carrier.entry).all()\n"
        imported = "from models import Book\n\ndef carry(db):\n    return db.query(Book).all()\n"

        assert _parameterised_reads(runtime) == [2]
        assert _parameterised_reads(attribute) == [2]
        assert _parameterised_reads(imported) == []

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param(
                "from sqlalchemy import func\n"
                "def carry(db, carrier):\n"
                "    return db.query(func.count(carrier.entry)).all()\n",
                id="inside a call",
            ),
            pytest.param(
                "def carry(db, columns):\n    return db.query(*columns).all()\n",
                id="starred",
            ),
        ],
    )
    def test_a_runtime_name_anywhere_in_an_argument_is_reported(self, source):
        """A local below the argument's root chooses the table at run time as
        surely as one at it. Both shapes are the tree's own: `lending.py` wraps
        a builder argument in `func.count`, and `backup.py` stars one."""
        line = len(source.splitlines())

        assert _parameterised_reads(source) == [line]

    def test_a_parameterised_reader_is_genuinely_invisible_to_this_pass(self):
        """The diagonal on `PARAMETERISED_READERS`, in the direction that rots.

        A module listed there is excused nothing: its parameterised statements
        are recorded as unseeable. If one of those statements starts naming an
        entity this pass sees, the entry becomes a note about a gap that closed,
        which is worse than no note. Asked per statement rather than per module,
        because a listed module may hold other reads this pass sees by design:
        the Shelf's own, and `backup.py`'s `book_tags.select()`.
        """
        sources = application_sources()
        seen = {
            name: overlap
            for name in sorted(PARAMETERISED_READERS)
            if (
                overlap := sorted(
                    set(_parameterised_reads(sources[name])) & set(_book_owned_offences(sources[name]))
                )
            )
        }
        assert not seen, (
            "these statements are named in PARAMETERISED_READERS as reads this "
            "pass cannot see, and it can see them: give them entries in "
            f"BOOK_OWNED_READERS and say so beside that set: {seen}"
        )

    def test_the_book_owned_set_is_the_entities_those_tables_map_to(self):
        """The entities the docstrings name, measured rather than asserted in
        prose."""
        assert set(BOOK_OWNED) == {
            "BookIdentifier",
            "Classification",
            "CustomFieldValue",
            "DigitalReference",
            "OnlineLink",
            "book_tags",
        }, (
            "The guarded entities no longer match BOOK_OWNED_TABLES. If a table "
            "was renamed, rename it there; do not update this constant to make "
            "the test green, because that is how a table leaves the guard."
        )

    def test_every_book_owned_table_has_a_name_this_rule_can_look_for(self):
        """A table with no mapped class and no module-level `Table` variable
        would be book-owned, unguarded and invisible, which is the exact
        failure mode this file exists to prevent."""
        assert not UNNAMEABLE_BOOK_OWNED, (
            "These tables are book-owned and no module could name them, so the "
            f"fourth pass cannot see a read of them: {sorted(UNNAMEABLE_BOOK_OWNED)}"
        )

    def test_the_predicates_are_defined_where_this_rule_says_they_are(self):
        """The rules above are name checks, so it is worth proving the names
        they check are real. A typo in `PREDICATES` would let them pass over a
        tree that had abandoned the seam entirely."""
        models = (BACKEND / "models.py").read_text()
        for predicate in PREDICATES:
            assert f"def {predicate}(" in models, predicate

    @staticmethod
    def _callees(source: str) -> set[str]:
        """Every call in a module, spelled as its callee.

        `ast`, not a substring, and the difference is a failure this file
        already has a paragraph about: `lending.py`'s module docstring contains
        the literal `Shelf.seen_by(db, viewer).select(Loan).join(...)`, so a
        substring assertion that the door roots at the Shelf passes with the
        rooting deleted. A guard satisfied by the prose arguing for the rule
        guards nothing.
        """
        return {ast.unparse(node.func) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)}

    @staticmethod
    def _privacy_calls(source: str) -> set[str]:
        """Every `Book.is_private.is_(...)` a module writes, with its argument.

        The argument is the whole point: `is_(True)` is the count of what was
        held back and `is_(False)` is the audience, and a rule that could not
        tell them apart would pass a module that had swapped them.
        """
        return {
            ast.unparse(node)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "Book.is_private.is_"
        }

    def test_notifications_reads_books_and_is_deliberately_not_a_shelf(self):
        """Named rather than left as a silent pass.

        The overdue **digest** runs for the Library on a schedule, so it has no
        viewer to be scoped to, and its two halves **partition** on privacy
        rather than filter by it: `is_(False)` for the reminders it sends and
        `is_(True)` for the count of what privacy held back. A Shelf would have
        to mean both at once, which is what `in_trash_for` being a separate
        function from `visible_to` exists to avoid.

        **The exemption is the digest's and does not cover the module.** The in
        app channel added for #86 has a viewer, and it does not get to inherit a
        note written about a scheduled job: `overdue_for_viewer` is rooted at
        the Shelf, and its own tests pin who sees what. So this asserts both
        halves rather than one: the digest still partitions, and the half with a
        viewer still goes through the Shelf.

        **Two of the three halves became calls on 2026-09-17**, so both files
        are read and both are read as calls. This module's viewerless half is
        `Loans.for_a_channel`, which is `Shelf.seen_by_the_public`, and its
        viewer scoped half is `Loans.seen_by`, which is `Shelf.seen_by`. The
        third, `is_(True)`, is `count_private_overdue`, which is not a loan
        scope at all: it counts what the exclusion held back without naming any
        of it, and it stays here.

        **The door is asserted not to restate the predicate**, rather than to
        contain it. A `lending.py` that wrote `Book.is_private.is_(False)` onto
        a query of its own would be the arrangement this rule exists to refuse,
        one table further out, and it is what that module shipped for half a
        day.

        This fails if that module ever applies a viewer predicate **itself**,
        because at that point it has stopped using the seam.

        Read with `ast` and not as text, and the reason is not hypothetical: the
        substring form of this check failed on the sentence "`visible_to()` has
        always said a private book is visible to the member who added it",
        written in a docstring explaining why the Shelf is used. A guard that
        reddens on the comment arguing for the rule it enforces is one somebody
        deletes.

        **What the substring form did and did not catch, measured rather than
        asserted**, because this docstring said something false about it once.
        `"visible_to(" in "models.visible_to(1)"` is **True**, so it caught both
        dotted shapes. The one call shape it missed is the local alias,
        `from models import visible_to as vt` then `vt(1)`, which contains
        neither predicate name followed by a bracket. So the rewrite buys one
        call shape and the end of the false positive on prose; it does not buy
        the dotted call, and saying it did was a measurement nobody had taken.
        """
        source = (BACKEND / "notifications.py").read_text()
        desk = (BACKEND / "lending.py").read_text()

        assert {"lending.Loans.for_a_channel", "lending.Loans.seen_by"} <= self._callees(source)
        assert {"Shelf.seen_by_the_public", "Shelf.seen_by"} <= self._callees(desk)
        assert self._privacy_calls(source) == {"Book.is_private.is_(True)"}
        assert self._privacy_calls(desk) == set()

        assert _predicate_calls(source) == set(), (
            "notifications.py applies a visibility predicate itself. Its viewer "
            "scoped half belongs behind Shelf.seen_by, and its viewerless half "
            "partitions rather than filters."
        )

    def test_no_module_but_the_shelf_calls_a_visibility_predicate(self):
        """The other half of the import rule, and it is a separate pass because
        the two are evaded differently.

        Importing a predicate is caught by `_imported_predicates`. **Importing
        the module is not, and must not be**: `import models` is legal
        everywhere and dozens of modules do it. What that leaves is
        `models.visible_to(1)`, which binds no predicate name and so is invisible
        to every rule reading import statements. This is the pass that sees it,
        and it is run over the whole tree rather than over `notifications.py`
        alone, because the hole was tree-wide.
        """
        offenders = sorted(
            f"{name}:{called}"
            for name, source in application_sources().items()
            if name not in PREDICATE_IMPORTERS
            for called in _predicate_calls(source)
        )
        assert offenders == [], (
            f"These modules apply a visibility predicate themselves: {offenders}. "
            "Ask the Shelf for one instead."
        )

    @pytest.mark.parametrize(
        ("shape", "source"),
        [
            ("bare", "from models import visible_to\nq.filter(visible_to(1))\n"),
            ("dotted", "import models\nq.filter(models.visible_to(1))\n"),
            (
                "aliased",
                "from models import visible_to as vt\nq.filter(vt(1))\n",
            ),
            ("dotted alias", "import models as m\nq.filter(m.in_trash_for(1))\n"),
        ],
    )
    def test_the_predicate_call_rule_reports_every_way_of_reaching_one(self, shape, source):
        """Attacked rather than read, which is what this file's own header says
        about every guard in it.

        One of these four evaded the substring check that stood here before: the
        local alias. The two dotted shapes did **not**, and this docstring said
        they did until somebody measured `"visible_to(" in "models.visible_to(1)"`
        and got True.
        """
        assert _predicate_calls(source), f"the {shape} shape is not reported"

    #: Every way a module can import a predicate, one source per spelling.
    #:
    #: One list, read by the rule's own parametrisation **and** by the test that
    #: pins what the superseded expression missed, so the two cannot disagree
    #: about what the spellings are. It was two lists, and the docstring on one
    #: of them described the other.
    _IMPORT_SPELLINGS = (
        ("bare", "from models import visible_to\n"),
        ("aliased", "from models import visible_to as _v\n"),
        ("aliased, second name", "from models import in_trash_for as trashed\n"),
        ("beside another name", "from models import Book, visible_to\n"),
        # Binds the predicate exactly as a named import does. This file asserted
        # the opposite until 2026-08-28; see `_imported_predicates`.
        ("a star from the module that holds one", "from models import *\n"),
        ("a star from the module that re-exports one", "from shelf import *\n"),
    )

    @pytest.mark.parametrize(("shape", "source"), _IMPORT_SPELLINGS)
    def test_the_predicate_import_rule_reports_every_spelling(self, shape, source):
        """Every spelling binds a predicate, so every one must be reported.

        `alias.name` is the whole of it, and it is the idiom `test_reading.py`
        and `test_custom_fields.py` already use for the same question, both
        verified correct on 2026-08-28 rather than assumed.

        Which of these the expression this replaced let past is **not stated
        here**. It is measured, in the test below, off this same list. A
        docstring saying "of these four only the first and the last" stood here
        against a list of six whose last entry it named wrongly, which is the
        fourth wrong count this one file produced in one wave.
        """
        assert _imported_predicates(source), f"the {shape} spelling is not reported"

    def test_the_superseded_expression_let_the_aliases_and_the_stars_past(self):
        """What the rewrite bought, derived from the spellings rather than
        recalled about them.

        `alias.asname or alias.name` answers "what does this module bind", which
        is the right answer to a different question and the wrong one to this.
        It is reconstructed here rather than described, so the claim is a
        measurement that fails when it stops being true instead of a sentence
        nothing checks.

        The `Import | ImportFrom` walk is the superseded form verbatim, plain
        `import` included, which is why a reader should not take this as a
        second implementation of the rule: it is a fixture of a deleted one.
        """

        def superseded(source: str) -> set[str]:
            return {
                alias.asname or alias.name
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Import | ast.ImportFrom)
                for alias in node.names
            } & set(PREDICATES)

        missed = {shape for shape, source in self._IMPORT_SPELLINGS if not superseded(source)}

        assert missed == {
            "aliased",
            "aliased, second name",
            "a star from the module that holds one",
            "a star from the module that re-exports one",
        }, (
            "The set of spellings the superseded expression let past has moved. "
            "Every one of these is reported by the rule that replaced it, which "
            f"the parametrisation above holds: {sorted(missed)}"
        )

    @pytest.mark.parametrize(
        ("shape", "source"),
        [
            ("the module itself", "import models\n"),
            ("another name from it", "from models import Book\n"),
            ("a name that contains one", "from models import visible_to_all\n"),
            # A star from a module **outside `_STAR_SOURCES`**, which is what
            # this pins: the gate, not the contents. It short-circuits before
            # `dir()` is called, so it would report nothing even if `enums`
            # exported a predicate. The star from a module inside the gate is in
            # the positive parametrisation, where it belongs.
            ("a star from outside the laundering set", "from enums import *\n"),
        ],
    )
    def test_the_predicate_import_rule_reports_nothing_else(self, shape, source):
        """`& set(PREDICATES)` is what makes this a rule about two names rather
        than a rule about importing, and nothing pinned it: with the
        intersection dropped, `_imported_predicates` reports every name any
        module imports, and every module in the tree becomes an offender.

        `import models` is the load bearing case. It imports the module and not
        the predicate, which is legal everywhere and which most of the backend
        does; the **call** through it is `_predicate_calls`' job. The two rules
        divide the work, and this is what stops them overlapping into a false
        positive that would flag the whole tree.
        """
        assert _imported_predicates(source) == set(), f"{shape} is reported"

    #: The ways a module can reach a predicate, as a product rather than a list.
    #:
    #: **A product, because a list describes itself.** The first version of this
    #: table was a dict of ten hand-written rows and the assertions drew their
    #: domain from it, so deleting a row shrank the domain and an `all()` over
    #: fewer items could not fail: six of the ten deleted green, and with both
    #: `direct` rows gone `_predicate_calls` could return `set()` unconditionally
    #: and still pass. That is the shape `CLAUDE.md` records as "a stated bound
    #: can stop guarding without ever failing", and it is the same defect the
    #: prose had, one level in.
    #:
    #: So the rows are generated from these two tuples and the test asserts the
    #: keys are exactly their product, which is the check this file already
    #: applies to `BOOK_OWNED_READERS`. It also derives the count, so the
    #: paragraph on `_predicate_calls` cannot state a fourth wrong number: it
    #: stated 13, then 5, then 11 against a table of 10, in three rounds, in a
    #: paragraph calling itself a measurement.
    _FAMILIES = ("direct", "rebind", "getattr", "dict", "partial")
    _SPELLINGS = ("from", "dotted", "star")

    @staticmethod
    def _shape(family: str, spelling: str) -> str:
        """One module, reaching a predicate one way."""
        head = {
            "from": "from models import visible_to\n",
            "dotted": "import models\n",
            "star": "from models import *\n",
        }[spelling]
        # The dotted spelling never binds a predicate name, which is the whole
        # difference between it and the other two.
        ref = "models.visible_to" if spelling == "dotted" else "visible_to"
        holder = "models" if spelling == "dotted" else "m"
        body = {
            "direct": f"q.filter({ref}(1))\n",
            "rebind": f"vis = {ref}\nq.filter(vis(1))\n",
            "getattr": f'q.filter(getattr({holder}, "visible_to")(1))\n',
            "dict": f'd = {{"v": {ref}}}\nq.filter(d["v"](1))\n',
            "partial": f"p = partial({ref}, 1)\nq.filter(p())\n",
        }[family]
        return head + body

    def test_the_two_rules_together_leave_exactly_the_dotted_indirections_open(self):
        """The blind spot list in `_predicate_calls`, executed rather than
        recalled.

        That paragraph has been wrong three times, on the count and once on the
        reason, which is what a list of blind spots kept as prose does. This is
        the same list as a table, so it fails when it stops being true: a shape
        that starts being caught, or one that stops being, moves a row.

        The shape of the answer is the finding. Two of the three spellings bind
        a predicate name, so the import rule carries every indirection written
        with them; the dotted one binds nothing and puts nothing in a callee, so
        neither rule sees it. **The discriminator is `import models`.**
        """
        # **The two tuples against literals**, which is the precedent
        # `test_the_book_owned_set_is_the_entities_those_tables_map_to` sets four
        # hundred lines up. What stood here compared the generated keys against
        # the identical generating expression, so it could not fail: run
        # verbatim, dropping the whole `star` spelling passed, dropping `from`
        # passed, dropping both non-dotted spellings passed, and dropping a
        # family passed. Only the `escaping` literal below pinned anything, and
        # it pinned families only.
        #
        # Do not edit these two literals to make a red build green. That is how
        # a spelling leaves the guard, and this table exists because one already
        # had.
        assert self._FAMILIES == ("direct", "rebind", "getattr", "dict", "partial"), (
            "An indirection family left the table. Every one of them defeats "
            "`_predicate_calls`, so removing a row removes a claim rather than "
            "a redundancy."
        )
        assert self._SPELLINGS == ("from", "dotted", "star"), (
            "A spelling left the table. `star` in particular was added because "
            "it escaped both rules and was absent from the list that claimed to "
            "enumerate what escapes."
        )

        shapes = {
            (family, spelling): self._shape(family, spelling)
            for family in self._FAMILIES
            for spelling in self._SPELLINGS
        }

        escaping = sorted(
            key
            for key, source in shapes.items()
            if not (_imported_predicates(source) or _predicate_calls(source))
        )

        assert escaping == [
            ("dict", "dotted"),
            ("getattr", "dotted"),
            ("partial", "dotted"),
            ("rebind", "dotted"),
        ], (
            "The set of shapes that escape both rules has moved. Update the "
            "blind spot paragraph on `_predicate_calls` with the measurement, "
            "not with a recollection of it."
        )

        # Every row is asserted about, not only the escaping ones, so a row
        # cannot be deleted for being uninteresting. `direct` is the row that
        # pins the call pass: with it gone, `_predicate_calls` returning an
        # empty set passes everything above.
        for (family, spelling), source in shapes.items():
            caught = bool(_imported_predicates(source) or _predicate_calls(source))
            assert caught is (spelling != "dotted" or family == "direct"), (
                f"{family} written {spelling} changed side"
            )

    def test_the_predicate_import_rule_leaves_the_module_import_alone(self):
        """The one sentence both rules depend on, kept as its own assertion so
        deleting the parametrisation above cannot take it with them."""
        assert _imported_predicates("import models\n") == set()

    def test_the_predicate_rule_does_not_report_prose_about_it(self):
        """The failure that produced this test. A docstring arguing **for** the
        rule is not a use of it, and a guard that reddens on the comment
        explaining itself is one somebody deletes."""
        source = (
            '"""Rooted at the Shelf, because `visible_to()` says a private book\n'
            'is visible to the member who added it. See `in_trash_for()`."""\n'
            "rows = Shelf.seen_by(db, viewer.id).select(Loan).all()\n"
        )
        assert _predicate_calls(source) == set()

    def test_the_backup_is_the_third_way_past_a_viewer_and_says_so(self):
        """`backup.py` is invisible to every rule in this file, so it is
        asserted rather than assumed.

        It reads every row of every table through `select(*columns)` over a
        table bound at run time, so no rule that reads a query's arguments can
        see which table it reads.
        That is deliberate: a backup that omitted everyone else's Private Books
        would restore to a library missing rows. What holds it safe is that it
        is admin only, which is checked here because nothing else does.
        """
        source = (BACKEND / "backup.py").read_text()
        assert "Not filtered by `visible_to`" in source
        assert _query_offences(source) == [], (
            "backup.py now names Book in a query, so it is no longer invisible "
            "to the rule above and no longer needs this test"
        )
        # Counted against the number of routes, not against a fixed 2. A literal
        # count is a proxy for the thing it stands for: a third route added with
        # no guard leaves it at 2 and passes green, which is the same defect as
        # counting modules instead of call sites in the test below.
        routes = (BACKEND / "routers" / "backup.py").read_text()
        assert routes.count("Depends(require_admin)") == routes.count("@router."), (
            "backup.py has a route that is not gated on require_admin"
        )

    def test_the_named_ways_past_a_viewer_have_the_callers_they_claim(self):
        """The counting the deleted guard did, kept.

        `test_the_exemptions_are_still_the_known_ones` existed so the list of
        opt-outs could not grow quietly. The opt-outs became named functions,
        and the counting has to survive that or the same drift happens with a
        different spelling. Growing any of these lists is allowed; growing one
        without saying so here is not.
        """
        calls: dict[str, list[str]] = {
            "whole_table_for_uniqueness": [],
            "rereading_filtered_rows": [],
            "entries_any_book_carries": [],
        }
        for name, source in application_sources().items():
            if name == "shelf.py":
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in calls:
                    calls[node.func.id].append(f"{name}:{node.lineno}")

        # **Call sites, not modules.** A set of module names does not count
        # anything: two of the three uniqueness calls are already in
        # `routers/books.py`, so a fourth added there would leave the set
        # unchanged and pass green, which is exactly the quiet growth the
        # deleted exemption counter existed to prevent.
        #
        # **Three, and every recognition holds one of them between them.**
        # The importers and the add door reach the whole table through
        # `recognition.Index`, so a new importer or door is not a fourth.
        assert len(calls["whole_table_for_uniqueness"]) == 3, calls
        assert len(calls["rereading_filtered_rows"]) == 1, calls
        # **One, and it is the arm that keeps the third way past a viewer
        # narrow.** It answers whether a vocabulary entry has anything to
        # disclose at all, which is a question no viewer can be applied to without turning
        # it into a different one, and it hands back ids rather than a count so
        # nothing about how many hidden Books carry one crosses the boundary. A
        # second caller is a decision about that boundary rather than an edit.
        assert len(calls["entries_any_book_carries"]) == 1, calls


class TestWhoSeesWhat:
    def test_a_public_book_is_on_every_members_shelf(self, db, user, other):
        db.add(Book(title="Public", added_by_user_id=user.id, is_private=False))
        db.commit()

        assert Shelf.seen_by(db, other.id).count() == 1

    def test_a_private_book_is_on_nobody_elses(self, db, user, other):
        db.add(Book(title="Private", added_by_user_id=user.id, is_private=True))
        db.commit()

        assert Shelf.seen_by(db, user.id).count() == 1
        assert Shelf.seen_by(db, other.id).count() == 0

    def test_a_trashed_book_is_on_nobodys_shelf_and_is_in_its_owners_trash(self, db, user):
        db.add(_trashed(title="Gone", added_by_user_id=user.id, is_private=False))
        db.commit()

        assert Shelf.seen_by(db, user.id).count() == 0
        assert Shelf.trashed_by(db, user.id).count() == 1

    def test_another_members_private_book_is_not_in_your_trash(self, db, user, other):
        """Privacy outlives deletion. The trash is a view of the shelf, not a
        way around it."""
        db.add(_trashed(title="Gone", added_by_user_id=user.id, is_private=True))
        db.commit()

        assert Shelf.trashed_by(db, user.id).count() == 1
        assert Shelf.trashed_by(db, other.id).count() == 0

    def test_another_members_trashed_public_book_is_in_your_trash(self, db, user, other):
        """The positive direction of the same predicate, which no arm held.

        `in_trash_for` is trashed **and visible**, never trashed **and
        theirs**: there is no column recording who deleted a row. With only the
        refusal above pinned, "has trashed away" read as true, and four
        docstrings downstream had copied it by 2026-09-30.
        """
        db.add(_trashed(title="Gone", added_by_user_id=user.id, is_private=False))
        db.commit()

        assert Shelf.trashed_by(db, other.id).count() == 1


class TestNarrowing:
    def test_where_keeps_the_privacy_predicate(self, db, user, other):
        """The narrowing that would be the leak: asking for a title by name. A
        `where()` that replaced the predicate rather than adding to it would
        answer this with the other member's private book."""
        db.add(Book(title="Secret", added_by_user_id=user.id, is_private=True))
        db.commit()

        assert Shelf.seen_by(db, other.id).where(Book.title == "Secret").all() == []

    def test_select_keeps_the_privacy_predicate(self, db, user, other):
        """The `query(Book.<column>)` shape. An index publishes a name and a
        count, which is a disclosure rather than a slow query, and it is the
        shape the old guard had to be widened to see at all."""
        db.add(
            Book(
                title="Secret",
                author="Hidden Author",
                added_by_user_id=user.id,
                is_private=True,
            )
        )
        db.commit()

        rows = (
            Shelf.seen_by(db, other.id)
            .select(Book.author, func.count(Book.id))
            .filter(Book.author.isnot(None))
            .group_by(Book.author)
            .all()
        )
        assert rows == []

    def test_select_carries_a_narrowing_applied_before_it(self, db, user):
        """`select()` rebuilds from the accumulated clauses, so a `where()`
        applied first is still on it. Rebuilding from the viewer id alone would
        widen the query back to the whole shelf."""
        db.add_all(
            [
                Book(title="Kept", location="study", added_by_user_id=user.id),
                Book(title="Dropped", location="attic", added_by_user_id=user.id),
            ]
        )
        db.commit()

        rows = Shelf.seen_by(db, user.id).where(Book.location == "study").select(Book.title).all()
        assert [title for (title,) in rows] == ["Kept"]

    def test_select_refuses_a_shelf_narrowed_by_read_status(self, db, user):
        """The one narrowing that is a join rather than a clause.

        Rebuilding it from the clauses alone would drop the join and hand back
        every Book on the shelf, which is a wrong answer rather than an error.
        """
        shelf = Shelf.seen_by(db, user.id).matching(BookFilters(status=ReadStatus.READING))
        with pytest.raises(ValueError, match="read status"):
            shelf.select(Book.id)

    def test_a_shelf_is_immutable(self, db, user):
        """A narrowing returns a new Shelf, so one handed to two callers cannot
        be narrowed by one of them behind the other's back."""
        db.add_all(
            [
                Book(title="A", location="study", added_by_user_id=user.id),
                Book(title="B", location="attic", added_by_user_id=user.id),
            ]
        )
        db.commit()

        shelf = Shelf.seen_by(db, user.id)
        narrowed = shelf.where(Book.location == "study")

        assert narrowed.count() == 1
        assert shelf.count() == 2


class TestFilters:
    def test_unfiled_and_a_collection_are_separate_questions(self, db, user, shelved):
        db.add_all(
            [
                Book(title="Filed", collection_id=shelved.id, added_by_user_id=user.id),
                Book(title="Loose", added_by_user_id=user.id),
            ]
        )
        db.commit()

        shelf = Shelf.seen_by(db, user.id)
        assert shelf.matching(BookFilters(unfiled=True)).count() == 1
        assert shelf.matching(BookFilters(collection_id=shelved.id)).count() == 1

    def test_the_text_search_covers_title_author_and_isbn(self, db, user):
        db.add_all(
            [
                Book(title="Findable", added_by_user_id=user.id),
                Book(title="x", author="Findable", added_by_user_id=user.id),
                Book(title="y", isbn="9780000000019", added_by_user_id=user.id),
            ]
        )
        db.commit()

        shelf = Shelf.seen_by(db, user.id)
        assert shelf.matching(BookFilters(q="findable")).count() == 2
        assert shelf.matching(BookFilters(q="978000000001")).count() == 1

    def test_a_wildcard_in_the_search_term_is_a_character_and_not_a_wildcard(self, db, user):
        """`100%` finds the four characters, not every title holding `100`.

        Both directions, because a fix that escaped everything would pass a
        test that only checked the literal: an ordinary term must still match
        as a substring.
        """
        db.add_all(
            [
                Book(title="100% Wool", added_by_user_id=user.id),
                Book(title="1000 Ships", added_by_user_id=user.id),
                Book(title="a_b", added_by_user_id=user.id),
                Book(title="axb", added_by_user_id=user.id),
            ]
        )
        db.commit()

        shelf = Shelf.seen_by(db, user.id)
        assert shelf.matching(BookFilters(q="100%")).count() == 1
        assert shelf.matching(BookFilters(q="a_b")).count() == 1
        # The ordinary case, which is what the escape must not break.
        assert shelf.matching(BookFilters(q="100")).count() == 2
        assert shelf.matching(BookFilters(q="Wool")).count() == 1

    def test_a_backslash_in_the_search_term_is_a_character_too(self, db, user):
        """The escape character itself, which the loop escapes along with the two
        wildcards.

        **The row rather than the count, and the difference is the whole test.**
        Both fixtures are one edit apart, so a term left unescaped matches the
        other one and the count stays at 1. Measured: with `"\\\\"` dropped from
        the loop's tuple this asserted `count() == 1`, matched `ACDC Live`
        instead, and passed, and so did every other test in this file. Asserting
        which book came back is what makes the fixtures worth having.

        **It does not pin the order the loop escapes in**, which its own reason
        used to claim. A term carrying no `%` and no `_` produces the same
        pattern whichever end the backslash is escaped from, so the order is
        invisible here.
        `test_a_wildcard_in_the_search_term_is_a_character_and_not_a_wildcard` is
        what pins it: escaping the backslash last escapes the ones the loop had
        just added, and `q="100%"` goes from 1 to 0.
        """
        db.add_all(
            [
                Book(title=r"AC\DC Live", added_by_user_id=user.id),
                Book(title="ACDC Live", added_by_user_id=user.id),
            ]
        )
        db.commit()

        shelf = Shelf.seen_by(db, user.id)
        found = shelf.matching(BookFilters(q=r"AC\DC")).all()

        assert [book.title for book in found] == [r"AC\DC Live"]

    def test_unread_includes_a_book_nobody_has_touched(self, db, user):
        """A Book with no `UserBook` row has never been touched, which is
        unread. Filtering on the row alone reports an untouched shelf as having
        nothing unread on it."""
        db.add(Book(title="Never opened", added_by_user_id=user.id))
        db.commit()

        shelf = Shelf.seen_by(db, user.id)
        assert shelf.matching(BookFilters(status=ReadStatus.UNREAD)).count() == 1

    def test_unrated_works_with_no_status_filter_beside_it(self, db, user):
        """The reason `_unrated` is a correlated exists rather than a reuse of
        the read status join: that join is conditional, so depending on it would
        make this filter do nothing whenever no status was sent."""
        rated = Book(title="Rated", added_by_user_id=user.id)
        unrated = Book(title="Unrated", added_by_user_id=user.id)
        db.add_all([rated, unrated])
        db.commit()
        db.add(UserBook(book_id=rated.id, user_id=user.id, rating=4))
        db.commit()

        found = Shelf.seen_by(db, user.id).matching(BookFilters(unrated=True)).all()
        assert [book.title for book in found] == ["Unrated"]

    def test_unrated_and_a_status_filter_together_keep_their_from_clause(self, db, user):
        """`correlate(Book)` is load bearing: with the status filter's own
        UserBook join in play, SQLAlchemy would otherwise pull UserBook out of
        the subquery and leave it with no FROM clause, raising rather than
        filtering."""
        book = Book(title="Reading and unrated", added_by_user_id=user.id)
        db.add(book)
        db.commit()
        db.add(UserBook(book_id=book.id, user_id=user.id, status=ReadStatus.READING))
        db.commit()

        found = (
            Shelf.seen_by(db, user.id).matching(BookFilters(status=ReadStatus.READING, unrated=True)).all()
        )
        assert [book.title for book in found] == ["Reading and unrated"]

    def test_discuss_is_anybodys_flag_not_the_viewers(self, db, user, other):
        """The same choice `discuss_with` on the payload makes: the filter has
        to select exactly the Books that carry the marker the grid draws, or
        pressing it hides half of them."""
        book = Book(title="Offered", added_by_user_id=user.id, is_private=False)
        db.add(book)
        db.commit()
        db.add(UserBook(book_id=book.id, user_id=other.id, wants_to_discuss=True))
        db.commit()

        assert Shelf.seen_by(db, user.id).matching(BookFilters(discuss=True)).count() == 1

    def test_a_filter_does_not_widen_past_the_privacy_rule(self, db, user, other):
        """Every filter narrows a shelf that is already scoped. This is the
        assertion that fails if `matching` ever rebuilds the query instead."""
        db.add(
            Book(
                title="Secret",
                location="study",
                added_by_user_id=user.id,
                is_private=True,
            )
        )
        db.commit()

        shelf = Shelf.seen_by(db, other.id)
        assert shelf.matching(BookFilters(location="study")).count() == 0

    def test_every_filter_field_narrows_something(self, db, user):
        """`BookFilters` is a value object with thirteen fields, and a field
        `matching()` forgot to read would be a filter the API accepts and
        silently ignores. Counted here rather than trusted: the dataclass names
        the fields, so the two cannot drift."""
        from dataclasses import fields

        names = {field.name for field in fields(BookFilters)}
        source = (BACKEND / "shelf.py").read_text()
        body = source[source.index("def matching(") : source.index("def _with_read_status(")]
        unread = {name for name in names if f"filters.{name}" not in body}
        assert unread == set(), f"BookFilters fields nothing reads: {unread}"


class TestASliceWithNoCount:
    """`limited` beside `page`, for a caller that walks the whole shelf.

    Driven through the route as well, by
    `tests/routers/test_imports_marc.py::TestTheExportIsPagedRatherThanWhole`.
    These are the unit cases beside `page`'s, and the refusal is the one nothing
    else reaches.
    """

    def test_it_returns_at_most_the_limit_in_the_order_given(self, db, user):
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(5))
        db.commit()

        books = Shelf.seen_by(db, user.id).limited(2, Book.id.asc())

        assert len(books) == 2
        assert [book.id for book in books] == sorted(book.id for book in books)

    def test_it_takes_the_whole_shelf_when_the_limit_is_larger(self, db, user):
        """The other side, without which a method returning nothing passes the
        case above."""
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(3))
        db.commit()

        assert len(Shelf.seen_by(db, user.id).limited(10, Book.id.asc())) == 3

    def test_it_refuses_a_slice_with_no_ordering(self, db, user):
        """A LIMIT with no ORDER BY is an unspecified subset rather than an
        unsorted one, and a walk resuming from its last row resumes from
        nowhere. Nothing else in the tree reaches this refusal."""
        with pytest.raises(ValueError, match="needs an ordering"):
            Shelf.seen_by(db, user.id).limited(2)


class TestPaging:
    def test_total_counts_the_matches_not_the_page(self, db, user):
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(5))
        db.commit()

        books, total = Shelf.seen_by(db, user.id).page(0, 2, Book.id.asc())
        assert len(books) == 2
        assert total == 5

    def test_paging_is_stable_when_titles_tie(self, db, user):
        """Two Books with the same title would otherwise be free to swap between
        pages, which makes paging lose one row and repeat another."""
        db.add_all(Book(title="Same", added_by_user_id=user.id) for _ in range(3))
        db.commit()

        order = order_for(BookSort.TITLE_ASC)
        first, _ = Shelf.seen_by(db, user.id).page(0, 2, *order)
        second, _ = Shelf.seen_by(db, user.id).page(2, 2, *order)

        ids = [book.id for book in first] + [book.id for book in second]
        assert ids == sorted(ids)
        assert len(set(ids)) == 3

    def test_the_series_sort_puts_the_unnumbered_books_last(self, db, user):
        """`nullslast`, or a NULL index scatters them through the list wherever
        SQLite happens to put it."""
        db.add_all(
            [
                Book(title="Second", series_name="Dune", series_index=2, added_by_user_id=user.id),
                Book(title="Loose", added_by_user_id=user.id),
                Book(title="First", series_name="Dune", series_index=1, added_by_user_id=user.id),
            ]
        )
        db.commit()

        books, _ = Shelf.seen_by(db, user.id).page(0, 10, *order_for(BookSort.SERIES))
        assert [book.title for book in books] == ["First", "Second", "Loose"]


class TestStatementCost:
    """The N+1 this seam must not reintroduce.

    Listing 25 Books once went from **6** statements to **53** by adding a per
    request field inside the serialisation loop. These pin the Shelf's own half
    of that number, so a regression is a failing test rather than a slow page.

    Each measurement warms up outside the counted window, for the reason
    `test_serialisation.py` records: a commit inside the window makes the
    session open a fresh savepoint on its next statement, and the listener
    counts that savepoint as a query.
    """

    @staticmethod
    def _count(db, work):
        statements: list[str] = []

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def record(conn, cursor, statement, *args):
            statements.append(statement)

        try:
            work()
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)
        return statements

    def test_a_page_with_serialised_loading_costs_two_statements(self, db, user, other):
        """One count and one page of rows, and nothing else. `added_by` is a
        many to one and rides on the row itself, and Tags are deliberately not
        loaded here: `serialisation.books_to_out` re-reads the page with its
        own `selectinload(Book.tags)`, so an option here would be a second load
        of the same collection.

        **Exactly two, not at most two.** This assertion read `== 3` while the
        option was present, and a ceiling would have gone on passing when it
        was removed: a smaller count is a weaker inequality, which is this
        repository's recorded way of not noticing a statement.

        **The `expunge_all` is what pins the one option left.** Every fixture
        User in this file is created in this same session, so `book.added_by`
        is answered out of the identity map and the `joinedload` could be
        deleted with this test green. Measured by a critic on 2026-08-30, and
        the same hole is why `test_exported_loading_costs_two_statements`
        expunges too.

        `expunge_all`, not `expunge(other)`: the loading option puts a **new**
        `User` instance in the session on every call, so expunging the fixture's
        object works once and then raises "not present in this Session".
        Measured, on the first version of this test. The ids are read before
        the window for the matching reason: the commit above expired both rows,
        and a detached expired instance raises rather than reloading.
        """
        db.add_all(Book(title=f"Book {n}", added_by_user_id=other.id) for n in range(25))
        db.commit()
        viewer_id = user.id

        def page():
            db.expunge_all()
            books, total = Shelf.seen_by(db, viewer_id).page(0, 25, Book.id.asc(), load=Loading.SERIALISED)
            assert len(books) == 25
            assert total == 25
            assert books[0].added_by is not None

        page()  # warm up outside the window
        assert len(self._count(db, page)) == 2

    def test_the_count_does_not_pay_for_the_eager_loading(self, db, user):
        """`page()` counts from the query without the loading options. Counting
        through them would issue the `selectinload` for rows it discards."""
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(5))
        db.commit()

        def count():
            assert Shelf.seen_by(db, user.id).count() == 5

        count()
        assert len(self._count(db, count)) == 1

    def test_exported_loading_costs_two_statements(self, db, user, other, shelved):
        """The third `Loading` member, pinned because the enum's docstring
        states a cost for it. One for the rows, one `selectinload` for the tags
        of the whole page; `added_by` and `collection` are both many to one and
        ride on the row itself, which is the claim being checked.

        The `expunge_all` is the same one the SERIALISED test above explains:
        the adder is created in this session, so without it the `joinedload` on
        `added_by` is answered from the identity map and nothing here pins it.
        """
        db.add_all(
            Book(title=f"Book {n}", collection_id=shelved.id, added_by_user_id=other.id) for n in range(5)
        )
        db.commit()
        viewer_id = user.id

        def export():
            db.expunge_all()
            books = Shelf.seen_by(db, viewer_id).all(Book.title.asc(), load=Loading.EXPORTED)
            assert len(books) == 5
            assert books[0].collection is not None
            assert books[0].added_by is not None

        export()
        assert len(self._count(db, export)) == 2

    def test_published_loading_costs_four_statements(self, db, user):
        """The fourth member. One for the rows and one for each of the three
        collections; `added_by` is not loaded at all, because the public
        payload names no member.

        It was the one cost the enum stated and nothing measured, which is why
        the docstring could say "each of the three" above a list of four
        without anything failing.

        **Every book, not `books[0]`.** Reading one book's collections inside
        the window pays a dropped eager load back as exactly one lazy load, so
        the count is 3 with the options and 3 without them and the test passes
        with its own subject deleted. Both critics measured that separately on
        2026-08-30, on the first version of this test.
        """
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(5))
        db.commit()

        def read():
            books = Shelf.seen_by_the_public(db).all(Book.id.asc(), load=Loading.PUBLISHED)
            assert len(books) == 5
            assert all(book.tags == [] for book in books)
            assert all(book.classifications == [] for book in books)
            assert all(book.online_links == [] for book in books)

        read()
        assert len(self._count(db, read)) == 4

    def test_nothing_loading_costs_one_statement(self, db, user):
        """The first member, pinned through `all()` rather than only through
        `count()`, so all three costs the enum states are measured."""
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(5))
        db.commit()

        def read():
            assert len(Shelf.seen_by(db, user.id).all()) == 5

        read()
        assert len(self._count(db, read)) == 1

    def test_the_cost_of_a_page_does_not_grow_with_the_page(self, db, user):
        """The relative measurement, which is the one that catches a *new* per
        book query rather than a new constant one."""
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(25))
        db.commit()

        def page(size):
            def work():
                Shelf.seen_by(db, user.id).page(0, size, Book.id.asc(), load=Loading.SERIALISED)

            return work

        page(25)()
        assert len(self._count(db, page(25))) == len(self._count(db, page(1)))


class TestAPageIsWholeHoweverTheLoadingJoins:
    """Two numbers behind one page, and the defect is where they diverge.

    The driver's row count is the number **before** the ORM folds a joined
    result back into entities; `len(books)` is the number **after**. A
    loading option that joins a collection under a limit returns one row per
    related row, and the limit applies to the rows, so the page comes back
    short while every row the caller asked for arrived. **The row counter
    reads the first number and is blind here by construction**, which is why
    this is a second instrument and not a reading over the first.

    Measured on this tree, page of ten, three tags a book: `contains_eager`
    over a manual join returned **ten rows and four Books**.
    `shelf.py:229` states the mechanism in the repository's own words, that a
    join "returns that Book once per row", and until now nothing measured it.

    **The premise holds today and that is a measurement rather than a
    reading of the options.** SQLAlchemy wraps the primary select in a
    subquery when a `joinedload` of a collection meets a limit, so the limit
    counts entities and the page is whole. Every member of `Loading` is
    driven through the arms below, so a member added arrives under them.

    **A join written at a call site rather than in `Loading` is outside
    every arm here**, and the coverage above is stated so often that the
    exclusion has to be stated beside it. These arms are driven off the enum,
    so what they reach is what the enum spells; `shelf.py` writes no such
    join today, which makes this an open hole rather than a live defect, and
    the arm below on `contains_eager` is the counter example rather than
    cover for it. A third reading, over the statements a route issues rather
    than over the enum's members, is what would close it.

    **Both arms expunge, and that is a dependency rather than hygiene.** A
    relationship already in the session's identity map is answered with no
    statement at all, measured at one statement for five Books, so a reading
    taken without expunging counts what the reading before it left behind
    rather than what this member loads. `TestStatementCost` pays the same
    price for the same reason. **An arm over a route cannot pay it**: the
    request opens its own session and there is nowhere to stand between its
    statements, which `tests/routers/test_books.py` states where it reads the
    driver.

    **What a short page costs, which is why it is worth an arm at all.**
    `routers/books.py` ends an export walk when a page comes back short, so
    an option that shortens a full page truncates the export to one page and
    answers 200.

    The warm up outside the counted window is `TestStatementCost`'s, for the
    reason that class records: a commit inside the window makes the session
    open a savepoint on its next statement.
    """

    #: A page, and a fan out wide enough that a joined collection could not
    #: fill it. With three tags a book, a page of three fits one book's rows.
    PAGE = 3
    TAGS = 3

    def a_shelf(self, db, viewer_id: int, count: int, titled: str = "Book") -> None:
        """`count` visible books, with tags and a collection on all but two.

        **The owner arrives as an id rather than as the fixture's `User`.**
        One arm expunges between two measurements, for the reason
        `TestStatementCost` records, and reading an attribute off a detached
        instance raises rather than reloading.

        The tags are what make a fan out exist at all: without them every
        loading option costs one row a book and the two numbers cannot come
        apart, so an arm over them would be green on an arrangement that is
        an accident of the fixture.

        **The first book has no collection and the second has no tags, and
        that is the half a fixture usually gets wrong.** A shelf where every
        book satisfies every join is a shelf on which an inner join loses
        nothing, so an arm over it cannot see the change that reads most like
        an optimisation: `innerjoin=True` on a `joinedload` of a nullable
        relationship. Both gaps land inside the first page.
        """
        collection = Collection(name=f"{titled} collection")
        db.add(collection)
        db.commit()
        books = [
            Book(
                title=f"{titled} {n:02d}",
                added_by_user_id=viewer_id,
                collection_id=None if n == 0 else collection.id,
            )
            for n in range(count)
        ]
        db.add_all(books)
        db.commit()
        for book in books[2:] + books[:1]:
            book.tags.extend(
                Tag(
                    key=f"{titled}-{book.id}-{n}",
                    name=f"{titled} {book.id} {n}",
                    category=TagCategory.CUSTOM,
                )
                for n in range(self.TAGS)
            )
        db.commit()

    @pytest.mark.parametrize("load", list(Loading))
    @pytest.mark.sqlite_only(reason="counts rows through sqlite3's row_factory, which no other driver has")
    def test_a_page_is_whole_however_this_member_loads(self, db, user, load):
        """One book more than a page, and the page still holds a page.

        This is the claim the enum rested on and nobody had measured: that
        no current option can shorten a page. It is driven off `Loading`
        itself, so a member added is measured by construction rather than by
        somebody remembering this file.

        **The page is read by its ids rather than by its length**, because
        the two failures an option can cause are different. A join over a
        collection makes the page **short**; an inner join over a nullable
        relationship keeps it full and **skips** the rows that do not match,
        which a length cannot see and which loses a book from a walk
        entirely.
        """
        viewer_id = user.id
        self.a_shelf(db, viewer_id, self.PAGE + 1)
        db.expunge_all()
        expected = [book.id for book in db.query(Book).order_by(Book.id.asc()).limit(self.PAGE).all()]
        db.expunge_all()

        with rows_at_the_engine() as seen:
            books, total = Shelf.seen_by(db, viewer_id).page(0, self.PAGE, Book.id.asc(), load=load)

        assert total == self.PAGE + 1
        assert [book.id for book in books] == expected, (
            f"{load.name} filled a page of {self.PAGE} with {len(books)} books "
            f"out of {sum(statement.rows for statement in seen)} rows, and the "
            "page was not the first page of the shelf. A join under a limit "
            "counts rows rather than books, and an inner join drops the rows "
            "with nothing on the other side."
        )

    @pytest.mark.parametrize("load", list(Loading))
    @pytest.mark.sqlite_only(reason="counts rows through sqlite3's row_factory, which no other driver has")
    def test_the_rows_behind_a_page_do_not_grow_with_the_shelf(self, db, user, load):
        """What a page's eager loads pull behind it, pinned as a relative number.

        **Relative because the absolute is unbounded in the fan out**: the
        tags behind a correct page grow with tags a book, and no page size
        makes it otherwise. What must not happen is the number following the
        **shelf**, which is what a load that escaped the page would do.

        **The sum here rather than the peak**, and the two readings answer
        different questions. The peak is what tells a second full pass from a
        correct walk, and `tests/routers/test_books.py` reads it that way over
        a whole request. This is one page of one query, and the quantity the
        enum's docstring is about is everything that page dragged behind it.
        """
        viewer_id = user.id
        self.a_shelf(db, viewer_id, self.PAGE + 1)

        def page() -> int:
            db.expunge_all()
            with rows_at_the_engine() as seen:
                Shelf.seen_by(db, viewer_id).page(0, self.PAGE, Book.id.asc(), load=load)
            return sum(statement.rows for statement in seen)

        page()  # warm up outside the window
        small = page()
        self.a_shelf(db, viewer_id, self.PAGE + 1, titled="Extra")
        grown = page()

        assert small, "no rows were recorded, so this arm watched nothing."
        assert grown == small, (
            f"{load.name} pulled {small} rows behind a page of {self.PAGE} on a "
            f"shelf of {self.PAGE + 1} and {grown} on one of "
            f"{(self.PAGE + 1) * 2}, so what it loads follows the shelf rather "
            "than the page."
        )

    @pytest.mark.sqlite_only(reason="counts rows through sqlite3's row_factory, which no other driver has")
    def test_the_rows_cannot_see_a_short_page_and_the_books_can(self, db, user):
        """The counter example that keeps these two instruments apart.

        **Nothing in `shelf.py` writes this shape**, so this is an open hole
        rather than a live defect, and it is driven here because the claim
        it falsifies is the one that would otherwise close the second ticket
        with the first one's arm. `contains_eager` over a manual join is not
        wrapped in a subquery, so the limit lands on the rows.

        A row counter compares the page it asked for against the rows it
        got, finds them equal, and passes. The books are the reading that
        fails.
        """
        self.a_shelf(db, user.id, self.PAGE + 1)
        db.expunge_all()

        with rows_at_the_engine() as seen:
            books = (
                db.query(Book)
                .join(Tag, Book.tags)
                .options(contains_eager(Book.tags))
                .order_by(Book.id)
                .limit(self.PAGE)
                .all()
            )

        assert peak_rows(seen)[Book, False] == self.PAGE
        assert len(books) < self.PAGE


class TestTheAnchoringFixesDirectionNotPresence:
    """The limit `select()` documents, pinned so it cannot be quietly restated
    as a guarantee.

    An earlier version of the module docstring claimed the anchoring stopped
    the cartesian product that `db.query(Tag.name).filter(visible_to(1))`
    produces. It does not: it fixes which table the FROM starts from, and a
    caller that forgets the join gets the cross product either way.
    """

    @staticmethod
    def _froms(query) -> int:
        """How many tables this query selects from.

        `Query.statement` is typed as a union that includes two statement kinds
        with no `get_final_froms`, so the narrowing is explicit rather than
        ignored.
        """
        statement = query.statement
        assert isinstance(statement, Select)
        return len(statement.get_final_froms())

    def test_a_select_with_no_join_is_still_a_cross_product(self, db, user):
        assert self._froms(Shelf.seen_by(db, user.id).select(Tag.name)) == 2

    def test_where_on_another_table_is_the_same_cross_product(self, db, user):
        """The twin claim, on the more used method. `where()` documents this and
        nothing measured it until now."""
        shelf = Shelf.seen_by(db, user.id).where(UserBook.rating > 3)
        assert self._froms(shelf._query) == 2

    def test_a_select_joined_outward_from_books_has_one_from(self, db, user):
        query = (
            Shelf.seen_by(db, user.id)
            .select(Tag.name, func.count(book_tags.c.book_id))
            .join(book_tags, Book.id == book_tags.c.book_id)
            .join(Tag, Tag.id == book_tags.c.tag_id)
        )
        assert self._froms(query) == 1


class TestTheNamedWaysPastTheShelf:
    def test_uniqueness_sees_a_book_the_caller_cannot(self, db, user, other):
        """The ISBN is unique across the whole table, so a clash with somebody
        else's Private Book is still a clash. A filtered check would miss the
        row that collides and turn a 409 into a 500."""
        db.add(
            Book(
                title="Private",
                isbn="9780000000019",
                added_by_user_id=user.id,
                is_private=True,
            )
        )
        db.commit()

        assert Shelf.seen_by(db, other.id).count() == 0
        taken = whole_table_for_uniqueness(db, Book.isbn).filter(Book.isbn.isnot(None)).all()
        assert [isbn for (isbn,) in taken] == ["9780000000019"]

    def test_uniqueness_sees_a_trashed_book(self, db, user):
        """The trap soft deletion introduces: a number is held by a Book in the
        bin until that Book is purged."""
        db.add(_trashed(title="Trashed", isbn="9780000000019", added_by_user_id=user.id))
        db.commit()

        held = whole_table_for_uniqueness(db).filter(Book.isbn == "9780000000019").count()
        assert held == 1

    def test_rereading_takes_ids_and_not_criteria(self, db, user):
        """It cannot quietly become a way to read the table: the only thing it
        accepts is a set of ids the caller already holds."""
        private = Book(title="Private", added_by_user_id=user.id, is_private=True)
        db.add(private)
        db.commit()

        # Given the id it re-reads the row, which is what populating a
        # relationship on rows already in hand requires.
        assert rereading_filtered_rows(db, [private.id]).count() == 1
        # Given no ids it reads nothing. There is no argument that widens it.
        assert rereading_filtered_rows(db, []).count() == 0


# ── The public shelf ──────────────────────────────────────────────────────────
#
# `Shelf.seen_by_the_public` is the one constructor with no viewer, and the
# whole safety argument for it is one property: the ownership arm does not
# exist in that path. `TestThePublicShelfHasNoOwnershipArm` is what pins it.

#: The column an ownership arm would have to be built on.
#:
#: A name rather than a literal at three assertion sites, and
#: `test_the_column_this_rule_names_is_still_a_column_on_books` is what stops it
#: going vacuous: a rename would otherwise leave every check below searching for
#: a string that appears nowhere and passing clean.
OWNER_COLUMN = "added_by_user_id"

#: The two modules the AST pass may follow a call into.
#:
#: `shelf.py` because that is where the constructor lives, and `models.py`
#: because `visible_to` and `in_trash_for` live there and are exactly what a
#: future edit would reach for. A call out of these two is not followed, which
#: is a stated blind spot rather than a claim: see the class docstring.
_FOLLOWED_MODULES = ("shelf.py", "models.py")


def _definitions(source: str) -> dict[str, list[ast.FunctionDef]]:
    """Every `def` in a module, keyed by the name a call site would write.

    Methods are keyed by their own name, so `Shelf.seen_by_the_public` and a
    module level `seen_by_the_public` would collide. Collisions are kept as a
    list and all of them are followed, which over-approximates: a guard that
    visits too much reports a leak that is not there, and a guard that visits
    too little misses one that is.

    A class name maps to that class's `__init__`, which is what makes
    `cls(...)` inside a classmethod resolve to the constructor rather than to
    nothing. Without it the body of `Shelf.__init__` would be outside the
    closure while every `seen_by*` call site goes straight through it.
    """
    tree = ast.parse(source)
    found: dict[str, list[ast.FunctionDef]] = {}

    def record(name: str, node: ast.FunctionDef) -> None:
        found.setdefault(name, []).append(node)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            record(node.name, node)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == "__init__":
                    record(node.name, member)
    return found


def _enclosing_class_of(source: str, function: str) -> str | None:
    """Which class holds `function`, so `cls(...)` inside it can be resolved."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            isinstance(member, ast.FunctionDef) and member.name == function for member in node.body
        ):
            return node.name
    return None


def _called_names(node: ast.AST) -> set[str]:
    """The names a body calls, however the call is spelled.

    `f()` and `x.f()` are both `f`, because the receiver is not knowable from
    the source and following the name is the conservative choice.
    """
    return {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name | ast.Attribute)
    }


def _reachable_from(entry: str) -> dict[str, ast.FunctionDef]:
    """The transitive closure of definitions `entry` can call, by name.

    Keyed `module:qualifier:name` so the report says where a body came from,
    and so two definitions of one name are two entries rather than one.
    """
    sources = application_sources()
    tables = {name: _definitions(sources[name]) for name in _FOLLOWED_MODULES}

    # `cls` inside a classmethod is the class it is defined on, which is how
    # `cls(db, ...)` reaches `__init__`. Resolved per module rather than
    # assumed, because the entry point could move.
    aliases: dict[str, dict[str, str]] = {}
    for module in _FOLLOWED_MODULES:
        holder = _enclosing_class_of(sources[module], entry)
        aliases[module] = {"cls": holder} if holder else {}

    visited: dict[str, ast.FunctionDef] = {}
    pending = [entry]
    while pending:
        name = pending.pop()
        for module in _FOLLOWED_MODULES:
            for index, node in enumerate(tables[module].get(name, [])):
                key = f"{module}:{index}:{name}"
                if key in visited:
                    continue
                visited[key] = node
                for called in _called_names(node):
                    pending.append(aliases[module].get(called, called))
    return visited


def _mentions(node: ast.AST, token: str) -> bool:
    """Whether a body names `token` as an attribute, a bare name or a string.

    The string arm is what catches `getattr(Book, "added_by_user_id")`. What it
    does not catch is a name assembled at runtime, which is why the SQL
    assertions below exist beside this one and are the stronger half.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == token:
            return True
        if isinstance(child, ast.Name) and child.id == token:
            return True
        if isinstance(child, ast.Constant) and child.value == token:
            return True
    return False


def _sql_after_the_projection(query) -> str:
    """Everything a compiled query says **after** its select list.

    The select list is not the subject and including it made the first version
    of this rule fail on its own correct code: an ORM query selects every mapped
    column, so `books.added_by_user_id` is named in every `SELECT` whatever the
    predicate says. Reading the column is not the leak. **Matching on it is**,
    so what is checked is the FROM, the joins and the WHERE.

    Wider than `statement.whereclause`, deliberately: an ownership arm can sit
    in a join onclause as easily as in a WHERE, and a rule that read only the
    WHERE would forgive `join(User, Book.added_by_user_id == User.id)`.
    """
    sql = str(query.statement.compile(compile_kwargs={"literal_binds": False}))
    # The split is asserted rather than assumed. SQLAlchemy compiles a newline
    # before FROM today; if that ever changes, this returns the whole statement
    # including the select list and every assertion below fails loudly rather
    # than going quiet.
    _, separator, rest = sql.partition("\nFROM ")
    assert separator, f"No FROM clause found in the compiled statement:\n{sql}"
    return rest


class TestThePublicShelfHasNoOwnershipArm:
    """The property `Shelf.seen_by_the_public` is safe by, asserted two ways.

    `visible_to(viewer_id)` is `deleted_at IS NULL AND (is_private IS false OR
    added_by_user_id = :viewer)`. The public constructor is that predicate with
    the second disjunct **removed**, not that predicate with an argument, and
    the argument for it over a sentinel viewer id is entirely that there is no
    value any input can take that makes a Private Book match. So the thing to
    pin is that the column which could make one match is never named.

    Two independent checks, because each covers what the other cannot.

    * **The AST pass** reads the source: the closure of everything
      `seen_by_the_public` can call inside `shelf.py` and `models.py`, and none
      of it may name the column. That catches a helper added later, an import
      of `visible_to`, and a `getattr` by string.
    * **The SQL assertions** read the compiled statement, which is what the
      database actually receives. That catches a name this pass cannot see: a
      string assembled at runtime, a call out to a third module, a column
      reached through a relationship.

    Neither is enough alone, and a check that only says "the owner column is
    absent" is satisfied by a query with **no predicate at all**, which is the
    worse bug. So the presence of both surviving clauses is asserted beside its
    absence.

    Stated blind spots, because a guard whose limits are undocumented is read
    as a guarantee it never made:

    * The AST closure follows a call by **name**, so a function reached
      through a variable, a dict of handlers or a decorator is not followed.
      The SQL check is what covers that class.
    * The SQL assertions are over the constructor and the narrowings a public
      caller uses. A caller that adds its own `.where(Book.added_by_user_id ==
      ...)` afterwards has written an ownership arm of its own, which is a
      different rule and is not this one's to catch.
    """

    def test_the_column_this_rule_names_is_still_a_column_on_books(self):
        """Without this every check below could pass by searching for a string
        that no longer appears anywhere.

        The mapped attribute **and** the SQL column, because the AST pass reads
        the first and the SQL assertions read the second, and a rename that
        moved only one of them would leave half this class vacuous.
        """
        assert hasattr(Book, OWNER_COLUMN), (
            f"{OWNER_COLUMN} is no longer an attribute of Book. Every check in "
            "this class searches for that name, so they now all pass by "
            "finding nothing. Rename the constant with the column."
        )
        assert OWNER_COLUMN in Book.__table__.c, f"{OWNER_COLUMN} is no longer a column of the books table."

    def test_the_constructor_this_rule_guards_exists(self):
        """A guard whose subject has been deleted passes clean, which has
        happened twice in this repository. This is the check that does not."""
        found = [key for key in _reachable_from("seen_by_the_public") if key.endswith(":seen_by_the_public")]
        assert found, (
            "Shelf.seen_by_the_public was not found in shelf.py. Either it was "
            "renamed, in which case rename it here too, or it was removed, in "
            "which case the public catalogue has lost the only query path that "
            "has no ownership arm."
        )

    def test_nothing_the_public_constructor_can_call_names_the_owner_column(self):
        """The AST half: the closure, not just the body.

        The body alone would be satisfied by `predicate = visible_to(0)`, which
        is precisely the sentinel shape that was refused.
        """
        offenders = sorted(
            key
            for key, node in _reachable_from("seen_by_the_public").items()
            if _mentions(node, OWNER_COLUMN)
        )
        assert offenders == [], (
            f"These bodies are reachable from Shelf.seen_by_the_public and name "
            f"{OWNER_COLUMN}: {offenders}.\n\n"
            "That column is the ownership arm. The public constructor is safe "
            "because the arm does not exist in its path, not because the value "
            "compared against it is chosen carefully: a sentinel id is a real "
            "comparison against a real column and is safe only while no account "
            "holds that id, which nothing enforces. If a public reader needs to "
            "be told which books are theirs, they are not a public reader."
        )

    def test_the_public_query_does_not_mention_the_owner_column(self, db):
        public = Shelf.seen_by_the_public(db)
        assert OWNER_COLUMN not in _sql_after_the_projection(public._query)

    def test_the_public_query_still_applies_both_surviving_clauses(self, db):
        """The half that stops the check above being satisfied by no predicate
        at all, which would be the worse bug and would read as a pass."""
        sql = _sql_after_the_projection(Shelf.seen_by_the_public(db)._query)
        assert "is_private" in sql
        assert "deleted_at" in sql

    def test_the_owner_column_survives_neither_the_filter_chain_nor_a_select(self, db):
        """Every narrowing a public caller reaches for, not only the
        constructor. `matching` is the whole filter chain and `select` rebuilds
        the query from the stored criteria, so either could reintroduce it."""
        shelf = Shelf.seen_by_the_public(db).matching(BookFilters(q="dune", series="Dune", location="study"))
        assert OWNER_COLUMN not in _sql_after_the_projection(shelf._query)
        assert OWNER_COLUMN not in _sql_after_the_projection(shelf.select(Book.location))

    def test_seen_by_still_has_the_arm_this_one_lacks(self, db, user):
        """The diagonal. Without it every assertion above would pass on a
        `visible_to` that had quietly stopped scoping to a member at all, and
        on a `_sql_after_the_projection` that returned the empty string."""
        member = Shelf.seen_by(db, user.id)
        assert OWNER_COLUMN in _sql_after_the_projection(member._query)


class TestThePublicShelfShowsOnlyWhatWasPublished:
    """What the constructor actually returns, against rows in a database."""

    def test_a_public_book_on_the_shelf_is_shown(self, db, user):
        db.add(Book(title="Public", added_by_user_id=user.id))
        db.commit()
        assert Shelf.seen_by_the_public(db).count() == 1

    def test_a_private_book_is_absent_whoever_added_it(self, db, user, other):
        db.add(Book(title="Mine", added_by_user_id=user.id, is_private=True))
        db.add(Book(title="Theirs", added_by_user_id=other.id, is_private=True))
        db.commit()
        assert Shelf.seen_by_the_public(db).count() == 0

    def test_a_trashed_public_book_is_absent(self, db, user):
        db.add(_trashed(title="Trashed", added_by_user_id=user.id))
        db.commit()
        assert Shelf.seen_by_the_public(db).count() == 0

    def test_a_book_with_no_member_behind_it_is_still_shown(self, db):
        """`added_by_user_id` is nullable, and a restore or an import can leave
        it null. A predicate built on that column would have to decide what
        null means; this one never asks."""
        db.add(Book(title="Orphan"))
        db.commit()
        assert Shelf.seen_by_the_public(db).count() == 1

    def test_it_is_stricter_than_any_member_shelf(self, db, user, other):
        """The fail safe direction, asserted rather than argued: an
        authenticated request wrongly routed through here sees less."""
        db.add(Book(title="Public", added_by_user_id=other.id))
        db.add(Book(title="Mine", added_by_user_id=user.id, is_private=True))
        db.commit()
        assert Shelf.seen_by(db, user.id).count() == 2
        assert Shelf.seen_by_the_public(db).count() == 1


class TestAShelfWithNoViewerRefusesAPerMemberNarrowing:
    """The two narrowings that read a member, on a shelf that has none.

    Two rather than three, counted: `_with_read_status` and `_unrated` read
    `_viewer`, and `_offered_for_discussion` reads anybody's flag rather than
    the viewer's, which is why the last test here asserts it is **allowed**.
    Three of the four cases below drive `_with_read_status`, because its two
    arms fail in opposite directions.

    Silently they would be answered rather than refused, and the answer would
    be wrong rather than empty: `UserBook.user_id == None` compiles to `IS
    NULL`, so the outer join in `_with_read_status` matches nothing and
    `status=unread`, whose branch also accepts a missing row, returns the whole
    public catalogue.
    """

    def test_narrowing_by_read_status_is_refused(self, db):
        with pytest.raises(ValueError, match="no viewer"):
            Shelf.seen_by_the_public(db).matching(BookFilters(status=ReadStatus.READ))

    def test_narrowing_to_unread_is_refused_too(self, db, user):
        """The arm that would have returned everything rather than nothing, so
        the one a test asserting emptiness would have missed."""
        db.add(Book(title="Public", added_by_user_id=user.id))
        db.commit()
        with pytest.raises(ValueError, match="no viewer"):
            Shelf.seen_by_the_public(db).matching(BookFilters(status=ReadStatus.UNREAD))

    def test_narrowing_to_unrated_is_refused(self, db):
        with pytest.raises(ValueError, match="no viewer"):
            Shelf.seen_by_the_public(db).matching(BookFilters(unrated=True))

    def test_a_narrowing_that_reads_no_member_is_allowed(self, db, user):
        """`discuss` is anybody's flag rather than the viewer's, which is why
        it is not in the list above. Asserted so the refusal is known to be
        about the viewer rather than about the public shelf."""
        db.add(Book(title="Public", added_by_user_id=user.id))
        db.commit()
        assert Shelf.seen_by_the_public(db).matching(BookFilters(discuss=True)).count() == 0


class TestEverySortHasAnOrdering:
    """`order_for` reads two tables, and a value in neither is a 500.

    Both docstrings in `shelf.py` claimed this file pinned the partition and it
    did not, which is the shape a critic seat is for: the claim was true about
    the code and false about the test. A ninth `BookSort` member added to the
    enum and to neither table would have shipped as a `KeyError` on a request,
    at a value the caller chooses.
    """

    def test_the_two_tables_partition_the_enum(self):
        one_column = set(_SORT_CLAUSES)
        many_columns = set(_MULTI_COLUMN_ORDERS)

        assert one_column | many_columns == set(BookSort)
        assert one_column & many_columns == set()

    def test_the_shelf_sorts_cover_every_scheme_that_files_a_shelf(self):
        """`shelf._SHELF_SORTS` says this class pins this, so it does.

        Two vocabularies that cannot derive each other: `BookSort` is the API's
        and a scheme is the catalogue's. Without this assertion
        `filing.SHELF_SCHEMES` and `orders_a_shelf` were read by nothing in
        production, three documents said they were the mechanism, and both
        critic seats found that independently on 2026-09-03. A scheme whose
        rule starts ordering a shelf is now a failing test rather than an order
        no client can ask for.
        """
        assert set(_SHELF_SORTS.values()) == set(filing.SHELF_SCHEMES)

    def test_a_scheme_that_files_no_shelf_cannot_be_given_a_sort(self):
        """The other half, and the one that is enforced rather than compared.

        `_shelf_order` refuses at import, so giving GND a `BookSort` member and
        mapping it in `_SHELF_SORTS` breaks the build instead of shipping a
        shelf ordered by a subject vocabulary. `BookSort` has no GND member, so
        this drives the refusal directly rather than pretending one exists.
        """
        with pytest.raises(ValueError, match="orders no shelf"):
            shelf_module._shelf_order(ClassificationScheme.GND)

    @pytest.mark.parametrize("sort", list(BookSort))
    def test_every_value_produces_an_ordering(self, sort):
        """The property the partition exists for, asserted directly.

        Parametrised over the enum rather than over a list written here, so a
        new member is covered the day it is added rather than the day somebody
        remembers this file.
        """
        clauses = order_for(sort)

        assert clauses
        assert clauses[-1].compare(Book.id.asc())


class TestTheDivisionProjectionsAgree:
    """The Dewey division is projected twice, in Python and in SQL, and the two
    have to give the same answer.

    `ddc.division` serves the parser and the facet's labels; `shelf._division_key`
    serves the filter and the facet's grouping. They are different expressions
    over the same rule, so nothing but a comparison keeps them together.
    `_division_key` claimed this test existed before it did.
    """

    @staticmethod
    def _sql(db, expression):
        """One scalar, evaluated by the database rather than reimplemented here.

        That is the point of the whole class: a test that recomputed `substr`
        in Python would agree with itself and say nothing about SQLite.
        """
        return db.execute(select(expression)).scalar_one()

    def test_across_every_three_digit_number(self, db):
        """All 1,000 of them, not a sample."""
        mismatches = [
            (number, in_sql, ddc.division(number))
            for number in (f"{n:03d}" for n in range(1000))
            if f"{(in_sql := self._sql(db, _division_key(literal(number))))}0" != ddc.division(number)
        ]

        assert mismatches == []

    def test_the_sql_guard_never_admits_what_cannot_be_projected(self, db):
        """The other half of the pair, over the shapes that are not notations.

        `_looks_like_a_notation` is deliberately weaker than `ddc.notation`: it
        tests three leading digits and nothing else, because it guards a row
        written before the validator existed rather than parsing one. What must
        hold is that it never *admits* something the projection cannot turn into
        a division, which is what put a fabricated `He0` in the facet.
        """
        admitted_but_unprojectable = []
        for candidate in [
            "Hello world",
            "</script><b>x",
            "BF575.S75 E64 2022",
            "12x",
            "1",
            "",
            "04",
            "0004",
            "004",
            "155.9042",
        ]:
            if not self._sql(db, _looks_like_a_notation(literal(candidate))):
                continue
            key = self._sql(db, _division_key(literal(candidate)))
            if not (len(key) == 2 and key.isdigit()):
                admitted_but_unprojectable.append((candidate, key))

        assert admitted_but_unprojectable == []

    def test_admits_the_numbers_a_catalogue_actually_supplies(self, db):
        """So the guard above cannot pass by refusing everything."""
        admitted = [
            number
            for number in ("004", "005.133", "155.9042", "330", "830")
            if self._sql(db, _looks_like_a_notation(literal(number)))
        ]

        assert admitted == ["004", "005.133", "155.9042", "330", "830"]

    def test_refuses_the_row_that_produced_a_fabricated_division(self, db):
        """`He0` was a real facet entry. Pinned so it cannot come back."""
        assert self._sql(db, _looks_like_a_notation(literal("Hello world"))) is False


class TestTheStoredKeyIsTheRulesKey:
    """`classifications.sort_key` holds what the scheme's rule returned, and
    every path that writes the table has to put it there.

    The rule used to be written twice, in Python and in SQL, and this class
    compared the two. There is one implementation now and the SQL is deleted, so
    what needs holding together is the **write path** and the rule: an ORM
    insert, an ORM update of either column it derives from, and
    `backup.restore`, which inserts through Core and fires no validator.

    Read back out of SQLite rather than off the instance, because half of what
    this checks is that the value survives the column: a key is longer than the
    number it files, and `models.CLASSIFICATION_SORT_KEY_MAX` is the bound that
    says how much longer.

    The corpus is `tests/test_filing.py::CORPUS`, which reaches all twelve class
    shapes twice over. Its own coverage is guarded there.
    """

    @staticmethod
    def _stored(db, scheme, number):
        """The key SQLite holds for a row written through the ORM."""
        book = Book(title="Filed", added_by_user_id=None)
        db.add(book)
        db.flush()
        row = Classification(book_id=book.id, scheme=scheme, number=number)
        db.add(row)
        db.flush()
        db.expire(row)
        return row.sort_key

    @pytest.mark.parametrize("scheme", list(ClassificationScheme))
    def test_across_every_scheme_and_the_whole_corpus(self, db, user, scheme):
        """Parametrised over the enum, so a fifth scheme is covered the day it
        is added rather than the day somebody remembers this file."""
        rule = filing.rule_for(scheme)
        mismatches = [
            (value, stored, rule.sort_key(value))
            for value in CORPUS
            if (stored := self._stored(db, scheme, value)) != rule.sort_key(value)
        ]

        assert mismatches == []

    def test_changing_the_number_refiles_the_row(self, db, user):
        """The half a write-time derivation gets wrong. Nothing renames a
        classification today, and `Collection._fold_the_name` is here for the
        same reason: a derivation a writer could forget will be forgotten."""
        book = Book(title="Refiled", added_by_user_id=user.id)
        db.add(book)
        db.flush()
        row = Classification(book_id=book.id, scheme=ClassificationScheme.LCC, number="BF75")
        db.add(row)
        db.flush()

        row.number = "BF575"
        db.flush()
        db.expire(row)

        assert row.sort_key == filing.LIBRARY_OF_CONGRESS.sort_key("BF575")

    def test_changing_the_scheme_refiles_the_row(self, db, user):
        """The other column the key is derived from. `005.13/3` keys differently
        under Dewey, which drops the segmentation prime, than under the generic
        rule, which does not."""
        book = Book(title="Rescheming", added_by_user_id=user.id)
        db.add(book)
        db.flush()
        row = Classification(book_id=book.id, scheme=ClassificationScheme.GND, number="005.13/3")
        db.add(row)
        db.flush()
        assert row.sort_key == "005.13/3"

        row.scheme = ClassificationScheme.DDC
        db.flush()
        db.expire(row)

        assert row.sort_key == "005.133"

    def test_the_two_columns_may_be_given_in_either_order(self, db, user):
        """The trap `Tag._drop_the_key_on_a_rename` records: SQLAlchemy assigns
        constructor kwargs in the order given, so a hook reading a sibling
        attribute depends on which was assigned first. Whichever of the two is
        set second recomputes the key with the first already there.
        """
        book = Book(title="Either way", added_by_user_id=user.id)
        db.add(book)
        db.flush()
        scheme_first = Classification(book_id=book.id, scheme=ClassificationScheme.LCC, number="BF75")
        number_first = Classification(number="BF75", scheme=ClassificationScheme.LCC, book_id=book.id)

        assert scheme_first.sort_key == number_first.sort_key
        assert scheme_first.sort_key == filing.LIBRARY_OF_CONGRESS.sort_key("BF75")

    def test_a_writer_that_skips_the_hook_is_refused_rather_than_filed_last(self, db, user):
        """The enforcement, and the reason the column is NOT NULL with no default.

        A null key files last under `nullslast`, so a row written past the hook
        would sit at the end of every shelf order with nothing to see: the book
        is there, its number is right, and only its position is wrong. This
        makes that write raise instead.
        """
        book = Book(title="Unfiled", added_by_user_id=user.id)
        db.add(book)
        db.flush()

        with pytest.raises(IntegrityError):
            db.execute(
                Base.metadata.tables["classifications"].insert(),
                [{"book_id": book.id, "scheme": "lcc", "number": "BF75"}],
            )


class TestTheShelfOrdersByEachSchemesOwnRule:
    """The property the whole of `filing.py` exists for, through a real query."""

    @staticmethod
    def _shelf(db, user, sort):
        books, _ = Shelf.seen_by(db, user.id).page(0, 30, *order_for(sort))
        return [book.title for book in books]

    @staticmethod
    def _file(db, user, title, scheme, number):
        book = Book(title=title, added_by_user_id=user.id)
        db.add(book)
        db.flush()
        db.add(Classification(book_id=book.id, scheme=scheme, number=number))
        return book

    def test_a_library_of_congress_shelf_is_in_shelf_order(self, db):
        """Nine call numbers, filed as a shelf files them.

        `BF75` before `BF575`, because the class number sorts numerically and
        not as text. `BF575` before its own cuttered books, and all of class
        575 before class 575.5, because 575 is less than 575.5 whatever cutter
        a book in it carries. The first draft of this expectation had the
        decimal extension before the cutters and was wrong; the code was right.
        """
        user = User(username="kim", email="k@example.invalid", password_hash="x")
        db.add(user)
        db.flush()
        shelf = [
            ("a", "BF75"),
            ("b", "BF100.5"),
            ("c", "BF575"),
            ("d", "BF575 1999"),
            ("e", "BF575.S75 E64 2022"),
            ("f", "BF575.S8 A1 1990"),
            ("g", "BF575.5.S75"),
            ("h", "Q1"),
            ("i", "QA76.73.J38"),
        ]
        for title, number in reversed(shelf):
            self._file(db, user, title, ClassificationScheme.LCC, number)
        db.commit()

        assert self._shelf(db, user, BookSort.LCC) == [t for t, _ in shelf]

    def test_the_text_order_those_numbers_would_have_had(self, db):
        """The defect, stated as the thing the rule is not.

        Ordering the same nine as text puts `BF75` seventh instead of first,
        which is what a Dewey rule applied to a Library of Congress column did.
        Derived here rather than asserted, so it cannot go stale against the
        list above.
        """
        numbers = [
            "BF75",
            "BF100.5",
            "BF575",
            "BF575 1999",
            "BF575.S75 E64 2022",
            "BF575.S8 A1 1990",
            "BF575.5.S75",
            "Q1",
            "QA76.73.J38",
        ]

        assert sorted(numbers).index("BF75") == 6

    def test_a_dewey_shelf_files_a_segmentation_prime_where_the_notation_goes(self, db):
        """`005.1/33` is `005.133` and files after `005.12`, not before it.

        The prime reaches the column because `ClassificationIn` validates
        through `ddc.notation` without writing its answer back.
        """
        user = User(username="ana", email="a@example.invalid", password_hash="x")
        db.add(user)
        db.flush()
        self._file(db, user, "primed", ClassificationScheme.DDC, "005.1/33")
        self._file(db, user, "plain", ClassificationScheme.DDC, "005.12")
        db.commit()

        assert self._shelf(db, user, BookSort.DDC) == ["plain", "primed"]
        assert sorted(["005.1/33", "005.12"]) == ["005.1/33", "005.12"]


#: A route is a function carrying an HTTP verb decorator, whatever the router
#: object is called. Matching `router.` instead missed 2 of 107 routes, because
#: `routers/public.py` declares a second router named `catalogue`, and a
#: `SERIALISED` call site added through that door moved no number and failed no
#: test.
_HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def _book_dependency(annotation) -> str | None:
    """The function inside `Annotated[Book, Depends(f)]`, or None.

    Shared by the alias derivation and the chain walk in
    `TestTheRoutesThisDocstringCounts`, which need the same question answered
    about a module level assignment and about a parameter annotation. It tests
    for `Book` specifically, so `Annotated[Session, Depends(get_db)]` beside it
    in the same signature is not mistaken for a link in the chain.
    """
    import ast

    if annotation is None:
        return None
    if not isinstance(annotation, ast.Subscript):
        return None
    if ast.unparse(annotation.value) != "Annotated":
        return None
    parts = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    if not parts or ast.unparse(parts[0]) != "Book":
        return None
    for part in parts[1:]:
        if isinstance(part, ast.Call) and ast.unparse(part.func) == "Depends" and part.args:
            return ast.unparse(part.args[0])
    return None


def _fetch_chain(tree) -> tuple[dict[str, bool], dict[str, str | None]]:
    """Per dependency function: does it fetch SERIALISED, and what it depends on.

    The two maps `_root_that_fetches` walks. Split out of the alias derivation
    so the route scan can use the identical rule on a parameter written in
    place, which was the third enumeration this class had to lose.
    """
    import ast

    fetches: dict[str, bool] = {}
    parents: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        fetches[node.name] = any(
            any(kw.arg == "load" and ast.unparse(kw.value) == "Loading.SERIALISED" for kw in call.keywords)
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
        parents[node.name] = None
        for arg in node.args.args + node.args.kwonlyargs:
            depended = _book_dependency(arg.annotation)
            if depended is not None:
                parents[node.name] = depended
    return fetches, parents


def _root_that_fetches(
    function: str | None,
    fetches: dict[str, bool],
    parents: dict[str, str | None],
) -> str | None:
    """Walk `Depends` to whichever link carries `load=Loading.SERIALISED`.

    Shared by the alias derivation and by the route scan, which is the point:
    an alias and a route spelling the dependency **inline** resolve to the same
    fetch, and counting only the first is an enumeration wearing a derivation's
    clothes. A chain with no fetch returns None, which is how `book_for_cover`
    is excluded by construction rather than by omission.
    """
    seen: set[str] = set()
    while function is not None and function not in seen:
        if fetches.get(function):
            return function
        seen.add(function)
        function = parents.get(function)
    return None


class TestTheRoutesThisDocstringCounts:
    """`Loading`'s docstring counts routes, and a count in prose goes stale.

    It states that 17 of the 33 routes reaching `book_for_read` or
    `book_in_trash` do not serialise the Book they read, split 11 that
    serialise a sub-resource, 5 that answer 204 and serialise nothing, and
    `add_copy`, which serialises the copy. Those numbers are the evidence for
    the sentence a reader uses to judge a new `Loading.SERIALISED` call site.

    **Two breakdowns were written before this one and both were wrong**, by
    two parties deriving them separately: `19` with a split of `16/2`, then
    `17` with a split of `14/2`, against the tree's `17` and `11/5`. The first
    counted the enrichment family as three routes when only
    `enrich/candidates` qualifies; the second filed the note, quote and
    progress deletes as sub-resource routes when they answer 204 and serialise
    nothing, exactly like the two book deletes beside them.

    **Each bucket is asserted separately and that is the point.** A guard on
    the total alone passes when one bucket moves and another moves back, which
    is what 14/2 and 11/5 are: same total, same everything else, and only the
    three deletes moved. The first draft of this class made exactly that
    mistake.

    **The universe this counts over is derived twice, and both derivations
    replaced an enumeration that a review seat evaded.** They are stated here
    rather than left to be discovered:

    * a **route** is any function carrying an HTTP verb decorator, whatever the
      router object is called. The first draft matched `router.` and so missed
      2 of 107, because `routers/public.py` declares a second router named
      `catalogue`; a `SERIALISED` call site added there moved no number and
      failed no test.
    * a **dependency** is resolved by following `Depends` through each
      dependency's own signature to whichever link carries
      `load=Loading.SERIALISED`. The first draft held a list of four alias
      names, and a 34th route on a fifth alias measured 33 against 33.

    Both holes were found by attacking rather than by reading, by two seats
    independently, and neither could be caught by any mutation that moves a
    number inside a universe the guard already sees. Both evasions are kept as
    mutations, which is why this class is worth more than the count it asserts.

    What it still does not see, named rather than left to be found: a route
    reached through `include_router` on a prefix this repository does not use.

    The other blind spot a reader would reasonably expect, a dependency that
    fetches SERIALISED without spelling `load=` as a keyword, **cannot occur**:
    `Shelf.all`, `Shelf.first` and `Shelf.page` all put `load` after a `*`, so
    it is keyword only and the signature closes it. Naming a blind spot that
    cannot happen would be safe but misleading, which is why this says which
    one it is.
    """

    @staticmethod
    def _dependency_aliases(source: str | None = None) -> dict[str, str]:
        """Every `Annotated[Book, Depends(...)]` alias that fetches SERIALISED.

        **Derived from `dependencies.py`, never listed here**, and that is the
        whole point of the method. The first version of this class carried a
        hard-coded map of four alias names, so it could only count routes
        spelled with a name somebody had already thought of: a fifth alias, or
        a rename, left every number in both docstrings stale with all seven
        tests green. None of the five mutations could find it either, because
        each of them moved something inside the universe the map already saw.

        So the discriminator is the thing that actually matters, `load=`
        carrying `Loading.SERIALISED`, followed through the chain: an alias
        points at a dependency, that dependency may take another Book
        dependency as a parameter, and the fetch lives at the end of it.
        `BookForCover` is excluded by construction rather than by omission,
        because `book_for_cover` fetches with no `load=` at all.

        Returns alias name to the name of the function that carries the fetch,
        not the immediate dependency, so `BookForWrite` resolves to
        `book_for_read` and `book_for_read`'s own count stays derivable.
        """
        import ast
        import pathlib

        if source is None:
            source = (pathlib.Path(__file__).resolve().parent.parent / "dependencies.py").read_text()
        tree = ast.parse(source)

        fetches, parents = _fetch_chain(tree)

        aliases: dict[str, str] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            function = _book_dependency(node.value)
            root = _root_that_fetches(function, fetches, parents)
            if root is not None:
                aliases[target.id] = root
        return aliases

    @classmethod
    def _routes(cls):
        """Every routed function taking one of those, classified.

        Yields `(name, dependency, bucket)` where bucket is one of `own`,
        `copy`, `nothing` or `sub_resource`. `own` and `copy` are separated
        because `add_copy` calls the serialiser on the **copy**, so a guard
        asking only "does this call `book_to_out`" files it on the wrong side
        and 17 comes out as 16.
        """
        import ast
        import pathlib

        aliases = cls._dependency_aliases()
        # The same two maps the alias derivation walks, so a route spelling the
        # dependency inline resolves by the identical rule rather than by being
        # absent from a list of alias names.
        backend = pathlib.Path(__file__).resolve().parent.parent
        fetches, parents = _fetch_chain(ast.parse((backend / "dependencies.py").read_text()))
        out = []
        routers = backend / "routers"
        for path in sorted(routers.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not any(
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in _HTTP_VERBS
                    for decorator in node.decorator_list
                ):
                    continue
                dependency = argument = None
                for arg in node.args.args + node.args.kwonlyargs:
                    annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                    resolved = aliases.get(annotation) or _root_that_fetches(
                        _book_dependency(arg.annotation), fetches, parents
                    )
                    if resolved is not None:
                        dependency = resolved
                        argument = arg.arg
                if dependency is None:
                    continue
                own = other = False
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call):
                        continue
                    if not isinstance(call.func, ast.Name):
                        continue
                    if call.func.id not in ("book_to_out", "books_to_out"):
                        continue
                    first = ast.unparse(call.args[0]) if call.args else ""
                    if first in (argument, f"[{argument}]"):
                        own = True
                    else:
                        other = True
                returns = ast.unparse(node.returns) if node.returns else "None"
                if own:
                    bucket = "own"
                elif other:
                    bucket = "copy"
                elif returns == "None":
                    bucket = "nothing"
                else:
                    bucket = "sub_resource"
                out.append((node.name, dependency, bucket))
        return out

    @staticmethod
    def _stated(pattern: str) -> int:
        """A number read out of the `Loading` docstring, so prose is the subject."""
        import re

        match = re.search(pattern, Loading.__doc__ or "")
        assert match is not None, f"the docstring no longer states {pattern!r}"
        return int(match.group(1))

    def _bucket(self, name: str) -> list[str]:
        return sorted(r[0] for r in self._routes() if r[2] == name)

    def test_the_number_of_routes_on_those_dependencies_is_the_stated_one(self):
        assert len(self._routes()) == self._stated(r"of the (\d+) routes\*\*")

    def test_the_number_that_do_not_serialise_their_own_book_is_the_stated_one(self):
        falsifying = [r for r in self._routes() if r[2] != "own"]
        assert len(falsifying) == self._stated(r"\*\*(\d+) of the \d+ routes\*\*")

    def test_the_sub_resource_count_is_the_stated_one(self):
        assert len(self._bucket("sub_resource")) == self._stated(r"\*\*(\d+)\*\* serialise a sub-resource")

    def test_the_count_that_serialises_nothing_is_the_stated_one(self):
        """Asserted apart from the sub-resource count, not summed with it."""
        assert len(self._bucket("nothing")) == self._stated(r"\*\*(\d+)\*\* answer 204 and serialise nothing")

    def test_the_three_sub_resource_deletes_are_counted_as_serialising_nothing(self):
        """The three routes the two review seats put in different buckets.

        Named rather than counted, because the disagreement was about these
        three specifically and a count would go quiet if one were renamed.
        """
        nothing = self._bucket("nothing")
        assert {"delete_note", "delete_quote", "delete_progress"} <= set(nothing)
        assert {"delete_book", "purge_book"} <= set(nothing)

    def test_exactly_one_route_serialises_a_book_other_than_the_one_it_read(self):
        assert self._bucket("copy") == ["add_copy"]

    def test_the_aliases_are_derived_from_the_fetch_not_from_a_list(self):
        """The four aliases, and that `BookForCover` is excluded for a reason.

        `book_for_cover` reads the same book by the same rule and fetches with
        no `load=`, so it is the discriminator this derivation turns on. If it
        ever appears here, the walk has stopped asking about the fetch and
        started matching names again, which is the defect the derivation
        replaced.
        """
        aliases = self._dependency_aliases()

        assert aliases == {
            "BookForRead": "book_for_read",
            "BookInTrash": "book_in_trash",
            "BookForWrite": "book_for_read",
            "BookForOwner": "book_for_read",
        }

    def test_a_new_alias_would_be_counted_without_editing_this_file(self):
        """The evasion the hard-coded map could not see, run against itself.

        A fifth alias pointing at a dependency that fetches SERIALISED is
        resolved by the same walk, so the counts move and the tests above fail
        rather than going quietly stale. Asserted by deriving from a copy of
        `dependencies.py` with one alias appended, because the real file has
        four and a guard proved only on those four is the thing being fixed.
        """
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "dependencies.py").read_text()
        mutated = source + "\n\nBookForSomethingNew = Annotated[Book, Depends(book_for_write)]\n"

        aliases = self._dependency_aliases(mutated)

        # Resolved through `book_for_write` to the link that carries the fetch,
        # which is the whole walk: the alias scan, the chain, and the root.
        assert aliases["BookForSomethingNew"] == "book_for_read"
        # And the discriminator still bites on the same text, so this cannot
        # pass by the walk having been replaced with a list of every alias.
        assert "BookForCover" not in aliases

    def test_the_dependency_docstring_counts_are_the_stated_ones(self):
        """`dependencies.book_for_read` states its own pair, and the
        denominator is different: it excludes the two trash routes."""
        import re

        from dependencies import book_for_read

        stated = re.search(
            r"\*\*(\d+) of\s+the (\d+)\*\* routes fed from here serialise no Book",
            " ".join((book_for_read.__doc__ or "").split()),
        )
        assert stated is not None, "book_for_read no longer states its counts"
        mine = [r for r in self._routes() if r[1] == "book_for_read"]
        silent = [r for r in mine if r[2] in ("nothing", "sub_resource")]
        assert (len(silent), len(mine)) == (int(stated.group(1)), int(stated.group(2)))


# ── What may leave the instance ───────────────────────────────────────────────


#: The type that says a set of rows may leave the instance.
_OUTBOUND = frozenset({"Outbound"})


def _outbound_constructions(source: str) -> list[str]:
    """Every construction of `shelf.Outbound` in one module, as `name:line`.

    **Which local names mean that type is `_entity_aliases`' question**, asked
    of `shelf` rather than of `models`. Written with its own import scan it
    followed `from shelf import Outbound as Rows` and walked past
    `Mk = Outbound`, which is the rebinding the shared resolver has followed
    since it was written for `Book`.

    The attribute arm is this rule's own, because `shelf.Outbound(...)` binds no
    local name at all. It is deliberately blunt and reports `x.Outbound(...)`
    for any `x`: a false report on some other module's `Outbound` costs a person
    one look, and a missed one costs a private Book.

    **Three shapes name the type nowhere and this rule cannot see any of them**:
    `dataclasses.replace(rows, ...)`, `copy.replace(rows, ...)` and
    `type(rows)(...)`. The reason first written here was that all three need a
    genuine `Outbound` in hand and so only widen rows a caller was already
    given. **That was wrong**, and the security seat measured it: an empty
    `Outbound` is one `outbound_page(0, 0)` away, so the value in hand is a token
    rather than a constraint on the rows. `Outbound.__post_init__` is what
    actually refuses all three; this rule is the half that fails in CI on a
    construction that is merely written.
    """
    tree = ast.parse(source)
    local_names = _entity_aliases(tree, _OUTBOUND, module="shelf")

    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        by_name = isinstance(func, ast.Name) and func.id in local_names
        by_attribute = isinstance(func, ast.Attribute) and func.attr == "Outbound"
        if by_name or by_attribute:
            found.append(str(node.lineno))
    return found


class TestOnlyTheShelfSaysWhatMayLeave:
    """The privacy rule at the boundary: a private Book is never **sent**.

    `TestTheShelfIsTheOnlyWayIn` above holds the query side, and it stops where
    a query returns: once a `Book` is in a list, nothing on it records whose
    shelf produced it. `shelf.Outbound` is the type that carries the missing
    fact, and these are the two halves that make it worth anything: that nothing
    but `shelf.py` mints one, and that the only shelf which can mint one has no
    ownership arm.

    **What it cannot see**, because a guard whose limits are unstated is read as
    a guarantee it never made:

    * **A payload that is not built by a serialiser taking `Outbound`.** MARC's
      `record_element` takes a bare `Book` and always will, for the reason
      `shelf.Outbound` gives. `sru._records_element` is what holds the SRU
      server, because it takes the type and the loop is inside it.
    * **Anything that leaves by something other than a route.**
      `tests/test_nothing_private_leaves.py` sweeps the routes and its docstring
      lists what that misses.
    * **Disclosure that is not a row.** A count, a gap in the ids, the number of
      records an SRU response reports: none is a Book and none is caught here.
      `schemas/public.py` records the id gap as a known one.
    * **Any construction that does not name the type**, which is the family
      `Outbound.__post_init__` exists to refuse rather than this rule.
    * **A construction in a test**, since `application_sources()` excludes `tests/`.
      That is not a hatch any more: `__post_init__` refuses a test like anything
      else, which `TestOnlyTheShelfCanMintOne` asserts, and nothing in the tree
      relies on minting one by hand.
    * **Fabricating an instance without constructing one.**
      `Outbound.__new__(Outbound)` then `object.__setattr__(o, "books", ...)`
      holds any rows and is seen by neither guard, because it never runs
      `__init__`. Named rather than closed: it is not a shape anybody reaches
      for by accident, and this file's standard is that a way round is named.
    """

    def test_nothing_outside_the_shelf_constructs_one(self):
        offenders = sorted(
            f"{name}:{line}"
            for name, source in application_sources().items()
            if name != "shelf.py"
            for line in _outbound_constructions(source)
        )
        assert offenders == [], (
            f"These statements mint an Outbound outside shelf.py: {offenders}. "
            "That type means the rows came off a shelf with no viewer, and "
            "building one by hand is asserting that rather than proving it. "
            "Ask `Shelf.seen_by_the_public(db).outbound_page(...)` instead, or "
            "bring the reason here the way the named ways past a viewer do."
        )

    @pytest.mark.parametrize(
        "spelling",
        [
            "from shelf import Outbound\nrows = Outbound(books=())\n",
            "from shelf import Outbound as Rows\nrows = Rows(books=())\n",
            "import shelf\nrows = shelf.Outbound(books=())\n",
            "from shelf import Outbound\nMk = Outbound\nrows = Mk(books=())\n",
            "from shelf import Outbound\nMk: type = Outbound\nrows = Mk(books=())\n",
        ],
        ids=["imported", "aliased", "attribute", "rebound", "rebound annotated"],
    )
    def test_the_rule_catches_each_spelling(self, spelling):
        """The diagonal, one mutation each.

        Each spelling is asserted on its own, because a sample carrying two of
        them would pass with either arm deleted and would never say which arm
        caught it. **No count here**: this docstring carried one, the list grew
        by two, and the number went stale in the round that fixed another stale
        number.
        """
        assert _outbound_constructions(spelling) != []

    def test_the_rule_does_not_report_an_annotation_or_an_import(self):
        """The other side of the diagonal: reporting every mention would make
        the rule above unusable, since the serialisers must name the type to
        take it, and an unusable rule is one somebody deletes."""
        assert (
            _outbound_constructions(
                "from shelf import Outbound\ndef f(rows: Outbound) -> int:\n    return len(rows)\n"
            )
            == []
        )

    def test_the_only_shelf_with_no_viewer_is_the_public_one(self, db):
        """The value the rule above rests on, pinned where the rule cannot see
        it move.

        `Outbound` is worth something only because a shelf with no viewer is a
        shelf with no ownership arm. That is true of `seen_by_the_public` and of
        nothing else today, and a second viewerless constructor added tomorrow
        would widen what may leave the instance without touching a line of the
        guard above.

        **Derived from the class**, so a constructor added and not classified
        fails this rather than passing unnoticed.
        """
        viewerless = set()
        for name in dir(shelf_module.Shelf):
            attribute = inspect.getattr_static(shelf_module.Shelf, name)
            if not isinstance(attribute, classmethod):
                continue
            parameters = list(inspect.signature(getattr(shelf_module.Shelf, name)).parameters)
            built = (
                getattr(shelf_module.Shelf, name)(db)
                if parameters == ["db"]
                else getattr(shelf_module.Shelf, name)(db, 1)
            )
            if built._viewer_id is None:
                viewerless.add(name)
        assert viewerless == {"seen_by_the_public"}, (
            f"{sorted(viewerless)} build a Shelf with no viewer. Every one of "
            "them can mint an Outbound, so every one of them has to apply a "
            "predicate with no ownership arm, and only `seen_by_the_public` is "
            "argued to."
        )

    def test_there_are_constructors_to_classify(self):
        """Anti vacuity for the test above: an empty scan of the class would
        satisfy an equality against a set it never filled."""
        classmethods = [
            name
            for name in dir(shelf_module.Shelf)
            if isinstance(inspect.getattr_static(shelf_module.Shelf, name), classmethod)
        ]
        assert len(classmethods) >= 3


class TestOnlyTheShelfCanMintOne:
    """The runtime half: `Outbound.__post_init__` refuses a caller outside
    `shelf.py`, whatever spelling it reaches the class by.

    The ast rule above reads names, so it is blind to every reflective
    construction. Each of those is driven here rather than argued, because the
    argument written in its place ("they only widen rows already handed over")
    was wrong: an empty `Outbound` is one call away and is a token, not a
    constraint.
    """

    @staticmethod
    def _an_empty_one(db):
        """A genuine `Outbound`, minted the only way there is.

        This is also the value that makes the reflective shapes below reachable
        at all, which is the whole finding.
        """
        return shelf_module.Shelf.seen_by_the_public(db).outbound_page(0, 0)[0]

    def test_the_shelf_can_mint_one(self, db):
        """The control. Without it every refusal below would pass on a class
        that refuses everybody."""
        assert len(self._an_empty_one(db)) == 0

    def test_a_direct_call_from_another_module_is_refused(self, db, user):
        db.add(Book(title="Not published", added_by_user_id=user.id, is_private=True))
        db.commit()
        with pytest.raises(TypeError, match="shelf with no viewer"):
            shelf_module.Outbound(books=(db.query(Book).one(),))

    def test_dataclasses_replace_is_refused(self, db):
        import dataclasses

        with pytest.raises(TypeError, match="shelf with no viewer"):
            dataclasses.replace(self._an_empty_one(db), books=())

    def test_copy_replace_is_refused(self, db):
        """The 3.13 spelling of the same thing, and the one nothing named until
        the security seat drove it."""
        import copy

        with pytest.raises(TypeError, match="shelf with no viewer"):
            copy.replace(self._an_empty_one(db), books=())

    def test_reaching_the_class_through_a_value_is_refused(self, db):
        rows = self._an_empty_one(db)
        with pytest.raises(TypeError, match="shelf with no viewer"):
            type(rows)(books=())


class TestRowsThatMayLeaveTheInstance:
    """The behaviour of the two read methods, against a real shelf."""

    def test_a_members_shelf_refuses_to_hand_over_rows_that_may_leave(self, db, user):
        db.add(Book(title="Anything", added_by_user_id=user.id))
        db.commit()
        with pytest.raises(ValueError, match="one member"):
            shelf_module.Shelf.seen_by(db, user.id).outbound_page(0, 10)

    def test_the_trash_shelf_refuses_too(self, db, user):
        """The other per member constructor, asserted separately. One of the two
        passing proves nothing about the other, and the trash shelf is the one
        somebody reaches for when a purge needs a payload."""
        with pytest.raises(ValueError, match="one member"):
            shelf_module.Shelf.trashed_by(db, user.id).outbound_first()

    def test_the_public_shelf_hands_over_its_rows(self, db, user):
        db.add(Book(title="Published", added_by_user_id=user.id))
        db.commit()
        rows, total = shelf_module.Shelf.seen_by_the_public(db).outbound_page(0, 10, Book.title.asc())
        assert total == 1
        assert [book.title for book in rows] == ["Published"]

    def test_a_private_book_is_absent_rather_than_stripped(self, db, user):
        """Absent, which is the answer the ticket settled: a row with its fields
        blanked still says a Book is there and lets a stranger count them."""
        db.add(Book(title="Published", added_by_user_id=user.id))
        db.add(Book(title="Not published", added_by_user_id=user.id, is_private=True))
        db.commit()
        rows, total = shelf_module.Shelf.seen_by_the_public(db).outbound_page(0, 10, Book.title.asc())
        assert total == 1
        assert len(rows) == 1

    def test_one_book_comes_back_as_rows_rather_than_a_book(self, db, user):
        """`outbound_first` answers with the same type as the page, so a handler
        has no bare `Book` in hand between the shelf and the serialiser."""
        db.add(Book(title="Published", added_by_user_id=user.id))
        db.commit()
        rows = shelf_module.Shelf.seen_by_the_public(db).outbound_first()
        assert isinstance(rows, shelf_module.Outbound)
        assert len(rows) == 1

    def test_a_private_book_asked_for_by_id_comes_back_empty(self, db, user):
        private = Book(title="Not published", added_by_user_id=user.id, is_private=True)
        db.add(private)
        db.commit()
        db.refresh(private)
        rows = shelf_module.Shelf.seen_by_the_public(db).where(Book.id == private.id).outbound_first()
        assert len(rows) == 0
        assert not rows


# ── Who may build a payload out of rows that may leave ────────────────────────


def _annotations(arguments: ast.arguments) -> list[ast.expr]:
    """Every parameter annotation on one signature, of whatever kind.

    **Walked off the `arguments` node rather than added up from named lists.**
    The first version read `posonlyargs + args + kwonlyargs`, which is three of
    the five slots: `def write(stream, *pages: Outbound)` and `**rows: Outbound`
    were not signatures as far as the rule was concerned, and every spelling in
    the diagonal below lived in the covered half. A list of slot names is the
    enumeration shape this file keeps recording, and `ast.walk` over the node
    has no list to fall behind.
    """
    return [
        node.annotation
        for node in ast.walk(arguments)
        if isinstance(node, ast.arg) and node.annotation is not None
    ]


def _names_the_type(annotation: ast.expr, local_names: set[str]) -> bool:
    """Whether one annotation mentions `shelf.Outbound`, however it is written.

    The whole subtree, so `Outbound | None` and `Sequence[Outbound]` count.

    **A quoted name is re-parsed wherever it sits, not only when the whole
    annotation is one.** Reading the top level alone is an enumeration over
    where a quote may go: `rows: "Outbound"` was a door and
    `rows: Sequence["Outbound"]` was not, and quoting one name inside a
    subscript is the cheaper evasion of the two. This backend runs under PEP 649
    and quotes almost nothing, so a quote here is somebody reaching for the
    spelling the rule does not read. A string that does not parse is not an
    annotation and is left alone.

    What that costs is a `Literal["Outbound"]` reported as a door, which costs a
    person one look, and this file has already chosen that direction: see
    `_outbound_constructions` on `x.Outbound(...)`.
    """
    pending = [annotation]
    while pending:
        for inner in ast.walk(pending.pop()):
            if isinstance(inner, ast.Name) and inner.id in local_names:
                return True
            if isinstance(inner, ast.Attribute) and inner.attr == "Outbound":
                return True
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                try:
                    pending.append(ast.parse(inner.value, mode="eval").body)
                except SyntaxError:
                    continue
    return False


def _outbound_signatures(source: str) -> list[str]:
    """Every function in one module that takes an `Outbound`, by name.

    The annotation is resolved through `_entity_aliases` like every other rule
    in this file, so `from shelf import Outbound as Rows` is read rather than
    walked past.
    """
    tree = ast.parse(source)
    local_names = _entity_aliases(tree, _OUTBOUND, module="shelf")
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(_names_the_type(annotation, local_names) for annotation in _annotations(node.args))
    ]


def _outbound_requests(source: str) -> list[str]:
    """Every call in one module that asks a Shelf for rows that may leave."""
    return [
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"outbound_page", "outbound_first"}
    ]


class TestTheSerialisersThatMayBuildAnOutboundPayload:
    """The third question `docs/data-model.md` asks, which had no rule behind it.

    Two of the three had one. *Which rows may a stranger see* is
    `Shelf.seen_by_the_public`. *How do those rows stay marked as such* is
    `Outbound`, minted by the shelf alone and pinned by the two classes above.
    *Which serialiser may build the payload* was answered "whichever takes an
    `Outbound`", which describes the tree rather than constraining it: a second
    serialiser is a signature, and nothing was reading signatures.

    **The point of one door is that the test is "does anything else build an
    outbound payload", not "did each caller remember".** That is the shape that
    has kept the Shelf rule intact, and it needs the set of doors to be a set
    somebody argued rather than a set somebody counted once.

    **Producers as well as consumers**, because they fail differently. A new
    consumer is a payload nobody argued about. A new producer is a route
    reaching for rows a stranger may see, which is where the publish gate and
    the record limits live, and `routers/public.py` is where those are.

    **What this cannot see:**

    * **A payload built for a stranger that never names the type.** That is not
      caught here and is not meant to be: `tests/test_nothing_private_leaves.py`
      drives every route answered with no member and asserts a marked private
      Book comes back from none of them. This rule and that sweep meet at the
      routes and diverge off them, which is why both exist.
    * **Reaching past the type.** `outbound.books` is a public attribute and
      hands back a plain tuple. It discloses nothing, because those rows came
      off a shelf with no ownership arm, and the direction that would matter,
      putting unsafe rows *into* the type, is what `Outbound.__post_init__`
      refuses.
    * **A serialiser in a test**, since `application_sources()` excludes `tests/`.
    * **A second door of a kind already argued, in a module already argued.**
      The keys are module and kind, so a second `outbound_page` call inside
      `routers/public.py` adds none. What a new key says is that a module has
      started building outbound payloads, or has started building them a second
      way, which is the change worth an argument.
    """

    #: Every function that takes rows which may leave, and every call that asks
    #: for a set of them, with the reason each may.
    #:
    #: **Asserted by equality in both directions.** A door that appears without
    #: a line here is a payload addressed to somebody this instance cannot name
    #: and that nobody argued about; a door that disappears is a claim in
    #: `docs/data-model.md` that has stopped being true.
    OUTBOUND_DOORS: dict[str, str] = {
        "serialisation.py: books_to_public_out takes an Outbound": (
            "the JSON catalogue. Takes no Session and no User, so it structurally cannot ask who is reading"
        ),
        "sru.py: _records_element takes an Outbound": (
            "the SRU records element. Takes the type rather than looping "
            "outside it, so the loop that writes a record cannot be handed a "
            "bare list"
        ),
        "routers/public.py: asks a shelf for one": (
            "the two published catalogue routes, which is also where the publish switch is read"
        ),
        "sru.py: asks a shelf for one": ("the SRU searchRetrieve response, gated by the same switch"),
    }

    @staticmethod
    def _doors() -> set[str]:
        # **No exemption for `shelf.py`**, which had one until it was asked what
        # it bought. Nothing there takes an `Outbound`, only returns one, and
        # the resolver reads parameters, so the exemption changed no verdict;
        # what it did buy was the one module where a serialiser could be put and
        # this rule would not see it.
        found: set[str] = set()
        for name, source in application_sources().items():
            found |= {f"{name}: {function} takes an Outbound" for function in _outbound_signatures(source)}
            if _outbound_requests(source):
                found.add(f"{name}: asks a shelf for one")
        return found

    def test_the_doors_are_the_argued_ones(self):
        found = self._doors()
        assert found == set(self.OUTBOUND_DOORS), (
            f"Added: {sorted(found - set(self.OUTBOUND_DOORS))}. Gone: "
            f"{sorted(set(self.OUTBOUND_DOORS) - found)}. A private Book never "
            "leaves this instance, and that holds because the payloads "
            "addressed to a stranger are few enough to name. Add the line with "
            "the reason, or serialise through one that is already there."
        )

    def test_there_are_doors_to_classify(self):
        """Anti vacuity: the equality above is satisfied by a resolver that
        finds nothing, which is what renaming the type would produce."""
        assert len(self._doors()) >= 3

    @pytest.mark.parametrize(
        "spelling",
        [
            "from shelf import Outbound\ndef f(rows: Outbound) -> int:\n    return 0\n",
            "from shelf import Outbound as Rows\ndef f(rows: Rows) -> int:\n    return 0\n",
            "import shelf\ndef f(rows: shelf.Outbound) -> int:\n    return 0\n",
            "from shelf import Outbound\ndef f(rows: Outbound | None) -> int:\n    return 0\n",
            "from shelf import Outbound\nasync def f(*, rows: Outbound) -> int:\n    return 0\n",
            "from shelf import Outbound\ndef f(stream, *pages: Outbound) -> int:\n    return 0\n",
            "from shelf import Outbound\ndef f(**rows: Outbound) -> int:\n    return 0\n",
            "from shelf import Outbound\ndef f(rows: 'Outbound', /) -> int:\n    return 0\n",
            "from shelf import Outbound\ndef f(rows: Sequence['Outbound']) -> int:\n    return 0\n",
            "from shelf import Outbound\ndef f(rows: list['Outbound'] | None) -> int:\n    return 0\n",
        ],
        ids=[
            "imported",
            "aliased",
            "attribute",
            "optional",
            "keyword only async",
            "star args",
            "star kwargs",
            "quoted and positional only",
            "quoted inside a subscript",
            "quoted inside a subscript and optional",
        ],
    )
    def test_a_new_serialiser_is_found_however_it_spells_the_type(self, spelling):
        """The diagonal, one mutation each, for the reason
        `test_the_rule_catches_each_spelling` gives: a sample carrying two
        spellings passes with either arm deleted and never says which caught
        it."""
        assert _outbound_signatures(spelling) == ["f"]

    def test_a_function_that_only_returns_one_is_not_a_door(self):
        """What keeps `shelf.py`'s own two out, now that nothing excludes that
        module by name: they annotate a return and this rule reads parameters.
        Reporting a return as well would make the rule unusable, since minting
        one is the shelf's job and is guarded by the class above."""
        assert (
            _outbound_signatures("from shelf import Outbound\ndef f() -> Outbound:\n    return g()\n") == []
        )

    @pytest.mark.parametrize(
        "spelling",
        [
            "rows, total = shelf.outbound_page(0, 10)\n",
            "rows = Shelf.seen_by_the_public(db).outbound_first()\n",
        ],
        ids=["page", "first"],
    )
    def test_both_ways_to_ask_for_rows_are_found(self, spelling):
        assert _outbound_requests(spelling) != []

    def test_asking_for_something_else_is_not_a_request(self):
        assert _outbound_requests("rows = shelf.page(0, 10)\n") == []


class TestTheModulesTheseRulesWalk:
    """The corpus every rule in this file is asked about.

    Every guard here is an absence over `application_sources()`, so a walk that
    quietly returns the wrong set changes every verdict in the file with nothing
    to say so. Two ways that happens, and the second is the one that was live:
    it narrows and a rule stops seeing an offender, or it widens into a tool's
    own directory and a rule reports third party code nobody here can fix.

    **The walk is `corpus.application_sources` and this file no longer
    keeps its own.** The copy here excluded a tool's directory by naming `.venv`
    and nothing else, so a `.uv-cache/` under `backend/` in CI, which is where
    the pipeline puts it, was source as far as every rule in this file was
    concerned. `is_vendored` is the structural rule and it has its own tests
    beside it.
    """

    def test_it_returns_the_modules_these_rules_are_about(self):
        """Anti vacuity, and it names one module per shape the rules read: the
        seam itself, a router and a module reached only through a join."""
        assert {"shelf.py", "routers/books.py", "notifications.py"} <= set(application_sources())
