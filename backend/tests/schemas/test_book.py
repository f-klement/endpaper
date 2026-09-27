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
  model. Both `cover_url` fields carry such a bound, on the width of the value
  **after** the ORM rewrites it, and both also carry a `max_length` these rules
  do see, so neither is reported. `TestAColumnRewrittenOnWriteIsBoundedAfterTheRewrite`
  is what covers the part these three rules cannot.
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

import ast
import collections.abc as abc
import importlib
import importlib.util
import inspect
import pathlib
import pkgutil
import re
import textwrap
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
from pydantic.fields import FieldInfo
from sqlalchemy import Column, Integer, MetaData, Table

import catalogue
import models
import routers
import routers.books as books_router
import schemas.book as schemas_book
from enums import ReadStatus
from google_books import CATEGORY_SEPARATOR, join_categories, split_categories
from models import CLASSIFICATION_NUMBER_MAX, Book
from schemas.book import (
    CATEGORIES_MAX,
    CATEGORY_MAX,
    MAX_CATEGORIES_PER_BOOK,
    BookCreate,
    BookMatch,
)

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
    absent, so `description` and `categories` are outside this rule.

    **`description` is covered by the agreement rule and `categories` is not**,
    and the difference is the shape rather than the column. Two request bodies
    state a width for `description` and the agreement rule compares them. Both
    bodies name `categories`, but one carries it as a list, which `_kinds`
    answers `{list}` for, so only one of the pair reaches `_column_fields` and
    there is nothing for that rule to compare. What covers it instead is
    `TestTheTwoDoorsIntoTheCategoriesColumn`, which asserts the identity between
    the list bounds and this column's stated width directly.

    **The claim about `categories` was already false before a list door existed**,
    and dating it to that door would be the same error again: the agreement rule
    needs two request bodies stating a bound for one column, and `BookMatch` was the
    only body naming this one, so the rule had a single row and could never report.
    `BookOut` and `PublicBookOut` are response models.
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
        """`CATEGORIES_MAX` is `MAX_CATEGORIES_PER_BOOK * CATEGORY_MAX` plus one
        separator between each pair, and the expression spells that width as
        `len(CATEGORY_SEPARATOR)` rather than as a `2`.

        **So there is no literal here to pin, which is the point.** The
        arithmetic and the separator now sit in the module whose request body
        states both bounds, so the width is read off the separator and cannot
        drift underneath a comment claiming it cannot. This arm is a second
        reading of that one derivation; what it adds is the factors, since a
        `32` or a `120` retyped anywhere is a further home for a number the
        field already states.

        `CATEGORY_MAX == CLASSIFICATION_NUMBER_MAX` is asserted as a
        measurement rather than spelled as an alias, so widening a column width
        fails here instead of silently widening every accepted subject list.
        """
        assert len(CATEGORY_SEPARATOR) == 2
        assert CATEGORY_MAX == CLASSIFICATION_NUMBER_MAX
        assert MAX_CATEGORIES_PER_BOOK * CATEGORY_MAX + (
            MAX_CATEGORIES_PER_BOOK - 1
        ) * len(CATEGORY_SEPARATOR) == CATEGORIES_MAX

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


#: What a value of a rewritten column has to start with to be legal apart from
#: its width.
#:
#: One per key of `catalogue._AS_STORED`, and the arming test below fails when
#: that table grows a column this does not. `cover_url` needs plain **http**,
#: which is what makes the rewrite lengthen the value at all. The host is not
#: load bearing: `covers.is_renderable` asks for https or a local upload and
#: takes any host, measured.
_REWRITTEN_SEEDS = {"cover_url": "http://covers.openlibrary.org/b/id/"}


def _rewritten_probe(column: str) -> str:
    """A value of `column` at exactly its column's width.

    Padded from the width rather than typed out, so the probe follows the column
    and a widened column cannot leave it testing a value that already fits.
    """
    seed = _REWRITTEN_SEEDS[column]
    return seed + "9" * (_column_widths()[column] - len(seed))


def _fields_writing_a_rewritten_column(
    models: dict[str, type[BaseModel]],
) -> list[tuple[str, str, str]]:
    """(model, field, column) for every request body field writing one."""
    return [
        (name, field_name, column)
        for name, model in sorted(models.items())
        for field_name in model.model_fields
        for column in [_COLUMN_FOR_FIELD.get(field_name, field_name)]
        if column in catalogue._AS_STORED
    ]


def _refuses(model: type[BaseModel], field_name: str, value: str) -> bool:
    """Whether `model` refuses `value` for `field_name`, with the other required
    fields filled so nothing else can be what fails."""
    payload: dict[str, Any] = {field_name: value}
    for other, field in model.model_fields.items():
        if other != field_name and field.is_required():
            payload[other] = "x"
    try:
        model(**payload)
    except ValidationError as exc:
        return any(error["loc"] == (field_name,) for error in exc.errors())
    return False


