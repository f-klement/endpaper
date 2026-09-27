"""No route handler builds its own concurrency bound.

A bound built inside a handler body bounds one call, and every bound in this
application defends something the pod owns: `fetch.MAX_RESPONSE_BYTES`' sixteen
concurrent responses, two free image services with one address at them, a
metered key's bill. The identifier backfill built its semaphore per request, so
nine runs of six inside its own rate limit put 54 sockets against a pod priced
at sixteen with `metadata.search` already spending eight of them.

**Three arms, and only the first is the rule.** The second pins the set of
primitives the first matches on, by a derivation that degrades differently, and it
is the one that pays for itself: it alone reports a primitive arm one cannot see.
The third is the arming arm, because arm one is a refusal and a refusal is
vacuously green when nothing bounds anything at all; it says so by name rather
than by an `AttributeError`, its subject being derived from the module rather than
written down.

**There was a fourth, and it went with the exemption it policed.** `KNOWN_OPEN`
held `backfill_covers`' per request `ThreadPoolExecutor` and that arm held that the
row still matched a call, so that a debt could not outlive its reason. The route
now submits to a pool `covers.py` holds for the process, the row is gone, and over
an empty exemption list the arm asserted nothing: nothing is unpoliced, and an arm
that cannot fail is read as cover it is not giving.

**What the next seat to write an exemption does not get, measured rather than
assumed**: a row that matches nothing is **silent**, four arms green, so an
exemption outlives the work that justified it with nothing to say so. Adding one
means bringing that arm back with it, and this file's history carries its text.
`EXCLUDED` has no liveness arm either, and its rows are pinned only from the other
side, by `test_the_primitive_set_is_every_one_this_backend_constructs` going red
when the tree stops constructing what a row excuses.

**What none of the three holds is the bound's value.** Six raised to six hundred is
green in every arm here and red in
`test_books_identifier_backfill.py::TestTheSlotsAreDerivedRatherThanChosen`, which
is where a figure about the pod belongs.

**The deadline's placement is not held here and cannot be.** Nothing static can
tell a deadline spent on the slot from one spent on the request, so
`TestTheBatchIsBoundedInWallClockAndNotOnlyInBooks` in
`test_books_identifier_backfill.py` is what holds that. The third arm holds only
that this module acquires and releases the bound at all.

## What is refused here, and why the obvious spelling was not taken

The narrower rule this replaces was "no `asyncio.Semaphore(...)` inside a route
handler in `routers/books.py`". It passes the neighbouring instance of its own
defect, `backfill_covers`' per request `ThreadPoolExecutor`, which two seats
found independently: its population is a **spelling** and its file list is a
**list**. Both halves are replaced:

* the handlers come from the `@router.<method>` decorator, which is a property
  of the function, over every module of the route layer read off the directory;
* `PRIMITIVES` is still a set of names, so it gets `test_the_primitive_set_is_
  every_one_this_backend_constructs`, which derives the same set from **which
  module a constructed class came from** rather than from its name. A primitive
  nobody here has thought of fails that arm by name instead of passing this one
  in silence.

Arm one matches a call against both the name a primitive was **imported as** and
the name it **is**, so `from asyncio import Semaphore as Gate` then `Gate(6)` in
a handler is refused. The union of the two is deliberate: a resolution that
replaced the terminal name rather than joining it would accept
`from asyncio import Queue as Semaphore`, which the name alone refuses.

## What goes past all three, stated rather than bounded

The mechanism in each case, and no claim about how much is out there: every seat
that has tried to bound one of these in this repository succeeded at measuring
something and failed at bounding it.

* **A bound built one function away, a `Depends(...)` callable among them.** Arm
  one reads the calls inside a handler's own tree, `ast.walk` included, so a
  helper the handler calls is invisible however the helper builds it, and so is a
  callable FastAPI calls per request on the handler's behalf, which is per request
  exactly as a handler body is. Extending the population to the callables a
  handler's signature names would examine nothing here: measured 2026-09-26, 34
  `Depends(...)` sites in `backend/routers/`, none naming a function defined in
  the route layer, because the per request dependencies are `Annotated` aliases in
  `dependencies.py` and the one route layer callable,
  `routers.public.public_reader`, is passed to `APIRouter(...)` rather than to a
  handler.
* **A module level name called inside a handler.** `S = asyncio.Semaphore` at
  module level is a legitimate mention there, and `S(6)` in a handler resolves to
  no import, so neither the name it is nor the name it was imported as is a
  primitive.
* **A bare literal capacity**, and a bound reached through a factory,
  `pool_for(...)`, whose callee names no primitive.
* **A primitive from a module outside `CONCURRENCY_MODULES`**, a third party
  limiter among them, and a **submodule of a listed module reached through its
  parent's binding**: `import multiprocessing.pool` resolves and
  `import multiprocessing` then `multiprocessing.pool.ThreadPool(...)` does not.
  That tuple is an enumeration and is the weakest thing here; what it buys is that
  the enumeration is of **modules** and covers their submodules, where the arm it
  feeds is of names, so the two go stale on different days.
* **A handler declared outside `backend/routers/`.** `_route_modules` is that
  directory, so `main.py`'s API and auth fallbacks are out of this file's
  population and a bound inside one leaves every arm here green. They are
  registered with `@_fallback.api_route(...)`, which `_is_route_handler` does
  read: the predicate covers them and this population does not, so widening the
  predicate is not what would bring them in. It is also not this file's to widen:
  it has one home, in `tests/test_house_rules.py`, and a copy here would be the
  second decision about what a route handler is. What keeps that predicate from
  quietly narrowing is one arm of
  `test_house_rules.py::TestTheRouteHandlerPopulationIsDerivedTwice`,
  `test_the_two_derivations_name_the_same_handlers`, which puts it against the
  routes the app registers; the other arms there read one derivation.
* **`--workers` beyond the `CMD` line**, which is now asserted below rather than
  stated here. The bound is process wide, which is pod wide only while the image
  runs one worker, and `WEB_CONCURRENCY` in the environment is outside any test's
  reach.

## Both members are covered now, and neither is covered by name

`backfill_from_identifiers` and `backfill_covers` are the two handlers this rule
was written for, and each is asserted to be **in the population** rather than
exempted from it, so a matcher that stopped seeing one reports that handler by
name instead of reporting no offender.

The cover route's bound is `covers.FETCHES_AT_ONCE`, built beside
`covers.MAX_CONCURRENT_FETCHES`, which puts it out of the arming arm's reach as
well: that arm's subject is `routers/books.py`, so a bound another module holds is
neither a second candidate for it to choose between nor anything it can see. What
holds the cover route's own bound and its deadline is
`tests/routers/test_books_cover_backfill.py`, and arm one here is what keeps the
construction out of the handler.
"""

