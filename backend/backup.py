"""Taking the whole catalogue out, and putting it back.

The CSV export has existed since the beginning and is not a backup. It carries
one row per book and drops the notes, the quotes, the classifications, the
loans, every member's reading status, the accounts themselves and every cover
file, which is to say
it drops most of what somebody spent an evening typing in.

This produces a **zip** holding two things:

    endpaper.json    every row of every table, in dependency order
    covers/          the uploaded cover images, byte for byte

JSON rather than a copy of the SQLite file, for one reason that matters: a file
copy taken while the application is running is only consistent if it goes
through SQLite's backup API, and a file restored underneath a running process
is not consistent at all. A dump read through the ORM's own session is
consistent by construction, and it can be inspected, diffed and repaired with a
text editor when something has gone wrong, which is exactly the moment a backup
is opened.

**Restoring replaces everything.** That is what a restore is, and pretending
otherwise (merging, skipping conflicts) produces a database in a state neither
the backup nor the original describes. It is admin-only and asks.
"""

import json
import logging
import zipfile
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Table, delete, update
from sqlalchemy.orm import Session

import covers
import credentials
import filing
import settings_store
from config import ALLOWED_IMAGE_EXTENSIONS, COVERS_DIR
from database import Base
from enums import VerificationProvenance
from models import (
    OPDS_CREDENTIAL_PREFIX,
    AuthorAlias,
    AuthorIdentifier,
    Book,
    CatalogueCredential,
    CatalogueTarget,
    Classification,
    Collection,
    CustomField,
    CustomFieldValue,
    Loan,
    Note,
    OpdsServer,
    PasswordResetRequest,
    Quote,
    ReadingProgress,
    Setting,
    Tag,
    User,
    UserBook,
    book_tags,
    fold_collection_name,
)
from uploads import SNIFF_BYTES, sniff_image_extension, write_image

logger = logging.getLogger("endpaper.backup")

#: Bumped when the archive's **envelope** changes: the manifest layout, the
#: table list, the way covers are stored.
#:
#: Deliberately not bumped when a table gains a column. An archive taken before
#: a migration is still restorable, and refusing it would make every schema
#: change throw away the library's backups. A column the archive does not
#: carry takes its database default, which is right for every one of them
#: except `tags.is_predefined`; see `_repair_seeded_tags`.
#: Still 1. The envelope has not changed: the manifest layout is the same, the
#: table list is the same, and covers are the same files under `covers/`.
FORMAT_VERSION = 1

MANIFEST_NAME = "endpaper.json"
COVERS_PREFIX = "covers/"

