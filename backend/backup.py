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
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Table, delete
from sqlalchemy.orm import Session

import covers
import settings_store
from config import COVERS_DIR
from database import Base
from models import (
    AuthorAlias,
    AuthorIdentifier,
    Book,
    CatalogueTarget,
    Classification,
    Collection,
    CustomField,
    CustomFieldValue,
    Loan,
    Note,
    Quote,
    ReadingProgress,
    Setting,
    Tag,
    User,
    UserBook,
    book_tags,
    fold_collection_name,
)

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
_COVER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

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

    covers_restored = 0
    for entry in archive.namelist():
        filename = _safe_cover_name(entry)
        if filename is None:
            continue
        (COVERS_DIR / filename).write_bytes(archive.read(entry))
        covers_restored += 1
    restored["covers"] = covers_restored

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
