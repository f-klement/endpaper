"""The local copy of each declared subject vocabulary: filled in the background,
read by exact label.

**Where the copy lives**: two tables in the library's own database, so it rides
the backup, the export and the restore with everything else (owner,
2026-11-20). `models.VocabularyLabel` holds a row per label and
`models.VocabularyCopy` a row per vocabulary saying which load is current.

**How a load becomes current** (ADR 0009, section 4): the release is fetched to
a file beside the data directory's copy, converted by `vocabulary_dumps`, read
back through `vocabularies.read_entries` against the count and digest the
converter recorded, and written under the next generation in short
transactions, so the rest of the application keeps writing while it runs.
Only then does one transaction point `VocabularyCopy` at it; the previous
generation answers every lookup until that moment and is deleted after it. A
load that fails at any step leaves the previous copy, or none, answering.

**A source that may be queried is not one that may be copied**: a scheme whose
licence permits no copy has no `origin` once declared, and `start` refuses it.

**One load at a time**, on a daemon thread per request, so a refresh of both
vocabularies queues the second and a shutdown is never held by a download.
Progress is the process's own and is lost with it; what survives a restart is
what the swap wrote.
"""

import asyncio
import contextlib
import email.utils
import functools
import hashlib
import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from sqlalchemy import CursorResult, Delete, and_, delete, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

import config
import fetch
import vocabularies
import vocabulary_dumps
from database import Base, SessionLocal
from enums import HeadingUse, VocabularyLoadPhase
from models import (
    VOCABULARY_IDENTIFIER_MAX,
    VOCABULARY_LABEL_MAX,
    VocabularyCopy,
    VocabularyLabel,
    datestamp_now,
)
from vocabularies import Entry, Scheme

logger = logging.getLogger("endpaper.vocabulary_copy")

#: Label rows written per transaction. Small enough that a write elsewhere in
#: the application waits a moment rather than the length of a load.
BATCH: Final = 5000

#: The most bytes a release download may run to. The converter's own output
#: ceiling, since a release is compressed and smaller than what it converts to.
MAX_RELEASE: Final = vocabulary_dumps.MAX_DATA_FILE

#: The longest a release download may take, start to finish, after which the
#: load fails and the next one queued begins. Measured 2026-11-20: the GND
#: release is 26,336,971 bytes and LCSH 66,188,602, so this admits a link of
#: about 37 KB/s for the larger. Without it a source sending a byte just inside
#: each read's timeout held `_ONE_LOAD` for the life of the process.
RELEASE_SECONDS: Final = 1800

#: What a failure message keeps, in characters, for the status a client shows.
_ERROR_MAX: Final = 300

_LABELS: Final = Base.metadata.tables["vocabulary_labels"]


class Refused(Exception):
    """A load `start` will not begin, with the reason."""


class Unknown(LookupError):
    """No declared vocabulary has this id."""


@dataclass(frozen=True, slots=True)
class Progress:
    """Where a load stands. `done` and `total` count bytes while fetching and
    entries while loading; `total` is None where the source did not say."""

    phase: VocabularyLoadPhase
    done: int = 0
    total: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Status:
    """One declared vocabulary, what is loaded of it, and any load under way."""

    scheme: Scheme
    copyable: bool
    copy: VocabularyCopy | None
    progress: Progress | None


type Report = Callable[[Progress], None]


@functools.cache
def declared() -> tuple[Scheme, ...]:
    """The schemes the shipped declaration names. No catalogue source answers
    suggestions yet, so none may name one."""
    return vocabularies.load_declaration(vocabularies.DECLARATION.read_text())


def scheme(scheme_id: str) -> Scheme:
    """The declared scheme `scheme_id` names, or `Unknown`."""
    found = next((one for one in declared() if one.id == scheme_id), None)
    if found is None:
        raise Unknown(scheme_id)
    return found


def copyable(declared_scheme: Scheme) -> bool:
    """Whether a copy of the scheme may be kept and fetched: its licence left it
    a data file and an origin (`vocabularies.LICENCES_PERMITTING_A_COPY`)."""
    return declared_scheme.data_file is not None and declared_scheme.origin is not None


# ── The background load ──────────────────────────────────────────────────────

