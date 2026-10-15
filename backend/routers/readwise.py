"""A member's Readwise token and their pull, behind the ordinary session.

Every route here acts on the caller's own login and nobody else's: there is no
member id in any path, so no route can be pointed at another member's token or
highlights. `readwise.py` holds what a pull does.
"""

from typing import Final

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

import credentials
import readwise
from dependencies import CurrentUser, DbSession
from enums import ReadwiseOutcome
from models import ReadwiseBook
from ratelimit import import_limiter
from schemas import (
    ReadwiseAccountOut,
    ReadwiseSyncOut,
    ReadwiseTokenIn,
    ReadwiseWaitingOut,
)
from schemas.readwise import WAITING_SHOWN

router = APIRouter(prefix="/api/readwise", tags=["readwise"])

#: The `detail.code` on the 409 when the caller has saved no token.
NOTHING_SAVED: Final = "no_token"
#: The `detail.code` on the 409 when the caller's pull is already under way.
SYNC_RUNNING: Final = "sync_running"
#: The `detail.code` on the 409 when this library has no encryption key.
NO_KEY: Final = "no_key"
#: The `detail.code` on the 400 when Readwise refuses the token being saved.
#: Not 422, which the schema types as a list of validation errors.
REFUSED: Final = "token_refused"
#: The `detail.code` on the 502 when Readwise cannot say whether it is good.
UNAVAILABLE: Final = "unavailable"


def _detail(code: str, message: str) -> dict[str, str]:
    return {"message": message, "code": code}


_RUNNING: Final = _detail(SYNC_RUNNING, "A pull is under way. Try again when it ends.")


def _account(db: DbSession, member_id: int) -> ReadwiseAccountOut:
    login = readwise.login_of(db, member_id)
    waiting = (
        db.query(ReadwiseBook.title, ReadwiseBook.author)
        .filter(ReadwiseBook.user_id == member_id, ReadwiseBook.book_id.is_(None))
        .order_by(ReadwiseBook.title, ReadwiseBook.id)
        .limit(WAITING_SHOWN)
        .all()
    )
    return ReadwiseAccountOut(
        has_token=login is not None,
        token_set_at=login.set_at if login is not None else None,
        last_run_at=login.last_run_at if login is not None else None,
        last_outcome=login.last_outcome if login is not None else None,
        waiting_count=readwise.waiting_count(db, member_id),
        waiting=[ReadwiseWaitingOut(title=title, author=author) for title, author in waiting],
    )


@router.get("/account", response_model=ReadwiseAccountOut)
def get_readwise_account(current_user: CurrentUser, db: DbSession) -> ReadwiseAccountOut:
    """Whether the caller has saved a token, how their last pull went, and
    which Readwise books wait for a Book. The token itself is never served."""
    return _account(db, current_user.id)


@router.put("/token", response_model=ReadwiseAccountOut)
async def save_readwise_token(
    payload: ReadwiseTokenIn, current_user: CurrentUser, db: DbSession
) -> ReadwiseAccountOut:
    """Check the token with Readwise, then seal it as the caller's.

    **Checked before it is stored**, so a mistyped token is refused here rather
    than discovered by the first pull: 400 `token_refused` when Readwise says
    no, 502 `unavailable` when it cannot be asked. 409 `no_key` when this
    library has no encryption key to seal it with.

    Replacing a token starts the next pull from the beginning, since the new
    one may be another Readwise account. The first pull runs with the daily
    job, or from the sync button.

    **Rate limited first, before anything is checked**, on the import limiter
    the pull shares: each save asks Readwise once, and a saved token starts the
    pull over.
    """
    import_limiter.check(current_user.username)
    if credentials.key_material() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail(
                NO_KEY,
                "This library has no encryption key, so a Readwise token cannot be "
                "stored. An admin can create one on the Catalogue settings screen.",
            ),
        )
    checked = await readwise.check(payload.token)
    if checked is ReadwiseOutcome.REFUSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_detail(REFUSED, "Readwise refused that token."),
        )
    if checked is not None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_detail(
                UNAVAILABLE,
                "Readwise could not be asked whether that token is good. Try again later.",
            ),
        )
    if current_user.id in readwise.running():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_RUNNING)
    envelope = readwise.seal(current_user.id, payload.token)
    login = readwise.login_of(db, current_user.id)
    if login is None:
        db.add(readwise.new_login(current_user.id, envelope))
        try:
            db.commit()
        except IntegrityError:
            # A first save from another process won the insert; replace its
            # token with this one, as a second save would.
            db.rollback()
            login = readwise.login_of(db, current_user.id)
    if login is not None:
        readwise.replace_token(db, login, envelope)
        db.commit()
    return _account(db, current_user.id)


@router.delete("/token", status_code=status.HTTP_204_NO_CONTENT)
async def forget_readwise_token(current_user: CurrentUser, db: DbSession) -> None:
    """Remove the caller's token and the pull's state. Needs no key, so a
    token nobody can open can still be removed. Highlights already pulled
    stay; each is the member's to share or keep.

    **`async def`, so the check and the removal run on the event loop with no
    await between them**: a pull starts on the same loop, so none can start
    between the two and write after the token is gone."""
    if current_user.id in readwise.running():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_RUNNING)
    readwise.forget(db, current_user.id)


@router.post("/sync", response_model=ReadwiseSyncOut)
async def sync_readwise(current_user: CurrentUser, db: DbSession) -> ReadwiseSyncOut:
    """Pull the caller's changed highlights now, as the daily job does.

    How it ended is the answer's `outcome`, never a status: a refused token or
    a Readwise that cannot be reached is a 200 saying so, recorded on the
    account as the daily job's would be. 409 `no_token` without a saved token,
    409 `sync_running` while the caller's pull is already under way. Rate
    limited on the import limiter, with the other bulk writes.
    """
    import_limiter.check(current_user.username)
    try:
        result = await readwise.sync(db, current_user.id)
    except readwise.NoToken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail(NOTHING_SAVED, "Save a Readwise token first."),
        ) from None
    except readwise.AlreadyRunning:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_RUNNING) from None
    counts = result.counts
    return ReadwiseSyncOut(
        outcome=result.outcome,
        created=counts.created,
        updated=counts.updated,
        unchanged=counts.unchanged,
        deleted=counts.deleted,
        skipped=counts.skipped,
        waiting_count=result.waiting_count,
    )
