"""A route that sends bytes declares what those bytes are.

Four documented operations sent something other than JSON and declared
`application/json` with an empty schema: both export arms of
`GET /api/books/export`, `GET /api/backup`, and both cover routes. So the
committed document, which the TypeScript client is generated from and which a
third party may read, promised a JSON body under every one of them.

**The mirror of `tests/routers/test_auth.py::TestARouteThatSendsNoBodyDocumentsNone`,
and together the two cover the routes *annotated* to build their own
`Response`**, which is narrower than every route that builds one and is what
the walk below can see. That one takes the routes annotated **exactly**
`Response`, which in this API is the answer that carries nothing, and forbids
them content. This one takes the routes annotated with a **subclass**, which is
a body and a media type of its own, and requires them content that is not JSON.

**What made the fix look done when it was not.** Declaring the types with
`responses=` alone leaves `application/json` in the 200 *beside* them, because
FastAPI derives the 200's content from `response_class.media_type` and the
default class is `JSONResponse`. Declaring `response_class=StreamingResponse`
alone produces no content at all, which trades a wrong promise for none.
`Response.media_type` is `None`, so only the plain class **together with** the
dictionary leaves the declaration as the whole answer, and
`test_every_such_route_declares_something` is the arm that catches the second
of those two, which a diff review passes.

**These rules are per declared answer, not per route.** A cover route declares
a 206 as well as a 200, because `FileResponse` honours a `Range` header, so
"the route's answer" stopped being one thing. The helper that used to choose a
key refused to choose when there were two, which made the obvious declaration
red; the four cells at `_carries_a_representation` replace it with a rule per
key. They are total by construction; `TestThePartitionIsOne` holds the one
pair whose disjointness rests on a fact in another file.
"""

import typing
from typing import Any, Final

import pytest
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.routing import APIRoute
from fastapi.utils import is_body_allowed_for_status_code

import main
import routers.covers as covers_router
import settings_store
import tests.test_errors as the_refusal_rule
from enums import EXPORT_MEDIA_TYPES, SettingKey
from routers.backup import ARCHIVE_MEDIA_TYPE
from tests.helpers import PNG_BYTES

#: The one type this class exists to keep off a route that does not send it.
JSON = "application/json"


def _routes_answering_with_a_body_of_their_own() -> list[Any]:
    """Every documented route whose handler builds a body-carrying `Response`.

    **A subclass, never the base class exactly**: a bare `Response` here is the
    answer that carries nothing, and the rule about those is the opposite one
    named in this module's docstring.

    **The population is the return annotation, so say what that misses.** Two
    shapes, and they are not equally knowable.

    A route with **no** return annotation is outside the walk, and there is no
    such route: `test_every_documented_route_is_annotated` asserts that rather
    than this sentence claiming it, because a described reason rots where an
    asserted one reddens.

    A route annotated with a **schema model** that nonetheless returns a
    `Response` at runtime is also outside it, and **this docstring deliberately
    does not say how many of those there are.** Deriving the set means matching
    source text for a return of a constructor, which is the one shape this
    repository has measured wrong every time it has tried it. The mechanism is
    stated and the extent is refused.

    What makes the annotation the right key rather than a convenient one is that
    the sibling rule in `tests/routers/test_auth.py` uses the same key, so the
    two cannot overlap, and what the key does not see is outside both rules
    rather than between them.

    `main.iter_api_routes` rather than `app.routes`, because `include_router`
    appends a wrapper rather than splicing the child's routes in.
    """
    return [
        route
        for route in main.iter_api_routes(main.app.routes)
        if _answers_with_a_body_of_its_own(route)
    ]


def _answers_with_a_body_of_its_own(route: Any) -> bool:
    """Membership of the walk above, as one predicate.

    Its own function so the arms about the framework can put a throwaway app
    through the same test the live one goes through. A second copy of the
    expression would be two instruments reading as one.
    """
    annotation = typing.get_type_hints(route.endpoint).get("return")
    return bool(
        route.include_in_schema
        and isinstance(annotation, type)
        and issubclass(annotation, Response)
        and annotation is not Response
    )


