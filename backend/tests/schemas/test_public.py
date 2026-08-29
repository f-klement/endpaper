"""Tests for backend/schemas/public.py: the column boundary.

`Shelf.seen_by_the_public` filters **rows**. This module is what filters
**columns**, and the two are separate rules because a row filter is necessary
and not sufficient: a Book that is public still carries what the household paid
for it, which room it is in, who added it and whether anybody has read it.

`TestEveryFieldOnBookOutIsClassified` is the guard, and its shape is chosen so
it cannot go quiet. It does **not** check a list of forbidden names, which is an
enumeration over something open and would publish every field somebody forgets
to add to it. It checks that the partition is total: every field on `BookOut` is
either on `PublicBookOut` or in `WITHHELD` with a reason, so a field added to
`BookOut` tomorrow turns this red until a person decides which it is.

The rule that decides: a field is public when it is a fact about the **work** or
about the **object as a catalogue record**, and withheld when it is a fact about
a **member**, about the **household**, or about the **transaction** that brought
the book in.
"""

import pytest
from pydantic import BaseModel

from enums import BookSort
from schemas import (
    BookOut,
    PublicBookOut,
    PublicBookSort,
    PublicClassificationOut,
    PublicTagOut,
    TagOut,
)
from shelf import order_for


def _public_models() -> set[type[BaseModel]]:
    """Every model reachable from `PublicBookOut`, itself included.

    Walked through `model_fields`, following any annotation that mentions a
    `BaseModel` subclass, so a nested list, a union and an optional are all
    followed rather than only a bare field. This is what the first version of
    this file did not have: it read `PublicBookOut.model_fields` and stopped, so
    `classifications` pointed at the signed in `ClassificationOut` and a field
    added there would have published with nothing failing.
    """
    seen: set[type[BaseModel]] = set()
    pending: list[type[BaseModel]] = [PublicBookOut]
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        for field in model.model_fields.values():
            for candidate in _models_in(field.annotation):
                pending.append(candidate)
    return seen


def _models_in(annotation: object) -> list[type[BaseModel]]:
    """Every `BaseModel` an annotation mentions, at any depth.

    `get_args` recursively rather than a match on `list[...]`, because the shape
    is open: `list[X]`, `X | None`, `dict[str, X]` and a nested pair of those are
    all things a field may legitimately be, and enumerating the containers is
    the shape of guard this repository has had to rewrite four times.
    """
    import typing

    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.append(annotation)
    for argument in typing.get_args(annotation):
        found.extend(_models_in(argument))
    return found