#: Insert order. Parents before children, because the foreign keys are real and
#: SQLite checks them. Reversed for the delete, for the same reason.
#:
#: The `Table` is taken from the metadata rather than off the model: a
#: declarative class types `__table__` as the wider `FromClause`, which has
#: neither `insert` nor a shape `delete()` accepts.
_TABLES: tuple[tuple[str, Any, Table], ...] = tuple(
    (name, model, Base.metadata.tables[name])
    for name, model in (
        ("users", User),
        ("tags", Tag),
        # The library's own field definitions. No foreign key of its own, so it
        # could sit anywhere before the values that reference it; here beside
        # `tags`, which is the other library wide vocabulary. Deliberately
        # absent from `_REQUIRED_TABLES`: an archive taken before custom fields
        # existed restores with none, which is the state it was written in.
        ("custom_fields", CustomField),
        # Before books, which carry a foreign key into it. Absent from
        # `_REQUIRED_TABLES` on purpose: an archive taken before collections
        # existed restores with none, which is exactly the state it was
        # written in.
        ("collections", Collection),
        ("books", Book),
        # Straight after the books they hang off, and deliberately absent from
        # `_REQUIRED_TABLES`: an archive taken before classifications existed
        # restores with none, which is the state it was written in.
        ("classifications", Classification),
        # After both parents, `books` above and `custom_fields` further up. The
        # values are the half of the feature a member typed by hand, so an
        # archive that carried the definitions and not these would restore a
        # library with every field defined and every one of them empty, which
        # is the shape of failure `author_aliases` had. Absent from
        # `_REQUIRED_TABLES` for the same reason as the definitions.
        ("custom_field_values", CustomFieldValue),
        ("user_books", UserBook),
        # After user_books, which is the other per-member table, and before
        # loans purely to keep the reading rows together. Both parents
        # (users, books) are already inserted by this point, which is the
        # only ordering this tuple actually constrains.
        ("reading_progress", ReadingProgress),
        ("loans", Loan),
        ("notes", Note),
        # After notes, which it is shaped after and has no relationship with.
        # Deliberately absent from `_REQUIRED_TABLES`: an archive taken before
        # quotes existed restores with none, which is the state it was written
        # in.
        ("quotes", Quote),
        # The author merge decisions. Its only foreign key is `users`, which is
        # first in this tuple, so it could sit anywhere after that; it is here
        # beside the other tables that hold what members decided rather than
        # what the catalogue says.
        #
        # **It was missing until 2026-08-26**, and the symptom was silent: a
        # restore produced a library where every merged author had split back
        # into its spellings, with the books themselves perfectly intact,
        # because the merges were never written to `books` in the first place.
        # Nothing errored, and `docs/data-model.md` called this "the one stored
        # table in the feature" the whole time. `test_holds_every_table` now
        # asserts that the archive's **manifest** carries every table in the
        # metadata, so the next one cannot be forgotten the same way. The
        # manifest rather than this tuple, because `book_tags` is in the
        # manifest and deliberately not here: it has no model of its own and is
        # read straight from the table.
        #
        # Absent from `_REQUIRED_TABLES` for the reason `quotes` and
        # `classifications` are: an archive written before this restores with
        # no aliases, which is the state it was written in.
        ("author_aliases", AuthorAlias),
        # Beside the aliases, which it is keyed the same way as and shares its
        # only foreign key with. A different claim about the same spelling: an
        # alias says who two names mean and this says which record in an
        # external file one of them is.
        #
        # **Here on the day the table was created**, because the identical
        # omission for `author_aliases` was silent for months: a restore
        # produced a library whose books were perfectly intact and whose author
        # decisions had all vanished. `test_holds_every_table` reads the
        # manifest against the metadata, so a table left out of this tuple now
        # fails rather than waiting to be noticed after a restore.
        #
        # Absent from `_REQUIRED_TABLES` for the reason `author_aliases` is: an
        # archive written before this restores with none, which is the state it
        # was written in.
        ("author_identifiers", AuthorIdentifier),
        # The catalogue roster as rows. No foreign key of its own, so its
        # position here is free; beside `settings` because it is the same kind
        # of thing, a library wide configuration rather than anybody's data.
        #
        # **Here on the day the table was created**, for the reason the comment
        # above gives, and with one difference worth stating: nothing reads
        # these rows at runtime, so losing them costs no lookup. What it costs
        # is #130, which is the ticket that puts them on a screen, and
        # `main.seed_catalogue_targets` refills them on the next start anyway.
        # The reason to be in this tuple regardless is that an archive is
        # supposed to hold the library, and a row a household has edited is
        # theirs the moment #130 ships.
        #
        # Absent from `_REQUIRED_TABLES` for the reason `author_identifiers` is:
        # an archive written before this restores with none, which is the state
        # it was written in.
        ("catalogue_targets", CatalogueTarget),
        # The sealed catalogue logins, straight after the rows they hang off.
        # No foreign key between them, so the position is free; here because
        # reading one without the other is meaningless.
        #
        # **This is the table that makes the archive safe to hand around, and
        # the one that makes a restore onto a new machine incomplete.** The
        # column holds ciphertext and the key is never in the database, so
        # `endpaper.json` carries a credential nobody can use without a key the
        # archive does not contain. That is the whole design and it is strictly
        # better than the plaintext this feature started as.
        #
        # **The same property is the trap on a machine nobody administers.** A
        # restore onto a new laptop, or onto the same one after a reinstall,
        # brings these rows back unreadable unless the person still has the
        # recovery phrase: the key lives in that machine's keychain or in a file
        # under `DATA_DIR`, and neither travels in the zip. "Keep your key safe"
        # is not a plan for somebody who double clicked an installer, which is
        # why the phrase exists at all and why the settings screen says this
        # beside the field rather than only here. `RestoreResult` counts these
        # rows for the reason it counts `author_aliases`: silently restoring
        # none leaves a library whose sources look configured and answer with an
        # authentication error.
        #
        # Absent from `_REQUIRED_TABLES`, like every table added after
        # `FORMAT_VERSION` 1: an archive written before this restores with none,
        # which is the state it was written in.
        ("catalogue_credentials", CatalogueCredential),
        # The household's own OPDS servers, after the credential table their
        # `credential_key` points into. No foreign key in either direction, so
        # the position is free; here because the two are read together.
        #
        # **The address is the library's and the login is not in this row**, so
        # this table restores usefully where `catalogue_credentials` restores
        # unreadable: somebody who moves to a new machine gets their servers
        # back and types the passwords again, which is the same bargain the
        # comment above describes and a better one than losing the addresses
        # too.
        #
        # **An orphaned envelope is the failure this ordering does not
        # prevent**, and it does not need to: an archive holding a credential
        # whose server row is gone leaves a row `credentials.unreadable_sources`
        # reports and `DELETE /api/settings/catalogue-sources/{source}/credential`
        # removes, which is exactly why that route deliberately does not check
        # the roster.
        #
        # Absent from `_REQUIRED_TABLES`, like every table added after
        # `FORMAT_VERSION` 1: an archive written before this restores with none,
        # which is the state it was written in.
        ("opds_servers", OpdsServer),
        # The password reset requests, whose only foreign key is `users`, first
        # in this tuple. Here rather than beside the other per member tables
        # because it is not about the catalogue at all: it is the record of who
        # approved a member's way back into their account, which is the half of
        # that flow the member reads.
        #
        # **Carried rather than dropped**, and the pending rows come with it. An
        # archive already holds every password hash in the library, so a hash of
        # a code that stops working within the hour discloses nothing new, and a
        # restore that silently emptied this table would take away the record a
        # member is entitled to read back.
        #
        # **This module is the exception to "only a member starts a reset", and
        # it is named at every site that states the rule.** `restore` writes
        # these rows through `table.insert()` from the archive, so an archive
        # can carry an approved request. That widens nothing: a restore replaces
        # every password hash in the library in the same transaction, so
        # whoever can hand one to this route already holds every account.
        #
        # Absent from `_REQUIRED_TABLES`, like every table added after
        # `FORMAT_VERSION` 1.
        ("password_reset_requests", PasswordResetRequest),
        ("settings", Setting),
    )
)

