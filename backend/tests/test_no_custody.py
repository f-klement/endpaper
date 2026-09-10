"""Endpaper never takes custody of a book file, asserted at the server.

`README.md` and `docs/featurelist.md` both tell a reader that a book file is read
in their own browser and never uploaded. That is a promise about this server, so
this is where it is checked.

`frontend/tests/houseRules.test.ts`, under "a member's book file cannot leave the
browser", keeps the reader modules away from the network. It is worth having and
it is a matcher over six names: it catches a reader that grows a request, and it
cannot see a way out it has no spelling for. **It is the second line.** The first
is that there is nowhere to send a book file to, which is structural rather than
a discipline, and it is what this file asserts.

Both halves are equalities rather than searches, so a route that begins taking a
file, or a table that begins holding bytes, has to be named here with what it is
for. A search for the unexpected is satisfied by an empty tree, which is the
evasion it would allow.

**What this cannot see**, said because a guard that reads thorough is believed to
be one:

* **A body FastAPI does not declare.** Every parameter here comes from
  `route.dependant`, so a handler taking a `Request` and reading the raw stream
  is outside it. Measured 2026-09-08 by walking the AST of the 121 Python files
  under `backend/` outside `tests/` for a call to `body`, `form`, `stream`,
  `receive` or `json`: 10 call sites, four on an `httpx` client and six on a
  response, and **none of them on a `Request`**. That is a measurement, not an
  enforcement.
* **A declared body that is not a file.** `CARRIES_A_FILE` asks for a `File`
  marker or an `UploadFile`, so a `bytes` body, a base64 string on a schema
  field, and every query and header parameter are invisible here. **A book
  arriving as a string in JSON would break the published promise and match
  nothing in this file.** There is no such field today: no module under
  `backend/schemas/` declares `bytes`.
* **A door that is not an `APIRoute`.** The four Starlette routes FastAPI adds
  for the schema and the docs, and the SPA's `StaticFiles` mount, which is not
  registered in this process at all, so nothing here would notice what it
  served. `/sru` is not one of these: it is an `APIRoute`, it is walked, and it
  takes its query in the query string. Z39.50 is a client this app calls out
  with rather than a door into it.
* **What a handler does with a file it legitimately took.** A cover is an image,
  bounded by `uploads.read_image_upload`, and a restore is this instance's own
  archive. Neither is re-checked here. What `backup.restore` checks is that an
  entry's bytes are an image this app serves, through the same sniff an upload
  gets; what it does **not** check is the entry's **name**, which is the
  archive's rather than derived from the bytes, so a restored cover may be a PNG
  called `1.jpg`. `backup._cover_bytes` carries why. Somebody restoring their own
  backup is outside both rules below either way.
* **Bytes this server fetches for itself.** `covers.store` writes a remote body
  into `COVERS_DIR` from the `cover_url` a member supplies, so bytes reach disk
  without passing any route this file reads. What stops a book file surviving
  that trip lives in `covers.py` rather than here: `is_fetchable`'s host
  allowlist, re-tested on every redirect hop, a size cap applied over `iter_raw`,
  and an extension taken from the magic bytes rather than from the URL.
* **Storage that is not a column of bytes.** The second class says no column
  carries bytes. A column carrying text is a different question, and so is a
  file on disk: a cover is written there with only its path in a `String`.
"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, UploadFile
from fastapi import params as fastapi_params
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from sqlalchemy import Column

import models as orm  # noqa: F401  (registers the tables on Base.metadata)
from database import Base
from main import app, iter_api_routes

#: Every route that accepts a file, and what the file is.
#:
#: **None of them is a book**, which is the whole claim. Four take a catalogue
#: export produced by another program, two an image, and one this instance's own
#: backup. A route added here is a decision about the published promise rather
#: than an edit to a list.
ROUTES_TAKING_A_FILE = {
    ("POST", "/api/backup/restore"): "this instance's own backup archive",
    ("POST", "/api/books/{book_id}/cover"): "a cover image",
    ("POST", "/api/imports/csv"): "another app's CSV export",
    ("POST", "/api/imports/marc"): "a MARCXML record set",
    ("POST", "/api/imports/marc/preview"): "a MARCXML record set",
    ("POST", "/api/imports/preview"): "another app's CSV export",
    ("POST", "/api/settings/login-image"): "the login page's background image",
}

#: The Python types that make a column a place to keep a file.
#:
#: Written as what the values are rather than as which SQLAlchemy types spell it:
#: `LargeBinary`, `BLOB` and `VARBINARY` all answer `bytes` here, so a name list
#: would have been three arms of an open set for no gain.
BYTE_TYPES = (bytes, bytearray, memoryview)

#: A body parameter carries an uploaded file, asked two ways.
#:
#: They are one concept reached differently, and each alone has a hole. FastAPI
#: marks a multipart part with a `File` field info and infers that marker from an
#: `UploadFile` annotation, so the marker misses nothing today; the annotation is
#: what a reader of the source sees. Asking only the annotation would miss
#: `file: Annotated[bytes, File()]`, which uploads a file and never names the
#: type. Both are asserted to find the same set, so neither can rot unnoticed.
CARRIES_A_FILE: dict[str, Callable[[Any], bool]] = {
    "the File marker FastAPI attaches": lambda field: isinstance(
        getattr(field, "field_info", None), fastapi_params.File
    ),
    "an UploadFile in the annotation": lambda field: "UploadFile"
    in str(getattr(getattr(field, "field_info", None), "annotation", "")),
}


def api_routes() -> list[APIRoute]:
    return list(iter_api_routes(app.routes))


def body_fields(route: APIRoute) -> list[Any]:
    """The body parameters of a route, including those a dependency declares.

    The whole dependency tree, because a body parameter contributed by a sub
    dependency is not on the route's own `body_params` and would otherwise be
    invisible here while being perfectly able to accept a file.

    Walked here rather than through FastAPI's own flattener, which was
    `get_flat_dependant` until it was renamed to a private `_get_flat_body_params`
    in 0.141: a guard resting on a private helper stops running on the release
    that renames it, and an import error reads as a broken test rather than as a
    rule that no longer holds.
    """
    fields: list[Any] = []
    pending: list[Dependant] = [route.dependant]
    seen: set[int] = set()
    while pending:
        dependant = pending.pop()
        if id(dependant) in seen:
            continue
        seen.add(id(dependant))
        fields.extend(dependant.body_params)
        pending.extend(dependant.dependencies)
    return fields


def routes_taking_a_file(carries: Callable[[Any], bool]) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in api_routes()
        if any(carries(field) for field in body_fields(route))
        # `or ()` because FastAPI types `methods` as optional. A route with none
        # answers nothing, so it contributes no pair rather than an untyped one.
        for method in route.methods or ()
    }


def python_type(column: Column[Any]) -> type | None:
    """What a column's values are, or `None` where the type will not say.

    A SQLAlchemy type that cannot answer raises rather than returning anything,
    and a rule that swallowed that would go quiet on exactly the custom type
    somebody added to hold bytes. So it is answered as `None` here and the count
    of `None`s is asserted below.
    """
    try:
        return column.type.python_type
    except NotImplementedError:
        return None


def columns() -> list[Column[Any]]:
    return [column for table in Base.metadata.sorted_tables for column in table.columns]


class TestNoRouteAcceptsABookFile:
    """The door, as an equality in both directions.

    A route joining the set fails, which is the prompt to ask whether the
    published promise still holds. A route leaving it fails too, which is what a
    list checked only for unexpected members lets through.
    """

    def test_the_routes_that_take_a_file_are_the_named_ones(self) -> None:
        found = routes_taking_a_file(
            lambda field: any(carries(field) for carries in CARRIES_A_FILE.values())
        )
        assert found == set(ROUTES_TAKING_A_FILE), (
            "The set of routes accepting an uploaded file has changed. README.md and "
            "docs/featurelist.md promise that a book file is read in the browser and "
            "never uploaded, so every route that takes a file is named in "
            "ROUTES_TAKING_A_FILE with what the file is. A route taking a book file "
            "breaks the published promise; one taking anything else is added there "
            "with its reason."
        )

    def test_each_way_of_asking_finds_the_same_routes(self) -> None:
        # The union above passes while either half sees nothing, which is how a
        # matcher stops matching without anything going red. Each is asserted
        # against the routes rather than against a fixture, so a FastAPI release
        # that moves the marker fails here rather than quietly leaving the union
        # resting on one arm.
        assert set(CARRIES_A_FILE) == {
            "the File marker FastAPI attaches",
            "an UploadFile in the annotation",
        }, (
            "an arm was added to or removed from CARRIES_A_FILE. The loop below is over "
            "the dict, so a shorter dict is a shorter loop and a deleted arm is a test "
            "that passes. Both arms are named here for the same reason the routes are."
        )
        for description, carries in CARRIES_A_FILE.items():
            assert routes_taking_a_file(carries) == set(ROUTES_TAKING_A_FILE), (
                f"{description} no longer finds the routes that take a file"
            )

    def test_the_walk_reads_body_parameters_beyond_the_named_routes(self) -> None:
        # What the equality needs and cannot show on its own. It compares
        # against a non empty set, so a walk returning nothing fails it; a walk
        # that read the body of the seven and nothing else would pass it while
        # "no OTHER route takes a file" rested on routes never looked at.
        #
        # **A count of routes does not say it**, which is the shape to refuse
        # here: a bound on how many routes the walk found multiplies two
        # unrelated quantities, so one loose enough to hold today lets the walk
        # lose most of the app, and one tight enough to bite starts failing on a
        # correct walk as soon as the named set grows.
        named = {path for _, path in ROUTES_TAKING_A_FILE}
        with_a_body = {route.path for route in api_routes() if body_fields(route)}
        #
        # **What it does not refuse is a truncated enumeration.** It passes on
        # one body bearing route outside the named set, so an `iter_api_routes`
        # yielding the seven and one other satisfies this and the equality above
        # as well. The guard that refuses that is an equality over the whole
        # route set in another file,
        # `test_nothing_private_leaves.py::TestNothingPrivateLeavesByARoute`
        # `::test_the_route_set_is_the_pinned_one`. This file leans on it and
        # names it rather than keeping a second copy of the route set.
        assert with_a_body.difference(named), (
            "no route outside ROUTES_TAKING_A_FILE was read as having a body, so the "
            "equality above is comparing against a walk that may be reading nothing"
        )


class TestTheWalkSeesABodyParameterADependencyDeclares:
    """`body_fields` descends the dependency tree, exercised on an app built here.

    No route in this app contributes a body parameter through a sub dependency
    today, so every rule above passes with the descent deleted: it is correct by
    design and unexercised by the tree. The rule is about what the walk can see
    rather than about what this app happens to declare this week, so the case is
    built rather than found.
    """

    @staticmethod
    def _probe() -> APIRoute:
        # **Two levels down, not one.** A probe at one level is reached by a
        # walk that reads the route's own dependencies and recurses no further,
        # so a one level probe scores a descent that does not descend. The
        # deepest dependency tree in this app is deeper than either, which is
        # why the second level is not a contrivance.
        probe = FastAPI()

        def declares_the_file(file: Annotated[UploadFile, File()]) -> None:
            return None

        def one_level_further_down(
            _: Annotated[None, Depends(declares_the_file)],
        ) -> None:
            return None

        @probe.post("/probe")
        def take_it(_: Annotated[None, Depends(one_level_further_down)]) -> None:
            return None

        return next(route for route in probe.routes if isinstance(route, APIRoute))

    def test_the_file_is_two_dependencies_down_from_the_route(self) -> None:
        # The half that makes the next test mean anything, and it is the depth
        # rather than the absence: the route declares no body parameter and
        # neither does anything one level below it, so a walk that stops at
        # either finds nothing to score.
        route = self._probe()
        assert route.dependant.body_params == []
        assert [
            field
            for dependency in route.dependant.dependencies
            for field in dependency.body_params
        ] == []

    def test_the_walk_finds_it_anyway(self) -> None:
        route = self._probe()
        assert any(
            carries(field)
            for field in body_fields(route)
            for carries in CARRIES_A_FILE.values()
        )


class TestTheDatabaseHasNowhereToPutABookFile:
    """No column in the schema carries bytes.

    The weaker half of the claim, and still worth asserting: it is what makes
    "never takes custody" true of what is stored rather than only of the wire.
    Read off `Base.metadata`, so it covers every table the app maps rather than
    the ones somebody thought to check.
    """

    def test_no_column_can_hold_bytes(self) -> None:
        offenders = [
            f"{column.table.name}.{column.name} ({column.type})"
            for column in columns()
            if python_type(column) in BYTE_TYPES
        ]
        assert offenders == [], (
            "These columns carry bytes, so the database now has somewhere to keep a "
            "book file: " + ", ".join(offenders)
        )

    def test_every_column_says_what_it_carries(self) -> None:
        # A column whose type will not answer is skipped by the rule above, and
        # skipped silently. Asserted as a count recomputed from the schema rather
        # than as a number written here, so it cannot be satisfied by a shorter
        # walk.
        assert [column.name for column in columns() if python_type(column) is None] == []
        assert columns(), "no tables were mapped, so the rule above checked nothing"
