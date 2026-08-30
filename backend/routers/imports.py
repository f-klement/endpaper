"""Bulk import from other services.

Always from a file rather than an API. Goodreads retired theirs in December
2020, LibraryThing never had a general one, and asking somebody for their
password to a service we do not control is not a thing to build. An export is
the route that exists everywhere, and the only one that does not ask for a
credential.

The parser reads whatever the file turns out to be: see `backend/csv_import.py`
for how the columns are guessed and which services were used to write the
guess list.

**Two formats and two audiences.** `/csv` reads a person's shelf out of a
service they are leaving and writes their reading record. `/marc` reads another
institution's catalogue and writes no reading record at all: see
`importing.MarcImport` for why that makes them two appliers rather than one
with a flag. MARC is a library mode feature and the routes enforce it.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

import csv_import
import marc
import settings_store
from classifications import bounded_headings
from config import MAX_UPLOAD_BYTES
from dependencies import CurrentUser, DbSession
from importing import Import, MarcImport, MarcIndex, bounded_fields
from ratelimit import import_limiter
from schemas import (
    ImportPreviewOut,
    ImportPreviewRow,
    ImportResultOut,
    MarcPreviewOut,
    MarcPreviewRow,
)

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


# ── MARC ──────────────────────────────────────────────────────────────────────
#
# The other direction of the exchange `GET /api/books/export?format=marcxml`
# opens. Both are library mode features and both say so on the server, because
# hiding a control in the browser is advice to one client.


def _require_library_mode(db: Session) -> None:
    """Refuse a MARC route unless the Library is running as one.

    **403 rather than 404**, which is the opposite of the public catalogue's
    answer and is right for a different caller. A stranger asking for an
    unpublished catalogue is told 404 because a 403 would confirm the
    deployment holds one. Here the caller is a signed in member, and
    `GET /api/settings/features` already tells anybody at all whether library
    mode is on, so there is nothing a 403 discloses. It is the same answer
    `routers/auth.py` gives when registration is closed.
    """
    if not settings_store.library_mode(db):
        raise HTTPException(
            status_code=403, detail="MARC import is a library mode feature."
        )


def _read_marc(content: bytes) -> marc.ParsedMarc:
    try:
        return marc.read(content)
    except marc.MarcError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


#: How many records the preview shows.
#:
#: `csv_import.PREVIEW_ROWS`, and the same reasoning: enough to see whether the
#: records came through, few enough that a five thousand record file does not
#: come back through the browser.
_PREVIEW_RECORDS = csv_import.PREVIEW_ROWS


@router.post("/marc/preview", response_model=MarcPreviewOut)
def preview_marc(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> MarcPreviewOut:
    """Read a MARC file and report what it holds, writing nothing.

    **`already_held` is the number this exists for.** Importing the same file
    twice is the ordinary accident in a catalogue transfer, and "will this
    double my catalogue" has to be answerable before the write.

    **Both of the import's refusals are modelled, not one.** `already_held`
    counts what it will match and `blocked` counts what it will refuse for an
    ISBN this member cannot see, through `MarcIndex.holds` and
    `MarcIndex.would_refuse`, which are the same index and the same predicates
    `MarcImport` applies, over the same `bounded_fields`. Counting only the
    first overstated what an import would add by exactly the number of records
    another member holds privately.

    **What is left is an upper bound rather than an equality, and it errs
    towards promising less.** The index is read once here and mutated during an
    import: `MarcIndex.remember` makes a freshly created Book findable, so a
    work listed twice in one file is created once and matched once, while this
    counts both as additions. Measured, two identical records: the preview would
    add 2 and the import created 1 and matched 1.

    **`blocked` describes the default.** `would_refuse` is the refusal
    `create_missing` reaches, and this endpoint takes no `create_missing`
    because the import defaults it true. With it off nothing is created, so
    nothing can be refused for a collision.

    **And it under-counts** where a record's ISBN is held invisibly but its
    title and author match a visible Book: that is a match, not a refusal. See
    `MarcPreviewOut`.

    Rate limited together with the import, so a preview and the import that
    follows it spend two of the three a minute allows. Parsing is the expensive
    half and `_read_upload` caps the body without capping the rate.
    """
    _require_library_mode(db)
    import_limiter.check(current_user.username)

    parsed = _read_marc(_read_upload(file))
    index = MarcIndex.build(db, current_user.id)
    # The same bounded view the import matches on. Matching the raw record here
    # and the truncated one there would make the two screens disagree about the
    # records the bound acts on, which is exactly what the counts are for.
    bounded = [bounded_fields(record) for record in parsed.records]

    return MarcPreviewOut(
        total_records=parsed.total,
        readable=len(parsed.records),
        skipped=parsed.skipped,
        # `holds`, never `find`: this is a count, and `find` loads a Book that
        # would be thrown away. See `MarcIndex.holds` for the measurement.
        already_held=sum(1 for fields in bounded if index.holds(fields)),
        blocked=sum(1 for fields in bounded if index.would_refuse(fields)),
        rows=[
            MarcPreviewRow(
                title=record.title or "",
                author=record.author,
                isbn=record.isbn,
                classifications=[
                    f"{heading.scheme.value}:{heading.number}"
                    for heading in bounded_headings(record.headings)
                ],
            )
            for record in parsed.records[:_PREVIEW_RECORDS]
        ],
    )


@router.post("/marc", response_model=ImportResultOut)
def import_marc(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    create_missing: Annotated[
        bool, Query(description="Add records this catalogue does not already hold")
    ] = True,
) -> ImportResultOut:
    """Apply a MARC21 file another library exported.

    MARCXML only. `enums.ExportFormat` says why the binary serialisation is not
    read, and it is the same reason it is not written.

    **Declared `def`, not `async def`, for `import_csv`'s reason**, which is
    load bearing rather than stylistic: everything below blocks, and an `async`
    handler runs on the event loop, so a running import stops the whole
    application answering. Measured on a 3000 row file, `GET /api/books` went
    from 7ms to 14.4 seconds.

    **Nothing personal is written.** A catalogue record carries no reading
    status, no rating and no review, so this touches no `user_books` row and
    changes nothing about what anybody has read. `statuses_updated` comes back
    zero for that reason rather than because nothing needed changing.

    **`create_missing` defaults to true, where the CSV importer defaults it to
    false.** A reading history is mostly books the household does not own, so
    creating them by default would fill the shelf; a catalogue transfer that
    adds no records has transferred nothing.

    Records added this way arrive `ownership=unknown`: another institution's
    record says that institution holds the book. They are confirmed together
    from the library view, which is what the bulk ownership endpoint is for.
    """
    _require_library_mode(db)
    import_limiter.check(current_user.username)

    parsed = _read_marc(_read_upload(file))

    return MarcImport.for_member(db, current_user.id).apply(
        parsed, create_missing=create_missing
    )
