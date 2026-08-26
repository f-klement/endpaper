"""Tests for backend/shelf.py: the seam every many-Book query goes through.

Two kinds of test live here and they answer different questions.

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
resolve. Three `ast` passes ask three flat questions.

| Pass | Question | Allowed in |
|---|---|---|
| `_imported_names` | who imports `visible_to` / `in_trash_for` | `PREDICATE_IMPORTERS` |
| `_query_offences` | who builds a query naming `Book` | `QUERY_BUILDERS` |
| `_join_offences` | who reaches `books` through a join | `QUERY_BUILDERS`, `JOIN_CALLERS` |

`_book_aliases` resolves which local names mean `Book` first, so an import alias,
a rebinding or an `aliased()` entity is caught rather than looked past.

**It is wider than the old guard**, which was blind to a query reaching `books`
through `.join(Book, ...)` while naming no `Book` inside `query()`: its own
docstring recorded **10** such statements in the tree, and teaching it that shape
was costed at four fresh exemptions and refused. `_join_offences` sees them, and
here the same widening costs **one** allowlist entry, `notifications.py`, because
that is the only module in the tree taking the shape. The reason is the seam, not
the rule: once every legitimate query goes through one module, the exceptions are
few enough to name.

**The blind spots, because a guard whose limits are undocumented is read as a
guarantee it never made.** Five rounds of review found **nineteen** shapes that
evaded earlier versions of this rule; `EVASIONS` holds every one, and each is
asserted against the specific pass that must catch it. What is *still* not
caught:

* **A variable this resolver cannot trace back to `Book`.** It follows
  `X = Book`, `X = models.Book` and `X = aliased(Book)`, in both the plain and
  the annotated form, and unpacks a tuple target. It does not follow a value
  computed any other way: `backup.py` does `db.query(model)` over a loop, so no
  rule reading the arguments to `query()` can see it. Asserted separately by
  name instead, and listed in `INDIRECT_READERS`.
* **Raw SQL.** `db.execute(text("SELECT location, count(*) FROM books ..."))`
  names no `Book` anywhere and evades all three passes. `text()` is already used
  in the tree (`main.py:451`), and a location index with a count is exactly the
  shape the child-table bullet below warns about.
* **A join through a relationship**, `db.query(Loan).join(Loan.book)`, which
  names no `Book` at all.
* **A child table carrying book-derived data.** A query over `quotes`,
  `notes` or `classifications` names no `Book` and is invisible here. The one to
  watch for is an *index* over such a table, which is the shape that publishes a
  name and a count.
* Importing `Book` for a `db.get(Book, id)` or a type annotation is not
  distinguished from importing it to build a listing, which is why the rule tests
  query shapes rather than that import.
* **`select` under an import alias.** `from sqlalchemy import select as sel`,
  then `sel(Book.location)`. Catching it means alias-resolving the *function*
  name the way `_book_aliases` resolves the model, doubling the resolver to guard
  a spelling the tree does not use: `serialisation.py` imports `select` bare.
* **`Query([Book], session=db)`**, constructing `orm.Query` directly. Not how a
  query is written anywhere in this codebase.
* **An implicit FROM through a clause rather than an entity position.**
  `db.query(Loan.id).filter(Book.is_private.is_(True))` compiles to
  `SELECT loans.id FROM loans, books WHERE ...`, and `.order_by(Book.title)` and
  `.group_by(Book.location)` do the same: a real cartesian read of `books` with
  no predicate. Refused a pass deliberately, and this is the one worth
  understanding. `Book` appears in a clause position on every **correct** caller
  too, `routers/stats.py`'s `join(User, Book.added_by_user_id == User.id)` among
  them, so separating the two means knowing whether the query is rooted at
  `books`, which is the flow analysis this rule exists to avoid. It also leaks by
  row existence and count rather than by content, which makes it the weakest
  member of the family. Named rather than caught.

Both critic seats reviewed that list and called it complete at these eight
entries. It is the deliverable for everything the rule does not catch: a shape
that is named here has been decided about, and a shape that is neither caught nor
named is an oversight.

The rest of the file tests the Shelf's behaviour.
"""

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Select, event, func

from enums import BookSort, ReadStatus
from models import Book, Collection, Tag, User, UserBook, book_tags
from shelf import (
    BookFilters,
    Loading,
    Shelf,
    order_for,
    rereading_filtered_rows,
    whole_table_for_uniqueness,
)

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
JOIN_CALLERS = {"notifications.py"}

