"""Bulk import from other services.

Always from a file rather than an API. Goodreads retired theirs in December
2020, LibraryThing never had a general one, and asking somebody for their
password to a service we do not control is not a thing to build. An export is
the route that exists everywhere, and the only one that does not ask for a
credential.

The parser reads whatever the file turns out to be: see `backend/csv_import.py`
for how the columns are guessed and which services were used to write the
guess list.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

import csv_import
from config import MAX_UPLOAD_BYTES
from dependencies import CurrentUser, DbSession
from importing import Import
from ratelimit import import_limiter
from schemas import ImportPreviewOut, ImportPreviewRow, ImportResultOut

logger = logging.getLogger("endpaper.imports")

router = APIRouter(prefix="/api/imports", tags=["imports"])



def _read_upload(file: UploadFile) -> bytes:
    """The uploaded bytes, read synchronously.

    `UploadFile.file` is the underlying blocking file object. Reading it here
    rather than awaiting `file.read()` is what lets both handlers be `def`,
    which is the whole point: see the note on `import_csv`.
    """
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="That file is empty.")
    return content


def _parse(content: bytes, overrides: dict[str, str] | None = None) -> csv_import.ParsedFile:
    try:
        return csv_import.parse(content, overrides)
    except csv_import.ImportError_ as error:
        # A readable explanation beats "0 books imported" for somebody who
        # picked the wrong file.
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/preview", response_model=ImportPreviewOut)
def preview_import(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    overrides: Annotated[
        str | None,
        Query(description="Correct a guessed column, as field=header pairs"),
    ] = None,
) -> ImportPreviewOut:
    """Read a file and report what it turned out to be, writing nothing.

    A column guessed wrong is invisible until after the import, and after the
    import is too late: undoing it means finding and deleting a few hundred
    books. So the mapping is shown first, against the file's real header list,
    with the first few rows as the parser actually read them.

    Rate limited together with the import itself, so a preview and the import
    that follows it spend two of the three a minute allows.
    """
    # Rate limited, like `/csv`. `docs/security.md` has promised
    # `/api/imports/*` at 3 a minute all along and only the import enforced it,
    # while parsing is the expensive half: measured, a 5.02 MB export of 20,000
    # rows costs 3.081 seconds of CPU, and `_read_upload` caps the body without
    # capping the rate. A preview then an import spends two of the three, which
    # is the real shape of the flow.
    import_limiter.check(current_user.username)

    # The same overrides the import will use. Without them a reader who
    # corrects a mapping cannot see the corrected result, which defeats the
    # point of looking before anything is written.
    parsed = _parse(_read_upload(file), _parse_overrides(overrides))

    return ImportPreviewOut(
        headers=parsed.headers,
        mapping=parsed.mapping,
        delimiter=parsed.delimiter,
        total_rows=len(parsed.rows),
        skipped=parsed.skipped,
        # A count of this file rather than "often hundreds", so the warning
        # about bringing tags across is about the file in hand.
        distinct_tags=len({tag.lower() for row in parsed.rows for tag in row.tags}),
        rows=[
            ImportPreviewRow(
                title=row.title,
                author=row.author,
                isbn=row.isbn,
                status=row.status.value if row.status else None,
            )
            for row in parsed.rows[: csv_import.PREVIEW_ROWS]
        ],
    )


@router.post("/csv", response_model=ImportResultOut)
def import_csv(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    create_missing: Annotated[
        bool, Query(description="Add books from the export that are not in the catalogue")
    ] = False,
    apply_tags: Annotated[
        bool, Query(description="Create the file's tags and put them on the books")
    ] = False,
    overrides: Annotated[
        str | None,
        Query(
            description=(
                "Correct a guessed column, as field=header pairs separated by "
                "commas, e.g. title=Book Name,author=Written By"
            )
        ),
    ] = None,
) -> ImportResultOut:
    """Apply a library export from Goodreads, LibraryThing, StoryGraph, Libib
    or anything else with a title column.

    **Declared `def`, not `async def`, and that is load bearing.** Everything
    below is blocking: SQLAlchemy has no async here. An `async` handler runs on
    the event loop, so a running import stops the whole application answering.
    Measured on a 3000 row file: `GET /api/books` went from 7ms to **14.4
    seconds**, and exactly one such request completed for the duration.
    FastAPI runs a `def` handler in a threadpool instead, which costs nothing
    and keeps the app alive while a library comes across.

    Statuses are **personal**, so this only ever writes the importing member's
    own `user_books` rows. Importing your shelves does not change what anyone
    else has read, and two members can import their own exports without
    fighting over the same books.

    Books created by `create_missing` are marked `ownership=unknown`: a reading
    history is not evidence of possession. They are then confirmed together
    from the library view, which is what the bulk ownership endpoint is for.

    `apply_tags` is off by default and deliberately so. A Goodreads export's
    tag column is its shelves, which for most people is a few hundred one-off
    names, and turning all of them into tags here buries the curated list under
    somebody's filing habits from another app.
    """
    import_limiter.check(current_user.username)

    parsed = _parse(_read_upload(file), _parse_overrides(overrides))

    return Import.for_member(db, current_user.id).apply(
        parsed, create_missing=create_missing, apply_tags=apply_tags
    )


def _parse_overrides(raw: str | None) -> dict[str, str]:
    """`title=Book Name,author=Written By` into a mapping.

    A pair with no `=` is skipped rather than raising. This parameter exists to
    rescue an import, and refusing the whole file over one malformed pair would
    be the opposite of that.
    """
    if not raw:
        return {}
    overrides: dict[str, str] = {}
    for pair in raw.split(","):
        field_name, separator, header = pair.partition("=")
        if separator and field_name.strip() and header.strip():
            overrides[field_name.strip()] = header.strip()
    return overrides
