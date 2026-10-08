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
import traceback
from http import HTTPStatus
from pathlib import Path
from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, PendingRollbackError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("endpaper.errors")

_TEMPLATE_PATH: Final = Path(__file__).parent / "templates" / "error.html"

# Paths owned by the API. Everything else belongs to the single-page app.
# `/covers/` is here because a missing or forbidden cover is requested by an
# <img> tag, and answering that with a full HTML error page means the browser
# downloads a document to render as an image. A short JSON body is the honest
# reply to something that is not a picture.
API_PREFIXES: Final = ("/api/", "/auth/", "/covers/", "/openapi.json", "/docs", "/redoc")

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
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101  narrowing, not validation
    if wants_html(request):
        return render_error_page(exc.status_code)
    response = _json_error(exc.status_code, exc.detail)
    # Preserve headers the raiser set deliberately: WWW-Authenticate on a 401
    # and Retry-After on a 429 both carry meaning the client acts on.
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)  # noqa: S101  narrowing, not validation
    if wants_html(request):
        return render_error_page(status.HTTP_422_UNPROCESSABLE_CONTENT)
    # Keep FastAPI's per-field array: the client flattens it into a message.
    #
    # Through `jsonable_encoder`, which is not optional. A validator that
    # rejects a value by raising `ValueError` puts the **exception object**
    # into the entry's `ctx`, and `JSONResponse` cannot serialise that: the
    # 422 turns into a TypeError during rendering and the caller gets a 500
    # for a request that was merely invalid. FastAPI's own handler does the
    # same encode, which is why this only surfaced once a validator here
    # started raising.
    #
    # **`input` is dropped from every entry, and that is the load bearing
    # line.** pydantic puts the value it rejected into the entry, so a 422
    # echoed the whole submitted value back in the response body: measured
    # 2026-09-06, a recovery phrase and a catalogue password each came back in
    # full, and `SecretStr` does not change it. The echo is to the same caller,
    # so nothing reaches a third party, but a secret in a response body is a
    # secret in whatever logs that response, and `docs/security.md` states the
    # rule without qualification. Dropped here rather than per field, because
    # the next secret field would otherwise have to remember.
    #
    # The client flattens the remaining `loc`, `msg` and `type` into a message,
    # which is what it always rendered; nothing displayed `input`.
    reported = [
        {key: value for key, value in entry.items() if key != "input"}
        for entry in jsonable_encoder(exc.errors())
    ]
    return _json_error(status.HTTP_422_UNPROCESSABLE_CONTENT, reported)


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Last resort for a bug in our own code.

    The traceback is logged and never sent: it names internal paths and can
    quote request data back to whoever triggered it. For a validation error or
    a database error it is not logged either, for the reasons at those
    branches. The caller gets a generic message, which is all they can act on
    anyway.
    """
    # LOG004 reads the lexical position and reports this as an `.exception()`
    # outside a handler, where a traceback would be `NoneType: None`. It is an
    # exception handler: Starlette calls it with the exception, which is why
    # `exc_info=exc` is passed explicitly rather than left to the ambient one.
    # Narrowing to `.error(..., exc_info=exc)` to satisfy it would log the same
    # bytes at the same level and lose the one word that says what this is.
    if isinstance(exc, ResponseValidationError | ValidationError):
        # **Not the traceback, because both carry the value that failed**, in
        # their message and in every entry's `input`. A response model defect
        # would log the row it failed on: a member's title, their notes, a
        # private book. The type, where each value failed and why, and the
        # frames are what a fix needs. The 422 handler above drops `input` for
        # the same reason. Only these two: an exception chained to one of them
        # still goes through the traceback below.
        #
        # **One line, because `AnswerUnhandledErrors` answers first.** Reached
        # through Starlette's own last resort instead, the exception would be
        # re-raised to the server after this answered, and uvicorn would log
        # the whole traceback again, value included.
        logger.error(
            "Unhandled error serving %s %s: %s %s\n%s",
            request.method,
            request.url.path,
            type(exc).__name__,
            _without_values(exc.errors()),
            frames(exc),
            extra={UNHANDLED: exc},
        )
    elif isinstance(exc, DATABASE_ERRORS):
        # **Not the traceback, because the driver's message can quote the
        # row.** `hide_parameters` keeps the bound values out of SQLAlchemy's
        # half, and Postgres puts the conflicting value in the error's own
        # detail ("Key (email)=(...) already exists", or the whole failing
        # row), which pg8000 renders. The type, the constraint and the frames.
        logger.error(
            "Unhandled error serving %s %s: %s\n%s",
            request.method,
            request.url.path,
            database_error_summary(exc),
            frames(exc),
            extra={UNHANDLED: exc},
        )
    else:
        logger.exception(  # noqa: LOG004  exc_info is explicit, see above
            "Unhandled error serving %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
            extra={UNHANDLED: exc},
        )
    if wants_html(request):
        return render_error_page(status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _json_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR, HTTPStatus.INTERNAL_SERVER_ERROR.phrase
    )


#: The log record attribute carrying the exception an "Unhandled error" line is
#: about, whichever branch wrote it. Not rendered by any formatter: it is how the
#: suite's crash net, `tests/conftest.py`, re-raises the route's own exception
#: in the test that caused it, where two of the three branches log no traceback.
UNHANDLED: Final = "unhandled_exception"


def frames(error: BaseException) -> str:
    """Where an exception was raised, as file, line, function and source line.

    Code and never a value, which is what lets a branch above log it in place
    of a traceback whose message would carry one.
    """
    return "".join(traceback.format_tb(error.__traceback__)).rstrip()


#: The database errors logged without their message. `PendingRollbackError` is
#: not a driver error and wraps none, and it is here because it **quotes** one:
#: the next use of a session after a failed flush raises it with "Original
#: exception was: ..." and the flush error's whole text, pg8000's detail
#: included, in its own message.
DATABASE_ERRORS: Final = (DBAPIError, PendingRollbackError)


def database_error_summary(error: DBAPIError | PendingRollbackError) -> str:
    """A database error as its types and the constraint it broke, never its text.

    The constraint is named where the driver hands it over apart from the
    message: pg8000 keeps the server's fields as a dict, and `n` is the
    constraint name. SQLite has no such field, and its message, which names
    columns rather than values, is left out with the rest: one rule for every
    engine is the one nobody has to remember the exceptions to. An error
    wrapping no driver exception is its type alone.
    """
    if not isinstance(error, DBAPIError):
        return type(error).__name__
    original = error.orig
    fields = original.args[0] if original is not None and original.args else None
    constraint = fields.get("n") if isinstance(fields, dict) else None
    summary = f"{type(error).__name__}({type(original).__name__})"
    return f"{summary} on {constraint}" if isinstance(constraint, str) else summary


def _without_values(errors: object) -> list[dict[str, object]]:
    """A validation error's entries with only `type`, `loc` and `msg` kept.

    A positive list rather than dropping `input`: `ctx` carries the exception a
    validator raised and `url` nothing a fix needs, and a key added to the
    entries later stays out until somebody decides it belongs.
    """
    if not isinstance(errors, list | tuple):
        return []
    return [
        {key: entry[key] for key in ("type", "loc", "msg") if key in entry}
        for entry in errors
        if isinstance(entry, dict)
    ]


class AnswerUnhandledErrors:
    """Answer a route's unhandled exception with the 500, and do not re-raise it.

    **Why this exists rather than the `Exception` handler alone.** Starlette
    calls that handler from `ServerErrorMiddleware` and then re-raises, so that
    a server can log the error too, and uvicorn does: "Exception in ASGI
    application" with the whole traceback. That second copy renders the
    exception's message, which for a validation error is the member's value
    `unhandled_exception_handler` takes care to leave out. Caught here, the
    exception never reaches that middleware, and the handler's line is the only
    one. The start command is untouched.

    **Added first, so innermost**: the 500 passes back out through the security
    headers like any other answer, which the outermost last resort's never did.
    An exception raised by a middleware outside this one still takes the old
    path.

    **Three things pass through unchanged.** A cancellation, which is not an
    `Exception`, so stopping the server still stops a request. A client that
    disconnected, which has nobody to answer: passed on, it reaches Starlette's
    last resort and is logged twice as before, and it reaches only a route that
    reads the request stream itself, because FastAPI already answers a
    disconnect while it parses a body with a 400. And anything raised after the
    response started, where a 500 can no longer be sent and swallowing it would
    end a truncated body as though it were whole.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def noting_the_start(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, noting_the_start)
        except ClientDisconnect:
            raise
        except Exception as error:
            if started:
                raise
            response = await unhandled_exception_handler(Request(scope, receive), error)
            await response(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    # Registered against Starlette's HTTPException, not FastAPI's subclass.
    # Routing failures (an unmatched path, a method not allowed) are raised
    # by Starlette itself as the base class, so a handler bound to the subclass
    # never sees them and they fall back to a bare JSON 404. Registering the
    # base catches both, since FastAPI's inherits from it.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
