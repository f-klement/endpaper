"""Tests for backend/refusals.py: each route declares the refusals it can answer.

`refusals.declare` reads marks. These derive the same three statuses from the
code instead, by following what each route runs to the `HTTPException`s it
builds, and hold the two equal per route. A mark forgotten on a new raise and a
mark left on a function that no longer raises are each a route named here. A
raise the walk cannot reach from any route is named too, at the line that
builds it, so the walk's blind spots are red rather than trusted.
"""

import ast
import functools
import importlib
import inspect
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Self

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette.exceptions import HTTPException

import main
import refusals
from tests.test_errors import _constructions, _Module, _resolve, _status_of
from tests.test_house_rules import BACKEND, _python_sources

_REFUSAL_BODY = {"application/json": {"schema": {"$ref": "#/components/schemas/Refusal"}}}

type _Def = ast.FunctionDef | ast.AsyncFunctionDef


@cache
def _application_files() -> frozenset[Path]:
    return frozenset(path.resolve() for path in _python_sources())


@cache
def _parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function_of(target: Any) -> Any:
    """What runs when `target` is called, as far as a `def` can say.

    A class runs its own `__init__`; a callable instance runs its class's
    `__call__`, which is FastAPI's parameterised dependency; a
    `functools.partial` runs what it wraps.
    """
    if isinstance(target, functools.partial):
        target = target.func
    if inspect.isclass(target):
        return target.__dict__.get("__init__")
    if target is not None and not inspect.isroutine(target) and callable(target):
        return type(target).__call__
    return target


def _definition(target: Any) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, Any] | None:
    """The `def` node of an application function, and the module it is in.

    None for anything the walk does not read: a function outside the
    application corpus, such as FastAPI's own, and anything that is not a
    function at all.
    """
    target = _function_of(target)
    target = inspect.unwrap(getattr(target, "__func__", target)) if target else None
    code = getattr(target, "__code__", None)
    if code is None or Path(code.co_filename).resolve() not in _application_files():
        return None
    # `co_firstlineno` is the first decorator's line when there is one.
    for node in ast.walk(_parsed(Path(code.co_filename).resolve())):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and code.co_firstlineno in {
            node.lineno,
            *(decorator.lineno for decorator in node.decorator_list),
        }:
            return node, sys.modules[target.__module__]
    return None