import ast
import asyncio
import importlib
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Final

from routers import books
from tests.test_house_rules import (
    BACKEND,
    _declared_route_handlers,
    _is_route_handler,
    _python_sources,
)

#: Where a concurrency primitive can come from, each entry standing for itself
#: **and its submodules**, so `multiprocessing.pool` is inside `multiprocessing`
#: as a reader of this tuple would assume. An enumeration, and the guard's weakest
#: part; see the module docstring.
CONCURRENCY_MODULES: Final = (
    "asyncio",
    "threading",
    "concurrent.futures",
    "multiprocessing",
    "queue",
    "anyio",
)

#: The primitives a route handler may not construct, by the name the callee
#: resolves to and by the name written at the call site. Pinned by
#: `test_the_primitive_set_is_every_one_this_backend_constructs` against a second
#: derivation, so it cannot quietly fall short of the tree.
PRIMITIVES: Final = frozenset({"Semaphore", "ThreadPoolExecutor"})

#: Classes of a concurrency module this backend constructs that **ration
#: nothing**, name to the reason it is not a bound. They satisfy the pin below
#: without arming the rule above, where adding one to `PRIMITIVES` instead would
#: make arm one refuse a per request one in a handler, which is legitimate.
#:
#: **`Lock` was in `PRIMITIVES` for one round and that was a false refusal.** A
#: lock has no capacity to hand out: it orders one holder's own tasks, so a per
#: request one rations nothing the pod owns and is the right shape rather than the
#: defect this file is about. `z3950.Association.__init__` builds exactly that,
#: one lock per association serialising that association's own single worker
#: executor, and a handler needing the same ordering would have been refused.
#: Found by a design seat, which is the half an author does not look for: an
#: author hunts for what slips past a guard, not for what it stops wrongly.
#:
#: **What this row costs**: a `Lock` used as a pod wide bound inside a handler now
#: passes arm one. Nothing in the tree does that, and it would be a bound of one,
#: which `metadata._HARDER_AT_ONCE` spells as a semaphore for the reason its own
#: comment gives.
EXCLUDED: Final[dict[str, str]] = {
    "Lock": (
        "a lock has no capacity: it orders one holder's own tasks rather than "
        "rationing anything the pod owns, so a per request one is correct"
    ),
}

