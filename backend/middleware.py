"""Response headers that constrain what a browser will do with our pages."""

from collections.abc import Awaitable, Callable
from typing import Final

from starlette import status
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from config import MAX_UPLOAD_BYTES

# Book covers come from Open Library and Google Books, and locally uploaded
# ones are served from our own origin as data the browser must be allowed to
# render. Everything executable is restricted to same-origin.
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
        "img-src 'self' data: https://covers.openlibrary.org https://books.google.com "
        "https://*.googleusercontent.com",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

_ONE_YEAR_SECONDS: Final = 31_536_000


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
