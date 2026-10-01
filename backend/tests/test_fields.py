"""Who may be told a custom field exists, and the rules that nothing else
decides it.

The behaviour a member meets is pinned in
`tests/routers/test_books_custom_fields.py`, beside the routes that serve it.
What is here is the cross module part, and it is three rules rather than one,
because this question has three ways back open where the collection version
had one.

**One: every read of `custom_fields` is classified.** The same pass
`test_shelving.py` runs one entity over, sharing
`tests/test_shelf.py::_book_owned_offences` rather than copying the walk.

**Two: the whole table read has the callers it claims.** This is the rule
`test_shelving.py` does not need and this one cannot do without.
`Shelving.listable` reads `collections` in the same statement that filters it,
so a registry entry can see the scoping. `Fields.listable` filters
`custom_fields.definitions`, which reads the table whole for three callers and
is right to: `define` and `rename` fold every name because uniqueness is whole
table of necessity. So the read stays unscoped and correct, and what a new
route could do is **call it and publish the rows**, which the registry cannot
see because the read itself has not changed. The caller count is what sees it.

**Three: nothing but field ids crosses out of the value table.** Two of the
three reads in `fields.py` go through the Shelf and the third is unscoped on
purpose. What makes the third safe is the bound rather than the predicate, so
the bound is asserted: those statements may name `book_id` and `field_id` and
nothing else, which is what keeps a value, a count or a book out of the answer.

Every plant below is run through `_report`, `_definition_callers` or
`_named_attributes_of`, which are the functions the tree is read with, rather
than through a copy: a fixture exercising its own copy reports on a rule
nothing else uses.
"""

import ast
from datetime import UTC, datetime
from typing import Final

import pytest

import custom_fields
from enums import CustomFieldKind
from fields import Fields
from models import Book, CustomField, CustomFieldValue, User
from tests.test_house_rules import _source_modules
from tests.test_shelf import _book_owned_offences, _statement_at
from tests.test_tags import _reaches_private

#: The entity, as the shared pass takes it.
#:
#: `CustomFieldValue` is a different name and is not in this set: that table is
#: `BOOK_OWNED`'s and is classified in `tests/test_shelf.py`. This rule is
#: about the **definition**, which hangs off no Book at all and so is invisible
#: to every pass in that file.
CUSTOM_FIELD: Final = frozenset({"CustomField"})