class TestAColumnRewrittenOnWriteIsBoundedAfterTheRewrite:
    """A fourth rule, and it is the one the three above cannot ask.

    Those read a **stated** ceiling and compare it with the column. That is the
    right comparison for a column stored as it arrives, and the wrong one for a
    column the ORM rewrites on the way in: `Book`'s `@validates("cover_url")`
    runs `covers.https_url`, which turns `http://` into `https://` and lengthens
    the value by one, so a `max_length` equal to the column bounds a string one
    character shorter than the stored one. Measured before the fix: a 500
    character http URL was accepted by both bodies carrying the field and stored
    as 501 against a `String(500)`.

    **Driven from `catalogue._AS_STORED`**, which is the register of what a
    write rewrites, so a request body added later is covered without a list of
    field names here.

    **That register is not derived from the model, so it is the half that has to
    be checked rather than assumed.** Measured: add a lengthening validator for
    `publisher`, leave `_AS_STORED` alone, and nothing in either of these two
    files goes red. `test_every_column_with_a_validator_is_in_the_rewrite_table`
    is what closes it, and it is why this class covers a column that grows a
    validator later rather than merely claiming to.

    That register arguably belongs beside the column in `models.py` rather than
    in the catalogue module: raised rather than moved, since `models.py` is one
    seam away from this change.
    """

    def test_every_column_with_a_validator_is_in_the_rewrite_table(self) -> None:
        """The register against the model, so `_AS_STORED` cannot go stale in the
        one direction that matters.

        Every `@validates` on `Book` runs on the way into the column, so it is a
        candidate for rewriting the value, and one missing from the table is a
        column this whole class stops covering **in silence**. Equality rather
        than containment, because a name in the table that no validator backs is
        a probe measuring a rewrite nobody performs.
        """
        assert set(catalogue._AS_STORED) == set(Book.__mapper__.validators), (
            "`Book`'s validators and `catalogue._AS_STORED` disagree. A new "
            "validator goes in that table when it rewrites the value; when it "
            "only refuses one, widen this test and say so here."
        )

    def test_every_rewritten_column_has_a_seed_here(self) -> None:
        """The arming step. A column added to the rewrite table with no seed
        would make the rules below iterate over nothing for it, in silence."""
        missing = sorted(set(catalogue._AS_STORED) - set(_REWRITTEN_SEEDS))
        assert missing == [], (
            f"{missing} is rewritten on write with no probe seed here, so "
            "nothing checks that the request bodies writing it bound the "
            "stored form rather than the arriving one"
        )

    def test_every_seed_names_a_column_that_is_still_rewritten(self) -> None:
        """The other direction, so the table cannot rot into an exemption for
        whatever lands on that name next."""
        assert sorted(set(_REWRITTEN_SEEDS) - set(catalogue._AS_STORED)) == []

    def test_each_probe_is_a_value_the_rewrite_actually_lengthens(self) -> None:
        """Without this the rules below pass on a probe the column holds, which
        is a guard proving nothing while reading as if it proved everything."""
        for column, rewrite in catalogue._AS_STORED.items():
            probe = _rewritten_probe(column)
            width = _column_widths()[column]

            assert len(probe) == width
            assert len(rewrite(probe) or "") > width

    def test_the_walk_finds_the_bodies_that_carry_one(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """A rule over an empty set passes and looks like a rule that holds."""
        assert {
            (name, field_name)
            for name, field_name, _ in _fields_writing_a_rewritten_column(bodies)
        } == {("BookCreate", "cover_url"), ("BookMatch", "cover_url")}

    def test_every_such_field_refuses_a_value_the_rewrite_pushes_past_the_column(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        accepted = [
            f"{name}.{field_name}"
            for name, field_name, column in _fields_writing_a_rewritten_column(bodies)
            if not _refuses(bodies[name], field_name, _rewritten_probe(column))
        ]

        assert accepted == [], (
            "These request-body fields accept a value the column cannot hold "
            "once the ORM rewrites it, so the row is stored over width:\n  "
            + "\n  ".join(accepted)
        )

    def test_the_same_value_one_character_shorter_is_still_accepted(
        self, bodies: dict[str, type[BaseModel]]
    ) -> None:
        """The diagonal. A field refusing the probe for some other reason, a
        host rule or a pattern, would satisfy the rule above while bounding
        nothing, and this is what tells the two apart: one character less is the
        widest value the column can hold after the rewrite."""
        refused = [
            f"{name}.{field_name}"
            for name, field_name, column in _fields_writing_a_rewritten_column(bodies)
            if _refuses(bodies[name], field_name, _rewritten_probe(column)[:-1])
        ]

        assert refused == []


def _writes_a_row_from_its_body(endpoint: Any) -> bool:
    """Whether this handler puts what the caller sent onto a row.

    Two shapes, and the second is the one the first version of this missed.
    The loop, `model_dump(exclude_unset=True)` and `setattr`, which is what a
    partial update is. And the single assignment, `book.ownership =
    payload.ownership`, which is what every one field route does: no dump, same
    value, same column. A rule that saw only the loop left `OwnershipUpdate`
    outside it, safe by the annotation rather than by the rule, which is the
    shape this repository keeps paying for. Found by the design seat.

    **Found by the write rather than by the model's name.** A list of partial
    update bodies would have to be extended by whoever adds the next one, which
    is the enumeration this file replaced three times already.

    **What it still cannot see is a write one call further down**, because
    `inspect.getsource` reads the endpoint and not what the endpoint calls. That
    direction over reports rather than under reports where it does reach: an
    assignment to any attribute counts, so a handler that writes one field of
    its own puts its whole body under the rule.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    return any(
        (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "model_dump"
            and any(
                keyword.arg == "exclude_unset" and keyword.value.value is True
                for keyword in node.keywords
                if isinstance(keyword.value, ast.Constant)
            )
        )
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Attribute) for target in node.targets)
        )
        for node in ast.walk(tree)
    )


def _bodies_written_onto_a_row() -> dict[str, type[BaseModel]]:
    """The request bodies a route writes onto a row."""
    found: dict[str, type[BaseModel]] = {}
    for route in _api_routes():
        if not _writes_a_row_from_its_body(route.endpoint):
            continue
        found.update(
            _models_from(
                [parameter.field_info.annotation for parameter in route.dependant.body_params]
            )
        )
    return found


def _fields_over_a_column_that_refuses_null(
    models: dict[str, type[BaseModel]],
) -> list[tuple[str, str, str]]:
    """(model, field, column) wherever a body field names a NOT NULL column.

    The pair is the defect and neither half is: a column may refuse null and a
    field may accept one, and it is only a body whose route writes that field
    onto that column that turns the two into `UPDATE books SET title=NULL`.
    """
    refuses_null = {
        column.name for column in Book.__table__.columns if not column.nullable
    }
    return sorted(
        (name, field_name, column)
        for name, model in models.items()
        for field_name in model.model_fields
        if (column := _COLUMN_FOR_FIELD.get(field_name, field_name)) in refuses_null
    )


def _refuses_a_null(model: type[BaseModel], field_name: str) -> bool:
    """Whether the model refuses an explicit null for this field.

    **Wider than `_refuses` above, which asks whether the field was named in
    the error.** A refusal derived from the table is raised by a model
    validator, and pydantic reports one of those at `loc == ()`, so a rule
    reading the field's own entry alone would call a refused null accepted.

    **A model level error still has to name the field**, which is the half a
    bare `loc == ()` does not have: any other model validator refusing for an
    unrelated reason would otherwise read as this field being refused, and the
    rule above would pass on a model that accepts the null. Raised by the
    security seat. An error naming some **other** field is excluded for the
    same reason in the other direction, so a required neighbour the probe
    filled badly cannot be read as this field refusing.

    **On a word boundary, because `title` is inside `subtitle`** and both are
    fields of the one model in this rule with a live pair. A substring match
    read a message about the subtitle as the title being refused, which fails
    open on exactly the field the class exists for. Found by the design seat,
    on the round that added the sentence above.
    """
    payload: dict[str, Any] = {field_name: None}
    for other, field in model.model_fields.items():
        if other != field_name and field.is_required():
            payload[other] = "x"
    try:
        model(**payload)
    except ValidationError as exc:
        return any(
            error["loc"] == (field_name,)
            or (
                error["loc"] == ()
                and re.search(rf"\b{re.escape(field_name)}\b", str(error["msg"]))
            )
            for error in exc.errors()
        )
    return False


class TestNoBodyWrittenOntoARowCanClearAColumnThatRefusesNull:
    """A fifth rule, and the one the four above cannot ask.

    They are about how **wide** a value may be. This is about whether the value
    may be absent at all: `PATCH /api/books/{book_id}` with `{"title": null}`
    reached `UPDATE books SET title=NULL`, SQLite refused on the constraint, and
    `errors.unhandled_exception_handler` turned the `IntegrityError` into a
    **500** over a value the edit form lets somebody type. Found 2026-09-20 by
    the schema driven run in `tests/api_contract.py`.

    **Derived from the table at one end and from the write at the other**, so
    neither half is a list: a field added over a NOT NULL column joins the rule,
    and so does the body of the next route that writes one onto a row. **Three
    pairs, and the floor below is what pins that**: two of the three are reached
    only by the assignment arm, so without it the arm could be deleted and every
    assertion here would still pass on the one pair the dump arm finds. Found by
    the design seat, on the round that added the arm.

    `BookMatch.title` is the other field in the tree naming a NOT NULL column
    and admitting null, and it is not here because nothing writes it:
    `google_books.merge_into` walks `book_columns.WORK_DETAIL`, which holds the
    descriptive facts, and `title` is `WORK_IDENTITY`. That is a property of the
    writer rather than of the model, which is why this rule asks about the
    writer.

    **`books` and no other table**, which is the boundary this file already has
    and the one to watch: a field named for a column of another table is matched
    against `books` or not at all. The first body written onto a row of a
    different table needs the walk to carry which table that is.
    """

    def test_the_rule_has_a_pair_to_be_about(self) -> None:
        """A rule over an empty set passes and reads exactly like one that
        holds, and so does a rule over a set that quietly shrank. Three ways
        this one can: a walk that finds no partial update route, a column set
        read off the wrong table, and an arm of the walk deleted."""
        written = _bodies_written_onto_a_row()

        assert "BookDetailsUpdate" in written, (
            "the walk no longer finds the body PATCH /api/books/{book_id} "
            f"writes; it found {sorted(written)}"
        )
        pairs = _fields_over_a_column_that_refuses_null(written)

        assert pairs, (
            "no field of a body written onto a row names a NOT NULL column, so "
            "this rule is about nothing"
        )
        assert len(pairs) >= 3, (
            f"only {len(pairs)} field of a body written onto a row names a NOT "
            "NULL column. A floor rather than a count, because the number moves "
            "with every route added: what it refuses is the assignment arm of "
            "`_writes_a_row_from_its_body` going away, which takes two of the "
            f"three with it and leaves every other assertion here green. {pairs}"
        )

    def test_every_such_field_refuses_an_explicit_null(self) -> None:
        written = _bodies_written_onto_a_row()
        accepted = [
            f"{name}.{field_name} accepts null, books.{column} refuses one"
            for name, field_name, column in _fields_over_a_column_that_refuses_null(written)
            if not _refuses_a_null(written[name], field_name)
        ]

        assert accepted == [], (
            "These request bodies let a caller clear a column the database "
            "refuses to leave empty, which is an IntegrityError on the flush "
            "and a 500 to whoever sent it:\n  " + "\n  ".join(accepted)
        )

    def test_the_probe_reports_a_field_that_takes_the_null(self) -> None:
        """The diagonal. A probe that answered "refused" for everything would
        satisfy the rule above while measuring nothing, and this is the shape
        the rule exists to catch: optional, defaulted, and null means null."""

        class _Clearable(BaseModel):
            title: str | None = None

        assert not _refuses_a_null(_Clearable, "title")


def _element_ceiling(field: Any) -> int | None:
    """The width one entry of a container field declares, or None.

    Through `FieldInfo.from_annotation` rather than by reading `__metadata__`
    here, so the element goes through the same `_constraints` walk the field
    does: that walk exists because the house spelling hides a `MaxLen` inside a
    `FieldInfo`, and an element read any other way would miss it exactly as the
    first version of that walk did.
    """
    elements = _element_types(field.annotation)
    if not elements:
        return None
    return min(
        (
            ceiling
            for element in elements
            if (ceiling := _stated_ceiling(FieldInfo.from_annotation(element)))
            is not None
        ),
        default=None,
    )


class TestTheTwoDoorsIntoTheCategoriesColumn:
    """`BookCreate.categories` and `BookMatch.categories`, and the rules differ.

    **The agreement rule cannot see this pair, which is why these arms exist.**
    `_kinds` answers `{list}` for a generic, deliberately and with its reason at
    its own site, so `BookCreate.categories` never reaches `_column_fields` and
    `_disagreements` has one field for this column where it needs two. Nothing
    else in this file relates `CATEGORIES_MAX` to `MAX_CATEGORIES_PER_BOOK` and
    `CATEGORY_MAX`: a product and its factors live in one module and no type
    checker relates them, so a widening of either factor without the width is a
    stored value the column cannot hold.

    **What these arms do not cover.** They read the bounds the two bodies state
    and the values the two validators return. A hostile client can store any
    value the column holds through either door, so nothing here is a claim about
    what a determined caller writes: the refusal on the create door is a
    correctness control against an honest producer. Neither is this a claim about
    stored rows, which predate both bounds.
    """

    def test_the_widest_list_the_create_body_admits_joins_to_the_column_bound(
        self,
    ) -> None:
        """The identity the two factors were named for.

        Read off the field rather than from the constants, so widening either
        bound on the body without widening the column fails here. Exactly equal
        rather than within: that is what makes the width a derivation of the pair
        and not a number that happens to be larger.

        **Implied by the two arms below rather than independent of them**, which is
        worth saying instead of adding a fourth: this, the factor arm and
        `test_the_categories_ceiling_assumes_the_separator_it_is_derived_from` are
        three readings of one derivation, not three instruments. What this one adds
        is that it goes through `join_categories`, so a change to the join is
        visible here and to neither of the others.
        """
        field = BookCreate.model_fields["categories"]
        count = _stated_ceiling(field)
        entry = _element_ceiling(field)
        assert count is not None and entry is not None, (
            "the create body's subject list states no count or no entry width, "
            "so the column bound is no longer derived from anything"
        )

        widest = join_categories(["x" * entry] * count)

        assert widest is not None and len(widest) == CATEGORIES_MAX, (
            f"{count} subjects of {entry} characters join to "
            f"{len(widest or '')}, and the column holds {CATEGORIES_MAX}"
        )

    def test_the_two_factors_are_the_ones_the_column_width_is_computed_from(
        self,
    ) -> None:
        """The other half, and it is not the same assertion.

        The arm above passes if the body states any pair whose join fits. This
        one refuses a body that states a pair the column width was not computed
        from, which is what stops the two drifting into agreement at the wrong
        number.
        """
        field = BookCreate.model_fields["categories"]

        assert _stated_ceiling(field) == MAX_CATEGORIES_PER_BOOK
        assert _element_ceiling(field) == CATEGORY_MAX

    def test_the_two_widths_are_the_same_population(self) -> None:
        """A subject and a classification number are bounded alike because they are
        the same thing measured: an access point with its subdivisions.

        **An arm rather than an alias.** `CATEGORY_MAX` used to be spelled
        `= CLASSIFICATION_NUMBER_MAX`, which made this claim unfalsifiable while the
        coupling ran the wrong way: that constant is a **column** width, widened
        three times for column reasons by its own record, and each widening silently
        widened every subject list this application accepts, with every arm green.
        Two literals and this arm means moving either has to be done twice.
        """
        assert CATEGORY_MAX == CLASSIFICATION_NUMBER_MAX

    def test_the_entry_width_applies_to_the_normalised_subject(self) -> None:
        """The `mode="before"` ordering, and nothing else armed it.

        Measured: under `mode="after"` the element `max_length` would refuse this
        raw 140 character entry, and under `mode="before"` normalisation removes the
        20 that have no width and the 120 that remain are accepted. The other two
        width arms are refused under either ordering, so that mutation survived
        them both.

        **A `Cc` character and not a `Cf` one.** `one_line_without_invisible_characters`
        removes NUL and leaves U+200B, U+00AD and U+FEFF in place, deliberately, so a
        `Cf` probe would be refused for its width and the arm would pass for the
        wrong reason.
        """
        raw = "y" * CATEGORY_MAX + "\x00" * 20
        assert len(raw) == CATEGORY_MAX + 20

        accepted = BookCreate(title="t", categories=[raw]).categories

        assert accepted == ["y" * CATEGORY_MAX]

    def test_a_subject_carrying_the_separator_is_refused_rather_than_split(
        self,
    ) -> None:
        """The create door's rule, and the value that drives it.

        Splitting would answer 201 and store two subjects where the member
        asserted one, and the invented one is then served without a session. The
        entry here is the shape an honest producer supplies: one field a
        publisher put two subjects in.
        """
        with pytest.raises(ValidationError) as refusal:
            BookCreate(title="t", categories=["Fiction; general"])

        assert CATEGORY_SEPARATOR.strip() in str(refusal.value), (
            "the refusal does not name the character it refuses, so nobody can "
            "act on it"
        )

    def test_the_separator_is_refused_inside_a_subject_however_it_is_spelled(
        self,
    ) -> None:
        """The joined form is two characters and the split form is one, so a
        rule written against the joined form refuses nothing a bare semicolon
        does."""
        for spelling in ("A;B", "A; B", "A ;B", ";A", "A;"):
            with pytest.raises(ValidationError):
                BookCreate(title="t", categories=[spelling])

    def test_no_subject_the_create_door_accepts_carries_the_separator(
        self,
    ) -> None:
        """The refusal as a property over what is accepted rather than over what
        is refused: every candidate either raises or comes back without the
        character.

        **The candidates have to include one that carries it.** The first version
        of this arm asserted the property over three entries that had no separator
        in them, so removing the refusal altogether left it green: measured, that
        mutation was caught by the two arms above and not by this one. A property
        arm over inputs that cannot exercise it is the arm that reads as the
        strongest and holds the least.
        """
        candidates = ["Fiction", "Fiction; general", "A;B", "  Social   Problems  "]
        assert any(CATEGORY_SEPARATOR.strip() in candidate for candidate in candidates)

        seen = 0
        for candidate in candidates:
            try:
                accepted = BookCreate(title="t", categories=[candidate]).categories
            except ValidationError:
                continue
            seen += len(accepted)
            assert not any(
                CATEGORY_SEPARATOR.strip() in subject for subject in accepted
            ), f"{candidate!r} was accepted as {accepted!r}, which carries the separator"

        assert seen, "every candidate was refused, so the property held over nothing"

    def test_an_accepted_list_survives_the_round_trip_through_the_column(
        self,
    ) -> None:
        """Normalisation does not desync the round trip: a padded or multi word
        subject reads back as the one subject it was.

        **This arm does not carry the refusal**, and saying so is the point: every
        input here is separator free, so deleting the refusal leaves it green.
        Measured. What carries the refusal is
        `test_no_subject_the_create_door_accepts_carries_the_separator`, which is
        driven by a separator bearing candidate.
        """
        accepted = BookCreate(
            title="t", categories=["Fiction, general", "  Science   Fiction  "]
        ).categories

        assert split_categories(join_categories(accepted)) == accepted
        assert accepted == ["Fiction, general", "Science Fiction"]

    def test_an_empty_subject_list_stores_a_null_rather_than_an_empty_string(
        self,
    ) -> None:
        """The column is nullable and `join_categories` answers None for an
        empty list. A stored `""` would read back as no subjects and sort
        differently from a row that never had any."""
        assert join_categories(BookCreate(title="t", categories=[]).categories) is None

    def test_the_enrichment_door_bounds_the_subjects_inside_the_joined_string(
        self,
    ) -> None:
        """The looseness one route apart, and its size.

        `POST /api/books/{book_id}/enrich/apply` takes this body from the client
        and `merge_into` writes the column from it, so the count the create door
        states meant nothing here while the only bound was on the string.
        """
        stated = _stated_ceiling(BookMatch.model_fields["categories"])
        assert stated == CATEGORIES_MAX
        bypass = ("a" + CATEGORY_SEPARATOR.strip()) * (stated // 2)
        assert len(bypass) == stated, "the driving value no longer fills the field"
        assert len(split_categories(bypass)) > MAX_CATEGORIES_PER_BOOK

        with pytest.raises(ValidationError):
            BookMatch(categories=bypass)

    def test_the_enrichment_door_bounds_after_the_split_and_never_before(
        self,
    ) -> None:
        """The ordering, driven by the value that separates the two.

        The field's own `max_length` accepts this payload whole, so a door
        applying its bounds to what arrived would take it. What it would then
        store is far wider than the column, which is the failure the order exists
        to stop.
        """
        entry = ("a" + CATEGORY_SEPARATOR.strip()) * (CATEGORY_MAX // 2)
        payload = CATEGORY_SEPARATOR.join([entry] * MAX_CATEGORIES_PER_BOOK)
        assert len(payload) <= CATEGORIES_MAX, (
            "the payload no longer fits the field's own bound, so this arm would "
            "pass on that bound rather than on the ordering"
        )
        rejoined = join_categories(split_categories(payload))
        assert rejoined is not None and len(rejoined) > CATEGORIES_MAX

        with pytest.raises(ValidationError):
            BookMatch(categories=payload)

    def test_the_enrichment_door_bounds_the_count_where_the_width_cannot(
        self,
    ) -> None:
        """The count bound, isolated.

        **Every other arm that trips the count also trips the rejoin width**, so
        deleting the count left them all green. Measured. One character subjects are
        the shape that separates the two: 33 of them rejoin to 97, far inside
        `CATEGORIES_MAX`, so only the count can refuse this.
        """
        payload = CATEGORY_SEPARATOR.strip().join(["a"] * (MAX_CATEGORIES_PER_BOOK + 1))
        subjects = split_categories(payload)
        assert len(subjects) == MAX_CATEGORIES_PER_BOOK + 1
        rejoined = join_categories(subjects)
        assert rejoined is not None and len(rejoined) < CATEGORIES_MAX, (
            "the driving value now trips the width bound too, so this arm would "
            "pass without the count bound existing"
        )

        with pytest.raises(ValidationError):
            BookMatch(categories=payload)

    def test_the_enrichment_door_accepts_exactly_the_count_the_other_door_does(
        self,
    ) -> None:
        """The count bound from the accepting side, which is the side that was
        unarmed.

        **The most subjects any other arm accepted here was three**, so mutating the
        comparison to `>=`, or the bound to any constant above three, passed every
        arm in both suites while making the two doors disagree about a list the
        create door admits. Measured. This sits the value exactly on the boundary.
        """
        payload = CATEGORY_SEPARATOR.strip().join(["a"] * MAX_CATEGORIES_PER_BOOK)

        accepted = BookMatch(categories=payload).categories

        assert accepted == CATEGORY_SEPARATOR.join(["a"] * MAX_CATEGORIES_PER_BOOK)
        assert len(split_categories(accepted)) == MAX_CATEGORIES_PER_BOOK

    def test_the_enrichment_door_bounds_the_width_of_what_it_would_store(
        self,
    ) -> None:
        """The bound the count cannot stand in for, and the reason it is the
        rejoin rather than a per subject width.

        Splitting on a bare separator and rejoining with the two character one
        **lengthens** the value by one per split. So a payload of exactly
        `CATEGORIES_MAX` carrying the greatest legal number of bare separators is
        inside the count bound and still 31 characters past the column.
        """
        parts = MAX_CATEGORIES_PER_BOOK
        content = CATEGORIES_MAX - (parts - 1)
        each, extra = divmod(content, parts)
        values = ["a" * each] * parts
        values[0] += "a" * extra
        payload = CATEGORY_SEPARATOR.strip().join(values)

        assert len(payload) == CATEGORIES_MAX
        assert len(split_categories(payload)) == MAX_CATEGORIES_PER_BOOK, (
            "the payload no longer sits inside the count bound, so the count "
            "would refuse it and this arm would pass on the wrong bound"
        )
        joined = join_categories(split_categories(payload))
        assert joined is not None and len(joined) == CATEGORIES_MAX + parts - 1

        with pytest.raises(ValidationError):
            BookMatch(categories=payload)

    def test_the_enrichment_door_stores_one_subject_the_column_can_hold(
        self,
    ) -> None:
        """The diagonal, and it is what a per subject width would have broken.

        A catalogue heading wider than one entry of the create body's list is
        still a value this column holds, and on this path what the column can hold
        is stored:
        `tests/routers/test_books_google.py::TestACatalogueCannotWriteWhatTheColumnsRefuse`
        pins that as the answer for every field. So the bound here is the width of
        the rejoin and not a width per subject.
        """
        widest = "s" * CATEGORIES_MAX

        assert BookMatch(categories=widest).categories == widest
        assert len(widest) > CATEGORY_MAX

    def test_the_enrichment_door_rejoins_what_it_split(self) -> None:
        """It hands on the stored form, so what the column holds is what this
        model validated. A bare separator is the producer's spelling and the
        joined one is this application's."""
        assert BookMatch(categories="A;B").categories == f"A{CATEGORY_SEPARATOR}B"
        assert BookMatch(categories="A ;  B").categories == f"A{CATEGORY_SEPARATOR}B"
        assert BookMatch(categories="A;;B").categories == f"A{CATEGORY_SEPARATOR}B"

    def test_the_enrichment_door_leaves_an_empty_value_null(self) -> None:
        """`split_categories` answers `[]` for a string with nothing in it, and
        the column is nullable, so a blank arrives as a null rather than as an
        empty string."""
        assert BookMatch(categories=None).categories is None
        assert BookMatch(categories="   ").categories is None
        assert BookMatch(categories=CATEGORY_SEPARATOR).categories is None

    def test_the_enrichment_door_is_idempotent_over_what_it_returns(self) -> None:
        """It writes the column and `as_match` reads one, so a value round
        tripping through both must not move on the second pass."""
        once = BookMatch(categories="A;B; C").categories
        assert BookMatch(categories=once).categories == once


_SCHEMAS_BOOK = pathlib.Path(schemas_book.__file__)


def _load_schemas_book() -> None:
    """Execute `schemas/book.py` as a module of its own, so its refusal runs.

    A fresh module object rather than a reload, for `test_book_columns.py`'s
    reason: a reload would leave the real module half initialised in this worker
    when the refusal raises, and every later test in the process would read a
    schema module with none of its models in it.
    """
    spec = importlib.util.spec_from_file_location(
        "schemas_book_under_test", _SCHEMAS_BOOK
    )
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


def _book_whose_table_has(names: list[str]) -> type:
    """A stand in for `Book` carrying exactly these column names.

    Built here and never mapped, so the real metadata is untouched. Only the
    names are read, so every column is an `Integer`.
    """
    metadata = MetaData()
    table = Table(
        "books",
        metadata,
        *(Column(name, Integer, primary_key=name == "id") for name in names),
    )
    return type("BookStandIn", (), {"__table__": table})


def _book_columns() -> list[str]:
    return [column.name for column in Book.__table__.columns]


class TestEveryCreateFieldEitherReachesTheConstructorOrIsPopped:
    """The partition behind `POPPED_BEFORE_THE_CONSTRUCTOR`, driven.

    Two cells rather than one list of popped names, because the remedies differ:
    a name in the first has no column at all and is written as child rows, and a
    name in the second has a column whose stored shape differs from the request
    shape and needs an assignment at the route as well as the pop.

    The arms below drive the predicate against sides built here, so each one can
    be made to fail. **The evasions were not chosen by whoever wrote the
    predicate**, which is the one thing this class cannot certify about itself.
    """

    def test_nothing_is_reported_when_the_cells_and_the_fields_agree(self) -> None:
        """The baseline. Without it every arm below scores a pass it did not
        earn, because a predicate reporting everything reports these too."""
        assert (
            schemas_book._unconstructable_create_fields(
                ["kids"],
                ["joined"],
                {"title": str, "kids": list[str], "joined": list[str]},
                ["title", "joined"],
            )
            == {}
        )

    def test_a_popped_name_that_is_not_a_field_of_the_body_is_reported(self) -> None:
        """A pop claiming a field nobody sends. Silent today, because `pop` with
        a default does not raise on a name that is not there."""
        reported = schemas_book._unconstructable_create_fields(
            ["gone"], [], {"title": str}, ["title"]
        )

        assert set(reported) == {"gone"}

    def test_a_child_row_cell_naming_a_real_column_is_reported(self) -> None:
        """A name popped as a child row that IS a column would pass through or be
        reshaped, and popping it stores nothing."""
        reported = schemas_book._unconstructable_create_fields(
            ["shelf_mark"], [], {"title": str, "shelf_mark": str}, ["title", "shelf_mark"]
        )

        assert set(reported) == {"shelf_mark"}

    def test_a_popped_name_the_body_lacks_keeps_the_remedy_for_that(self) -> None:
        """One name, one remedy, and the arms above could not see this.

        Every existing arm passes the offending name **as** a field, so the
        subtraction that stops a second wrong remedy was unarmed: the child row cell
        reported such a name as one that "should pass through or be reshaped", which
        is the wrong instruction for a field nobody sends. Driven from both cells,
        because only one of them subtracted.
        """
        both_cells: tuple[tuple[list[str], list[str]], ...] = (
            (["ghost"], []),
            ([], ["ghost"]),
        )
        for child_rows, reshaped in both_cells:
            reported = schemas_book._unconstructable_create_fields(
                child_rows, reshaped, {"title": str}, ["title", "ghost"]
            )

            assert set(reported) == {"ghost"}
            assert "is not a field of the body" in reported["ghost"]

    def test_a_reshaped_cell_naming_no_column_is_reported(self) -> None:
        """The symmetric half. A name in the reshape cell with no column behind it
        is a child row, and a reshape assignment for it would raise."""
        reported = schemas_book._unconstructable_create_fields(
            [], ["kids"], {"title": str, "kids": list[str]}, ["title"]
        )

        assert set(reported) == {"kids"}

    def test_a_field_reaching_the_constructor_that_is_not_a_column_is_reported(
        self,
    ) -> None:
        """The ruling's own case: a twentieth field added to the body and to
        nothing else is a `TypeError` on the constructor."""
        reported = schemas_book._unconstructable_create_fields(
            [], [], {"title": str, "shelf_mark": str}, ["title"]
        )

        assert set(reported) == {"shelf_mark"}

    def test_the_house_spelling_of_a_bounded_container_is_reported(self) -> None:
        """The spelling every optional field on these bodies has, and the one the
        predicate missed.

        Measured: `get_origin(Annotated[list[str], ...])` answers `typing.Annotated`
        rather than `list`, so before the peel this read as a scalar. It answered
        correctly for `RowIdField | None` for the wrong reason, that
        `typing.Annotated` is not a `type`.
        """
        reported = schemas_book._unconstructable_create_fields(
            [],
            [],
            {"title": str, "subjects": Annotated[list[str], Field(max_length=1)] | None},
            ["title", "subjects"],
        )

        assert set(reported) == {"subjects"}

    def test_a_container_spelled_as_an_abstract_type_is_reported(self) -> None:
        """A field may be annotated with the abstract type rather than the concrete
        one, and `get_origin` answers the abstract one, so an enumeration of `list`,
        `set`, `dict` and `tuple` looks straight past it."""
        reported = schemas_book._unconstructable_create_fields(
            [], [], {"title": str, "subjects": abc.Sequence[str]}, ["title", "subjects"]
        )

        assert set(reported) == {"subjects"}

    def test_a_string_field_is_not_reported_as_a_container(self) -> None:
        """The false refusal the fix above could have bought. Every one of `str`,
        `bytes` and `bytearray` satisfies `abc.Sequence`, so admitting the abstract
        types without excluding these three reports every string field on the body
        and stops the schema module importing."""
        assert (
            schemas_book._unconstructable_create_fields(
                [],
                [],
                {"title": str, "raw": bytes, "buf": bytearray, "opt": str | None},
                ["title", "raw", "buf", "opt"],
            )
            == {}
        )

    def test_a_container_field_reaching_the_constructor_is_reported(self) -> None:
        """The arm that makes the one above more than a name check.

        A field sharing a name with a column and arriving as a list passes the
        column arm and still cannot be constructed: the constructor takes the
        keyword and the INSERT fails on it, which is a 500 rather than a 422.
        """
        reported = schemas_book._unconstructable_create_fields(
            [], [], {"title": str, "subjects": list[str]}, ["title", "subjects"]
        )

        assert set(reported) == {"subjects"}

    def test_a_scalar_field_whose_name_is_a_column_needs_no_edit(self) -> None:
        """The common case, and why this is a derivation rather than a list. The
        arms above are worth nothing if every new field fires them."""
        assert (
            schemas_book._unconstructable_create_fields(
                [], [], {"title": str, "shelf_mark": str | None}, ["title", "shelf_mark"]
            )
            == {}
        )

    def test_each_report_says_which_of_the_faults_it_is(self) -> None:
        """A set of names cannot say which remedy a fault wants, and the two cells
        exist because the remedies differ. So the answer is keyed by name."""
        reported = schemas_book._unconstructable_create_fields(
            ["shelf_mark"], ["kids"], {"shelf_mark": str, "kids": list[str]}, ["shelf_mark"]
        )

        assert set(reported) == {"shelf_mark", "kids"}
        assert reported["shelf_mark"] != reported["kids"]

    def test_the_live_body_and_the_live_table_are_clean(self) -> None:
        assert (
            schemas_book._unconstructable_create_fields(
                schemas_book.CARRIED_AS_CHILD_ROWS,
                schemas_book.RESHAPED_FOR_ITS_COLUMN,
                {
                    name: field.annotation
                    for name, field in BookCreate.model_fields.items()
                },
                _book_columns(),
            )
            == {}
        )

    def test_the_two_cells_do_not_overlap(self) -> None:
        """A name in both is popped for two reasons, which the predicate cannot
        report because a dict holds one fault per name."""
        assert not set(schemas_book.CARRIED_AS_CHILD_ROWS) & set(
            schemas_book.RESHAPED_FOR_ITS_COLUMN
        )

    def test_the_popped_list_is_the_two_cells_and_nothing_else(self) -> None:
        """The route loops this, so a name dropped out of it is a field handed to
        the constructor and a name added to it is a field silently not stored."""
        assert set(schemas_book.POPPED_BEFORE_THE_CONSTRUCTOR) == set(
            schemas_book.CARRIED_AS_CHILD_ROWS
        ) | set(schemas_book.RESHAPED_FOR_ITS_COLUMN)


class TestEveryReshapedFieldIsWrittenAtTheRoute:
    """The half the import refusal cannot see, and it is the fault it calls worst.

    A name in `RESHAPED_FOR_ITS_COLUMN` is popped out of the dump, so the
    constructor never sees it and **nothing raises** if the route forgets to write
    it: the create answers 201 having stored nothing. Measured: deleting the
    `categories=` keyword from `_create_book` leaves
    `_unconstructable_create_fields` returning `{}`, the module importing clean and
    every partition arm green.

    So this reads the route's own source. The security seat asked for it in the
    design round, shaped on `TestTheSignatureIsTheBound`, which partitions a model's
    fields against the names a writer's loop walks.
    """

    @staticmethod
    def _constructor_keywords() -> set[str]:
        """Every keyword of the one `Book(...)` call in `_create_book`.

        Read off the function's own source rather than from a list here, so a
        keyword renamed or moved is visible. `Book(` is the single constructor site
        in the application, which `TestTheSchemaModuleRefusesToImport` relies on
        too.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(books_router._create_book)))
        return {
            keyword.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Book"
            for keyword in node.keywords
            if keyword.arg is not None
        }

    def test_the_route_builds_a_book_at_all(self) -> None:
        """The baseline. A finder that matched nothing would satisfy the arm below
        by having no keywords to disagree with."""
        keywords = self._constructor_keywords()

        assert keywords, "no `Book(...)` call found in the create route"
        assert "added_by_user_id" in keywords

    def test_every_reshaped_name_is_a_keyword_of_that_call(self) -> None:
        """The arm. A popped name with no assignment stores nothing and says
        nothing."""
        keywords = self._constructor_keywords()
        unwritten = sorted(
            name
            for name in schemas_book.RESHAPED_FOR_ITS_COLUMN
            if name not in keywords
        )

        assert unwritten == [], (
            "These fields are popped out of the dump before the constructor and "
            "never written back, so the route accepts them and stores nothing: "
            f"{unwritten}. Each needs a keyword on the `Book(...)` call."
        )

    def test_no_child_row_name_is_a_keyword_of_that_call(self) -> None:
        """The other direction, which the arm above cannot see. A name carried as
        child rows must NOT reach the constructor: `Book.classifications` is a
        relationship, so handing it plain dicts raises rather than building rows."""
        keywords = self._constructor_keywords()
        wrongly_written = sorted(
            name for name in schemas_book.CARRIED_AS_CHILD_ROWS if name in keywords
        )

        assert wrongly_written == [], (
            f"These are written after the insert as rows, not handed to the "
            f"constructor: {wrongly_written}"
        )


class TestTheSchemaModuleRefusesToImport:
    def test_it_imports_against_the_real_table(self) -> None:
        """The baseline arm. A module that raised whatever it was handed would
        pass the tests below and say nothing."""
        _load_schemas_book()

    def test_it_refuses_when_a_body_field_has_no_column(self, monkeypatch) -> None:
        """At import, not at the first create. A check at the first create fires
        on somebody's library, and the field it fires for is the one whose author
        never ran the route."""
        monkeypatch.setattr(
            models, "Book", _book_whose_table_has([c for c in _book_columns() if c != "location"])
        )
        with pytest.raises(RuntimeError, match="location"):
            _load_schemas_book()

    def test_it_refuses_when_the_reshaped_cell_loses_its_column(
        self, monkeypatch
    ) -> None:
        """The other side of the same name. Without `categories` on the table the
        reshape cell is a claim about a write nobody can perform."""
        monkeypatch.setattr(
            models,
            "Book",
            _book_whose_table_has([c for c in _book_columns() if c != "categories"]),
        )
        with pytest.raises(RuntimeError, match="categories"):
            _load_schemas_book()

    def test_the_refusal_says_what_to_do_about_it(self, monkeypatch) -> None:
        """A refusal that does not say what to do is one somebody deletes. It has
        to name the pop and the write together, because the fault that costs most
        is a pop with no write, which raises nothing at all."""
        monkeypatch.setattr(
            models, "Book", _book_whose_table_has([c for c in _book_columns() if c != "location"])
        )
        with pytest.raises(RuntimeError) as refusal:
            _load_schemas_book()

        assert "RESHAPED_FOR_ITS_COLUMN" in str(refusal.value)
        assert "pop" in str(refusal.value)