#: Every field on `BookOut` that a public reader does not get, and why.
#:
#: **The reason is the deliverable.** This rule decides nothing on its own: it
#: says a person has classified each field, and the classification is only worth
#: as much as the sentence beside it. A reason that is really a restatement of
#: the field name has classified nothing.
WITHHELD: dict[str, str] = {
    # ── Facts about a member ──────────────────────────────────────────────
    "added_by": "the member who added it, by name",
    "my_status": "the caller's reading status, and there is no caller",
    "my_rating": "the caller's rating out of five, and there is no caller",
    "my_started_at": "when the caller started it",
    "my_finished_at": "when the caller finished it",
    "my_progress_page": "how far the caller has read",
    "my_progress_percent": "the same fact derived",
    "my_progress_recorded_at": "when the caller last recorded a position",
    "my_wants_to_discuss": "whether the caller offered to talk about it",
    "discuss_with": "every member who offered to, by name",
    "active_loan": "who has it out and when it is due, both about people",
    # ── Facts about the household ─────────────────────────────────────────
    "location": (
        "which room it is in. In library mode this column holds a shelf mark "
        "and a patron would want it, but the column is shared with household "
        "mode and the publish switch does not change what is in it. Publishing "
        "a room list is not a trade this makes on a household's behalf; a shelf "
        "mark for patrons wants its own field"
    ),
    "ownership": "owned, wanted or borrowed: the household's relation to the object",
    "lending": "whether the household will lend it, named out of scope by #95",
    "condition": "how battered this household's copy is",
    "is_private": (
        "always false on a published row, so it carries no information and "
        "carrying it would invite a client to believe it could ever be true here"
    ),
    "deleted_at": "always null on a published row, for the same reason",
    "collection_id": (
        "how this household organises its shelves, by an id nothing publishes a "
        "name for. It was briefly accepted as a filter on the public listing and "
        "cut: the ids are consecutive, so the filter is enumerable, and what it "
        "enumerates is the grouping this field withholds"
    ),
    "collection_name": "the name the household gave that shelf",
    "added_at": "when this household acquired it",
    # ── Facts about the transaction ───────────────────────────────────────
    "purchase_price_minor": "what the household paid",
    "purchase_currency": "which currency the household paid in",
    "purchased_at": "the date the household bought it",
    "purchase_source": "which shop or seller the household bought it from",
    # ── Cannot be computed here, rather than must not be shown ────────────
    "copy_count": (
        "counts the copies **the caller may see**, so it takes a viewer and a "
        "public reader has none. A count over the public shelf would be a "
        "different number wearing the same name"
    ),
    "google_books_id": (
        "a lookup key for this app's own enrichment rather than a catalogue "
        "identifier a reader has any use for. The ISBN is the identifier that is "
        "published"
    ),
    "refused_identifiers": (
        "empty on every response but two, and both of those are enrichment "
        "writes no public reader can make. It reports what this library declined "
        "to believe, which is an internal cataloguing argument"
    ),
}


class TestEveryFieldOnBookOutIsClassified:
    def test_the_partition_is_total(self):
        """Every `BookOut` field is published or withheld, and nothing is both.

        **This is the whole guard.** It is not a list of forbidden names, which
        would be an enumeration over something open: a field added to `BookOut`
        and forgotten would simply not be on it. It is a partition, so a new
        field fails until somebody classifies it, and there is no answer that
        happens by default.
        """
        published = set(PublicBookOut.model_fields)
        withheld = set(WITHHELD)
        every = set(BookOut.model_fields)

        unclassified = every - published - withheld
        both = published & withheld
        stale = withheld - every

        assert (unclassified, both, stale) == (set(), set(), set()), (
            f"unclassified: {sorted(unclassified)}\n"
            f"published and withheld at once: {sorted(both)}\n"
            f"withheld but no longer on BookOut: {sorted(stale)}\n\n"
            "A field on BookOut is a fact about the work, the object as a "
            "catalogue record, a member, the household, or the transaction. The "
            "first two are published and go on PublicBookOut; the rest are "
            "withheld and go in WITHHELD with the reason. If you cannot write "
            "the reason in a sentence, it is the wrong field."
        )

    def test_the_public_payload_invents_nothing(self):
        """Every published field is a projection of `BookOut`, never a new fact.

        A public model free to invent fields could publish a computed one that
        no signed in reader has ever seen, and nothing above would notice: the
        partition only looks at what `BookOut` has.
        """
        assert set(PublicBookOut.model_fields) <= set(BookOut.model_fields)

    def test_every_withheld_field_carries_a_reason(self):
        """The list is only worth its sentences. An empty one is a field
        somebody moved out of the way rather than classified."""
        empty = sorted(name for name, reason in WITHHELD.items() if len(reason) < 20)
        assert empty == [], f"These entries do not say why: {empty}"

    def test_no_field_beginning_my_is_published(self):
        """A second, independent statement of one arm of the rule.

        The partition asks a person; this asks the naming convention. Every
        per member field on `BookOut` is spelled `my_*`, so a new one added and
        wrongly published fails here even if it was classified wrongly above.
        """
        assert [f for f in PublicBookOut.model_fields if f.startswith("my_")] == []