def _route_modules() -> list[Path]:
    """Every module of the route layer, from the directory rather than a list.

    One `glob` of one directory and deliberately not a recursion: the shared
    walks in `tests/test_house_rules.py` are what may recurse a tree of Python
    here, and the route layer is flat. A router in a subdirectory would be out
    of this population, which is the cost of not writing a second walk.
    """
    routers = BACKEND / "routers"
    return sorted(path for path in _python_sources() if path.parent == routers)


def _terminal_name(callee: ast.expr) -> str | None:
    """The last name in a callee, `asyncio.Semaphore` and `Semaphore` alike."""
    if isinstance(callee, ast.Attribute):
        return callee.attr
    return callee.id if isinstance(callee, ast.Name) else None


def _is_concurrency_module(name: str) -> bool:
    """A listed module, or a submodule of one.

    **A prefix and not the first component.** `concurrent.futures` is listed and
    `concurrent` is a member of nothing, so a rule reading `name.split(".")[0]`
    would drop the very entry this guard was written for while admitting
    `multiprocessing.pool`. A prefix keeps both.
    """
    return any(name == one or name.startswith(f"{one}.") for one in CONCURRENCY_MODULES)


def _dotted(callee: ast.expr) -> str | None:
    """`a.b.c` for a callee that is names all the way down, else `None`.

    The whole chain, because a version asking for `Attribute(value=Name)` sees
    `asyncio.Semaphore` and not `multiprocessing.pool.ThreadPool`, whose own
    prefix is an `Attribute`.
    """
    parts: list[str] = []
    node = callee
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _constructed(
    node: ast.Call, imported: dict[str, tuple[str, str]]
) -> tuple[str, str] | None:
    """`(module, attribute)` for a call on a concurrency import, else `None`."""
    callee = node.func
    if isinstance(callee, ast.Name):
        return imported.get(callee.id)
    dotted = _dotted(callee)
    if dotted is None:
        return None
    prefix, _, attribute = dotted.rpartition(".")
    where = imported.get(f"{prefix}.")
    return (where[0], attribute) if where else None


def _constructions(
    tree: ast.AST, names: frozenset[str], imported: dict[str, tuple[str, str]]
) -> list[tuple[str, int]]:
    """Every call in this tree constructing one of `names`, under either spelling.

    A **call**, so a mention that is not a construction is ignored: an
    annotation, an `isinstance` argument, a module level alias.

    **What the callee resolves to and what is written at the call site, joined.**
    The resolved name is what catches `from asyncio import Semaphore as Gate`.
    The written name is what keeps the resolution from being weaker than the rule
    it replaced: `from asyncio import Queue as Semaphore` resolves to a name this
    set does not hold, and dropping the written name would make it acceptable.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        where = _constructed(node, imported)
        for name in (where[1] if where is not None else None, _terminal_name(node.func)):
            if name is not None and name in names:
                found.append((name, node.lineno))
                break
    return found


def _concurrency_classes(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Local name to `(module, attribute)` for each concurrency import in a tree.

    Both spellings, because which one a module reaches for says nothing about
    what it builds: `import asyncio` then `asyncio.Semaphore`, and
    `from concurrent.futures import ThreadPoolExecutor` then the bare name. A
    submodule counts as its parent, so `import multiprocessing.pool` is keyed on
    the prefix a reference to it actually carries.
    """
    found: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {
                f"{alias.asname or alias.name}.": (alias.name, "")
                for alias in node.names
                if _is_concurrency_module(alias.name)
            }
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and _is_concurrency_module(node.module)
        ):
            found |= {
                alias.asname or alias.name: (node.module, alias.name)
                for alias in node.names
            }
    return found


