"""What a name means in a Python module, answered once.

**One home for "which local names mean this thing".** Before this module the
question was answered by a resolver in each guard that needed it, and the copies
disagreed: one followed `m = metadata` and its namesake in another file did not,
and one took the bound name where the rule needed the imported one.
`test_bindings.py` holds every other module to the reads of an import alias it
still makes, by count per function, so the next resolver that reads an alias is
written here. A resolver reading only the imported name reads no alias, and
that ratchet does not see it.

**Two adapters, each with a `means`, answering in different namespaces:**

* `SourceNames` reads the source alone, so a guard can drive a planted string
  that could never be imported. It follows imports and plain rebinding, and
  nothing else: a name bound by `def`, `for`, `with` or a call means nothing
  here. It answers with the **path the import spelled**, so `from os.path import
  join` means `os.path.join`.
* `ModuleNames` reads an imported module's own globals, which is what the
  interpreter will do. It answers with the **home the object was defined in**,
  so that same `join` means `posixpath.join`, and a function the module defines
  means a name, where the source adapter gives it none.

So the two agree on a name imported from where it is defined, and part on a
re-export and on a module's own definitions; `test_bindings.py` pins both.

**The source adapter is flow insensitive.** Every binding anywhere in the module
counts, at any depth and in any order, so a name rebound to two things means
both. A guard is wrong loudly that way, by reporting a binding that a later line
replaced, rather than silently by missing one an earlier line made. The one cut:
no meaning is derived through the same refining assignment twice, so `os = os.path`
means `os` and `os.path`, and not `os.path.path`, while `x = mod; x = x.sub`
still means `mod.sub`. What that misses is a meaning only one assignment
applied twice would give, as a loop running `x = x.parent` does.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from tests.declaration import declares


@dataclass(frozen=True)
class Binding:
    """One local name and the dotted name it stands for.

    `written` is the name as the import spelled it, and `None` for a rebinding.
    `from_module` is the module a `from` import took it from, resolved where the
    package was given, and `None` for anything else.
    """

    local: str
    target: str
    written: str | None = None
    from_module: str | None = None


def assignments(node: ast.AST) -> list[tuple[ast.expr, ast.expr]]:
    """The `(target, value)` pairs one statement binds.

    **`AnnAssign` as well as `Assign`**: the annotated form is the more
    idiomatic half of this backend, and a resolver reading only `Assign` follows
    the less used spelling. A tuple target is unpacked against a tuple value of
    the same length, so `M, N = Book, Tag` binds `M` to `Book` and nothing else.
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


def _absolute(level: int, module: str | None, package: str | None) -> str:
    """The module a `from` import names, resolved against `package` where one is given.

    Without a package a relative import keeps its leading dots, so it can never
    equal an absolute name a guard asks for. That is a miss, and it is why a
    guard over a test tree passes the package.
    """
    if level == 0:
        return module or ""
    if package is None:
        return "." * level + (module or "")
    base = package.rsplit(".", level - 1)[0] if level > 1 else package
    return f"{base}.{module}" if module else base


def _star_names(module: ModuleType) -> list[str]:
    """What `from module import *` binds: its `__all__`, or every public global."""
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return list(declared)
    return [name for name in vars(module) if not name.startswith("_")]


def _rooted(expression: ast.expr) -> tuple[str, str] | None:
    """The local a `Name` or an attribute chain on one starts from, and the dotted rest."""
    rest = ""
    while isinstance(expression, ast.Attribute):
        rest = f".{expression.attr}{rest}"
        expression = expression.value
    return (expression.id, rest) if isinstance(expression, ast.Name) else None


