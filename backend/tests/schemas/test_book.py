"""Tests for backend/schemas/book.py: the bounds a request body carries.

`BookMatch` carried seventeen fields, four bounded and thirteen not, under a
comment saying the bounds matched `BookCreate`'s. The comment was true of the
two fields it sat above and false of the rest, which is why nobody reading it
noticed: the sentence was locally correct.

Counted against `schemas/book.py` at 45b7b22 rather than taken from the ticket,
which said eleven: it had counted the strings, and `series_index` (a float) and
`suggested_tag_ids` (a list, bounded per entry and not per count) were open as
well. Both are covered here, and neither would be by a rule about strings.

So the guard here is deliberately **not** a list of fields and their expected
numbers. That is the same enumeration one model down, and it would have to be
extended by the person adding the next loose field. It asks three questions of
every request body in the application:

1. Does every field carry a ceiling at all? (`_unbounded`)
2. Does a field writing a `Book` column stay inside that column? (`_over_column`)
3. Do two request bodies writing one `Book` column agree about it?
   (`_disagreements`)

`BookMatch` was the only offender of the first, and it was one because it is a
**response** model that is also a request body. That is the shape to expect
next, so the scope is every model a route accepts rather than the two this
ticket compared.

**How a ceiling is detected.** Strings and numbers are probed by **executing**
the field's own validation against an oversized value, so a bound spelled as a
`pattern` counts exactly as much as one spelled as `max_length`, and a bound
this file has never heard of counts too.

A **container** has two sizes and needs both: a count, read off `max_length`
because pydantic has no other way to bound one, and an entry, which is asked
this same question recursively. So `list[str]` at `max_length=500` is
unbounded, and `list[RowIdField]` at `max_length=500` is not. A container that
declares no entry type at all is unbounded, because there is nothing to ask.

"Container" is `collections.abc.Collection` rather than a list of names, so
`set`, `frozenset`, `tuple` and `dict` are the same rule and the next one needs
no arm. `str` and `bytes` are `Collection`s too and are excluded: their size is
a length the probes measure directly.

This paragraph said the opposite until 2026-09-02, that a list is read off
`max_length` alone and that probing an element "is not possible generically",
which is what the recursion does. It survived two fix rounds because it is
prose beside code that had changed, which is the class of defect this whole
file exists to make mechanical.

**Blind spots, listed rather than left to be found.**

* A string bounded only by a `pattern` that admits arbitrarily long strings of
  a shape none of `_LONG_STRINGS` spells is reported bounded. The probes cover
  letters, digits, hyphens and a repeated pair.
* A field bounded only by a **model** validator (`@field_validator`) is
  reported unbounded, because the probe runs the annotation rather than the
  model. Nothing in the tree relies on one for a length.
* **Rules 2 and 3 read a *stated* bound, so a field bounded only by a
  `pattern` is invisible to both** even though rule 1 sees it. That is the
  honest shape of the limitation: not a corner about aliases, which is fixed,
  but that a ceiling nobody wrote as a number cannot be compared with one.
* **Rule 2 is string only, deliberately.** A numeric column states no width,
  so `Integer` and `Float` give a range nothing to exceed. Rule 3 does cover
  numbers, which is what stops the three bodies writing `series_index` from
  drifting apart.
* A renamed field is invisible to rules 2 and 3 unless `_COLUMN_FOR_FIELD`
  names it. `isbn13` is the only rename today and is named there. A new one
  would be bounded (rule 1) at a number nothing cross-checks.

**And two gaps that were listed here and are now checked instead**, because a
sentence saying a gap is empty stops being true the moment somebody fills it.
A route declared in `main.py` rather than in `routers/` is not walked, and
`test_the_routers_walk_reaches_every_body_model_the_app_does` proves that costs
no body model. **That same test is also what refuses partial discovery**, by
comparing this collector against the app's own route tree: this sentence used
to credit `test_every_router_module_contributes_routes`, which cannot do it,
because a collector that finds one module finds no empty ones.
"""

from __future__ import annotations

import importlib
import pkgutil
import typing
from collections.abc import Collection
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal

import pytest
from annotated_types import MaxLen
from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

import routers
from enums import ReadStatus
from google_books import CATEGORY_SEPARATOR
from models import CATEGORIES_MAX, CLASSIFICATION_NUMBER_MAX, Book

#: A caller-supplied field that carries no ceiling, and why that is right.
#:
#: One entry, and it is the same exemption `docs/decisions.md` records for the
#: row id rule. `BulkRequest.value` cannot be typed: which field it fills
#: depends on the verb, so a tag id, an ownership status, a shelf name and a
#: collection id all arrive here.
#:
#: **The reason is that no reader of it stores an unbounded value, not that
#: every reader range checks.** That distinction was bought by a critic seat,
#: which measured the seven verbs rather than the two the first version of this
#: comment named: `_bulk_set_location` refuses past 120 characters and
#: `_checked_collection` range checks against `MAX_ROW_ID`, while `_require_tag`
#: did neither. It called `int(str(value))` and handed the result to `db.get`,
#: where `10**19` raised `OverflowError` from the driver and answered **500**.
#: Nothing was stored and no bound was exceeded, so this file's rule was never
#: the one that catches it, but the sentence claiming "every handler bounds it
#: itself" was this repository's signature failure in miniature: correct about
#: the two fields it named and wrong about the class it covered.
#:
#: `_require_tag` range checks against `MAX_ROW_ID` since 2026-09-03 and
#: answers 404, which is what an unused id already got.
#: `tests/routers/test_books_bulk.py::TestATagIdPastTheDatabasesRangeIsRefused`
#: holds it, for both verbs that reach the helper. **Three** of the seven verbs
#: read this field as a row id and they reach **two** helpers, which is the
#: count to quote: reading the helpers as the verbs is how the sentence above
#: came to name two.
_UNBOUNDED_OK = frozenset({"BulkRequest.value"})