def _concurrency_module(name: str) -> object | None:
    """The imported module, or `None` where this machine has none of that name.

    Imported by name rather than looked up in a dict keyed on
    `CONCURRENCY_MODULES`, because a submodule resolves to a name that tuple does
    not hold: `multiprocessing.pool` is inside `multiprocessing` and is its own
    module. `find_spec` raises rather than answering for a missing parent, which
    is why the guard is a `try` and not an `is None`.
    """
    if not _is_concurrency_module(name):
        return None
    try:
        if importlib.util.find_spec(name) is None:
            return None
    except (ImportError, ValueError):
        return None
    return importlib.import_module(name)


def _is_a_class_of(module: str, attribute: str) -> bool:
    """Whether `module.attribute` is a class here, decided at runtime.

    Classhood at runtime and not from a list, so a **function** of a concurrency
    module drops out on its own: `asyncio.gather`, `asyncio.to_thread` and
    `asyncio.timeout` are calls on those modules and none of them is a bound.
    """
    found = _concurrency_module(module)
    return found is not None and inspect.isclass(getattr(found, attribute, None))


def _sized_from(path: Path, name: str) -> ast.Call | None:
    """The call a module level `name = Callee(arg)` is built by, or `None`.

    **The call rather than its text.** Comparing `ast.unparse(value.func)` to one
    spelling refused `asyncio.BoundedSemaphore`, which is a strictly safer bound
    at the same site, so the caller decides what the callee has to resolve to and
    this returns the node.

    **Read off the module's own source, never off `Semaphore._value`.** That
    attribute is private and it is *mutable*: a test that contended the bound
    leaves it decremented, so an arm reading it would fail under
    `--dist loadfile` for a reason with nothing to do with the rule. Reading the
    source also catches `asyncio.Semaphore(6)`, a literal that would drift from
    the constant in silence.
    """
    for node in ast.parse(path.read_text()).body:
        # **Both kinds, because the annotated one is the kind this tree writes.**
        # `AnnAssign` carries `target` and `Assign` carries `targets`, so a
        # version reading one of them is a rule about half its own corpus:
        # `_BACKFILL_LOOKUPS_AT_ONCE: Final = ...` is the first and a bare
        # `x = asyncio.Semaphore(6)` is the second.
        if isinstance(node, ast.AnnAssign):
            targets: list[ast.expr] = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            continue
        if not any(isinstance(one, ast.Name) and one.id == name for one in targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and value.args:
            return value
    return None


def _module_level_bounds(module: ModuleType) -> dict[str, object]:
    """Every module level attribute of `module` that is an instance of a
    concurrency module's class.

    **Derived, where the arming arm below named its subject twice.** Renaming
    `_BACKFILL_LOOKUPS_AT_ONCE` and every use of it is a legitimate edit and it
    reddened that arm in three places, one of them an `AttributeError` rather than
    a message. Asked as a property, a consistent rename passes and a deletion says
    the bound went missing.

    Instance rather than annotation, because what is wanted is the object the
    module actually holds; `type(asyncio.Semaphore()).__module__` is
    `asyncio.locks`, which is why `_is_concurrency_module` matches on a prefix.
    """
    return {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("__")
        and _is_concurrency_module(type(value).__module__)
    }


def _used_in(tree: ast.Module, name: str) -> tuple[bool, bool]:
    """Whether this module acquires and releases `name`. `(acquired, released)`.

    **The subject is the module, and the first version's was one named handler.**
    That version asked whether `backfill_from_identifiers` mentioned the bound,
    which made the single change `IDENTIFIER_BACKFILL_DEADLINE_SECONDS`' own
    comment names as its deletion condition, moving the fan out out of the
    request, red in three asserts of one arm. A diff that prices its own stated
    next step at three reds is a diff that will not be taken. Moving the fan out
    into a module level helper, or into a background job with the route left as
    its door, now passes; taking the whole route out takes this arm with it, which
    is the sitting where the constant goes too.

    **Both directions of the move, said plainly.** What the handler subject
    refused and this accepts: a bound acquired somewhere in this module other than
    by the backfill. `_BACKFILL_LOOKUPS_AT_ONCE` is module private and named for
    one route, so that would be its own defect, and the six arms in
    `test_books_identifier_backfill.py` are what hold the wiring. What this
    refuses and the handler subject accepted: a bare mention. A name annotated,
    logged or passed somewhere and never acquired satisfied that version and does
    not satisfy this one, so the release is now held as well as the acquire.

    **`async with name:` counts as both**, because that is what
    `_ContextManagerMixin` is. Refusing it would make this arm encode where the
    deadline sits, which nothing static can hold and which this module's docstring
    says it does not.
    """
    acquired = released = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncWith) and any(
            isinstance(item.context_expr, ast.Name) and item.context_expr.id == name
            for item in node.items
        ):
            acquired = released = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        ):
            if node.func.attr == "acquire":
                acquired = True
            elif node.func.attr == "release":
                released = True
    return acquired, released