class TestAPublishedCoverIsOneThePublicCanAlreadyReach:
    """`cover_url` holds one of two things, and only one of them is public."""

    @pytest.mark.parametrize(
        "stored",
        ["/covers/12.jpg", "http://covers.openlibrary.org/b/id/1.jpg", "", None],
    )
    def test_anything_that_is_not_an_https_url_is_dropped(self, stored):
        """The local path is served behind `book_for_read`, so publishing it
        would advertise an image a public reader cannot fetch. `http://` is
        dropped as well: a mixed content image on an https page does not render
        either, so publishing it has the same result and one fewer promise.
        """
        assert PublicBookOut(id=1, title="T", cover_url=stored).cover_url is None

    def test_a_catalogue_supplied_https_url_survives(self):
        """The diagonal: without it the rule above is satisfied by dropping
        every cover, which is a different behaviour that would also pass."""
        url = "https://covers.openlibrary.org/b/id/1.jpg"
        assert PublicBookOut(id=1, title="T", cover_url=url).cover_url == url


class TestThePublicPayloadParsesTheSameWayTheSignedInOneDoes:
    def test_categories_split_on_the_semicolon_and_not_the_comma(self):
        """Google's own category names contain commas ("Fiction, general"), so
        splitting on one shreds them. Restated here rather than inherited
        because this model deliberately does not inherit, and a restated rule is
        a rule that can drift."""
        book = PublicBookOut(id=1, title="T", categories="Fiction, general;Science")
        assert book.categories == ["Fiction, general", "Science"]

    def test_the_credit_line_is_split_into_people(self):
        book = PublicBookOut(id=1, title="T", author="Ann Lee, Bo Ng")
        assert book.authors == ["Ann Lee", "Bo Ng"]

    def test_authors_passed_in_are_overwritten_rather_than_believed(self):
        """`author` is the fact and `authors` is that fact parsed, so the two
        cannot be made to disagree by a caller."""
        book = PublicBookOut(id=1, title="T", author="Ann Lee", authors=["Somebody Else"])
        assert book.authors == ["Ann Lee"]


class TestAPublicTagIsNarrowerThanATag:
    def test_it_publishes_neither_the_delete_control_nor_a_count(self):
        """`is_predefined` drives a control no public reader has, and
        `book_count` is a count over the whole catalogue that would have to be
        recomputed against the public shelf to be true."""
        assert set(PublicTagOut.model_fields) < set(TagOut.model_fields)
        assert "book_count" not in PublicTagOut.model_fields
        assert "is_predefined" not in PublicTagOut.model_fields

    def test_it_keeps_the_key_so_a_seeded_tag_can_be_translated(self):
        """The public catalogue is localised like the signed in one, and the
        key is how a seeded tag is shown in the reader's language."""
        assert "key" in PublicTagOut.model_fields