#: A body field whose name is not its column's name.
#:
#: `BookMatch` calls the ISBN `isbn13`, because a search row is one printing
#: among several rather than the one asked for. Without this, rules 2 and 3
#: cannot see that `BookCreate.isbn` and `BookMatch.isbn13` are the same
#: column.
_COLUMN_FOR_FIELD = {"isbn13": "isbn"}

#: Long values a bounded string field has to refuse. Several shapes, because a
#: `pattern` can bound the alphabet without bounding the length, and one probe
#: made of the wrong characters is refused for the wrong reason.
_LONG_STRINGS = ("a" * 100_001, "0" * 100_001, "-" * 100_001, "ab" * 50_000)


def _routes_by_module() -> dict[str, list[APIRoute]]:
    """Every route in the application, by the module that declares it.

    Through `routers` rather than through `main.app`, and that is not a
    preference: FastAPI wraps an included router in a private
    `_IncludedRouter` whose routes are not on `app.routes`, so walking the app
    reports **one** route and a rule over it would be vacuous while looking
    healthy. `APIRouter.routes` is public and holds what was registered.

    `walk_packages` rather than `iter_modules`, so a future `routers/<pkg>/`
    subpackage is discovered rather than silently contributing nothing.

    Keyed by module rather than flattened, because the count per module is what
    `test_every_router_module_contributes_routes` needs: both critic seats
    found, separately, that the earlier anti-vacuity check named three models
    that all live in `routers/books.py`, so restricting discovery to that one
    module left 22 of 31 body models unchecked with every assertion green.
    """
    found: dict[str, list[APIRoute]] = {}
    for info in pkgutil.walk_packages(routers.__path__, prefix="routers."):
        module = importlib.import_module(info.name)
        routes = [
            route
            for value in vars(module).values()
            if isinstance(value, APIRouter)
            for route in value.routes
            if isinstance(route, APIRoute)
        ]
        if any(isinstance(value, APIRouter) for value in vars(module).values()):
            found[info.name] = routes
    return found


def _api_routes() -> list[APIRoute]:
    """Every route in the application, flattened."""
    return [route for routes in _routes_by_module().values() for route in routes]


def _models_from(annotations: list[Any]) -> dict[str, type[BaseModel]]:
    """Every pydantic model reachable from these annotations, by name.

    Transitively through fields, because a body model may hold another one and
    a field on the inner model arrives in the same JSON.
    """
    found: dict[str, type[BaseModel]] = {}
    pending = list(annotations)
    while pending:
        candidate = pending.pop()
        pending.extend(typing.get_args(candidate))
        if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
            continue
        if candidate.__name__ in found:
            continue
        found[candidate.__name__] = candidate
        pending.extend(field.annotation for field in candidate.model_fields.values())
    return found


def _body_models() -> dict[str, type[BaseModel]]:
    """The models a route accepts as a request body."""
    return _models_from(
        [
            parameter.field_info.annotation
            for route in _api_routes()
            for parameter in route.dependant.body_params
        ]
    )


def _app_body_models() -> dict[str, type[BaseModel]]:
    """The same set, reached through the app instead of through the routers.

    A second derivation by a different route, which is the only thing that has
    ever caught a wrong number in this repository. It follows the private
    `original_router` that `_api_routes` exists to avoid, so it sees the three
    routes `main.py` declares itself and the routers walk cannot.

    Used by one test, which asserts the two sets are equal. That is what keeps
    "`main.py` declares no request body" a fact rather than a sentence: the day
    somebody declares one, the equality breaks and the blind spot announces
    itself instead of quietly becoming real.
    """
    from main import app

    def walk(router: Any) -> list[APIRoute]:
        found: list[APIRoute] = []
        children = list(getattr(router, "routes", ())) + list(
            getattr(getattr(router, "original_router", None), "routes", ())
        )
        for route in children:
            if isinstance(route, APIRoute):
                found.append(route)
            else:
                found.extend(walk(route))
        return found

    return _models_from(
        [
            parameter.field_info.annotation
            for route in walk(app)
            for parameter in route.dependant.body_params
        ]
    )


def _accepts(annotation: Any, metadata: list[Any], value: Any) -> bool:
    """Whether the field's own validation lets this value through.

    `Annotated` refuses a single argument, and a field with no constraints has
    exactly none, which is the case the whole rule is about. So the bare
    annotation is used when the metadata is empty rather than built into an
    `Annotated` of one.
    """
    subject = Annotated[(annotation, *metadata)] if metadata else annotation
    adapter: TypeAdapter[Any] = TypeAdapter(subject)
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    except TypeError:
        # **A constraint that cannot apply to the probe does not bound it.**
        # Pydantic raises a bare `TypeError`, not a `ValidationError`, for
        # `max_length` against an integer or `le` against a string, so on a
        # mixed union like `str | int` one of the two probes always hits it.
        # Unreachable until every kind started being checked rather than the
        # first matching one, and still not reachable by any field here
        # (`BulkRequest.value` is the only mixed union and carries no
        # constraints), which is exactly why it had to be found by attacking.
        #
        # `True` is both correct and the safe direction: "accepted" means the
        # kind is unbounded, so the field gets **reported**. Returning False
        # would call it bounded on the strength of an error.
        return True
    return True


def _peel(annotation: Any) -> Any:
    """An annotation with its `Annotated` wrappers removed."""
    while typing.get_origin(annotation) is Annotated:
        annotation = typing.get_args(annotation)[0]
    return annotation


