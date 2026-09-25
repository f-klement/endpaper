"""What decides a tag, and how many of them one Book may carry.

The route's own behaviour is pinned in `tests/routers/test_books_tags.py` and the
importer's in `tests/test_importing.py`, which is where a member meets either.
What is pinned here is the module's own rules, and one house rule:
`TestNothingElseDecidesATagFromAName` is what makes a third copy of the minting
rule fail rather than merely be a third copy.

**Two instruments read the same corpus** and they have different blind spots, so
a pass that quietly stops matching shows up as a disagreement rather than as a
smaller number nobody sees. `ast` resolves a name back to `models.Tag`, so it
follows an import alias and a rebinding; `tokenize` sees only the spelling
`Tag`, so it reads `models.Tag(...)` without being taught to and follows no
alias at all. Neither sees a construction assembled at runtime,
`getattr(models, "Tag")()` among them. That is described rather than bounded:
the arms below plant what they can reach and claim nothing about what they
cannot.
"""

import ast
import io
import logging
import tokenize
from pathlib import Path
from typing import Final, NamedTuple

import pytest

from models import Book, Tag
from tags import (
    MAX_NEW_TAGS_PER_IMPORT,
    MAX_TAGS_PER_BOOK,
    Mint,
    attach,
    folded,
    room_on,
    tidy,
)
from tests.test_house_rules import BACKEND, _every_module_but_the_tests, _source_modules
from tests.test_importing import selects


#: The modules that may decide a tag, and what each one is.
#:
#: **Two, and the second is not a mint.** `main.py` holds `seed_tags`, which
#: inserts the predefined vocabulary: it matches on the stored name rather than
#: on the folded one, so that a library which renamed a seeded tag keeps their
#: word, and it writes `key` and `is_predefined`, which nothing a member invents
#: ever carries. Putting it through the Mint would find the vocabulary short and
#: insert an English second copy beside their own name.
#:
#: **An exemption is a whole file**, so anything later added to `main.py`
#: inherits it. That is the cost of naming files rather than functions, and it
#: is stated rather than armed: the diagonal below can say an exemption is load
#: bearing and cannot say the file has not since grown a second reason.
class Exemption(NamedTuple):
    """Why a module may decide a tag, and whose evidence says it does.

    **`carried_by` is the note the diagonal checks**, so which instrument
    reports an exemption is data rather than a sentence beside the data. Both
    carry both today. An entry naming only the token pass is a module that
    should be skipped rather than exempted, and the arm below says so.
    """

    why: str
    carried_by: frozenset[str]


MINTERS: Final = {
    "tags.py": Exemption("the mint itself", frozenset({"tree", "token"})),
    "main.py": Exemption(
        "seed_tags, which matches on the stored name and writes the key",
        frozenset({"tree", "token"}),
    ),
}

#: A `models.py` for a planted corpus, carrying the property that makes the
#: class the mapped row rather than the spelling of its base.
MODELS: Final = 'class Tag(Base):\n    __tablename__ = "tags"\n'

#: The two statement forms where a bare name is followed by `(` and is not a
#: call. `class Tag(Base)` in `models.py` is the live one; a `def` of that name
#: is the same shape and costs nothing to exclude.
_DEFINES: Final = frozenset({"class", "def"})


def _declares_the_model(tree: ast.Module) -> bool:
    """Whether this module declares the mapped `Tag` rather than importing it.

    `models.py` binds the name by declaring it, so without this the one module
    that can construct a Tag under its own name is the one module neither
    instrument watches.

    **The property is the table it is mapped to**, read off `__tablename__` in
    the class body. Reading the base instead was a class name match wearing the
    word "property", and it cost both directions: renaming how `models.py`
    spells its declarative base would have left that module declaring no model,
    dropped it into the skip below as a module that merely defines a class
    called `Tag`, and blinded **both** instruments on the one file that can
    construct one under its own name. Measured: a `Tag.of()` classmethod minting
    by exact name, with no fold, no normaliser and no ceiling, went green under
    that version with every planted shape still passing. Two tokens of data in
    another file disarmed the guard.

    It cost a refusal as well. This repository reads MARC, SRU and Z39.50, where
    a field label is called a tag, so a `class Tag(Base)` for a field label is
    ordinary work, and against the base match both instruments refused it.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Tag":
            continue
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                bound: list[ast.expr] = list(statement.targets)
            elif isinstance(statement, ast.AnnAssign):
                bound = [statement.target]
            else:
                continue
            if not any(isinstance(target, ast.Name) and target.id == "__tablename__" for target in bound):
                continue
            if isinstance(statement.value, ast.Constant) and statement.value.value == "tags":
                return True
    return False


def _means_tag(node: ast.expr, names: set[str], modules: set[str]) -> bool:
    return (isinstance(node, ast.Name) and node.id in names) or _is_attribute(node, modules)


def _is_attribute(node: ast.expr, modules: set[str]) -> bool:
    """`models.Tag`, where `models` is a name this module imported as the module.

    **The receiver has to be a module name this file imported**, which is what
    is stated rather than armed. `package.models.Tag(...)` is an `Attribute` on
    an `Attribute`, and a class attribute holding the model, `Holder.Tag(...)`,
    is an `Attribute` on a class name; neither is seen. Nothing in this tree
    reaches the model either way, and a rule that walked an arbitrary dotted
    path or followed a class body would be matching a spelling rather than a
    binding.
    """
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "Tag"
        and isinstance(node.value, ast.Name)
        and node.value.id in modules
    )


def _synthesises_tag(node: ast.expr, names: set[str], modules: set[str]) -> bool:
    """`type("Row", (Tag,), {})`: a class statement written as a call.

    The same defect as the `class` form and reachable without one, which is why
    it is here rather than in a sentence saying a subclass is covered.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return False
    if node.func.id != "type" or len(node.args) != 3:
        return False
    bases = node.args[1]
    return isinstance(bases, ast.Tuple | ast.List) and any(
        _means_tag(base, names, modules) for base in bases.elts
    )


