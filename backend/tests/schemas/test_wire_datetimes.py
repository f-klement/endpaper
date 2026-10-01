"""Every dated field this API publishes carries an offset.

**Behavioural, so it is not a test of one object's identity.** It pushes a naive
datetime through each field's **own annotation** and asks what comes out of the
JSON form. `schemas.common.UtcDateTime` is how that is spelled today; a second
policy spelled another way passes this unchanged, and deleting the policy from
one field reddens by name whatever the spelling was.

**The rule it holds.** `format: date-time` in the published schema means RFC
3339, which requires an offset. Every column behind these fields is naive, so
nothing but the serialiser can supply one, and a consumer validating the schema
this repository publishes is right to reject a value without it.

**What it does not cover.** Whether the offset is the *right* one. These columns
hold naive values in whatever frame their writer used, which
`schemas.common._as_utc` states and bounds; this asks only that the wire says
which frame it claims, not that the claim is true.
"""

import importlib
import inspect
import pkgutil
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, PlainSerializer, TypeAdapter

import main
import schemas

#: The value pushed through every field. Naive, because that is what a column
#: hands the serialiser, and a value already carrying an offset would pass on
#: fields that do nothing.
A_NAIVE_INSTANT = datetime(2026, 8, 19, 10, 0, 0)

#: The two spellings RFC 3339 admits for zero offset. `Z` is what pydantic emits
#: for UTC; `+00:00` is accepted so that a policy written another way is not
#: reported for a difference nobody can observe.
ZERO_OFFSET = ("Z", "+00:00")

#: The keys a format can hide under. A nullable field is `anyOf` of the type and
#: `null`, so reading `format` off the top level alone finds none of them: that
#: reading reported twenty offenders on a clean tree.
COMPOSITE_KEYS = ("anyOf", "oneOf", "allOf")


def _declared_formats(node: Any) -> list[str]:
    """Every `format` under one property's schema, composites descended."""
    if isinstance(node, dict):
        found = [node["format"]] if "format" in node else []
        for key in COMPOSITE_KEYS:
            for member in node.get(key, []):
                found += _declared_formats(member)
        return found
    return []


def _declared_formats_deep(node: Any) -> list[str]:
    """Every `format` anywhere under a subtree, containers included.

    **This is what finds a dated value inside a container**, where
    `_declared_formats` cannot: `list[datetime]` puts the format under `items`,
    a mapping under `additionalProperties`, a tuple under `prefixItems`, and
    none of those is a composite key. Both escape arms read with this one, so a
    container is reported rather than invisible.

    **The narrow reader is kept for the rule's own population and that is a
    separate decision**, written at `_dated_fields`.

    Descending everything is safe here because a reference is a `$ref` string
    and carries no `format`, so a component reached from a path or from another
    component is not counted twice.
    """
    if isinstance(node, dict):
        found = [node["format"]] if "format" in node else []
        for value in node.values():
            found += _declared_formats_deep(value)
        return found
    if isinstance(node, list):
        found = []
        for value in node:
            found += _declared_formats_deep(value)
        return found
    return []


def _models_under_the_schemas_package() -> dict[type[BaseModel], str]:
    """Every pydantic model the schema package defines or re-exports.

    `pkgutil` over `schemas.__path__` rather than a file list, for the reason
    `tests/test_house_rules.py` gives at its own walk of this package: a model
    can be declared in any module there and an inclusion list of one file is
    what goes stale.

    **The count this returns is not load bearing and no arm reads it.** It moves
    with what has already been imported, because `vars()` sees a module's
    imports as well as its own classes: measured 122 from a bare walk and 127
    with the application imported first, over the same 41 fields. The pairs are
    the population; the models are how they are reached.
    """
    found: dict[type[BaseModel], str] = {}
    for info in pkgutil.iter_modules(schemas.__path__):
        module = importlib.import_module(f"schemas.{info.name}")
        for _name, obj in vars(module).items():
            if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
                found[obj] = obj.__name__
    return found


def _dated_fields(model: type[BaseModel]) -> list[str]:
    """The fields of one model whose serialisation schema declares `date-time`.

    **Serialisation mode, because that is the document a client validates
    against.** FastAPI writes the response half of the schema from this mode, so
    a field that declares the format here is one a response carries.

    **Narrow on purpose: a container of datetimes is not in this population.**
    `_emitted` pushes one naive instant through the field, and a `list[datetime]`
    has no such value to push, so the rule cannot speak about it. It is caught
    by `TestNothingDatedEscapesTheWalk` instead, which reads with the deep
    reader and reports exactly the fields this one cannot cover.
    """
    schema = model.model_json_schema(
        mode="serialization", ref_template="#/$defs/{model}"
    )
    properties = schema.get("properties") or {}
    return [
        name
        for name, node in properties.items()
        if "date-time" in _declared_formats(node)
    ]