#: Tables a manifest must actually list, as opposed to tables this version
#: knows how to restore.
#:
#: The two are not the same set, and conflating them breaks every backup the
#: library already holds. `FORMAT_VERSION` promises that an archive taken
#: before a schema change is still restorable, and `read_manifest` used to
#: enforce presence of every entry in `_TABLES`, so **adding a table would have
#: refused every older archive** with "the backup is missing: reading_progress".
#: An absent table restores as empty instead, which is exactly right: there was
#: no such data when the archive was written.
#:
#: A table belongs here only if it existed at `FORMAT_VERSION` 1. Anything
#: added later must not, or the promise breaks again.
_REQUIRED_TABLES: frozenset[str] = frozenset(
    {"users", "tags", "books", "user_books", "loans", "notes", "settings"}
)

#: A cover named anything else is not one of ours. Guards against a crafted
#: archive writing outside the covers directory, which is what makes a zip a
#: security question rather than a container format.
#:
#: **Derived from the app's own allowlist rather than written out beside it.**
#: It was a second literal spelling the same four formats, and the drift is
#: silent in the expensive direction: a format added to
#: `ALLOWED_IMAGE_EXTENSIONS`, to `uploads.sniff_image_extension` and to
#: `routers/covers._MEDIA_TYPES` but forgotten here makes `create` stop
#: archiving those covers and `restore` stop writing them, with nothing failing
#: and nothing logged. Sorted so the order is stable to read in a message.
_COVER_SUFFIXES = tuple(sorted(f".{extension}" for extension in ALLOWED_IMAGE_EXTENSIONS))

#: Total **uncompressed** bytes an archive may declare.
#:
#: The upload cap bounds the compressed size only, and zip is a compressing
#: format: a 1.38 MB archive holding a padded manifest and one enormous cover
#: entry drove peak memory to 1.8 GB, against a pod limited to 512Mi. That is
#: an OOMKill from a file that passes every other check.
#:
#: Generous enough for a library's whole library with its covers, small
#: enough that the pod survives being handed a bomb.
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024

#: How much bigger than the upload an archive may claim to be. A real backup of
#: JSON and JPEGs compresses a few times over; a hundredfold is not a backup.
MAX_COMPRESSION_RATIO = 100