class TestEveryPublicSortOrdersByAPublishedColumn:
    """A sort is a read of the column it sorts by, in one request.

    `BookSort.NEWEST` orders by `added_at`, which is withheld because it says
    when this household acquired the book. Offering it publicly would hand a
    stranger the whole acquisition order of the catalogue at once, which is a
    stronger version of the thing the filter list already refuses: a filter over
    a column nobody can see reads that column one query at a time.

    So the check is not a list of forbidden sorts. It compiles the clauses each
    public sort actually produces and asks whether every column named in them is
    on `PublicBookOut`, which is the same question the partition above asks,
    applied to the ORDER BY.
    """

    @staticmethod
    def _columns(sort: BookSort) -> set[str]:
        """The `books` columns one sort orders by, off the compiled clauses."""
        import re

        rendered = " ".join(str(clause) for clause in order_for(sort))
        return set(re.findall(r"books\.(\w+)", rendered))

    def test_the_clauses_name_columns_this_rule_can_read(self):
        """Without this the rule below passes on an empty set, which is what a
        change in how SQLAlchemy renders a clause would produce."""
        assert self._columns(BookSort.TITLE_ASC) == {"title", "id"}

    def test_every_public_sort_names_only_published_columns(self):
        published = set(PublicBookOut.model_fields)
        offenders = {
            sort.value: sorted(self._columns(sort.as_book_sort()) - published)
            for sort in PublicBookSort
            if self._columns(sort.as_book_sort()) - published
        }
        assert offenders == {}, (
            f"These public sorts order by a column the public payload withholds: "
            f"{offenders}. An ordering is a read of the column it orders by, and "
            "one request returns the whole ordering. Either publish the column or "
            "take the sort out of PublicBookSort."
        )

    def test_the_sort_that_was_left_out_is_the_one_that_would_fail(self):
        """The diagonal. Without it the rule above would pass on a
        `PublicBookSort` that had quietly become empty, or on a `_columns` that
        returned nothing."""
        assert BookSort.NEWEST.value not in {sort.value for sort in PublicBookSort}
        assert self._columns(BookSort.NEWEST) - set(PublicBookOut.model_fields) == {
            "added_at"
        }

    def test_every_public_sort_is_a_real_book_sort(self):
        """The values are the same strings on purpose: the subset is a narrowing
        of one vocabulary rather than a second one."""
        for sort in PublicBookSort:
            assert sort.as_book_sort().value == sort.value