def _the_bound(module: ModuleType) -> tuple[str, object]:
    """This module's one concurrency bound: the name it is held under, and it.

    **Selected by being acquired and released, not by being an instance.** Being an
    instance does not tell a bound from anything else a concurrency module exports,
    which is exactly the distinction `EXCLUDED` exists to make three hundred lines
    above: a module level `asyncio.Lock` beside the bound would redden this arm
    while that dict's own row argues a lock rations nothing. **A guard that prices
    its own named next step is the failure `_used_in` was rewritten to remove**, one
    function earlier in this file, and it had come back here: the cover backfill's
    executor was the step, and this arm counted it.

    **It landed in `covers.py` instead, so this selection was never exercised by
    it.** A `ThreadPoolExecutor` is neither acquired nor released whatever module
    holds it, so the selection would have absorbed the hoist either way; what still
    argues for it is the `Lock` case above, which is live in this tree.

    **The cost, stated rather than discovered**: a second module level bound that
    nothing acquires now passes, where counting instances caught it. What that buys
    is that neither edit above has to fight this arm to land.
    """
    tree = ast.parse(Path(module.__file__ or "").read_text())
    every = _module_level_bounds(module)
    held = {
        name: value
        for name, value in every.items()
        if _used_in(tree, name) == (True, True)
    }
    assert len(held) == 1, (
        "this arm's subject is the one module level concurrency object this module "
        f"acquires and releases, and it found {sorted(held)} among {sorted(every)}. "
        "None means the bound went missing, or that nothing acquires and releases "
        "it, which every other arm here is green on; a second means this arm has "
        "to say which of them it is about"
    )
    return next(iter(held.items()))