def _serialise(value: Any) -> Any:
    """Dates as ISO strings; everything else is already JSON-shaped."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _temporal_columns(table: Table) -> dict[str, type[date] | type[datetime]]:
    """Which columns need parsing back from a string, and into what.

    The dump writes dates as ISO strings because JSON has no date type. Feeding
    those back to SQLAlchemy's `insert()` raises: SQLite's DateTime accepts a
    `datetime` and nothing else, so a round trip that skips this step fails on
    the very first table.
    """
    parsers: dict[str, type[date] | type[datetime]] = {}
    for column in table.columns:
        if isinstance(column.type, DateTime):
            parsers[column.name] = datetime
        elif isinstance(column.type, Date):
            parsers[column.name] = date
    return parsers


def _parse_row(
    row: dict[str, Any],
    parsers: dict[str, type[date] | type[datetime]],
    table: Table,
) -> dict[str, Any]:
    parsed = dict(row)
    for name, kind in parsers.items():
        value = parsed.get(name)
        if isinstance(value, str) and value:
            try:
                parsed[name] = kind.fromisoformat(value)
            except ValueError as error:
                raise RestoreError(
                    f"{name!r} in the backup is not a date: {value!r}"
                ) from error

    # A restore inserts through Core, not the ORM, so `@validates` never fires
    # and `Book._store_covers_over_https` does not run. `covers.storable` is
    # that validator's whole rule, called directly: an earlier version of this
    # line repeated only the scheme upgrade, so an archive could still write
    # `javascript:` or `//host` straight past every other guard. An archive is
    # admin-supplied, and an admin is not a reason to trust a file: it may have
    # come from another deployment or been edited by hand.
    #
    # Dropped rather than refused, matching the ORM backstop: one odd cover is
    # not a reason to fail a whole restore. Only `books` has this column, so
    # testing for the name keeps this row parser generic.
    cover = parsed.get("cover_url")
    if isinstance(cover, str):
        stored = covers.storable(cover)
        if cover and stored is None:
            logger.warning(
                "Dropped a cover URL in the archive that is not renderable: %r",
                cover[:120],
            )
        parsed["cover_url"] = stored

    # The second derived column with the same problem, and it is not optional
    # the way the cover is. `Collection.name_folded` is written by a
    # `@validates` hook, which a Core insert never fires, so an archive decides
    # this value rather than the model. Two consequences, both real:
    #
    # * An archive taken **before** the revision that added the column carries
    #   no value for it. The column is NOT NULL, so the insert raises
    #   `IntegrityError`, which is not `RestoreError`, so the route answers 500
    #   rather than the 400 its docstring promises. Recomputing here is what
    #   keeps an older backup restorable, which is the rule `FORMAT_VERSION`
    #   states: a column the archive does not carry must not throw a library's
    #   backups away.
    # * A hand-edited archive can carry a fold that disagrees with its name.
    #   The unique index catches two rows folding the same; it can never catch
    #   one row folding wrongly. Derived rather than trusted, for the same
    #   reason an admin uploading the file is not a reason to trust the file.
    #
    # Keyed on the column being in this table, because `tags` and `users` have
    # a name too and neither has a fold. `_TABLES` is the only caller and holds
    # the `Table`, so the check costs nothing.
    if "name_folded" in table.columns:
        # `written_name` rather than `name`, which the date loop above binds to
        # a column name. mypy catches the collision; a reader would not.
        written_name = parsed.get("name")
        # Refused rather than skipped. A non-string here used to fall past the
        # recompute and leave the archive's own fold standing, which is the
        # trust this block exists to withhold. SQLite's TEXT affinity then
        # converts quietly: `{"name": 1}` and `{"name": true}` both insert as
        # the string `'1'`, so two collections a reader cannot tell apart pass
        # `uq_collections_name_folded` while their folds describe no name at
        # all. Measured against the real column types before this line existed.
        if not isinstance(written_name, str):
            raise RestoreError(
                f"A row in {table.name!r} has a name that is not text: "
                # Truncated like the `cover_url` warning above, and for the
                # same reason: a manifest may declare 1 GiB, so one value can
                # carry ~500 MiB, and `repr` amplifies it about 4x before
                # `json.dumps` takes another 5x into the response body.
                #
                # The slice is on the **repr**, not on the value. Everything
                # reaching this line is by definition not a `str`, so
                # `written_name[:120]` would raise `TypeError` on the int and
                # bool cases this exists to report, and a JSON number can be
                # arbitrarily long too.
                f"{repr(written_name)[:120]}"
            )
        parsed["name_folded"] = fold_collection_name(written_name)

    # The third derived column, and the one that arrives with a unique index on
    # it. `tags.key` says which seeded tag a row **is**, and it is recomputed
    # from the name by `_repair_seeded_tags` a few lines after the inserts, so
    # the archive's own value is never read for anything. Left standing it is
    # still enforced: an archive holding two rows with the same key raises
    # `IntegrityError` on the insert, which is not `RestoreError`, so the route
    # answers 500 rather than the 400 its docstring promises, over a column
    # nobody can see and whose value was about to be overwritten. Measured on
    # the real route by putting `"fiction"` on an invented row.
    #
    # Blanked rather than validated, which is the difference from
    # `_refuse_a_colliding_pair` above and turns on whether the value is data.
    # A collection's *name* is data: it is what the library typed, it cannot be
    # derived from anything else, and two that collide is a question only a
    # person can answer, so that pair is refused with both names in the
    # message. A key is not data. It is derived, this file derives it, and
    # refusing a restore over a claim we were going to discard would cost a
    # library its backup to protect a column it does not know exists.
    #
    # `table.name == "tags"`, **not** `"key" in table.columns`: `settings.key`
    # is that table's row identity, `VARCHAR(64) NOT NULL PRIMARY KEY`, and
    # blanking it would raise "NOT NULL constraint failed: settings.key" and
    # take down every restore. Measured against the real column.
    if table.name == "tags":
        parsed["key"] = None

    # The fourth derived column, and the one whose failure is silent rather
    # than loud. `classifications.sort_key` is written by
    # `Classification._file_the_number`, which is a `@validates` hook and so
    # never fires here. Left to the archive it would restore whatever an
    # archive happened to hold, and a wrong key is not visible anywhere: the
    # row is there, the number is right, and the book stands in the wrong place
    # on one shelf order.
    #
    # Derived rather than trusted for the reason `name_folded` is: an admin
    # uploading a file is not a reason to trust the file, and this value is
    # computable from the row. An archive taken before the column existed
    # carries nothing for it and the column is NOT NULL, so recomputing is also
    # what keeps that archive restorable at all, which is `FORMAT_VERSION`'s
    # promise.
    #
    # `table.name`, not `"sort_key" in table.columns`, so that a second table
    # growing a column of that name does not silently acquire a filing rule.
    if table.name == "classifications":
        number = parsed.get("number")
        # Refused rather than skipped, the shape `name_folded` above uses.
        #
        # **What it buys is the promised 400, and not a correct key**, which is
        # the opposite of what this comment first claimed. Measured against the
        # real columns over `100`, `1.5`, `true`, `null`, an array and an
        # object, on all four schemes:
        #
        # * `lcc` and `ddc` raise on every one of them, so without this the
        #   route answers 500 where this module's docstring promises 400;
        # * a generic rule returns the value unchanged, and `null`, an array
        #   and an object then fail at the insert, which is a 500 again;
        # * a generic rule with a number or a boolean is the one case that
        #   would have restored **correctly**. SQLite's TEXT affinity converts
        #   the bound value into `sort_key` exactly as it converts it into
        #   `number`, so both store `'100'` and the stored key is the key that
        #   value deserves.
        #
        # So no scheme can produce a silently wrong key, and that last case is
        # refused for consistency with `name_folded` rather than because
        # anything would be wrong. The cost is real and small: an archive
        # carrying `{"scheme": "gnd", "number": 100}` restored before this
        # column existed and is a 400 now. Only a hand-edited archive reaches
        # it, since `_row_to_dict` over a `String` column cannot write a
        # non-string.
        #
        # The slice is on the repr, because everything reaching this line is by
        # definition not a `str`.
        if not isinstance(number, str):
            raise RestoreError(
                f"A row in {table.name!r} has a number that is not text: "
                f"{repr(number)[:120]}"
            )
        parsed["sort_key"] = filing.sort_key_for(parsed.get("scheme"), number)

    # The fifth, and the one whose failure is a 500 rather than a wrong value.
    # `ck_catalogue_credentials_envelope` refuses anything that is not an
    # envelope, which is what stands between a hand-edited archive and a
    # plaintext password being sent to a catalogue. But a CHECK fires as
    # `IntegrityError`, which is not `RestoreError`, so the route answered 500
    # where this module's docstring promises 400. Exactly the shape the `tags`
    # arm above records for a colliding key.
    #
    # **The rule is asked of the module that owns the format, not restated.**
    # `credentials.generation_of` answers empty for anything that is not a
    # version this build knows, so the constraint and this check cannot drift
    # into two definitions of "an envelope". The constraint stays as the last
    # line, for a write that never comes through here.
    #
    # No value in the message: the column holds a secret, and an archive whose
    # row is not an envelope holds whatever a person put there.
    if table.name == "catalogue_credentials":
        if not credentials.generation_of(str(parsed.get("envelope") or "")):
            raise RestoreError(
                f"A row in {table.name!r} does not carry an encrypted credential."
            )
        # **The key travels too, and that is newer than the column.** The
        # settings screen is sent the source of any login it cannot open so
        # somebody can remove it, and a client puts that value in a URL path.
        # A hand-edited archive naming a source of `../../books/5?` steered an
        # admin's own authenticated DELETE at another route. Refused here for
        # the 400, and by `ck_catalogue_credentials_source` for the write that
        # does not come through here.
        #
        # The value is in the message because it is not a secret and is the
        # only thing that identifies the bad row, unlike the envelope above.
        if not credentials.is_safe_source(str(parsed.get("source") or "")):
            raise RestoreError(
                f"A row in {table.name!r} names a source that is not a catalogue: "
                f"{str(parsed.get('source'))[:60]!r}"
            )
    return parsed


def _row_to_dict(row: Any, table: Table) -> dict[str, Any]:
    return {
        column.name: _serialise(getattr(row, column.name)) for column in table.columns
    }


def build_archive(db: Session) -> bytes:
    """The whole database and every cover, as a zip.

    Not filtered by `visible_to`. A backup that silently omitted the private
    books of everyone but the admin taking it would restore to a library
    missing rows, which is the one thing a backup must never do. It is
    admin-only for exactly this reason.
    """
    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now().isoformat(),
        "tables": {},
    }

    for name, model, table in _TABLES:
        rows = db.query(model).all()
        manifest["tables"][name] = [_row_to_dict(row, table) for row in rows]

    # The tag association carries no model of its own, so it is read straight
    # from the table. Forgetting it loses every book's tags while looking like
    # a complete backup.
    manifest["tables"]["book_tags"] = [
        dict(row._mapping) for row in db.execute(book_tags.select())
    ]

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=1))
        for cover in sorted(COVERS_DIR.glob("*")):
            if cover.is_file() and cover.suffix.lower() in _COVER_SUFFIXES:
                archive.write(cover, f"{COVERS_PREFIX}{cover.name}")

    return buffer.getvalue()


class RestoreError(Exception):
    """The archive cannot be restored, and nothing has been changed yet."""


def read_manifest(data: bytes) -> dict[str, Any]:
    """Validate the archive and return its manifest.

    Every check happens **before** the database is touched. A restore that
    fails halfway leaves a library that is neither the backup nor what was
    there before, which is worse than either.
    """
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as error:
        raise RestoreError("That file is not an Endpaper backup.") from error

    _reject_a_bomb(archive, len(data))

    try:
        manifest: dict[str, Any] = json.loads(archive.read(MANIFEST_NAME))
    except KeyError as error:
        raise RestoreError(
            f"The archive has no {MANIFEST_NAME}, so it is not an Endpaper backup."
        ) from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RestoreError("The backup's contents could not be read.") from error

    version = manifest.get("format_version")
    if version != FORMAT_VERSION:
        raise RestoreError(
            f"This backup is format {version}, and this version reads "
            f"{FORMAT_VERSION}. Restore it with the version that wrote it."
        )

    tables = manifest.get("tables")
    if not isinstance(tables, dict):
        raise RestoreError("The backup lists no tables.")

    missing = [
        name
        for name, _model, _table in _TABLES
        if name in _REQUIRED_TABLES and name not in tables
    ]
    if missing:
        raise RestoreError(f"The backup is missing: {', '.join(missing)}.")

    # A user table with nobody in it restores to a library nobody can sign in
    # to, which locks the library out of their own catalogue.
    if not tables.get("users"):
        raise RestoreError("The backup contains no accounts, so nothing could sign in.")

    return manifest


def _reject_a_bomb(archive: zipfile.ZipFile, compressed: int) -> None:
    """Refuse an archive that expands to more than the pod can hold.

    Checked from the central directory, before a single entry is read, because
    reading is the thing that costs the memory. `file_size` is attacker
    controlled in principle, but an entry that lies low and expands anyway is
    caught by the per-entry read in `restore`.
    """
    declared = sum(entry.file_size for entry in archive.infolist())

    if declared > MAX_UNCOMPRESSED_BYTES:
        raise RestoreError(
            f"That backup expands to {declared // (1024 * 1024)} MB, over the "
            f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit."
        )

    if compressed > 0 and declared / compressed > MAX_COMPRESSION_RATIO:
        raise RestoreError(
            "That archive expands far more than a backup of books and covers "
            "ever would, so it is refused rather than unpacked."
        )


def _safe_cover_name(name: str) -> str | None:
    """The bare filename, if this entry is a cover and nothing else.

    A zip entry may name any path it likes, including `../../etc/passwd`. Only
    the final component is used, and only when it looks like one of ours, so a
    crafted archive cannot write outside the covers directory.
    """
    if not name.startswith(COVERS_PREFIX):
        return None
    tail = Path(name[len(COVERS_PREFIX) :])
    if tail.name != str(tail) or not tail.name:
        return None
    if tail.suffix.lower() not in _COVER_SUFFIXES:
        return None
    return tail.name


def _cover_bytes(archive: zipfile.ZipFile, entry: str) -> bytes | None:
    """This entry's bytes, if they are an image this app serves. Else None.

    **Why the restore checks content at all**, given that an archive is written
    by this app and restored by the person who owns the instance. Every other
    writer into `COVERS_DIR` stores only bytes it has sniffed: both upload
    routes through `uploads.read_image_upload`, the remote fetch through
    `covers.download`, and `covers.adopt` / `covers.duplicate` by moving bytes
    one of those already checked. Restore took the entry's suffix and wrote the
    bytes unread, so it was the one way a file in that directory could be
    something other than an image.

    **The same test the upload path applies, and no stricter.** Deliberately
    `uploads.sniff_image_extension` rather than a fuller decode: a restore that
    refuses bytes this app itself would accept on upload is a restore that fails
    on its own backup, which is the reason the ticket weighed refusing at all.
    A valid header followed by rubbish passes here exactly as it passes an
    upload.

    **It asks whether these are an image, not whether they are the image the
    name claims**, and the difference is a cover somebody would lose. A `.jpg`
    holding PNG bytes renders today: an `<img>` decodes by magic number, so the
    `Content-Type` the route reads off the filename is not what makes a cover
    appear. `nosniff` does not change that, and does not apply to an image
    destination at all. Requiring the two to agree would therefore delete a
    working cover from a legacy library, silently, to correct a label nothing
    reads. What the four suffixes already guarantee is the property that
    matters: every one of them is a raster type with no script in it, and
    `image/svg+xml` is absent from `ALLOWED_IMAGE_EXTENSIONS` for that reason.

    **What this is not.** It is not what stands between a stored file and script
    execution in a browser. That is the extension allowlist, plus
    `X-Content-Type-Options: nosniff` for the navigation case: measured, HTML
    stored as `1.jpg` is served `content-type: image/jpeg` with `nosniff`, so a
    browser will not render it as a document.

    Read through `archive.open` and decided on `uploads.SNIFF_BYTES` of header,
    so a declined entry costs **a fixed window rather than its declared
    `file_size`**, which `_reject_a_bomb` lets reach `MAX_UNCOMPRESSED_BYTES`.
    Not twelve bytes: `zipfile.ZipExtFile` decompresses in blocks of
    `MIN_READ_SIZE`, so the real figure is 4096 for a deflated entry. Measured
    on CPython 3.14 against a 200 MB entry, tracemalloc peak 45,257 bytes here
    against 458,834,368 for `archive.read`. **The accepted path is unchanged**,
    measured at 437.6 MB peak either way, so nothing here bounds a cover that
    passes: a single enormous entry inside `MAX_UNCOMPRESSED_BYTES` still OOMs
    the pod, and that is its own ticket rather than something this closed.
    """
    with archive.open(entry) as handle:
        header = handle.read(SNIFF_BYTES)
        if sniff_image_extension(header) is None:
            return None
        return header + handle.read()


def _refuse_a_colliding_pair(tables: dict[str, Any]) -> None:
    """Refuse an archive holding two collections whose names fold the same.

    Only an archive taken **before** `e7b3d02a5c94` can hold such a pair, which
    is exactly the archive `_parse_row` recomputes the fold for. Recomputing
    keeps the missing column restorable; it cannot keep the pair restorable,
    because the pair is what the new unique index exists to forbid. Without
    this the insert raises `IntegrityError`, which is not `RestoreError`, so
    the route answers 500 rather than the 400 its docstring promises and says
    nothing about which two names are the problem.

    **Refused, not merged**, and the difference from the migration is the
    caller. The migration is an upgrade nobody asked for and cannot consult, so
    it merges and logs. A restore is something an admin chose to do to a file
    they hold, so it can say what is wrong and let them fix it. This is
    `rename_collection`'s rule, not the upgrade's.
    """
    first_by_fold: dict[str, str] = {}
    for row in tables.get("collections") or []:
        name = row.get("name")
        if not isinstance(name, str):
            continue  # `_parse_row` refuses it, with the table in the message.
        folded = fold_collection_name(name)
        seen = first_by_fold.get(folded)
        if seen is not None:
            # Any second row folding the same, **including one spelled
            # identically**. An earlier version compared `seen != name` and so
            # let two rows both named `Fiction` through, on the assumption that
            # only a pre-revision archive reaches here and that such an archive
            # came from a database whose old index caught the ASCII pair. That
            # is the trusted-archive assumption `_parse_row` above explicitly
            # withholds: a hand edited file is not required to be self
            # consistent. The index is on the fold rather than the name, so the
            # identical pair collides too, and the 500 it caused named neither
            # collection.
            raise RestoreError(
                "This backup holds two collections whose names fold the same: "
                f"{seen[:120]!r} and {name[:120]!r}. Merge them in the library "
                "the backup came from, take a new backup, and restore that."
            )
        first_by_fold[folded] = name


def _archive_knows_about_confirmation(rows: list[dict[str, Any]]) -> bool:
    """Whether this archive's `users` rows were written after `a7c41d9e6b28`.

    **The key's presence, not its value**, and that distinction is the whole of
    the rule below. `_row_to_dict` emits every column, so a modern archive
    carries `email_verified_at: null` for exactly the accounts the policy
    refuses: the ones that registered while `accounts_open_to_outsiders` was on
    and never confirmed. Reading the value would restore those as confirmed,
    which is the opposite of what the archive says.

    An empty `users` payload counts as knowing, because there is nothing to
    stamp either way and guessing on no evidence is how the wrong branch gets
    taken silently.
    """
    return not rows or "email_verified_at" in rows[0]


def _settle_restored_accounts(db: Session) -> None:
    """Stamp the accounts an archive older than `a7c41d9e6b28` carried no
    confirmation for.

    **The migration's rule, applied to the same population by the one other path
    that writes `users` rows wholesale.** Such an archive has no
    `email_verified_at` in its manifest at all, so its accounts come back
    unconfirmed, and turning the account policy on afterwards would refuse every
    one of them, the library's only admin included, with nobody left to override
    it.

    `not_required` is the honest value and the same one the migration wrote:
    those accounts were made under a policy that asked nothing.

    Called only where the archive predates the column. A recent archive keeps
    what it says, including an account that was deliberately left unconfirmed.
    """
    db.execute(
        update(User)
        .where(User.email_verified_at.is_(None))
        .values(
            email_verified_at=datetime.now(UTC).replace(tzinfo=None),
            email_verification_source=VerificationProvenance.NOT_REQUIRED.value,
        )
    )


def _without_household_logins(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every credential in the archive except a household server's own.

    **The belt, and `credentials.seal` is the brace.** An envelope now carries
    the origin it was sealed for, so one lifted beside an address somebody else
    wrote fails authentication rather than opening: the loss below is closed by
    construction, whichever writer moved the row. This filter is kept because it
    is cheap once that is true and because it refuses one step earlier, at the
    archive rather than at the send.

    **What it was bought for.** The address a household login is sent to is
    decided by a row in the same archive, which is what makes this one different
    from a roster catalogue's: `credentials.for_request` binds a stored
    credential to the `base_url` it is **asked** about, and
    `routers/opds.sync_server` asks about `opds_servers.base_url`, which
    `restore` writes with no validating arm. So an archive could keep a
    legitimate `opds-` key and change only the address beside it, and the next
    sync sent the household's login for its own server to a host the archive
    named. Measured by a critic: with a real generated key, a sealed
    `house:housepw` and the address rewritten, `for_request` bound the pair to
    the attacker's origin and `header_for` emitted it. A roster catalogue's
    address is a module constant (`targets.SEEDED`), so its credential never had
    such a writer.

    **The cost is stated rather than hidden**: a restore onto the same machine
    loses OPDS logins this deployment's key could still have opened, and they
    are typed again. That is the bargain `_TABLES` already describes for a
    restore onto a new machine, applied one case earlier, and it is the safe
    direction.

    **Why dropping the row is sufficient, which is not a property of this
    function.** The delete loop above runs over every entry of `_TABLES`
    unconditionally rather than over the tables the archive happens to list, so
    a live envelope cannot survive an archive that simply omits
    `catalogue_credentials`. Without that, an archive could leave the deployment's
    own `opds-` envelope in place and pair it with an `opds_servers` row of its
    choosing, which is this attack one step around this filter. The two do not
    otherwise name each other, so it is said here.
    """
    return [
        row
        for row in rows
        if not str(row.get("source", "")).startswith(OPDS_CREDENTIAL_PREFIX)
    ]


