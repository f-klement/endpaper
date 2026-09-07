"""The household's own OPDS servers: configuring them, and syncing what they hold.

**Configuration is an admin's and the sync is any member's**, and the split is
the one this application already draws. Which machines this server will open a
connection to is a deployment question, so it sits beside the other admin only
settings. What a sync then does is write into the catalogue as the member who
asked for it, exactly as `POST /api/imports/csv` does, because holdings and the
Books created for them belong to a person rather than to the configuration.

**An admin gains a capability here that nothing else on their list has.** They
can already restore a backup, create accounts and set the API key; none of those
turns this server into a request generator aimed at an address they choose.
#131 names that as concession 2 of the typed host design and it applies in full.
What bounds it, and which of #131's controls deliberately does not apply here,
is `opds.py`'s subject and is not restated.
"""

import logging
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import credentials
import opds
import settings_store
from auth import require_admin
from dependencies import CurrentUser, DbSession, RowId
from importing import OpdsImport
from models import OpdsServer, User
from ratelimit import import_limiter
from schemas import (
    OpdsCredentialIn,
    OpdsServerIn,
    OpdsServerOut,
    OpdsServerSummaryOut,
    OpdsSyncOut,
)

logger = logging.getLogger("endpaper.opds")

router = APIRouter(prefix="/api/opds", tags=["opds"])