def _union_parts(annotation: Any) -> tuple[Any, ...]:
    """A union's members, or the annotation itself. `Annotated` left on."""
    peeled = _peel(annotation)
    if typing.get_origin(peeled) is typing.Union:
        return typing.get_args(peeled)
    return (peeled,)


def _kinds(annotation: Any) -> set[Any]:
    """The kinds this annotation admits: a union's members, and nothing else.

    **A union is unwrapped and a generic is not**, and the difference is the
    whole helper. `str | None` is a string field, so its members are read.
    `list[int]` is a **list**, and reading its element type instead reports it
    as an int field: the first version of this did exactly that, so
    `suggested_tag_ids: list[RowIdField]` was probed as though it were one
    bounded integer and its missing count bound passed clean. It also skipped
    `collection_id: RowIdField | None` entirely, because an `Annotated`
    member's origin is `Annotated` rather than `int`.
    """
    annotation = _peel(annotation)
    origin = typing.get_origin(annotation)
    parts = typing.get_args(annotation) if origin is typing.Union else (annotation,)
    return {typing.get_origin(_peel(part)) or _peel(part) for part in parts}


def _constraints(field: Any) -> list[Any]:
    """Every constraint on the field, wherever pydantic left it.

    **Two places, and reading only the first is the hole both critic seats
    found separately.** Pydantic lifts an `Annotated` alias's constraints into
    `field.metadata` for `x: Alias`, and does **not** for `x: Alias | None`,
    where they stay on the union member. Every field on `BookMatch` is
    optional, and `RowIdField` shows the alias spelling is already house style,
    so the shape that escapes is the shape this model is made of. Measured:
    `publisher: Annotated[str, Field(max_length=9999)] | None` left
    `field.metadata` empty, so the stated ceiling read as absent and rules 2
    and 3 both went silent against a `String(255)` column.
    """
    found = list(field.metadata)
    for part in _union_parts(field.annotation):
        found.extend(getattr(part, "__metadata__", ()))

    # **One level down, because `Field(...)` is not a constraint.** The house
    # spelling wraps the real `MaxLen` inside a `FieldInfo` that carries its
    # own `metadata` list, so an alias written `Annotated[str, Field(
    # max_length=9999)]` hides it one deeper than `Annotated[str,
    # MaxLen(9999)]` does. The first version of this walk read the union and
    # stopped, which found the bare spelling and missed the one this
    # repository actually writes: an example is not a family.
    return [
        constraint
        for candidate in found
        for constraint in (candidate, *(getattr(candidate, "metadata", None) or ()))
    ]


def _stated_ceiling(field: Any) -> int | None:
    """The tightest `max_length` the field declares, or None.

    The tightest rather than the last, because two spellings can both be
    present and the one that actually refuses is the smaller.
    """
    stated = [
        constraint.max_length
        for constraint in _constraints(field)
        if getattr(constraint, "max_length", None) is not None
    ]
    return min(stated) if stated else None


def _stated_range(field: Any) -> str | None:
    """The numeric bounds the field declares, or None if it declares neither.

    **The operator is part of the value**, so `le=1000` and `lt=1000` are two
    different ceilings rather than one. Collapsing them to the number reports
    two models as agreeing when the second refuses a value the first accepts.
    A critic seat found the collapse; no field pair spells it that way today,
    which is why it had to be reasoned about rather than observed.
    """
    # **The tightest per operator, not the last**, which is `_stated_ceiling`'s
    # rule fifteen lines up applied to its neighbour. `_constraints` yields
    # `field.metadata` before the union member's, so an alias always arrived
    # last and overwrote the `Field` beside it. Measured: `Annotated[int,
    # Field(ge=0, le=10**9)] | None` declared `le=10` on the field really
    # refuses 1000 and was reported as `le=1000000000`, so two bodies both
    # enforcing `le=1000` were reported as disagreeing. A false positive, and
    # by the same mechanism a real drift the looser spelling would hide.
    tightest = {"ge": max, "gt": max, "le": min, "lt": min}
    parts: dict[str, Any] = {}
    for constraint in _constraints(field):
        for name, keep in tightest.items():
            value = getattr(constraint, name, None)
            if value is None:
                continue
            parts[name] = value if name not in parts else keep(parts[name], value)
    if not parts:
        return None
    return " ".join(f"{name}={parts[name]}" for name in sorted(parts))


#: Kinds a caller cannot make large, named because there is nothing structural
#: to key on: a `bool` is small by being a `bool`.
#:
#: **The last enumeration in this file, so it is the one with a test naming its
#: members.** `test_every_kind_reaching_the_sizeless_tuple_is_named_in_it`
#: recomputes which fields land here and refuses any whose kind is not listed,
#: which is a property rather than a count and so cannot go stale as models are
#: added.
#:
#: Recounted 2026-09-02, after `Collection` and `Literal` moved fields off this
#: arm: **35** fields over the 31 body models, all bool, enum, `date`,
#: `datetime`, nested model or `None`. The recount mattered because the same
#: figure was first measured before those two changes, and a number carried
#: across the change that invalidates it is this repository's commonest defect.
_SIZELESS = (bool, type(None), date, datetime, Enum, BaseModel)


def _element_types(annotation: Any) -> tuple[Any, ...]:
    """What a container declares its entries to be, or () if it declares none.

    The `()` case is the whole reason this is a function. `typing.get_args` of
    a bare `list` is empty, and an `all()` over nothing is True, so an
    unparameterised container was **vacuously bounded** by the arm added to
    stop unbounded containers. Both critic seats found it separately and both
    measured the same 50,000,500 characters that
    `test_a_list_losing_its_entry_bound` quotes as the defect it exists to
    catch. So the caller checks this is non-empty rather than letting `all()`
    answer for a container with no element type.
    """
    return tuple(
        argument
        # **Container members only.** `get_args` of a `Literal` returns its
        # *values*, so `Literal["a", "b"] | list[X]` handed "a" and "b" to a
        # rule that asks whether an annotation is bounded and got a report for
        # a field that is fine. No such field exists here.
        for part in _union_parts(annotation)
        if _is_container(typing.get_origin(_peel(part)) or _peel(part))
        for argument in typing.get_args(_peel(part))
        if argument is not Ellipsis
    )


