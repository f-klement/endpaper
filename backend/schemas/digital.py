"""What a browser may say about where one of a Member's book files is.

**Nothing in this module has been checked by anything.** Endpaper takes no
custody of a Member's book file: the client parses it and sends metadata, so no
bytes reach this server and every value below is a claim by whoever holds a
session. That makes a payload here untrusted input in exactly the way a
catalogue record is, and it is bounded twice for the same reason: here, and
again by `ck_digital_references_bounds` on the column, because `backup.restore`
inserts through Core and sees no model in this file at all.

`models.DigitalReference` carries the rest of the reasoning, including why the
row can be re-checked only by a client and never by this server.
"""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from enums import BookFormat
from models import DIGITAL_REFERENCE_MAX_SIZE, DIGITAL_REFERENCE_PATH_MAX, PARTIAL_MD5_HEX
from schemas.common import RowIdField, UtcDateTime, UtcDateTimeIn

#: The most file references one book may carry.
#:
#: **Not measured, and it says so.** There is no population to measure: this
#: counts the places a household keeps the same file, which is its machines and
#: its shares, and nothing in this tree or any competitor's records that number.
#: `MAX_CLASSIFICATIONS_PER_BOOK` sits beside two measured tables; this one
#: cannot and inventing a corpus for it would be worse than saying so.
#:
#: So it is chosen the way `categories.MAX_CATEGORIES_PER_BOOK` chose 32, by
#: which way the failure
#: modes are asymmetric. Too loose costs rows on a page nobody scrolls; too
#: tight refuses a Member a real location and there is no way to tell them which
#: one to drop. 16 is far past any household's count of machines and shares, and
#: still one screen.
#:
#: **It counts locations and not machines, and those diverge over time.** A file
#: moved within its root is a new location, and the row for the old one survives
#: until somebody deletes it: nothing here can know the file went rather than
#: vanished, which is the same refusal `missing_since` makes. So a library that
#: reorganises its shelves reaches this ceiling through path history rather than
#: through hardware, and the 409 it then gets is the honest answer: a Member
#: decides which references are stale, because this server cannot.
#:
#: **The bound is per book and not per request**, which is the distinction
#: `MAX_CLASSIFICATIONS_PER_BOOK` records paying for: a route that bounds one
#: payload while the writer is additive across requests bounds nothing.
#: `file_references.report` counts the rows already on the book.
#: `backup.restore` is uncapped here as it is everywhere, for the reason that
#: file gives: it reinstates a database rather than adding to one.
MAX_DIGITAL_REFERENCES_PER_BOOK = 16

#: The most files one lookup of their holders may name.
#:
#: The scan queue's own unit: a folder pick is sent in chunks of this many, so
#: a pick of any size is answered in a few requests and no one request makes
#: the database match an unbounded list. Chosen, not measured: it is a large
#: folder pick in one request.
MAX_FILES_PER_LOOKUP = 500

#: KOReader's partial MD5 as this server takes it: 32 lower case hex digits and
#: nothing else. `ck_digital_references_partial_md5` is the same rule on the
#: column. Lower case because that is how KOReader writes it and how a device
#: names a document on the wire, so an upper case spelling would be a second
#: value for one digest and match nothing.
PartialMd5 = Annotated[str, Field(pattern=f"^[0-9a-f]{{{PARTIAL_MD5_HEX}}}$")]


def _a_path_without_a_null(value: str) -> str:
    """The value back, refusing one carrying a NUL.

    **Only NUL, and the narrowness is the decision.** A filename on the systems
    this app's Members use may legally contain a newline, a tab or an escape
    character, so refusing control characters as a class would refuse real
    files and tell their owner nothing they could act on. NUL is the one that is
    not a filename character anywhere: it terminates a C string, so no
    filesystem call can carry it, and SQLite's own text functions stop at it,
    which makes a stored value with one a value the CHECK measured differently
    from the value that was sent.

    **Path shape is deliberately not policed here.** A leading slash, a `..`, a
    Windows drive letter and a UNC root are all things a Member's own path
    legitimately looks like, and this server never resolves any of it: the
    string is stored and echoed, never opened. The client that goes looking
    holds a file handle rather than this text, and it is the place that rule
    belongs.
    """
    if "\x00" in value:
        raise ValueError("A path may not contain a NUL")
    return value