def _emitted(model: type[BaseModel], field: str) -> object:
    """What this one field makes of a naive instant, in JSON form.

    Rebuilt as `Annotated[...]` from the field's own annotation and metadata
    rather than read off the model, so the subject is the field's declaration
    and nothing the model does around it.
    """
    info = model.model_fields[field]
    annotation = (
        Annotated[info.annotation, *info.metadata] if info.metadata else info.annotation
    )
    # Spelled out, because the annotation is only known at runtime and the type
    # checker otherwise infers `TypeAdapter[Never]` and refuses the argument.
    adapter: TypeAdapter[Any] = TypeAdapter(annotation)
    return adapter.dump_python(A_NAIVE_INSTANT, mode="json")


def _without_an_offset(models: dict[type[BaseModel], str]) -> list[str]:
    """The offenders, named, with what each emitted."""
    offenders = []
    for model, name in sorted(models.items(), key=lambda pair: pair[1]):
        for field in _dated_fields(model):
            emitted = _emitted(model, field)
            if not isinstance(emitted, str) or not emitted.endswith(ZERO_OFFSET):
                offenders.append(f"{name}.{field} emitted {emitted!r}")
    return offenders


def _population(models: dict[type[BaseModel], str]) -> list[tuple[str, str]]:
    return [(name, field) for model, name in models.items() for field in _dated_fields(model)]


def _covered_by_the_rule() -> set[tuple[str, str]]:
    """The (model, field) pairs the rule above actually pushes a value through."""
    return {
        (name, field)
        for model, name in _models_under_the_schemas_package().items()
        for field in _dated_fields(model)
    }


