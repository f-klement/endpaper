"""KOReader's progress sync: the device protocol, and the member's screens for it.

Two routers, because they have two audiences.

**`device` answers KOReader**, under `kosync.KOSYNC_PREFIX` and not `/api/`,
because the address is what a member types into the device and the protocol
is not this application's. Every answer is the reference server's, status and
body, from `koreader-sync-server`'s `syncs_controller.lua` and `errors.lua`;
`docs/api.md` has the table. It has no session: a device signs in with the
member's username and a sync password on every call, and **a deployment behind
a sign in proxy must let exactly this prefix through unauthenticated**, since a
device cannot complete a sign in page. Nothing here reads a proxy header, so the
exemption grants a caller nothing but the protocol.

Two answers carry the protocol's whole weight. **An unknown document is 200
`{}`**, because the device reads a 404 as a sync error. And **any refusal but
401 makes a device queue the push and send it again at its next connection**,
once, so a member who is not signed in is 401 and nothing else is.

**`member` is the library's own API** for minting the sync password and
linking a document to a Book, behind the ordinary session.

Not in the OpenAPI schema on the device side, for the reason `routers/sru.py`
gives: it is a document another program fetches, not an operation this
application's client calls.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import JSONResponse

import kosync
from accounts import end_every_session
from auth import require_admin
from dependencies import BookForRead, CurrentUser, DbSession, RowId
from logvalues import clipped
from models import KOSYNC_DOCUMENT_MAX, KosyncDocument, User
from ratelimit import client_address
from refusals import refuses
from schemas import KosyncAccountOut, KosyncDocumentOut, KosyncPasswordOut

#: How many inbox rows one request returns. A member's inbox is what their
#: devices opened and nobody linked; past this, the oldest wait for the next.
INBOX_SHOWN: Final = 100

logger = logging.getLogger("endpaper.kosync")

device = APIRouter(prefix=kosync.KOSYNC_PREFIX, include_in_schema=False)
member = APIRouter(prefix="/api/kosync", tags=["kosync"])


# ── The device protocol ───────────────────────────────────────────────────────


async def refused_answer(request: Request, exc: Exception) -> JSONResponse:
    """A protocol refusal in the reference's own envelope, `message` and `code`.

    Registered in `main.py` for `kosync.Refused`, which only this module's
    routes raise. Not the application's `{"detail": ...}`: a device shows
    `message` to its reader.
    """
    refused = (
        exc
        if isinstance(exc, kosync.Refused)
        else kosync.Refused(502, 2000, "Unknown server error.")
    )
    return JSONResponse(
        status_code=refused.status,
        content={"message": refused.message, "code": refused.code},
    )


async def _body(request: Request) -> object:
    """The JSON body, refused as the reference's framework refuses it."""
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except (ValueError, RecursionError):
        # `RecursionError` for a body nested deeper than the parser recurses,
        # which fits under the body limit and would otherwise be a 500.
        raise kosync.Refused(400, 103, "Could not parse JSON in body.") from None
    if isinstance(body, list):
        raise kosync.Refused(400, 104, "Body should be a JSON hash.")
    return body


def _header(request: Request, name: str) -> str | None:
    """A header as the text the device meant, which is UTF-8.

    KOReader writes the username's bytes as they are, and Starlette decodes
    every header as latin-1, so `jürgen` would arrive as `jÃ¼rgen` and never
    match. Bytes that are not UTF-8 are kept as latin-1 text and are matched
    as they read.
    """
    value = request.headers.get(name)
    if value is None:
        return None
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def _signed_in(request: Request, db: DbSession) -> User:
    """The member a device's two headers name, or the protocol's 401.

    **A refusal is logged once, at warning**, with the username clipped and the
    client's address and never the key, so the deployment's log pipeline sees
    a run of guesses; nothing here limits them, because the password is too
    long to guess.
    """
    username = _header(request, "x-auth-user")
    found = kosync.authenticate(db, username, _header(request, "x-auth-key"))
    if found is None:
        logger.warning(
            "KOReader sync refused a sign in as %s from %s",
            clipped(username),
            client_address(request),
        )
        raise kosync.unauthorized()
    return found


Device = Annotated[User, Depends(_signed_in)]
Body = Annotated[object, Depends(_body)]


@device.post("/users/create")
def kosync_register() -> JSONResponse:
    """Registration is off: a sync password is minted in the library's settings."""
    raise kosync.registration_disabled()


@device.get("/users/auth")
def kosync_authorize(member: Device) -> JSONResponse:
    """What KOReader's login button checks."""
    return JSONResponse({"authorized": "OK"})


@device.put("/syncs/progress")
def kosync_push(member: Device, body: Body, db: DbSession) -> JSONResponse:
    """Store where the device is. 200 is the only answer a device takes as done."""
    push = kosync.read_push(body)
    timestamp = kosync.record(db, member, push)
    db.commit()
    return JSONResponse({"document": push.document, "timestamp": timestamp})


@device.get("/syncs/progress/{document}")
def kosync_pull(document: str, member: Device, db: DbSession) -> JSONResponse:
    """Where this member's devices last were in a document, or `{}`."""
    try:
        name = kosync.checked_document(document)
    except kosync.Refused:
        # The reference refuses an unusable name on this route with 2004
        # whatever is wrong with it; 2007 is its PUT's code.
        raise kosync.Refused(403, 2004, "Field 'document' not provided.") from None
    return JSONResponse(kosync.answer(db, member, name))


