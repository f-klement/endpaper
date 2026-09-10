"""Tests for backend/uploads.py: content-based image validation.

The filename used to decide the format, and a filename is caller-controlled.
Anything at all could be stored as `12.png` and then served back from this
app's own origin.
"""

import ast
import pathlib
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

import uploads
from config import ALLOWED_IMAGE_EXTENSIONS, MAX_UPLOAD_BYTES
from tests.helpers import JPEG_BYTES, NOT_AN_IMAGE, PNG_BYTES, WEBP_BYTES
from uploads import (
    SNIFF_BYTES,
    read_image_upload,
    replace_image,
    sniff_image_extension,
)


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

    def test_two_threads_writing_one_book_do_not_share_a_scratch_name(
        self, tmp_path, monkeypatch
    ):
        """The pid used to be the whole of the uniqueness, which was true while
        the only concurrency here was separate processes.

        The cover backfill fans out across a ThreadPoolExecutor **inside one
        process**, so two overlapping writes of the same book built an identical
        temp path: one `os.replace` won and the other failed ENOENT. The barrier
        below holds both threads between the write and the replace, so the two
        temporary files must coexist, which is exactly the case the pid alone
        could not survive.
        """
        import os
        import threading

        both_written = threading.Barrier(2, timeout=10)
        scratch: list[str] = []
        real_replace = os.replace

        def replace_once_both_have_written(source, target):
            scratch.append(str(source))
            both_written.wait()
            return real_replace(source, target)

        # Patched by name: `uploads.os` is the same module object, and mypy
        # refuses an attribute access through a module that does not re-export.
        monkeypatch.setattr("uploads.os.replace", replace_once_both_have_written)

        failures: list[BaseException] = []

        def write(payload: bytes) -> None:
            try:
                replace_image(tmp_path, "7", "png", payload)
            except BaseException as error:  # noqa: BLE001
                failures.append(error)

        threads = [
            threading.Thread(target=write, args=(PNG_BYTES + bytes([n]),))
            for n in (1, 2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert failures == []
        assert len(set(scratch)) == 2, scratch
        assert (tmp_path / "7.png").read_bytes() in (
            PNG_BYTES + bytes([1]),
            PNG_BYTES + bytes([2]),
        )

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


#: One body per format the app accepts, keyed by what the sniffer answers for
#: it. **Tied to `ALLOWED_IMAGE_EXTENSIONS` by a test below** rather than left as
#: a hand written list: an enumeration is what goes stale when the app grows a
#: format, and a window guard parametrised over a stale list is a guard that has
#: stopped guarding without ever failing.
SNIFFABLE: dict[str, bytes] = {
    "jpg": JPEG_BYTES,
    "jpeg": JPEG_BYTES,
    "png": PNG_BYTES,
    "webp": WEBP_BYTES,
}


class TestTheSnifferAnswersOnlyWhatTheAppServes:
    def test_every_extension_the_sniffer_can_return_is_one_the_app_serves(self):
        """Read off the source, not off a list kept beside it.

        `read_image_upload` stores whatever this returns without checking it
        against the allowlist, and the cover route refuses any extension outside
        that allowlist, so an arm added here for a format the app does not serve
        stores a file nothing can ever fetch. An `ast` pass rather than calling
        it with samples, because a sample list cannot see an arm nobody wrote a
        sample for.
        """
        source = ast.parse(pathlib.Path(uploads.__file__).read_text())
        function = next(
            node
            for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef)
            and node.name == "sniff_image_extension"
        )
        returned = {
            node.value.value
            for node in ast.walk(function)
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }

        assert returned <= set(ALLOWED_IMAGE_EXTENSIONS)
        assert returned, "the ast pass found no returned literal, so it is not reading it"

        # **The shape, not only the values.** The pass above can only read a
        # `return "literal"`, so an arm returning a name, an f-string or a
        # lookup is invisible to it: `returned` stays correct, both assertions
        # above pass, and the format the guard exists to catch walks straight
        # through. This is what a guard enumerating statement kinds needs to say
        # out loud rather than a further arm reading one more kind.
        unreadable = [
            ast.dump(node)
            for node in ast.walk(function)
            if isinstance(node, ast.Return)
            and not (
                node.value is None
                or (
                    isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str | None)
                )
            )
        ]
        assert not unreadable, (
            "sniff_image_extension returns something this pass cannot read, so it "
            f"is no longer checking what it claims to: {unreadable}"
        )

    def test_a_sample_exists_for_every_format_the_app_accepts(self):
        """What makes the window guard below hold for a format added later."""
        assert set(SNIFFABLE) == set(ALLOWED_IMAGE_EXTENSIONS)


class TestTheSniffWindow:
    """`SNIFF_BYTES` is what a caller reading from a stream may look at.

    It exists so `backup.restore` declines an archive entry on a header instead
    of on its declared `file_size`. It is derived from the magic numbers rather
    than written as a number, so these check the derivation rather than a
    literal: a window narrower than the sniffer reads makes the stream caller
    decline a file the upload path accepts, which costs a cover.
    """

    @pytest.mark.parametrize("extension", sorted(SNIFFABLE))
    def test_the_window_decides_every_format_the_app_accepts(self, extension):
        """Truncated to the window, each format still sniffs to itself."""
        body = SNIFFABLE[extension]
        whole = sniff_image_extension(body)

        assert whole is not None
        assert sniff_image_extension(body[:SNIFF_BYTES]) == whole

    def test_the_window_is_no_wider_than_it_needs_to_be(self):
        """One byte short of the window must break at least one format.

        Without this the derivation passes for any width large enough, including
        one carrying a term nobody trimmed after a magic number got shorter, and
        the constant stops describing the sniffer.
        """
        one_short = SNIFF_BYTES - 1
        answers = [
            sniff_image_extension(body[:one_short]) for body in SNIFFABLE.values()
        ]

        assert None in answers

    def test_a_body_shorter_than_the_window_is_still_decided(self):
        """A short read is what a stream returns at the end of a file, so the
        sniffer must not depend on getting the whole window."""
        assert sniff_image_extension(JPEG_BYTES[:3]) == "jpg"
        assert sniff_image_extension(b"") is None
        assert sniff_image_extension(NOT_AN_IMAGE[:SNIFF_BYTES]) is None
