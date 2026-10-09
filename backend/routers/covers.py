"""Uploaded cover images, served only to members allowed to see the book.

## The hole this closes

Until now this was a bare static mount:

    app.mount("/covers", StaticFiles(directory=str(COVERS_DIR)), name="covers")

`StaticFiles` has no dependencies, so **no authentication and no authorization
ran on that path at all**. Every other route 401s without an identity; this one
answered from disk. Measured on the running deployment: `/api/books/1` returned
401 with no identity header and `/covers/1.jpg` returned 404, which is
`StaticFiles` reporting a missing file rather than anything refusing the caller.

Cover files are named `<book_id>.<ext>` (see the upload handler), so the id is
an integer a caller can simply count through. Any signed-in member could
therefore fetch the cover of **another member's private book**, and
`visible_to()` never ran. That is a hole in the single rule the whole data
model is built around, and the only thing containing it was the reverse proxy
at the edge, which decides who is a member and has no opinion about which books
a member may see.

Serving covers through a route fixes it the same way every other book endpoint
is fixed: by asking for the book, and letting `book_for_read` decide. A missing
file and an invisible book are both 404, which is the house rule (a 403 would
confirm the id exists).

Cover files are still files, named by book id; the decision and what it costs
are in `docs/decisions.md`, and `cover_store` is what knows the name. The guard
is the dependency, not the sink, which is why moving the bytes around changes
nothing here.

## How an image tag proves who it is

An `<img src>` cannot carry an `Authorization` header. Under `AUTH_MODE=proxy`
that does not matter: identity arrives in a request header the proxy sets on
every request, images included. Under `AUTH_MODE=local` the token lives in
localStorage and is attached by the fetch wrapper, which an image tag never
goes through, so covers would 401. Local is the published image's default, so
that would ship a catalogue with no covers.

So this route, and only this route, also accepts a path-scoped cookie. The
reasoning for why that is not CSRF, and why it must not be generalised to any
other route, is at `auth.COVER_COOKIE_NAME`.
"""

from typing import Annotated, Any, Final

from fastapi import APIRouter, HTTPException, Response, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

import cover_store
from dependencies import BookForCover

router = APIRouter(prefix="/covers", tags=["covers"])

# Long, because the content at a given URL never changes: a re-upload writes a
# new extension or the same bytes, and the cache buster is the filename itself.
# `private` and not `public`: a shared cache in front of this must not serve one
# member's cover to another, which is the whole point of the route existing.
#
# **It reaches the 206 and neither of the two refusals a `Range` header can
# produce**, which is worth saying because this claim now has three statuses
# under it rather than one. Both range handlers rebuild from the response's own
# raw headers, so a partial answer carries this; a malformed `Range` (400) and
# an unsatisfiable one (416) are built inside the framework as plain text
# responses and carry no `Cache-Control` at all. Measured. Both run after the
# dependency below has already refused an invisible book, and neither status is
# one a conformant shared cache stores on its own, so nothing crosses members
# either way. What would break the sentence above is a 206 losing the header,
# not these two.
_CACHE_CONTROL: Final = "private, max-age=604800"

#: The `Content-Type` a cover is served with, chosen by its **filename**.
#:
#: **What makes that safe is the allowlist, not the accuracy of the name.**
#: Every value here is a raster type a browser decodes and cannot execute, and
#: the route refuses any extension outside `ALLOWED_IMAGE_EXTENSIONS`, so the
#: worst a wrong name produces is one of these four labels on another of the
#: four formats. That is not a hole: an `<img>` decodes by magic number, so a
#: `.jpg` holding PNG bytes renders regardless of what this table said about it.
#:
#: **`image/svg+xml` is the one that must never appear here.** It is an
#: `image/*` and it is also a document with script in it, running under this
#: app's own origin and CSP, so adding it is the edit that would undo the
#: arrangement. `svg` is absent from `ALLOWED_IMAGE_EXTENSIONS` for the same
#: reason. `tests/routers/test_covers.py::TestTheMediaTypesAreNotDocuments`
#: holds both halves: these keys equal that allowlist, and no value is a
#: scriptable type.
#:
#: What the files themselves do guarantee is that the bytes are one of these
#: formats: every write goes through `cover_store`, which sniffs them on the way
#: past. That is a property of one module rather than of each caller, which is
#: what it was when restore could store anything at all under a cover name.
_MEDIA_TYPES: Final[dict[str, str]] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