#: Every read of `CustomField` **the pass reports**, and why that one is safe.
#:
#: Not every read of the table there is. Four families sit outside it, named
#: rather than armed, and the first is the live one:
#:
#: * **A caller of `custom_fields.definitions`.** The pass reports the read
#:   inside that function and says nothing about who calls it, so a new route
#:   publishing its rows is invisible here. That is
#:   `TestTheWholeTableReadHasTheCallersItClaims`, and it is the rule this
#:   registry structurally cannot be.
#: * **`backup.py`** reads the table through a runtime bound name in `_TABLES`,
#:   so no pass reading the arguments to `query()` sees it. Admin only, which
#:   `tests/test_shelf.py` asserts separately, and unfiltered on purpose
#:   because an archive missing rows restores a library missing them.
#: * **A raw `text(...)` read.** Names no entity, so the pass is blind to it.
#:   No live member, measured 2026-10-01 over `_source_modules()`.
#:   `tests/test_shelf.py` carries the same hole for `books`, with the argument
#:   for naming it rather than chasing it.
#: * **A computed entity.** `model = getattr(models, "CustomField")` then
#:   `db.query(model)`. The alias resolver follows an assignment from a name
#:   and not from a call, so the pass reports nothing: measured 2026-10-01,
#:   that probe comes back empty. It is also invisible to the walk over
#:   parameterised readers, whose test is on a call's arguments. No live
#:   member: no module outside `shelf.py` reaches an entity off `models`
#:   through `getattr`. Contrived, and named because a list of three read as
#:   closed.
#:
#: Keyed on the enclosing function and the whole flattened statement,
#: positionally in line order, the key `COLLECTION_READERS` uses and for the
#: same reason: the two `db.get(CustomField, field_id)` entries below are
#: identical statements and differ only in which door they serve, so keyed on
#: the statement alone their reasons would be interchangeable.
FIELD_READERS: Final = {
    "custom_fields.py": [
        (
            "definitions: return db.query(CustomField).order_by(CustomField.id).all()",
            "**the whole table, deliberately unscoped, with three callers and "
            "no fourth.** `define` and `rename` fold every name in Python "
            "because uniqueness is whole table of necessity, and a scoped fold "
            "would answer 'free' for a name already taken and turn a 409 into "
            "a 500 against the unique index. `Fields.listable` is the third "
            "and is the only one that publishes, and it narrows the rows in "
            "the comprehension it reads them into. **The scoping is therefore "
            "not in this statement**, which is what the collection rule relies "
            "on, so the caller count is the arm that stands in for it.",
        ),
        (
            "values_on: rows = ( db.query(CustomFieldValue, CustomField) "
            ".join(CustomField, CustomField.id == CustomFieldValue.field_id) "
            ".filter(CustomFieldValue.book_id == book.id) "
            ".order_by(CustomFieldValue.field_id) .all() )",
            "one Book's values with their definitions joined on, so the name "
            "can be rendered beside the value. Takes a `Book` object and never "
            "an id, which is `custom_fields.py`'s own privacy rule: a `Book` "
            "has already been through the Shelf. Every definition it can reach "
            "is one this Book carries a value in, which is `Fields`' first arm "
            "by construction, so the names on that payload are exactly the "
            "names the list would have shown the same caller.",
        ),
    ],
    "routers/books.py": [
        (
            "_custom_field: field = db.get(CustomField, field_id)",
            "the definition an id door names. **Gated in the same statement's "
            "condition** by `Fields.addressable`, which collapses a field the "
            "caller may not be told about into the 404 an absent id already "
            "gets. Two callers, the rename and the value write, and both "
            "answer with the field's `name`, which is why leaving it ungated "
            "beside a scoped list would have moved a broadcast to a poll.",
        ),
        (
            "_any_custom_field: field = db.get(CustomField, field_id)",
            "the same read for the admin delete, and **deliberately ungated**, "
            "with the measurement at its own site: an admin has no privilege "
            "over another member's private books, so gating it would leave a "
            "field whose every value sits on those books undeletable for good, "
            "and with a ceiling of 25 the delete is the only verb that frees a "
            "slot. It answers 404 or 204 and publishes no name in either.",
        ),
    ],
}


def _key(source: str, line: int) -> str:
    """`<enclosing function>: <flattened statement>`, both off the `ast`.

    The key `COLLECTION_READERS` is read with, spelled here rather than
    imported for the reason that file gives at its own copy: it is four lines,
    and importing a private helper out of a sibling test to save them couples
    two registries meant to move independently.
    """
    enclosing = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.lineno <= line <= (node.end_lineno or node.lineno)
    ]
    statement = _statement_at(source, line)
    if not enclosing:
        return statement
    holder = max(enclosing, key=lambda node: node.lineno)
    return f"{holder.name}: {statement}"


def _report(sources: dict[str, str]) -> list[str]:
    """The comparison, over whatever corpus it is handed."""
    found = {
        name: lines
        for name, source in sources.items()
        if (lines := _book_owned_offences(source, CUSTOM_FIELD))
    }

    report: list[str] = []
    for name in sorted(set(found) | set(FIELD_READERS)):
        lines = found.get(name, [])
        entries = FIELD_READERS.get(name, [])
        if len(lines) != len(entries):
            shown = "\n".join(
                f"      {name}:{line}  {_key(sources.get(name, ''), line)}"
                for line in lines
            )
            report.append(
                f"  {name}: {len(lines)} reads, {len(entries)} classified\n{shown}"
            )
            continue
        for line, (expected, _) in zip(lines, entries, strict=True):
            actual = _key(sources.get(name, ""), line)
            if actual != expected:
                report.append(
                    f"  {name}:{line} is not what its entry is keyed on.\n"
                    f"      entry expects: {expected}\n"
                    f"      statement is:  {actual}"
                )
    return report