def _escaping(published: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Published dated properties no arm above covers.

    A function rather than an expression inside the arm, so a planted component
    can be handed to the same comparison the live document goes through. An arm
    that reasons about what it would report is the shape that let a container
    through in the first place.
    """
    return sorted(published - _covered_by_the_rule())


class TestEveryPublishedDatedFieldCarriesAnOffset:
    """The rule, and the three things that would let it pass while meaning
    nothing: an empty population, a detector that reports nobody, and a model
    the walk never reaches."""

    def test_no_dated_field_serialises_without_one(self) -> None:
        offenders = _without_an_offset(_models_under_the_schemas_package())
        assert not offenders, (
            "these fields declare `format: date-time` and serialise a naive "
            "datetime without an offset, which RFC 3339 does not admit and a "
            f"consumer validating the published schema rejects: {offenders}"
        )

    def test_it_found_fields_at_all(self) -> None:
        """The vacuity arm. Every assertion here is over a derived set, and an
        empty one satisfies all of them.

        A first version of this instrument reported population zero, clean and
        exit zero, because the thing that built the subject raised inside a bare
        except. An absence is not a green.
        """
        population = _population(_models_under_the_schemas_package())
        assert len(population) > 30, (
            f"only {len(population)} dated fields were found, where this API "
            "publishes dozens. The walk or the format reading has stopped "
            f"reaching them: {sorted(population)}"
        )

    def test_the_detector_reports_a_field_that_lost_the_policy(self) -> None:
        """The planted case, run on every run rather than once by hand.

        Without it the arm above is satisfied by a detector that reports
        nothing, which is the state this instrument was actually in twice while
        reading as correct. Both inhabitants of the nullable form are planted,
        because the policy sits inside the union member and a reading that
        looked only at the top level got the nullable case wrong in both
        directions.
        """

        class _LostIt(BaseModel):
            plain: datetime
            nullable: datetime | None = None

        reported = _without_an_offset({_LostIt: "_LostIt"})

        assert sorted(reported) == [
            "_LostIt.nullable emitted '2026-08-19T10:00:00'",
            "_LostIt.plain emitted '2026-08-19T10:00:00'",
        ], f"the detector did not report a bare datetime field: {reported}"

    def test_a_policy_written_another_way_passes(self) -> None:
        """The other half of the diagonal, and what makes this a rule rather
        than a test of one object's identity.

        A different function, no `when_used`, nothing imported from
        `schemas.common`: the field still declares `date-time` and still emits
        an offset, so it passes. Without this arm, replacing the policy with a
        correct one of another shape reddens the suite for no reason, which is
        how a guard comes to be deleted instead of read.
        """

        def another_way(value: datetime) -> datetime:
            return value if value.tzinfo else datetime.combine(
                value.date(), value.time(), UTC
            )

        class _AnotherSpelling(BaseModel):
            when: Annotated[
                datetime, PlainSerializer(another_way, return_type=datetime)
            ]

        assert _dated_fields(_AnotherSpelling) == ["when"], (
            "the format reading lost a field whose policy returns a datetime, "
            "which is the half that keeps the declaration in the schema"
        )
        assert not _without_an_offset({_AnotherSpelling: "_AnotherSpelling"})


class TestNothingDatedEscapesTheWalk:
    """The blast radius refusal.

    The rule above is derived over the schema package, so a model declaring a
    dated field anywhere else would be outside it with nothing to say so. These
    two close the escapes **from the application's own document** rather than
    from a list: whatever FastAPI publishes is what a client gets.
    """

    @staticmethod
    def _published_dated_properties() -> set[tuple[str, str]]:
        """**Read deep**, because this is the arm that has to see what the rule
        cannot: a dated value inside a list, a mapping or a tuple.

        Reading this with the narrow reader was the defect, and the shape of it
        is worth keeping: the escape arm exists to catch what the rule misses,
        and it shared the rule's blind spot, so a container field escaped both
        with nothing red. **Measured inert today**, the two readers disagree on
        no property of the live document, which is what makes the change loud
        later rather than noisy now.
        """
        spec = main.app.openapi()
        return {
            (component, prop)
            for component, body in spec["components"]["schemas"].items()
            for prop, node in (body.get("properties") or {}).items()
            if "date-time" in _declared_formats_deep(node)
        }

    def test_every_published_dated_property_is_covered_by_an_arm_above(self) -> None:
        """Measured zero escaping on 2026-10-01, re-derived here rather than
        written into prose.

        **Two ways a property reaches this list and the message names both.**
        No model under the schema package carries it, which is the original
        subject; or a model does and the field is a container, which the rule
        cannot push a value through. Either way nothing above speaks about it.

        **A container carrying the policy is refused too, and that is not in
        tension with the arm above requiring another spelling to pass.** That
        arm is about how the rule's own population is serialised; this one is
        about what the population leaves out. Measured: `list[UtcDateTime]` is
        seen by the deep reader, is absent from `_dated_fields`, and lands
        here. Admitting it means giving `_emitted` a value of that shape, which
        is a widening of the rule rather than a loosening of this refusal.

        The reverse direction is **not** asserted, and the difference is a base
        class: `ViewerFields` carries three dated fields and is published only
        through `BookOut`, which inherits them. A model the walk reaches and the
        document does not is covered for free.
        """
        escaped = _escaping(self._published_dated_properties())
        assert not escaped, (
            "these published properties declare `format: date-time` and no arm "
            "above covers them, either because no model under the schema "
            "package carries them or because the field is a container the rule "
            "cannot push a value through. A container is refused here rather "
            "than reported wrong: one that carries the policy lands in this "
            "list too, because the rule still has no value of that shape to "
            "push, so admitting it means extending `_emitted` rather than "
            f"loosening this: {escaped}"
        )

    def test_a_container_of_datetimes_is_reported_rather_than_invisible(self) -> None:
        """The planted case for this arm, and the defect it was written after.

        A `list[datetime]` puts its format under `items`, which the rule's own
        reader does not descend, so the field is absent from the rule's
        population. **That is acceptable only while this arm reports it**, and
        for one round it did not, because both read with the same reader.
        """

        class _Published(BaseModel):
            whens: list[datetime]

        node = _Published.model_json_schema(mode="serialization")["properties"]["whens"]

        assert _declared_formats(node) == [], (
            "the narrow reader now sees inside a container, which makes the "
            "split above pointless rather than wrong"
        )
        assert "date-time" in _declared_formats_deep(node)
        assert _dated_fields(_Published) == [], (
            "the rule's population grew a container field it cannot push a "
            "value through"
        )
        assert _escaping({("_Published", "whens")}) == [("_Published", "whens")]

    def test_no_operation_declares_a_dated_property_inline(self) -> None:
        """The second escape, which the component walk cannot see.

        A response schema written inline in a path rather than referenced is not
        a component at all. None exists today; one would be a dated field with
        no model behind it and no arm over it.
        """
        spec = main.app.openapi()
        inline = [
            path
            for path, item in spec["paths"].items()
            if "date-time" in _declared_formats_deep(item)
        ]
        assert not inline, (
            "these paths declare `format: date-time` inline rather than "
            f"through a component, so no model carries them: {inline}"
        )