def _is_container(kind: Any) -> bool:
    """A kind whose size the caller chooses.

    **`Collection`, not a list of container names.** The arm this replaces
    named `list` and let `set[int]`, `tuple[int, ...]`, `frozenset[int]` and
    `dict[str, str]` fall through to the sizeless tuple, where they were
    refused for the wrong reason: safe today, and leaving the next person a
    failure with no arm to fix and an escape hatch to reach for. Keying on the
    abstract base is the structural form of the same question, and it needs no
    further arm for the next container type.

    `str` and `bytes` are `Collection`s too and are excluded: their size is a
    length the probes measure directly.
    """
    return (
        isinstance(kind, type)
        and issubclass(kind, Collection)
        and not issubclass(kind, (str, bytes))
    )


def _is_bounded(field: Any) -> bool:
    """Whether a caller-supplied value for this field has a ceiling."""
    return _annotation_is_bounded(field.annotation, _constraints(field), field)


def _kind_is_bounded(
    kind: Any, annotation: Any, constraints: list[Any], field: Any
) -> bool:
    """Whether one kind an annotation admits can be made large."""
    if kind in (str, bytes):
        return not any(_accepts(annotation, constraints, p) for p in _LONG_STRINGS)
    if kind in (int, float):
        return not _accepts(annotation, constraints, 10**30)
    if _is_container(kind):
        if field is None or _stated_ceiling(field) is None:
            return False
        elements = _element_types(annotation)
        return bool(elements) and all(
            _annotation_is_bounded(element, [], None) for element in elements
        )
    if kind is Literal or typing.get_origin(kind) is Literal:
        return True
    return isinstance(kind, type) and issubclass(kind, _SIZELESS)


def _annotation_is_bounded(
    annotation: Any, constraints: list[Any], field: Any
) -> bool:
    """The rule itself, on an annotation rather than on a field.

    Separated so the container arm can ask it about an **element**, which is
    the other half of a container's size: `max_length` bounds the number of
    entries and says nothing about any one of them, so `list[str]` at
    `max_length=500` accepted 50,000,500 characters, measured. That is the
    inverse of the `suggested_tag_ids` defect this file was written from, where
    the entries were bounded and the count was not.

    **Every kind, not the first one that matches.** The arm order used to
    decide: `str in kinds` answered for the whole annotation, so a
    `str | list[str]` was judged on its string half and its list half was never
    looked at. No such field exists here, and the ordering was the same shape
    as the two defects above, which is reason enough not to keep it.
    """
    kinds = _kinds(annotation)
    return bool(kinds) and all(
        _kind_is_bounded(kind, annotation, constraints, field) for kind in kinds
    )


def _unbounded(models: dict[str, type[BaseModel]]) -> list[str]:
    """Fields a caller can make arbitrarily large."""
    return sorted(
        f"{name}.{field_name}"
        for name, model in models.items()
        for field_name, field in model.model_fields.items()
        if f"{name}.{field_name}" not in _UNBOUNDED_OK and not _is_bounded(field)
    )


def _column_widths() -> dict[str, int]:
    """Every `Book` column that states a width.

    Read off the table rather than written down, because a width copied here
    is the same fact stored twice and would agree with the schema forever
    while both drifted away from the database. `Text` states none and is
    absent, which is why `description` and `categories` are covered by the
    agreement rule and not by the column rule.
    """
    widths: dict[str, int] = {}
    for column in Book.__table__.columns:
        length = getattr(column.type, "length", None)
        if isinstance(length, int):
            widths[column.name] = length
    return widths


def _column_fields(
    models: dict[str, type[BaseModel]],
) -> list[tuple[str, str, str, int | None]]:
    """(model, field, column, stated ceiling) for every string field on a
    request body that writes a `Book` column."""
    rows: list[tuple[str, str, str, int | None]] = []
    for name, model in sorted(models.items()):
        for field_name, field in model.model_fields.items():
            if str not in _kinds(field.annotation):
                continue
            column = _COLUMN_FOR_FIELD.get(field_name, field_name)
            if column not in {c.name for c in Book.__table__.columns}:
                continue
            rows.append((name, field_name, column, _stated_ceiling(field)))
    return rows


def _column_numbers(
    models: dict[str, type[BaseModel]],
) -> list[tuple[str, str, str, str | None]]:
    """The same, for numeric fields, and only the agreement rule reads it.

    Not `_over_column`, because a numeric column states no width: `Integer` and
    `Float` have no `length`, so there is nothing for a range to exceed. But
    two bodies **can** disagree about a range, and one of them is this
    ticket's sharpest field: `series_index` is written by three request bodies
    and its ceiling is the difference between a stored 1000 and a stored 1e9.
    A string only agreement rule cannot see them drift apart.
    """
    rows: list[tuple[str, str, str, str | None]] = []
    for name, model in sorted(models.items()):
        for field_name, field in model.model_fields.items():
            kinds = _kinds(field.annotation)
            if not kinds & {int, float} or bool in kinds:
                continue
            # A field that is also a string belongs to the ceiling rule, and
            # counting it in both makes one model disagree with itself: a
            # critic seat measured `year: (None, 2200) on C.year, 4 on C.year`
            # on a synthetic `str | int`. No Book column is both today.
            if str in kinds:
                continue
            column = _COLUMN_FOR_FIELD.get(field_name, field_name)
            if column not in {c.name for c in Book.__table__.columns}:
                continue
            rows.append((name, field_name, column, _stated_range(field)))
    return rows


