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

from models import Book, Tag, User
from tags import (
    MAX_NEW_TAGS_PER_IMPORT,
    MAX_TAGS_PER_BOOK,
    Mint,
    Naming,
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
#: **An exemption is one statement, not a whole file.** It was a filename, and
#: the cost was measured rather than argued: a second minting rule appended to
#: `tags.py` with no fold, no normaliser and no ceiling was **green**, because
#: the file it sat in was exempt. That is the same hole `TAG_READERS` had for
#: reads, closed the same way, and there is exactly one construction statement
#: in each of these files to key on.
class Exemption(NamedTuple):
    """Why a module may decide a tag, and whose evidence says it does.

    **`carried_by` is the note the diagonal checks**, so which instrument
    reports an exemption is data rather than a sentence beside the data. Both
    carry both today. An entry naming only the token pass is a module that
    should be skipped rather than exempted, and the arm below says so.
    """

    why: str
    carried_by: frozenset[str]
    #: The construction this covers, flattened, exactly as `_statement_at`
    #: prints it. A second construction in the same file is a second entry
    #: with its own reason, or it is reported.
    statement: str


MINTERS: Final = {
    "tags.py": Exemption(
        "the mint itself",
        frozenset({"tree", "token"}),
        "tag = Tag(name=name, category=TagCategory.CUSTOM, is_predefined=False)",
    ),
    "main.py": Exemption(
        "seed_tags, which matches on the stored name and writes the key",
        frozenset({"tree", "token"}),
        "db.add(Tag(key=key, name=name, category=category, is_predefined=True))",
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


def _containing_statement(source: str, line: int) -> str:
    """The **narrowest statement whose span covers** this line, flattened.

    **A local helper and not `_statement_at`, which the read rule's keys
    depend on.** That one returns the widest statement *beginning* at a line,
    which is the right unit there because the read rule reports statements.
    This rule reports the **call**, and a call's line is the statement's only
    while nobody wraps it. Measured: wrapping the seeder's `db.add(...)` over
    three lines, a pure whitespace change of the shape a formatter makes when
    a line grows, left the lookup empty and the guard accusing the seeder of
    being a second mint, with the other file's diagonal failing as collateral
    so the message pointed at the wrong file.

    Narrowest rather than widest, because the enclosing `for` and `if` also
    cover the line and neither is the construction.

    Two more shapes take the same route and are unmeasured: a call inside any
    wrapped expression, and a compound statement written on one line, where
    the statement beginning there is the `with` or the `if`.
    """
    best: ast.stmt | None = None
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.stmt):
            continue
        if node.lineno <= line <= (node.end_lineno or node.lineno):
            span = (node.end_lineno or node.lineno) - node.lineno
            if best is None or span < (best.end_lineno or best.lineno) - best.lineno:
                best = node
    if best is None:
        return ""
    return " ".join((ast.get_source_segment(source, best) or "").split())


def outside(found: list[str], allowed) -> list[str]:
    """The sites in files no exemption covers.

    One of the three failures this rule has, and the only one the diagonals
    below are about. `inside_but_unexempted` holds the other two.
    """
    return [site for site in found if site.rsplit(":", 1)[0] not in allowed]


def inside_but_unexempted(found: list[str], allowed, sources: dict[str, str]) -> list[str]:
    """What an exempt file is doing that its one exemption does not cover.

    **Two failures, reported apart, the way the read report already separates
    them.** An exempt file holding **more** constructions than its exemption
    covers has grown a second mint, which is the hole that made keying on the
    filename wrong: a second rule written beside the first inherited the
    first's reason and was measured green. An exempt file holding **one** that
    is not the statement named has had that statement moved or reformatted,
    which decides nothing a second time.

    Folded into one message, a wrapped `db.add(...)` in the seeder read as
    "the seeder constructs a tag outside the mint": false, and pointing a
    reader at the wrong question in the wrong file.
    """
    report = []
    for path, entry in sorted(allowed.items()):
        sites = [site for site in found if site.rsplit(":", 1)[0] == path]
        if not sites:
            # **Its own branch, because the equality conflated it with a second
            # mint and then accused the file of one.** Planted the battery's
            # documented rebinding blind spot: the tree pass said the statement
            # moved, correctly, and the token pass said this file holds a
            # second rule deciding the fold again and printed an empty list of
            # offenders, the emptiness being the only tell that no such rule
            # exists. Nothing said the two instruments had disagreed.
            report.append(
                f"{path} holds no construction at all and its exemption covers "
                f"one, which is {entry.why}. **Nothing here is a second mint.** "
                "Either that construction is gone and the exemption is stale, "
                "or this instrument cannot see it: the token pass reads the "
                "spelling `Tag(` and a rebinding such as `_Row = Tag` hides it "
                "while the tree pass resolves it. If the other instrument "
                "reports this file and this one does not, that is the "
                "disagreement the two are bought for, and "
                "`test_the_battery_answers_as_recorded` holds the shape."
            )
            continue
        if len(sites) > 1:
            report.append(
                f"{path} holds {len(sites)} constructions and its exemption covers "
                f"one, which is {entry.why}. A second rule here decides the fold, "
                f"the ordering and the caps again: {sites}"
            )
            continue
        actual = _containing_statement(sources[path], int(sites[0].rsplit(":", 1)[1]))
        if actual != entry.statement:
            report.append(
                f"{sites[0]} is not the construction its exemption covers. "
                "Nothing here says a tag is decided a second time: the "
                "statement moved, so re-read the reason and re-key it.\n"
                f"      exemption covers: {entry.statement}\n"
                f"      construction is:  {actual}"
            )
    return report


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
        corpus = _source_modules()
        offenders = outside(constructions_by_ast(corpus), MINTERS)

        assert not offenders, (
            "these construct a Tag outside the mint, so the fold, the ordering and "
            f"the caps are decided again wherever they are: {offenders}"
        )

    @pytest.mark.parametrize(
        "census", [constructions_by_ast, constructions_by_token], ids=["tree", "token"]
    )
    def test_each_exempt_file_holds_only_the_construction_it_was_exempted_for(
        self, census
    ) -> None:
        """A file is exempt for one construction, and this is the arm that says
        so: a second one there, and the covered one having moved, are its two
        failures and they carry different messages.

        **Both instruments, for the reason the file has two.** The first
        version wired this failure to the tree pass alone, so a tree pass gone
        quietly blind to a construction inside an exempt file had nothing to
        disagree with it, which is exactly what two readings that degrade
        differently are bought for. The token pass reports a file and a line
        like the other, so it feeds the same function.
        """
        corpus = _source_modules()
        drifted = inside_but_unexempted(census(corpus), MINTERS, corpus)

        assert not drifted, "\n  ".join(["", *drifted])

    def test_the_second_instrument_agrees_on_the_tree(self) -> None:
        """Two readings that degrade differently, so a matcher that stopped
        matching is a disagreement rather than a clean run."""
        corpus = _source_modules()

        assert not outside(constructions_by_token(corpus), MINTERS)

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


#: Every read of `Tag` **the fourth pass reports**, and why that one is safe.
#:
#: Not every read there is. The pass matches a reading method on `Query` or
#: `Select`, and a clause built from anything else is invisible to it: the live
#: member is `sru.py`'s subject index, `Book.tags.any(Tag.name.ilike(...))`,
#: where neither `any` nor `ilike` is such a method. That read is safe for the
#: reason the `shelf.py` entry carries, it narrows Books and resolves no name
#: outward, **and an entry for it cannot be written**, because the arm below
#: pairs entries with reported lines one for one and an entry for an unreported
#: line would red the guard. So it is named in the class docstring's list of
#: what this does not see, which is the only place it can be recorded.
#:
#: **Keyed on the enclosing function and the whole flattened statement**,
#: positionally in line order. `BOOK_OWNED_READERS` keys on the statement
#: alone, which works there because no two of its statements are spelled the
#: same. Here four are: `tag = db.get(Tag, tag_id)` appears in four handlers of
#: `routers/books.py` and three of them differ only in what the next line does
#: with it. Keyed on the statement alone, their four reasons would be
#: interchangeable and could drift onto each other in silence, which is the
#: fragment failure one level up. The function name is read off the `ast`, not
#: matched out of the text.
#:
#: A reason, not a restatement. "Admin only, and the name never leaves" is a
#: reason; "reads a Tag" is not.
@pytest.fixture
def writer(db) -> User:
    """The member doing the writing. Named for the role rather than for the
    account, because everything below is about what a **writer** may be handed
    and the account is incidental."""
    row = User(username="reader", password_hash="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def stranger(db, writer) -> User:
    row = User(username="stranger", password_hash="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class TestNamingATagForAWriter:
    """`Naming` is the Mint with a viewer on the hand off, and the two writers
    that resolve a name from a member ask it.

    The match itself stays unscoped for the reason `Mint.get_or_mint` gives,
    so what these arms are about is the step after the match: whether a Tag
    the Library already has is this Member's to be handed.
    """

    @pytest.fixture
    def mine(self, db, writer) -> Book:
        row = Book(title="Mine", added_by_user_id=writer.id)
        db.add(row)
        db.commit()
        return row

    @pytest.fixture
    def hidden(self, db, stranger) -> Tag:
        """A Tag whose only carrier is somebody else's private Book."""
        tag = Tag(name="Divorce Law", category="custom", is_predefined=False)
        book = Book(
            title="A private matter", is_private=True, added_by_user_id=stranger.id
        )
        book.tags.append(tag)
        db.add_all([tag, book])
        db.commit()
        return tag

    def test_a_name_the_library_does_not_have_is_minted(self, db, writer) -> None:
        tag = Naming.for_member(db, writer.id).tag("Holiday reads")

        assert tag is not None
        assert tag.name == "Holiday reads"

    def test_a_name_whose_every_book_is_hidden_is_refused(
        self, db, writer, hidden
    ) -> None:
        assert Naming.for_member(db, writer.id).tag("Divorce Law") is None

    def test_and_folding_still_finds_it_rather_than_minting_a_second_row(
        self, db, writer, hidden
    ) -> None:
        """**The refusal must not be a miss**, which is the whole reason the
        viewer is here and not on the match: a miss falls to the mint and
        inserts a name the binary unique index already holds."""
        before = db.query(Tag).count()

        assert Naming.for_member(db, writer.id).tag("divorce LAW") is None

        assert db.query(Tag).count() == before

    def test_a_name_it_has_already_handed_over_stays_handed_over(
        self, db, writer, mine
    ) -> None:
        """**The false refusal a viewer introduces into every ordinary
        upload.** `Vocabulary.counts` is read once, so the Book this writer
        has just tagged is not in it, while `_carried_by_any_book` is live and
        answers yes: without the memory the writer's own name is refused off
        their own Book from the second row on.
        """
        naming = Naming.for_member(db, writer.id)
        first = naming.tag("Holiday reads")
        assert first is not None
        attach(mine, first)
        db.commit()

        assert naming.tag("Holiday reads") is first

    def test_and_a_later_unit_of_work_reaches_the_same_answer_without_it(
        self, db, writer, mine
    ) -> None:
        """What says the memory is the true answer rather than a patch over a
        stale read: a fresh Naming reads a fresh count, sees the Book on this
        writer's own shelf, and admits the name on `writable`'s second arm."""
        first = Naming.for_member(db, writer.id).tag("Holiday reads")
        assert first is not None
        attach(mine, first)
        db.commit()

        assert Naming.for_member(db, writer.id).tag("Holiday reads") is first

    def test_a_name_that_normalises_to_nothing_is_the_same_answer(
        self, db, writer
    ) -> None:
        """One outcome for every reason, because separating them is the oracle
        the refusal exists to narrow."""
        assert Naming.for_member(db, writer.id).tag("  \x00 ") is None

    def test_a_spent_budget_is_the_same_answer_again(self, db, writer) -> None:
        """Both names are ones `seed_tags` does not own, because a seeded name
        is answered off the table rather than minted and would pass this with
        the budget ignored."""
        naming = Naming.for_member(db, writer.id, budget=1)

        assert naming.tag("Holiday reads") is not None
        assert naming.tag("Bookclub") is None

    def test_it_does_not_commit(self, db, writer) -> None:
        """The module's one non negotiable shape: an import commits once at the
        end of the file, so nothing here may commit in the middle of one."""
        Naming.for_member(db, writer.id).tag("Holiday reads")
        db.rollback()

        assert db.query(Tag).filter(Tag.name == "Holiday reads").count() == 0


TAG_READERS: Final = {
    "backup.py": [
        (
            '_repair_seeded_tags: for tag in db.query(Tag).all(): # **One pass,'
            ' and that it is safe rests on `_parse_row` blanking the # key.** '
            '`uq_tags_key` is unique, so a key moving from one row to # another'
            ' would need the old holder cleared in an earlier statement, # and '
            'the order SQLAlchemy flushes these in is not the order of this # '
            'loop. No key can move here: every row arrives null, `tags.name` is'
            ' # unique, and `PREDEFINED_TAGS` maps 105 distinct names onto 105 '
            '# distinct keys, so this writes each key at most once. Delete # '
            '`_blank_tag_key` and this becomes an `IntegrityError` on a restore. '
            'seeded_key = keys_by_name.get(tag.name) should_be = '
            'seeded_key is not None if tag.is_predefined != should_be or '
            'tag.key != seeded_key: tag.is_predefined = should_be tag.key = '
            'seeded_key changed += 1',
            "reads every Tag into the archive, names included. Admin only, and "
            "`tests/test_shelf.py` already names `backup.py` as one of the ways "
            "past a viewer: an archive that omitted another member's rows would "
            "restore a library missing them.",
        ),
    ],
    "main.py": [
        (
            "seed_tags: existing = {name for (name,) in db.query(Tag.name).all()}",
            "`seed_tags()` at boot, deciding which seeded names are already "
            "present. No viewer exists at boot and no name leaves the process: "
            "the set is compared against `PREDEFINED_TAGS`, which the mirror "
            "publishes anyway.",
        ),
    ],
    "routers/books.py": [
        (
            "delete_tag: tag = db.get(Tag, tag_id)",
            "admin only and answers 404, 400 for a "
            "seeded row, or 204. The name is never returned, so what an admin "
            "learns is that an id they typed is in use.",
        ),
        (
            "_require_tag: tag = db.get(Tag, tag_id)",
            "the Tag a bulk verb names. **Gated on the next line** by "
            "`Vocabulary.writable`, which is what collapses a Tag the caller "
            "may not be told about into the 404 an unused id already gets.",
        ),
        (
            "add_book_tag: tag = db.get(Tag, tag_id)",
            "gated on the next line by `Vocabulary.writable`, "
            "and it is the site that made the id an oracle: `book_to_out` "
            "returns the Book with its tags, so attaching a guessed id used to "
            "hand back the name.",
        ),
        (
            "remove_book_tag: tag = db.get(Tag, tag_id)",
            "**deliberately ungated**, with the measurement "
            "at its own site: this answers 200 with the unchanged Book whether "
            "the id is unused or merely hidden, so it confirms nothing, and a "
            "404 for the second would create the tell rather than close one.",
        ),
    ],
    "routers/stats.py": [
        (
            'get_stats: by_tag = ( shelf.select( Tag.name, Tag.category, '
            'Tag.key, func.count(book_tags.c.book_id).label("count") ) '
            '.join(book_tags, Book.id == book_tags.c.book_id) .join(Tag, Tag.id'
            ' == book_tags.c.tag_id) .group_by(Tag.id) .order_by(Tag.category, '
            'func.count(book_tags.c.book_id).desc(), Tag.name) .all() )',
            "the statistics page's tag counts, rooted at the Shelf and inner "
            "joined out to `tags`, so a Tag no visible Book carries produces no "
            "row. Correct, and reported anyway, which is the cost of not trying "
            "to recognise a correct join.",
        ),
    ],
    "shelf.py": [
        (
            'matching: shelf = shelf.where(Book.tags.any(Tag.id == tag_id))',
            "the tag filter, which narrows a Shelf that already carries the "
            "viewer's predicate. It reads an id the caller supplied and returns "
            "Books, never a Tag, so no name is resolved here at all.",
        ),
    ],
    # **`tags.py` is in the list like everything else, and that is the fix for
    # a hole this guard shipped with.** It exempted the module by filename, so
    # any read anywhere in it was exempt with no entry and no reason. Measured:
    # append a plain function returning the whole table, point `list_tags` at
    # it, and the guard was green with the disclosure fully restored, because
    # the route then named no entity and the new read sat inside the
    # exemption. `test_a_bypass_beside_the_vocabulary_is_not_exempt_for_being_there`
    # is that plant.
    "tags.py": [
        (
            "_by_folded_name: self._index = _first_wins(self._db.query(Tag)"
            ".order_by(Tag.id).all())",
            "the Mint's deduplication index: every Tag row, unscoped. **Library "
            "wide of necessity and not a disclosure**, because no name leaves "
            "it. Two spellings of one name must not both exist, so deciding a "
            "name has to see every name; what the caller gets back is the row "
            "for the name they supplied, which they already had. Read once per "
            "unit of work and lazily, so a caller resolving no name issues no "
            "query.",
        ),
        (
            "listable: return [ tag for tag in self._db.query(Tag)"
            ".order_by(Tag.category, Tag.name).all() if _is_seeded(tag) or "
            "counts.get(tag.id, 0) > 0 ]",
            "**the rule itself**, and the one read in the tree whose job is to "
            "decide this question. The comprehension is the filter: the table "
            "is read whole and each row is kept only when the seeded exemption "
            "or this viewer's count admits it. The scoping is in the same "
            "statement as the read, which is what an entry here can check and "
            "a reader can see.",
        ),
    ],
}


def _reaches_private(source: str, private: frozenset[str]) -> list[str]:
    """Where this module names one of those private members on another object.

    Two shapes, and the second is not decoration: `getattr(mint, "_index")`
    carries the name as a string, which no attribute walk sees.

    **`self` is excluded and that is the whole of what keeps this usable.**
    These names are derived from one class and are ordinary private field
    names, so other classes carry their own: reporting `self._db` would report
    four unrelated modules. A class reaching its own state is not reaching into
    a Mint; reaching one through anything else is, whatever holds it.

    **That exclusion is safe only because `Mint` is `@final`**, and the
    decorator is what makes the sentence above true rather than nearly true. A
    **subclass** reaching its own state writes `self._index` and inherits the
    slot, so it reaches into a Mint through the one receiver this skips:
    measured, a subclass in a router with a route over its rows passed the
    whole suite and served a member a hidden tag. Subclassing is refused by
    the type check in the gate, which also closes the two routes no `ast` walk
    resolves, a class built by `type(...)` and a subclass declared through an
    alias elsewhere. **Do not remove that decorator as decoration.**

    **What is outside both walks is three mechanisms, and the members of each
    are open.** Named rather than listed, because the first version of this
    paragraph gave two examples and read as though it had given the set.

    *An accessor taking the name as data.* A `getattr` on a computed name, a
    static lookup, a dunder access, a loop over the slot names handing each to
    `getattr`. Nothing here spells an attribute, so no walk over attribute
    nodes sees any of them.

    *The object's state as data.* `__reduce_ex__(2)` hands back the slot state
    as a dict keyed by the slot names, with no attribute spelled anywhere;
    measured, the keys are exactly `__slots__`. The instance dictionary is the
    same door and is shut **only because `__slots__` is declared**: delete
    that line, an edit nobody reviews as touching a guard, and `vars(mint)`
    answers with the index while the decorator is still in place. **So
    `__slots__` is load bearing for this rule as well as for memory.**

    *The rows, reached without reaching the object.* Measured on this tree: a
    route building a Mint, resolving one seeded name and then walking the
    session's identity map served a member the name of a tag whose only book
    is another member's private one. No private name, no `getattr`, no
    subclass. **And what makes it work is the Mint**, which is the half worth
    knowing: the identity map holds weak references, so the same walk through
    the vocabulary returns nothing, and it is the live index holding every row
    strongly for the length of the request that puts them there.

    **So what this arm contains is the class's surface, not the rows.** That
    is not a hole in it: nothing here claims to contain object identity, and
    `@final` does what it was measured doing. It is the extent the sentence
    above must not claim.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in private:
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                continue
            found.append(f"{node.lineno}: {ast.unparse(node)}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in private
        ):
            found.append(f"{node.lineno}: {ast.unparse(node)}")
    return found


class TestNothingElseDecidesWhoMaySeeATag:
    """`tags.Vocabulary` is the only module answering who may be told a Tag exists.

    **The counterpart of `TestNothingElseDecidesATagFromAName`, one level out.**
    That rule made `Mint` the only writer; this one makes `Vocabulary` the only
    reader that takes a viewer. The writes had an owner and the reads had none,
    which is how a name minted off somebody's Private Book reached every member
    on every page load with a `book_count` of zero: the count had been scoped
    for privacy and the row set had not.

    **The same instrument as the shelf rule, with the entity substituted.**
    `tests/test_shelf.py::_book_owned_offences` is the fourth pass, and it takes
    the entity set as a parameter for this. A second walk written here would be
    a second thing to keep in step, and this repository has measured seven
    guards whose population was matched from source text and every one was
    wrong at least once. Sharing the instrument means a miss is a miss in one
    place.

    **Why `tags` is not simply in `BOOK_OWNED` instead.** That set is derived
    from the foreign key to `books`, which is the right derivation for what it
    guards: `tags` has no such key, because `book_tags` carries it. A library
    wide vocabulary is reachable **from** books without being a child **of**
    them, and widening a foreign key derivation to catch one would turn it into
    an inclusion list of vocabularies. This is the second question, asked
    separately.

    **What it does not see.** Everything the shared pass does not see, which its
    own docstring lists: raw SQL, a read through a relationship attribute, a
    query over a name bound at runtime.

    **And a clause built with no reading method, which has a live member.**
    `sru.py:1298` returns `Book.tags.any(Tag.name.ilike(...))` from a helper.
    Neither `any` nor `ilike` is on `Query` or `Select`, so the pass never
    reports it and `TAG_READERS` cannot carry it: the arm below pairs entries
    with reported lines one for one, so an entry for an unreported line would
    red the guard. **A refusal in the direction nobody looks**, recorded here
    because there is nowhere else it can go. That read is safe for the reason
    the `shelf.py` entry gives, and the shape is not: a second one written
    tomorrow would be as invisible.

    **And where the rows go.** The pass matches a statement that reads the
    entity and says nothing about what the caller does with the result, which
    is why `test_the_mint_s_index_is_named_nowhere_else` exists beside it. It also says nothing about
    `collections` and `custom_fields`, which were measured to carry the same
    shape live on this tree and are a separate ticket; `Vocabulary` takes a
    viewer and a Shelf and nothing else, so a second vocabulary moves behind it
    without a second design round.
    """

    #: The module the Mint's private state belongs to. This arm is about a
    #: module boundary, unlike `TAG_READERS`, which is about statements: the
    #: whole claim is that nothing outside this file reaches into the class.
    OWNER: Final = "tags.py"

    @staticmethod
    def _offences(sources: dict[str, str]) -> dict[str, list[int]]:
        from tests.test_shelf import _book_owned_offences

        return {
            name: lines
            for name, source in sources.items()
            if (lines := _book_owned_offences(source, frozenset({"Tag"})))
        }

    @staticmethod
    def _key(source: str, line: int) -> str:
        """`<enclosing function>: <flattened statement>`, both off the `ast`.

        The function is the innermost `def` containing the line, so a statement
        moved from one handler to another changes its key and has to be
        re-argued rather than inheriting a reason written about somewhere else.
        A statement at module level keys on the statement alone.
        """
        from tests.test_shelf import _statement_at

        enclosing = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.lineno <= line <= (node.end_lineno or node.lineno)
        ]
        statement = _statement_at(source, line)
        if not enclosing:
            return statement
        # The innermost, which is the one declared last of those containing the
        # line: a nested helper would otherwise key on the function around it.
        holder = max(enclosing, key=lambda node: node.lineno)
        return f"{holder.name}: {statement}"

    def _report(self, sources: dict[str, str]) -> list[str]:
        """The comparison, over whatever corpus it is handed.

        **A parameter so the plant below runs the rule the tree is read
        against**, rather than a copy of it: a fixture exercising its own copy
        reports on a rule nothing else uses.
        """
        found = self._offences(sources)

        report: list[str] = []
        for name in sorted(set(found) | set(TAG_READERS)):
            lines = found.get(name, [])
            entries = TAG_READERS.get(name, [])
            if len(lines) != len(entries):
                shown = "\n".join(
                    f"      {name}:{line}  {self._key(sources.get(name, ''), line)}"
                    for line in lines
                )
                report.append(
                    f"  {name}: {len(lines)} reads, {len(entries)} classified\n{shown}"
                )
                continue
            for line, (expected, _) in zip(lines, entries, strict=True):
                actual = self._key(sources.get(name, ""), line)
                if actual != expected:
                    report.append(
                        f"  {name}:{line} is not what its entry is keyed on.\n"
                        f"      entry expects: {expected}\n"
                        f"      statement is:  {actual}"
                    )

        return report

    def test_every_tag_reader_is_classified(self) -> None:
        report = self._report(_source_modules())

        assert not report, (
            "A statement reads the Tag table, and either is not classified or "
            "is not the statement its entry was written for.\n\n"
            + "\n".join(report)
            + "\n\n  A Tag carries no member, so nothing in a row says who may "
            "read it: the answer is whoever may read a Book carrying it, and "
            "`tags.Vocabulary` is where that is decided. Publishing a set of "
            "names out of this table discloses what other members typed against "
            "Books you cannot see, which is what `GET /api/books/tags` did.\n\n"
            "  If your read is genuinely safe, add an entry to TAG_READERS with "
            "the statement exactly as printed above and why. If you cannot write "
            "the reason in a sentence, ask `Vocabulary` instead."
        )

    def test_a_bypass_beside_the_vocabulary_is_not_exempt_for_being_there(
        self,
    ) -> None:
        """The plant this rule shipped green, and the reason no module is exempt.

        A first version exempted `tags.py` by filename. Appending a plain
        function that returns the whole table and pointing the route at it put
        the disclosure back with the guard still green: the route then named no
        entity, so no pass saw it, and the new read was inside the exemption.

        **A floor on the number of reads in that module does not catch it**,
        which is what the first version asserted instead: the plant adds a read
        rather than removing one.
        """
        sources = dict(_source_modules())
        sources["tags.py"] += (
            "\n\ndef every_tag_there_is(db):\n"
            "    return db.query(Tag).order_by(Tag.category, Tag.name).all()\n"
        )
        rewritten = sources["routers/books.py"].replace(
            "for tag in vocabulary.listable()", "for tag in every_tag_there_is(db)", 1
        )
        # **The plant is data about another module**, so a rewrap of that line
        # turns the replace into a no op and leaves this arm passing on a tree
        # it did not plant anything in. Asserted rather than assumed.
        assert rewritten != sources["routers/books.py"], (
            "the route no longer spells the call this plant rewrites, so "
            "nothing was planted"
        )
        sources["routers/books.py"] = rewritten

        report = self._report(sources)

        assert any("every_tag_there_is" in line for line in report), report

    def test_the_mint_s_private_state_is_reached_from_nowhere_else(self) -> None:
        """`_by_folded_name`'s entry rests on "no name leaves it". Nothing
        checked that.

        It is the unscoped whole table index, read so that two spellings of one
        name cannot both exist. The pass reports the statement that builds it
        and says nothing about **where the rows go**, so a caller reusing the
        index restores the disclosure with **no new read anywhere**: measured,
        one line in `search_books` swapping the vocabulary for
        `list(Mint(db)._by_folded_name.values())` passed the whole gate, mypy
        and ruff included, and served a member the id of a tag on somebody
        else's private book.

        **The names are derived from the class, because the state has more
        than one.** A first version matched the source text for
        `_by_folded_name`, which is one spelling of it: the property returns
        `self._index`, that slot **is** the same dict, and it is populated by
        any call that resolves a name the table already holds, which mints
        nothing. A planted route building a `Mint`, resolving one name and
        returning the slot's values was green on that version and served the
        member a hidden tag. The slot is the shape that works; a bound method
        hands out no table, an import of the class names nothing private, and
        a `getattr` with the literal contains the literal and was caught.

        **Reached from anything but `self`, which is what keeps it green.**
        `_db` is one of the four derived names and is an ordinary private field
        name: four other modules carry `self._db` on classes of their own, 55
        times, and none of them is this Mint. Its own state is `self._x` inside
        its own file, so the property this arm tests is not the name but the
        name **on another object**, which is what reaching into a Mint from
        outside looks like however it is spelled.
        """
        from tags import Mint

        private = frozenset(
            name
            for name in set(Mint.__slots__) | set(vars(Mint))
            if name.startswith("_") and not name.startswith("__")
        )
        assert private, "Mint declares no private state, so this arm tests nothing"

        reaching = {
            name: sites
            for name, source in _source_modules().items()
            if name != self.OWNER and (sites := _reaches_private(source, private))
        }

        assert not reaching, (
            "the Mint's index is the whole tag table with no viewer, and its "
            "entry in TAG_READERS is safe only because no name leaves the "
            f"function that builds it. These reach into it: {reaching}. A "
            "caller outside `tags.py` holding those rows has the disclosure "
            "back with no read this rule can see."
        )

    def test_deleting_an_unrelated_entry_does_not_explain_that_red(self) -> None:
        """Wave G's check, because a red for the wrong reason is not a red.

        The plant above is reported with a second module's entry knocked out
        from under it, so the failure is the plant rather than an accident of
        the corpus holding exactly one spare offence.
        """
        sources = dict(_source_modules())
        sources["tags.py"] += (
            "\n\ndef every_tag_there_is(db):\n"
            "    return db.query(Tag).all()\n"
        )
        knocked_out = sources["routers/stats.py"].replace(
            "Tag.name, Tag.category, Tag.key,", "1,", 1
        )
        # Same reason, and worse here: this one is the **control**. If the
        # replace no ops, the arm still passes and has quietly stopped
        # deleting the unrelated thing it exists to delete.
        assert knocked_out != sources["routers/stats.py"], (
            "the statistics index no longer spells the columns this control "
            "knocks out, so nothing unrelated was deleted"
        )
        sources["routers/stats.py"] = knocked_out

        report = self._report(sources)

        assert any("every_tag_there_is" in line for line in report), report


#: Every call outside `tags.py` that is handed a Tag resolved from a name, and
#: why that call is allowed to be.
#:
#: **Keyed on the call, which is the property the other two registers miss.**
#: `MINTERS` keys on constructing a Tag and `TAG_READERS` keys on querying one,
#: so a module that asks the Mint for a name and then attaches the answer
#: constructs nothing, queries nothing at its own site, and is reported by
#: neither. That module would resolve a name with no viewer and complete the
#: attach, which is exactly the disclosure `tags.Naming` exists to close, and
#: `Naming` is a convention until something says so.
#:
#: **`get_or_mint` is the whole surface**, because it is the only method that
#: hands a Tag back out of a Mint: the index is private, `@final` refuses a
#: subclass reaching it, and `__slots__` refuses `vars()`. Those three are the
#: same reasoning `TestNothingElseDecidesWhoMaySeeATag` rests on and are argued
#: at their own sites rather than again here.
#:
#: One sentence per entry saying why that caller is not the hole. **A caller
#: that attaches what it resolves is the hole**, and the repair is to ask
#: `tags.Naming` rather than to add an entry.
TAGS_RESOLVED_WITHOUT_A_VIEWER: Final = {
    "routers/books.py": [
        (
            "create_tag: minted = Mint(db).get_or_mint(payload.name)",
            "the create route, which mints and hands back the row and "
            "**attaches nothing**. The attach is what publishes a name, by "
            "putting it on a Book that counts for every member, so a route "
            "that does not attach discloses only what `Vocabulary`'s own "
            "docstring records as open: that a guessed name is confirmed. "
            "Gating this call instead would answer the same question through "
            "a status line and would refuse the member who typed the name.",
        ),
    ],
}


class TestNothingElseIsHandedATagResolvedFromAName:
    """`tags.Naming` is the only way a writer gets a Tag it may attach.

    **The third register, and the gap between the first two.**
    `TestNothingElseDecidesATagFromAName` makes `Mint` the only writer and
    keys on constructing a row; `TestNothingElseDecidesWhoMaySeeATag` makes
    `Vocabulary` the only viewer aware reader and keys on querying the table.
    A module doing neither, asking the Mint for a name and attaching what
    comes back, is reported by **neither**, and that module is the branch this
    rule was written on: an import did exactly that and published a name off
    another member's private Book to every member in the library.

    **`Naming` closed that at two call sites and closes nothing at a third.**
    It is a class somebody has to choose to use, so what keeps it the only
    road is this register rather than its existence.

    **What the walk sees, and what it does not.** It reports a `get_or_mint`
    spelled as an attribute anywhere outside `tags.py`, including through an
    alias, a local, or a `getattr` with the literal, because it is the same
    instrument the private state arm uses and it is shared rather than
    reimplemented.

    **It skips a receiver spelled `self`, and that skip stands on two limbs.**
    Reaching a **Mint's** method through `self` needs a subclass, which
    `@final` and the type check in the gate refuse, for the reason
    `_reaches_private` gives at its own site. And the case that actually
    arises, a class of its own defining `get_or_mint` and delegating to a Mint
    it holds, is caught at the delegation, where the receiver is `self._mint`
    rather than `self`. Finality says nothing about that one, so a sentence
    carrying only the first limb reads as true and covers half of what the
    skip needs.

    **Two mechanisms go past, and both are argued elsewhere rather than
    restated here.** A `getattr` on a computed name, which no walk over
    attribute nodes sees. And a Tag reached off another Book's rows rather
    than off a Mint, which constructs nothing, queries nothing at its own site
    and calls no resolver, so all three registers in this file are silent.
    `_reaches_private` holds both families, with the identity map route
    measured on this tree.

    **Nothing plants a call to show the walk is armed, and the absence is
    deliberate rather than a gap.** The register carries a classified entry,
    so a walk gone inert reports no sites against one entry and reddens
    `test_every_caller_of_the_mint_is_classified` on the count. The register
    is its own arming check; a planted call would be a second one.
    """

    OWNER: Final = "tags.py"

    #: Every public name `Mint` declares that is not one of its slots.
    #:
    #: **A syntactic set standing in for a semantic one.** The rule wants
    #: every method that hands a caller a Tag it did not already hold; what
    #: code can read off a class is its public surface. They are one set today
    #: and diverge the day `Mint` grows a public method handing back something
    #: else, so `test_the_mint_exposes_one_resolver_and_this_is_it` is what
    #: holds them together rather than this comment.
    #:
    #: **Read off the class rather than written out, and the widening has to
    #: be noticed rather than taken.** This name goes to a walk that reports
    #: the attribute on **any** receiver anywhere in the backend, so what a
    #: second member costs is decided by how common its spelling is and not by
    #: anything about `Mint`. Measured as the walk sees it, with the owner
    #: excluded: `get_or_mint` is 1 site in 1 module, a `seen_by` would be 44
    #: in 10, a `get` would be 398 in 48. A failure naming 48 modules of
    #: `db.get(...)` cannot be acted on, so the arm is the brake and the road
    #: back to green is never to quietly edit this derivation.
    #:
    #: **What it excludes is a private name, a declared slot, and an inherited
    #: member**, since `vars` is the class dictionary alone. Excluding by slot
    #: rather than by type is the half that matters: it separates state from
    #: surface by the property that actually decides it, and admits a
    #: classmethod, a property and a `cached_property`, each of which can hand
    #: a Tag out. **An exclusion list reads as complete and is the sentence
    #: most likely to be short.** A `callable` test here would read as having
    #: named them and would drop a classmethod, which is the idiom
    #: `Vocabulary.seen_by` and `Naming.for_member` are both written in, and
    #: so is the `Mint.for_import` somebody writes next.
    RESOLVERS: Final = frozenset(
        name for name in vars(Mint) if not name.startswith("_")
    ) - frozenset(Mint.__slots__)

    def test_the_mint_exposes_one_resolver_and_this_is_it(self) -> None:
        """Derive it and assert it, so a widening is noticed rather than taken.

        The set above is read off the class, which is what stops a second
        public method being silently left out of the walk. What that alone
        does not stop is the same method widening a **tree wide** attribute
        walk under whoever added it, at a cost set by its spelling. So the
        derivation moves, and this reddens by name at one site, which is a
        sentence somebody can act on.

        Sorted into a list rather than compared as a set, so the failure
        prints the member that widened it beside the one that belongs. The
        name is the whole content of this arm's report.
        """
        assert sorted(self.RESOLVERS) == ["get_or_mint"]

    @staticmethod
    def _keyed(source: str, site: str) -> str:
        """`<enclosing function>: <flattened statement>`, for one reported site.

        **The same keying as `TAG_READERS`, called rather than copied.** Two
        spellings of one rule is what the registers in this file exist to
        stop, and a second copy would drift on the day somebody changes how a
        statement is flattened. The line comes off the front of what
        `_reaches_private` reports, which is that function's own format.
        """
        line = int(site.split(":", 1)[0])
        return TestNothingElseDecidesWhoMaySeeATag._key(source, line)

    def _report(self, sources: dict[str, str]) -> list[str]:
        found = {
            name: sites
            for name, source in sources.items()
            if name != self.OWNER
            and (sites := _reaches_private(source, self.RESOLVERS))
        }

        report: list[str] = []
        for name in sorted(set(found) | set(TAGS_RESOLVED_WITHOUT_A_VIEWER)):
            sites = found.get(name, [])
            entries = TAGS_RESOLVED_WITHOUT_A_VIEWER.get(name, [])
            if len(sites) != len(entries):
                shown = "\n".join(
                    f"      {name}:{site}  {self._keyed(sources.get(name, ''), site)}"
                    for site in sites
                )
                report.append(
                    f"  {name}: {len(sites)} calls, {len(entries)} classified\n{shown}"
                )
                continue
            for site, (expected, _) in zip(sites, entries, strict=True):
                actual = self._keyed(sources.get(name, ""), site)
                if actual != expected:
                    report.append(
                        f"  {name}:{site} is not what its entry is keyed on.\n"
                        f"      entry expects: {expected}\n"
                        f"      statement is:  {actual}"
                    )

        return report

    def test_every_caller_of_the_mint_is_classified(self) -> None:
        report = self._report(_source_modules())

        assert not report, (
            "a module outside `tags.py` is handed a Tag resolved from a name, "
            "and either is not classified or is not the statement its entry "
            "was written for.\n\n"
            + "\n".join(report)
            + "\n\n  The Mint matches a name against every Tag in the library "
            "with no viewer, deliberately and for the reason "
            "`Mint.get_or_mint` gives. What makes that safe is that the "
            "viewer is applied before the answer reaches a writer, which is "
            "`tags.Naming`.\n\n"
            "  **If your caller attaches what it resolves, it is the hole**: "
            "ask `Naming.for_member(db, member_id).tag(name)` instead, which "
            "is what the import and the attach by name route do. Only a "
            "caller that attaches nothing belongs in "
            "TAGS_RESOLVED_WITHOUT_A_VIEWER, with one sentence saying so."
        )

    def test_no_entry_names_a_module_that_is_gone(self) -> None:
        """An exclusion list that only grows is how a ratchet stops being one.

        **Module keys, which is all this compares.** The call level ratchet is
        the arm above, where a module's classified entries are counted against
        the sites found in it, and an entry for a call the tree no longer
        makes reddens there. So does a module that has gone, as no sites
        against one entry; what this adds is the sentence saying which,
        because that count over a module with no source reads as a call that
        moved rather than as a file that did.
        """
        sources = _source_modules()

        stale = sorted(set(TAGS_RESOLVED_WITHOUT_A_VIEWER) - set(sources))

        assert not stale, (
            f"these are classified and are no longer modules here: {stale}"
        )