class SourceNames:
    """The names one module's source binds, read without importing it.

    `package` is the dotted package the module sits in, for a relative import.
    `star` hands over the module a `from m import *` reads, or `None` where the
    caller will not import it; an unexpanded star binds nothing.
    """

    def __init__(
        self,
        source: str | ast.AST,
        *,
        package: str | None = None,
        star: Callable[[str], ModuleType | None] | None = None,
    ) -> None:
        tree = ast.parse(source) if isinstance(source, str) else source
        found: set[Binding] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    target = alias.name if alias.asname else local
                    found.add(Binding(local, target, alias.name))
            elif isinstance(node, ast.ImportFrom):
                origin = _absolute(node.level, node.module, package)
                joiner = "" if origin.endswith(".") else "."
                for alias in node.names:
                    if alias.name != "*":
                        local = alias.asname or alias.name
                        found.add(Binding(local, f"{origin}{joiner}{alias.name}", alias.name, origin))
                        continue
                    module = star(origin) if star is not None else None
                    for name in _star_names(module) if module is not None else ():
                        found.add(Binding(name, f"{origin}{joiner}{name}", name, origin))
        # Rebinding to a fixed point, because `a = b` may sit above `b = models`
        # in the walk and this does not care which. **Each meaning carries the
        # refining assignments it was derived through (those adding an
        # attribute, `x = x.sub`), and never uses one twice.** Without that,
        # `os = os.path` grew `os.path.path` and one name more per round, so the
        # answer depended on how many unrelated assignments the module held.
        # Keyed on the assignment and not on the local, because a local is
        # legitimately refined through itself by a second assignment: `x = mod;
        # x = x.sub` means `mod.sub`, exactly as `import mod as x; x = x.sub`
        # does. A plain rename (`a = b`) changes no meaning, so it is not
        # carried: a cycle of renames ends on the meanings already found, and
        # carrying them made six locals bound to each other run for minutes.
        # The cost left is in the refinements themselves: k refining
        # assignments among locals that rename each other in a cycle (a
        # strongly connected group, not one local) give every order of them as
        # a meaning, which is the loud direction, and grows factorially: two
        # locals with five each gave 32826 meanings in 0.44 s.
        pairs = [
            (target.id, rooted)
            for node in ast.walk(tree)
            for target, value in assignments(node)
            if isinstance(target, ast.Name) and (rooted := _rooted(value)) is not None
        ]
        derived: set[tuple[str, str, frozenset[int]]] = {
            (binding.local, binding.target, frozenset()) for binding in found
        }
        fresh = set(derived)
        while fresh:
            by_local: dict[str, list[tuple[str, frozenset[int]]]] = {}
            for local, meaning, used in fresh:
                by_local.setdefault(local, []).append((meaning, used))
            fresh = {
                (local, f"{meaning}{rest}", used | {index} if rest else used)
                for index, (local, (root, rest)) in enumerate(pairs)
                for meaning, used in by_local.get(root, ())
                if index not in used
            } - derived
            derived |= fresh
        self._meanings: dict[str, set[str]] = {}
        for local, meaning, _ in derived:
            self._meanings.setdefault(local, set()).add(meaning)
        imported = {(binding.local, binding.target) for binding in found}
        found |= {
            Binding(local, meaning)
            for local, meaning, _ in derived
            if (local, meaning) not in imported
        }
        self.bindings = frozenset(found)

    def means(self, expression: ast.expr) -> frozenset[str]:
        """The dotted names a `Name` or an attribute chain on one may stand for."""
        if isinstance(expression, ast.Name):
            return frozenset(self._meanings.get(expression.id, ()))
        if isinstance(expression, ast.Attribute):
            return frozenset(f"{base}.{expression.attr}" for base in self.means(expression.value))
        return frozenset()

    def bound_to(self, *targets: str) -> set[str]:
        """Every local name that may stand for one of `targets`, exactly."""
        return {b.local for b in self.bindings if b.target in targets}

    def imported(self) -> set[str]:
        """Every name an import here took, under both its spellings.

        **Both, because two questions are asked of an import.** "Which local
        names mean this" wants the bound name; "does this module reach this"
        wants the name it took, since `from models import Book as B` reaches
        `Book` whatever it calls it.
        """
        return {
            name
            for b in self.bindings
            if b.written is not None
            for name in (b.local, b.written)
        }


class ModuleNames:
    """The names of a module already imported, read off its globals."""

    def __init__(self, module: ModuleType | Any) -> None:
        self.module = module

    def value(self, expression: ast.expr) -> Any:
        """The object a dotted name holds where the module that wrote it reads it, or `None`."""
        steps: list[str] = []
        while isinstance(expression, ast.Attribute):
            steps.append(expression.attr)
            expression = expression.value
        if not isinstance(expression, ast.Name):
            return None
        found: Any = getattr(self.module, expression.id, None)
        for step in reversed(steps):
            found = getattr(found, step, None)
        return found

    def means(self, expression: ast.expr) -> frozenset[str]:
        """The dotted name of the object the expression holds: a module's own name,
        or where a class or function was defined. A value with neither means nothing."""
        found = self.value(expression)
        if isinstance(found, ModuleType):
            return frozenset({found.__name__})
        home = getattr(found, "__module__", None)
        qualname = getattr(found, "__qualname__", None)
        if isinstance(home, str) and isinstance(qualname, str):
            return frozenset({f"{home}.{qualname}"})
        return frozenset()



def source_of(path: Path) -> str:
    """A module's text with its line endings as written.

    `stated` asks `declares` of it, which follows the gate in ending a line only
    at a newline. Universal newlines would turn a bare carriage return into one,
    and call internal a module the gate publishes.
    """
    return path.read_text(encoding="utf-8", newline="")


def stated[Allowed](
    source: str,
    relative: str,
    rows: Mapping[str, Allowed],
    own: str,
    absent: Allowed,
) -> Allowed:
    """What a ratchet allows one module: its row in `rows`, or its own `own` if it is internal.

    **A module the mirror strips states its own allowance**, as a literal of
    `absent`'s type bound to `own` at module level, because a published row naming
    a stripped module would fail in a mirror clone, which does not carry it. Which
    modules those are is read off the declaration the publish gate demands.
    """
    if not declares(source.encode("utf-8")):
        return rows.get(relative, absent)
    for node in ast.parse(source).body:
        for target, value in assignments(node):
            if isinstance(target, ast.Name) and target.id == own:
                try:
                    allowed = ast.literal_eval(value)
                except ValueError:
                    continue
                if type(allowed) is type(absent):
                    return allowed
    return absent