def _bindings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The local names meaning the mapped `Tag`, and those meaning `models`.

    Resolved from what the module **binds**, never from the spelling `Tag`: a
    module writing `from models import Tag as Row` is the case a matcher looking
    for one spelling never looks for.

    Five ways a name comes to mean the model, each a property of a binding:

    * `from models import Tag [as X]`, and `from models import *`, which binds
      whatever `models` exports and therefore binds this;
    * `import models [as alias]`, for the attribute form;
    * declaring it, which is `models.py`;
    * `X = Tag` and `X = models.Tag`;
    * `class X(Tag)`, and `X = type("X", (Tag,), {})`, which is the same
      statement written as a call. **A subclass writes real rows**: measured in
      process against sqlite, two instances of one wrote `Ästhetik` and
      `ästhetik` as rows 1 and 2 of `tags`, which is the pair this module exists
      to prevent.

    Resolved to a fixed point, so a subclass of a subclass is one too.

    Following any assignment that merely mentions `Tag` is what
    `tests/test_shelf.py::_entity_aliases` measured as five false positives on
    this tree, because `tag = mint.get_or_mint(...)` would make `tag` an alias.

    **Names are resolved for the module, with no regard for scope.** A name
    bound to the model inside one function means the model everywhere in the
    file, so this errs toward reporting, which is the right direction for a rule
    whose failure is a silent second minting site.
    """
    names: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            names |= {alias.asname or alias.name for alias in node.names if alias.name == "Tag"}
            if any(alias.name == "*" for alias in node.names):
                names.add("Tag")
        elif isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == "models"}
    if _declares_the_model(tree):
        names.add("Tag")

    # To a fixed point and in no particular file order, because an alias may be
    # bound above or below the import, and a subclass above or below its base.
    growing = True
    while growing:
        growing = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name in names:
                    continue
                if any(_means_tag(base, names, modules) for base in node.bases):
                    names.add(node.name)
                    growing = True
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
                if not isinstance(target, ast.Name) or target.id in names:
                    continue
                if _means_tag(value, names, modules) or _synthesises_tag(value, names, modules):
                    names.add(target.id)
                    growing = True
    return names, modules


def _binds_tag_to_something_else(tree: ast.Module, own_modules: frozenset[str]) -> bool:
    """Whether this module's `Tag` is some other tag entirely.

    **This repository reads MARC, SRU and Z39.50, where a field label is called
    a tag**, so the bare spelling is ordinary work here and modules in this
    corpus already carry it. A `class Tag(str)` for a field label, or
    `from pymarc import Tag`, is not a minting site and the token pass cannot
    tell by looking at the token.

    **How many carry it is deliberately not written here, in a figure or in a
    word.** It was, as a word, and the word stood in for a count it overstated:
    the two obvious ways to count disagree by most of the answer, because one
    reads comments and strings and the other reads names the tokeniser sees. A
    word is not safer than a number when it is encoding one.

    **Nothing binds it that way today**, so this skip is latent and is driven by
    the planted shapes rather than by the tree. It is here because the shape is
    one line of ordinary work away, and because of what the repair costs:
    `MINTERS` would have to grow an entry, and an exemption resting on this
    instrument alone is refused by the diagonal, which says to come here instead.

    **A skip has to fail closed, and the first version of this failed open.**
    Every question below asks whether the name is bound to *something that is
    not the model*, so anything this cannot recognise must answer no:

    * an import is proof only when the module is neither relative nor a spelling
      of one of this corpus's own modules, so `from backend.models import Tag`
      and `from .models import Tag` are not proof. Testing `!= "models"` made
      every other spelling of the same module proof that it was a different one;
    * an assignment is proof only when its value is a **name or an attribute**
      that this file does not resolve to the model. Testing `_is_attribute`
      alone made `Tag = <an alias resolved two lines up>` proof, so the gate
      contradicted the function it had just called; accepting any value the tree
      could not evaluate made `Tag = getattr(models, "Tag")` proof, which is a
      rebinding of the model itself. An expression this cannot read is not
      evidence about what it means.

    **One shape passes, and it is a miss rather than a decision**: a hop through
    a module **outside** this corpus that re-exports the model. Closing it means
    refusing every third party import of the name, which is the false refusal
    this skip exists to remove, and the shape barely exists: reaching this
    model requires importing `models`, which is this corpus, so the live hop is
    through one of our own modules and that one is seen. The battery records
    both halves.
    """
    if _declares_the_model(tree):
        return False
    names, modules = _bindings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name == "Tag":
                return True
        elif isinstance(node, ast.ImportFrom):
            if "Tag" not in {alias.asname or alias.name for alias in node.names}:
                continue
            if node.level:
                continue
            if (node.module or "").rsplit(".", 1)[-1] in own_modules:
                continue
            return True
        elif isinstance(node, ast.Import):
            if "Tag" in {alias.asname or alias.name for alias in node.names}:
                return True
        elif (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "Tag" for target in node.targets)
            and isinstance(node.value, ast.Name | ast.Attribute)
            and not _means_tag(node.value, names, modules)
        ):
            return True
    return False


def constructions_by_ast(sources: dict[str, str]) -> list[str]:
    """Every `Tag(...)` in the corpus, with the callee resolved."""
    found: list[str] = []
    for path, source in sorted(sources.items()):
        tree = ast.parse(source)
        names, modules = _bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _means_tag(node.func, names, modules):
                found.append(f"{path}:{node.lineno}")
    return found


def constructions_by_token(sources: dict[str, str]) -> list[str]:
    """Every `Tag (` pair in the corpus, read as tokens rather than as a tree.

    The second instrument. A comment and a string are their own token kinds, so
    prose naming the constructor is not a match and nothing has to be stripped
    for it. What this cannot do is follow a name, which is the half `ast` has.

    The skip above is decided from the tree, which is the other instrument's
    reading. That is a gate on the population and not the match: what this pass
    answers for a module it reads is still read off the tokens alone.

    Which module names are this corpus's own is derived from the corpus it was
    handed, so a spelling of one of them is recognised without a list of them
    being written anywhere.
    """
    own_modules = frozenset(Path(path).stem for path in sources)
    found: list[str] = []
    for path, source in sorted(sources.items()):
        if _binds_tag_to_something_else(ast.parse(source), own_modules):
            continue
        tokens = [
            token
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type
            not in {
                tokenize.COMMENT,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
            }
        ]
        for index, token in enumerate(tokens):
            if token.type != tokenize.NAME or token.string != "Tag":
                continue
            after = tokens[index + 1] if index + 1 < len(tokens) else None
            if after is None or after.type != tokenize.OP or after.string != "(":
                continue
            if index and tokens[index - 1].string in _DEFINES:
                continue
            found.append(f"{path}:{token.start[0]}")
    return found


def outside(found: list[str], allowed) -> list[str]:
    """The sites in files no exemption covers."""
    return [site for site in found if site.rsplit(":", 1)[0] not in allowed]


def _corpus(module: str, source: str) -> dict[str, str]:
    """The planted module, with a `models.py` beside it unless it is the plant.

    A module name is resolved against the corpus's **own** module names, so a
    plant standing alone is a corpus this repository never has and would answer
    differently from the tree for reasons that are the fixture's rather than the
    rule's.
    """
    if module == "models":
        return {"models.py": source}
    return {"models.py": MODELS, f"{module}.py": source}


#: Every shape either instrument has been asked about, and what each answers.
#:
#: Read as four groups: what the first version of this guard caught and this one
#: must still catch, what it wrongly refused and this one must leave alone, the
#: subclass family, and the misses, which are rows expecting nothing from both.
#:
#: A row is `(module, source, lines the tree pass reports, lines the token pass
#: reports)`. The line numbers are the point: a pass that starts reporting the
#: class statement, or stops reporting the call, is a different answer rather
#: than a smaller list.
BATTERY: Final = [
    # ── What the tree pass resolves ──────────────────────────────────────────
    ("elsewhere", "from models import Tag\nrow = Tag(name='x')\n", [2], [2]),
    ("elsewhere", "from models import Tag as Row\nrow = Row(name='x')\n", [2], []),
    ("elsewhere", "import models\nrow = models.Tag(name='x')\n", [2], [2]),
    ("elsewhere", "import models as orm\nrow = orm.Tag(name='x')\n", [2], [2]),
    ("elsewhere", "from models import Tag\nRow = Tag\nrow = Row(name='x')\n", [3], []),
    ("elsewhere", "import models\nRow = models.Tag\nrow = Row(name='x')\n", [3], []),
    # ── What only the token pass reaches ─────────────────────────────────────
    ("elsewhere", "row = Tag(name='x')\n", [], [1]),
    (
        "elsewhere",
        "from models import Tag as Row\n\n\nclass Holder:\n    Tag = Row\n\n\nrow = Holder.Tag(name='x')\n",
        [],
        [8],
    ),
    ("elsewhere", "from backend.models import Tag\nrow = Tag(name='x')\n", [], [2]),
    ("elsewhere", "from .models import Tag\nrow = Tag(name='x')\n", [2], [2]),
    ("elsewhere", "from . import models\nrow = models.Tag(name='x')\n", [], [2]),
    # ── Recorded misses ──────────────────────────────────────────────────────
    (
        "elsewhere",
        "import models\nTag = getattr(models, 'Tag')\nrow = Tag(name='x')\n",
        [],
        [3],
    ),
    (
        "elsewhere",
        "from models import Tag\ndb.bulk_insert_mappings(Tag, [{'name': raw}])\n",
        [],
        [],
    ),
    (
        "elsewhere",
        "from models import Tag\ndb.execute(Tag.__table__.insert(), rows)\n",
        [],
        [],
    ),
    # ── A field label this repository calls a tag, which neither may report ──
    ("marc_fields", "class Tag(str):\n    pass\n\n\nfield = Tag('245')\n", [], []),
    ("marc_fields", "from pymarc import Tag\nfield = Tag('245')\n", [], []),
    (
        "marc_fields",
        "from typing import NamedTuple\n\n\nclass Tag(NamedTuple):\n    value: str\n\n\nfield = Tag('245')\n",
        [],
        [],
    ),
    (
        "marc_fields",
        "from database import Base\n\n\nclass Tag(Base):\n    pass\n\n\nfield = Tag('245')\n",
        [],
        [],
    ),
    ("marc_fields", "def Tag(value):\n    return value\n\n\nfield = Tag('245')\n", [], []),
    ("marc_fields", "Tag = str\nfield = Tag('245')\n", [], []),
    # ── The subclass family ──────────────────────────────────────────────────
    (
        "elsewhere",
        "from models import Tag\n\n\nclass Shelfmark(Tag):\n    pass\n\n\nrow = Shelfmark(name='x')\n",
        [8],
        [],
    ),
    (
        "elsewhere",
        "import models\n\n\nclass Shelfmark(models.Tag):\n    pass\n\n\nrow = Shelfmark(name='x')\n",
        [8],
        [],
    ),
    (
        "elsewhere",
        "from models import Tag\n\n\nclass A(Tag):\n    pass\n\n\nclass B(A):\n"
        "    pass\n\n\nrow = B(name='x')\n",
        [12],
        [],
    ),
    (
        "elsewhere",
        "from models import Tag\nRow = type(\"Row\", (Tag,), {})\nrow = Row(name='x')\n",
        [3],
        [],
    ),
    ("elsewhere", "from models import *\nrow = Tag(name='x')\n", [2], [2]),
    ("elsewhere", "from models import *\nRow = Tag\nrow = Row(name='x')\n", [3], []),
    (
        "elsewhere",
        "from models import Tag as Row\n\nif legacy:\n    Mark = str\nelse:\n"
        "    Mark = Row\n\nrow = Mark(name='x')\n",
        [8],
        [],
    ),
    # ── The module that declares the mapped class ────────────────────────────
    ("models", MODELS + "\n\nrow = Tag(name='x')\n", [5], [5]),
    (
        "models",
        "class Tag(Registry):\n    __tablename__ = \"tags\"\n\n\nrow = Tag(name='x')\n",
        [5],
        [5],
    ),
]

#: One id per row, prefixed with what the row is: a minting site both
#: instruments must between them catch, a minting site neither catches and this
#: records, or ordinary work neither may report. **The prefix is data rather
#: than a sentence**, so a reader comparing this rule against an earlier version
#: of itself can classify a row without deciding what it is first.
BATTERY_IDS: Final = [
    "mint: plain import",
    "mint: import alias",
    "mint: the attribute form",
    "mint: a module alias",
    "mint: a rebinding",
    "mint: a rebinding of the attribute form",
    "mint: a name this module never binds",
    "mint: a class attribute holding the model",
    "mint: another spelling of the same module",
    "mint: a relative import of the same module",
    "mint: a relative import of the module itself",
    "mint: a rebinding the tree cannot evaluate",
    "miss: a write through bulk_insert_mappings",
    "miss: a write through the table's own insert",
    "innocent: a field label of this repository's own",
    "innocent: a field label from a library",
    "innocent: a field label as a tuple",
    "innocent: a field label on a declarative base",
    "innocent: a factory of that name",
    "innocent: a field label aliased to another type",
    "mint: a subclass",
    "mint: a subclass of the attribute form",
    "mint: a subclass of a subclass",
    "mint: a class statement written as a call",
    "mint: a star import",
    "mint: a star import then a rebinding",
    "mint: a conditional rebinding, field label branch first",
    "mint: the module that declares the model",
    "mint: the module that declares it, base renamed",
]


class TestNothingElseDecidesATagFromAName:
    """A third copy of the minting rule fails rather than merely existing.

    There were two, `routers/books.create_tag` and `importing._apply_tags`, each
    folding in Python on both sides for the same measured reason and each
    docstring pointing at the other saying so. They had already disagreed about
    which of a case differing pair wins while both claimed to agree, and nothing
    counted the sites, so a third copy was free to write.

    **Deciding a tag, not writing the table.** Neither instrument sees a write
    that constructs nothing, and that is the subject rather than an omission
    either could close: `bulk_insert_mappings(Tag, ...)` and
    `db.execute(Tag.__table__.insert(), ...)` each name a tag into this table
    without calling the model, and the battery records both. The one live write
    of that shape decides nothing it writes: `backup.restore` reinserts an
    archive's own rows, which makes it a deliberate non minter like the seeder
    and not an instance of the family.

    **The author of a guard is the worst seat to choose its evasions**, so the
    shapes below are a mixture: the ones its author planted, and the ones a
    non author found afterwards, which include the subclass family and the
    reason the token pass skips a module rather than exempting it.
    """

    def test_no_module_but_the_mint_and_the_seed_decides_a_tag(self) -> None:
        offenders = outside(constructions_by_ast(_source_modules()), MINTERS)

        assert not offenders, (
            "these construct a Tag outside the mint, so the fold, the ordering and "
            f"the caps are decided again wherever they are: {offenders}"
        )

    def test_the_second_instrument_agrees_on_the_tree(self) -> None:
        """Two readings that degrade differently, so a matcher that stopped
        matching is a disagreement rather than a clean run."""
        assert not outside(constructions_by_token(_source_modules()), MINTERS)

    def test_the_corpus_is_every_backend_module_but_the_generated_revisions(
        self,
    ) -> None:
        """A round floor is one a collapsed walk steps over: this corpus holds
        ninety five modules and an assertion of fifty would pass with forty five
        of them missing. So it is compared against a second shared walk, which
        differs from it by the generated revisions and by nothing else.

        **The two share `_is_vendored`**, so a change there moves both and the
        equality holds while the corpus shrinks. What this catches is one walk
        drifting from the other, which is what happened to the three test
        modules that each kept a copy of one."""
        corpus = set(_source_modules())
        wider = {str(path.relative_to(BACKEND)) for path in _every_module_but_the_tests()}

        assert corpus == {path for path in wider if "migrations" not in Path(path).parts}
        assert {"tags.py", "main.py", "importing.py", "routers/books.py"} <= corpus

    @pytest.mark.parametrize("exempt", sorted(MINTERS))
    def test_each_exemption_is_load_bearing_under_the_instruments_it_names(self, exempt: str) -> None:
        """The diagonal: drop one name, and exactly that file is reported, by
        exactly the instruments the entry says carry it.

        **Per instrument rather than unioned, and that is the interlock.** This
        is the only arm that checks against the **real tree** that a pass is
        still matching at all: the battery below covers a pass broken by an edit
        to its own code and cannot cover one gone blind because the tree moved,
        which is exactly how the base spelling defect would have landed. A union
        hides that, because either instrument alone satisfies it.
        """
        narrowed = {path: entry for path, entry in MINTERS.items() if path != exempt}
        corpus = _source_modules()

        reporting = set()
        for instrument, found in (
            ("tree", constructions_by_ast(corpus)),
            ("token", constructions_by_token(corpus)),
        ):
            reported = {site.rsplit(":", 1)[0] for site in outside(found, narrowed)}
            assert reported <= {exempt}, f"dropping {exempt} made the {instrument} pass report {reported}"
            if reported:
                reporting.add(instrument)

        assert reporting == MINTERS[exempt].carried_by

    @pytest.mark.parametrize("exempt", sorted(MINTERS))
    def test_every_exemption_is_carried_by_the_tree_pass(self, exempt: str) -> None:
        """An exemption resting on the token pass alone is the wrong repair.

        That is a module whose `Tag` is some other tag, and the answer is
        `_binds_tag_to_something_else`, which skips it by what it binds. Writing
        it here instead exempts every construction in that file from the pass
        that can actually resolve one. This arm is what sends the next reader to
        the skip rather than to the exemption list.
        """
        assert "tree" in MINTERS[exempt].carried_by

    @pytest.mark.parametrize(("module", "source", "tree", "token"), BATTERY, ids=BATTERY_IDS)
    def test_the_battery_answers_as_recorded(
        self, module: str, source: str, tree: list[int], token: list[int]
    ) -> None:
        """Every shape either instrument has ever been asked about, and what each
        one answers now.

        **A row expecting nothing from both is a recorded miss, not an
        approval.** Closing one is an edit here, and a shape that starts being
        caught goes red rather than passing quietly, which is the only way a
        blind spot stays a known one.

        Selecting on `battery` runs the whole table, which is what to do when
        either pass is changed.
        """
        planted = _corpus(module, source)
        here = f"{module}.py:"

        assert [site for site in constructions_by_ast(planted) if site.startswith(here)] == [
            f"{here}{line}" for line in tree
        ]
        assert [site for site in constructions_by_token(planted) if site.startswith(here)] == [
            f"{here}{line}" for line in token
        ]

    def test_a_re_export_through_a_module_of_this_corpus_is_still_seen(self) -> None:
        """The hop the gate was accused of losing, measured in both directions.

        A module of this corpus re-exporting the model is a spelling of one of
        our own, so the token pass reads it. The tree pass does not: it resolves
        `from models import Tag` and nothing further, which is why this is one
        instrument's catch rather than two.
        """
        hop = {
            "models.py": MODELS,
            "reexport.py": 'from models import Tag\n\n__all__ = ["Tag"]\n',
            "elsewhere.py": "from reexport import Tag\nrow = Tag(name='x')\n",
        }

        assert constructions_by_ast(hop) == []
        assert constructions_by_token(hop) == ["elsewhere.py:2"]

    def test_a_re_export_through_a_module_outside_this_corpus_is_not(self) -> None:
        """The other half, and a **recorded miss**. A third party module
        re-exporting the model is indistinguishable, from the importing file
        alone, from a third party module exporting some other tag, and the
        second is the live case here. Closing it means reading a module this
        corpus does not contain."""
        outside_hop = {
            "models.py": MODELS,
            "elsewhere.py": "from vendor.shim import Tag\nrow = Tag(name='x')\n",
        }

        assert constructions_by_ast(outside_hop) == []
        assert constructions_by_token(outside_hop) == []


class TestFoldingAName:
    def test_two_spellings_of_one_name_share_a_key(self) -> None:
        assert folded("Cookbooks") == folded("cookbooks")

    def test_a_non_ascii_capital_folds(self) -> None:
        """The whole reason the fold is Python's: SQLite's `lower()` leaves this
        one unchanged, so a comparison across the two never matched."""
        assert folded("Ästhetik") == "ästhetik"

    def test_the_fold_is_lower_and_not_casefold(self) -> None:
        """Widening it would merge rows a library already holds apart, which is a
        migration rather than an edit."""
        assert folded("Straße") != folded("STRASSE")


class TestTidyingAName:
    def test_whitespace_collapses(self) -> None:
        assert tidy("  Holiday   reads  ") == "Holiday reads"

    def test_a_control_character_is_removed(self) -> None:
        """`Fiction` with a NUL on the end is a second row a member reads as the
        first, and `str.strip` does not remove one, so the parser passed it on."""
        assert tidy("Fiction\x00") == "Fiction"

    def test_a_name_that_normalises_to_nothing_is_none(self) -> None:
        assert tidy("  \x00 ") is None

    def test_a_character_with_no_width_survives(self) -> None:
        """The normaliser removes the control characters that are not whitespace
        and no more. A joiner is a letter of somebody's name in Arabic and Indic
        scripts, so widening this is `schemas/common`'s decision and not a tag's."""
        zero_width = chr(0x200B)

        assert tidy(f"Fiction{zero_width}") == f"Fiction{zero_width}"

    def test_a_long_name_is_cut_to_the_column(self) -> None:
        assert tidy("x" * 500) == "x" * 100

    def test_the_cut_leaves_no_trailing_space(self) -> None:
        """The normaliser trims the ends and the cut can put a space back."""
        assert tidy("x" * 99 + " yz") == "x" * 99

    def test_normalising_comes_before_the_cut(self) -> None:
        """Cutting first would take a hundred characters of padding and hand back
        one word."""
        assert tidy("  " + "x" * 100 + "  ") == "x" * 100


@pytest.fixture
def book(db):
    row = Book(title="Piranesi")
    db.add(row)
    db.commit()
    return row


class TestMintingOne:
    def test_a_new_name_becomes_a_row(self, db) -> None:
        tag = Mint(db).get_or_mint("Holiday reads")

        assert tag is not None
        assert (tag.name, tag.category, tag.is_predefined) == (
            "Holiday reads",
            "custom",
            False,
        )

    def test_a_name_already_taken_gives_back_that_row(self, db) -> None:
        first = Mint(db).get_or_mint("Cookbooks")
        db.commit()

        assert Mint(db).get_or_mint("cookbooks") is first

    def test_a_seeded_tag_is_not_shadowed(self, db) -> None:
        """The vocabulary is matched the same way anything else is, so inventing
        `fantasy` finds `Fantasy` rather than minting beside it."""
        tag = Mint(db).get_or_mint("fantasy")

        assert tag is not None
        assert tag.is_predefined
        assert db.query(Tag).filter(Tag.name.ilike("fantasy")).count() == 1

    def test_a_non_ascii_capital_finds_the_row_it_already_has(self, db) -> None:
        """The fold that answered 500 on the route and lost the whole file on an
        import: SQLite's `lower()` never matched this one."""
        first = Mint(db).get_or_mint("Ästhetik")
        db.commit()

        assert Mint(db).get_or_mint("ästhetik") is first
        assert db.query(Tag).filter(Tag.name.in_(["Ästhetik", "ästhetik"])).count() == 1

    def test_a_name_that_normalises_to_nothing_mints_nothing(self, db) -> None:
        before = db.query(Tag).count()

        assert Mint(db).get_or_mint("  \x00 ") is None
        assert db.query(Tag).count() == before

    def test_an_import_and_a_route_normalise_the_same_way(self, db) -> None:
        """The asymmetry this module removes: one writer ran the normaliser and
        the other truncated with none, so an import could mint a name the route
        would have refused."""
        tag = Mint(db).get_or_mint("Fiction\x00")

        assert tag is not None
        assert tag.name == "Fiction"
        assert tag.is_predefined

    def test_it_does_not_commit(self, db) -> None:
        """The one thing about this module's shape that cannot move: an import
        commits once at the end of the file, so a commit here is a half applied
        import with no way back."""
        Mint(db).get_or_mint("Holiday reads")
        db.rollback()

        assert db.query(Tag).filter(Tag.name == "Holiday reads").count() == 0

    def test_the_row_is_flushed_so_it_carries_an_id(self, db) -> None:
        """`attach` deduplicates on the id, and two rows with none compare equal."""
        tag = Mint(db).get_or_mint("Holiday reads")

        assert tag is not None
        assert tag.id is not None

    def test_the_table_is_read_once_however_many_names_are_asked(self, db) -> None:
        """The lookup this replaced was one query per unseen name, which is five
        hundred for a five hundred row export sharing a handful of tags."""
        mint = Mint(db)

        issued = selects(lambda: [mint.get_or_mint(f"tag {n}") for n in range(5)])

        reads = [read for read in issued if "FROM tags" in read.replace("\n", " ")]

        assert len(reads) == 1
        assert mint.minted == 5

    def test_it_reads_nothing_until_it_is_asked(self, db) -> None:
        """What lets the importer build one whether or not tags are wanted."""
        mint = Mint(db)

        assert mint._index is None

    def test_a_budget_stops_it_inventing(self, db) -> None:
        mint = Mint(db, budget=2)

        minted = [mint.get_or_mint(f"tag {n}") for n in range(4)]

        assert [tag is not None for tag in minted] == [True, True, False, False]

    def test_a_spent_budget_still_answers_with_a_tag_the_library_has(self, db) -> None:
        """The cap stops inventing rather than failing: the Books in the file are
        still worth having, and so are the tags already there."""
        mint = Mint(db, budget=1)
        mint.get_or_mint("Holiday reads")

        assert mint.get_or_mint("Fantasy") is not None

    def test_the_import_budget_is_the_one_the_importer_passes(self, db) -> None:
        """A route holds a Mint for one request and passes no budget, so an
        import's history can never refuse a member typing a name."""
        assert Mint(db)._budget is None
        assert MAX_NEW_TAGS_PER_IMPORT == 200