def _bound(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, list[ast.expr]]:
    """What each plain local name in `function` is assigned, every time it is."""
    found: dict[str, list[ast.expr]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.setdefault(target.id, []).append(node.value)
        elif (
            isinstance(node, ast.AnnAssign | ast.NamedExpr)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            found.setdefault(node.target.id, []).append(node.value)
    return found


@dataclass(frozen=True)
class _Scope:
    """One function as the walk reads it: its module, what each local name is
    assigned, and, for a method, the class its own first argument is."""

    module: Any
    local: dict[str, list[ast.expr]]
    receivers: dict[str, type]


def _receivers(target: Any, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, type]:
    """`self` for a method defined on a module level class, or nothing."""
    function = _function_of(target)
    function = inspect.unwrap(getattr(function, "__func__", function))
    parts = function.__qualname__.split(".")
    owner = getattr(sys.modules[function.__module__], parts[0], None) if len(parts) == 2 else None
    first = [*node.args.posonlyargs, *node.args.args]
    if not inspect.isclass(owner) or not first:
        return {}
    if not inspect.isfunction(inspect.getattr_static(owner, parts[1], None)):
        return {}
    return {first[0].arg: owner}


def _builds(callee: Any) -> type | None:
    """The class whose instance calling `callee` returns, where the walk can
    name it: the class itself, or a classmethod of it annotated `Self`."""
    if inspect.isclass(callee):
        return callee
    owner = getattr(callee, "__self__", None)
    if not (inspect.ismethod(callee) and inspect.isclass(owner)):
        return None
    returned = inspect.signature(callee).return_annotation
    return owner if returned is Self or returned is owner else None


def _instance_of(expression: ast.expr, scope: _Scope, expanding: frozenset[str]) -> list[type]:
    """The classes an expression's value is an instance of, where the walk can
    name them: built in the expression, `self`, or a local assigned either."""
    if isinstance(expression, ast.Await):
        expression = expression.value
    if isinstance(expression, ast.Name):
        if expression.id in scope.receivers:
            return [scope.receivers[expression.id]]
        if expression.id in expanding:
            return []
        return [
            each
            for value in scope.local.get(expression.id, [])
            for each in _instance_of(value, scope, expanding | {expression.id})
        ]
    if isinstance(expression, ast.Call):
        return [
            built
            for callee in _callees(expression, scope, expanding)
            if (built := _builds(callee)) is not None
        ]
    return []


def _named(expression: ast.expr, scope: _Scope, expanding: frozenset[str]) -> list[Any]:
    """What an expression names: through the module's globals, or as a method
    of an instance whose class `_instance_of` can name.

    A subscripted name is every member of the table it names, so
    `_BULK_HANDLERS[payload.action]` is each handler the table holds: which
    one runs is decided by the request, so each can answer.
    """
    if isinstance(expression, ast.Subscript):
        table = _resolve(expression.value, scope.module)
        if isinstance(table, dict):
            return list(table.values())
        if isinstance(table, list | tuple):
            return list(table)
        return []
    found = _resolve(expression, scope.module)
    if found is not None:
        return [found]
    if isinstance(expression, ast.Attribute):
        return [
            method
            for owner in _instance_of(expression.value, scope, expanding)
            if (method := getattr(owner, expression.attr, None)) is not None
        ]
    return []


def _callees(call: ast.Call, scope: _Scope, expanding: frozenset[str] = frozenset()) -> list[Any]:
    """What a call can run: its callee as `_named` reads it, or, where the
    callee is a local name, what every assignment to that name reads as."""
    if isinstance(call.func, ast.Name) and call.func.id in scope.local:
        if call.func.id in expanding:
            return []
        return [
            each
            for value in scope.local[call.func.id]
            for each in _named(value, scope, expanding | {call.func.id})
        ]
    return _named(call.func, scope, expanding)


def _constructed(target: Any, seen: dict[_Def, str]) -> set[int]:
    """The statuses in `refusals.DECLARED` that `target` builds an exception for.

    Follows every call whose callee the walk can name to another application
    function, so a raise in a helper counts for each handler calling it: a
    name through the calling module's globals, a member of a subscripted table,
    a local assigned either, and a method of an instance built in the function
    by its class or by a classmethod annotated `Self`, or of `self`. Every
    `def` it reads lands in `seen`, which is what the reach arm below reads.

    **What it does not follow**: a method of an instance the function was
    handed or got back from anything else, a local assigned anything it cannot
    name, and a refusal **returned** as a response rather than raised. A raise
    reached only the first two ways is named by the reach arm at its line; the
    third builds no `HTTPException` at all and is outside both arms.
    """
    found = _definition(target)
    if found is None or found[0] in seen:
        return set()
    node, module = found
    seen[node] = Path(module.__file__).resolve().relative_to(BACKEND).as_posix()
    context = _Module(
        module=module,
        functions={
            each.name: each
            for each in _parsed(Path(module.__file__).resolve()).body
            if isinstance(each, ast.FunctionDef | ast.AsyncFunctionDef)
        },
    )
    scope = _Scope(module=module, local=_bound(node), receivers=_receivers(target, node))
    statuses: set[int] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        for callee in _callees(call, scope):
            # Starlette's class, so FastAPI's subclass and Starlette's own both count.
            if isinstance(callee, type) and issubclass(callee, HTTPException):
                built = _status_of(call, context)
                assert built is not None, f"{module.__name__}:{call.lineno} has a status nothing reads"
                statuses |= built & refusals.DECLARED
            else:
                statuses |= _constructed(callee, seen)
    return statuses


def _published() -> list[RouteContext]:
    """Every operation the document publishes, **as FastAPI serves it**.

    The served route, never the route as written: FastAPI builds what it serves
    and documents from the route plus what its `include_router` adds, a prefix
    and `dependencies=` among them, and the route as written holds neither. So
    a gate given at the include is walked here, where `refusals.declare`, which
    reads the route as written, cannot see it, and the route is named.
    """
    return [
        context
        for context in iter_route_contexts(main.app.routes)
        if isinstance(context.original_route, APIRoute) and context.include_in_schema
    ]


def _runs(dependant: Dependant) -> list[Any]:
    """Every callable in a route's dependency tree, the handler first."""
    return [dependant.call, *(each for sub in dependant.dependencies for each in _runs(sub))]


def _derived(context: RouteContext, seen: dict[_Def, str] | None = None) -> set[int]:
    seen = {} if seen is None else seen
    return {status for call in _runs(context.dependant) for status in _constructed(call, seen)}


def _declared(context: RouteContext) -> set[int]:
    """The three as the document declares them, read off one of the route's
    methods: FastAPI writes one `responses` into every method's operation."""
    method = next(iter(context.methods or {"GET"}))
    operation = main.app.openapi()["paths"][context.path_format][method.lower()]
    return {int(key) for key in operation["responses"] if key.isdigit()} & refusals.DECLARED


def _label(context: RouteContext) -> str:
    return f"{'/'.join(sorted(context.methods or ()))} {context.path_format}"


def _module_of(path: Path) -> Any:
    return importlib.import_module(path.relative_to(BACKEND).with_suffix("").as_posix().replace("/", "."))


def _read_by_every_route() -> dict[_Def, str]:
    seen: dict[_Def, str] = {}
    for context in _published():
        _derived(context, seen)
    return seen


class TestEveryRouteDeclaresTheRefusalsItsCodeBuilds:
    def test_the_walk_derives_each_of_the_three_somewhere(self) -> None:
        """The vacuity arm: a walk that stopped reading the code derives
        nothing, and every route then agrees with a document declaring
        nothing."""
        derived = set().union(*(_derived(context) for context in _published()))

        assert derived == refusals.DECLARED

    def test_each_route_declares_exactly_what_it_can_answer(self) -> None:
        disagreeing = [
            f"{_label(context)}: declares {sorted(_declared(context))}, "
            f"builds {sorted(_derived(context))}"
            for context in _published()
            if _declared(context) != _derived(context)
        ]

        assert disagreeing == [], (
            "Where a route builds a refusal it does not declare, mark the handler "
            "or the dependency the raise is reached from with `@refuses(...)`. A "
            "dependency given to `include_router(..., dependencies=...)` is served "
            "but not read by `refusals.declare`: give it to the included "
            "`APIRouter(...)` instead. Where a route declares one it does not "
            "build, the mark is stale, or the raise is reached through a call this "
            "walk does not follow, which "
            "`test_every_refusal_built_is_inside_some_routes_walk` names at its line "
            "only when no route reaches it in a way the walk follows; reach the raise "
            "in a way the walk follows, and keep the mark.\n  " + "\n  ".join(disagreeing)
        )

    def test_every_refusal_built_is_inside_some_routes_walk(self) -> None:
        """Coverage rather than spelling: a 401, 403 or 404 the walk never
        reads from any route is one no route can be held to declaring.

        Two are outside every walk, and rightly: `main.api_not_found` answers
        API paths no route matches and the SPA mount answers a missing file,
        so neither has an operation in the document to declare it on.
        """
        read = _read_by_every_route()
        for nowhere in (main.api_not_found, main.CachePolicyStaticFiles.get_response):
            found = _definition(nowhere)
            assert found is not None, nowhere
            read[found[0]] = "main.py"
        spans = [(where, node.lineno, node.end_lineno or node.lineno) for node, where in read.items()]
        unread = [
            f"{where}:{call.lineno} builds {sorted(statuses & refusals.DECLARED)}"
            for where, call, statuses in _constructions()
            if statuses and statuses & refusals.DECLARED
            if not any(
                path == where and first <= call.lineno <= last for path, first, last in spans
            )
        ]

        assert unread == [], (
            "No route's walk reads these, so no route is held to declaring what "
            "they build. Reach each from the route that answers it in a way the walk "
            "follows (`_constructed` lists them); a method of an instance the "
            "function was handed is one it does not. A raise no schema operation can "
            "answer, on a hidden route or in code no route runs, joins the two exempt "
            "beside `main.api_not_found` in this test, with its reason:\n  " + "\n  ".join(unread)
        )

    def test_every_mark_is_read_by_some_route(self) -> None:
        """A mark anywhere but a route's handler or a dependency it takes is
        read by nothing, so it declares nothing and looks as if it did."""
        roots = {
            found[0]
            for context in _published()
            for call in _runs(context.dependant)
            if (found := _definition(call)) is not None
        }
        dead = [
            f"{path.relative_to(BACKEND).as_posix()}:{node.lineno} {node.name}"
            for path in _python_sources()
            for node in ast.walk(_parsed(path.resolve()))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and any(
                isinstance(decorator, ast.Call)
                and _resolve(decorator.func, _module_of(path)) is refusals.refuses
                for decorator in node.decorator_list
            )
            and node not in roots
        ]

        assert dead == [], (
            "These carry `@refuses(...)` and are neither a handler nor a dependency "
            "of one, so the mark is read by nothing. Move it to the handler or "
            "dependency the raise is reached from:\n  " + "\n  ".join(dead)
        )

    def test_every_operation_asking_for_a_session_declares_401(self) -> None:
        """Read off the document alone, which says an operation wants a
        session through `security` whatever the marks say. An operation whose
        only session is optional, a scheme built with `auto_error=False`, is
        refused here though it cannot answer 401, and no mark satisfies both
        this and the equality above; none exists, and the first needs an
        exemption here."""
        unmarked = [
            f"{method.upper()} {path}"
            for path, methods in main.app.openapi()["paths"].items()
            for method, operation in methods.items()
            if operation.get("security") and "401" not in operation["responses"]
        ]

        assert unmarked == []


class TestEveryDeclaredRefusalIsTheRefusalBody:
    def test_each_carries_the_one_model_and_nothing_else(self) -> None:
        """`tests/test_declared_media_types.py` steps over every key at or
        above 400, so the content of these three is held here or nowhere."""
        wrong = [
            f"{method.upper()} {path} {key}"
            for path, methods in main.app.openapi()["paths"].items()
            for method, operation in methods.items()
            for key, response in operation["responses"].items()
            if key in {str(status) for status in refusals.DECLARED}
            and response.get("content") != _REFUSAL_BODY
        ]

        assert wrong == []

    def test_no_construction_of_the_three_passes_a_structured_detail(self) -> None:
        """`Refusal.detail` is a string, so one of the three built with a
        mapping or a list as its `detail` sends what the document says it
        does not. Read where the `detail` is written at the construction; one
        handed over in a `**` mapping is not read."""
        structured = [
            f"{where}:{call.lineno}"
            for where, call, statuses in _constructions()
            if statuses and statuses & refusals.DECLARED
            and _is_structured(_detail_of(call))
        ]

        assert structured == []


def _detail_of(call: ast.Call) -> ast.expr | None:
    given = next((keyword.value for keyword in call.keywords if keyword.arg == "detail"), None)
    return given if given is not None or len(call.args) < 2 else call.args[1]


def _is_structured(detail: ast.expr | None) -> bool:
    if isinstance(detail, ast.Dict | ast.List | ast.Tuple | ast.Set | ast.DictComp | ast.ListComp):
        return True
    return (
        isinstance(detail, ast.Call)
        and isinstance(detail.func, ast.Name)
        and detail.func.id in {"dict", "list", "tuple"}
    )


class TestRefuses:
    @pytest.mark.parametrize("statuses", [(409,), (404, 429), ()])
    def test_a_status_outside_the_three_is_refused_at_import(self, statuses: tuple[int, ...]) -> None:
        with pytest.raises(ValueError, match="refuses"):
            refusals.refuses(*statuses)
