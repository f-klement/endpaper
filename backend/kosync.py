"""KOReader's progress sync, served from this library.

KOReader's `kosync.koplugin` pushes where a member is in a document and pulls
where another of their devices got to. The protocol has no specification; the
plugin and the reference server, `koreader-sync-server`, define it, and
`routers/kosync.py` serves it at `KOSYNC_PREFIX`. This module is what a push
and a pull mean here: who is asking, what is stored, and what a position does
to the member's reading record.

**A member signs a device in with their username and a sync password this
library minted**, never their login: under proxy or directory auth there is no
login here to give, and a device stores what it is given in plain text. The
device sends `md5(password)` on every call; `users.kosync_key_digest` holds the
SHA-256 of that. A fast hash and not a password hash, because the secret is
`KEY_LENGTH` characters chosen at random rather than one a person picked: there
is no dictionary to walk, and a push arrives every few minutes against a
device's 5 second budget.

**Everything here is the member's own.** A document row is keyed by member,
and a Book is reached only through `Shelf.seen_by` for that member.
"""

import hashlib
import hmac
import math
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import file_references
from models import (
    AUTHOR_LINE_MAX,
    KOSYNC_DEVICE_MAX,
    KOSYNC_DOCUMENT_MAX,
    KOSYNC_FILENAME_MAX,
    KOSYNC_PROGRESS_MAX,
    TITLE_MAX,
    Book,
    KosyncDocument,
    ReadingProgress,
    User,
)
from reading import Reading
from shelf import Shelf

#: Where the protocol is served. The member types this, after the library's
#: own address, as KOReader's custom sync server.
KOSYNC_PREFIX: Final = "/kosync"

#: The characters a sync password is drawn from: lower case, so it is typed on
#: an e-reader's keyboard without a shift, and without `i`, `l`, `o`, `0` or
#: `1`, which a person copying it off a screen mistakes for one another.
_ALPHABET: Final = "abcdefghjkmnpqrstuvwxyz23456789"

#: How many characters a sync password has: 31 to the 16th, about 79 bits.
KEY_LENGTH: Final = 16

#: The whole percent a position must reach to mark the Book read.
_FINISHED: Final = 100

#: What an unknown member and a wrong key both compare against, so the two
#: refusals do the same work.
_NOBODY: Final = hashlib.sha256(b"").hexdigest()


# ── The sync password ─────────────────────────────────────────────────────────


def key_digest(key: str) -> str:
    """What `users.kosync_key_digest` holds for the key a device sends."""
    return hashlib.sha256(key.encode()).hexdigest()


def device_key(password: str) -> str:
    """What a device sends for this password: KOReader's `md5(password)`, lower
    case hex. MD5 because the protocol says so; it protects nothing here."""
    return hashlib.md5(password.encode(), usedforsecurity=False).hexdigest()


def mint(member: User) -> str:
    """A new sync password for this member, replacing any they had.

    Returned once and stored only as a digest of what a device will send, so
    nobody can read it back: a member who loses it mints another, and every
    device signed in with the old one is refused from then on.
    """
    password = "".join(secrets.choice(_ALPHABET) for _ in range(KEY_LENGTH))
    member.kosync_key_digest = key_digest(device_key(password))
    member.kosync_key_set_at = datetime.now(UTC).replace(tzinfo=None)
    return password


def revoke(member: User) -> None:
    """Refuse every device this member signed in, until they mint another."""
    member.kosync_key_digest = None
    member.kosync_key_set_at = None


def authenticate(db: Session, username: str | None, key: str | None) -> User | None:
    """The member these two headers name, or None.

    **No username is told apart from a wrong key**, in the answer or in the
    work: both compare a digest, so the protocol's 401 is all a caller learns.
    """
    member = db.query(User).filter(User.username == username).first() if username and key else None
    stored = member.kosync_key_digest if member is not None else None
    presented = key_digest(key or "")
    if not hmac.compare_digest(presented, stored or _NOBODY) or stored is None:
        return None
    return member