class TestWhichOfACaseDifferingPairWins:
    """Two rows differing only in case are reachable on any database that met the
    fold defect, because the route that had it created exactly that pair: the
    lookup missed and the binary index allowed both.

    Measured on a pair at ids 106 and 107 before this module: the import resolved
    it to 107 and the route to 106, while both docstrings claimed the ordering
    was what made them agree.
    """

    @pytest.fixture
    def pair(self, db):
        lower = Tag(name="cookbooks", category="custom", is_predefined=False)
        upper = Tag(name="Cookbooks", category="custom", is_predefined=False)
        db.add_all([lower, upper])
        db.commit()
        return lower, upper

    def test_the_row_the_library_has_had_longest_wins(self, db, pair) -> None:
        lower, _upper = pair

        assert Mint(db).get_or_mint("COOKBOOKS") is lower

    def test_the_later_row_never_wins(self, db, pair) -> None:
        """Stability is not what decides it: a dict comprehension over the same
        ordering is equally stable and keeps the last key written."""
        _lower, upper = pair

        assert Mint(db).get_or_mint("Cookbooks") is not upper

    def test_neither_of_the_pair_is_minted_over(self, db, pair) -> None:
        before = db.query(Tag).count()
        Mint(db).get_or_mint("CookBooks")
        db.commit()

        assert db.query(Tag).count() == before