_STATE_LOCK: Final = threading.Lock()
#: Held for the whole of a load, so a second waits in `QUEUED`.
_ONE_LOAD: Final = threading.Lock()
#: Set while `no_load` rather than a load holds `_ONE_LOAD`, so a second
#: restore is told a restore is running. Without it the refusal names a
#: vocabulary download that nobody started.
_A_RESTORE_HOLDS: Final = threading.Event()
_PROGRESS: dict[str, Progress] = {}
_THREADS: dict[str, threading.Thread] = {}


def statuses(db: Session) -> list[Status]:
    """Every declared vocabulary, in declaration order."""
    copies = {row.scheme: row for row in db.scalars(select(VocabularyCopy))}
    with _STATE_LOCK:
        progress = dict(_PROGRESS)
    return [
        Status(scheme=one, copyable=copyable(one), copy=copies.get(one.id), progress=progress.get(one.id))
        for one in declared()
    ]


def running(scheme_id: str) -> threading.Thread | None:
    """The thread loading `scheme_id`, while it is alive."""
    with _STATE_LOCK:
        thread = _THREADS.get(scheme_id)
    return thread if thread is not None and thread.is_alive() else None


def start(
    scheme_id: str,
    directory: Path | None = None,
    sessions: Callable[[], Session] = SessionLocal,
) -> threading.Thread:
    """Begin fetching and loading `scheme_id` in the background.

    `Unknown` for an undeclared id; `Refused` where the licence permits no copy
    or a load of it is already queued or running. `directory` is where the
    release and the converted file are written, the data directory by default.
    """
    target = scheme(scheme_id)
    if not copyable(target):
        raise Refused(f"{target.id}: its licence does not permit a local copy")
    with _STATE_LOCK:
        alive = _THREADS.get(target.id)
        if alive is not None and alive.is_alive():
            raise Refused(f"{target.id}: a download is already under way")
        thread = threading.Thread(
            target=_run,
            args=(target, directory or config.DATA_DIR, sessions),
            name=f"vocabulary-{target.id}",
            daemon=True,
        )
        _THREADS[target.id] = thread
        _PROGRESS[target.id] = Progress(VocabularyLoadPhase.QUEUED)
    thread.start()
    return thread


@contextlib.contextmanager
def no_load() -> Iterator[None]:
    """No load runs while the body does: `Refused` where one is under way or
    another body holds it, and a load asked for meanwhile waits in `QUEUED`
    until the body ends.

    **For a restore**, which empties both tables and writes the archive's. A
    load writing its next generation beside it would go on inserting into the
    restored table, and its swap would make current a generation whose earlier
    batches the restore had deleted, counted as complete.

    **Within one process only**: `_ONE_LOAD` is a `threading.Lock`, which
    holds because the image's `CMD` starts one uvicorn worker. A second worker
    or a second replica would not be held by it.
    """
    if not _ONE_LOAD.acquire(blocking=False):
        if _A_RESTORE_HOLDS.is_set():
            raise Refused("another restore is under way")
        raise Refused("a vocabulary download is under way")
    _A_RESTORE_HOLDS.set()
    try:
        yield
    finally:
        _A_RESTORE_HOLDS.clear()
        _ONE_LOAD.release()


def _report(scheme_id: str, progress: Progress) -> None:
    with _STATE_LOCK:
        _PROGRESS[scheme_id] = progress


def _run(target: Scheme, directory: Path, sessions: Callable[[], Session]) -> None:
    """One load, start to finish, recording how it ended.

    **Every failure is caught and recorded**, because this is a thread's whole
    body: an exception left to escape is printed to the log and the status
    would say `loading` for the life of the process.
    """
    with _ONE_LOAD:
        try:
            refresh(target, directory, sessions, functools.partial(_report, target.id))
        except Exception as failure:
            logger.exception("%s: the local copy was not refreshed", target.id)
            _report(target.id, Progress(VocabularyLoadPhase.FAILED, error=str(failure)[:_ERROR_MAX]))
            return
    with _STATE_LOCK:
        _PROGRESS.pop(target.id, None)