def _server(db: Session, server_id: int) -> OpdsServer:
    row = db.get(OpdsServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such OPDS server.")
    return row


def _out(db: Session, row: OpdsServer, state: credentials.KeyState) -> OpdsServerOut:
    """One row plus what may be said about its login, and never the login.

    `credentials.view` walks the same ladder the outbound request walks, so this
    screen cannot report one level while a sync authenticates as another.
    """
    held = credentials.view(db, row.credential_key, row.base_url, state)
    return OpdsServerOut(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        credential_provenance=held.provenance,
        credential_username_preview=settings_store.mask(held.username),
        credential_unreadable=held.unreadable,
    )


def _listed(db: Session) -> list[OpdsServerOut]:
    # The key is resolved once for the whole list rather than per row: see
    # `credentials.KeyState`, which exists because `_supplied` reads the
    # keychain and runs a BIP-39 decode on every call.
    state = credentials.key_state()
    return [
        _out(db, row, state)
        for row in db.query(OpdsServer).order_by(OpdsServer.id).all()
    ]


def _checked_address(base_url: str) -> str:
    """The address, or a 400 naming why this server will not fetch it.

    **Both of the walk's own refusals, rather than a validator that agrees with
    one of them.** A rule enforced at the write and a different rule enforced at
    the fetch is how a stored row comes to be one the fetcher refuses, which is
    a sync that fails with nothing an admin can act on. This ran
    `is_fetchable` alone and `holdings` refuses a second thing: an address
    `credentials.origin_of` cannot parse pins no origin and binds no credential.

    **The two parsers really do disagree**, which is why the second check is not
    implied by the first: `is_fetchable` reads with `urlsplit` and `origin_of`
    with `httpx.URL`. Measured by a critic, three classes where the first admits
    and the second answers `""`: a fullwidth letter in the host, a bare `xn--`
    label, and a soft hyphen in the host. Each was storable and every sync of it
    was a 502 nothing on the screen predicted.
    """
    if not opds.is_fetchable(base_url):
        raise HTTPException(
            status_code=400,
            detail=(
                "That is not an address this server will fetch. An OPDS feed is "
                "an http or https address carrying no username or password."
            ),
        )
    if not credentials.origin_of(base_url):
        raise HTTPException(
            status_code=400,
            detail="That address cannot be used as a server's identity.",
        )
    return base_url


@router.get("/servers", response_model=list[OpdsServerOut])
def list_servers(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> list[OpdsServerOut]:
    """Every OPDS server this library is configured to read."""
    return _listed(db)


# **Declared before every `/{server_id}` route**, because FastAPI matches in
# declaration order and `mine` would otherwise be read as a row id. It is not
# ambiguous today, since no `/{server_id}` route answers GET, and it costs
# nothing to be in the order that stays right when one does.
@router.get("/servers/mine", response_model=list[OpdsServerSummaryOut])
def list_syncable_servers(
    db: DbSession,
    current_user: CurrentUser,
) -> list[OpdsServerSummaryOut]:
    """The servers this member may sync, by id and name.

    **Without this the split above is not deliverable and nothing said so.** The
    full listing is admin only, so a member had no way to learn a `server_id`
    and could reach `POST /servers/{id}/sync` only by guessing an integer. A
    critic found it because the router's own test took the id from the admin's
    create response, which is exactly where a missing route does not show.

    **Two fields and not the full row.** A member needs to name the server they
    are syncing; the address is the configuration an admin owns, and the
    credential state is about a secret. Neither belongs on a screen that only
    offers a button.
    """
    return [
        OpdsServerSummaryOut(id=row.id, name=row.name)
        for row in db.query(OpdsServer).order_by(OpdsServer.id).all()
    ]


@router.post("/servers", response_model=OpdsServerOut, status_code=201)
def add_server(
    payload: OpdsServerIn,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> OpdsServerOut:
    """Add a server, with no login on it yet.

    The credential is a second call rather than two more fields here, mirroring
    the catalogue settings screen: a login is replaced far more often than an
    address is, and folding them would make an edit that leaves the password
    field blank ambiguous between "unchanged" and "removed".
    """
    row = OpdsServer(name=payload.name, base_url=_checked_address(payload.base_url))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(db, row, credentials.key_state())


@router.put("/servers/{server_id}", response_model=OpdsServerOut)
def edit_server(
    server_id: RowId,
    payload: OpdsServerIn,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> OpdsServerOut:
    """Rename a server, or point it somewhere else.

    **Moving it to a different origin drops the stored login**, and what that
    buys changed when the envelope started carrying its origin: the login can no
    longer be sent to the new address, because it does not open there. That is
    true of a household server's envelope at every version, because the
    superseded scheme is refused outright for one: `credentials._may_open_unbound`
    opens such an envelope only at the address this build published for its own
    roster source, and a household server has neither. What this
    still does is make the row honest. A login left behind would report as held
    and unreadable for the rest of its life, which reads as a damaged row and
    sends somebody to the recovery phrase. The response reports the credential
    as gone, so nothing has to be inferred from silence.

    A rename, or an edit that keeps the same scheme, host and port, keeps the
    login: it is the same machine, and making somebody retype a password to fix
    a path would teach them to keep the row wrong.
    """
    row = _server(db, server_id)
    address = _checked_address(payload.base_url)
    moved = credentials.origin_of(address) != credentials.origin_of(row.base_url)
    if moved:
        # **Before the address moves, and the order is still worth keeping.**
        # `credentials.forget` commits on its own, so forgetting afterwards
        # leaves a window, and permanently if the second commit never runs, in
        # which this row names the new machine and still holds the old machine's
        # sealed login. That window no longer sends the login anywhere, since
        # the envelope is sealed over the old origin and does not open at the
        # new one; it leaves a row reporting an unreadable login instead.
        # Failing here leaves the login gone on an unchanged address, which is
        # still the safe direction. Found by a critic reading the two commits.
        credentials.forget(db, row.credential_key)
    row.name = payload.name
    row.base_url = address
    db.commit()
    return _out(db, row, credentials.key_state())


@router.delete("/servers/{server_id}", status_code=204)
def remove_server(
    server_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Forget a server, and the login sealed for it.

    **Both, and the credential is not merely tidied away.** The key is random
    rather than derived from the row id, so no later server can be handed this
    one's login even if this delete were skipped, and this delete means the
    envelope does not sit in every archive after the machine it was for is gone.
    See `models.new_opds_credential_key` for why the two guards are separate.
    """
    row = _server(db, server_id)
    key = row.credential_key
    db.delete(row)
    db.commit()
    credentials.forget(db, key)


@router.put("/servers/{server_id}/credential", response_model=OpdsServerOut)
def set_server_credential(
    server_id: RowId,
    payload: OpdsCredentialIn,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> OpdsServerOut:
    """Store this server's login, sealed.

    Sealed against the row's own credential key **and its address**, so a
    ciphertext moved between rows by a hand edited archive, or left beside an
    address that archive rewrote, fails authentication rather than decrypting
    into a request aimed at a different machine. `credentials.seal` carries the
    argument.

    409 when no encryption key is configured: there is nowhere to put a secret,
    and the message names the variables that would supply one.
    """
    row = _server(db, server_id)
    try:
        credentials.put(
            db, row.credential_key, row.base_url, payload.username, payload.password
        )
    except credentials.KeyConfigurationError as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    except credentials.NoKeyConfigured as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    except credentials.CredentialError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal)) from None
    return _out(db, row, credentials.key_state())


@router.delete("/servers/{server_id}/credential", response_model=OpdsServerOut)
def forget_server_credential(
    server_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> OpdsServerOut:
    """Drop this server's stored login.

    **Succeeds whether or not one was stored, and needs no key**, for the
    catalogue credential route's reason: a login nobody can read is exactly the
    one somebody most wants to be rid of, and requiring the key to delete it
    would make a rotated key unrecoverable without a database edit.
    """
    row = _server(db, server_id)
    credentials.forget(db, row.credential_key)
    return _out(db, row, credentials.key_state())


@router.post("/servers/{server_id}/sync", response_model=OpdsSyncOut)
async def sync_server(
    server_id: RowId,
    db: DbSession,
    current_user: CurrentUser,
    create_missing: Annotated[
        bool, Query(description="Add books the feed lists and this catalogue lacks")
    ] = True,
) -> OpdsSyncOut:
    """Read one server's feed and record what this member holds.

    **`async def`, and the applying is pushed off the event loop by hand, which
    is the opposite arrangement to the other two importers and is deliberate.**
    Those read a file that has already arrived and are `def` throughout, so
    FastAPI runs them in a threadpool. This one has two halves: the walk is
    network bound and awaits, and the apply is blocking, because SQLAlchemy has
    no async here. Declaring the whole handler `def` would put an `asyncio.run`
    inside a worker thread; leaving the apply on the loop would stop the
    application answering for its duration, measured elsewhere at 14.4 seconds
    for `GET /api/books` during a 3,000 row import. So the walk awaits and the
    apply goes to `anyio.to_thread`.

    **The session is touched from one thread at a time**, which is what makes
    that safe: the walk is finished before the apply starts, and nothing else
    holds this request's session.

    **Rate limited on the import limiter**, with the other bulk writes. A sync
    is a walk of somebody's whole library and a write per entry, and the
    address it walks is one an admin chose rather than one this build ships.

    Books created here arrive `ownership=owned`, which is the whole point of the
    route: a member's own library server is the evidence of possession that a
    reading history and another institution's catalogue both are not. **Only an
    entry that says the member holds the book is counted**, so a title a server
    offers for sale or loan is passed over rather than recorded as owned: an
    entitlement is not a holding.

    **A book added by a sync carries a title, an author and nothing else, and
    that is a complete row rather than a half finished one.** What the feed
    cannot supply, measured across seven servers rather than read off the
    specification, is an identifier, a series, a publisher, a year, a language
    and a page count. A description arrives later from the catalogue chain, and
    **the chain may have none for a born digital title**: of the eight
    catalogues a title search asks, six refuse a record that says it is
    electronic. Five decide it from codes, the four MARC ones on their carrier
    codes and the Library of Congress on its MODS form, and the BnF decides it
    from the format prose alone. Only Open Library and Google Books apply no
    such rule. So a row with no description is this route working, not failing,
    and it is reported under `created` for that reason.
    """
    import_limiter.check(current_user.username)
    row = _server(db, server_id)
    credential = credentials.for_request(db, row.credential_key, row.base_url)

    try:
        found = await opds.holdings(row.base_url, credential=credential)
    except opds.OpdsError as failure:
        # 502 rather than 500: the address answered, or refused to, and it is
        # not this application that is broken. The message never carries the
        # login; `Credential.__str__` is overridden for exactly this path.
        logger.warning("OPDS sync of server %d failed: %s", row.id, failure)
        raise HTTPException(status_code=502, detail=str(failure)) from None

    applied = await anyio.to_thread.run_sync(
        lambda: OpdsImport.for_member(db, current_user.id).apply(
            found.records, create_missing=create_missing
        )
    )

    return OpdsSyncOut(
        **applied.model_dump(),
        pages_read=found.pages_read,
        entries_not_held=found.not_held,
        truncated=found.truncated,
    )
