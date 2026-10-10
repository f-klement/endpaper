"""The refusals a route declares in the schema, read off what the route runs.

A route answers 401, 403 or 404 because something it runs raises one: the identity
dependency, the admin gate, the lookup that applies the privacy rule, or its own
body. `refuses` marks the handler, or the dependency the raise is reached from,
with the statuses it can raise, and `declare` walks each route's dependency tree,
the handler included, and declares the union. So a route taking `CurrentUser`
declares 401 because the dependency it takes is marked, and a route that stops
taking it stops declaring it. A mark on a helper the handler calls is read by
nothing, since the walk reads the dependency tree alone.

**These three and no other.** They are what a page has to survive whatever it
asked: the session ended, the account may not, the row is gone or was never
yours to see. Every other refusal, 400, 409 and 429 among them, stays undeclared
everywhere, so the document is uniform about each status rather than deliberate
on some routes and silent on the rest.

**Declared only where it can be answered.** A 404 on a route that cannot send one
is a false claim the frontend's schema driven property then draws, so a mark goes
where a raise is reached from, never on a route that merely takes an id.
`tests/test_refusals.py` derives the same three a second way, from the
`HTTPException` constructions each route's functions reach, and holds every route
to equality with what this declares.
"""

import functools
import inspect
from collections.abc import Callable, Iterable
from typing import Any, Final

from fastapi import status
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from schemas.common import Refusal

#: The statuses `refuses` may name, and the only refusals the schema declares.
DECLARED: Final = frozenset(
    {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    }
)

#: Where the mark is kept: an attribute on the function rather than a table keyed
#: by it, because `functools.wraps` copies a function's attributes and a table
#: would lose any function a later decorator wraps.
_MARK: Final = "__endpaper_refuses__"


def refuses[F: Callable[..., Any]](*statuses: int) -> Callable[[F], F]:
    """Mark a dependency or a handler with the refusals its body can raise.

    Refuses a status outside `DECLARED` at import, rather than declaring a 409
    on one route and leaving every other 409 undeclared.
    """
    outside = sorted(set(statuses) - DECLARED)
    if outside or not statuses:
        raise ValueError(f"refuses() takes some of {sorted(DECLARED)}, not {outside or 'none'}")

    def mark(function: F) -> F:
        setattr(function, _MARK, marked(function) | frozenset(statuses))
        return function

    return mark


def marked(call: object) -> frozenset[int]:
    """The statuses `refuses` put on `call`, or none.

    A dependency FastAPI is handed as a callable instance runs its class's
    `__call__`, and one handed as a `functools.partial` runs what it wraps, so
    the mark is read there as well.
    """
    if isinstance(call, functools.partial):
        call = call.func
    found: object = getattr(call, _MARK, frozenset())
    own = found if isinstance(found, frozenset) else frozenset()
    if inspect.isroutine(call) or inspect.isclass(call) or not callable(call):
        return own
    return own | marked(type(call).__call__)


def answered_by(dependant: Dependant) -> frozenset[int]:
    """Every status marked anywhere in a route's dependency tree.

    The handler is the root of that tree, so a mark on the handler is read
    the same way as a mark on a dependency it takes.
    """
    found = marked(dependant.call)
    for each in dependant.dependencies:
        found |= answered_by(each)
    return found


def declare(routes: Iterable[APIRoute]) -> None:
    """Add a `Refusal` response for each status a route's tree is marked with.

    **Before the first request or schema read, and that is not tidiness.**
    FastAPI builds the route it serves and documents from `responses`
    lazily, on first use, and keeps it; a status added here after that is in
    `responses` and in no schema. `main` calls this below every
    `include_router`; a route included after it declares nothing, which
    `tests/test_refusals.py` names.

    **It reads each route as written**, so a dependency given to
    `include_router(..., dependencies=...)` is served and not read here: give
    it to the included `APIRouter(...)`. And a route declared on the app
    itself built its response models when it was declared, so a status added
    here reaches its document with no body; `tests/test_refusals.py` names it.
    """
    for route in routes:
        for code in sorted(answered_by(route.dependant)):
            route.responses.setdefault(code, {"model": Refusal})