def refresh(target: Scheme, directory: Path, sessions: Callable[[], Session], report: Report) -> int:
    """Fetch, convert and load `target`, then make the load current; the entry
    count loaded. The release and the converted file are removed either way."""
    if target.origin is None or target.data_file is None:
        raise Refused(f"{target.id}: its licence does not permit a local copy")
    data_file = directory / target.data_file
    data_file.parent.mkdir(parents=True, exist_ok=True)
    _sweep(data_file)
    download = data_file.with_name(f".{data_file.name}.release")
    try:
        released = fetch_release(target.origin, download, report)
        report(Progress(VocabularyLoadPhase.CONVERTING))
        with download.open("rb") as release_bytes:
            release = vocabulary_dumps.convert(target, release_bytes, data_file)
        download.unlink()
        fetched_at = datestamp_now()
        with sessions() as db:
            entries = vocabularies.read_entries(data_file, target, release)
            return load(db, target.id, entries, fetched_at, released, _counting(report, release.entries))
    finally:
        download.unlink(missing_ok=True)
        data_file.unlink(missing_ok=True)


def _sweep(data_file: Path) -> None:
    """Remove what a conversion killed with its process left beside `data_file`.

    `vocabulary_dumps` writes aside under a `mkstemp` name, so each process
    stopped mid conversion left another file of up to `MAX_RELEASE`. Safe
    under `_ONE_LOAD`: no other load of this vocabulary is converting.
    """
    for partial in data_file.parent.glob(f".{data_file.name}.*.partial"):
        partial.unlink(missing_ok=True)


def _counting(report: Report, total: int) -> Callable[[int], None]:
    return lambda done: report(Progress(VocabularyLoadPhase.LOADING, done=done, total=total))


# ── The fetch ────────────────────────────────────────────────────────────────


def fetch_release(url: str, path: Path, report: Report) -> datetime | None:
    """Stream the release at `url` to `path` through `fetch.download`; its
    `Last-Modified`, as naive UTC.

    **No digest is checked here.** Both shipped releases are gzip, whose trailer
    carries the length and a CRC that the conversion checks, so a download cut
    short fails there; a response shorter than its `Content-Length` fails in
    the client before that.
    """
    report(Progress(VocabularyLoadPhase.FETCHING))

    def fetched(done: int, total: int | None) -> None:
        report(Progress(VocabularyLoadPhase.FETCHING, done=done, total=total))

    downloaded = asyncio.run(
        fetch.download(url, path, limit=MAX_RELEASE, seconds=RELEASE_SECONDS, progress=fetched)
    )
    return _released(downloaded.last_modified)


def _released(header: str | None) -> datetime | None:
    """An HTTP date as naive UTC, or None where it is absent or unreadable."""
    try:
        moment = email.utils.parsedate_to_datetime(header or "")
    except TypeError, ValueError:
        return None
    zoned = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return zoned.astimezone(UTC).replace(tzinfo=None)


# ── The load and the swap ────────────────────────────────────────────────────


def load(
    db: Session,
    scheme_id: str,
    entries: Iterable[Entry],
    fetched_at: datetime,
    released: datetime | None,
    progress: Callable[[int], None] = lambda _done: None,
) -> int:
    """Write `entries` as the next generation of `scheme_id`, then make it current.

    Rows a load stopped halfway left behind are removed first. A failure while
    writing removes this load's rows and re-raises, leaving the current copy as
    it was. The count of entries kept is returned; an entry whose identifier or
    preferred label is past its column, or whose identifier came earlier in the
    release, is passed over and logged.
    """
    current = db.get(VocabularyCopy, scheme_id)
    keep = current.generation if current is not None else None
    _discard(db, scheme_id, keep)
    generation = (keep or 0) + 1
    try:
        kept = _write(db, scheme_id, generation, entries, progress)
    except BaseException:
        db.rollback()
        _discard(db, scheme_id, keep)
        raise
    _swap(db, scheme_id, generation, kept, fetched_at, released)
    return kept


def _discard(db: Session, scheme_id: str, keep: int | None) -> None:
    """Delete every row of `scheme_id` but those of generation `keep`, `BATCH`
    rows to a transaction.

    **In batches for the reason the load writes in batches.** One statement
    over a whole generation held SQLite's write lock for its length, and
    `database.py` gives every other writer a five second `busy_timeout`.
    Measured 2026-11-20 over a million synthetic rows in a pod of one CPU, beside a
    writer committing every 50 ms: one statement took 34.4 s, the writer
    waited up to 5.05 s and 6 of its 12 writes failed with `OperationalError`;
    in batches it took 120.0 s, the writer waited at most 0.73 s and none of
    its 503 writes failed.
    """
    doomed = VocabularyLabel.scheme == scheme_id
    if keep is not None:
        doomed = and_(doomed, VocabularyLabel.generation != keep)
    batch = select(VocabularyLabel.id).where(doomed).limit(BATCH).scalar_subquery()
    while _deleted(db, delete(VocabularyLabel).where(VocabularyLabel.id.in_(batch))):
        db.commit()
    db.commit()


