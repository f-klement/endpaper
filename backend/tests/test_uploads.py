"""Tests for backend/uploads.py: content-based image validation.

The filename used to decide the format, and a filename is caller-controlled.
Anything at all could be stored as `12.png` and then served back from this
app's own origin.
"""

from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from config import MAX_UPLOAD_BYTES
from tests.helpers import JPEG_BYTES, NOT_AN_IMAGE, PNG_BYTES, WEBP_BYTES
from uploads import read_image_upload, replace_image, sniff_image_extension


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


class TestReplaceImage:
    """The order matters: both callers used to delete the old image and then
    write the new one."""

    def test_it_writes_the_file(self, tmp_path):
        path = replace_image(tmp_path, "7", "png", PNG_BYTES)
        assert path == tmp_path / "7.png"
        assert path.read_bytes() == PNG_BYTES

    def test_it_removes_the_same_image_in_another_format(self, tmp_path):
        """Two formats of one base both existing means which is served depends
        on lookup order."""
        (tmp_path / "7.jpg").write_bytes(JPEG_BYTES)

        replace_image(tmp_path, "7", "png", PNG_BYTES)

        assert not (tmp_path / "7.jpg").exists()

    def test_it_leaves_another_books_cover_alone(self, tmp_path):
        (tmp_path / "8.jpg").write_bytes(JPEG_BYTES)

        replace_image(tmp_path, "7", "png", PNG_BYTES)

        assert (tmp_path / "8.jpg").exists()

    def test_a_failed_write_leaves_the_old_image_in_place(self, tmp_path, monkeypatch):
        """The point of the whole helper. A full disk used to leave the book
        with no cover and a cover_url pointing at what had been deleted."""
        (tmp_path / "7.jpg").write_bytes(JPEG_BYTES)

        def full_disk(self, data):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(Path, "write_bytes", full_disk)

        with pytest.raises(OSError):
            replace_image(tmp_path, "7", "png", PNG_BYTES)

        assert (tmp_path / "7.jpg").read_bytes() == JPEG_BYTES

    def test_a_failed_write_leaves_no_temporary_file_behind(self, tmp_path, monkeypatch):
        def full_disk(self, data):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(Path, "write_bytes", full_disk)

        with pytest.raises(OSError):
            replace_image(tmp_path, "7", "png", PNG_BYTES)

        assert list(tmp_path.iterdir()) == []

    def test_replacing_the_same_format_keeps_one_file(self, tmp_path):
        replace_image(tmp_path, "7", "png", PNG_BYTES)
        replace_image(tmp_path, "7", "png", PNG_BYTES)
        assert [p.name for p in tmp_path.iterdir()] == ["7.png"]