def _built_to(module: ModuleType, name: str) -> int:
    """The number of slots this module's own source builds `name` to.

    **The size the bound is built to, not the constant a reader expects it to be
    built from**, and that gap is how the defect this whole guard exists to stop
    walked back in through it. `asyncio.Semaphore(MAX_IDENTIFIER_BACKFILL)` is
    fifty slots against a pod priced for sixteen with a search already holding
    eight; it is one identifier away from the right expression, and it was green on
    every arm in this file **and** on the arm that read
    `IDENTIFIER_BACKFILL_CONCURRENCY`, because nothing joined the two.

    **Read off the source and never off `Semaphore._value`.** That attribute is
    private and it is mutable: a test that contended the bound leaves it
    decremented, so an arm reading it fails under `--dist loadfile` for a reason
    with nothing to do with the rule.

    **Evaluated rather than matched**, in the module's own namespace, because the
    expression is open: the constant, a rename of it, `min(CONSTANT, 16)` and a
    settings lookup all have to answer, and a matcher over the spellings a size can
    take is the enumeration this repository keeps paying for.
    """
    built_by = _sized_from(Path(module.__file__ or ""), name)
    assert built_by is not None, (
        f"{name} is not built by a module level call with a positional "
        "argument. A keyword sizing, which the signature itself names, "
        "reads as absent here rather than as unread"
    )
    expression = ast.unparse(built_by.args[0])
    try:
        size = eval(expression, vars(module))
    except Exception as exc:
        raise AssertionError(
            f"the size {name} is built to cannot be read in "
            f"{module.__name__}: {expression!r} raised {exc!r}"
        ) from exc
    assert isinstance(size, int), (
        f"{name} is built to {size!r}, which is not a number of slots"
    )
    return size


