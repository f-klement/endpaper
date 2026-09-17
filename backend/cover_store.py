"""The covers directory, and the only door into it.

Five modules used to import `config.COVERS_DIR`, compose `<base>.<ext>` by hand,
and choose between the two writers in `uploads.py` whose difference is a cover
somebody can see. Nothing owned the layout, so every new call site re-derived it
and `uploads.py` could only warn, at its own site, that picking the wrong writer
is a one word edit.

A caller here names **what** it is storing: a book, the login background, or an
entry out of an archive. It never names the directory, the filename, the
extension set, or which writer applies. `uploads.py` keeps the sniffing and the
atomic write and stops being a door a caller configures.

**Which writer sweeps is decided by the argument, not by the caller.** `save`
takes a book id and sweeps the other formats of that book; `restore` takes a
filename out of an archive and must not sweep, because a library that holds both
`1.jpg` and `1.png` is a library whose rows name both (`restore` carries that
reasoning). An upload cannot reach `restore` without inventing a filename, and a
restore cannot reach `save` without discarding the name the archive gave it. The
one word edit is now a different argument.

**Every write of bytes from outside this directory sniffs them**, including the
three whose caller already did. `copy` and `move` are the exception and the only
one: they move bytes that are already in here, so `_place` does not sniff and
says why. That is what makes "nothing in this directory is anything but
`ALLOWED_IMAGE_EXTENSIONS`" a property of this module rather than of four call
sites checked by hand. `uploads.py` records an allowlist of importing modules
weighed and refused for naming its importers instead of checking what reaches
the disk; this is the door that refusal left open.

**Where a cover file is.** `covers.py` is the other half and answers a different
question: where a cover comes from, and what URL one is served at.

`tests/test_cover_store.py::TestTheDirectoryHasOneOwner` is the enforcement, and
names its own blind spots.
"""

from pathlib import Path
from typing import Final

from config import ALLOWED_IMAGE_EXTENSIONS, COVERS_DIR
from uploads import replace_image, sniff_image_extension, write_image

# No logger. Every failure here is raised, and the caller that can say what the
# failure cost is the one that logs it: `covers.adopt` names the book a move came
# from, `backup.restore` collects the entries it declined into one line.

#: The login background's base name. Not a book, so `book_ids` and `remove`
#: never see it: both of those read or write an integer stem. It lives in this
#: directory because the route that serves it and the route that writes it agree
#: on that, and it is spelled here because this module owns every name in here.
LOGIN_BG_BASE: Final = "login_bg"


class NotAnImage(ValueError):
    """The bytes offered are not a format this app serves.

    A `ValueError`, because `backup.restore` already declines an entry on one
    and the alternative is a 500 on a restore that is otherwise fine.
    """


def _identify(data: bytes) -> str:
    """The extension these bytes will be stored under. Raises `NotAnImage`.

    The one gate every write in this module passes through. `uploads.py` decides
    what an image is; this decides that an unrecognised one never lands.
    """
    extension = sniff_image_extension(data)
    if extension is None:
        raise NotAnImage("Not a JPEG, PNG or WebP image")
    return extension


def _within(path: Path) -> bool:
    """Whether `path` is a name directly inside the covers directory.

    Belt and braces rather than the primary defence, and it is here so that the
    reasoning is in one place instead of at each route that composes a name: a
    book id is an int and the cover routes constrain the extension to letters,
    so neither half can carry a separator today. This is what still holds when
    somebody changes that without reading why it was safe.

    **The parent, not `relative_to`.** That answers yes for a subdirectory too,
    and this directory is flat: every name in it is `<book id>` or the login
    background, `files` and `book_ids` read it with `iterdir`, and nothing here
    creates a subdirectory. Accepting one would mean serving a file no other
    function in this module can see.

    Symlinks are resolved, so a cover file that is a link out of the directory is
    refused rather than served. Nothing this app writes creates one, and the two
    lookups that apply this are the serving one and `restore`'s destination:
    `_first_on_disk` says why it does not.
    """
    try:
        return path.resolve().parent == COVERS_DIR.resolve()
    except (OSError, ValueError):
        return False


def _is_cover(path: Path) -> bool:
    """Whether this file is one of ours, judged by its name alone."""
    return path.suffix.lstrip(".").lower() in ALLOWED_IMAGE_EXTENSIONS