class TestTheCeilingOnABook:
    """`MAX_TAGS_PER_BOOK` bound exactly one writer while it lived in the CSV
    parser, so the 4000 tags on one Book that the measured failure produced
    stayed reachable through `POST /api/books/{book_id}/tags/{tag_id}`, one
    request at a time. `attach` is what makes it true of whoever writes.
    """

    def _fill(self, db, book, how_many: int) -> None:
        for index in range(how_many):
            row = Tag(name=f"filler {index}", category="custom", is_predefined=False)
            db.add(row)
            book.tags.append(row)
        db.commit()

    def test_a_book_with_room_takes_the_tag(self, db, book) -> None:
        tag = Mint(db).get_or_mint("Holiday reads")

        assert tag is not None
        assert attach(book, tag) is True
        db.commit()

        assert [carried.name for carried in book.tags] == ["Holiday reads"]

    def test_a_full_book_takes_no_more(self, db, book) -> None:
        self._fill(db, book, MAX_TAGS_PER_BOOK)
        tag = Mint(db).get_or_mint("Holiday reads")
        assert tag is not None

        assert attach(book, tag) is False
        db.commit()

        assert len(book.tags) == MAX_TAGS_PER_BOOK

    def test_a_book_one_short_still_takes_one(self, db, book) -> None:
        """The diagonal, so the arm above is not passing on an off by one that
        refuses every Book."""
        self._fill(db, book, MAX_TAGS_PER_BOOK - 1)
        tag = Mint(db).get_or_mint("Holiday reads")
        assert tag is not None

        assert attach(book, tag) is True
        db.commit()

        assert len(book.tags) == MAX_TAGS_PER_BOOK

    def test_a_tag_the_book_already_carries_is_not_added_twice(self, db, book) -> None:
        tag = Mint(db).get_or_mint("Holiday reads")
        assert tag is not None
        attach(book, tag)
        db.commit()

        assert attach(book, tag) is True
        db.commit()

        assert len(book.tags) == 1

    def test_a_full_book_still_answers_yes_for_a_tag_it_has(self, db, book) -> None:
        """What lets a caller walking a file's tag column read False as "this
        Book is full" and stop, rather than stopping on a repeat."""
        self._fill(db, book, MAX_TAGS_PER_BOOK)

        assert attach(book, book.tags[0]) is True

    def test_the_drop_is_logged(self, db, book, caplog) -> None:
        """A dropped name came out of a member's own file and nothing regenerates
        it, so a silent drop is a loss with nowhere to read it off."""
        self._fill(db, book, MAX_TAGS_PER_BOOK)
        tag = Mint(db).get_or_mint("Holiday reads")
        assert tag is not None

        with caplog.at_level(logging.INFO, logger="endpaper.tags"):
            attach(book, tag)

        assert "Holiday reads" in caplog.text

    def test_room_is_asked_before_a_name_is_minted(self, db, book) -> None:
        """The check the importer makes before `attach` makes it again: without
        it a Book at its ceiling spends the import's budget on names it is then
        refused, and a later Book in the same file loses tags to it."""
        self._fill(db, book, MAX_TAGS_PER_BOOK)

        assert room_on(book) is False