def _deleted(db: Session, statement: Delete) -> int:
    """How many rows `statement` deleted."""
    return cast(CursorResult[Any], db.execute(statement)).rowcount


def _write(
    db: Session, scheme_id: str, generation: int, entries: Iterable[Entry], progress: Callable[[int], None]
) -> int:
    kept = passed_over = 0
    batch: list[dict[str, object]] = []
    for rows in _rows_per_entry(entries, scheme_id, generation):
        if not rows:
            passed_over += 1
            continue
        batch.extend(rows)
        kept += 1
        if len(batch) >= BATCH:
            _insert(db, batch)
            progress(kept)
    _insert(db, batch)
    progress(kept)
    if passed_over:
        logger.warning("%s: passed over %d entries, repeated or past a column", scheme_id, passed_over)
    return kept


def _rows_per_entry(
    entries: Iterable[Entry], scheme_id: str, generation: int
) -> Iterator[list[dict[str, object]]]:
    """Each entry's label rows, or an empty list for one passed over.

    **An identifier is remembered by an eight byte digest, not by itself**, so
    the set held over a whole LCSH release is a few tens of megabytes; two ids
    sharing a digest would pass the second over, at odds of one in 2**64 a pair.
    """
    seen: set[bytes] = set()
    for entry in entries:
        digest = hashlib.blake2b(entry.id.encode(), digest_size=8).digest()
        labels = _labels(entry) if digest not in seen and _fits(entry.id, VOCABULARY_IDENTIFIER_MAX) else []
        seen.add(digest)
        yield [
            {
                "scheme": scheme_id,
                "generation": generation,
                "identifier": entry.id,
                "label": label,
                "preferred": index == 0,
            }
            for index, label in enumerate(labels)
        ]


def _labels(entry: Entry) -> list[str]:
    """The preferred label first, then each alternate once, none repeating it;
    empty where the preferred label does not fit. An alternate that does not fit
    is dropped alone."""
    if not _fits(entry.subject, VOCABULARY_LABEL_MAX):
        return []
    alternates = [
        label for label in entry.synonyms if label != entry.subject and _fits(label, VOCABULARY_LABEL_MAX)
    ]
    return [entry.subject, *dict.fromkeys(alternates)]


def _fits(value: str, ceiling: int) -> bool:
    return 0 < len(value) <= ceiling


def _insert(db: Session, batch: list[dict[str, object]]) -> None:
    if batch:
        db.execute(_LABELS.insert(), batch)
        db.commit()
        batch.clear()


def _swap(
    db: Session, scheme_id: str, generation: int, kept: int, fetched_at: datetime, released: datetime | None
) -> None:
    """Point `scheme_id` at `generation` in one transaction, then drop the rest."""
    row = db.get(VocabularyCopy, scheme_id) or VocabularyCopy(scheme=scheme_id)
    row.generation, row.entries, row.fetched_at, row.released = generation, kept, fetched_at, released
    db.add(row)
    db.commit()
    _discard_after_swap(db, scheme_id, generation)


def _discard_after_swap(db: Session, scheme_id: str, generation: int) -> None:
    """`_discard` once the new copy is current, logged rather than raised.

    **The load has succeeded by now**: lookups read the new generation and
    `fetched_at` says so, so a failure here reported as a failed load would
    contradict the copy in use. The rows left are removed by the next load.
    """
    try:
        _discard(db, scheme_id, generation)
    except Exception:
        db.rollback()
        logger.exception("%s: loaded, and the previous copy's rows are left for the next load", scheme_id)


# ── Lookups ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Heading:
    """One entry of a copy: its identifier and its preferred label."""

    identifier: str
    label: str


def _current(label_row: type[VocabularyLabel]) -> ColumnElement[bool]:
    return and_(VocabularyCopy.scheme == label_row.scheme, VocabularyCopy.generation == label_row.generation)