def _over_column(models: dict[str, type[BaseModel]]) -> list[str]:
    """Fields stating a ceiling their column cannot hold."""
    widths = _column_widths()
    return sorted(
        f"{name}.{field_name} says {stated}, {column} is String({widths[column]})"
        for name, field_name, column, stated in _column_fields(models)
        if column in widths and stated is not None and stated > widths[column]
    )


def _disagreements(models: dict[str, type[BaseModel]]) -> list[str]:
    """Columns two request bodies bound differently.

    Strings by their ceiling and numbers by their range, because a column is
    one or the other and both can drift. A body that states **no** bound is
    invisible here on purpose: there is nothing to disagree with, and that
    case belongs to `_unbounded`, which is the rule that actually caught this
    ticket's thirteen fields.
    """
    stated: dict[str, dict[Any, list[str]]] = {}
    rows: list[tuple[str, str, str, Any]] = [
        *_column_fields(models),
        *_column_numbers(models),
    ]
    for name, field_name, column, bound in rows:
        if bound is None:
            continue
        stated.setdefault(column, {}).setdefault(bound, []).append(
            f"{name}.{field_name}"
        )

    return sorted(
        f"{column}: "
        + ", ".join(
            f"{value} on {' and '.join(sorted(fields))}"
            for value, fields in sorted(by_value.items(), key=repr)
        )
        for column, by_value in stated.items()
        if len(by_value) > 1
    )


@pytest.fixture(scope="module")
def bodies() -> dict[str, type[BaseModel]]:
    return _body_models()