def _label(route: Any) -> str:
    """**Every method the route carries, not one of them.**

    This read `sorted(route.methods)[0]` while the key helper beside it read
    `next(iter(route.methods))`, which is arbitrary over a set: two instruments
    naming different operations while reading as one. Latent, because no
    documented route declares two methods today, and silent on the day one
    does.
    """
    return f"{' '.join(sorted(route.methods))} {route.path}"


def _answer_label(route: Any, method: str, key: str) -> str:
    """One declared answer, which is what every rule below is about."""
    return f"{method.upper()} {route.path} [{key}]"


def _answer_class(route: Any) -> type:
    """The `Response` subclass this route is annotated to return."""
    return typing.get_type_hints(route.endpoint)["return"]


def _written_by_the_framework(key: str) -> bool:
    """FastAPI writes 422 from the route's own parameter validation rather than
    from anything the route declares, so no rule about what a route promises
    has anything to say about it. The refusal rule next door excludes it by
    name for the same reason.
    """
    return key == "422"


def _the_refusal_rules_business(key: str) -> bool:
    """A key this module deliberately says nothing about.

    Its members are everything at or above 400 and every key that is not a
    plain number: `4XX`, `default`, and a ranged success such as `2XX`.
    `tests/test_errors.py::TestTheDocumentEnumeratesNoRefusal` refuses all of
    them outright, so a route declaring one is red there before anything here
    could have an opinion.

    **Its own predicate, called rather than restated, which is what turns the
    interlock from a paragraph into one object.** Both ends used to describe
    the division of labour in prose, and prose at two ends is two chances to
    disagree: the helper this replaces had to add a sentence saying its own
    refusal was the exception to the sentence next door. This cell is now that
    rule's population by construction, so a key cannot be stepped over here
    and allowed there.
    """
    return the_refusal_rule.TestTheDocumentEnumeratesNoRefusal._is_a_refusal(key)


def _carries_a_representation(key: str) -> bool:
    """Whether the document says this answer is a body at all.

    **Two halves, and FastAPI's own instrument is only one of them.**
    `is_body_allowed_for_status_code` refuses a body to 204, 205 and 304, which
    is what the sibling vacuity arm in `tests/routers/test_auth.py` imports it
    for. It says **yes** to 307, measured against this worktree's FastAPI, so a
    redirect passed it while correctly declaring nothing. A redirect's answer is
    its `Location`, so the other half is that the status is a success at all.

    It also says yes to `2XX`, `4XX` and `default`, which is why the two cells
    above are asked first: after them `int` cannot raise and cannot be handed a
    range.
    """
    return (
        not _written_by_the_framework(key)
        and not _the_refusal_rules_business(key)
        and 200 <= int(key) < 300
        and is_body_allowed_for_status_code(key)
    )


def _answers_without_a_body(key: str) -> bool:
    """The remainder below 400: 204, 205, 304 and every redirect.

    **Written as the remainder rather than as a list of statuses**, so the
    cells are **total** by construction: this one is the complement of the
    other three, and there is no key for all four to miss.

    **Disjointness is not all by construction, and calling it that is one rung
    too strong.** This cell cannot overlap the other three, because it is
    defined as their negation. Cells one and two cannot overlap only because
    `TestTheDocumentEnumeratesNoRefusal._is_a_refusal` opens by excluding the
    validation key, which is a fact in another file rather than a property of
    anything here. That pair is **tested**, by `TestThePartitionIsOne`, where
    one arm is complete cover for it because the framework's cell holds
    exactly one key.
    """
    return not (
        _written_by_the_framework(key)
        or _the_refusal_rules_business(key)
        or _carries_a_representation(key)
    )


def _documented_answers(route: Any, schema: dict[str, Any]) -> list[tuple[str, str]]:
    """Every (method, response key) this document files for this route, less
    the one the framework writes.

    **The path item decides which methods are documented**, rather than
    `route.methods` alone: a method on the route with no operation in the
    document would be a `KeyError` here, and a guard that raises has stopped
    being a guard. That the intersection is not empty is asserted rather than
    assumed, since an empty one would make every rule below silently vacuous
    for that route.
    """
    operations = schema["paths"][route.path]
    documented = sorted(
        method for method in (name.lower() for name in route.methods) if method in operations
    )

    assert documented, (
        f"{_label(route)} is documented and this schema files no operation "
        "under any of its methods, so every rule in this module steps over it"
    )

    return [
        (method, key)
        for method in documented
        for key in sorted(operations[method]["responses"])
        if not _written_by_the_framework(key)
    ]


