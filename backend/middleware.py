"""Response headers that constrain what a browser will do with our pages."""

from collections.abc import Awaitable, Callable
from typing import Final

from starlette import status
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

import settings_store
from config import MAX_UPLOAD_BYTES
from covers import COVER_HOSTS
from database import SessionLocal
from routers.public import PUBLIC_PAGE_PREFIX, PUBLIC_PREFIX

# `img-src` is **derived** from `covers.COVER_HOSTS`, not written out here.
# The two used to be separate lists and drifted: covers.py started resolving
# German ISBNs through portal.dnb.de, this policy never learned about it, and
# every cover on a German shelf was blocked by the browser while the stored
# record looked correct. Adding a host to that tuple is the only edit needed.
#
# Locally uploaded covers come from our own origin, and `data:` is what lets an
# inline placeholder render. Everything executable is restricted to same-origin.
#
# `style-src` needs 'unsafe-inline' and it is not an oversight: React applies
# the login background through an inline `style` attribute, and inline styles
# cannot be nonced the way scripts can. Scripts are NOT granted it, which is
# the half that matters for XSS.
_CSP: Final = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        " ".join(("img-src", "'self'", "data:", *COVER_HOSTS)),
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

_ONE_YEAR_SECONDS: Final = 31_536_000

#: What every response says to a crawler unless something lifts it.
#:
#: `noindex` alone would still let a crawler follow every link out of a page and
#: index those, which for a catalogue is every record.
NOINDEX: Final = "noindex, nofollow"

#: The paths a published catalogue is actually read at, and the only ones that
#: may ever lose `NOINDEX`.
#:
#: **Two of the three are client routes, and that is the point.** A crawler
#: indexes the HTML at `/catalogue` and `/catalogue/<id>`, not the JSON at
#: `/api/public/books`, and the JSON is what the first version of this listed.
#: The SPA is served by a `StaticFiles` mount, which has no dependencies, so a
#: header set by a route dependency could never have reached it: that is the gap
#: this middleware closes and it is why this lives here rather than in
#: `routers/public.py`.
#: Matched **exactly or followed by a slash**, never as a bare prefix. A bare
#: `startswith("/catalogue")` also matches `/catalogue-of-members`, which is the
#: same looseness the signed out route table is tested against in
#: `frontend/tests/app/App.test.tsx`.
#:
#: **Imported from the router rather than restated.** `routers/public.py` says
#: those two constants and this list must agree, and for a round nothing tied
#: them: they agreed because somebody had checked, which is the state a pair of
#: literals is in right up until it is not.
_INDEXABLE_PATHS: Final = (PUBLIC_PREFIX, PUBLIC_PAGE_PREFIX, "/robots.txt")


def _may_be_indexed(path: str) -> bool:
    """Whether this path is a published catalogue page a crawler was invited to.

    **The database is read only for a path that could possibly qualify**, which
    is three prefixes, so the signed in app pays nothing for this. The read
    itself is a settings row on a local SQLite file, and it costs a session per
    request on `/catalogue`, which has no rate limiter: measured at 3.99ms
    against 2.01ms. A short cache removes it and is its own ticket rather than
    this change.

    `settings_store` and `SessionLocal` are imported at module scope. They were
    deferred, on the argument that this module is imported by `main` before the
    app is built, and that stopped being a reason the moment `_INDEXABLE_PATHS`
    started importing from `routers.public`, which pulls the same chain.

    Failure is `False`, deliberately and by construction: anything that goes
    wrong leaves the response `noindex`, which is the answer a deployment that
    has published nothing wants and the answer a broken one wants too.
    """
    if not any(
        path == candidate or path.startswith(f"{candidate}/")
        for candidate in _INDEXABLE_PATHS
    ):
        return False
    session = SessionLocal()
    try:
        return settings_store.public_catalogue_may_be_indexed(session)
    except Exception:
        return False
    finally:
        session.close()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds the standard hardening headers to every response.

    HSTS is only sent when the request already arrived over HTTPS. Sending it
    over plain HTTP is ignored by browsers anyway, and setting it
    unconditionally in a LAN deployment that has no certificate would be a way
    to lock people out of their own bookshelf.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault(
            "Permissions-Policy",
            # The barcode scanner needs the camera; nothing needs the rest.
            "camera=(self), microphone=(), geolocation=(), interest-cohort=()",
        )

        # **Every response, not only a handler's.** A header set from a route
        # dependency merges onto the success path alone, so measured on the
        # public catalogue it was present on the 200 and absent from the gate's
        # 404, the item 404, a 429 and a 500, while two documents claimed every
        # public response carried it. Here it is unconditional and the public
        # paths are what may lift it, which is the safe direction: a response
        # nobody thought about stays out of the index.
        response.headers.setdefault("X-Robots-Tag", NOINDEX)
        if _may_be_indexed(request.url.path):
            del response.headers["X-Robots-Tag"]

        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if request.url.scheme == "https" or forwarded_proto == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", f"max-age={_ONE_YEAR_SECONDS}; includeSubDomains"
            )

        return response