def _first_on_disk(base: str) -> Path | None:
    """The file stored for `base` in whichever format, or None.

    **`sorted`, and the order itself does not matter: being the same order twice
    does.** `ALLOWED_IMAGE_EXTENSIONS` is a frozenset, whose iteration order is
    not stable between processes, and a base can have two formats on disk: `save`
    sweeps the losers but `restore` deliberately does not.

    Unordered, the consequences are not cosmetic. `covers.local_url_for` reads
    this for a book, and `merge_books` decides whether the keeper adopts a cover
    by comparing `keeper.cover_url` against it: one run adopts the cover, the
    next hands the loser to `remove`, which deletes both files. For the
    login background it is the public login page serving a different image after
    a pod restart with nothing having changed. Alphabetical is arbitrary and
    stable, which is the whole requirement.

    **No `_within` here, deliberately, so this answers about a file the serving
    lookup may refuse**: a cover that is a symlink out of the directory is found
    by this and not served by `_to_serve`, which shows up as a `cover_url` that
    404s. It is refused where it is read back and not where it is looked up
    because nothing this app writes creates one, and an operator who placed one
    by hand had write access to the data volume already. `files()` skips the
    check for the same reason and with one more consequence.
    """
    for extension in sorted(ALLOWED_IMAGE_EXTENSIONS):
        candidate = COVERS_DIR / f"{base}.{extension}"
        if candidate.is_file():
            return candidate
    return None


def _to_serve(base: str, extension: str) -> Path | None:
    """The file a request for `base.extension` is answered with, or None.

    One answer to the four questions a route would otherwise ask itself, because
    a route answers all four the same way: 404. A 403 would confirm the id
    exists.
    """
    normalised = extension.lower()
    if normalised not in ALLOWED_IMAGE_EXTENSIONS:
        return None
    path = COVERS_DIR / f"{base}.{normalised}"
    if not _within(path) or not path.is_file():
        return None
    return path


# ── Reading ───────────────────────────────────────────────────────────────────


def path_of(book_id: int) -> Path | None:
    """The cover file this app holds for a book, in whatever format, or None."""
    return _first_on_disk(str(book_id))


def login_background_path() -> Path | None:
    """The login background on disk, in whatever format, or None."""
    return _first_on_disk(LOGIN_BG_BASE)


def cover_to_serve(book_id: int, extension: str) -> Path | None:
    """The file to answer this book's cover request with, or None."""
    return _to_serve(str(book_id), extension)


def login_background_to_serve(extension: str) -> Path | None:
    """The file to answer a login background request with, or None."""
    return _to_serve(LOGIN_BG_BASE, extension)


def book_ids() -> set[int]:
    """Every book id with a cover file behind it.

    One directory read rather than a `stat` per book, because the caller is the
    backfill and it asks about the whole library at once. On the deployment's NFS
    mount the difference between one readdir and three thousand stats is the
    difference between a click and a timeout.

    A name that is not `<int>.<ext>` is skipped, which is what keeps
    `login_bg.png` out of it.
    """
    if not COVERS_DIR.is_dir():
        return set()

    found: set[int] = set()
    for entry in COVERS_DIR.iterdir():
        if not entry.is_file() or not _is_cover(entry):
            continue
        # `isascii()` beside `isdigit()`, so a filename of non ASCII digits
        # cannot raise out of the `int()` and take the whole orphan sweep with
        # it. See `isbn.is_valid_isbn13`.
        if entry.stem.isascii() and entry.stem.isdigit():
            found.add(int(entry.stem))
    return found


def files() -> list[Path]:
    """Every cover file in the directory, the login background included.

    Sorted, so an archive written from it lists its entries the same way twice.
    `is_file()` as well as the suffix, so a directory somebody named `1.jpg`
    cannot be read as a cover or counted as one.

    No `_within`, as in `_first_on_disk`, and here the consequence is that
    `backup.build_archive` reads through a link out of the directory into the
    archive an admin downloads. Unchanged by this module existing: the walk it
    replaced did not check either.
    """
    if not COVERS_DIR.is_dir():
        return []
    return sorted(path for path in COVERS_DIR.iterdir() if path.is_file() and _is_cover(path))


# ── Writing ───────────────────────────────────────────────────────────────────


def save(book_id: int, data: bytes) -> Path:
    """Store `data` as this book's cover, replacing any other format of it.

    The sweep is the point: one book has one cover, and two formats of it leave
    `path_of` picking between them. It happens only once the write has succeeded,
    because the order that deleted first left a book with no cover at all when
    the write then failed. `uploads.replace_image` carries that incident.

    Raises `NotAnImage` if the bytes are not one this app serves, and `OSError` if
    the write fails. The caller decides which of those is a 400, which is a
    counted failure and which is a 500.
    """
    return replace_image(COVERS_DIR, str(book_id), _identify(data), data)


def save_login_background(data: bytes) -> Path:
    """Store `data` as the login background, replacing any other format of it."""
    return replace_image(COVERS_DIR, LOGIN_BG_BASE, _identify(data), data)


