"""Downloading the whole catalogue, and putting one back.

Admin only, both directions. A backup contains every account's password hash
and every member's private books, and a restore replaces the lot.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse

import backup as backup_service
import downloads
from auth import require_admin
from dependencies import DbSession
from models import User
from ratelimit import backup_limiter
from schemas import RestoreResult

router = APIRouter(prefix="/api/backup", tags=["backup"])

#: An archive is a database plus every cover image, so the ordinary upload cap
#: is far too small. This is generous enough for a library's whole library
#: and small enough that a mistaken upload cannot exhaust the pod's memory.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024

#: What an archive is sent as, and the only home for the string: the route sets
#: it on the response and the route's `responses` declares it, so a literal at
#: each site would be a promise and a delivery that can disagree.
ARCHIVE_MEDIA_TYPE = "application/zip"


@router.get(
    "",
    # `response_class=Response` **and** the dictionary, because either alone is
    # weaker than it reads: the dictionary alone leaves `application/json` in
    # the 200 beside the zip, and `response_class=StreamingResponse` alone
    # declares no content at all. `routers/books.export_books` carries the
    # measurement.
    response_class=Response,
    responses={
        200: {
            "content": {ARCHIVE_MEDIA_TYPE: {}},
            "headers": downloads.DOWNLOAD_DISPOSITION,
        }
    },
)
def download_backup(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> StreamingResponse:
    """The whole database and every cover, as a zip.

    Not paginated and not streamed row by row: the archive has to be internally
    consistent, so it is built in one pass from one session and then sent.
    A library is megabytes, not gigabytes.

    **Rationed, and the schema does not say so.** The refusal is a 429 carrying
    `Retry-After`, undeclared for the reason `routers/books.export_books`
    states: this document declares a 401, a 403 or a 404 wherever the code a
    route runs builds one and no other refusal on any operation, so declaring a
    429 here alone would make it look deliberate and every other one look
    accidental. `tests/test_refusals.py` holds the first half and
    `tests/test_errors.py::TestTheDocumentDeclaresNoOtherRefusal` the second,
    because a reason described in prose rots silently where an asserted one
    reddens.

    **The limit bounds how often an archive is built and nothing else.** It
    does not bound how large one is: `MAX_ARCHIVE_BYTES` is the *restore*
    upload cap and the body size middleware's, both on `/backup/restore`, and
    the download reads neither, so `build_archive` returns the whole library as
    `bytes` with nothing above it. Nor does it bound how many are built at
    once: a sliding window counts starts, not responses in flight, so three
    concurrent builds are inside it. Both of those are a concurrency bound,
    which is a different instrument.
    """
    # After `require_admin`, which is a parameter dependency and has therefore
    # already refused by the time this line runs. A path operation dependency
    # is inserted ahead of the endpoint's own parameters, so a charge placed
    # there runs before the gate unless it depends on **whichever dependency
    # refuses**, which on this route is `require_admin` and not the
    # authenticator underneath it. Measured 2026-09-29, this worktree's
    # FastAPI: keyed on the address, which needs no session, the charge runs
    # with authentication never reached, so a caller holding none spends the
    # administrator's budget; keyed on `CurrentUser`, which is the safe shape
    # on the export because authentication is that route's only gate, a plain
    # member is charged and then answered 403. `routers/books.export_books`
    # carries the export's two shapes and the reason for the key. The safe
    # shape is named here rather than read off that route, because the gate
    # here is authorisation and there it is authentication.
    backup_limiter.check(current_user.username)

    archive = backup_service.build_archive(db)
    filename = f"endpaper-backup-{downloads.datestamp()}.zip"
    return StreamingResponse(
        iter([archive]),
        media_type=ARCHIVE_MEDIA_TYPE,
        headers=downloads.attachment(filename),
    )


@router.post("/restore", response_model=RestoreResult)
async def restore_backup(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
    file: Annotated[UploadFile, File()],
    confirm: Annotated[
        bool, Query(description="Must be true. Restoring replaces everything.")
    ] = False,
) -> RestoreResult:
    """Replace the catalogue with the contents of a backup.

    `confirm` is a required opt-in rather than a body field, so the destructive
    call cannot be made by accident by anything replaying a plain upload. This
    is the only endpoint in the app that destroys data it was not given the id
    of, and it destroys all of it.

    The archive is validated in full before the first row is deleted. A restore
    that fails halfway leaves a library that is neither the backup nor what was
    there before, which is worse than either.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Restoring replaces every book, account and cover in this library. "
                "Send confirm=true if that is what you mean to do."
            ),
        )

    data = await file.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That backup is larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB.",
        )

    try:
        restored = backup_service.restore(db, data)
    except backup_service.RestoreError as error:
        # 400, not 500: the archive is the caller's, and every one of these
        # says exactly what is wrong with it.
        raise HTTPException(status_code=400, detail=str(error)) from error

    # Built from the schema's own field names rather than enumerated by hand,
    # because the hand-written version is how a table gets counted and then
    # silently dropped on the way out. `collections` was added to `_TABLES` and
    # to `RestoreResult`, was populated by `restore()`, and still reported 0
    # here, which is precisely the "reads as a clean restore" failure the field
    # exists to prevent. `restore()` keys its counts by table name and the
    # fields are named after those tables; a field with no matching key reads 0,
    # which is what the enumeration did anyway.
    return RestoreResult(
        **{name: restored.get(name, 0) for name in RestoreResult.model_fields}
    )