class DigitalReferenceIn(BaseModel):
    """A browser reporting that it found this book's file at this location.

    One shape for cataloguing a file and for re-checking it later, because they
    are the same sentence: a client looked and here is what it saw. What the
    server does with it differs (a new location is stored, a known one is
    refreshed), and that belongs at the route rather than in two payloads whose
    fields would be identical.
    """

    #: What the Member calls the place the file lives under. Never resolved.
    root_label: str = Field(min_length=1, max_length=DIGITAL_REFERENCE_PATH_MAX)

    #: The file beneath it. **The picked directory's own name belongs to
    #: `root_label` and not here**: repeating it would be the same fact twice,
    #: and two clients disagreeing about it make two rows for one file under
    #: `uq_digital_references_location`. Stated rather than enforced, because
    #: nothing on this side can tell the two spellings apart.
    relative_path: str = Field(min_length=1, max_length=DIGITAL_REFERENCE_PATH_MAX)

    #: Whether a browser corroborated the structure beneath the root, or the
    #: Member supplied all of it. Defaults to the weaker claim: a client that
    #: does not say has not corroborated anything.
    root_confirmed: bool = False

    #: `File.size`, if the client read it.
    size_bytes: int | None = Field(default=None, ge=0, le=DIGITAL_REFERENCE_MAX_SIZE)

    #: `File.lastModified`, if the client read it.
    file_modified_at: UtcDateTimeIn | None = None

    #: KOReader's partial MD5 of the file, if the client computed it.
    #: `models.DigitalReference.partial_md5` says what it samples.
    partial_md5: PartialMd5 | None = None

    @field_validator("root_label", "relative_path")
    @classmethod
    def _no_nulls(cls, value: str) -> str:
        return _a_path_without_a_null(value)

    @model_validator(mode="after")
    def _the_pair_fits_a_path(self) -> DigitalReferenceIn:
        """The two halves together, which is the bound that is actually derived.

        `max_length` on each field alone permits a root and a path that together
        name something no filesystem could open, because
        `DIGITAL_REFERENCE_PATH_MAX` is the budget for the **pair**: it is
        PATH_MAX less the separator between them. The per field bound is the
        same number so that the field never refuses what this rule admits, and
        the two are different rules for that reason: neither implies the other,
        and this one is the one that binds.

        The same inequality is `ck_digital_references_bounds` on the column,
        from the same constant. Two layers rather than two numbers.
        """
        if len(self.root_label) + len(self.relative_path) > DIGITAL_REFERENCE_PATH_MAX:
            raise ValueError(
                "A root and the path beneath it may be at most "
                f"{DIGITAL_REFERENCE_PATH_MAX} characters together"
            )
        return self


class DigitalReferenceOut(BaseModel):
    """One stored reference, read back.

    **Some of these are things a browser said and the rest are this server's**,
    and the grouping below is in that order rather than in column order, so a
    reader of the generated client meets the distinction rather than having to
    know it. `id` is the server's too, and is first because it is what the other
    three routes are addressed by.

    Deliberately no count of either group: the members of a group are the group,
    and a stated "N of these" is what goes stale when one is added.
    """

    model_config = {"from_attributes": True}

    id: int

    #: Which Book the reference is on. Here rather than on the cross shelf
    #: subclass alone, because `NoteOut` and `QuoteOut` both carry it and both
    #: are per book addressed sub-resources with a cross book listing: the
    #: listing is where it earns its place, and one shape for one row is worth
    #: more than saving a field on four responses that already know their Book.
    #: Without it no row of that listing can be acted on, since flagging,
    #: re-confirming and forgetting are all `/books/{book_id}/...`.
    book_id: int

    # What a client said. Unverified, every one of them.
    root_label: str
    relative_path: str
    root_confirmed: bool
    size_bytes: int | None
    file_modified_at: UtcDateTime | None
    partial_md5: str | None = None

    # This server's own clock.
    created_at: UtcDateTime

    #: When this server last received a report that the file was there.
    #: **Not when anybody looked**: see `models.DigitalReference.confirmed_at`.
    confirmed_at: UtcDateTime

    #: When this server first received a report that it did not resolve, or null
    #: while nothing has said so.
    missing_since: UtcDateTime | None


class MissingDigitalReferenceOut(DigitalReferenceOut):
    """One flagged reference, with enough of its book to render a row.

    The shape `QuoteWithBookOut` already has, for the same reason: a listing
    spanning the shelf renders a title and a cover per row, and fetching the
    Book per row is the N+1 `serialisation.books_to_out` exists to avoid. Three
    scalars rather than a nested `BookOut`, which carries tags, the adder, the
    active loan and the caller's own reading state, none of which a row shows.

    **`missing_since` is narrowed to non-null**, which is the only field this
    type narrows rather than adds. Every row is here *because* the column is
    set, so the base's `UtcDateTime | None` would make every client branch on a
    null the route's WHERE clause has already excluded. The guarantee lives in
    that clause; if it ever loosens, this narrowing turns a row into a 500
    rather than into a client rendering "missing since never", and loud is the
    failure to prefer.
    """

    #: When this server was first told the file did not resolve. Never null
    #: here, which is what this listing selects on.
    missing_since: UtcDateTime

    book_title: str
    book_author: str | None = None
    book_cover_url: str | None = None