def restore(db: Session, data: bytes) -> dict[str, int]:
    """Replace the database and the covers with the archive's contents.

    Returns a count per table, so the UI can say what actually landed rather
    than "done".
    """
    manifest = read_manifest(data)
    tables = manifest["tables"]
    archive = zipfile.ZipFile(BytesIO(data))

    _refuse_a_colliding_pair(tables)

    # Children first. The association table holds foreign keys into books and
    # tags, so it has to go before either of them.
    db.execute(delete(book_tags))
    for _name, _model, table in reversed(_TABLES):
        db.execute(delete(table))

    restored: dict[str, int] = {}
    for name, _model, table in _TABLES:
        rows = tables.get(name) or []
        if name == "catalogue_credentials":
            rows = _without_household_logins(rows)
        if rows:
            parsers = _temporal_columns(table)
            db.execute(table.insert(), [_parse_row(row, parsers, table) for row in rows])
        restored[name] = len(rows)

    associations = tables.get("book_tags") or []
    if associations:
        db.execute(book_tags.insert(), associations)
    restored["book_tags"] = len(associations)

    # After the new settings rows, not before: the archive carries its own
    # value for this key and would otherwise restore an older epoch, which is
    # exactly the state a pre-restore token verifies against.
    settings_store.bump_token_epoch(db)

    if not _archive_knows_about_confirmation(tables.get("users") or []):
        _settle_restored_accounts(db)

    db.commit()

    # Covers last, and only once the database is committed. A cover with no row
    # is orphaned clutter; a row with no cover shows the placeholder. The
    # second is the better failure.
    #
    # The old files are cleared first, so a restore leaves the directory
    # describing the library that was restored rather than that library plus
    # whatever the previous one had. Files are the one thing a row does not
    # carry with it, which is the standing cost of covers living on disk.
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for existing in COVERS_DIR.glob("*"):
        if existing.is_file() and existing.suffix.lower() in _COVER_SUFFIXES:
            existing.unlink()

    declined: list[str] = []
    for entry in archive.namelist():
        filename = _safe_cover_name(entry)
        if filename is None:
            continue
        body = _cover_bytes(archive, entry)
        if body is None:
            declined.append(filename)
            continue
        # Not `name`: this function already binds that to a table name, a
        # `str`, in the insert loop above.
        stored = Path(filename)
        try:
            # `write_image`, **not** `replace_image`, and the difference is a
            # cover somebody can see. `replace_image` sweeps the other formats of
            # a base, which is right for an upload and wrong here: the directory
            # was emptied above, so the only file a sweep could reach is a
            # sibling this same archive just wrote. An archive holding `1.jpg`
            # and `1.png` describes a library that held both, and
            # `routers/covers.get_cover` answers from the extension in the row's
            # `cover_url`, so deleting the loser 404s that row, silently, with
            # the count still reporting it restored. Leaving both is safe rather
            # than merely easier: `covers.stored_path` and
            # `routers/settings._find_login_bg` are the two lookups that resolve
            # on disk and both are ordered, so a base with two files resolves the
            # same way in every process. `write_image` still writes beside the
            # destination and moves it into place, which is the half a bare
            # `write_bytes` lacked.
            #
            # **Lowercased**, which a bare write did not do: `_safe_cover_name`
            # accepts `1.JPG`, and the cover route builds its path from a
            # lowercased extension, so on a case sensitive filesystem that file
            # restored to a name nothing could ever serve. The **stem** is left
            # alone: a book's is its id and the login background's is one fixed
            # constant, so nothing legitimate needs folding, and folding it would
            # merge two entries an archive deliberately spelled apart.
            write_image(
                COVERS_DIR,
                stored.stem,
                stored.suffix.lower().removeprefix("."),
                body,
            )
        except (OSError, ValueError):
            # **Declined, never raised.** This loop runs after `db.commit()` and
            # after the directory was emptied, so anything escaping here is a
            # 500 on a library whose rows are restored and whose covers are
            # gone: the state this function promises not to produce. A zip entry
            # may name a file with a NUL byte in it or one longer than the
            # filesystem allows, and neither is `RestoreError`; a full disk part
            # way through the loop is the same shape and the same answer.
            declined.append(filename)
    if declined:
        # `%r` on each name, not `%s` on the join. A zip name field holds 64 KB
        # and may contain a newline, so an archive could otherwise write its own
        # lines into this log. `_parse_row` states the same rule at its own site.
        logger.warning(
            "Declined %d archive entries that are not an image this app serves: %s",
            len(declined),
            ", ".join(repr(name[:120]) for name in sorted(declined)[:20]),
        )
    # Counted off the directory rather than off the loop, so the number is what
    # is actually there rather than what this function believes it put there.
    # The two agree while nothing removes a file behind the count, which is the
    # property `write_image` above exists to keep and which `replace_image`
    # would have broken.
    restored["covers"] = sum(
        1 for path in COVERS_DIR.glob("*") if path.suffix.lower() in _COVER_SUFFIXES
    )

    _repair_seeded_tags(db)

    logger.info("Restored a backup: %s", restored)
    return restored