def _dotted(node: ast.expr) -> str | None:
    """A call target written as a dotted name, or None for anything else.

    `cf.definitions` and `backend.custom_fields.definitions` both come back as
    text; `getattr(cf, name)()` and `(x or y).definitions()` come back None,
    which is where this rule stops and the docstring below says so.
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _definition_bindings(source: str) -> tuple[frozenset[str], frozenset[str]]:
    """What this module calls the `custom_fields` module and the function.

    **Derived from the module's own import statements rather than matched as
    two literal spellings**, which is the instrument `_entity_aliases` in
    `tests/test_shelf.py` already uses and the reason it exists. Two literals
    were the first version of this rule and a non author broke it in one line:
    `import custom_fields as cf` restored the broadcast with every arm green.

    A module level `def definitions` also binds the name, so `custom_fields.py`
    is read by the same rule as everybody else rather than by an exemption.
    """
    modules: set[str] = set()
    functions: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "custom_fields" or alias.name.endswith(
                    ".custom_fields"
                ):
                    modules.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or not (
                node.module == "custom_fields"
                or node.module.endswith(".custom_fields")
            ):
                continue
            for alias in node.names:
                if alias.name == "definitions":
                    functions.add(alias.asname or alias.name)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "definitions":
            functions.add(node.name)
    return frozenset(modules), frozenset(functions)


def _reaches_definitions(
    target: ast.expr, modules: frozenset[str], functions: frozenset[str]
) -> bool:
    """Whether this call target resolves to `custom_fields.definitions`.

    A free function rather than a closure over the loop below, because `ruff`
    refuses one that binds a loop variable and is right to: the bindings
    change per module and a closure reading them late would answer for
    whichever module the loop had reached.
    """
    dotted = _dotted(target)
    if dotted is None:
        return False
    if dotted in functions:
        return True
    head, _, tail = dotted.rpartition(".")
    if tail != "definitions" or not head:
        return False
    # The head is what the import bound, or a dotted path whose last segment
    # is the module: `backend.custom_fields.definitions` binds `backend` and
    # names the module two segments along.
    return head in modules or head.rpartition(".")[2] == "custom_fields"


def _definition_callers(sources: dict[str, str]) -> list[str]:
    """Every call of `custom_fields.definitions`, under whatever local name.

    Five spellings reach it: the plain qualified call, a module alias, a from
    import with or without an alias, the package qualified form, and
    `getattr(<module>, "definitions")`. Each is resolved against the bindings
    the module's own imports make, so a rename at the import is a rename here.
    The `getattr` arm is the one `_reaches_private` in `tests/test_tags.py`
    already carries at its own site, for the reason it gives there: a name
    carried as a string is invisible to any attribute walk.

    **What it reports is a direct call under a resolved name, and that is
    narrower than "a new publisher".** This docstring claimed the wider thing.
    A wrapper is reported only because a wrapper has to contain such a call,
    so a wrapper whose call is written in one of the two shapes below goes
    past exactly as a bare call in that shape does.

    **Those two are outside the rule and are named rather than chased**, the
    way the sibling registry in `tests/test_shelving.py` names raw SQL:

    * **Binding the function to a local and calling the local.**
      `read = custom_fields.definitions` then `read(db)`. Following it is flow
      analysis, which is the machinery `shelf.py` exists to have retired.
    * **`getattr` on a computed name.** The literal is resolved below; a name
      assembled at runtime is not, and no walk over call targets resolves one.

    Both need a line written for no other purpose, in a module whose import of
    `custom_fields` is itself the thing a reviewer reads. Neither is live:
    measured over `_source_modules()` on 2026-10-01, no module binds this
    function to a local or reaches it through a computed `getattr`.
    """
    sites: list[str] = []
    for name, source in sorted(sources.items()):
        modules, functions = _definition_bindings(source)
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            # `getattr(cf, "definitions")(db)`: the call's target is itself a
            # call, and the name it resolves is a string the walk above cannot
            # see. Unwrapped here rather than left open, because one token is
            # all it costs to write and the literal is the form somebody
            # reaching for it would write first.
            if (
                isinstance(target, ast.Call)
                and isinstance(target.func, ast.Name)
                and target.func.id == "getattr"
                and len(target.args) >= 2
                and isinstance(target.args[1], ast.Constant)
                and target.args[1].value == "definitions"
                and _dotted(target.args[0]) in modules
            ):
                sites.append(f"{name}:{node.lineno}")
                continue
            if _reaches_definitions(target, modules, functions):
                sites.append(f"{name}:{node.lineno}")
    return sites


def _named_attributes_of(source: str, entity: str) -> list[str]:
    """Which columns of `entity` this source names, sorted and deduplicated.

    An attribute walk and nothing cleverer: the question is which column names
    appear, and a column reached any other way is outside it.

    **What it misses is an aliased entity**, measured: `V = aliased(
    CustomFieldValue)` then `V.value` leaves this walk returning exactly the
    two columns it expects. That read is still caught, by the per module
    statement count in `BOOK_OWNED_READERS` rather than by this walk, so the
    class is held and this instrument is not what holds it. Said here because
    a reader who thinks the attribute walk covers it will strengthen the wrong
    thing.

    **Two shapes that look like misses and are not**, both measured rather
    than reasoned: `CustomFieldValue.__table__.c.value` reds, because the
    chain still roots on the bare name and `__table__` lands in the set; and a
    star import does not rebind the entity, so the spelling is reported
    exactly as before.
    """
    named = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == entity
    }
    return sorted(named)


class TestNothingElseDecidesWhoMayBeToldAFieldExists:
    """`fields.Fields` is the only place this question is answered.

    **The counterpart of `TestNothingElseDecidesWhoMayBeToldACollectionExists`,
    one entity over**, sharing the instrument rather than a base class for the
    reason that file gives: a second walk is a second thing to keep in step,
    over a repository that has measured seven guards whose population was
    matched from source text and every one wrong at least once.

    **Why `custom_fields` is not simply in `BOOK_OWNED`.** That set is derived
    from the foreign keys **into** `books`, and a definition has none: it is
    reached from a Book through `custom_field_values` rather than pointing at
    one. Widening a foreign key derivation to catch it turns it into an
    inclusion list, which is the shape that goes stale.
    """

    #: The module the reader's private state belongs to.
    OWNER: Final = "fields.py"

    def test_every_definition_reader_is_classified(self) -> None:
        report = _report(_source_modules())

        assert not report, (
            "A statement reads the custom field definitions, and either is not "
            "classified or is not the statement its entry was written for.\n\n"
            + "\n".join(report)
            + "\n\n  A definition carries no member any query may read, so "
            "nothing in a row says who may be told it exists: the answer is "
            "whoever may read a book holding a value in it, and `fields.Fields` "
            "is where that is decided. A field name is free text a member "
            "typed, so serving one unasked tells the house that somebody's "
            "books hold a fact under that label.\n\n"
            "  If your read is genuinely safe, add an entry to FIELD_READERS "
            "with the statement exactly as printed above and why. If you "
            "cannot write the reason in a sentence, ask `Fields` instead."
        )

    def test_a_bypass_beside_the_reader_is_not_exempt_for_being_there(self) -> None:
        """The plant the tag rule shipped green on, run here before this ships.

        Exempting the owning module by filename would make any read anywhere in
        it exempt with no entry and no reason: append a function returning the
        whole table, point the route at it, and the disclosure is back with the
        guard green.
        """
        sources = dict(_source_modules())
        sources["fields.py"] += (
            "\n\ndef every_field_there_is(db):\n"
            "    return db.query(CustomField).order_by(CustomField.id).all()\n"
        )
        rewritten = sources["routers/books.py"].replace(
            "return Fields.seen_by(db, current_user.id).listable()",
            "return every_field_there_is(db)",
            1,
        )
        assert rewritten != sources["routers/books.py"], (
            "the list route no longer spells the call this plant rewrites, so "
            "nothing was planted"
        )
        sources["routers/books.py"] = rewritten

        report = _report(sources)

        assert any("every_field_there_is" in line for line in report), report

    def test_deleting_an_unrelated_entry_does_not_explain_that_red(self) -> None:
        """A red for the wrong reason is not a red.

        The plant above is reported with another module's entry knocked out
        from under it, so the failure is the plant rather than an accident of
        the corpus holding exactly one spare offence.
        """
        sources = dict(_source_modules())
        sources["fields.py"] += (
            "\n\ndef every_field_there_is(db):\n"
            "    return db.query(CustomField).all()\n"
        )
        knocked_out = sources["custom_fields.py"].replace(
            "        .order_by(CustomFieldValue.field_id)\n", "", 1
        )
        # The control. If the replace no ops, the arm still passes and has
        # quietly stopped perturbing the unrelated thing it exists to perturb.
        assert knocked_out != sources["custom_fields.py"], (
            "`values_on` no longer spells the ordering this control removes, "
            "so nothing unrelated was moved"
        )
        sources["custom_fields.py"] = knocked_out

        report = _report(sources)

        assert any("every_field_there_is" in line for line in report), report

    def test_the_readers_private_state_is_reached_from_nowhere_else(self) -> None:
        """The half the registry structurally cannot see: where the rows go.

        The state at risk is `_carried`, every field id some book holds a value
        in, with no viewer applied. One line swapping a `Fields` for another
        object's index is a whole gate green on a member reading a hidden name,
        which is measured on the tag version of this rule.

        `_reaches_private`'s docstring carries the three mechanisms outside the
        walk and why `@final` and `__slots__` are load bearing for the
        sentence. Not restated here.
        """
        private = frozenset(
            name
            for name in set(Fields.__slots__) | set(vars(Fields))
            if name.startswith("_") and not name.startswith("__")
        )
        assert private, "Fields declares no private state, so this arm tests nothing"

        reaching = {
            name: sites
            for name, source in _source_modules().items()
            if name != self.OWNER and (sites := _reaches_private(source, private))
        }

        assert not reaching, (
            "`Fields._carried` is every carried field id with no viewer, and "
            "the registry entry for the read behind it is safe only because "
            f"nothing but the reader holds it. These reach into it: {reaching}."
        )


class TestTheWholeTableReadHasTheCallersItClaims:
    """`custom_fields.definitions` reads every row, so who calls it is the rule.

    This is the arm `test_shelving.py` has no counterpart for, and the reason
    is in this file's docstring: there the read and the filter are one
    statement, here they are two modules. A route calling `definitions` and
    returning the rows restores the disclosure with every other arm green,
    because the read it reaches is the correct one.

    **What it reports is a direct call under a name resolved from the module's
    own imports, which is narrower than "a new publisher".** The two shapes
    `_definition_callers` names as outside it go past here too, wrapped in a
    route or not. The inside arm is keyed on the calling functions rather than
    on how many there are, because a count at two is satisfied by a new public
    wrapper that takes one of the folds' place.
    """

    def test_one_module_outside_custom_fields_calls_it(self) -> None:
        sources = {
            name: source
            for name, source in _source_modules().items()
            if name != "custom_fields.py"
        }

        callers = _definition_callers(sources)

        assert callers == [f"fields.py:{_line_of_the_listable_call()}"], (
            "`custom_fields.definitions` reads every definition in the library "
            "with no viewer applied, and `fields.Fields.listable` is the one "
            f"caller outside its own module that narrows them. These call it: "
            f"{callers}. A second caller is a decision about who may be told a "
            "field exists, not an edit: narrow the rows through `Fields` or "
            "argue here for the exception."
        )

    def test_inside_its_own_module_the_two_folds_call_it_and_nothing_else(
        self,
    ) -> None:
        """The fold, which is whole table of necessity and must stay that way.

        Without this the arm above is satisfied by deleting the function: the
        two uniqueness checks are what make the unscoped read correct rather
        than tolerated, and a scoped fold would answer "free" for a name
        already taken.

        **Keyed on which functions call it, not on how many.** A bare equality
        at two is defeated by routing one of the two folds through a new
        public wrapper: the count stays at two, the wrapper becomes a second
        publisher, and the outside walk never names it because the route calls
        the wrapper rather than this function.
        """
        source = _source_modules()["custom_fields.py"]
        tree = ast.parse(source)
        callers = sorted(
            {
                holder.name
                for site in _definition_callers({"custom_fields.py": source})
                for holder in ast.walk(tree)
                if isinstance(holder, ast.FunctionDef)
                and holder.lineno
                <= int(site.rpartition(":")[2])
                <= (holder.end_lineno or holder.lineno)
            }
        )

        assert callers == ["define", "rename"], (
            "`custom_fields.definitions` reads every row with no viewer "
            f"applied. Inside its own module the two uniqueness folds are what "
            f"make that correct, and these call it: {callers}. A third is a "
            "new publisher of the whole table, whatever the route in front of "
            "it is called."
        )

    def test_a_second_caller_is_reported(self) -> None:
        """The plant, because an `== [one thing]` is also satisfied by a walk
        that found nothing and a corpus that moved."""
        sources = {
            name: source
            for name, source in _source_modules().items()
            if name != "custom_fields.py"
        }
        sources["routers/books.py"] += (
            "\n\ndef _every_field(db):\n    return custom_fields.definitions(db)\n"
        )

        callers = _definition_callers(sources)

        assert any(site.startswith("routers/books.py:") for site in callers), callers

    def test_a_second_route_under_an_aliased_module_is_reported(self) -> None:
        """The scenario this guard exists for, planted as a whole.

        **Not rewriting the scoped route**, which a behaviour arm elsewhere
        already catches, but **adding one beside it** under an import alias,
        with the list route untouched. Four mutants of this family were green
        against the first version of this rule, which matched two literal
        spellings; a non author found them, and this is the one that matters.
        """
        sources = {
            name: source
            for name, source in _source_modules().items()
            if name != "custom_fields.py"
        }
        before = _definition_callers(sources)
        sources["routers/books.py"] += (
            "\n\nimport custom_fields as cf\n\n"
            '@router.get("/custom-fields/all")\n'
            "def every_custom_field(db: DbSession, current_user: CurrentUser):\n"
            "    return cf.definitions(db)\n"
        )

        after = _definition_callers(sources)

        assert len(after) == len(before) + 1, (before, after)
        assert any(site.startswith("routers/books.py:") for site in after), after

    #: Every spelling that reaches the function, and the arm is that each one
    #: is reported.
    #:
    #: **Not chosen by the author of the rule.** The first version matched two
    #: literals, the plain qualified call and a bare name; a non author planted
    #: these into the real router and found **five of six invisible**, with the
    #: broadcast restored and every arm green. They are kept as a table rather
    #: than as prose because the table is what a future narrowing is read
    #: against.
    REACHES_IT: Final = {
        "the plain qualified call": (
            "import custom_fields\n\ndef f(db):\n    return custom_fields.definitions(db)\n"
        ),
        "a module alias": (
            "import custom_fields as cf\n\ndef f(db):\n    return cf.definitions(db)\n"
        ),
        "a from import": (
            "from custom_fields import definitions\n\ndef f(db):\n    return definitions(db)\n"
        ),
        "a from import with an alias": (
            "from custom_fields import definitions as every\n\n"
            "def f(db):\n    return every(db)\n"
        ),
        "the package qualified form": (
            "import backend.custom_fields\n\n"
            "def f(db):\n    return backend.custom_fields.definitions(db)\n"
        ),
        "getattr on a literal name": (
            "import custom_fields as cf\n\n"
            'def f(db):\n    return getattr(cf, "definitions")(db)\n'
        ),
    }

    #: The two shapes outside the rule, pinned as outside rather than stated.
    #:
    #: An arm asserting a limit is what stops the limit being read as a miss
    #: somebody will later close by accident and leave undocumented. Both are
    #: measured dead over `_source_modules()`; `_definition_callers` carries
    #: why neither is chased.
    REACHES_IT_UNSEEN: Final = {
        "the function bound to a local": (
            "import custom_fields\n\ndef f(db):\n"
            "    read = custom_fields.definitions\n    return read(db)\n"
        ),
        "getattr on a computed name": (
            "import custom_fields as cf\n\ndef f(db, name):\n"
            "    return getattr(cf, name)(db)\n"
        ),
    }

    @pytest.mark.parametrize("spelling", sorted(REACHES_IT), ids=sorted(REACHES_IT))
    def test_every_spelling_that_reaches_it_is_reported(self, spelling: str) -> None:
        callers = _definition_callers({"somewhere.py": self.REACHES_IT[spelling]})

        assert callers == ["somewhere.py:4"], callers

    @pytest.mark.parametrize(
        "spelling", sorted(REACHES_IT_UNSEEN), ids=sorted(REACHES_IT_UNSEEN)
    )
    def test_the_two_shapes_outside_the_rule_are_outside_it(
        self, spelling: str
    ) -> None:
        callers = _definition_callers({"somewhere.py": self.REACHES_IT_UNSEEN[spelling]})

        assert callers == [], callers

    def test_a_name_this_module_never_imported_is_not_reported(self) -> None:
        """So the rule cannot be satisfied by reporting everything.

        A module with its own `definitions`, bound to nothing of ours, calls
        its own function and is not a caller of this one. Matching the bare
        literal reported it.
        """
        callers = _definition_callers(
            {"elsewhere.py": "import catalogue\n\ndef f(db):\n    return catalogue.definitions(db)\n"}
        )

        assert callers == [], callers


def _line_of_the_listable_call() -> int:
    """Where `fields.py` calls `custom_fields.definitions`, found rather than
    written down.

    A literal line number in an assertion is a guard that reds on an unrelated
    edit and teaches the next person to edit the guard.
    """
    sites = _definition_callers({"fields.py": _source_modules()["fields.py"]})
    assert len(sites) == 1, sites
    return int(sites[0].split(":")[1])


class TestOnlyFieldIdsCrossOutOfTheValueTable:
    """What makes the unscoped arm safe is the bound, so the bound is asserted.

    `Fields._carried_by_any_book` reads `custom_field_values` with no viewer.
    Its own docstring says what crosses is a set of field ids, never a count
    and never a value, which is the same bound
    `shelf.collections_any_book_is_filed_in` states. A sentence is the rung
    below a test, and this is the test.

    **It is not what holds the class, and `_named_attributes_of` says which
    spelling walks past it.** What holds the class is the per module statement
    count in `BOOK_OWNED_READERS`: any read that names a column this walk
    cannot see is still a statement, and a statement here is either one of the
    three classified keys or a red.
    """

    def test_the_module_names_two_columns_and_these_are_they(self) -> None:
        named = _named_attributes_of(_source_modules()["fields.py"], "CustomFieldValue")

        assert named == ["book_id", "field_id"], (
            "`fields.py` names a column of `custom_field_values` other than the "
            f"two it is allowed to: {named}. `book_id` is the join onclause and "
            "`field_id` is the answer. Naming `value` would carry a member's "
            "text out of a read that applies no viewer, and a count of rows "
            "would publish how many books hold a field, which "
            "`list_custom_fields` refuses to publish for the reason recorded "
            "in `docs/security.md`."
        )

    def test_a_third_column_is_reported(self) -> None:
        """The plant. `== [two names]` passes just as well over a walk that
        found nothing, or over a module that stopped naming the entity."""
        planted = _named_attributes_of(
            "x = db.query(CustomFieldValue.field_id, CustomFieldValue.value).all()\n",
            "CustomFieldValue",
        )

        assert planted == ["field_id", "value"], planted

    # **There was a third arm here and it was deleted rather than fixed.** It
    # asserted `func` is not among this module's imports, under a docstring
    # claiming the module cannot publish a ready made number.
    #
    # Three things were wrong with it. It was the only assertion in this file
    # with no plant, and an absence assertion with no plant is evidence about
    # the search. One token defeated it, since the comprehension read the
    # bound name and an alias, a package import or the method form all clear
    # it. And the class it was credited with is held by something else:
    # turning the unscoped read into a count changes the statement, and
    # `BOOK_OWNED_READERS` is keyed on the whole flattened statement, so it
    # reds by name. Verified by plant on 2026-10-01, substituting
    # `func.count(CustomFieldValue.field_id)` into that read: three statements
    # against three entries, and the third key no longer matches its entry.
    #
    # So the line lives in that register and the arm that stood in front of it
    # is gone. What is genuinely open is the cardinality of a cached set,
    # which is how many definitions the viewer may be told about and is the
    # length of the list the route already returns.


# ── The three arms, as behaviour ──────────────────────────────────────────────


@pytest.fixture
def viewer(db) -> User:
    user = User(username="viewer", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def stranger(db) -> User:
    user = User(username="stranger", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def field(db) -> CustomField:
    row = custom_fields.define(db, "Bought from", CustomFieldKind.TEXT)
    db.commit()
    db.refresh(row)
    return row


def _book(db, owner: User, *, private: bool = False, trashed: bool = False) -> Book:
    row = Book(
        title="Solaris",
        added_by_user_id=owner.id,
        is_private=private,
        deleted_at=datetime.now(UTC).replace(tzinfo=None) if trashed else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _fill(db, book: Book, field: CustomField, value: str = "Oxfam") -> None:
    db.add(CustomFieldValue(book_id=book.id, field_id=field.id, value=value))
    db.commit()


class TestAFieldNoBookCarries:
    def test_it_is_listed_to_everybody(self, db, viewer, stranger, field) -> None:
        assert Fields.seen_by(db, viewer.id).listable() == [field]
        assert Fields.seen_by(db, stranger.id).listable() == [field]

    def test_its_author_can_still_name_it_by_id(self, db, viewer, field) -> None:
        """The arm the whole define flow rests on.

        Between defining a field and the first value there is no carrier, so
        without this arm a member defines a field and watches it fail to
        appear, and the write that would have filled it answers 404.
        """
        assert Fields.seen_by(db, viewer.id).addressable(field.id) is True


class TestAFieldOnABookTheViewerCanSee:
    def test_it_is_listed(self, db, viewer, stranger, field) -> None:
        _fill(db, _book(db, stranger), field)

        assert Fields.seen_by(db, viewer.id).listable() == [field]

    def test_a_private_book_lists_it_for_its_owner_alone(
        self, db, viewer, stranger, field
    ) -> None:
        _fill(db, _book(db, stranger, private=True), field)

        assert Fields.seen_by(db, stranger.id).listable() == [field]
        assert Fields.seen_by(db, viewer.id).listable() == []

    def test_the_hidden_one_is_not_addressable(self, db, viewer, stranger, field) -> None:
        _fill(db, _book(db, stranger, private=True), field)

        assert Fields.seen_by(db, viewer.id).addressable(field.id) is False

    def test_an_id_no_row_carries_is_addressable(self, db, viewer) -> None:
        """Arm 3 admits an id that is not a field at all, and the route is what
        turns that into a 404: `_custom_field` resolves the row first."""
        assert Fields.seen_by(db, viewer.id).addressable(999) is True


class TestAFieldOnABookInTheViewersTrash:
    def test_their_own_trashed_book_keeps_it_listed(self, db, viewer, field) -> None:
        """A restore reinstates the value, so trashing the last carrier must
        not take the field off the page of the member about to bring it back."""
        _fill(db, _book(db, viewer, trashed=True), field)

        assert Fields.seen_by(db, viewer.id).listable() == [field]

    def test_another_members_trashed_public_book_keeps_it_listed(
        self, db, viewer, stranger, field
    ) -> None:
        """`in_trash_for` is not an ownership test: a trashed public book is in
        everybody's trash listing, so its field name is already readable."""
        _fill(db, _book(db, stranger, trashed=True), field)

        assert Fields.seen_by(db, viewer.id).listable() == [field]

    def test_another_members_trashed_private_book_does_not(
        self, db, viewer, stranger, field
    ) -> None:
        _fill(db, _book(db, stranger, private=True, trashed=True), field)

        assert Fields.seen_by(db, viewer.id).listable() == []


class TestTheListIsNotMonotonic:
    def test_destroying_the_last_hidden_carrier_brings_the_field_back(
        self, db, viewer, stranger, field
    ) -> None:
        """The thing a reader will call a bug, pinned so it is a decision.

        The rule tracks what there is to disclose, so when the last value goes
        there is nothing left to withhold. The transition is observable and the
        module docstring says so rather than claiming a bound on it.
        """
        book = _book(db, stranger, private=True)
        _fill(db, book, field)
        assert Fields.seen_by(db, viewer.id).listable() == []

        db.query(CustomFieldValue).filter(CustomFieldValue.book_id == book.id).delete()
        db.commit()

        assert Fields.seen_by(db, viewer.id).listable() == [field]


class TestTheOrderIsTheOrderItWasDefinedIn:
    def test_the_filter_keeps_definition_order(self, db, viewer, field) -> None:
        second = custom_fields.define(db, "Shelf photo", CustomFieldKind.TEXT)
        db.commit()
        db.refresh(second)

        assert [row.id for row in Fields.seen_by(db, viewer.id).listable()] == [
            field.id,
            second.id,
        ]