# ── A push ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Push:
    """One `PUT /syncs/progress` body, read the way the reference server reads it."""

    document: str
    progress: str
    percentage: float
    device: str
    device_id: str | None
    title: str | None
    authors: str | None
    filename: str | None


class Refused(Exception):
    """A request the protocol answers with an error body, and which one."""

    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def unauthorized() -> Refused:
    """The one refusal a device does not retry."""
    return Refused(401, 2001, "Unauthorized")


def registration_disabled() -> Refused:
    return Refused(402, 2005, "User registration is disabled.")


def _no_document() -> Refused:
    return Refused(403, 2004, "Field 'document' not provided.")


def _unservable_document() -> Refused:
    return Refused(403, 2007, "Field 'document' contains characters the read route cannot serve.")


def _invalid() -> Refused:
    return Refused(403, 2003, "Invalid request")


def checked_document(document: object) -> str:
    """The document name, or the reference server's refusal of it.

    **What a GET can route and nothing wider**: the reference server's read
    route matches `[A-Za-z0-9_]+`, so a name outside it would be stored by a
    PUT and never returned. Bounded at `KOSYNC_DOCUMENT_MAX` as well, which
    the reference is not; KOReader sends 32 characters.
    """
    if not isinstance(document, str) or not document or ":" in document:
        raise _no_document()
    if len(document) > KOSYNC_DOCUMENT_MAX or not all(
        character.isascii() and (character.isalnum() or character == "_") for character in document
    ):
        raise _unservable_document()
    return document


def _text(value: object, ceiling: int) -> str:
    """A required string field, as the reference stores it, or a refusal.

    A number is taken as its text because the reference stores whatever it is
    given in a Redis hash, which turns it into one. Anything else, or anything
    past the column, is the reference's invalid request.
    """
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise _invalid()
    text = value if isinstance(value, str) else str(value)
    if len(text) > ceiling or not _storable(text):
        raise _invalid()
    return text


def _storable(text: str) -> bool:
    """Whether a column can hold this: no NUL, and no lone surrogate, which
    JSON's `\\ud800` escape decodes to and UTF-8 cannot encode."""
    if "\x00" in text:
        return False
    try:
        text.encode()
    except UnicodeEncodeError:
        return False
    return True


def _percentage(value: object) -> float:
    """The percentage as a float, or a refusal. The reference reads it with
    `tonumber`, so a numeric string is a number too."""
    if isinstance(value, bool):
        raise _invalid()
    try:
        number = float(value) if isinstance(value, int | float | str) else math.nan
    except ValueError, OverflowError:
        raise _invalid() from None
    if not math.isfinite(number):
        raise _invalid()
    return number


def _optional(value: object, ceiling: int) -> str | None:
    """A field that may be absent, kept only if it is text that fits.

    **Never a refusal.** `metadata` is optional and the reference ignores it,
    so a push must not fail because of it: a value that is not storable text
    is dropped, and one past the column is cut to it.
    """
    if not isinstance(value, str) or not _storable(value):
        return None
    return value[:ceiling] or None


def read_push(body: object) -> Push:
    """A push body, refused in the order and with the codes the reference uses."""
    if not isinstance(body, dict):
        raise _invalid()
    document = checked_document(body.get("document"))
    if body.get("progress") is None or body.get("device") is None:
        raise _invalid()
    percentage = _percentage(body.get("percentage"))
    device_id = body.get("device_id")
    metadata = body.get("metadata")
    described = metadata if isinstance(metadata, dict) else {}
    return Push(
        document=document,
        progress=_text(body["progress"], KOSYNC_PROGRESS_MAX),
        percentage=percentage,
        device=_text(body["device"], KOSYNC_DEVICE_MAX),
        device_id=None if device_id is None else _text(device_id, KOSYNC_DEVICE_MAX),
        title=_optional(described.get("title"), TITLE_MAX),
        authors=_optional(described.get("authors"), AUTHOR_LINE_MAX),
        filename=_optional(described.get("filename"), KOSYNC_FILENAME_MAX),
    )