#: Modules that read every row of `books` without naming `Book` in the query,
#: so no rule of this shape can see them.
#:
#: One: `backup.py` iterates `_TABLES` and calls `db.query(model)` on a loop
#: variable. An archive that omitted everyone else's Private Books would
#: restore to a library missing rows, which is the one thing a backup must
#: never do, so it is unfiltered on purpose and admin only for that reason.
#: `test_the_backup_is_the_third_way_past_a_viewer_and_says_so` is what holds
#: that, since this rule structurally cannot.
INDIRECT_READERS = {"backup.py"}


def _book_aliases(tree: ast.Module) -> set[str]:
    """Every local name bound to the `Book` model in one module.

    Resolved rather than assumed, because `from models import Book as B` binds
    a name this rule would otherwise never look for.

    Three assignment forms are followed as well: `X = Book`, `X = models.Book`
    and `X = aliased(Book)`. The third is not hypothetical here,
    `serialisation.py` already builds queries on an `aliased(...)` entity.

    **Only those three, deliberately.** Following any assignment whose value
    merely mentions `Book` was measured against the tree and reports five false
    positives in `routers/books.py` (544, 571, 578, 3116, 3219), because
    `book = Book(...)` would make `book` an alias and
    `"; ".join(tag.name for tag in book.tags)` is then a join offence. The
    three literal forms give zero.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            names |= {a.asname or a.name for a in node.names if a.name == "Book"}

    # A second pass, because an alias may be assigned above or below the import
    # in file order and this rule does not care which.
    for node in ast.walk(tree):
        for target, value in _bindings(node):
            if isinstance(target, ast.Name) and _is_book_entity(value, names):
                names.add(target.id)
    return names


def _bindings(node: ast.AST) -> list[tuple[ast.expr, ast.expr]]:
    """The `(target, value)` pairs one statement binds.

    **`AnnAssign` as well as `Assign`, and that is not a completeness flourish.**
    The annotated form is the more idiomatic half of this backend: counted over
    the tree excluding tests and migrations, **125** module-level `AnnAssign`
    against **140** `Assign`, and every module-level binding in `shelf.py`
    itself is annotated. A resolver that read only `Assign` would have followed
    the less-used spelling, which is the shape of a guard that looks thorough
    and is not.

    A tuple target is unpacked element by element against a tuple value, so
    `M, N = Book, Tag` binds `M` and not `N`.
    """
    if isinstance(node, ast.AnnAssign):
        return [] if node.value is None else [(node.target, node.value)]
    if not isinstance(node, ast.Assign):
        return []
    pairs: list[tuple[ast.expr, ast.expr]] = []
    for target in node.targets:
        if (
            isinstance(target, ast.Tuple)
            and isinstance(node.value, ast.Tuple)
            and len(target.elts) == len(node.value.elts)
        ):
            pairs.extend(zip(target.elts, node.value.elts, strict=True))
        else:
            pairs.append((target, node.value))
    return pairs


def _is_book_entity(value: ast.expr, names: set[str]) -> bool:
    """Whether an assigned value rebinds the Book entity under a new name.

    `X = Book`, `X = models.Book`, `X = aliased(Book)`, and nothing else.
    """
    if _names_book(value, names):
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
    return named_aliased and any(_names_book(a, names) for a in arguments)


def _names_book(node: ast.AST, aliases: set[str]) -> bool:
    """Whether an expression is the Book entity itself, not a column of it."""
    if isinstance(node, ast.Name):
        return node.id in aliases
    return isinstance(node, ast.Attribute) and node.attr == "Book"


def _mentions_book(node: ast.AST, aliases: set[str]) -> bool:
    """Whether an expression names the Book model or any column of it.

    Both shapes count. `query(Book)` returns rows; `query(Book.author)` returns
    a column out of the same rows, and publishing which authors, locations or
    series exist is the same leak by a narrower door. The attribute form also
    catches `models.Book`, which a name-only check would miss.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in aliases:
            return True
        if isinstance(child, ast.Attribute) and child.attr == "Book":
            return True
    return False


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
    such decision to make: `_book_aliases` resolves which names mean `Book`, and
    everything after that is a flat walk with no scopes and no exemption
    comments.

    `obj.select(...)` is deliberately not an offence. That is the Shelf's own
    method, and reporting it would report every correct caller.
    """
    tree = ast.parse(source)
    aliases = _book_aliases(tree)
    offences = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _builds_a_query(node.func) and any(
            _mentions_book(arg, aliases) for arg in node.args
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
_QUERY_BUILDERS = frozenset(
    {"query", "select_from", "with_entities", "add_columns", "add_entity"}
)

#: Methods that reach another table by joining it.
#:
#: The same family rule. `join` was covered and `outerjoin` was not, which cost a
#: round; then `join_from` was covered and `outerjoin_from` was not, which cost
#: another. An outer join reads **more** rows than an inner one, never fewer.
#: The `_from` pair name the FROM entity as well as the target, so both of their
#: first two arguments are positions `Book` can occupy.
_JOIN_METHODS = frozenset({"join", "outerjoin", "join_from", "outerjoin_from"})


def _builds_a_query(func: ast.expr) -> bool:
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
    if isinstance(func, ast.Name) and func.id == "select":
        return True
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "select"
        and isinstance(func.value, ast.Name)
        and func.value.id in {"sa", "sqlalchemy"}
    )


def _join_offences(source: str) -> list[int]:
    """Line numbers where this module reaches `books` through a join.

    The shape the old guard was blind to and documented as such: a statement
    whose `query()` names no `Book` and gets to the table through
    `.join(Book, ...)` anyway, whatever it selects.
    """
    tree = ast.parse(source)
    aliases = _book_aliases(tree)
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
        if any(_mentions_book(t, aliases) for t in targets):
            offences.append(node.lineno)
    return sorted(offences)


def _imported_names(source: str) -> set[str]:
    """Every name one module binds by importing it."""
    return {
        alias.asname or alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }


def _source_modules() -> dict[str, str]:
    """Every backend module these rules apply to, keyed by relative path."""
    return {
        str(path.relative_to(BACKEND)): path.read_text()
        for path in BACKEND.rglob("*.py")
        if path.relative_to(BACKEND).parts[0] not in {"tests", "migrations", ".venv"}
    }


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
            for name, source in _source_modules().items()
            if name not in PREDICATE_IMPORTERS
            for predicate in _imported_names(source) & set(PREDICATES)
        )
        assert offenders == [], (
            "These modules import a visibility predicate instead of asking the "
            f"Shelf for one: {offenders}"
        )

    def test_no_module_but_the_shelf_builds_a_query_over_books(self):
        """The half that catches a query with no predicate at all, rather than
        one that imported the wrong thing."""
        offenders = sorted(
            f"{name}:{line}"
            for name, source in _source_modules().items()
            if name not in QUERY_BUILDERS
            for line in _query_offences(source)
        )
        assert offenders == [], (
            f"These statements build a query over books outside the Shelf: {offenders}"
        )

    def test_only_the_named_exception_reaches_books_through_a_join(self):
        """The blind spot the old guard documented and this rule closes.

        A query rooted at another table that reaches `books` through
        `.join(Book, ...)` names no `Book` in `query()`, so a rule reading the
        arguments alone never sees it, whatever it selects. Measured over the
        tree, exactly one module takes that shape.
        """
        offenders = sorted(
            f"{name}:{line}"
            for name, source in _source_modules().items()
            if name not in QUERY_BUILDERS | JOIN_CALLERS
            for line in _join_offences(source)
        )
        assert offenders == [], (
            f"These statements reach books through a join outside the Shelf: {offenders}"
        )

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
            "from models import Book, Loan\n"
            "def f(db):\n    return db.query(Loan).add_entity(Book).all()\n",
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
    }

    @pytest.mark.parametrize("shape", sorted(EVASIONS))
    def test_the_rule_catches_the_shapes_that_defeated_its_earlier_versions(self, shape):
        """Every shape below was measured passing some earlier version of this
        rule clean, and each is a location or author index publishing a name and
        a count over every Member's Private Books.

        **Sixteen shapes, from four rounds of review**, and the count is here
        rather than in prose elsewhere because this dict is what defines it.

        | Round | What broke the rule that round | Shapes |
        |---|---|---|
        | 1 | the two regexes both critics broke | 4 |
        | 2 | the `ast` pass that replaced them | 5 |
        | 3 | alias resolution, verifying shapes already listed | 0 |
        | 4 | `with_entities` and `join_from`, plus five binding forms | 7 |
        | 5 | `add_columns`, `add_entity`, `outerjoin_from` | 3 |

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

    def test_the_predicates_are_defined_where_this_rule_says_they_are(self):
        """The rules above are name checks, so it is worth proving the names
        they check are real. A typo in `PREDICATES` would let them pass over a
        tree that had abandoned the seam entirely."""
        models = (BACKEND / "models.py").read_text()
        for predicate in PREDICATES:
            assert f"def {predicate}(" in models, predicate

    def test_notifications_reads_books_and_is_deliberately_not_a_shelf(self):
        """Named rather than left as a silent pass.

        The overdue digest runs for the Library on a schedule, so it has no
        viewer to be scoped to, and its two halves **partition** on privacy
        rather than filter by it: `is_(False)` for the reminders it sends and
        `is_(True)` for the count of what privacy held back. A Shelf would have
        to mean both at once, which is what `in_trash_for` being a separate
        function from `visible_to` exists to avoid.

        This fails if that module ever starts applying a viewer predicate,
        because at that point it has a viewer and belongs behind the seam.
        """
        source = (BACKEND / "notifications.py").read_text()
        assert "Book.is_private.is_(False)" in source
        assert "Book.is_private.is_(True)" in source
        for predicate in PREDICATES:
            assert f"{predicate}(" not in source

    def test_the_backup_is_the_third_way_past_a_viewer_and_says_so(self):
        """`backup.py` is invisible to every rule in this file, so it is
        asserted rather than assumed.

        It reads every row of every table through `db.query(model)` on a loop
        variable, so no rule that reads the arguments to `query()` can see it.
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
        opt-outs could not grow quietly. The opt-outs became two named
        functions, and the counting has to survive that or the same drift
        happens with a different spelling. Growing either list is allowed;
        growing it without saying so here is not.
        """
        calls: dict[str, list[str]] = {
            "whole_table_for_uniqueness": [],
            "rereading_filtered_rows": [],
        }
        for name, source in _source_modules().items():
            if name == "shelf.py":
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in calls
                ):
                    calls[node.func.id].append(f"{name}:{node.lineno}")

        # **Call sites, not modules.** A set of module names does not count
        # anything: three of the four uniqueness calls are already in
        # `routers/books.py`, so a fifth added there would leave the set
        # unchanged and pass green, which is exactly the quiet growth the
        # deleted exemption counter existed to prevent.
        assert len(calls["whole_table_for_uniqueness"]) == 4, calls
        assert len(calls["rereading_filtered_rows"]) == 1, calls


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

        rows = (
            Shelf.seen_by(db, user.id)
            .where(Book.location == "study")
            .select(Book.title)
            .all()
        )
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
            Shelf.seen_by(db, user.id)
            .matching(BookFilters(status=ReadStatus.READING, unrated=True))
            .all()
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

    def test_a_page_with_serialised_loading_costs_three_statements(self, db, user):
        """One count, one page of rows, and one `selectinload` for the Tags of
        the whole page. `added_by` is a many to one and rides on the row itself,
        which is why it adds none."""
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(25))
        db.commit()

        def page():
            books, total = Shelf.seen_by(db, user.id).page(
                0, 25, Book.id.asc(), load=Loading.SERIALISED
            )
            assert len(books) == 25 and total == 25

        page()  # warm up outside the window
        assert len(self._count(db, page)) == 3

    def test_the_count_does_not_pay_for_the_eager_loading(self, db, user):
        """`page()` counts from the query without the loading options. Counting
        through them would issue the `selectinload` for rows it discards."""
        db.add_all(Book(title=f"Book {n}", added_by_user_id=user.id) for n in range(5))
        db.commit()

        def count():
            assert Shelf.seen_by(db, user.id).count() == 5

        count()
        assert len(self._count(db, count)) == 1

    def test_exported_loading_costs_two_statements(self, db, user, shelved):
        """The third `Loading` member, pinned because the enum's docstring
        states a cost for it. One for the rows, one `selectinload` for the tags
        of the whole page; `added_by` and `collection` are both many to one and
        ride on the row itself, which is the claim being checked."""
        db.add_all(
            Book(title=f"Book {n}", collection_id=shelved.id, added_by_user_id=user.id)
            for n in range(5)
        )
        db.commit()

        def export():
            books = Shelf.seen_by(db, user.id).all(Book.title.asc(), load=Loading.EXPORTED)
            assert len(books) == 5
            assert books[0].collection is not None
            assert books[0].added_by is not None

        export()
        assert len(self._count(db, export)) == 2

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
                Shelf.seen_by(db, user.id).page(
                    0, size, Book.id.asc(), load=Loading.SERIALISED
                )

            return work

        page(25)()
        assert len(self._count(db, page(25))) == len(self._count(db, page(1)))


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