def _content(route: Any, schema: dict[str, Any], method: str, key: str) -> dict[str, Any]:
    return schema["paths"][route.path][method]["responses"][key].get("content", {})


def _bodies_declaring_nothing(route: Any, schema: dict[str, Any]) -> list[str]:
    """Answers that are a body where the document names no type for them."""
    return [
        _answer_label(route, method, key)
        for method, key in _documented_answers(route, schema)
        if _carries_a_representation(key) and not _content(route, schema, method, key)
    ]


def _bodies_declaring_json_they_do_not_send(route: Any, schema: dict[str, Any]) -> list[str]:
    """Answers declaring JSON where the route's own class sends something else.

    **The exemption is the class's own `media_type`, derived rather than
    listed.** `-> JSONResponse` is the ordinary way to put a status or a header
    on a JSON body, it is a `Response` subclass and it enters the walk above;
    refused for declaring `application/json`, this rule would forbid the one
    media type such a route actually sends. Keying on what the class says it
    sends exempts any subclass spelling the same thing and exempts nothing
    else.

    A function rather than an expression inside the arm, so
    `TestTheCellsNoLiveRouteReaches` drives the same code the live arm does.
    """
    if getattr(_answer_class(route), "media_type", None) == JSON:
        return []
    return [
        f"{_answer_label(route, method, key)} declares "
        f"{sorted(_content(route, schema, method, key))}"
        for method, key in _documented_answers(route, schema)
        if _carries_a_representation(key) and JSON in _content(route, schema, method, key)
    ]


def _non_bodies_declaring_content(route: Any, schema: dict[str, Any]) -> list[str]:
    """Answers the framework will send no body under, carrying a declared type.

    **This is what the plural rule refuses that the singular one did not.** The
    old assertion reddened on any second key at all, so it never reached the
    question of what that key declared; the cells do, and 204, 205, 304 and
    every redirect promise nothing. Unreachable live, like both exemptions
    above, so `TestTheCellsNoLiveRouteReaches` is what holds it.
    """
    return [
        f"{_answer_label(route, method, key)} declares "
        f"{sorted(_content(route, schema, method, key))}"
        for method, key in _documented_answers(route, schema)
        if _answers_without_a_body(key) and _content(route, schema, method, key)
    ]


class TestThePartitionIsOne:
    """Four cells over every response key, total by construction and disjoint
    by construction for every pair but one.

    Which pair, and why it is tested instead, is at `_answers_without_a_body`.

    The helper these replace **chose** one key per route and asserted there was
    only one to choose, which made declaring a second success key red whatever
    the second key said. Two of the four cells are the same predicates that
    helper's callers used; the other two are the keys it refused rather than
    filed.

    **The keys below are spellings, not a population.** No live operation
    declares most of them, and the point of driving them here is that the cells
    answer for a key nobody has written yet: the totality is a property of how
    the last one is defined, not of this list being complete.
    """

    #: Two per cell at least, plus the shapes a later specification could add.
    KEYS: Final = (
        "200",
        "201",
        "202",
        "206",
        "299",
        "204",
        "205",
        "304",
        "301",
        "307",
        "400",
        "416",
        "429",
        "500",
        "422",
        "2XX",
        "3XX",
        "4XX",
        "default",
        "",
    )

    @staticmethod
    def _cells(key: str) -> list[str]:
        return [
            name
            for name, holds in (
                ("written by the framework", _written_by_the_framework(key)),
                ("the refusal rule's", _the_refusal_rules_business(key)),
                ("a body", _carries_a_representation(key)),
                ("a success that is not a body", _answers_without_a_body(key)),
            )
            if holds
        ]

    @pytest.mark.parametrize("key", KEYS)
    def test_every_key_lands_in_exactly_one_cell(self, key: str) -> None:
        assert self._cells(key) != [], f"{key!r} is in no cell, so every rule steps over it"
        assert len(self._cells(key)) == 1, f"{key!r} is in {self._cells(key)}"

    def test_no_cell_is_empty(self) -> None:
        """The vacuity arm. A cell nothing reaches is a rule about nothing, and
        the arm above is satisfied by any three of the four."""
        reached = {cell for key in self.KEYS for cell in self._cells(key)}

        assert len(reached) == 4, sorted(reached)