def preferred_identifiers(db: Session, scheme_id: str, label: str) -> tuple[str, ...]:
    """The identifiers of every entry whose preferred label in `scheme_id`'s
    current copy is exactly `label`, composed as an import composes it.

    Empty where no entry has it, or no copy is loaded. More than one where the
    vocabulary itself gives two entries one preferred label.
    """
    found = db.scalars(
        select(VocabularyLabel.identifier)
        .join(VocabularyCopy, _current(VocabularyLabel))
        .where(
            VocabularyLabel.scheme == scheme_id,
            VocabularyLabel.label == vocabularies.heading_text(label),
            VocabularyLabel.preferred.is_(True),
        )
        .order_by(VocabularyLabel.identifier)
    )
    return tuple(found)


def headings_for(db: Session, scheme_id: str, label: str) -> tuple[Heading, ...]:
    """Every entry of `scheme_id`'s current copy carrying `label` as its
    preferred or an alternate label, each under its preferred label: a search
    for a variant finds the preferred term."""
    matched = aliased(VocabularyLabel)
    found = db.execute(
        select(VocabularyLabel.identifier, VocabularyLabel.label)
        .join(VocabularyCopy, _current(VocabularyLabel))
        .join(
            matched,
            and_(
                matched.scheme == VocabularyLabel.scheme,
                matched.generation == VocabularyLabel.generation,
                matched.identifier == VocabularyLabel.identifier,
            ),
        )
        .where(
            VocabularyLabel.scheme == scheme_id,
            VocabularyLabel.preferred.is_(True),
            matched.label == vocabularies.heading_text(label),
        )
        .distinct()
        .order_by(VocabularyLabel.identifier)
    )
    return tuple(Heading(identifier=row.identifier, label=row.label) for row in found)


#: How many labels one lookup puts in an `IN`, well under SQLite's bound
#: parameter limit.
_ASKED_AT_ONCE: Final = 500


