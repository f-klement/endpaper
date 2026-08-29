"""Tests for backend/custom_fields.py: the seam every custom field row goes
through, and the link rendering rule.

Three kinds of test, the same split `test_shelf.py` and `test_reading.py` use.

`TestOnlyABookReachesAValue` is the **house rule**, and it is three passes.

**One: the import pass.** Nothing outside `custom_fields.py` holds the name
`CustomFieldValue`, so no other module can build a query over the table. Same
proxy `test_reading.py` uses for `UserBook`, resolving an aliased import for
the same reason.

**Two: the touch pass, which is the one that matters.** It walks the module's
own AST and reports **any public function whose body names `CustomFieldValue`
and that takes no `Book`**, with two names exempted. That is the enforcement of
the claim the whole design rests on, and it is written this way because the
obvious version is not enforcement at all.

The obvious version enumerated the two functions by hand:

    [(Values.of, "books"), (write, "book")]

which asserts something true about exactly the code that was written and
nothing about the code somebody adds next. Adding
`def values_of(db, book_ids: list[int])` to `custom_fields.py` passed it and
passed the import pass too, since that one allowlists this module by name. The
module docstring names that exact function as the thing being prevented, so
the guard permitted the shape its own prose forbids. Enumerating the module
rather than a literal is the difference between a test and a decoration, and
this is the twelfth guard in this repository to have been substantially wrong
on its first attempt.

**Three: the name pass.** Any parameter whose name mentions a book is annotated
with `Book`. Pass two would miss `Values.on(self, book_id: int)`, a method that
reads a mapping rather than naming the table; this catches it.

**The two exemptions are two different rules, not an escape hatch.** `remove`
deletes every value under one definition across the whole Library, which is
what deleting a field means and cannot be scoped to a viewer; `resolve_merge`
rewrites rows for Books nobody is holding, or a merge silently destroys them.
Both are named in the module docstring, and
`test_the_named_ways_past_a_book_have_the_callers_they_claim` counts their call
sites so a third cannot appear quietly.

**What none of the three catches**, stated because a guard whose limits are
undocumented gets read as a guarantee it never made:

* `book.custom_field_values`, the relationship on the parent. It is a lazy load
  off a row somebody already holds, so the Book it hangs off has been through
  the Shelf, which is exactly the safe case. What it does bypass is
  `link_target`, so a caller reading values that way would render a stored
  string as a link without re-checking it. Nothing does; `values_on` is the
  only reader.
* Raw SQL naming `custom_field_values`. Invisible to any rule that reads names.
* `models.CustomFieldValue` reached through `import models`. Nothing in the
  tree imports `models` as a module, and the same shape evades
  `test_reading.py`'s pass too.
* A reader keyed on something that is neither a Book nor a book-shaped name:
  `def values_under(db, field: CustomField)` names the table, takes no Book and
  would be reported by pass two, so the exemption list is where such a thing
  has to be argued for. The **relationship** version of it,
  `CustomField.values`, is not caught by any pass and is asserted absent below.
* **A decoy `Book` parameter.** `_takes_a_book` asks whether any parameter is
  annotated with `Book`, so `def values_of(db, ids: list[int], scope: Book)`
  touches the table, satisfies pass two, carries no book-shaped name for pass
  three, and reads whatever ids it was given. Deciding that `scope` is not what
  the query is keyed on means following the ids to the filter, which is the
  flow analysis `shelf.py` exists to have retired, so it is named here rather
  than caught. What makes it a poor hiding place rather than an open door: the
  parameter has to be added, annotated and then not used, in a module whose
  every other reader keys on the Book it is handed.

`TestALinkIsNotWhateverSomebodyTyped` is the injection surface. A value is
member supplied and `<a href>` is one of the two places a browser turns a
string into code.

The rest tests behaviour.
"""

import ast
import importlib
from pathlib import Path

import pytest
from sqlalchemy import event

import custom_fields
from custom_fields import (
    Refused,
    _kind_of,
    define,
    definitions,
    link_target,
    remove,
    rename,
    values_on,
    write,
)
from database import Base
from enums import CustomFieldKind
from models import Book, CustomField, CustomFieldValue, User

BACKEND = Path(__file__).resolve().parent.parent

#: Where `CustomFieldValue` may be imported.
#:
#: `models.py` defines it. `custom_fields.py` owns it. `backup.py` names it in
#: `_TABLES` so a restore cannot lose a table, which is the same third way past
#: a viewer `test_shelf.py` documents. Nothing else: a router asks
#: `custom_fields.py`, and it holds only `CustomField`, the definition, which is
#: Library wide and says nothing about any Book.
VALUE_READERS = {"models.py", "custom_fields.py", "backup.py"}

#: The modules a `from ... import *` can bind the name through. Derived from the
#: allowlist rather than written out, for the reason `test_reading.py` derives
#: its own: a module allowed to hold the name re-exports it, so adding a fourth
#: allowlist entry cannot reopen the hole by being forgotten here.
_STAR_SOURCES = {name.removesuffix(".py") for name in VALUE_READERS}