class TestARouteThatSendsBytesDeclaresThem:
    def test_some_route_sends_a_body_it_builds_itself(self) -> None:
        """The vacuity arm. This rule goes silent the day nothing matches the
        walk, which a refactor to `Annotated` returns or to a helper that
        returns `Any` would do without touching a decorator.

        **Filtered to the answers that are a body, so the cells cannot empty
        the rule quietly.** A tree whose only annotated routes were redirects
        and 204s would satisfy an unfiltered version of this while the arms
        below were about nothing."""
        schema = main.app.openapi()
        answerable = [
            _answer_label(route, method, key)
            for route in _routes_answering_with_a_body_of_their_own()
            for method, key in _documented_answers(route, schema)
            if _carries_a_representation(key)
        ]

        assert answerable, (
            "no documented route is annotated to return a Response subclass "
            "under a status that carries a body, so this rule is about nothing"
        )

    def test_every_documented_route_is_annotated(self) -> None:
        """The half of this rule's blind spot that is a property rather than a
        guess. An unannotated handler is outside the walk above and outside the
        sibling rule as well, so it would fall between the two with nothing
        saying so."""
        unannotated = [
            _label(route)
            for route in main.iter_api_routes(main.app.routes)
            if route.include_in_schema
            and "return" not in typing.get_type_hints(route.endpoint)
        ]

        assert unannotated == [], (
            "These documented routes declare no return type, so neither this "
            "rule nor the one forbidding content to a bare `Response` can see "
            "them, and a route sending bytes under a JSON declaration would sit "
            "between the two unnoticed:\n  " + "\n  ".join(unannotated)
        )

    def test_every_such_route_declares_something(self) -> None:
        """The arm that catches the shape a diff review passes.

        `response_class=StreamingResponse` with no `responses=` removes the
        wrong media type and declares nothing in its place, which reads as the
        fix and is a document that has stopped saying anything at all.

        **Per answer, so a second success key cannot arrive empty.** A 206
        declared as a description and no content reads as done and tells a
        client nothing; the singular helper could not see it, because it
        refused the route outright for having two keys."""
        schema = main.app.openapi()
        silent = [
            offender
            for route in _routes_answering_with_a_body_of_their_own()
            for offender in _bodies_declaring_nothing(route, schema)
        ]

        assert silent == [], (
            "These routes send a body and the schema declares no content type "
            "for it, so a reader of the document learns less than before:\n  "
            + "\n  ".join(silent)
        )

    def test_none_of_them_declares_json(self) -> None:
        """The exemption for a class that does send JSON is at
        `_bodies_declaring_json_they_do_not_send`, with the reason it is a
        property rather than a name."""
        schema = main.app.openapi()
        lying = [
            offender
            for route in _routes_answering_with_a_body_of_their_own()
            for offender in _bodies_declaring_json_they_do_not_send(route, schema)
        ]

        assert lying == [], (
            "These build their own response with a media type of their own and "
            f"the schema says {JSON}, so the generated client, anything "
            "validating the document and any third party reading it are all "
            "wrong about what arrives:\n  " + "\n  ".join(lying) + "\n"
            "Declaring the real types needs `response_class=Response` as well "
            "as `responses=`: the dictionary alone leaves this entry in place "
            "beside them."
        )

    def test_none_of_them_promises_a_body_under_a_status_that_sends_none(self) -> None:
        """The refusal the plural rule adds, and the one to read first when
        this file goes red on a change that looks unrelated: a 304 or a
        redirect declared beside a 200 must carry no content."""
        schema = main.app.openapi()
        promising = [
            offender
            for route in _routes_answering_with_a_body_of_their_own()
            for offender in _non_bodies_declaring_content(route, schema)
        ]

        assert promising == [], (
            "These answers declare a media type under a status the framework "
            "sends no body for, so the document promises bytes that never "
            "arrive:\n  " + "\n  ".join(promising)
        )


