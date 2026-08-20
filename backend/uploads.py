"""Validation for uploaded images.

Both upload endpoints (book covers and the login background) previously trusted
the filename extension alone. A filename is caller-controlled, so that decided
nothing: anything at all could be stored as `12.png` and then served back from
this app's own origin.

What actually determines the format is the file's leading bytes, so that is
what is checked here. The extension is derived from the content, not from the
name the caller sent.
"""

import os
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from config import ALLOWED_IMAGE_EXTENSIONS, MAX_UPLOAD_BYTES

# Leading bytes that identify each format we accept.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
# WebP is a RIFF container: "RIFF" <4-byte length> "WEBP".
_RIFF_MAGIC = b"RIFF"
_WEBP_TAG = b"WEBP"


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

    Both callers used to unlink the existing file first and then write the new
    one. A failure in between (a full disk is the realistic one) left the book
    with no cover at all and a `cover_url` pointing at what had just been
    deleted, which is a worse outcome than the upload simply failing.

    So the new file is written beside its destination and moved into place with
    `os.replace`, which is atomic within a filesystem: either the old image is
    still there or the new one is, never neither. The leftovers in other
    formats are removed only once that has succeeded, because two formats of
    the same base both existing means which one is served depends on lookup
    order.
    """
    destination = directory / f"{base}.{extension}"
    # A leading dot and the pid so a concurrent upload of the same book cannot
    # land on the same temporary name, and so a leftover is recognisable.
    temporary = directory / f".{base}.{os.getpid()}.tmp"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise

    for other in ALLOWED_IMAGE_EXTENSIONS:
        stale = directory / f"{base}.{other}"
        if stale != destination:
            stale.unlink(missing_ok=True)
    return destination