def _repair_seeded_tags(db: Session) -> None:
    """Put the seeded flag and the key back on the curated tags.

    The two columns whose default is wrong for a restored row, and both fail
    silently. An archive taken before `tags.is_predefined` existed carries no
    value for it, so every tag comes back as `False`, which makes the built-in
    vocabulary deletable and duplicates it at the next boot when `seed_tags()`
    finds the names missing its flag. An archive taken before `tags.key`
    existed comes back with every key null, and a null key is how a renamed tag
    is recorded, so the whole curated vocabulary would read as invented and a
    German library would silently be back in English.

    **The rule for the key is the migration's rule**, and it has to be: keyed
    where the name matches the English seed name exactly, and left null
    otherwise, so restoring an archive cannot put the seeded word back over one
    a household renamed. Neither column is read from the archive at all: the
    flag is overwritten here, and `_parse_row` blanks the key on the way in so
    that a hand-edited one cannot collide with the index before this runs.

    **The cost of that, said rather than left to be discovered.** A key this
    version has never heard of does not survive a restore: the name it belongs
    to is not in this `PREDEFINED_TAGS`, so the row is repaired to null and
    stays null, because `seed_tags()` only ever writes a key on a row it
    inserts. So a backup from a newer image restores into an older one with
    that tag shown as typed, permanently, which is what `is_predefined` has
    always done with a tag added after the image was built. `known_key` is
    about a key already in the database being **read**; this is the write path
    and it is stricter.

    **`collections.name_folded` is derived on the way in instead**, because it
    is NOT NULL: an archive predating it would not restore at all rather than
    restore wrongly, and the fold is computable from the row itself.
    `is_predefined` and the key are not, `PREDEFINED_TAGS` being a list only
    the app has, so they are repaired here after every row is in.

    `PREDEFINED_TAGS` is imported here rather than at module scope because
    `main` imports the routers, which import this module.
    """
    from main import PREDEFINED_TAGS

    keys_by_name = {name: key for key, name, _category in PREDEFINED_TAGS}
    changed = 0
    for tag in db.query(Tag).all():
        # **One pass, and that it is safe rests on `_parse_row` blanking the
        # key.** `uq_tags_key` is unique, so a key moving from one row to
        # another would need the old holder cleared in an earlier statement,
        # and the order SQLAlchemy flushes these in is not the order of this
        # loop. No key can move here: every row arrives null, `tags.name` is
        # unique, and `PREDEFINED_TAGS` maps 105 distinct names onto 105
        # distinct keys, so this writes each key at most once. Delete the
        # `_parse_row` block and this becomes an `IntegrityError` on a restore.
        seeded_key = keys_by_name.get(tag.name)
        should_be = seeded_key is not None
        if tag.is_predefined != should_be or tag.key != seeded_key:
            tag.is_predefined = should_be
            tag.key = seeded_key
            changed += 1
    if changed:
        db.commit()
        logger.info("Repaired the seeded flag and key on %d tags after a restore", changed)