class TestTheCellsNoLiveRouteReaches:
    """Every branch here is unreachable on this tree, so nothing else defends it.

    The live population is four routes. The two cover routes file an answer
    under 200 and under 206, both of which are a body; the export and the
    backup file one 200 each. So no live answer is a redirect, a 304 or a
    refusal, and no annotated class among them declares `application/json`. The
    exempting branch of the JSON rule never fires, `_answers_without_a_body`
    never returns True, and `_the_refusal_rules_business` never takes a key
    from this walk: **every mutation of any of the three, taken alone, is
    green.** A mutation sweep plants defects and never deletes a widening, so
    removing any of them as dead code would bring the false refusals back with
    nothing red.

    So these arms build their own app and are about FastAPI rather than about
    this tree, which is the shape
    `tests/routers/test_auth.py::TestARouteThatSendsNoBodyDocumentsNone::test_the_default_is_what_this_rule_refuses`
    already uses for the same reason. **Both directions for each branch,
    because an exemption that fires is half of it**: the other half is that it
    still refuses what it was never meant to allow. They drive the same three
    functions the live arms do rather than a copy of their expressions.

    The redirect carries its status on the **response class** and not on the
    decorator, which is the ordinary spelling because that class already
    defaults to 307. That is the spelling the first repair of the helper these
    replace missed: it read `route.status_code`, which is `None` here.
    """

    @staticmethod
    def _app() -> FastAPI:
        csv: dict[str, dict[str, Any]] = {"text/csv": {}}
        json_content: dict[str, dict[str, Any]] = {JSON: {}}
        app = FastAPI()

        @app.get("/json-of-its-own", response_class=JSONResponse)
        def json_of_its_own() -> JSONResponse:
            return JSONResponse({"ok": True})

        @app.get("/csv-under-a-json-declaration")
        def csv_under_a_json_declaration() -> StreamingResponse:
            return StreamingResponse(iter([b""]), media_type="text/csv")

        @app.get("/away", response_class=RedirectResponse)
        def away() -> RedirectResponse:
            return RedirectResponse("/elsewhere")

        @app.get("/a-stream-declaring-nothing", response_class=StreamingResponse)
        def a_stream_declaring_nothing() -> StreamingResponse:
            return StreamingResponse(iter([b""]), media_type="text/csv")

        @app.get("/nothing-at-all", status_code=204, response_class=StreamingResponse)
        def nothing_at_all() -> StreamingResponse:
            return StreamingResponse(iter([b""]))

        @app.get(
            "/two-successes",
            response_class=Response,
            responses={200: {"content": csv}, 206: {"content": csv}},
        )
        def two_successes() -> StreamingResponse:
            return StreamingResponse(iter([b""]), media_type="text/csv")

        @app.get(
            "/a-second-success-declaring-nothing",
            response_class=Response,
            responses={200: {"content": csv}, 206: {"description": "partial"}},
        )
        def a_second_success_declaring_nothing() -> StreamingResponse:
            return StreamingResponse(iter([b""]), media_type="text/csv")

        @app.get(
            "/a-second-success-declaring-json",
            response_class=Response,
            responses={200: {"content": csv}, 206: {"content": json_content}},
        )
        def a_second_success_declaring_json() -> StreamingResponse:
            return StreamingResponse(iter([b""]), media_type="text/csv")

        @app.get(
            "/content-under-a-redirect",
            response_class=RedirectResponse,
            responses={307: {"content": csv}},
        )
        def content_under_a_redirect() -> RedirectResponse:
            return RedirectResponse("/elsewhere")

        @app.get(
            "/content-beside-a-refusal",
            response_class=Response,
            responses={200: {"content": csv}, "4XX": {"content": csv}, 503: {"content": csv}},
        )
        def content_beside_a_refusal() -> StreamingResponse:
            return StreamingResponse(iter([b""]), media_type="text/csv")

        @app.api_route(
            "/two-methods",
            methods=["GET", "PUT"],
            response_class=Response,
            responses={200: {"content": csv}},
        )
        def two_methods() -> StreamingResponse:
            return StreamingResponse(iter([b""]), media_type="text/csv")

        return app

    @classmethod
    def _route(cls, app: FastAPI, path: str) -> Any:
        return next(
            route
            for route in app.routes
            if isinstance(route, APIRoute)
            and route.path == path
            and _answers_with_a_body_of_its_own(route)
        )

    @classmethod
    def _verdicts(cls, path: str, schema: dict[str, Any] | None = None) -> tuple[bool, bool, bool]:
        """(a body declaring nothing, a body declaring JSON it does not send,
        a non body declaring content), for one route of the app above.

        `schema` is taken rather than always derived so an arm can doctor one
        operation of a two method route, which is the only way to make the two
        methods disagree: FastAPI writes one `responses=` into both.
        """
        app = cls._app()
        route = cls._route(app, path)
        schema = schema if schema is not None else app.openapi()
        return (
            bool(_bodies_declaring_nothing(route, schema)),
            bool(_bodies_declaring_json_they_do_not_send(route, schema)),
            bool(_non_bodies_declaring_content(route, schema)),
        )

    def test_a_class_that_sends_json_may_declare_json(self) -> None:
        assert self._verdicts("/json-of-its-own")[1] is False

    def test_a_class_that_sends_something_else_still_may_not(self) -> None:
        """The other side of that exemption. Without it the fix for the false
        refusal is a hole the size of the rule."""
        assert self._verdicts("/csv-under-a-json-declaration")[1] is True

    def test_an_answer_that_is_not_a_body_need_declare_nothing(self) -> None:
        assert self._verdicts("/away")[0] is False

    def test_an_answer_that_is_a_body_still_must_declare_something(self) -> None:
        """The other side of that one. `response_class=StreamingResponse` alone
        is the shape that reads as the fix and declares nothing."""
        assert self._verdicts("/a-stream-declaring-nothing")[0] is True

    def test_a_status_that_forbids_a_body_need_declare_nothing(self) -> None:
        """The half of `_carries_a_representation` the redirect does not reach.
        204 is inside the success range, so the success test on its own would
        require content here that FastAPI does not write."""
        assert self._verdicts("/nothing-at-all")[0] is False

    def test_a_redirect_declaring_no_content_is_right_to(self) -> None:
        """The quiet side of the refusal below: a 307 with nothing under it is
        what a redirect is supposed to look like."""
        assert self._verdicts("/away")[2] is False

    def test_a_redirect_may_not_promise_a_body(self) -> None:
        """The refusal the plural rule adds. The singular one never reached it:
        a route with one key was exempted from the content rules by that key
        not carrying a body, and nothing then looked at what it declared."""
        assert self._verdicts("/content-under-a-redirect")[2] is True

    def test_two_successes_that_both_declare_are_both_accepted(self) -> None:
        """**What the plural rule accepts that the old assertion refused**, and
        the reason the cover declaration is possible at all. Two success keys
        each carrying a type was a red before this, whatever the types were,
        because choosing between them was a guess the helper would not make."""
        assert self._verdicts("/two-successes") == (False, False, False)

    def test_a_second_success_declaring_nothing_is_refused(self) -> None:
        """And the price of accepting the pair: the second key is now checked
        rather than skipped with the first."""
        assert self._verdicts("/a-second-success-declaring-nothing")[0] is True

    def test_a_second_success_declaring_json_is_refused(self) -> None:
        assert self._verdicts("/a-second-success-declaring-json")[1] is True

    def test_a_refusal_key_is_left_to_the_rule_that_owns_it(self) -> None:
        """The interlock, driven rather than described. `4XX` and 503 both
        carry content here and all three rules step over them, which is only
        safe because `tests/test_errors.py::TestTheDocumentEnumeratesNoRefusal`
        reddens on either key first. Its predicate is the one
        `_the_refusal_rules_business` calls, so the two cannot drift."""
        assert self._verdicts("/content-beside-a-refusal") == (False, False, False)

        assert the_refusal_rule.TestTheDocumentEnumeratesNoRefusal._is_a_refusal("4XX")
        assert the_refusal_rule.TestTheDocumentEnumeratesNoRefusal._is_a_refusal("503")

    @pytest.mark.parametrize("method", ["get", "put"])
    def test_every_method_of_a_route_is_read(self, method: str) -> None:
        """Both operations of a two method route, because the two helpers this
        replaces read one method each and disagreed about which.

        FastAPI writes one `responses=` into both operations, so the only way
        to make them differ is to empty one in the document. Parametrised over
        which one, because `sorted(route.methods)[0]` would have caught `get`
        and never `put`, and passing for the wrong reason is the failure this
        arm exists to rule out."""
        app = self._app()
        schema = app.openapi()
        schema["paths"]["/two-methods"][method]["responses"]["200"].pop("content")

        assert self._verdicts("/two-methods", schema)[0] is True

    def test_the_two_method_route_is_clean_before_it_is_doctored(self) -> None:
        """The baseline the arm above needs. Without it a rule that reddens on
        everything scores two passes there."""
        assert self._verdicts("/two-methods") == (False, False, False)