# The largest body any route legitimately accepts. Restore is the outlier: a
# whole library's covers in one zip. Everything else is capped at the image
# limit, which is comfortably above any JSON this API takes.
_ARCHIVE_PATH_SUFFIX: Final = "/backup/restore"
# Multipart framing costs a boundary and a header block per part.
_MULTIPART_SLACK: Final = 64 * 1024

_BODY_METHODS: Final = frozenset({"POST", "PUT", "PATCH"})


def _limit_for(path: str) -> int:
    from routers.backup import MAX_ARCHIVE_BYTES

    if path.endswith(_ARCHIVE_PATH_SUFFIX):
        return MAX_ARCHIVE_BYTES + _MULTIPART_SLACK
    return MAX_UPLOAD_BYTES + _MULTIPART_SLACK


class BodySizeLimitMiddleware:
    """Refuse an oversized request before its body is read.

    The endpoints do check their own limits, but by the time an endpoint runs,
    Starlette has already consumed the whole body: a multipart upload goes to a
    SpooledTemporaryFile, which means anything past a few kilobytes is on disk.
    A 200 MB request aimed at the 5 MB cover endpoint was therefore written to
    disk in full and only then answered with a 413. The per-endpoint checks
    stay, because they enforce the real per-route limit and produce the message
    the UI shows; this one exists so nothing large ever reaches the disk.

    Two rules, in order of how much they can be trusted:

    1. A declared `Content-Length` over the limit is refused outright, before a
       single byte of body is read. The declared length is authoritative for a
       non-chunked request, because the server stops reading at it.
    2. A multipart request that declares no length at all is refused with 411.
       Without a length there is nothing to check in advance, and the spool is
       then bounded only by the client's willingness to keep sending. Every
       HTTP client that uploads a file sends a length, so this costs nothing
       real. It is deliberately limited to multipart: a chunked JSON body is
       held in memory rather than spooled, and bounded by the route's own
       parsing.

    This is pure ASGI rather than BaseHTTPMiddleware because it has to answer
    without the request being consumed, which BaseHTTPMiddleware's call_next
    contract does not allow.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        limit = _limit_for(scope.get("path", ""))
        declared = headers.get("content-length")

        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                length = -1
            if length > limit:
                await self._refuse(
                    scope,
                    receive,
                    send,
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"Request body must be {limit // (1024 * 1024)} MB or smaller",
                )
                return
        elif headers.get("content-type", "").startswith("multipart/form-data"):
            await self._refuse(
                scope,
                receive,
                send,
                status.HTTP_411_LENGTH_REQUIRED,
                "A file upload must declare its Content-Length",
            )
            return

        await self.app(scope, receive, send)

    async def _refuse(
        self, scope: Scope, receive: Receive, send: Send, code: int, detail: str
    ) -> None:
        # `detail` matches the shape of every other error this API returns, so
        # the frontend's error handling needs no special case.
        response = JSONResponse(status_code=code, content={"detail": detail})
        await response(scope, receive, send)
