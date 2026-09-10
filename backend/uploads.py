"""Validation for uploaded images.

Both upload endpoints (book covers and the login background) previously trusted
the filename extension alone. A filename is caller-controlled, so that decided
nothing: anything at all could be stored as `12.png` and then served back from
this app's own origin.

What actually determines the format is the file's leading bytes, so that is
what is checked here. The extension is derived from the content, not from the
name the caller sent.

**One writer into that directory does not derive the name, and a reader of this
file needs to know it.** `backup.restore` keeps the name the archive gave an
entry and checks only that the bytes are one of these formats, so a cover
restored from a legacy archive may be a PNG called `1.jpg`. It is kept rather
than renamed because an `<img>` decodes by magic number, so it displays, and
because `create` does not sniff either: requiring the two to agree would leave
this app unable to restore its own backup. `backup._cover_bytes` carries the
reasoning.

**Every writer that exists today sniffs, and that is four call sites checked by
hand rather than a rule anything enforces.** Said plainly because the sentence
that used to sit here claimed no path into the directory allows bytes that are
not an image, which is a bound on the future that nothing holds up: a new caller
may pass unchecked bytes to either helper below, or skip both and write to the
directory itself. An allowlist of importing modules was weighed and refused, on
the grounds that it would fail when the set grew without ever checking the thing
it names, which is what reaches the disk.
"""

import os
import threading
from pathlib import Path
from typing import Final

from fastapi import HTTPException, UploadFile, status

from config import ALLOWED_IMAGE_EXTENSIONS, MAX_UPLOAD_BYTES

# Leading bytes that identify each format we accept.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
# WebP is a RIFF container: "RIFF" <4-byte length> "WEBP".
_RIFF_MAGIC = b"RIFF"
_WEBP_TAG = b"WEBP"

#: How many leading bytes `sniff_image_extension` can possibly read.
#:
#: **Derived from the magic numbers above, never written as a number.** A
#: caller holding the whole file never needs this, and one reading from a
#: stream does, so that it can decide on a header instead of on a gigabyte:
#: `backup.restore` is that caller. A literal here goes stale the first time a
#: magic number gets longer, and the staleness is silent in the direction that
#: costs a cover: too small a window makes the stream caller decline a file the
#: upload path accepts.
#:
#: The WebP term is the only one that is not a length: RIFF puts its tag at
#: offset 8, so the reach is that offset plus the tag. An arm added below that
#: reads further has to be added to this max too, and
#: `tests/test_uploads.py::TestTheSniffWindow` is what says so out loud, by
#: sniffing every format the app accepts truncated to this width.
SNIFF_BYTES: Final = max(len(_PNG_MAGIC), len(_JPEG_MAGIC), 8 + len(_WEBP_TAG))


def sniff_image_extension(data: bytes) -> str | None:
    """Return the canonical extension for `data`, or None if unrecognised.

    JPEG is reported as "jpg" so a book has one predictable cover filename
    rather than two possible ones.
    """
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpg"
    if data.startswith(_RIFF_MAGIC) and data[8:12] == _WEBP_TAG:
        return "webp"
    return None


async def read_image_upload(file: UploadFile) -> tuple[bytes, str]:
    """Read an upload, enforce the size cap, and identify it by content.

    Returns the bytes and the extension to store them under. Raises 413 if the
    file is too large and 400 if it is not an image format we serve.
    """
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    extension = sniff_image_extension(data)
    if extension is None:
        raise HTTPException(
            status_code=400,
            detail="File must be a JPEG, PNG or WebP image",
        )
    return data, extension


def replace_image(directory: Path, base: str, extension: str, data: bytes) -> Path:
    """Write `data` as `base.extension`, replacing any other format of `base`.

    The callers used to unlink the existing file first and then write the new
    one. A failure in between (a full disk is the realistic one) left the book
    with no cover at all and a `cover_url` pointing at what had just been
    deleted, which is a worse outcome than the upload simply failing. The atomic
    write that fixed it is `write_image` below, and this is that plus the sweep.

    The leftovers in other formats are removed only once the write has
    succeeded, because two formats of the same base both existing means the
    lookups that resolve a cover by looking on disk, `covers.stored_path` and
    `routers/settings._find_login_bg`, have two files to choose between.

    **Not for a restore.** `write_image` says why, and picking the wrong one of
    these two at a new call site is a one word edit.
    """
    destination = write_image(directory, base, extension, data)

    for other in ALLOWED_IMAGE_EXTENSIONS:
        stale = directory / f"{base}.{other}"
        if stale != destination:
            stale.unlink(missing_ok=True)
    return destination


def write_image(directory: Path, base: str, extension: str, data: bytes) -> Path:
    """Write `data` as `base.extension`, atomically, touching nothing else.

    `replace_image` without the sweep, and the split is not tidying: **a restore
    must not sweep.** The sweep exists so an upload replacing a book's JPEG with
    a PNG does not leave two files whose lookup order decides which is used.
    `backup.restore` empties the directory before it writes, so the only thing a
    sweep could reach there is a sibling the same archive just wrote. An archive
    holding both `1.jpg` and `1.png` describes a library that held both, and
    `routers/covers.get_cover` answers from the extension in the row's
    `cover_url`, so deleting the loser is deleting the cover a row names,
    silently, with the count still reporting it. Reproducing the directory the
    archive describes is the restore's job; correcting a library that holds two
    is not.

    **Two files of a base is a stable state, not a coin flip**, which is what
    makes leaving them the safe answer rather than the lazy one: the two lookups
    that resolve on disk, named above, are both ordered, so the pair resolves the
    same way in every process.
    """
    destination = directory / f"{base}.{extension}"
    # A leading dot so a leftover is recognisable, and the pid **and thread id**
    # so two writes of the same book cannot land on the same temporary name.
    #
    # The pid alone was enough while the only concurrency here was separate
    # processes. It is not any more: the cover backfill fans out across a
    # ThreadPoolExecutor **inside one process**, so two overlapping requests for
    # the same book id built an identical temp path. Two members repairing a
    # shared book does it, and so does one member inside their own rate limit.
    # Observed: both threads wrote `.9.31.tmp`, one `os.replace` won and the
    # other failed with ENOENT and was counted as a failed download.
    #
    # The failure that is not merely untidy: a body large enough to need more
    # than one write could be promoted half written, and `covers.stored_ids`
    # would then never revisit that book, because a file is there.
    temporary = directory / f".{base}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return destination