#: What these two routes promise for a 200, **derived from the table above** so
#: the document cannot name a type the routes will not send or miss one they
#: will. Three entries rather than four: two extensions share `image/jpeg`.
#:
#: Both routes declared `application/json` until this was added, for image
#: bytes, which is the same defect the export routes carried and is what
#: `tests/test_declared_media_types.py` now refuses for the class.
#:
#: No schema under each type: that is the OpenAPI 3.1 spelling for opaque bytes,
#: since `format: binary` belonged to 3.0 and JSON Schema 2020-12 has no such
#: format.
_DECLARED_CONTENT: Final[dict[str, dict[str, Any]]] = {
    media_type: {} for media_type in dict.fromkeys(_MEDIA_TYPES.values())
}

#: The envelope a request whose ranges **stay apart** is answered with, which is
#: not a type any file is served as.
#:
#: `FileResponse` handles `Range` itself, after this module has returned.
#:
#: **Not a function of how many ranges the caller wrote.** `_parse_range_header`
#: sorts the ranges and merges the ones that touch **before** anything counts, so
#: what decides the answer is how many survive that merge. Measured against the
#: pinned starlette: no header answers 200 under the file's own image type; one
#: range answers **206** under that same type, and so does any set that merges to
#: one, which two identical ranges and three adjacent ones both do; two or more
#: that survive the merge answer 206 under this, built by
#: `_handle_multiple_ranges` with a generated boundary; and above a hundred comma
#: separated ranges the parser returns nothing at all and the route answers 200
#: with the whole file.
#:
#: **The declaration is true for every one of those shapes**, which is why the
#: merge is recorded here rather than handled. What it would not be true for is a
#: 206 declaring `_DECLARED_CONTENT` alone: right for the single range somebody
#: checking this would type, wrong for the first request whose ranges stay apart,
#: which is the same defect as the JSON declaration this table replaced, one
#: request shape along.
#:
#: **Deliberately not a member of `_MEDIA_TYPES`.** That table answers what one
#: file on disk is labelled, keyed by the extensions `cover_store` hands back,
#: and its safety claim is about types a browser executes. This is an envelope
#: the framework builds around parts that each carry one of those labels, and
#: nothing looks it up by extension. Putting it there would make
#: `tests/routers/test_covers.py::TestTheMediaTypesAreNotDocuments` assert it is
#: an extension the store serves, which it is not.
_MULTIPART_BYTERANGES: Final = "multipart/byteranges"

#: What these two routes promise for a **206**: the 200's set, because a single
#: range still sends the file's own type, plus the envelope above.
#:
#: Derived from `_DECLARED_CONTENT` rather than rebuilt from `_MEDIA_TYPES`, so
#: the two keys cannot drift from each other or from the map.
#:
#: **The 400 and the 416 a `Range` header can also produce are left undeclared,
#: and that is a refusal rather than an omission.**
#: `tests/test_errors.py::TestTheDocumentEnumeratesNoRefusal` holds that this
#: document enumerates no refusal anywhere, which two published route docstrings
#: argue from by name. Declaring one here would make both of them false through
#: a decorator edit, and whether to declare refusals is a decision about the
#: whole surface rather than about these two routes.
#:
#: **A conditional request is not a third key either.** `FileResponse` does no
#: conditional handling at all, measured two ways: the only 304 in the pinned
#: starlette's response module is in the check on whether a status may carry a
#: body, and an `If-None-Match` echoing the etag this route has just sent
#: answers 200 with the whole file. Declaring an answer the framework cannot
#: send is the same defect as not declaring one it can.
_DECLARED_PARTIAL_CONTENT: Final[dict[str, dict[str, Any]]] = _DECLARED_CONTENT | {
    _MULTIPART_BYTERANGES: {}
}