class TestEveryFieldARequestBodyCarriesIsBounded:
    """The rule, over the application as it stands."""

    def test_the_collector_reaches_the_enrichment_apply_body(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """A rule over an empty set passes, and looks exactly like a rule that
        holds. The collector walks FastAPI internals, so this names what it has
        to have found: the route this ticket came from, and the two models it
        compared."""
        assert any(
            route.path.endswith("/enrich/apply") for route in _api_routes()
        ), "the route walker no longer finds POST /{book_id}/enrich/apply"
        assert {"BookCreate", "BookMatch", "BulkRequest"} <= set(bodies)

    def test_every_router_module_contributes_routes(self) -> None:
        """A floor on discovery, because the check above is satisfiable by one
        module.

        Both critic seats measured the same evasion separately: restrict
        discovery to `routers/books.py` and `_body_models` falls from 31 to 22,
        while every named model above is still present and all three rules
        still report nothing. Nine models go unchecked that way, two of them
        the unauthenticated bodies.

        **This is not the test that catches that, and saying so is the point.**
        A collector that discovers one module discovers no empty ones, so this
        one passes on the crippled collector; what fails is
        `test_the_routers_walk_reaches_every_body_model_the_app_does`, which is
        the floor. A seat measured that after an earlier version of this
        docstring claimed the floor for itself, which would have let a later
        reader delete the app side equality as a duplicate and keep a promise
        nothing kept. What this test does is narrower and still worth having: a
        module that was discovered and contributed nothing is an import that
        half worked.
        """
        empty = sorted(
            name for name, routes in _routes_by_module().items() if not routes
        )
        assert empty == [], f"these router modules contributed no routes: {empty}"

    def test_the_routers_walk_reaches_every_body_model_the_app_does(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """The collector's one structural gap, checked instead of asserted.

        `_api_routes` walks `routers/` and so cannot see a route `main.py`
        declares itself. Three do, and none takes a body, which is the whole
        reason the gap is harmless: this is what keeps that true. It also
        catches the collector going quiet from the other side, since a walk
        that found nothing could not match one that found everything.
        """
        assert set(_app_body_models()) == set(bodies)

    def test_every_field_a_request_body_carries_has_a_ceiling(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        assert _unbounded(bodies) == [], (
            "These request-body fields accept a value of any size, so a member "
            "chooses how much work the server does and how large the row is:\n  "
            + "\n  ".join(_unbounded(bodies))
            + "\nBound the field, or add it to _UNBOUNDED_OK with the handler "
            "that bounds it instead."
        )

    def test_no_field_states_a_ceiling_wider_than_its_column(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        assert _over_column(bodies) == []

    def test_two_request_bodies_writing_one_column_agree_about_it(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """The rule the ticket asked for, and **not** the rule that caught it.

        A seat checked that, and the correction is worth keeping: run these
        three rules over `schemas/book.py` at 45b7b22 and this one returns
        nothing. `BookMatch` stated no ceiling at all, and a body that states
        none has nothing to disagree with. What named all thirteen fields was
        `_unbounded`, and what named the `language` 16 against `String(10)` was
        `_over_column`.

        This rule covers the case those two cannot: two bodies that both state
        a bound and state different ones, which is how a column drifts once
        everything is nominally bounded.
        """
        assert _disagreements(bodies) == []

    def test_every_exemption_still_carries_its_weight(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """`_UNBOUNDED_OK` had no staleness check while `_COLUMN_FOR_FIELD` did.

        An entry that stopped being true passes silently and then quietly
        exempts whatever lands on that name next. So each one has to name a
        field that exists **and** still be doing work: an exemption for a field
        somebody has since bounded is a line to delete, not a line to keep.
        """
        for label in sorted(_UNBOUNDED_OK):
            model_name, _, field_name = label.partition(".")
            model = bodies.get(model_name)
            assert model is not None, f"{label} names no request body model"
            field = model.model_fields.get(field_name)
            assert field is not None, f"{label} names no field on {model_name}"
            assert not _is_bounded(field), (
                f"{label} is bounded now, so the exemption is dead and should go"
            )

    def test_every_kind_reaching_the_sizeless_tuple_is_named_in_it(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """`_SIZELESS` is the one enumeration left here, so it gets a test.

        Not a count, which would need updating by whoever adds an enum field.
        The property: a field that reaches this arm at all must have every kind
        it admits named in the tuple, or it is being called bounded by the
        catch-all rather than by a reason.

        **This is a diagnostic, not a second guard, and saying so is the
        point.** It cannot fail independently of
        `test_every_field_a_request_body_carries_has_a_ceiling`: the sizeless
        arm is `all(issubclass(kind, _SIZELESS))`, so an unnamed kind already
        makes that False and rule 1 already reports the field. Measured by a
        critic seat on `Decimal`, `UUID` and `Decimal | None`, each of which
        rule 1 reports on its own. What this adds is the **name of the kind**
        in the failure, where rule 1 says only that the field is unbounded.

        Kept for that, and labelled because a test whose docstring implies
        independent reach is exactly what three separate findings in this
        ticket turned on.
        """
        named = (*_SIZELESS, Literal)
        offenders = []
        for name, model in sorted(bodies.items()):
            for field_name, field in model.model_fields.items():
                kinds = _kinds(field.annotation)
                if any(k in (str, bytes, int, float) for k in kinds):
                    continue
                if any(_is_container(k) for k in kinds):
                    continue
                for kind in kinds:
                    literal = kind is Literal or typing.get_origin(kind) is Literal
                    if literal or (isinstance(kind, type) and issubclass(kind, named[:-1])):
                        continue
                    offenders.append(f"{name}.{field_name} ({kind})")
        assert offenders == [], (
            "These fields are called bounded by the sizeless arm and their kind "
            "is not named in _SIZELESS:\n  " + "\n  ".join(offenders)
        )

    def test_the_categories_ceiling_assumes_the_separator_it_is_derived_from(
        self,
    ) -> None:
        """`CATEGORIES_MAX` is `32 * CLASSIFICATION_NUMBER_MAX + 31 * 2`, and
        the `2` is the width of `google_books.CATEGORY_SEPARATOR`.

        That module is the only place allowed to know the separator, by its own
        docstring, so `models.py` cannot import it without becoming a second
        place that knows. The literal is pinned here instead: the heading width
        cannot drift because it is a named constant, and this is what stops the
        separator from drifting silently underneath a comment claiming the
        arithmetic cannot.
        """
        assert len(CATEGORY_SEPARATOR) == 2
        assert 32 * CLASSIFICATION_NUMBER_MAX + 31 * len(
            CATEGORY_SEPARATOR
        ) == CATEGORIES_MAX

    def test_the_rename_map_names_real_fields_and_real_columns(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """A rename map is the one enumeration here, so it is checked rather
        than trusted: a key that is itself a column name would silently
        redirect a field that needed no redirecting."""
        columns = {column.name for column in Book.__table__.columns}
        fields = {
            field_name
            for model in bodies.values()
            for field_name in model.model_fields
        }
        for field_name, column in _COLUMN_FOR_FIELD.items():
            assert field_name in fields, f"{field_name} is on no request body"
            assert column in columns, f"{column} is not a Book column"
            assert field_name not in columns, f"{field_name} is already a column"


#: A bounded list entry, spelled the way `RowIdField` is, because the alias in
#: a union is the shape that hid a missing bound from the first version of
#: `_stated_ceiling`.
_BoundedEntry = Annotated[int, Field(ge=1, le=9_999)]


class _Loose(BaseModel):
    """A synthetic request body, for driving the rules above.

    Four fields of four different kinds. The three the column rules can read
    name real `Book` columns; the list one does not, because those rules read
    strings and a list writing a column is not a shape this app has.

    Its list is bounded **twice**, at the count and at the entry, which is what
    the two list arms of the diagonal take apart one at a time. A `list[int]`
    here would be a fixture that is already reported before any mutation, and
    every case below would then pass by naming a second offender.
    """

    title: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=255)
    series_index: float | None = Field(default=None, ge=0, le=1000)
    suggested_tag_ids: list[_BoundedEntry] = Field(default=[], max_length=500)


def _mutated(
    annotations: dict[str, Any] | None = None, **overrides: Any
) -> dict[str, type[BaseModel]]:
    """`_Loose` with some fields replaced, as the rules see it.

    `annotations` replaces a field's **type**, which is how the entry half of
    the list rule is reached: dropping `_BoundedEntry` is a change to the
    annotation and not to the `Field`.
    """
    # **Resolved types from `model_fields`, never `__annotations__`.** This
    # module carries `from __future__ import annotations`, so the class
    # dictionary holds strings, and a synthetic class built by `type()` has no
    # module namespace for pydantic to resolve `_BoundedEntry` against. The
    # field then arrives as a `ForwardRef`, which matches no arm of
    # `_is_bounded` and is reported as unbounded: a fixture failure that reads
    # exactly like a real finding.
    field_types = {
        name: field.annotation for name, field in _Loose.model_fields.items()
    } | (annotations or {})
    unresolved = sorted(
        name for name, kind in field_types.items() if isinstance(kind, typing.ForwardRef)
    )
    assert not unresolved, f"the fixture's annotations did not resolve: {unresolved}"
    namespace: dict[str, Any] = {"__annotations__": field_types}
    for field_name, field in _Loose.model_fields.items():
        namespace[field_name] = Field(
            default=field.default, **_field_kwargs(field)
        )
    for field_name, replacement in overrides.items():
        namespace[field_name] = replacement
    model = type("Probe", (BaseModel,), namespace)
    return {"Probe": typing.cast(type[BaseModel], model)}


def _field_kwargs(field: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for constraint in field.metadata:
        for name in ("max_length", "ge", "le"):
            if getattr(constraint, name, None) is not None:
                kwargs[name] = getattr(constraint, name)
    return kwargs


class TestTheGuardWouldNoticeEachFieldGoingLoose:
    """The diagonal.

    A mutation test that loosens one field and asserts "something was
    reported" proves nothing: the rule may have reported a **different** field
    all along. Each case below loosens exactly one field of a four field body
    and asserts the report names that field **and nothing else**, so a fixture
    that is reported for its neighbour's reason cannot pass.

    Four kinds, because the rule detects each differently: a string by probing,
    a number by probing, a list by reading `max_length`, and a string against
    its column by reading it.
    """

    def test_the_unmutated_body_is_clean(self) -> None:
        """Or every case below is satisfied by a rule that reports
        everything."""
        assert _unbounded(_mutated()) == []
        assert _over_column(_mutated()) == []

    def test_a_string_losing_its_ceiling(self) -> None:
        assert _unbounded(_mutated(title=Field(default=None))) == ["Probe.title"]

    def test_a_second_string_losing_its_ceiling(self) -> None:
        """The diagonal's other arm: `publisher` and `title` must be pinned
        separately, or one fixture is carrying both."""
        assert _unbounded(_mutated(publisher=Field(default=None))) == [
            "Probe.publisher"
        ]

    def test_a_number_losing_its_ceiling(self) -> None:
        assert _unbounded(_mutated(series_index=Field(default=None, ge=0))) == [
            "Probe.series_index"
        ]

    def test_a_list_losing_its_count(self) -> None:
        """The trap this field was: `list[RowIdField]` bounds every entry and
        nothing bounds the number of entries."""
        assert _unbounded(_mutated(suggested_tag_ids=Field(default=[]))) == [
            "Probe.suggested_tag_ids"
        ]

    def test_a_list_losing_its_entry_bound(self) -> None:
        """The other half of a list's size, and the half the first version of
        this rule could not see: `max_length` on a list is a count, so entries
        of any size passed while the field looked bounded. Measured on
        `list[str]` at `max_length=500`: 500 entries of 100,001 characters, so
        50,000,500 accepted, which is the figure the probes actually produce."""
        assert _unbounded(
            _mutated(annotations={"suggested_tag_ids": list[int]})
        ) == ["Probe.suggested_tag_ids"]

    def test_a_string_widened_past_its_column(self) -> None:
        assert _over_column(_mutated(title=Field(default=None, max_length=501))) == [
            "Probe.title says 501, title is String(500)"
        ]

    def test_a_string_tightened_inside_its_column_is_allowed(self) -> None:
        """The other half, or the rule above is satisfied by refusing every
        value but the column's own width, and a model could never be stricter
        than its storage."""
        assert _over_column(_mutated(title=Field(default=None, max_length=100))) == []


class TestTheAgreementRuleReportsTheColumnAndNotTheModel:
    """`_disagreements`, driven separately.

    The trap this repository records by name: a schema comparison whose own
    mutation test picked the **covered** case, validating against a column
    present in both models when the hole was a column present in only one. So
    the fixture below is deliberately ragged. `Wide` carries a column `Narrow`
    does not, and a column `Narrow` bounds differently, and the rule has to
    report the second and stay silent about the first.
    """

    def _pair(self, **wide: Any) -> dict[str, type[BaseModel]]:
        narrow = type(
            "Narrow",
            (BaseModel,),
            {
                "__annotations__": {"title": str | None},
                "title": Field(default=None, max_length=500),
            },
        )
        annotations: dict[str, Any] = {"title": str | None, "publisher": str | None}
        namespace: dict[str, Any] = {
            "__annotations__": annotations,
            "title": Field(default=None, max_length=500),
            "publisher": Field(default=None, max_length=255),
        }
        namespace.update(wide)
        wide_model = type("Wide", (BaseModel,), namespace)
        return {
            "Narrow": typing.cast(type[BaseModel], narrow),
            "Wide": typing.cast(type[BaseModel], wide_model),
        }

    def test_two_models_agreeing_are_clean(self) -> None:
        assert _disagreements(self._pair()) == []

    def test_a_column_only_one_model_names_is_not_a_disagreement(self) -> None:
        """`publisher` is on `Wide` alone. A rule that reported it would be
        reporting the absence of a second opinion, not a conflict, and would
        fire on almost every model in the tree."""
        assert "publisher" not in "".join(_disagreements(self._pair()))

    def test_a_shared_column_bound_differently_is_reported(self) -> None:
        assert _disagreements(
            self._pair(title=Field(default=None, max_length=250))
        ) == ["title: 250 on Wide.title, 500 on Narrow.title"]

    def test_the_rule_reads_the_column_and_not_the_field_name(self) -> None:
        """`isbn13` is `isbn` under another name, and a rule keyed on the field
        name would let the two disagree with nothing reported."""
        pair = {
            "A": typing.cast(
                type[BaseModel],
                type(
                    "A",
                    (BaseModel,),
                    {
                        "__annotations__": {"isbn": str | None},
                        "isbn": Field(default=None, max_length=20),
                    },
                ),
            ),
            "B": typing.cast(
                type[BaseModel],
                type(
                    "B",
                    (BaseModel,),
                    {
                        "__annotations__": {"isbn13": str | None},
                        "isbn13": Field(default=None, max_length=40),
                    },
                ),
            ),
        }
        assert _disagreements(pair) == ["isbn: 20 on A.isbn, 40 on B.isbn13"]


class TestTheShapesThatEscapedTheFirstDraft:
    """Three holes two critic seats found by attacking, not by reading.

    Kept as a class of their own because each is a *shape* rather than a field,
    and because the pattern in all three is the same: the rule was correct
    about the case it was written from and silently accepted the case beside
    it.
    """

    def _one(self, name: str, annotation: Any, default: Any = None, **kw: Any) -> dict[str, type[BaseModel]]:
        model = type(
            "Probe",
            (BaseModel,),
            {"__annotations__": {name: annotation}, name: Field(default=default, **kw)},
        )
        return {"Probe": typing.cast(type[BaseModel], model)}

    def test_a_ceiling_hidden_in_an_alias_inside_a_union_is_found(self) -> None:
        """Pydantic lifts an `Annotated` alias's constraints into
        `field.metadata` for `x: Alias` and not for `x: Alias | None`, and
        every field on `BookMatch` is optional. Both spellings, because
        `Field(...)` buries the `MaxLen` one level deeper than a bare
        `MaxLen(...)` does and only the second was found first time.
        """
        for alias in (
            Annotated[str, Field(max_length=9999)],
            Annotated[str, MaxLen(9999)],
        ):
            models = self._one("publisher", alias | None)
            assert _over_column(models) == [
                "Probe.publisher says 9999, publisher is String(255)"
            ], alias

    def test_a_ceiling_inside_an_alias_that_fits_its_column_is_allowed(self) -> None:
        """The other half, or the rule above is satisfied by reporting every
        alias."""
        alias = Annotated[str, Field(max_length=255)]
        assert _over_column(self._one("publisher", alias | None)) == []

    def test_a_kind_the_rule_has_not_heard_of_is_reported(self) -> None:
        """The arm this replaces answered True for anything that was not a
        string, a number or a list, which is the ticket's own failure shape
        inside the guard written to stop it."""
        for annotation in (dict[str, str], bytes | None, set[int], Any):
            assert _unbounded(self._one("x", annotation)) == ["Probe.x"], annotation

    def test_a_sizeless_kind_is_still_accepted(self) -> None:
        """And the other half: the 35 fields that legitimately take that arm
        must not all start failing."""
        for annotation in (bool, date | None, datetime | None, ReadStatus):
            assert _unbounded(self._one("x", annotation)) == [], annotation

    def test_two_bodies_disagreeing_about_a_numeric_column_are_reported(self) -> None:
        """`series_index` is written by three request bodies and is this
        ticket's sharpest field, and a string only agreement rule could not see
        them drift apart."""
        def body(name: str, high: float) -> type[BaseModel]:
            return typing.cast(
                type[BaseModel],
                type(
                    name,
                    (BaseModel,),
                    {
                        "__annotations__": {"series_index": float | None},
                        "series_index": Field(default=None, ge=0, le=high),
                    },
                ),
            )

        assert _disagreements({"A": body("A", 1000), "B": body("B", 1e20)}) == [
            "series_index: ge=0 le=1000 on A.series_index, "
            "ge=0 le=1e+20 on B.series_index"
        ]
        assert _disagreements({"A": body("A", 1000), "B": body("B", 1000)}) == []

    def test_a_container_with_no_element_type_is_reported(self) -> None:
        """`typing.get_args(list)` is `()`, and `all()` over nothing is True.

        So the arm added to catch an unbounded container reported a bare one as
        bounded, which is the same 50,000,500 characters
        `test_a_list_losing_its_entry_bound` exists to refuse. Both critic
        seats found it separately in the same round.

        Every container spelling, not just `list`: fixing the one that was
        measured is what this file keeps being wrong about.
        """
        for annotation in (list, set, dict, frozenset, tuple):
            assert _unbounded(self._one("x", annotation, default=None, max_length=5)) == [
                "Probe.x"
            ], annotation

    def test_a_container_keyed_on_its_abstract_base_needs_no_arm_per_type(
        self,
    ) -> None:
        """`set[int]` and friends used to fall past the container arm and be
        refused by the sizeless tuple, which is the right answer for the wrong
        reason and leaves the next person no arm to fix. They are now the
        container rule's, count bound and elements alike."""
        assert _unbounded(self._one("x", set[int], default=None, max_length=5)) == [
            "Probe.x"
        ]
        bounded = Annotated[int, Field(ge=1, le=9)]
        assert _unbounded(self._one("x", set[bounded], default=None, max_length=5)) == []

    def test_a_kind_that_is_not_the_first_one_checked_is_still_checked(self) -> None:
        """The arm order used to decide: `str in kinds` answered for the whole
        annotation, so the list half of a `str | list[str]` was never looked
        at. No such field exists here; the shape is the one this file keeps
        paying for."""
        assert _unbounded(
            self._one("x", str | list[str], default=None, max_length=500)
        ) == ["Probe.x"]

    def test_a_constraint_that_cannot_apply_to_a_probe_reports_rather_than_raises(
        self,
    ) -> None:
        """Pydantic raises a bare `TypeError`, not a `ValidationError`, for
        `max_length` against an integer or `le` against a string.

        Checking every kind rather than the first matching one is what reaches
        it, so this defect was introduced by the fix for the arm ordering and
        found by a critic seat attacking that fix. A traceback here would read
        as a broken test rather than a verdict, and the natural reaction is to
        reach for the exemption list.
        """
        assert _unbounded(self._one("x", str | int | None, max_length=50)) == [
            "Probe.x"
        ]
        assert _unbounded(self._one("x", str | int | None, le=100)) == ["Probe.x"]

    def test_a_non_container_union_member_contributes_no_element_types(self) -> None:
        """`typing.get_args` of a `Literal` returns its **values**, so a
        `Literal["a", "b"] | list[bounded]` handed the strings "a" and "b" to a
        rule that asks whether an annotation is bounded."""
        bounded = Annotated[int, Field(ge=1, le=10)]
        annotation = Literal["a", "b"] | list[bounded]
        assert _element_types(annotation) == (bounded,)
        assert _unbounded(self._one("x", annotation, default=None, max_length=5)) == []