def held_preferred_labels(db: Session, asked: Iterable[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    """The `(scheme, label)` pairs of `asked` whose label, composed as an import
    composes it, is a preferred label in that scheme's current copy. Returned
    as asked, so a caller finds its own question in the answer.

    A query per scheme and `_ASKED_AT_ONCE` labels, never one per label: a MARC
    upload asks once for the whole file. A scheme with no copy loaded holds
    nothing.
    """
    by_scheme: dict[str, dict[str, list[str]]] = {}
    for scheme_id, label in asked:
        by_scheme.setdefault(scheme_id, {}).setdefault(vocabularies.heading_text(label), []).append(label)
    return frozenset(
        (scheme_id, label)
        for scheme_id, labels in by_scheme.items()
        for found in _preferred_among(db, scheme_id, sorted(labels))
        for label in labels[found]
    )


def _preferred_among(db: Session, scheme_id: str, texts: list[str]) -> Iterator[str]:
    """Each of `texts` that is a preferred label in `scheme_id`'s current copy."""
    for start in range(0, len(texts), _ASKED_AT_ONCE):
        yield from db.scalars(
            select(VocabularyLabel.label)
            .join(VocabularyCopy, _current(VocabularyLabel))
            .where(
                VocabularyLabel.scheme == scheme_id,
                VocabularyLabel.label.in_(texts[start : start + _ASKED_AT_ONCE]),
                VocabularyLabel.preferred.is_(True),
            )
            .distinct()
        )


# ── The suggest field ────────────────────────────────────────────────────────

#: The fewest characters a suggestion is asked for. One letter would rank a
#: twenty-sixth of a vocabulary for a keystroke nobody reads the answer to.
SUGGEST_MIN: Final = 2

#: The most headings one suggestion answers: what a dropdown shows unscrolled.
SUGGEST_MAX: Final = 10

#: Label rows read per suggestion before they are folded to entries. An entry
#: matching under its preferred and an alternate label is two rows, so this
#: leaves room for the fold while bounding the read whatever the prefix.
_SUGGEST_ROWS: Final = 4 * SUGGEST_MAX

#: What every declared vocabulary may be used as. The declaration holds subject
#: vocabularies alone (its `subjects:` key, ADR 0009) and both copies are subject
#: files, the GND's Sachbegriffe and LCSH, so the use is the file's rather than
#: an entry's: no column records an entry's `008/14` to `16`, and the converter
#: reads no MARC to take one from. What the file's use does not cover is LCSH's
#: subdivision records, `008/09` rather than `008/14` to `16`, valid only under
#: a heading: `vocabulary_dumps` leaves those out of a copy as it converts one.
_DECLARED_USE: Final = HeadingUse.SUBJECT

#: Above every character, so `prefix + _PAST_EVERY_CHARACTER` bounds the labels
#: beginning with `prefix` from above.
_PAST_EVERY_CHARACTER: Final = "\U0010ffff"


def suggest(db: Session, scheme_id: str, typed: str, use: HeadingUse) -> tuple[Heading, ...]:
    """Up to `SUGGEST_MAX` entries of `scheme_id`'s current copy with a label
    beginning with `typed`, each under its preferred label, in label order.

    A preferred or an alternate label matches, so typing a variant offers the
    preferred term. `typed` is composed as an import composes a label, and its
    first letter is also tried upper cased, since both files capitalise a
    heading. Nothing under `SUGGEST_MIN` characters, for a `use` the copies do
    not serve, or before a copy is loaded.

    **Reads the local copy only**, never a vocabulary service: this answers a
    keystroke, and one request per keystroke to somebody else's free service is
    the politeness problem #135 names.
    """
    text = vocabularies.heading_text(typed)
    if use is not _DECLARED_USE or len(text) < SUGGEST_MIN:
        return ()
    identifiers = _matching_identifiers(db, scheme_id, text)
    if not identifiers:
        return ()
    # A comprehension and not `dict(result)`: a `Result` has `keys()`, so
    # `dict` reads it as a mapping of column names and raises.
    preferred = {
        row.identifier: row.label
        for row in db.execute(
            select(VocabularyLabel.identifier, VocabularyLabel.label)
            .join(VocabularyCopy, _current(VocabularyLabel))
            .where(
                VocabularyLabel.scheme == scheme_id,
                VocabularyLabel.preferred.is_(True),
                VocabularyLabel.identifier.in_(identifiers),
            )
        )
    }
    # An entry missing here was swapped out between the two reads.
    return tuple(
        Heading(identifier, preferred[identifier]) for identifier in identifiers if identifier in preferred
    )


def suggestible(db: Session) -> tuple[Scheme, ...]:
    """The declared vocabularies `suggest` can answer from, those with a copy
    loaded, in the declaration's order."""
    loaded = set(db.scalars(select(VocabularyCopy.scheme)))
    return tuple(declared_scheme for declared_scheme in declared() if declared_scheme.id in loaded)


def _matching_identifiers(db: Session, scheme_id: str, text: str) -> list[str]:
    """The first `SUGGEST_MAX` distinct entries with a label beginning with
    `text` or its capitalised spelling, in label order."""
    spellings = dict.fromkeys((text, text[:1].upper() + text[1:]))
    rows = db.scalars(
        select(VocabularyLabel.identifier)
        .join(VocabularyCopy, _current(VocabularyLabel))
        .where(
            VocabularyLabel.scheme == scheme_id,
            or_(*(_begins_with(prefix) for prefix in spellings)),
        )
        .order_by(VocabularyLabel.label, VocabularyLabel.identifier)
        .limit(_SUGGEST_ROWS)
    )
    return list(dict.fromkeys(rows))[:SUGGEST_MAX]


def _begins_with(prefix: str) -> ColumnElement[bool]:
    """A label beginning with `prefix`, case sensitively.

    **The range is what reads the index**, `ix_vocabulary_labels_label`, so a
    keystroke reads the matching rows rather than the whole copy: SQLite's
    `LIKE` folds ASCII case and so cannot use a binary index, and PostgreSQL's
    cannot use a btree under a locale collation. **The `LIKE` is what makes it
    a prefix match on PostgreSQL**, where a locale collation's range also holds
    labels that do not begin with `prefix`; one such collation may also order a
    label that does past the upper bound, and that label is not offered. The
    `LIKE` is escaped, so a `%` or `_`
    typed is a character. On SQLite the range alone is exact, since the column
    compares bytes.
    """
    label = VocabularyLabel.label
    return and_(
        label >= prefix,
        label < prefix + _PAST_EVERY_CHARACTER,
        label.startswith(prefix, autoescape=True),
    )