class TestTheDeclarationIsTheOneHomeRead:
    """The declared set is the map the route serves from, not a copy of it.

    Pinned per operation rather than derived, because the rule above is about
    the class and this is about three particular tables: a declaration that
    drifts from the map is exactly the defect being closed, one level in.
    """

    @staticmethod
    def _declared(path: str, key: str) -> set[str]:
        """**The key by name, not through any rule above, and this does not
        generalise.** The paths below are pinned one at a time and each arm
        names the status it is about. A route filing an answer somewhere these
        arms do not name belongs to the rules above, which read every key off
        the document."""
        return set(main.app.openapi()["paths"][path]["get"]["responses"][key]["content"])

    def test_the_export_declares_every_format_it_can_send(self) -> None:
        assert self._declared("/api/books/export", "200") == {
            media_type.split(";")[0] for media_type in EXPORT_MEDIA_TYPES.values()
        }

    def test_the_backup_declares_the_type_it_sends(self) -> None:
        assert self._declared("/api/backup", "200") == {ARCHIVE_MEDIA_TYPE}

    @pytest.mark.parametrize(
        "path", ["/covers/{book_id}.{extension}", "/covers/login_bg.{extension}"]
    )
    def test_a_cover_declares_every_type_the_store_serves(self, path: str) -> None:
        assert self._declared(path, "200") == set(covers_router._MEDIA_TYPES.values())

    @pytest.mark.parametrize(
        "path", ["/covers/{book_id}.{extension}", "/covers/login_bg.{extension}"]
    )
    def test_a_cover_declares_the_envelope_two_ranges_arrive_in(self, path: str) -> None:
        """**A separate arm rather than a second parameter on the one above,
        because the two sets differ.** A single range sends the file's own
        type, so the 206 is the store's types **plus** the envelope
        `FileResponse` builds for two or more.

        The envelope is spelled here as a literal rather than read back off the
        route, so this is a pin and not a copy of the declaration. What holds
        the literal to what is sent is `TestTheWireIsWhatTheDocumentSays`,
        which drives a real two range request and reads the type off the
        response."""
        assert self._declared(path, "206") == set(covers_router._MEDIA_TYPES.values()) | {
            "multipart/byteranges"
        }