@device.get("/healthcheck")
def kosync_healthcheck() -> JSONResponse:
    """The reference's liveness answer. No device calls it; an operator may."""
    return JSONResponse({"state": "OK"})


@device.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def kosync_not_found(rest: str) -> JSONResponse:
    """Any other path under the prefix, answered 404 in JSON rather than by the
    app's shell. Declared last, so it claims only what nothing above did."""
    raise kosync.Refused(404, 404, "Not found.")


# ── The member's own screens ──────────────────────────────────────────────────

#: A document name in a path, the shape a device can push and nothing else.
DocumentName = Annotated[
    str, Path(min_length=1, max_length=KOSYNC_DOCUMENT_MAX, pattern="^[A-Za-z0-9_]+$")
]


def _out(row: KosyncDocument) -> KosyncDocumentOut:
    return KosyncDocumentOut(
        document=row.document,
        percentage=row.percentage,
        device=row.device,
        pushed_at=datetime.fromtimestamp(row.timestamp, UTC),
        title=row.title,
        authors=row.authors,
        filename=row.filename,
        book_id=row.book_id,
    )


@member.get("/account", response_model=KosyncAccountOut)
def get_kosync_account(current_user: CurrentUser) -> KosyncAccountOut:
    """Whether the caller has a sync password, and the username a device uses."""
    return KosyncAccountOut(
        username=current_user.username,
        has_password=current_user.kosync_key_digest is not None,
        password_set_at=current_user.kosync_key_set_at,
    )


@member.post(
    "/account/password",
    response_model=KosyncPasswordOut,
    status_code=status.HTTP_201_CREATED,
)
def mint_kosync_password(current_user: CurrentUser, db: DbSession) -> KosyncPasswordOut:
    """A new sync password, shown in this answer and never again.

    Replaces any the caller had, so every device signed in with the old one is
    refused from its next call.
    """
    password = kosync.mint(current_user)
    db.commit()
    return KosyncPasswordOut(username=current_user.username, password=password)


@member.delete("/account/password", status_code=status.HTTP_204_NO_CONTENT)
def revoke_kosync_password(current_user: CurrentUser, db: DbSession) -> None:
    """Sign every device out. What they already pushed stays."""
    kosync.revoke(current_user)
    db.commit()


@member.delete("/members/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
@refuses(404)
def revoke_member_kosync_password(
    user_id: RowId,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> None:
    """Sign one member out everywhere, devices included, for an admin.

    **The way to shut a person out under proxy or directory auth**, where
    removing them from the directory does not reach this library: a sync
    password is this library's, the sign in proxy does not stand in front of
    `/kosync/`, and under directory auth a token already issued stays good
    for its week without asking the directory again. So it ends their tokens
    as well, through `accounts.end_every_session`, or a live one would mint a
    new sync password the moment the old one went. What their devices already
    pushed stays.
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such member")
    end_every_session(target)
    db.commit()
    logger.warning(
        "An admin, user id %s, signed %s out of every session and device",
        admin.id,
        clipped(target.username),
    )


@member.get("/inbox", response_model=list[KosyncDocumentOut])
def list_kosync_inbox(current_user: CurrentUser, db: DbSession) -> list[KosyncDocumentOut]:
    """The caller's documents that no Book is linked to, newest push first.

    At most `INBOX_SHOWN`. Only the caller's own: nobody else's device is
    anybody's business.
    """
    return [_out(row) for row in kosync.unlinked(db, current_user.id, INBOX_SHOWN)]


@member.get("/books/{book_id}/documents", response_model=list[KosyncDocumentOut])
def list_kosync_documents(
    book: BookForRead, current_user: CurrentUser, db: DbSession
) -> list[KosyncDocumentOut]:
    """The caller's documents linked to one Book they can see."""
    return [_out(row) for row in kosync.linked_to(db, current_user.id, book.id)]


@member.put("/books/{book_id}/documents/{document}", response_model=KosyncDocumentOut)
@refuses(404)
def link_kosync_document(
    document: DocumentName, book: BookForRead, current_user: CurrentUser, db: DbSession
) -> KosyncDocumentOut:
    """Link one of the caller's documents to this Book, and remember it.

    Applies where the device is now, so a document finished before it was
    linked marks the Book read. 404 for a document the caller's devices never
    pushed, the answer for one that is somebody else's.
    """
    row = kosync.document_of(db, current_user.id, document)
    if row is None:
        raise _no_such_document()
    kosync.link(db, row, book.id)
    db.commit()
    return _out(row)


@member.delete(
    "/books/{book_id}/documents/{document}", status_code=status.HTTP_204_NO_CONTENT
)
@refuses(404)
def unlink_kosync_document(
    document: DocumentName, book: BookForRead, current_user: CurrentUser, db: DbSession
) -> None:
    """Send a document linked to this Book back to the inbox.

    What it already wrote to the reading log stays: those rows say where the
    member was on a day, which a wrong link does not make false.
    """
    row = kosync.document_of(db, current_user.id, document)
    if row is None or row.book_id != book.id:
        raise _no_such_document()
    kosync.unlink(row)
    db.commit()


def _no_such_document() -> HTTPException:
    """A fresh instance per raise: see `dependencies._not_found`."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
