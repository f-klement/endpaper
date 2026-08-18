"""Tests for backend/uploads.py: content-based image validation.

The filename used to decide the format, and a filename is caller-controlled.
Anything at all could be stored as `12.png` and then served back from this
app's own origin.
"""

import pytest
from fastapi import HTTPException, UploadFile

from config import MAX_UPLOAD_BYTES
from tests.helpers import JPEG_BYTES, NOT_AN_IMAGE, PNG_BYTES, WEBP_BYTES
from uploads import read_image_upload, sniff_image_extension


def upload(data: bytes, filename: str = "whatever.png") -> UploadFile:
    import io

    return UploadFile(filename=filename, file=io.BytesIO(data))


class TestSniffImageExtension:
    @pytest.mark.parametrize(
        "data,expected",
        [
            (PNG_BYTES, "png"),
            (JPEG_BYTES, "jpg"),
            (WEBP_BYTES, "webp"),
        ],
        ids=["png", "jpeg", "webp"],
    )
    def test_identifies_supported_formats(self, data, expected):
        assert sniff_image_extension(data) == expected

    def test_jpeg_is_reported_as_jpg(self):
        """One canonical extension per format, so a book has one predictable
        cover filename rather than both .jpg and .jpeg being possible."""
        assert sniff_image_extension(JPEG_BYTES) == "jpg"

    @pytest.mark.parametrize(
        "data",
        [
            NOT_AN_IMAGE,
            b"GIF89a" + b"\x00" * 8,
            b"%PDF-1.7",
            b"\x7fELF",
            b"",
            b"not bytes of any image",
        ],
        ids=["svg", "gif", "pdf", "elf", "empty", "text"],
    )
    def test_rejects_everything_else(self, data):
        assert sniff_image_extension(data) is None

    def test_riff_that_is_not_webp_is_rejected(self):
        """RIFF is a container: a WAV starts the same way as a WebP."""
        wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 8
        assert sniff_image_extension(wav) is None


class TestReadImageUpload:
    async def test_returns_the_bytes_and_the_extension(self):
        data, extension = await read_image_upload(upload(PNG_BYTES))
        assert data == PNG_BYTES
        assert extension == "png"

    async def test_the_filename_does_not_decide(self):
        """A JPEG named .png is stored as a .jpg."""
        _, extension = await read_image_upload(upload(JPEG_BYTES, filename="cover.png"))
        assert extension == "jpg"

    async def test_an_svg_named_png_is_rejected(self):
        # SVG can carry script and would be served from our own origin.
        with pytest.raises(HTTPException) as caught:
            await read_image_upload(upload(NOT_AN_IMAGE, filename="cover.png"))
        assert caught.value.status_code == 400

    async def test_an_empty_upload_is_rejected(self):
        with pytest.raises(HTTPException) as caught:
            await read_image_upload(upload(b""))
        assert caught.value.status_code == 400

    async def test_a_file_over_the_cap_is_rejected(self):
        oversized = PNG_BYTES + b"\x00" * MAX_UPLOAD_BYTES
        with pytest.raises(HTTPException) as caught:
            await read_image_upload(upload(oversized))
        assert caught.value.status_code == 413

    async def test_a_file_at_the_cap_is_accepted(self):
        at_limit = PNG_BYTES + b"\x00" * (MAX_UPLOAD_BYTES - len(PNG_BYTES))
        data, extension = await read_image_upload(upload(at_limit))
        assert len(data) == MAX_UPLOAD_BYTES
        assert extension == "png"

    async def test_reads_no_more_than_the_cap_plus_one(self):
        """The cap also bounds memory: the body is read into memory before it
        is written, so an unbounded read is a denial-of-service."""
        huge = PNG_BYTES + b"\x00" * (MAX_UPLOAD_BYTES * 3)
        with pytest.raises(HTTPException):
            await read_image_upload(upload(huge))