def restore(name: str, data: bytes) -> Path:
    """Write one cover out of an archive, under the name the archive gave it.

    **Does not sweep, and that is the whole reason it is not `save`.** The sweep
    exists so an upload replacing a book's JPEG with a PNG does not leave two
    files whose lookup order decides which is used. `backup.restore` empties this
    directory before it writes, so the only file a sweep could reach here is a
    sibling the same archive just wrote. An archive holding both `1.jpg` and
    `1.png` describes a library that held both, and `routers/covers.get_cover`
    answers from the extension in the row's `cover_url`, so deleting the loser is
    deleting the cover a row names, silently, with the restore's count still
    reporting it. Reproducing the directory the archive describes is the
    restore's job; correcting a library that holds two is not.

    **The name's extension is kept, and the sniff is a gate rather than the
    name.** A legacy archive may hold a PNG called `1.jpg`, which displays, since
    an `<img>` decodes by magic number. Renaming it to match the bytes would
    leave the row's `cover_url` naming a file that no longer exists, which is the
    same cover lost by a different route. What the sniff refuses is an entry that
    is not an image at all.

    **Lowercased**, because the cover route builds its path from a lowercased
    extension, so on a case sensitive filesystem `1.JPG` restores to a name
    nothing could ever serve. The **stem** is left alone: a book's is its id and
    the login background's is one fixed constant, so nothing legitimate needs
    folding, and folding it would merge two entries an archive spelled apart.

    Raises `ValueError` for a name that is not a bare `<stem>.<ext>` this app
    serves, `NotAnImage` for bytes that are not one, and `OSError` if the write
    fails. `backup.restore` declines the entry on any of the three rather than
    failing a restore whose rows are already committed.
    """
    stored = Path(name)
    extension = stored.suffix.lstrip(".").lower()
    if stored.name != name or not stored.stem or extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(f"Not a cover filename: {name!r}")
    _identify(data)
    destination = COVERS_DIR / f"{stored.stem}.{extension}"
    if not _within(destination):
        raise ValueError(f"Not a cover filename: {name!r}")
    return write_image(COVERS_DIR, stored.stem, extension, data)


def _place(book_id: int, source: Path) -> Path:
    """Write `source`'s bytes under `book_id`, keeping the source's extension.

    **The name's extension, not the bytes'.** `restore` may have kept a legacy
    cover whose two disagree, and this is where such a file travels to a new book
    id. Re-deriving it from the bytes would rename the file and leave the
    `cover_url` its caller returns pointing at the old name.

    No sniff, and it is the one write here without one: the bytes come out of
    this directory, so they have already passed one. Reading them back to check
    again would only be checking this module against itself.

    Through `replace_image` rather than a rename, so the receiving book's covers
    in other formats go the same way they do on an upload.
    """
    extension = source.suffix.lstrip(".").lower()
    return replace_image(COVERS_DIR, str(book_id), extension, source.read_bytes())


def copy(book_id: int, from_book_id: int) -> Path | None:
    """Copy one book's cover file to another book's id. None if there is none.

    The two rows must not share a file: files are named by book id and `remove`
    deletes by id, so purging either copy would blank the other's cover while
    leaving a `cover_url` pointing at nothing.

    Raises `OSError` if the write fails, having touched nothing.
    """
    source = path_of(from_book_id)
    return None if source is None else _place(book_id, source)


def move(book_id: int, from_book_id: int) -> Path | None:
    """Move one book's cover file to another book's id. None if there is none.

    The source is unlinked only once the write has succeeded. `replace_image` is
    atomic and re-raises with its temporary file removed, so a failure here
    leaves the source where it was: the caller's "the move did not happen" is
    also "these bytes are still the only copy".
    """
    source = path_of(from_book_id)
    if source is None:
        return None
    destination = _place(book_id, source)
    # **Not when the two are the same file**, which is a move onto the id the
    # cover is already under. `merge_books` passes two distinct ids so nothing
    # reaches it today, and what it would cost is the whole point of the check:
    # the unlink deletes the file just written and the caller is told the move
    # succeeded, so the row names a cover that is gone.
    if destination != source:
        source.unlink(missing_ok=True)
    return destination


def remove(book_id: int) -> None:
    """Delete every stored cover for a book. Called when the book goes for good.

    A file is not deleted by deleting a row, so this is the cost of holding
    covers on disk rather than in the database. A cover whose book no longer
    exists is dead bytes no query will ever find, and worse than that: SQLite
    reuses an id once the highest row goes, so the next book to take it would
    inherit somebody else's cover.
    """
    for extension in ALLOWED_IMAGE_EXTENSIONS:
        (COVERS_DIR / f"{book_id}.{extension}").unlink(missing_ok=True)


def clear() -> None:
    """Empty the directory of covers, creating it if it is not there.

    Only a restore does this, so that it leaves the directory describing the
    library that was restored rather than that library plus whatever the previous
    one had. Files are the one thing a row does not carry with it.
    """
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for existing in files():
        existing.unlink()