class TestThePublicPayloadIsBuiltOnlyFromPublicModels:
    """The rule the first draft applied to tags and not to classifications.

    `PublicTagOut` exists so that a field added to `TagOut` cannot reach a
    public reader. `classifications` then pointed straight at the signed in
    `ClassificationOut`, so the same hole was open one field along, and the
    library mode epic extends classifications next.

    So the rule is structural rather than a habit: **every model in the public
    payload's graph is declared in `schemas/public.py`**. A shared model is
    caught wherever it is nested and however deeply.
    """

    def test_the_walk_finds_the_models_it_is_supposed_to(self):
        """A guard that inspects nothing reads as coverage. Named models rather
        than a count, because a count is satisfied by finding the wrong three."""
        found = _public_models()
        assert PublicBookOut in found
        assert PublicTagOut in found, "the walk does not follow list[...] fields"
        assert PublicClassificationOut in found

    def test_every_model_in_the_payload_is_declared_in_the_public_module(self):
        outsiders = sorted(
            f"{model.__module__}.{model.__name__}"
            for model in _public_models()
            if model.__module__ != "schemas.public"
        )
        assert outsiders == [], (
            f"These models reach a public reader from outside schemas/public.py: "
            f"{outsiders}. A shared model is one somebody can widen without a "
            "review of what that publishes. Declare a public counterpart, as "
            "PublicTagOut and PublicClassificationOut already are."
        )

    def test_what_serialises_is_exactly_what_is_classified(self):
        """**The check that closes the family, on every model rather than the
        top level one.**

        Every guard above reads `model_fields`, which is the declared fields and
        nothing else. Three shapes put a value on the wire without appearing
        there, and all three were demonstrated to publish the withheld shelf
        location with the rest of this file green: an alias, a
        `@computed_field`, and a `@model_serializer`. The router's own wire test
        catches the first two on `PublicBookOut`, and only there: it reads
        `set(body)`, which is the **top level** keys, so the same shapes on
        `PublicTagOut` or `PublicClassificationOut` were seen by nothing.

        So this serialises each model in the graph and compares the keys that
        come out against the fields that were classified. It needs no list of
        shapes, which is the point: it asks what actually leaves, and a fourth
        way of adding a key is caught by the same assertion.
        """
        offenders: list[str] = []
        for model in _public_models():
            # Every declared field given a value, because `model_construct()`
            # with no arguments leaves the required ones unset and they are then
            # absent from the dump for a reason that has nothing to do with this
            # rule. `by_alias=True` because that is how FastAPI serialises a
            # response model, so this reads the keys that actually go on the
            # wire. That catches a `serialization_alias` here as well as by its
            # own rule; a `validation_alias` renames the **input** and is
            # invisible to any dump, which is why the alias rule below tests all
            # three spellings rather than leaning on this one. Measured: of the
            # three shapes attacked, this catches the computed field and the
            # model serializer, and the alias rule catches the alias.
            blank = model.model_construct(**dict.fromkeys(model.model_fields))
            produced = set(blank.model_dump(by_alias=True))
            declared = set(model.model_fields)
            for extra in sorted(produced - declared):
                offenders.append(f"{model.__name__}.{extra} (serialised, never classified)")
            for missing in sorted(declared - produced):
                offenders.append(f"{model.__name__}.{missing} (classified, never serialised)")

        assert offenders == [], (
            f"What these models put on the wire is not what this file classified: "
            f"{offenders}.\n\n"
            "A computed field, a model serializer and an alias each add or rename "
            "a key without touching `model_fields`, so the partition above "
            "describes a payload that is not the one sent. Every published fact "
            "has to be a declared field, or the classification is fiction."
        )

    def test_no_public_model_computes_a_field(self):
        """The same rule stated once more, structurally, on the shape most
        likely to be reached for: `@computed_field` is how somebody adds a
        derived value without thinking of it as a field."""
        offenders = sorted(
            f"{model.__name__}.{name}"
            for model in _public_models()
            for name in model.model_computed_fields
        )
        assert offenders == [], (
            f"These public models compute a field: {offenders}. A computed field "
            "is published and is not in `model_fields`, so nothing above sees it."
        )

    def test_no_public_model_overrides_its_serialiser(self):
        """`@model_serializer` replaces the whole payload, so every field level
        rule in this file stops describing what is sent.

        Read off `__pydantic_decorators__`, which is where pydantic records the
        decorator. **The first version of this check probed an attribute name
        that does not exist**, so it inspected nothing and passed while a model
        serializer on a nested model published the withheld shelf location. It
        was the wire test above that caught that, and this one is here as the
        second, independent catch rather than as the only one, which is the
        arrangement that made the hole visible in the first place.
        """
        offenders = sorted(
            f"{model.__name__}.{name}"
            for model in _public_models()
            for name in model.__pydantic_decorators__.model_serializers
        )
        assert offenders == [], (
            f"These public models define a model serializer: {offenders}. It "
            "replaces the whole payload, so every field level rule in this file "
            "stops describing what is sent."
        )

    def test_this_rule_can_see_a_model_serializer_at_all(self):
        """The check that stops the rule above going vacuous a second time.

        It is asserted against a model built here rather than against one of
        ours, because the whole point is that none of ours has one.
        """
        from pydantic import BaseModel, model_serializer

        class Decorated(BaseModel):
            a: int = 1

            @model_serializer
            def _dump(self) -> dict:
                return {}

        assert set(Decorated.__pydantic_decorators__.model_serializers) == {"_dump"}

    def test_no_public_field_carries_an_alias(self):
        """**The evasion that defeated all four of the original checks.**

        They read `model_fields`, whose keys are the **attribute** names, and
        pydantic serialises under the alias. Demonstrated:
        `publisher: str | None = Field(validation_alias="location")` put the
        withheld shelf location on the wire under the key `publisher` and passed
        every one of them. The same family bit another trio this wave through
        `serialization_alias`, in the other direction.

        No public model carries an alias today, so this is a rule that none may
        rather than a repair. Both directions and the shorthand, because they
        are three spellings of the same thing and forbidding one is the version
        that looks right.
        """
        offenders = sorted(
            f"{model.__name__}.{name}"
            for model in _public_models()
            for name, field in model.model_fields.items()
            if field.alias or field.validation_alias or field.serialization_alias
        )
        assert offenders == [], (
            f"These public fields carry an alias: {offenders}. Every guard in "
            "this file reads `model_fields`, whose keys are attribute names, "
            "while pydantic reads and writes the alias, so an alias makes the "
            "classification above describe a payload that is not the one sent."
        )
