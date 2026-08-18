"""Response headers that constrain what a browser will do with our pages."""

from collections.abc import Awaitable, Callable
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
