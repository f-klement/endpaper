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

**`/csv` is one route over several readers**, not one parser. Which reader ran
is chosen from the file and reported back on every preview, and `reader=` names
one by hand: `import_readers.py` is the contract and says why a service whose
compound cell no candidate header name can express gets its own reader rather
than a pre-pass. A row the file marks as deleted is dropped by every one of
them, so that is not what choosing a reader decides.
"""

import functools
import logging
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from itertools import chain, repeat
from typing import Annotated, Final

import anyio.to_thread
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

import csv_import
import harvester
import marc
import recognition
import settings_store
import vocabulary_copy
from auth import require_admin
from classifications import bounded_headings
from config import MAX_UPLOAD_BYTES
from dependencies import CurrentUser, DbSession
from errors import a_lost_race_answers_409
from import_readers import ImportReader
from importing import HarvestKeys, Import, MarcImport, recognise_stored, stored_record
from models import HARVEST_BASE_URL_MAX, HARVEST_SET_SPEC_MAX, Harvest, User
from ratelimit import import_limiter
from refusals import refuses
from schemas import (
    HarvestPreviewOut,
    HarvestResultOut,
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


def _parse(
    content: bytes,
    overrides: dict[str, str] | None = None,
    reader: ImportReader | None = None,
) -> csv_import.ParsedFile:
    try:
        return csv_import.parse(content, overrides, reader)
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
    reader: Annotated[
        ImportReader | None,
        Query(description="Read the file as this service's export, rather than detecting"),
    ] = None,
) -> ImportPreviewOut:
    """Read a file and report what it turned out to be, writing nothing.

    A column guessed wrong is invisible until after the import, and after the
    import is too late: undoing it means finding and deleting a few hundred
    books. So the mapping is shown first, against the file's real header list,
    with the first few rows as the parser actually read them.

    **`reader` is reported as well as the mapping, on every preview**, because a
    file read as the wrong service's export is the same class of silent wrong
    answer a column guessed wrong is, and it is corrected the same way: name the
    right one here and on the import that follows. Reported when it is the
    ordinary reader too: a screen that says nothing when the answer is ordinary
    cannot be checked at all.

    `excluded` and `exclusion_column` are reported the same way, count included
    when it is zero, so "this file marks nothing as deleted" is a different
    screen from "this file has no such column".

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
    parsed = _parse(_read_upload(file), _parse_overrides(overrides), reader)

    return ImportPreviewOut(
        headers=parsed.headers,
        mapping=parsed.mapping,
        delimiter=parsed.delimiter,
        reader=parsed.reader,
        total_rows=len(parsed.rows),
        skipped=parsed.skipped,
        excluded=parsed.excluded,
        exclusion_column=parsed.exclusion_column,
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
    reader: Annotated[
        ImportReader | None,
        Query(description="Read the file as this service's export, rather than detecting"),
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

    A review the file carries is kept as a **private** note: visible to the
    member who imported it and to nobody else, because the column another app
    called "private notes" must not become an instance-visible note under their
    own name. Notes written here through the app are unaffected and stay
    visible to whoever can see the book.

    Books created by `create_missing` are marked `ownership=unknown`: a reading
    history is not evidence of possession. They are then confirmed together
    from the library view, which is what the bulk ownership endpoint is for.

    `apply_tags` is off by default and deliberately so. A Goodreads export's
    tag column is its shelves, which for most people is a few hundred one-off
    names, and turning all of them into tags here buries the curated list under
    somebody's filing habits from another app.

    `reader` names which reader reads the file, and is left out for all but a
    file the detector reads as the wrong service's. A row the file's own
    exclusion column marks as deleted is dropped and counted in `excluded`
    whichever reader runs, so naming one never brings those titles back: the
    column is read wherever it appears, and the preview shows the count and the
    column before anything is written.
    """
    import_limiter.check(current_user.username)

    parsed = _parse(_read_upload(file), _parse_overrides(overrides), reader)

    # A merge over the same Books can deadlock with the import through its gap
    # fills, which update a matched Book's row: `import_marc` says why 409.
    with a_lost_race_answers_409(db, _MET_ANOTHER_CHANGE):
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
        raise HTTPException(status_code=403, detail="MARC import is a library mode feature.")


def _read_marc(db: Session, content: bytes) -> marc.ParsedMarc:
    """The file read with the local copies confirming a second indicator on a
    record the Library of Congress did not catalogue, asked once for the file."""
    try:
        return marc.read(content, functools.partial(vocabulary_copy.held_preferred_labels, db))
    except marc.MarcError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


#: How many records the preview shows.
#:
#: `csv_import.PREVIEW_ROWS`, and the same reasoning: enough to see whether the
#: records came through, few enough that a five thousand record file does not
#: come back through the browser.
_PREVIEW_RECORDS = csv_import.PREVIEW_ROWS


@router.post("/marc/preview", response_model=MarcPreviewOut)
@refuses(403)
def preview_marc(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> MarcPreviewOut:
    """Read a MARC file and report what it holds, writing nothing.

    **`already_held` is the number this exists for.** Importing the same file
    twice is the ordinary accident in a catalogue transfer, and "will this
    double my catalogue" has to be answerable before the write.

    **Every answer the import acts on is counted, not only the match.**
    `already_held` counts what it will match, `blocked` what it will refuse for
    an ISBN this member cannot see, `in_trash` what only their trash holds and
    `ambiguous` what two Books answer, through `importing.recognise_stored`,
    the same index and the same question `MarcImport` asks, over the same
    stored records. Counting only the first overstated what an import would add
    by exactly the number of records another member holds privately.

    **What is left is an upper bound rather than an equality, and it errs
    towards promising less.** The index is read once here and grows during an
    import: `recognition.Index.remember` makes a freshly created Book findable,
    so a work listed twice in one file is created once and matched once, while
    this counts both as additions. Measured, two identical records: the preview
    would add 2 and the import created 1 and matched 1.

    **`blocked` describes the default.** It is the refusal `create_missing`
    reaches, and this endpoint takes no `create_missing` because the import
    defaults it true. With it off nothing is created, so nothing can be refused
    for a collision.

    **And it under-counts** where a record's ISBN is held invisibly but its
    title and author match a visible Book: that is a match, not a refusal. See
    `MarcPreviewOut`.

    Rate limited together with the import, so a preview and the import that
    follows it spend two of the three a minute allows. Parsing is the expensive
    half and `_read_upload` caps the body without capping the rate.
    """
    _require_library_mode(db)
    import_limiter.check(current_user.username)

    return _previewed(db, current_user.id, _read_marc(db, _read_upload(file)))


def _previewed(
    db: Session, viewer_id: int, parsed: marc.ParsedMarc, keyed: Sequence[recognition.Answer | None] = ()
) -> MarcPreviewOut:
    """`preview_marc`'s counts and rows over records already read, as `viewer_id`
    sees the shelf. The harvest preview asks through here too, so a file and a
    harvest cannot disagree about one record. `keyed` is a harvest's
    `HarvestKeys` answer per record, asked before the ladder as the apply asks
    it; a file has none."""
    index = recognition.Index.build(db, viewer_id, recognition.Source.CATALOGUE)
    # The same stored view the import matches on. Matching the raw record here
    # and the truncated one there would make the two screens disagree about the
    # records the bound acts on, which is exactly what the counts are for.
    #
    # **One list, and the rows below read it too.** They used to read
    # `parsed.records` while the counts read the projection, which is the two
    # views of one value the comment above says must not happen; it was invisible
    # only because the projection is the identity on every reachable path.
    stored = [stored_record(record) for record in parsed.records]
    # Asked once per record and kept, so the four counts read one answer each.
    # No statement per record: the index answers ids and nothing is loaded.
    answers = Counter(
        type(known or recognise_stored(index, record))
        for record, known in zip(stored, chain(keyed, repeat(None)), strict=False)
    )

    return MarcPreviewOut(
        total_records=parsed.total,
        readable=len(parsed.records),
        skipped=parsed.skipped,
        already_held=answers[recognition.Seen],
        blocked=answers[recognition.Hidden],
        in_trash=answers[recognition.InTrash],
        ambiguous=answers[recognition.Tied],
        rows=[
            MarcPreviewRow(
                title=record.title or "",
                author=record.author,
                isbn=record.isbn,
                classifications=[
                    f"{heading.scheme}:{heading.number}" for heading in bounded_headings(record.headings)
                ],
            )
            for record in stored[:_PREVIEW_RECORDS]
        ],
    )


@router.post("/marc", response_model=ImportResultOut)
@refuses(403)
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

    parsed = _read_marc(db, _read_upload(file))

    # **A merge over the same Books can deadlock with the import**, and Postgres
    # then aborts one of the two. The import locks each Book it adds a link or a
    # heading to, in record order, until its one commit, so no lock order can be
    # imposed against a merge, which takes its keeper and then its loser.
    # Aborted, the import has written nothing, and the same file sent again
    # meets the catalogue the merge left. **Not retried here**: a retry starts
    # while the merge is still finishing, so it can match the loser and then
    # find it deleted (`docs/decisions.md`). A matched Book a merge deletes
    # with no cycle, anywhere between the import's index and its commit,
    # answers the same 409: the importer raises `MetAnotherChange`.
    with a_lost_race_answers_409(db, _MET_ANOTHER_CHANGE):
        return MarcImport.for_member(db, current_user.id).apply(parsed, create_missing=create_missing)


#: The 409 for an import Postgres aborted to break a deadlock.
_MET_ANOTHER_CHANGE = (
    "Another change to the same books met this import, and nothing was imported. Import the file again."
)


# ── OAI-PMH harvest ───────────────────────────────────────────────────────────
#
# Another repository read in as a MARC import (ticket 177): `harvester.py`
# fetches, `MarcImport.for_harvest` applies. A preview then an apply, as for a
# file, and the two fetch the repository each, since nothing is kept between.


#: The `detail.code` on the 409 a harvest meets while another runs, preview or
#: apply. The apply's other 409, a lost race with another change to the same
#: books, carries none, and the card words the two apart by it:
#: `frontend/src/pages/SettingsPage/LibrarySettingsPage/components/HarvestImport.tsx`.
HARVEST_RUNNING: Final = "harvest_running"

#: The `detail.code` on the apply's 409 when the repository it names is not the
#: one stored. The client names the address its settings held when it read the
#: preview, which the preview route never echoes, so an address saved in another
#: tab, before that read or after it, is refused here: the preview may have
#: counted the stored repository under the old label. The card words it by this
#: code, and `frontend/src/pages/SettingsPage/LibrarySettingsPage/hooks.ts` drops
#: the read on it.
REPOSITORY_CHANGED: Final = "repository_changed"


def _harvest_repository(db: Session) -> str:
    """The repository an admin may harvest, or 404.

    **404 rather than the MARC routes' 403**, the house rule for a feature that
    is off: `harvester.configured_repository` answers None in a household, with
    the switch off, or with no usable address, and the route then does not
    exist.
    """
    address = harvester.configured_repository(db)
    if address is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return address


async def _harvested(base_url: str, set_spec: str | None) -> tuple[harvester.Identity, harvester.Harvested]:
    """One run over the repository, or a 502 naming what went wrong.

    502 for `opds.py`'s reason: the repository answered, or refused to, and it is
    not this application that is broken. The message never names the address.
    """
    try:
        return await harvester.harvest(base_url, set_spec=set_spec)
    except harvester.HarvestError as failure:
        raise HTTPException(status_code=502, detail=str(failure)) from None


@contextmanager
def _the_only_harvest() -> Iterator[None]:
    """`harvester.one_run`, a second run answered 409 as a second vocabulary
    download is (`routers/settings.py::download_vocabulary`)."""
    try:
        with harvester.one_run():
            yield
    except harvester.AlreadyRunning as running:
        raise HTTPException(
            status_code=409, detail={"message": str(running), "code": HARVEST_RUNNING}
        ) from None


#: A set to harvest, as the repository names it: `harvests.set_spec`'s width.
_SetSpec = Annotated[
    str | None,
    Query(max_length=HARVEST_SET_SPEC_MAX, description="Harvest only this set of the repository"),
]


@router.post("/harvest/preview", response_model=HarvestPreviewOut)
@refuses(404)
async def preview_harvest(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
    set_spec: _SetSpec = None,
) -> HarvestPreviewOut:
    """Harvest the configured repository and report what an apply would do, writing nothing.

    Admin only, library mode and the harvester's switch required. The counts are
    `preview_marc`'s, over the harvested records, with a record an earlier
    harvest of this repository created counted as already held, as the apply
    matches it; `deleted` and `truncated` are the run's own. Rate limited with
    the imports, and a 409 while another harvest, preview or apply, is running.

    **`async`, unlike the file routes**, because the wait is the network: the
    fetch runs on the event loop through `fetch.py`, and the counting, which
    blocks on the database, runs in a thread, as `routers/opds.py::sync` does.
    """
    base_url = _harvest_repository(db)
    import_limiter.check(current_user.username)

    with _the_only_harvest():
        identity, run = await _harvested(base_url, set_spec)
        previewed = await anyio.to_thread.run_sync(
            lambda: _previewed_harvest(db, current_user.id, base_url, run)
        )
    return HarvestPreviewOut.model_validate(
        previewed.model_dump() | {"repository_name": identity.name} | _run_counts(run)
    )


def _previewed_harvest(
    db: Session, viewer_id: int, base_url: str, run: harvester.Harvested
) -> MarcPreviewOut:
    """`_previewed` over a run, each record asked by its identifier first."""
    keys = HarvestKeys.from_repository(db, viewer_id, base_url)
    return _previewed(db, viewer_id, run.parsed, [keys.answer(identifier) for identifier in run.identifiers])


def _the_previewed_repository(stored: str, previewed: str) -> None:
    """A 409 unless the apply names the repository stored now.

    **The address, not a fingerprint of it**: the admin reads it in the
    settings, so sending it back discloses nothing, and the refusal's message
    never names it. Trimmed, as `configured_repository` trims what is stored
    and the settings read does not.
    """
    if previewed.strip() != stored:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "The stored repository is not the one this page read, and nothing was"
                    " harvested. Read the repository again."
                ),
                "code": REPOSITORY_CHANGED,
            },
        )


@router.post("/harvest", response_model=HarvestResultOut)
@refuses(404)
async def apply_harvest(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
    repository: Annotated[
        str,
        Query(
            max_length=HARVEST_BASE_URL_MAX,
            description="The address held when the preview was read; refused unless it is the one stored",
        ),
    ],
    set_spec: _SetSpec = None,
) -> HarvestResultOut:
    """Harvest the configured repository into the catalogue.

    Matching asks first for the Book an earlier harvest of this repository
    created from the same record, by its OAI identifier, so a Book corrected
    here since that run is still found. Then it is `import_marc`'s, as this admin sees
    the shelf: ISBN, then author and title together, so a record crediting
    somebody never matches on its title alone, while a record crediting nobody
    matches a Book crediting nobody by its title. A matched Book has its gaps
    filled and nothing overwritten. **A created Book is nobody's, public, keeps
    its record's identifier and points at the run** this records in `harvests`.
    **No heading is written**: a harvest confirms no record (owner, 2026-11-20),
    so a created Book's headings, and those of a Book keyed by the same
    identifier, wait as suggestions an admin confirms or discards on the Book,
    counted in `headings_pending`. A Book matched by ISBN or by author and
    title gets none. A deleted record is counted
    and deletes nothing. A 409 while another harvest is running, and one when
    `repository` is not the address stored now: the client held another when it
    read the preview, whether the stored one was saved before that read or after
    it, so the preview it showed was labelled with an address this would not
    harvest.
    """
    base_url = _harvest_repository(db)
    _the_previewed_repository(base_url, repository)
    import_limiter.check(current_user.username)

    with _the_only_harvest():
        return await _applied(db, current_user.id, base_url, set_spec)


async def _applied(db: Session, admin_id: int, base_url: str, set_spec: str | None) -> HarvestResultOut:
    """`apply_harvest`'s run and its one transaction, under `_the_only_harvest`."""
    started = datetime.now(UTC).replace(tzinfo=None)
    _, run = await _harvested(base_url, set_spec)

    def apply() -> HarvestResultOut:
        row = Harvest(
            base_url=base_url,
            set_spec=set_spec,
            metadata_prefix=run.prefix,
            run_by_user_id=admin_id,
            started_at=started,
            records_seen=run.seen,
        )
        db.add(row)
        db.flush()
        importer = MarcImport.for_harvest(db, admin_id, row)
        applied = importer.apply(run.parsed, identifiers=run.identifiers)
        return HarvestResultOut.model_validate(
            applied.model_dump()
            | {"harvest_id": row.id, "headings_pending": importer.headings_raised}
            | _run_counts(run)
        )

    # The same one transaction as a file import, and the same deadlock with a
    # merge through its gap fills: `import_marc` says why 409.
    with a_lost_race_answers_409(db, _MET_ANOTHER_CHANGE):
        return await anyio.to_thread.run_sync(apply)


def _run_counts(run: harvester.Harvested) -> dict[str, object]:
    """The fields of `_HarvestRun`, which both answers carry."""
    return {
        "metadata_prefix": run.prefix,
        "pages_read": run.pages_read,
        "records_seen": run.seen,
        "deleted": run.deleted,
        "truncated": run.truncated,
    }
