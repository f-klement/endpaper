"""Error responses, in whichever form the caller can use.

One app serves both a JSON API and a browser. A person who mistypes a URL
should get a readable page; a fetch() call should get `{"detail": ...}` it can
parse. These handlers decide which by looking at the request, so neither
audience gets the other's format.

The rule is deliberately conservative: HTML only when the caller is a browser
navigating (`Accept` prefers `text/html`) *and* the path is not part of the
API. An API path always answers JSON, even to a browser, because anything
calling it is code.
"""

import logging
import string
from http import HTTPStatus
from pathlib import Path
from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("endpaper.errors")

_TEMPLATE_PATH: Final = Path(__file__).parent / "templates" / "error.html"

# Paths owned by the API. Everything else belongs to the single-page app.
API_PREFIXES: Final = ("/api/", "/auth/", "/openapi.json", "/docs", "/redoc")

# Wording per status. Keeping these here rather than inline means an error page
# never accidentally repeats an internal exception message back to the browser.
_PRESENTATION: Final[dict[int, tuple[str, str, str]]] = {
    status.HTTP_400_BAD_REQUEST: (
        "🤔", "That didn't work", "The request wasn't something we could act on."
    ),
    status.HTTP_401_UNAUTHORIZED: (
        "🔑", "Please sign in", "You need to be signed in to see this."
    ),
    status.HTTP_403_FORBIDDEN: (
        "🚫", "Not allowed", "Your account doesn't have access to this."
    ),
    status.HTTP_404_NOT_FOUND: (
        "📭", "Nothing here", "We couldn't find that page or book."
    ),
    status.HTTP_413_CONTENT_TOO_LARGE: (
        "🐘", "That file is too big", "Try a smaller image."
    ),
    status.HTTP_422_UNPROCESSABLE_CONTENT: (
        "📝", "Something's missing", "Some of the details sent weren't valid."
    ),
    status.HTTP_429_TOO_MANY_REQUESTS: (
        "⏳", "Too many attempts", "Please wait a moment and try again."
    ),
    status.HTTP_500_INTERNAL_SERVER_ERROR: (
        "💥", "Something broke", "That's our fault, not yours. Please try again."
    ),
}

_FALLBACK: Final = ("⚠️", "Something went wrong", "Please try again.")


def _load_template() -> string.Template:
    """Read the page once at import.

    `string.Template` rather than Jinja: there are four placeholders and no
    logic, so a templating dependency would earn nothing. `${}`-style
    substitution also cannot execute anything from the values.
    """
    raw = _TEMPLATE_PATH.read_text(encoding="utf-8")
    # The file uses {{name}} for readability; convert to $name for Template.
    for field in ("status", "title", "message", "glyph"):
        raw = raw.replace(f"{{{{{field}}}}}", f"${field}")
    return string.Template(raw)


_TEMPLATE: Final = _load_template()


def is_api_path(path: str) -> bool:
    return path.startswith(API_PREFIXES)


def wants_html(request: Request) -> bool:
    """True when this looks like a browser navigating to a non-API path."""
    if is_api_path(request.url.path):
        return False
    accept = request.headers.get("accept", "")
    # A browser navigation sends text/html first; fetch() defaults to */*.
    return "text/html" in accept


def render_error_page(status_code: int) -> HTMLResponse:
    glyph, title, message = _PRESENTATION.get(status_code, _FALLBACK)
    html = _TEMPLATE.substitute(
        status=status_code, title=title, message=message, glyph=glyph
    )
    return HTMLResponse(content=html, status_code=status_code)


def _json_error(status_code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    if wants_html(request):
        return render_error_page(exc.status_code)
    response = _json_error(exc.status_code, exc.detail)
    # Preserve headers the raiser set deliberately: WWW-Authenticate on a 401
    # and Retry-After on a 429 both carry meaning the client acts on.
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    if wants_html(request):
        return render_error_page(status.HTTP_422_UNPROCESSABLE_CONTENT)
    # Keep FastAPI's per-field array: the client flattens it into a message.
    return _json_error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors())


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Last resort for a bug in our own code.

    The traceback is logged and never sent: it names internal paths and can
    quote request data back to whoever triggered it. The caller gets a generic
    message, which is all they can act on anyway.
    """
    logger.exception(
        "Unhandled error serving %s %s", request.method, request.url.path, exc_info=exc
    )
    if wants_html(request):
        return render_error_page(status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _json_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR, HTTPStatus.INTERNAL_SERVER_ERROR.phrase
    )


def register_error_handlers(app: FastAPI) -> None:
    # Registered against Starlette's HTTPException, not FastAPI's subclass.
    # Routing failures (an unmatched path, a method not allowed) are raised
    # by Starlette itself as the base class, so a handler bound to the subclass
    # never sees them and they fall back to a bare JSON 404. Registering the
    # base catches both, since FastAPI's inherits from it.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
