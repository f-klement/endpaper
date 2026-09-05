"""The SRU base URL: one route, and everything it has to pass first.

**The gate is `routers.public.public_reader`, imported rather than restated.**
That dependency is the published catalogue's whole entry condition: the rate
limit, then the two switches, in that order so that probing the gate is bounded
too. Writing a second one here would be a second answer to "is anything
published", and the two would drift the first time one of them was edited.

Consequences worth stating, because they are not obvious from one import:

* **Library mode off is a 404**, and so is the publish switch off, because
  `public_catalogue_is_published` is the conjunction. The ticket asked only for
  the first; this is stricter, and an institution that has not published its
  catalogue has not published it over a protocol either.
* **404 and not 403.** A 403 would confirm that this deployment holds a
  catalogue it is declining to serve, to anybody who asked.
* **The rate limit is the catalogue's, not a second one.** One published
  catalogue, one budget: a harvester and a browser reading the same records
  should not have two.

**Not in the OpenAPI schema.** `robots.txt` is the precedent and the reason is
the same: this is a document another institution's software fetches, not an
operation this application's own client calls, and the response is MARCXML
rather than JSON. A generated typed hook for it would be noise nothing imports.

**`/sru` and not `/api/sru`.** The base URL is the thing handed to another
library, and it goes in their configuration, in a union catalogue's target list
and in a printed record. `/api/` names the private half of this deployment.
"""

import re
from typing import Final

from fastapi import APIRouter, Depends, Request, Response

import sru
from dependencies import DbSession
from routers.public import public_reader

#: Where the SRU service answers.
SRU_PREFIX: Final = "/sru"

#: What this server calls its one database in `explain`.
#:
#: The path, so the `<database>` an explain document reports and the URL a
#: client already has are the same string.
DATABASE: Final = "sru"

#: The `Host` header, as a name and an optional port.
#:
#: **Matched against the header rather than read off `request.url`, and that is
#: a security decision rather than a stylistic one.** Starlette validates the
#: `Host` header itself, against a pattern of its own that accepts a name of
#: `[a-z0-9.-]+` or a bracketed IPv6 literal with an optional `:port`; when the
#: header does not match, it falls back to `scope["server"]`, which is the
#: address this process is **bound** to. Behind a reverse proxy that is a
#: container's own listen address, so a client sending a malformed `Host` would
#: be told this deployment's internal address in a document it can keep. Reading
#: the header means the only two answers are the client's own host and
#: `localhost`.
#:
#: **That premise is a third party's behaviour, so it is pinned rather than
#: remembered**: `tests/routers/test_sru.py::TestTheFallbackThisAvoids` drives a
#: malformed header through Starlette and asserts the fallback really happens,
#: so an upgrade that changes it turns this paragraph red instead of leaving a
#: comment whose reason has quietly stopped being true. The code does not depend
#: on it either way, only the argument for not using `request.url` does.
#:
#: What this adds over Starlette's own rule, now that the two are not the same
#: check: a **length** bound, since that rule admits a name of any length and
#: this value goes into XML, and a refusal of the bracketed IPv6 form, which
#: costs a client on such a deployment an accurate `<host>` and nothing else,
#: because the URL it used to get here is the one it will use again.
#:
#: The port is bounded to five digits by the pattern, so the `int()` below
#: cannot be handed a number to parse, and range checked after it, because
#: `65536` is five digits and is not a port.
_HOST_HEADER: Final = re.compile(
    r"(?P<host>[A-Za-z0-9.\-]{1,253})(?::(?P<port>[0-9]{1,5}))?"
)

#: What `<host>` says when the request carries no host this server will echo.
_FALLBACK_HOST: Final = "localhost"

#: The port to report when the request names none, or names one that is not one.
#:
#: A URL with no port means the scheme's default, and there are only two schemes
#: this can arrive over. Read from `scope["scheme"]`, which is the server's own
#: fact rather than a header.
_DEFAULT_PORTS: Final = {"https": 443, "http": 80}

#: The largest number that is a port.
_MAX_PORT: Final = 65535

router = APIRouter(tags=["sru"], dependencies=[Depends(public_reader)])


def server_for(request: Request) -> sru.Server:
    """Where this request says it arrived, for `explain` to report.

    Derived from the request rather than from configuration, because the honest
    answer is the address the client used and no setting holds one. It is echoed
    back to the client that sent it and to nobody else, and nothing here builds
    a request from it. See `_HOST_HEADER` for what is done with a hostile value
    and why the header is read rather than the parsed URL.
    """
    default = _DEFAULT_PORTS.get(request.url.scheme, 80)
    match = _HOST_HEADER.fullmatch(request.headers.get("host", ""))
    if match is None:
        return sru.Server(host=_FALLBACK_HOST, port=default, database=DATABASE)
    port = int(match["port"]) if match["port"] else default
    return sru.Server(
        host=match["host"],
        port=port if 1 <= port <= _MAX_PORT else default,
        database=DATABASE,
    )


@router.get(SRU_PREFIX, include_in_schema=False)
def sru_request(request: Request, db: DbSession) -> Response:
    """One SRU request, answered as XML.

    **The raw query string, not FastAPI's parsed parameters**, and that is the
    seam rather than an oversight. Half of SRU's parameter handling is about the
    query string itself: whether `operation` arrived twice, whether a parameter
    nobody implements was sent, what a blank `query` means. FastAPI would have
    answered all three before `sru.respond` saw them, and answered them as HTTP
    422s, which is the one thing an SRU client cannot read.

    So there is no `Query(...)` declaration here and there is deliberately no
    request model: `sru.respond` is a function over a query string, and this
    handler is the four lines that give it a session and a place to answer from.
    """
    return Response(
        content=sru.respond(request.url.query, db, server_for(request)),
        media_type=sru.MEDIA_TYPE,
    )
