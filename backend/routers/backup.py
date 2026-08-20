"""Downloading the whole catalogue, and putting one back.

Admin only, both directions. A backup contains every account's password hash
and every member's private books, and a restore replaces the lot.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

import backup as backup_service
from auth import require_admin
from dependencies import DbSession
from models import User
from schemas import RestoreResult

router = APIRouter(prefix="/api/backup", tags=["backup"])

#: An archive is a database plus every cover image, so the ordinary upload cap
#: is far too small. This is generous enough for a household's whole library
#: and small enough that a mistaken upload cannot exhaust the pod's memory.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


@router.get("")
def download_backup(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> StreamingResponse:
    """The whole database and every cover, as a zip.

    Not paginated and not streamed row by row: the archive has to be internally
    consistent, so it is built in one pass from one session and then sent.
    A household library is megabytes, not gigabytes.
    """
    archive = backup_service.build_archive(db)
    filename = f"endpaper-backup-{date.today().isoformat()}.zip"
    return StreamingResponse(
        iter([archive]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    return RestoreResult(
        books=restored.get("books", 0),
        users=restored.get("users", 0),
        notes=restored.get("notes", 0),
        loans=restored.get("loans", 0),
        covers=restored.get("covers", 0),
    )