def record(db: Session, member: User, push: Push) -> int:
    """Store a push as this member's latest position, and return its timestamp.

    **Last write wins**, as on the reference server: nothing is compared, and a
    lower percentage from another device replaces a higher one.

    **Metadata a push leaves out is kept**, because a member may have it
    switched on for one device and not another, and absent is not a deletion.

    **The fingerprint links a document once, when its row is created**, and
    never again: a member who unlinks it has said it is not that Book, and the
    next push must not say otherwise. Then the position is applied to the
    member's reading record if the document is linked to a Book they can see.
    Does not commit.
    """
    timestamp = int(time.time())
    row = _existing(db, member.id, push.document)
    before = None if row is None else row.percentage
    if row is None:
        row = _created(db, member.id, push, timestamp)
    if row is None:
        # Another push of the same new document committed between the look
        # and the insert, and the unique index refused this one. That row is
        # the one to update now.
        row = _existing(db, member.id, push.document)
        if row is None:
            raise RuntimeError("the unique index refused a document row that is not there")
        before = row.percentage
    _write(row, push, timestamp)

    if row.book_id is not None and _can_see(db, member.id, row.book_id):
        apply(db, member.id, row.book_id, row.percentage, before)
    return timestamp


def _existing(db: Session, member_id: int, document: str) -> KosyncDocument | None:
    return (
        db.query(KosyncDocument)
        .filter(KosyncDocument.user_id == member_id, KosyncDocument.document == document)
        .first()
    )


def _created(db: Session, member_id: int, push: Push, timestamp: int) -> KosyncDocument | None:
    """A new row for a document never pushed before, linked by its fingerprint,
    or None when a concurrent push created it first.

    In a savepoint, so the refused insert is discarded alone and the request
    carries on to update the row that won.
    """
    row = KosyncDocument(
        user_id=member_id,
        document=push.document,
        book_id=_the_one_holder(db, member_id, push.document),
    )
    _write(row, push, timestamp)
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        return None
    return row


def _write(row: KosyncDocument, push: Push, timestamp: int) -> None:
    row.progress = push.progress
    row.percentage = push.percentage
    row.device = push.device
    row.device_id = push.device_id
    row.timestamp = timestamp
    for field in ("title", "authors", "filename"):
        if getattr(push, field) is not None:
            setattr(row, field, getattr(push, field))


def _the_one_holder(db: Session, member_id: int, document: str) -> int | None:
    """The Book whose file this is, when exactly one Book the member can see
    carries this fingerprint on a reference.

    `file_references.books_carrying` answers which Books; the tie rule is
    this module's. **Two or more Books leave it in the inbox**: guessing
    between copies would write a reading record to a Book the member did not
    pick.
    """
    holders = file_references.books_carrying(db, member_id, document, limit=2)
    return holders.pop() if len(holders) == 1 else None


def _can_see(db: Session, member_id: int, book_id: int) -> bool:
    """Whether a linked Book is still on this member's shelf.

    A link outlives the Book being trashed or made private by whoever owns it,
    so it is asked on every push rather than trusted.
    """
    return Shelf.seen_by(db, member_id).where(Book.id == book_id).count() > 0