def _not_found() -> HTTPException:
    """A cover that is absent, or one on a book this caller may not see.

    A fresh instance per raise, never a module level one, for the reason
    `dependencies._not_found` records: a shared exception object accumulates a
    frame on its `__traceback__` at every raise and never releases it.

    **This route is the worst place in the app to get that wrong.** It has five
    raise sites, and a cover 404 is ordinary rather than exceptional: every
    `<img>` on every page hits it, and a book with no stored cover answers 404
    by design.

    Three of the five pinned a `Session` and the `User` the cover cookie
    resolved to. The other two are in `get_login_background`, which is public:
    measured, `GET /api/covers/login_bg.png` answers 404 with no `Authorization`
    header and no cookie. Those pinned no identity and needed no session at all,
    which is the sharper half: an unauthenticated caller could grow that object
    without ever signing in.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cover not found")


# Declared BEFORE the book route. `book_id` is typed `int`, so "login_bg" would
# not match it anyway, but relying on that is relying on a coincidence of
# parsing: if the book route ever took a string id this would silently start
# resolving as a book and 401 the login page.
#
# **The name in this path is the one `cover_store` writes**, and this decorator
# is the only place it is spelled twice, because a route path is a literal.
# Drifting apart is a 404 on the public login page with the file sitting on disk
# and nothing else looking wrong.
# `TestTheLoginBackground::test_the_route_spells_the_name_the_store_writes` is
# what keeps the two the same fact. Here rather than in the docstring below,
# which FastAPI publishes as this route's OpenAPI description.
# `response_class=Response` **and** the dictionary. Either alone is weaker than
# it reads: the dictionary alone leaves `application/json` in the 200 beside the
# image types, and `response_class=FileResponse` alone declares no content at
# all. `routers/books.export_books` carries the measurement. The handler stays
# annotated `-> FileResponse`, which is what keeps it out of the population
# `tests/routers/test_auth.py::TestARouteThatSendsNoBodyDocumentsNone` forbids
# content to.
@router.get(
    "/login_bg.{extension}",
    response_class=Response,
    responses={
        200: {"content": _DECLARED_CONTENT},
        206: {"content": _DECLARED_PARTIAL_CONTENT},
    },
)
def get_login_background(
    extension: Annotated[str, PathParam(pattern=r"^[A-Za-z]{3,4}$")],
) -> FileResponse:
    """The login page background. Public, and it has to be.

    The login page renders before anyone holds a token, so an authenticated
    background is a broken image on the one screen every visitor sees. It is
    also admin-chosen and deliberately shown to anyone who reaches the door, so
    there is nothing here to withhold.

    This route is the reason the rest of this module cannot simply be "the
    covers directory, authenticated": one file in it is public, and the split
    is by name rather than by directory because that is where `settings.py`
    already writes it.
    """
    path = cover_store.login_background_to_serve(extension)
    if path is None:
        raise _not_found()

    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[path.suffix.lstrip(".")],
        # `public`, unlike the book covers below: this one is the same bytes for
        # everybody, so a shared cache serving it to another visitor is correct.
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get(
    "/{book_id}.{extension}",
    response_class=Response,
    responses={
        200: {"content": _DECLARED_CONTENT},
        206: {"content": _DECLARED_PARTIAL_CONTENT},
    },
)
def get_cover(
    book: BookForCover,
    extension: Annotated[str, PathParam(pattern=r"^[A-Za-z]{3,4}$")],
) -> FileResponse:
    """The cover for a book the caller may see.

    `book_id` is consumed by the `BookForCover` dependency rather than by this
    function: declaring it as a path parameter of the route is what lets the
    dependency resolve the book and apply `visible_to()` before any of this
    runs. An invisible book raises 404 there and never reaches this body.

    `FileResponse` rather than reading the bytes here, which is half the reason
    covers are files: it can hand the file off to the kernel, where reading a
    column would pull every image through the Python heap of a pod limited to
    512Mi.
    """
    # One question, one answer: `cover_store` refuses an extension outside the
    # allowlist, refuses a path that leaves its directory, and returns None when
    # there is simply no file. This route answers 404 to all three, and a 403 to
    # none of them.
    #
    # The media type is read off the file that is about to be served. That name
    # came from the request, lowercased and checked against the allowlist, so
    # this is not independent evidence about the bytes: what makes it safe is
    # that no type in the table is one a browser executes.
    # `TestTheMediaTypesAreNotDocuments` is what makes the lookup total: its keys
    # are exactly the extensions `cover_store` will hand back.
    path = cover_store.cover_to_serve(book.id, extension)
    if path is None:
        raise _not_found()

    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[path.suffix.lstrip(".")],
        headers={"Cache-Control": _CACHE_CONTROL},
    )