#: Spellings that must be reported. `test_reading.py`'s guard was weakened by a
#: single `or` and its own EVASIONS caught it; this pass is the same shape.
EVASIONS = {
    "plain": "from models import CustomFieldValue\n",
    "beside other names": "from models import Book, CustomFieldValue, User\n",
    "aliased": "from models import CustomFieldValue as V\n",
    "star": "from models import *\n",
    "star from a re-exporter": "from custom_fields import *\n",
}

#: Spellings that must **not** be reported, so the pass cannot be satisfied by
#: reporting everything. The definition is the interesting one: a router holds
#: it and must go on being allowed to.
NOT_OFFENCES = {
    "the definition": "from models import CustomField\n",
    "another model": "from models import Book\n",
    "a star with no value in it": "from enums import *\n",
    "a name that merely contains it": "from models import CustomFieldValueOut\n",
}


def _imported_names(source: str) -> set[str]:
    """Every name one module imports, under both its spellings.

    **Both, not `alias.asname or alias.name`, and that one word is the rule.**
    The question here is "does this module reach a custom field value", and the
    answer to that is the name it **imported**: `from models import
    CustomFieldValue as CFV` binds `CFV` and imports `CustomFieldValue`, so
    taking the local alias alone lets one rename walk past the guard. The local
    name is kept too, because the star expansion below binds names rather than
    importing them. `test_reading.py` states the same reasoning about `UserBook`.

    That reason is written out here rather than left to be inferred from
    `test_reading.py`. It arrived as correct code with no argument attached, and
    correct code with no argument is what gets tidied into `asname or name` by
    somebody reading it as a verbose idiom. `test_shelf.py` had exactly that
    tidied form and one aliased import evaded it; verified on 2026-08-28, this
    file and `test_reading.py` did not.

    Its own copy rather than `test_reading.py`'s, and that is not duplication
    for its own sake: that one expands a star against **its** allowlist, so
    importing it here would ask whether `shelf.py` re-exports a custom field.
    The one line that differs is the one that decides what the rule covers.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "*":
                if isinstance(node, ast.ImportFrom) and node.module in _STAR_SOURCES:
                    names |= set(dir(importlib.import_module(node.module)))
                continue
            names.add(alias.name)
            if alias.asname is not None:
                names.add(alias.asname)
    return names


#: The two public names allowed to touch a value without being handed a Book.
#:
#: Two different rules rather than one escape hatch, both named in the module
#: docstring. `remove` deletes every value under one definition, across the
#: whole Library, which is what deleting a field **means**: scoping it to a
#: viewer would leave rows nobody can reach. `resolve_merge` rewrites rows for
#: Books nobody is holding, or the cascade on a merge silently destroys them.
#:
#: A third entry is a decision. `test_the_named_ways_past_a_book_have_the_callers_they_claim`
#: counts their call sites so one cannot appear quietly inside a module already
#: on the list.
PAST_A_BOOK = {"remove", "resolve_merge"}


def _module_functions() -> dict[str, ast.FunctionDef]:
    """Every function `custom_fields.py` defines. **Private ones included.**

    Parsed from the file rather than read off the imported module, because the
    touch pass needs the body and `inspect.getsource` on a method reached
    through `vars()` is the same parse with more steps.

    A method is keyed `Class.method`, so a class that grows a reader is
    enumerated rather than hidden behind its class name.

    **The `_` filter this used to carry was the same hole the literal
    parametrize was**, one indirection further out. With it, a public function
    that reads the table through a private helper touched nothing this walk
    could see:

        def values_for(db, ids):     return _fetch(db, ids)
        def _fetch(db, ids):         db.query(CustomFieldValue)...

    `_fetch` was invisible, `values_for` names no table, and the pair passed.
    `_touches_the_table` said the opposite in its own docstring, that a callee
    "is reached through a name this pass has already enumerated": it was not.
    Dropping the filter changes nothing at the tip, measured, and closes that.
    """
    tree = ast.parse((BACKEND / "custom_fields.py").read_text())
    found: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            found[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, ast.FunctionDef):
                    found[f"{node.name}.{member.name}"] = member
    return found


def _public_names(functions: dict[str, ast.FunctionDef]) -> list[str]:
    """The subset a caller outside this module can reach, for the count only."""
    return sorted(
        name
        for name in functions
        if not any(part.startswith("_") for part in name.split("."))
    )


def _touches_the_table(node: ast.FunctionDef) -> bool:
    """Whether this function's own body names `CustomFieldValue`.

    The body, not the module. That is enough **only because the enumeration
    covers private functions too**: a public function reading the table through
    a helper is caught at the helper, which is a name in the same walk. It was
    not, for one round, and this sentence used to claim it was.
    """
    return any(
        isinstance(child, ast.Name) and child.id == "CustomFieldValue"
        for child in ast.walk(node)
    )


def _annotations(node: ast.FunctionDef) -> list[tuple[str, str]]:
    """Each parameter of one function as `(name, annotation source)`.

    `ast.unparse` rather than the runtime annotation: under PEP 649 a
    `TYPE_CHECKING` name never resolves, and this rule asks what was written.
    `self` and anything unannotated come back as an empty string, which fails
    the `"Book" in ...` test, which is the right direction for a guard.
    """
    arguments = node.args
    every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        every.append(arguments.vararg)
    if arguments.kwarg is not None:
        every.append(arguments.kwarg)
    return [
        (argument.arg, ast.unparse(argument.annotation) if argument.annotation else "")
        for argument in every
    ]


def _takes_a_book(node: ast.FunctionDef) -> bool:
    """Whether any parameter is annotated with `Book`.

    `Sequence[Book]` counts: the point is that the caller had to have fetched
    one, not how many.
    """
    return any("Book" in annotation for _name, annotation in _annotations(node))


#: Shapes both passes must report, and which pass must report each.
#:
#: The first is the one the hand-written parametrize this replaced permitted:
#: it enumerated `Values.of` and `write` by name, so a third reader taking ids
#: was invisible to it while the module docstring named that exact function as
#: the thing being prevented.
SIGNATURE_EVASIONS: dict[str, tuple[str, str]] = {
    "a reader taking book ids": (
        "def values_of(db: Session, book_ids: list[int]) -> list[Filled]:\n"
        "    return db.query(CustomFieldValue).filter(\n"
        "        CustomFieldValue.book_id.in_(book_ids)\n"
        "    ).all()\n",
        "touch",
    ),
    "a reader keyed on a definition": (
        "def values_under(db: Session, field: CustomField) -> list[Filled]:\n"
        "    return db.query(CustomFieldValue).filter(\n"
        "        CustomFieldValue.field_id == field.id\n"
        "    ).all()\n",
        "touch",
    ),
    "a writer taking a book id": (
        "def write_to(db: Session, book_id: int, field: CustomField, value: str) -> None:\n"
        "    db.add(CustomFieldValue(book_id=book_id, field_id=field.id, value=value))\n",
        "touch",
    ),
    # The shape the `_` filter let through for a round: the public name touches
    # nothing and the helper that touches everything was not enumerated.
    "a public function reading through a private helper": (
        "def _fetch(db: Session, book_ids: list[int]) -> list[Filled]:\n"
        "    return db.query(CustomFieldValue).filter(\n"
        "        CustomFieldValue.book_id.in_(book_ids)\n"
        "    ).all()\n",
        "touch",
    ),
    "a method reading a mapping by book id": (
        "def on(self, book_id: int) -> list[Filled]:\n"
        "    return self._by_book.get(book_id, [])\n",
        "name",
    ),
    "a book shaped parameter typed as an int": (
        "def values_on(db: Session, book: int) -> list[Filled]:\n"
        "    return []\n",
        "name",
    ),
}

#: Shapes neither pass may report, so neither can be satisfied by reporting
#: everything.
NOT_SIGNATURE_OFFENCES: dict[str, str] = {
    "the real reader": (
        "def values_on(db: Session, book: Book) -> list[Filled]:\n"
        "    return db.query(CustomFieldValue).filter(\n"
        "        CustomFieldValue.book_id == book.id\n"
        "    ).all()\n"
    ),
    "a batch reader taking Books": (
        "def values_for(db: Session, books: Sequence[Book]) -> list[Filled]:\n"
        "    return db.query(CustomFieldValue).filter(\n"
        "        CustomFieldValue.book_id.in_([b.id for b in books])\n"
        "    ).all()\n"
    ),
    "an operation on definitions only": (
        "def rename(db: Session, field: CustomField, name: str) -> CustomField:\n"
        "    field.name = name\n"
        "    return field\n"
    ),
    "the pure rule": (
        "def link_target(kind: CustomFieldKind, value: str) -> str | None:\n"
        "    return None\n"
    ),
}


def _source_modules() -> dict[str, str]:
    """Every backend module this rule applies to, keyed by relative path."""
    return {
        str(path.relative_to(BACKEND)): path.read_text()
        for path in BACKEND.rglob("*.py")
        if path.relative_to(BACKEND).parts[0] not in {"tests", "migrations", ".venv"}
    }


@pytest.fixture
def member(db) -> User:
    user = User(username="reader", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def book(db, member) -> Book:
    row = Book(title="Solaris", added_by_user_id=member.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def other_book(db, member) -> Book:
    row = Book(title="Roadside Picnic", added_by_user_id=member.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def link_field(db) -> CustomField:
    field = define(db, "Calibre-web", CustomFieldKind.URL)
    db.commit()
    db.refresh(field)
    return field


@pytest.fixture
def text_field(db) -> CustomField:
    field = define(db, "Bought from", CustomFieldKind.TEXT)
    db.commit()
    db.refresh(field)
    return field


class TestOnlyABookReachesAValue:
    def test_no_module_but_the_seam_imports_the_value(self):
        offenders = sorted(
            name
            for name, source in _source_modules().items()
            if name not in VALUE_READERS and "CustomFieldValue" in _imported_names(source)
        )
        assert offenders == [], (
            "These read a custom field value directly instead of asking "
            f"`custom_fields.py` for it: {offenders}"
        )

    @pytest.mark.parametrize("spelling", sorted(EVASIONS), ids=sorted(EVASIONS))
    def test_every_spelling_of_the_import_is_caught(self, spelling):
        assert "CustomFieldValue" in _imported_names(EVASIONS[spelling])

    @pytest.mark.parametrize("spelling", sorted(NOT_OFFENCES), ids=sorted(NOT_OFFENCES))
    def test_it_does_not_report_an_import_that_is_not_one(self, spelling):
        assert "CustomFieldValue" not in _imported_names(NOT_OFFENCES[spelling])

    def test_the_module_offers_something_to_check(self):
        """A pass over an empty enumeration is a pass that says nothing.

        Both passes below are `assert offenders == []`, which an enumeration
        that found no functions satisfies for ever.

        Three numbers, and the middle one is the reason this test grew a third
        assertion. Measured at the tip: **10** functions in the walk, **8** of
        them public, and **4** touching the table. The walk deliberately covers
        more than the public surface (see `_module_functions`), so asserting
        only the total would pass just as well if the private half went missing
        again.
        """
        functions = _module_functions()
        assert len(functions) >= 10, sorted(functions)
        assert len(_public_names(functions)) == 8, _public_names(functions)
        touching = [name for name, node in functions.items() if _touches_the_table(node)]
        assert sorted(touching) == ["remove", "resolve_merge", "values_on", "write"]

    def test_the_walk_covers_private_functions(self):
        """The filter that used to be here is the hole, not a tidiness choice.

        A snippet parsed in isolation says nothing about whether the walk over
        the real module would have found it, so this asks the tree: both of
        this module's private functions have to be in the enumeration the touch
        pass reads. `EVASIONS` holds the shape they let through.
        """
        found = _module_functions()

        assert {"_kind_of", "_stored_form"} <= set(found), sorted(found)

    def test_every_public_reader_of_a_value_is_handed_a_book(self):
        """The privacy rule, enforced against the module rather than a list.

        A function that reaches `custom_field_values` and was not handed a
        `Book` is answering "who may see this" from something a caller can
        invent. `Book` cannot be produced without a query, and every query that
        produces one has already applied `visible_to()`.
        """
        offenders = sorted(
            name
            for name, node in _module_functions().items()
            if name not in PAST_A_BOOK
            and _touches_the_table(node)
            and not _takes_a_book(node)
        )
        assert offenders == [], (
            "These read or write a custom field value without being handed a Book, "
            f"so nothing has checked who may see it: {offenders}. Either take a "
            f"`Book`, or argue for a third entry in PAST_A_BOOK ({sorted(PAST_A_BOOK)})."
        )

    def test_every_book_shaped_parameter_is_a_book(self):
        """Pass three, for the shape pass two cannot see.

        A method that reads a mapping rather than naming the table
        (`Values.on(self, book_id: int)`, in the version this module started
        as) touches no table and would go unreported.
        """
        offenders = sorted(
            f"{name}({parameter})"
            for name, node in _module_functions().items()
            for parameter, annotation in _annotations(node)
            if "book" in parameter.lower() and "Book" not in annotation
        )
        assert offenders == [], (
            f"These name a book and are annotated as something else: {offenders}"
        )

    @pytest.mark.parametrize("shape", sorted(SIGNATURE_EVASIONS), ids=sorted(SIGNATURE_EVASIONS))
    def test_the_passes_report_the_shapes_they_exist_for(self, shape):
        """A guard is not evidence until somebody has tried to evade it.

        Every one of these was written against the passes rather than against
        the tree, and the first of them is the shape the hand-written pair
        permitted.
        """
        source, reported_by = SIGNATURE_EVASIONS[shape]
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.FunctionDef)
        if reported_by == "touch":
            assert _touches_the_table(node) and not _takes_a_book(node)
        else:
            assert any(
                "book" in parameter.lower() and "Book" not in annotation
                for parameter, annotation in _annotations(node)
            )

    @pytest.mark.parametrize("shape", sorted(NOT_SIGNATURE_OFFENCES), ids=sorted(NOT_SIGNATURE_OFFENCES))
    def test_the_passes_leave_alone_what_is_not_an_offence(self, shape):
        """So neither pass can be satisfied by reporting everything."""
        node = ast.parse(NOT_SIGNATURE_OFFENCES[shape]).body[0]
        assert isinstance(node, ast.FunctionDef)
        assert not (_touches_the_table(node) and not _takes_a_book(node))
        assert not any(
            "book" in parameter.lower() and "Book" not in annotation
            for parameter, annotation in _annotations(node)
        )

    def test_the_definition_cannot_be_walked_to_its_values(self):
        """`CustomField.values` would read every Book's value for a field from
        a row nobody had to be allowed to see, and a lazy relationship is
        invisible to the import pass above."""
        assert not hasattr(CustomField, "values")

    def test_the_named_ways_past_a_book_have_the_callers_they_claim(self):
        """The same counting `test_reading.py` does, and for the same reason.

        Growing either list is allowed; growing it without saying so here is
        not. **Call sites, not modules**: a second `resolve_merge` call inside
        `routers/books.py` would leave a set of module names unchanged.
        """
        calls: dict[str, list[str]] = {name: [] for name in PAST_A_BOOK}
        for name, source in _source_modules().items():
            if name == "custom_fields.py":
                continue
            for node in ast.walk(ast.parse(source)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in calls
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "custom_fields"
                ):
                    calls[node.func.attr].append(f"{name}:{node.lineno}")

        assert len(calls["remove"]) == 1, calls
        assert len(calls["resolve_merge"]) == 1, calls


class TestALinkIsNotWhateverSomebodyTyped:
    #: Every one of these is a string a person can type into a text box, and
    #: every one of them is `<a href>` doing something other than going to a
    #: web page. `//host` is the quiet one: it carries no scheme at all and
    #: inherits the page's, so it is a link off this deployment that looks
    #: relative.
    REFUSED = {
        "javascript": "javascript:alert(1)",
        "javascript in caps": "JavaScript:alert(1)",
        "javascript split by a tab": "java\tscript:alert(1)",
        "javascript behind a control character": "\x01javascript:alert(1)",
        "data uri": "data:text/html,<script>alert(1)</script>",
        "vbscript": "vbscript:msgbox(1)",
        "scheme relative": "//evil.example/x",
        "a bare path": "/books/12",
        "no scheme at all": "calibre.example/book/12",
        "no host": "https:///book/12",
        "credentials": "https://calibre.example@evil.example/",
        "a password": "https://user:pass@evil.example/",
        "a port past the range": "https://calibre.example:99999/x",
        "port zero": "https://calibre.example:0/x",
        "empty": "",
        # A browser ends the authority at the backslash and reads the host as
        # `calibre.example`; `urlsplit` keeps it and reads one long host. The
        # two cannot be reconciled, so it is refused rather than repaired.
        "a backslash in the host": "http://calibre.example\\.evil.example/x",
        # `new URL()` throws on a space outright, so an href built from one is
        # a link nothing can follow. A space is what reaches this function
        # through the route, because `schemas/custom_field.py` removes control
        # characters and collapses whitespace runs rather than deleting them.
        "a space in the host": "https://calibre.example /x",
        # A tab and a newline reach here only from `backup.restore`, which
        # writes through Core and sees no schema. Refused for the same reason
        # and by the same test.
        "a tab in the host": "https://calibre.example\t/x",
        "a newline": "https://calibre.example/a\nb",
        "an empty label": "https://calibre..example/x",
        # WHATWG percent-decodes the host **before** IDNA maps it, so every one
        # of these is `_HOST_SEPARATORS` arriving one step earlier. Measured
        # 2026-08-27 against `new URL(...).host`: all three resolve to
        # `evil.example`. Refused rather than decoded, because decoding is
        # recursive and encodes more than separators.
        "a percent encoded full stop": "https://calibre.example%2eevil.example/x",
        "the same in capitals": "https://calibre.example%2Eevil.example/x",
        "a doubly encoded full stop": "https://calibre.example%252eevil.example/x",
        "a percent encoded fullwidth stop": "https://calibre.example%ef%bc%8eevil.example/x",
        "a percent encoded nul": "https://calibre.example%00/x",
        "a percent encoded slash": "https://calibre.example%2fevil.example/x",
    }

    ACCEPTED = {
        "https": "https://calibre.example/book/12",
        "http on a lan": "http://calibre.lan:8083/book/12",
        "a scheme in caps": "HTTPS://calibre.example/x",
        "an international host": "https://例え.jp/x",
        "a query string": "https://calibre.example/book?id=12&x=1",
        # The other half of the percent rule: an escape in a path or a query is
        # ordinary and both parsers agree about it. Only the host is refused.
        "a percent escape in the path": "https://calibre.example/book/12%20a",
        "a percent escape in the query": "https://calibre.example/x?q=a%20b",
    }

    @pytest.mark.parametrize("case", sorted(REFUSED), ids=sorted(REFUSED))
    def test_it_is_not_a_link(self, case):
        assert link_target(CustomFieldKind.URL, self.REFUSED[case]) is None

    @pytest.mark.parametrize("case", sorted(ACCEPTED), ids=sorted(ACCEPTED))
    def test_it_is_a_link(self, case):
        assert link_target(CustomFieldKind.URL, self.ACCEPTED[case]) is not None

    def test_a_text_field_never_links_however_it_looks(self):
        """The kind is declared, not detected. This is the whole reason it is."""
        assert link_target(CustomFieldKind.TEXT, "https://calibre.example/x") is None

    #: Hosts a browser reads differently from `urlsplit`, and what the browser
    #: reads. The reason this function rebuilds rather than returning its input.
    #:
    #: Measured 2026-08-27 against `new URL(...).host` in node: every left hand
    #: side here is one label to Python and three to a browser, so the
    #: registrable domain is `evil.example` and the link goes there while the
    #: text reads as somewhere this Household trusts.
    SEPARATORS = {
        "an ideographic full stop": "https://calibre.example\u3002evil.example/x",
        "a fullwidth full stop": "https://calibre.example\uff0eevil.example/x",
        "a halfwidth ideographic full stop": "https://calibre.example\uff61evil.example/x",
    }

    @pytest.mark.parametrize("case", sorted(SEPARATORS), ids=sorted(SEPARATORS))
    def test_a_host_a_browser_reads_differently_is_rewritten_to_what_it_reads(self, case):
        """The phishing case, and the reason the URL is rebuilt.

        Not refused: rewritten. The link then goes where the browser was always
        going to send it **and** says so, which is strictly better than storing
        a string that reads as one host and resolves as another.
        """
        assert (
            link_target(CustomFieldKind.URL, self.SEPARATORS[case])
            == "https://calibre.example.evil.example/x"
        )

    def test_the_target_is_rebuilt_rather_than_handed_back(self):
        """`parsed.geturl()` returns the string that came in, separators and
        all. Everything else about the URL survives the rebuild."""
        assert (
            link_target(CustomFieldKind.URL, "HTTPS://Calibre.EXAMPLE:8443/a/b?q=1#f")
            == "https://calibre.example:8443/a/b?q=1#f"
        )

    def test_an_ipv6_host_keeps_its_brackets(self):
        """`hostname` strips them and a bare `::1` in a netloc is not a URL, so
        a naive rebuild would break exactly the LAN case this feature is for."""
        assert (
            link_target(CustomFieldKind.URL, "http://[::1]:8083/book/12")
            == "http://[::1]:8083/book/12"
        )

    def test_a_kind_nobody_recognises_reads_as_text(self):
        """Degrades rather than raising, and in the safe direction.

        `CustomFieldKind('link')` raises `ValueError`, and raising in
        `values_on` would 500 every read of every Book with a value in that
        field, not one Book.

        **Not written to the database, because the database refuses it.**
        `ck_custom_fields_kind` is the first half of this guard and fires on
        both the ORM path and a Core insert, which is what
        `test_schema.py::test_a_kind_nobody_recognises_is_refused_by_the_database`
        pins. This is the second half, for a library restored from an archive
        older than that constraint, so it is asked of the function directly
        rather than through a row nothing can create.
        """
        assert _kind_of(CustomField(name="X", kind="link")) is CustomFieldKind.TEXT

    def test_the_model_carries_the_kind_constraint_the_migration_declares(self):
        """A CHECK in the migration and not in the metadata is a CHECK that is
        not there.

        `Base.metadata.create_all` builds the table from `__table_args__`, so a
        constraint declared only in the revision is absent from every database
        built that way, `--autogenerate` proposes dropping it, and everything
        resting on it is resting on nothing. This one was in that state for a
        round. The other two are asserted beside it so the rule reads as a set
        rather than as one repair.
        """
        # Off `Base.metadata` rather than `Model.__table__`, which a
        # declarative class types as the wider `FromClause`. `backup.py` takes
        # the same route and says so for the same reason.
        declared = {
            str(constraint.name)
            for table in ("custom_fields", "custom_field_values")
            for constraint in Base.metadata.tables[table].constraints
            if constraint.name is not None
        }

        assert {
            "ck_custom_fields_name_bounds",
            "ck_custom_fields_kind",
            "ck_custom_field_values_bounds",
        } <= declared, sorted(declared)

    def test_a_value_the_read_would_rewrite_is_served_as_text(
        self, db, book, link_field
    ):
        """The sharpest form of the phishing case, and it is the **read** end.

        `backup.restore` inserts through Core, so a row can carry a value the
        write path would have rewritten. Serving `link_target`'s answer as
        `href` beside the raw `value` puts two registrable domains in one
        anchor: the reader sees `calibre.example` leading the text and the tap
        goes to `evil.example`.

        So a target is served only when it **is** the value. Inserted the way a
        restore does, since `write()` would rewrite it.
        """
        db.add(
            CustomFieldValue(
                book_id=book.id,
                field_id=link_field.id,
                value="https://calibre.example\u3002evil.example/x",
            )
        )
        db.commit()

        filled = values_on(db, book)

        assert [(row.value, row.href) for row in filled] == [
            ("https://calibre.example\u3002evil.example/x", None)
        ]

    @pytest.mark.parametrize(
        "value",
        [
            "https://calibre.example/book/12",
            "http://calibre.lan:8083/book/12",
            "http://[::1]:8083/x",
            "https://calibre.example/book/12%20a",
            "https://calibre.example",
            "https://xn--80ak6aa92e.com/",
            "https://\u4f8b\u3048.jp/x",
        ],
    )
    def test_a_value_this_app_wrote_keeps_its_link(
        self, db, book, link_field, value
    ):
        """The other half, and the reason the rule above is free.

        `link_target` is idempotent, so anything it produced equals what it
        produces from itself and survives the equality test. A rule that cost
        real links would be a worse answer than the anchor it fixes.
        """
        write(db, book, link_field, value)
        db.commit()

        row = values_on(db, book)[0]

        assert row.href == row.value
        assert row.href is not None

    @pytest.mark.parametrize(
        "value",
        [
            "https://calibre.example/book/12",
            "HTTPS://Calibre.EXAMPLE:8443/a/b?q=1#f",
            "http://[::1]:8083/x",
            "https://a.example/x?",
            "https://a.example/x#",
            "https://\u4f8b\u3048.jp/x",
        ],
    )
    def test_link_target_is_idempotent(self, value):
        """Stated as a property because `values_on` now rests on it.

        The two that normalise are the interesting rows: an empty query and an
        empty fragment are dropped, and applying the function again drops
        nothing more.
        """
        once = link_target(CustomFieldKind.URL, value)

        assert once is not None
        assert link_target(CustomFieldKind.URL, once) == once

    def test_a_stored_value_is_re_checked_on_every_read(self, db, book, link_field):
        """The declaration is not the permission.

        `backup.restore` inserts through Core, where no Pydantic model and no
        validator fires, so a row can reach this table without passing the
        write check. Inserted the same way here.
        """
        db.add(
            CustomFieldValue(
                book_id=book.id, field_id=link_field.id, value="javascript:alert(1)"
            )
        )
        db.commit()

        filled = values_on(db, book)

        assert [(row.value, row.href) for row in filled] == [
            ("javascript:alert(1)", None)
        ]


class TestDefiningAField:
    def test_a_field_is_defined_once_for_the_library(self, db, text_field):
        assert [field.name for field in definitions(db)] == ["Bought from"]

    def test_a_name_that_already_exists_returns_that_field(self, db, text_field):
        again = define(db, "bought FROM", CustomFieldKind.URL)

        assert again.id == text_field.id
        assert again.kind == CustomFieldKind.TEXT

    def test_the_fold_is_pythons_and_not_sqlites(self, db):
        """SQLite's `lower()` is ASCII only, so a name with a non-ASCII capital
        would never match and the insert would hit the binary unique index as a
        500. Measured on `create_tag` before it was fixed."""
        first = define(db, "Ähnliches", CustomFieldKind.TEXT)
        db.commit()

        assert define(db, "ähnliches", CustomFieldKind.TEXT).id == first.id

    def test_the_library_is_capped(self, db):
        for index in range(25):
            define(db, f"Field {index}", CustomFieldKind.TEXT)
        db.commit()

        with pytest.raises(Refused):
            define(db, "One too many", CustomFieldKind.TEXT)

    def test_they_are_listed_in_the_order_they_were_defined(self, db):
        for name in ("Zebra", "Aardvark", "Moose"):
            define(db, name, CustomFieldKind.TEXT)
        db.commit()

        assert [field.name for field in definitions(db)] == ["Zebra", "Aardvark", "Moose"]


class TestRenamingAField:
    def test_every_value_survives_the_rename(self, db, book, text_field):
        write(db, book, text_field, "Oxfam, Cowley Road")
        db.commit()

        rename(db, text_field, "Provenance")
        db.commit()

        filled = values_on(db, book)
        assert [(row.field.name, row.value) for row in filled] == [
            ("Provenance", "Oxfam, Cowley Road")
        ]

    def test_renaming_onto_another_field_is_refused(self, db, text_field, link_field):
        with pytest.raises(Refused):
            rename(db, text_field, "calibre-WEB")

    def test_changing_its_own_capitalisation_is_allowed(self, db, text_field):
        rename(db, text_field, "BOUGHT FROM")
        db.commit()

        assert definitions(db)[0].name == "BOUGHT FROM"


class TestRemovingAField:
    def test_it_takes_its_values_with_it(self, db, book, text_field):
        write(db, book, text_field, "Oxfam")
        db.commit()

        removed = remove(db, text_field)
        db.commit()

        assert removed == 1
        assert definitions(db) == []
        assert values_on(db, book) == []

    def test_no_row_is_orphaned(self, db, book, other_book, text_field, link_field):
        write(db, book, text_field, "Oxfam")
        write(db, other_book, text_field, "A gift")
        write(db, book, link_field, "https://calibre.example/1")
        db.commit()

        remove(db, text_field)
        db.commit()

        assert db.query(CustomFieldValue).count() == 1
        assert db.query(CustomFieldValue).one().field_id == link_field.id


class TestWritingAValue:
    def test_a_value_set_on_one_book_is_not_on_another(
        self, db, book, other_book, text_field
    ):
        write(db, book, text_field, "Oxfam")
        db.commit()

        assert values_on(db, other_book) == []

    def test_a_field_with_no_value_is_absent_rather_than_empty(
        self, db, book, text_field, link_field
    ):
        write(db, book, text_field, "Oxfam")
        db.commit()

        assert [row.field.id for row in values_on(db, book)] == [text_field.id]

    def test_an_empty_value_deletes_the_row(self, db, book, text_field):
        write(db, book, text_field, "Oxfam")
        db.commit()

        write(db, book, text_field, "")
        db.commit()

        assert db.query(CustomFieldValue).count() == 0

    def test_clearing_a_field_nobody_filled_in_is_not_an_error(self, db, book, text_field):
        assert write(db, book, text_field, "") is None

    def test_writing_twice_updates_the_one_row(self, db, book, text_field):
        write(db, book, text_field, "Oxfam")
        db.commit()
        write(db, book, text_field, "A gift")
        db.commit()

        assert db.query(CustomFieldValue).count() == 1
        assert values_on(db, book)[0].value == "A gift"

    def test_a_url_field_refuses_a_value_that_is_not_one(self, db, book, link_field):
        with pytest.raises(Refused):
            write(db, book, link_field, "javascript:alert(1)")

    def test_a_url_field_stores_the_rebuilt_form(self, db, book, link_field):
        """Value and target are one string, and both name the host a browser
        reaches. `schemas/custom_field.py` has already removed the control
        characters by the time the route calls this; what is left for the seam
        is the host."""
        write(db, book, link_field, "HTTPS://Calibre.EXAMPLE\u3002evil.example/x")
        db.commit()

        row = values_on(db, book)[0]
        assert row.value == "https://calibre.example.evil.example/x"
        assert row.href == row.value

    def test_a_url_field_refuses_a_value_no_browser_could_follow(
        self, db, book, link_field
    ):
        """A space reaches here because the schema collapses runs rather than
        removing them, and `new URL()` throws on it."""
        with pytest.raises(Refused):
            write(db, book, link_field, "https://calibre.example /x")

    def test_a_text_field_takes_whatever_it_is_given(self, db, book, text_field):
        write(db, book, text_field, "javascript:alert(1)")
        db.commit()

        row = values_on(db, book)[0]
        assert row.value == "javascript:alert(1)"
        assert row.href is None


class TestReadingOneBook:
    def test_a_book_with_nothing_in_it_reads_empty(self, db, book, text_field):
        assert values_on(db, book) == []

    def test_it_costs_one_statement_however_many_fields_are_filled(
        self, db, book, text_field, link_field
    ):
        """The definitions are joined on rather than looked up per row.

        The obvious implementation reads the values and then the name of each
        field, which is one query plus one per row: two fields would measure 3.
        """
        write(db, book, text_field, "Oxfam")
        write(db, book, link_field, "https://calibre.example/1")
        db.commit()
        # `commit()` expired the object, so the first touch of `.id` reloads
        # the row. Refreshed here rather than counted: the assertion below
        # measured **2** before this line, one of them the fixture's.
        db.refresh(book)

        statements: list[str] = []

        def record(conn, cursor, statement, *rest):
            statements.append(statement)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            filled = values_on(db, book)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(statements) == 1, statements
        assert [row.field.name for row in filled] == ["Bought from", "Calibre-web"]


class TestMergingTwoBooks:
    def test_the_losers_value_moves_across(self, db, book, other_book, text_field):
        write(db, other_book, text_field, "Oxfam")
        db.commit()

        custom_fields.resolve_merge(db, book.id, [other_book.id])
        db.commit()

        assert values_on(db, book)[0].value == "Oxfam"

    def test_the_keepers_own_value_wins(self, db, book, other_book, text_field):
        write(db, book, text_field, "A gift")
        write(db, other_book, text_field, "Oxfam")
        db.commit()

        custom_fields.resolve_merge(db, book.id, [other_book.id])
        db.commit()

        assert [row.value for row in values_on(db, book)] == ["A gift"]
        assert db.query(CustomFieldValue).count() == 1

    def test_nothing_happens_with_no_losers(self, db, book, text_field):
        write(db, book, text_field, "Oxfam")
        db.commit()

        custom_fields.resolve_merge(db, book.id, [])

        assert db.query(CustomFieldValue).count() == 1