class AskedFileIn(BaseModel):
    """One file a client holds, named by where it is, by its digest, or both.

    **Either key alone is a question worth asking.** A location is what a
    folder pick knows for certain; a digest is what survives the file being
    moved or renamed, and it is the only thing a KOReader device names a
    document by. A file named by neither asks nothing, so it is refused.

    The location is bounded as `DigitalReferenceIn` bounds it: each half, the
    pair, and no NUL in either. Its two halves arrive together or not at all:
    half a location names no file.
    """

    root_label: str | None = Field(default=None, min_length=1, max_length=DIGITAL_REFERENCE_PATH_MAX)
    relative_path: str | None = Field(default=None, min_length=1, max_length=DIGITAL_REFERENCE_PATH_MAX)
    partial_md5: PartialMd5 | None = None

    @field_validator("root_label", "relative_path")
    @classmethod
    def _no_nulls(cls, value: str | None) -> str | None:
        return None if value is None else _a_path_without_a_null(value)

    @model_validator(mode="after")
    def _names_a_file(self) -> AskedFileIn:
        if (self.root_label is None) != (self.relative_path is None):
            raise ValueError("A location needs both its root and the path beneath it")
        if self.root_label is None and self.partial_md5 is None:
            raise ValueError("A file is named by its location, its digest, or both")
        if (
            self.root_label is not None
            and self.relative_path is not None
            and len(self.root_label) + len(self.relative_path) > DIGITAL_REFERENCE_PATH_MAX
        ):
            raise ValueError(
                "A root and the path beneath it may be at most "
                f"{DIGITAL_REFERENCE_PATH_MAX} characters together"
            )
        return self


class HoldersIn(BaseModel):
    """The files whose holders a client wants to know, in the order it asks."""

    files: list[AskedFileIn] = Field(min_length=1, max_length=MAX_FILES_PER_LOOKUP)


class HolderOut(BaseModel):
    """One visible Book holding a reference to the file, and how it matched."""

    book_id: int
    #: The reference on that Book that matched, so a client can refresh it.
    reference_id: int
    #: The Book's own format, so a client can choose between copies without a
    #: request per Book.
    format: BookFormat | None
    #: The reference is at the location the client named.
    same_location: bool
    #: The reference carries the digest the client named.
    same_partial_md5: bool


class HoldersOut(BaseModel):
    """The holders of one file, in Book id order, and empty where there are none.

    **Empty is also the answer for a Book the caller cannot see**, by
    construction rather than by a branch: the lookup starts from the caller's
    shelf, so a hidden Book never reaches the rows this is built from.
    """

    holders: list[HolderOut]


class SightingIn(BaseModel):
    """One stored reference a folder pick found, with what the browser saw.

    The fingerprint fields are `DigitalReferenceIn`'s and replace the stored
    ones whole, for that route's reason: a row says what one client saw in one
    look.
    """

    reference_id: RowIdField
    size_bytes: int | None = Field(default=None, ge=0, le=DIGITAL_REFERENCE_MAX_SIZE)
    file_modified_at: UtcDateTimeIn | None = None
    partial_md5: PartialMd5 | None = None


class SweepIn(BaseModel):
    """What a re-picked folder said about the references stored under it.

    `seen` are references whose file the pick held and `missing` those it did
    not. A reference under another root is not this folder's to judge, so the
    route skips one that does not carry `root_label`.

    **Bounded as the holder lookup is**, at `MAX_FILES_PER_LOOKUP` references
    in one request together: a client sweeping a larger root sends it in
    chunks, and no request makes the database match an unbounded list.
    """

    root_label: str = Field(min_length=1, max_length=DIGITAL_REFERENCE_PATH_MAX)
    # Each list alone at the joint ceiling as well, so the bound is visible on
    # the field; `_bounded` below is what holds the two together.
    seen: list[SightingIn] = Field(default_factory=list, max_length=MAX_FILES_PER_LOOKUP)
    missing: list[RowIdField] = Field(default_factory=list, max_length=MAX_FILES_PER_LOOKUP)

    @field_validator("root_label")
    @classmethod
    def _no_nulls(cls, value: str) -> str:
        return _a_path_without_a_null(value)

    @model_validator(mode="after")
    def _bounded(self) -> SweepIn:
        asked = len(self.seen) + len(self.missing)
        if asked == 0:
            raise ValueError("A sweep names at least one reference")
        if asked > MAX_FILES_PER_LOOKUP:
            raise ValueError(f"A sweep names at most {MAX_FILES_PER_LOOKUP} references at once")
        return self


class SweepOut(BaseModel):
    """The references the sweep wrote, by id.

    A reference the caller cannot see, or one under another root, is in
    neither list: it was not written, and saying so per id would confirm that
    the id exists.
    """

    seen: list[int]
    missing: list[int]
