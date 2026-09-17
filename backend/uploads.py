"""Validation for uploaded images, and the two ways bytes reach a file.

Both upload endpoints (book covers and the login background) previously trusted
the filename extension alone. A filename is caller-controlled, so that decided
nothing: anything at all could be stored as `12.png` and then served back from
this app's own origin.

What actually determines the format is the file's leading bytes, so that is
what is checked here. The extension is derived from the content, not from the
name the caller sent.

**This module knows what an image is and how to write one. It does not know
where covers live or what they are called**, which is `cover_store`, and every
writer below has exactly that one caller. The directory used to be addressed by
five modules and the choice between the two writers below made at each of them,
where a wrong choice was a one word edit; naming the importers that were allowed
to make it was weighed and refused, on the grounds that such a list fails when
the set grows without ever checking the thing it names, which is what reaches
the disk. A single door checks that instead: `cover_store` sniffs on the way
through, so "every file in that directory is one of these formats" is a property
of one module rather than of four call sites checked by hand.

**A name and its bytes need not agree, and a reader of this file needs to know
it.** `backup.restore` keeps the name the archive gave an entry, so a cover
restored from a legacy archive may be a PNG called `1.jpg`. It is kept rather
than renamed because an `<img>` decodes by magic number, so it displays.
`backup._cover_bytes` carries the reasoning.
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


async def read_image_upload(file: UploadFile) -> bytes:
    """Read an upload, enforce the size cap, and refuse what is not an image.

    Returns the bytes. Raises 413 if the file is too large and 400 if it is not
    an image format we serve. **The bytes are handed on unnamed**: what an
    upload is stored as is `cover_store`'s, and this exists so that a caller's
    mistake is a 400 rather than the store's refusal arriving as a 500.
    """
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if sniff_image_extension(data) is None:
        raise HTTPException(
            status_code=400,
            detail="File must be a JPEG, PNG or WebP image",
        )
    return data


def replace_image(directory: Path, base: str, extension: str, data: bytes) -> Path:
    """Write `data` as `base.extension`, replacing any other format of `base`.

    The callers used to unlink the existing file first and then write the new
    one. A failure in between (a full disk is the realistic one) left the book
    with no cover at all and a `cover_url` pointing at what had just been
    deleted, which is a worse outcome than the upload simply failing. The atomic
    write that fixed it is `write_image` below, and this is that plus the sweep.

    The leftovers in other formats are removed only once the write has
    succeeded, because two formats of the same base both existing means the
    lookup that resolves a cover by looking on disk, `cover_store._first_on_disk`,
    has two files to choose between.

    **Not for a restore.** `write_image` says why. Which of the two applies is
    `cover_store`'s to decide and it decides it by the argument it was handed,
    so this is not a choice a new call site makes.
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
    must not sweep.** `cover_store.restore` carries that reasoning, because it
    is the one caller and the one place the choice is made.

    **Two files of a base is a stable state, not a coin flip**, which is what
    makes leaving them the safe answer rather than the lazy one: the two lookups
    that resolve on disk, `cover_store.path_of` and
    `cover_store.login_background_path`, are the same ordered function, so the
    pair resolves the same way in every process.
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
    # than one write could be promoted half written, and `cover_store.book_ids`
    # would then never revisit that book, because a file is there.
    temporary = directory / f".{base}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return destination