def apply(db: Session, member_id: int, book_id: int, percentage: float, before: float | None) -> None:
    """What a device's position does to the member's reading record of a Book.

    **A percent row in the reading log when the whole percent moved**, and at
    most one a day per Book: a device pushes every few minutes and the log is
    of sittings, so the first move of the day is kept and the next day's first
    move is the next row. "Moved" is against the member's latest row for the
    Book from any source, and a row of theirs today, typed or synced, is the
    day's row. The row promotes an unstarted Book to reading, as a typed one
    does. **Zero percent writes nothing**: a book opened and closed has not
    moved.

    **Crossing into 100 percent marks the Book read**, whatever the log did.
    The owner's ruling, reversing the rule that progress never sets read: a
    device's last page is the book's end, where a typed page number checked
    against a provider's page count is not. **Only the crossing**, from
    `before` below the end or no position at all: a device resting on the last
    page pushes 100 on every suspend, and a member who set the status back
    must not be overruled by the next one. See `docs/decisions.md`.

    A percentage outside 0 to 1 is stored for the device and applies nothing.
    """
    if not 0 <= percentage <= 1:
        return
    # Rounded before the floor, because 0.29 * 100 is 28.999999999999996.
    whole = math.floor(round(percentage * 100, 6))
    reading = Reading.by(db, member_id)

    if whole > 0:
        latest = (
            db.query(ReadingProgress)
            .filter(ReadingProgress.user_id == member_id, ReadingProgress.book_id == book_id)
            .order_by(ReadingProgress.recorded_at.desc(), ReadingProgress.id.desc())
            .first()
        )
        today = datetime.now(UTC).date()
        if latest is None or (latest.recorded_at.date() != today and latest.percent != whole):
            db.add(ReadingProgress(user_id=member_id, book_id=book_id, percent=whole))
            if whole < _FINISHED:
                reading.begin(book_id)

    if whole >= _FINISHED and (before is None or before < 1):
        reading.finish(book_id)


# ── A pull ────────────────────────────────────────────────────────────────────


def answer(db: Session, member: User, document: str) -> dict[str, object]:
    """What a GET returns: the last push, field for field, or `{}`.

    **An unknown document is an empty object and a 200**, never a 404: the
    device reads the absence of `percentage` as "not read here yet" and a 404
    as a sync error. `device_id` is left out where the push sent none, as the
    reference leaves it out.
    """
    row = (
        db.query(KosyncDocument)
        .filter(KosyncDocument.user_id == member.id, KosyncDocument.document == document)
        .first()
    )
    if row is None:
        return {}
    body: dict[str, object] = {
        "document": row.document,
        "progress": row.progress,
        "percentage": row.percentage,
        "device": row.device,
        "timestamp": row.timestamp,
    }
    if row.device_id is not None:
        body["device_id"] = row.device_id
    return body


# ── The member's side ─────────────────────────────────────────────────────────


def unlinked(db: Session, member_id: int, limit: int) -> list[KosyncDocument]:
    """This member's documents no Book is linked to, newest push first."""
    return (
        db.query(KosyncDocument)
        .filter(KosyncDocument.user_id == member_id, KosyncDocument.book_id.is_(None))
        .order_by(KosyncDocument.timestamp.desc(), KosyncDocument.id.desc())
        .limit(limit)
        .all()
    )


def linked_to(db: Session, member_id: int, book_id: int) -> list[KosyncDocument]:
    """This member's documents linked to one Book the caller already resolved."""
    return (
        db.query(KosyncDocument)
        .filter(KosyncDocument.user_id == member_id, KosyncDocument.book_id == book_id)
        .order_by(KosyncDocument.timestamp.desc(), KosyncDocument.id.desc())
        .all()
    )


def document_of(db: Session, member_id: int, document: str) -> KosyncDocument | None:
    """One of this member's documents by name, or None. Nobody else's."""
    return (
        db.query(KosyncDocument)
        .filter(KosyncDocument.user_id == member_id, KosyncDocument.document == document)
        .first()
    )


def unlink(row: KosyncDocument) -> None:
    """Send this document back to the inbox. What it already wrote stays."""
    row.book_id = None


def link(db: Session, row: KosyncDocument, book_id: int) -> None:
    """Remember that this document is this Book, and apply where it is.

    The caller resolved the Book through the Shelf. Applying the position now
    rather than at the next push is what makes a document finished on the
    device before it was linked mark the Book read.
    """
    row.book_id = book_id
    # Applied as a first position: linking is the member's own act, so a
    # document already at its end marks the Book read once, here.
    apply(db, row.user_id, book_id, row.percentage, None)