class TestEveryConcurrencyBoundIsBuiltOnceForThePodAndNotPerRequest:
    def test_no_route_handler_constructs_a_concurrency_primitive(self) -> None:
        offenders: list[str] = []
        examined: set[tuple[str, str]] = set()

        for path in _route_modules():
            tree = ast.parse(path.read_text())
            imported = _concurrency_classes(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not _is_route_handler(node):
                    continue
                examined.add((str(path.relative_to(BACKEND)), node.name))
                for name, line in _constructions(node, PRIMITIVES, imported):
                    offenders.append(f"{path.name}:{line} {node.name} builds a {name}")

        # **The subjects by name, and the pair is not two examples.** One is
        # `async def` and one is `def`, so a matcher narrowed to either kind of
        # function loses one of them: that is why these two are the right subjects
        # and not simply the two the rule was written for.
        for subject in (
            ("routers/books.py", "backfill_from_identifiers"),
            ("routers/books.py", "backfill_covers"),
        ):
            assert subject in examined, (
                f"{subject} left the population, so this rule stopped covering the "
                f"handler it was written for, or was renamed, in which case update "
                f"this subject: {len(examined)} handlers examined"
            )

        # **The population, against the shared one rather than against a floor.**
        # The floors this replaces were `modules >= 12` against 13 and
        # `handlers >= 100` against 140, so one router module and forty handlers
        # could leave unnoticed where the mutation that raised this cost nineteen.
        # This equality is red on any partial loss.
        #
        # **It holds the walk and the traversal here, never the predicate**, which
        # both sides share: `_is_route_handler` cannot disagree with itself.
        # `tests/test_house_rules.py::TestTheRouteHandlerPopulationIsDerivedTwice`
        # is what holds that predicate, against the routes the app registers.
        layer = {str(path.relative_to(BACKEND)) for path in _route_modules()}
        assert examined == {key for key in _declared_route_handlers() if key[0] in layer}, (
            "the handlers this examined are not the route layer's share of the "
            "shared population, so this file's own walk of that directory, or its "
            f"traversal of a module, has lost something: {len(examined)} examined"
        )
        assert offenders == [], (
            "a bound built inside a handler is built once per call, and every "
            f"ceiling these defend belongs to one pod: {offenders}"
        )

    def test_the_primitive_set_is_every_one_this_backend_constructs(self) -> None:
        """The pin on `PRIMITIVES`, derived from where a class came from.

        The arm above matches a **name**. This one asks which classes of a
        concurrency module are constructed anywhere in this backend, deciding
        classhood at runtime with `inspect.isclass`, so a function of one of
        those modules drops out with no list: `asyncio.gather`,
        `asyncio.to_thread` and `asyncio.timeout` are calls on those modules and
        none of them is here.

        **One directional, and an equality here ratcheted the rule above down.**
        `built - EXCLUDED == PRIMITIVES` also demanded that `PRIMITIVES` be a
        **subset** of what the tree builds, so a refactor that stopped constructing
        a primitive reddened this arm and its message sent the reader to delete the
        row, which disarms arm one for that primitive across every handler with
        nothing going red.

        Measured 2026-09-26 by dropping each built name in turn: the tree ceasing
        to build `Semaphore`, or `ThreadPoolExecutor`, is red under the equality
        and green here. **`Lock` is not that case any more**, and the measurement
        that raised this finding was taken while `Lock` was still in `PRIMITIVES`:
        it sits in `EXCLUDED` now, which absorbs it on either side, so replacing
        the two `asyncio.Lock()` sites with `asyncio.Semaphore(1)` is green under
        both forms. The two fixes overlap on that one instance and not on the rule.

        So what is asserted is that nothing the tree builds is **unclassified**. A
        row in `PRIMITIVES` the tree has stopped building now leaves the rule
        **wider** than the corpus rather than weaker than it, which is the
        direction to fail in.

        **The two answers a red here has**, and the message says both: add the name
        to `PRIMITIVES`, which arms arm one for it, or give it an `EXCLUDED` row
        carrying the reason it rations nothing. `asyncio.Queue` and
        `threading.Thread` are the second shape. Widening `PRIMITIVES` for one of
        those would make arm one refuse a legitimate per request one.

        **`EXCLUDED` is driven by this tree**, which it was not for one round: it
        was empty and its subtraction was evidenced only by planting. `Lock` sits
        there now for the reason that row carries, so deleting the row is red here.
        """
        built: dict[str, list[str]] = {}

        for path in _python_sources():
            tree = ast.parse(path.read_text())
            imported = _concurrency_classes(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                found = _constructed(node, imported)
                if found is None:
                    continue
                if _is_a_class_of(*found):
                    built.setdefault(found[1], []).append(
                        f"{found[0]}.{found[1]} at {path.relative_to(BACKEND)}:{node.lineno}"
                    )

        unclassified = set(built) - set(EXCLUDED) - set(PRIMITIVES)
        assert unclassified == set(), (
            "every concurrency class this backend constructs has to be one arm "
            "one refuses or one `EXCLUDED` says rations nothing, or a bound "
            "nobody thought of passes. Add each of these to `PRIMITIVES`, or give "
            "it an `EXCLUDED` row carrying the reason it is not a bound: "
            f"{ {name: built[name] for name in sorted(unclassified)} }"
        )

    def test_the_identifier_backfill_holds_its_bound_at_module_level(self) -> None:
        """Arming, not behaviour: the walk above is green when nothing bounds
        anything at all, and it covers this one constant and no other.

        **Three things, and the third is why the first two are not enough.** The
        object is a semaphore; it is built at module level from the constant rather
        than from a literal; and this module acquires and releases it. With the
        acquire and the release deleted the first two stay green, and what caught
        that was six arms in another file.

        **The third is asked of the module and not of one handler**, for the reason
        `_used_in` gives: pinned to the handler it made moving the fan out out of
        the request, which is the deletion condition the deadline's own comment
        names, red in three asserts here. It is asked by `_the_bound`, which is
        also how the subject is **selected**, so a consistent rename of the bound
        passes and nothing here is keyed on its spelling.

        **What this arm does not hold is the number of slots.** It asks only that
        the size is read off a name; `asyncio.Semaphore(MAX_IDENTIFIER_BACKFILL)`
        satisfies that and is fifty slots against a pod priced for sixteen.
        `TestTheSlotsAreDerivedRatherThanChosen` in
        `test_books_identifier_backfill.py` bounds the figure, through `_built_to`,
        which reads what the bound is built to rather than what a reader expects it
        to be built from. Neither arm is sufficient alone and that is why both
        exist.

        **No comparison of any text, which for one round was true of the callee
        and false of its argument.** `asyncio.BoundedSemaphore` is a strictly
        safer bound at the same site and comparing the callee's text refused it,
        so the callee is resolved instead. The size was then compared against the
        literal string `IDENTIFIER_BACKFILL_CONCURRENCY`, which is the same defect
        one slot over: it refused renaming the constant and following it through,
        and reported a message about a literal that was not there. A factory is
        still refused either way, `_pool_for(...)` resolving to no concurrency
        module.

        **What is asked of the size is that it is read off a name**, which is what
        the message has always claimed. That admits the constant, a rename of it,
        `min(IDENTIFIER_BACKFILL_CONCURRENCY, 16)` and a settings lookup, and
        refuses `asyncio.Semaphore(6)` and any other expression of literals alone.

        **A proposed spelling was refused here with a measurement**: "no integer
        literal anywhere in the sizing expression" refuses
        `min(IDENTIFIER_BACKFILL_CONCURRENCY, 16)`, which is a **tightening** and
        was named in the same finding as a legitimate edit that must not go red. So
        the rule is the presence of a name and not the absence of a literal.

        **What this now accepts that the string comparison refused**: a name that
        is the wrong name. The **value** of the bound is not held here and is not
        claimed to be. `TestTheSlotsAreDerivedRatherThanChosen` in
        `test_books_identifier_backfill.py` holds it, which is where six raised to
        six hundred goes red; all four arms in this file are green on that.

        **This arm admits that swap and the module does not.** `built` then carries
        `BoundedSemaphore` where `PRIMITIVES` does not, so
        `test_the_primitive_set_is_every_one_this_backend_constructs` is red until
        the set gains a row. That is the right place to decide a new class is a
        bound, and it is one line rather than a fight with a text comparison.
        """
        source = Path(books.__file__)
        tree = ast.parse(source.read_text())

        name, bound = _the_bound(books)

        assert isinstance(bound, asyncio.Semaphore), (
            f"{name} is a {type(bound).__qualname__}, which hands out capacity "
            "differently from a semaphore"
        )

        built_by = _sized_from(source, name)
        assert built_by is not None, (
            f"{name} is not built by a module level call with a positional "
            "argument. A keyword sizing, which the signature itself names, "
            "reads as absent here rather than as unread"
        )
        where = _constructed(built_by, _concurrency_classes(tree))
        assert where is not None and _is_a_class_of(*where), (
            "the bound is not built by a class of a concurrency module: "
            f"{ast.unparse(built_by.func)}"
        )

        sizing = built_by.args[0]
        assert any(isinstance(node, ast.Name) for node in ast.walk(sizing)), (
            f"the size of {name} is written at its own site rather than read off a "
            "name, so nothing keeps it agreeing with whatever justifies it: "
            f"{ast.unparse(sizing)}"
        )


class TestTheImageRunsOneWorkerSoProcessWideIsPodWide:
    """Every bound in this file is process wide, and that is pod wide only here.

    **A worker flag turns one semaphore into N**, so the pod's response budget is
    exceeded N fold with nothing in the suite going red. The bound's own comment
    argues from a figure that belongs to the pod, so the assumption underneath it
    belongs in an arm rather than in a sentence: this file used to say a test could
    not read a `CMD` line, and three other test modules read the `Dockerfile`.

    **`WEB_CONCURRENCY` is the blind spot and is stated rather than bounded.**
    uvicorn honours it, it is set in a deployment rather than in this repository,
    and no test here can see one. So this arm holds the half that is in the tree.
    """

    def test_the_image_passes_no_worker_count_above_one(self) -> None:
        dockerfile = (BACKEND.parent / "Dockerfile").read_text()
        run = [
            line
            for line in dockerfile.splitlines()
            if line.upper().startswith(("CMD", "ENTRYPOINT"))
        ]

        assert run, "no CMD or ENTRYPOINT found, so this arm is measuring nothing"
        for line in run:
            assert "--workers" not in line and "-w " not in line, (
                "the image runs more than one worker, so every module level bound "
                "in the route layer is per worker rather than per pod and the "
                f"response budget is exceeded by that factor: {line.strip()}"
            )
