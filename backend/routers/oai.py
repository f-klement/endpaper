"""The OAI-PMH base URL: one route, and the two gates in front of it.

**The same two gates as `/sru`, in the same order: `routers.public.public_reader`,
then `oai_switch`.** The first is imported rather than restated, for the reason
`routers/sru.py` gives at length: one answer to "is anything published", one
rate limit, one 404 rather than 403. The second is this protocol's own switch,
read with the publish state by `settings_store.oai_is_served`, and it reads
neither SRU's switch nor anything SRU reads beyond the publish state, so turning
one protocol on never turns the other on.

**Off is the gate's own 404**, not an OAI-PMH `<error>`: an error in a 200 is how
a repository that is answering refuses one request, and a stranger told that a
repository is here and withheld has been told what the 404 rule exists not to
say. Both gates refuse before the query string is read.

**Not in the OpenAPI schema**, and at `/oai` rather than under `/api/`, for
`/sru`'s reasons: it is a document another institution's software fetches, and
the base URL is what goes into an aggregator's configuration.

**GET only.** The specification also names POST; no harvester this serves
needs it, and a second method is a second way in to keep equal to the first.
"""

from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

import oai
import settings_store
from dependencies import DbSession
from routers.public import public_reader
from routers.sru import server_for

#: Where the OAI-PMH repository answers.
OAI_PREFIX: Final = "/oai"

#: The port a URL of each scheme leaves out.
_DEFAULT_PORTS: Final = {"https": 443, "http": 80}


def oai_switch(db: DbSession) -> None:
    """Refuse every OAI-PMH request while the provider's own switch is off.

    After `public_reader`, never instead of it, so probing this switch spends the
    catalogue's rate limit. The same 404, so a stranger cannot tell a switched
    off protocol from an unpublished catalogue. **No `@refuses(404)`**, for
    `sru_switch`'s reason: the route is not in the OpenAPI schema.
    """
    if not settings_store.oai_is_served(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


#: Both gates on the router, so a route added here cannot be added without them.
router = APIRouter(tags=["oai"], dependencies=[Depends(public_reader), Depends(oai_switch)])


def repository_for(request: Request) -> oai.Repository:
    """The repository as this request reached it.

    The host comes from `routers.sru.server_for`, which reads the `Host` header
    against a bounded pattern and falls back to `localhost`, never to this
    process's own listen address: see `_HOST_HEADER` there. It is echoed to the
    client that sent it and to nobody else.
    """
    server = server_for(request)
    scheme = request.url.scheme if request.url.scheme in _DEFAULT_PORTS else "http"
    port = "" if server.port == _DEFAULT_PORTS[scheme] else f":{server.port}"
    return oai.Repository(host=server.host, base_url=f"{scheme}://{server.host}{port}{OAI_PREFIX}")


@router.get(OAI_PREFIX, include_in_schema=False)
def oai_request(request: Request, db: DbSession) -> Response:
    """One OAI-PMH request, answered as XML. The raw query string, for
    `routers/sru.py`'s reason: a repeated argument is an error the protocol
    names, and FastAPI's parsing would have answered it as a 422.

    **The first request ever answered is recorded before it is answered**, since
    from then on a harvester may hold any public record, and `harvest.py` writes
    a tombstone only for a record that leaves after that moment."""
    settings_store.record_oai_service(db)
    return Response(
        content=oai.respond(request.url.query, db, repository_for(request)),
        media_type=oai.MEDIA_TYPE,
    )