class TestTheWireIsWhatTheDocumentSays:
    """Driven through the ASGI stack, because every arm covering these routes
    today asserts a header against a literal and not one reads the document.

    That is how the five content type assertions in `tests/routers/test_books.py`,
    `tests/routers/test_imports_marc.py` and `tests/test_backup.py` stayed green
    while the schema said `application/json` for all of them.
    """

    @staticmethod
    def _assert_declared(response: Any, path: str, key: str) -> None:
        """The key is the one the arm calling this has already asserted it got,
        rather than a general answer: these arms drive named paths and check
        the status first."""
        sent = response.headers["content-type"].split(";")[0].strip()
        declared = set(
            main.app.openapi()["paths"][path]["get"]["responses"][key]["content"]
        )
        assert sent in declared, f"{path} [{key}] sent {sent!r}, declares {sorted(declared)}"

    @staticmethod
    def _a_stored_cover(client, admin) -> str:
        book_id = client.post(
            "/api/books", json={"title": "Dune"}, headers=admin["headers"]
        ).json()["id"]
        return client.post(
            f"/api/books/{book_id}/cover",
            files={"file": ("cover.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        ).json()["cover_url"]

    @pytest.mark.parametrize("fmt", sorted(EXPORT_MEDIA_TYPES))
    def test_every_export_arm_sends_a_declared_type(
        self, client, admin, db, make_book, fmt
    ) -> None:
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        make_book(admin["headers"], title="Stoner")

        response = client.get(
            "/api/books/export", params={"format": fmt}, headers=admin["headers"]
        )

        assert response.status_code == 200, response.text
        self._assert_declared(response, "/api/books/export", "200")

    def test_the_backup_sends_a_declared_type(self, client, admin) -> None:
        response = client.get("/api/backup", headers=admin["headers"])

        assert response.status_code == 200
        self._assert_declared(response, "/api/backup", "200")

    def test_a_cover_sends_a_declared_type(self, client, admin, covers_dir) -> None:
        url = self._a_stored_cover(client, admin)

        response = client.get(url, headers=admin["headers"])

        assert response.status_code == 200
        self._assert_declared(response, "/covers/{book_id}.{extension}", "200")

    def test_one_range_sends_a_type_declared_under_the_partial(
        self, client, admin, covers_dir
    ) -> None:
        """`FileResponse` handles `Range` after this module's route has
        returned, so the 206 is the framework's answer and not one any code
        here writes. The status is asserted first: an arm reading the type off
        a 200 would pass while saying nothing about the key it names."""
        url = self._a_stored_cover(client, admin)

        response = client.get(url, headers={**admin["headers"], "Range": "bytes=0-4"})

        assert response.status_code == 206, response.status_code
        self._assert_declared(response, "/covers/{book_id}.{extension}", "206")

    def test_two_ranges_send_a_type_the_two_hundred_does_not_declare(
        self, client, admin, covers_dir
    ) -> None:
        """**The arm the 206 declaration exists for.** A single range answers
        the file's own image type, so declaring the 200's content set under the
        206 would be right for the request somebody checking this would type
        and wrong for one whose ranges stay apart: those arrive as a multipart
        envelope instead.

        **The two assertions catch different things, and the first is the one
        that catches a false declaration.** The envelope is not in the image
        set, so a 206 declaring only the 200's types reddens on the type being
        undeclared whether or not the second assertion is here. What the second
        one catches is the two keys ceasing to differ, which is this arm going
        vacuous, and that is what its own message says.

        **The gap in the fixture is load bearing.** `_parse_range_header` sorts
        and merges the ranges that touch before it counts them, so
        `bytes=0-4,5-9` answers one range under the image type. Byte 5 is left
        out so the two survive that merge. **Tidying them to adjacent ones
        reddens the second assertion, not the status**: a single range still
        answers 206, so the status holds and what fails is the sent type being
        one the 200 declares too."""
        url = self._a_stored_cover(client, admin)

        response = client.get(url, headers={**admin["headers"], "Range": "bytes=0-4,6-9"})

        assert response.status_code == 206, response.status_code
        self._assert_declared(response, "/covers/{book_id}.{extension}", "206")

        sent = response.headers["content-type"].split(";")[0].strip()
        assert sent not in set(
            main.app.openapi()["paths"]["/covers/{book_id}.{extension}"]["get"]["responses"][
                "200"
            ]["content"]
        ), (
            f"a two range request sent {sent!r}, which the 200 declares too, so the "
            "two keys no longer differ and this arm has stopped being about "
            "anything. Two causes: the envelope was added to the 200's set as "
            "well, or these ranges now merge to one and the answer is the file's "
            "own type, which adjacent ranges do."
        )
