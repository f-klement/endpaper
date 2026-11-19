"""Further images of a book: kept, served, removed, shelved, and what the
trash and a merge do with them.

`models.CoverImage` carries the design. These hold the four promises it makes:
the shelf cover's upload bounds bind here too, the book's read rule is the
image's, a swap loses nothing a member kept, and the files follow the rows.
"""

import pytest
from sqlalchemy import delete, text

import cover_store
import covers
import database
import uploads
from models import MAX_COVER_IMAGES_PER_BOOK, Book, CoverImage
from tests.helpers import JPEG_BYTES, NOT_AN_IMAGE, PNG_BYTES, WEBP_BYTES


def _upload(client, account, book_id: int, data: bytes = PNG_BYTES, name: str = "back.png"):
    return client.post(
        f"/api/books/{book_id}/cover-images",
        files={"file": (name, data, "application/octet-stream")},
        headers=account["headers"],
    )


def _images_of(book_id: int) -> str:
    return f"/api/books/{book_id}/cover-images"


def _shelve(client, account, book_id: int, image_id: int):
    return client.put(f"{_images_of(book_id)}/{image_id}/shelf", headers=account["headers"])


def _slot_files(covers_dir) -> set[str]:
    return {path.name for path in covers_dir.iterdir() if path.name.startswith(cover_store.IMAGE_SLOT_PREFIX)}


class TestKeepingAnImage:
    def test_an_upload_is_listed_and_served_behind_the_book(self, client, admin, make_book, covers_dir):
        book = make_book(admin["headers"])

        res = _upload(client, admin, book["id"])

        assert res.status_code == 201, res.text
        [image] = res.json()
        assert image["url"] == f"/covers/{book['id']}/images/{image['id']}.png"
        served = client.get(image["url"], headers=admin["headers"])
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/png"
        assert served.content == PNG_BYTES

    def test_the_shelf_cover_is_left_alone(self, client, admin, make_book, covers_dir):
        book = make_book(admin["headers"])

        _upload(client, admin, book["id"])

        assert client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()["cover_url"] is None

    def test_bytes_that_are_not_an_image_are_refused(self, client, admin, make_book, covers_dir):
        book = make_book(admin["headers"])

        res = _upload(client, admin, book["id"], NOT_AN_IMAGE, "payload.svg")

        assert res.status_code == 400
        assert _slot_files(covers_dir) == set()

    def test_an_image_past_the_upload_cap_is_refused(self, client, admin, make_book, covers_dir, monkeypatch):
        monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", len(PNG_BYTES) - 1)
        book = make_book(admin["headers"])

        res = _upload(client, admin, book["id"])

        assert res.status_code == 413
        assert _slot_files(covers_dir) == set()

    def test_an_upload_past_the_ceiling_is_refused_and_leaves_no_file(
        self, client, admin, make_book, covers_dir
    ):
        book = make_book(admin["headers"])
        for _ in range(MAX_COVER_IMAGES_PER_BOOK):
            assert _upload(client, admin, book["id"]).status_code == 201

        res = _upload(client, admin, book["id"], JPEG_BYTES, "one.jpg")

        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "cover_image_ceiling"
        assert len(_slot_files(covers_dir)) == MAX_COVER_IMAGES_PER_BOOK

    def test_a_removed_image_takes_its_file_with_it(self, client, admin, make_book, covers_dir):
        book = make_book(admin["headers"])
        [image] = _upload(client, admin, book["id"]).json()

        res = client.delete(f"/api/books/{book['id']}/cover-images/{image['id']}", headers=admin["headers"])

        assert res.status_code == 204
        assert client.get(f"/api/books/{book['id']}/cover-images", headers=admin["headers"]).json() == []
        assert _slot_files(covers_dir) == set()


class TestTheBooksReadRuleIsTheImages:
    def test_another_members_private_book_answers_404_everywhere(
        self, client, admin, member, make_book, covers_dir
    ):
        book = make_book(admin["headers"], is_private=True)
        [image] = _upload(client, admin, book["id"]).json()

        assert client.get(_images_of(book["id"]), headers=member["headers"]).status_code == 404
        assert client.get(image["url"], headers=member["headers"]).status_code == 404
        assert _upload(client, member, book["id"]).status_code == 404
        delete = client.delete(f"{_images_of(book['id'])}/{image['id']}", headers=member["headers"])
        assert delete.status_code == 404

    def test_an_image_named_under_another_book_answers_404(self, client, admin, make_book, covers_dir):
        """An image id is a counter too, so a visible book beside another
        book's image id must not serve it."""
        first = make_book(admin["headers"], title="First")
        second = make_book(admin["headers"], title="Second")
        [image] = _upload(client, admin, first["id"]).json()

        res = client.get(f"/covers/{second['id']}/images/{image['id']}.png", headers=admin["headers"])

        assert res.status_code == 404

    def test_the_wrong_extension_answers_404(self, client, admin, make_book, covers_dir):
        book = make_book(admin["headers"])
        [image] = _upload(client, admin, book["id"]).json()

        res = client.get(f"/covers/{book['id']}/images/{image['id']}.jpg", headers=admin["headers"])

        assert res.status_code == 404


class TestShelvingAnImage:
    def test_the_image_becomes_the_cover_and_the_old_cover_takes_its_place(
        self, client, admin, make_book, covers_dir
    ):
        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("front.jpg", JPEG_BYTES, "image/jpeg")},
            headers=admin["headers"],
        )
        [image] = _upload(client, admin, book["id"], WEBP_BYTES, "back.webp").json()

        res = _shelve(client, admin, book["id"], image["id"])

        assert res.status_code == 200, res.text
        assert covers.unversioned(res.json()["cover_url"]) == f"/covers/{book['id']}.webp"
        assert (covers_dir / f"{book['id']}.webp").read_bytes() == WEBP_BYTES
        assert not (covers_dir / f"{book['id']}.jpg").exists()
        [kept] = client.get(f"/api/books/{book['id']}/cover-images", headers=admin["headers"]).json()
        assert kept["id"] != image["id"]
        assert client.get(kept["url"], headers=admin["headers"]).content == JPEG_BYTES
        assert _slot_files(covers_dir) == {f"{cover_store.IMAGE_SLOT_PREFIX}{kept['id']}.jpg"}

    def test_a_book_with_no_stored_cover_keeps_nothing_in_its_place(
        self, client, admin, make_book, covers_dir
    ):
        """A catalogue's link names no bytes, so there is nothing for a slot to
        hold: the refresh asks the catalogue for it again."""
        book = make_book(admin["headers"])
        [image] = _upload(client, admin, book["id"]).json()

        res = _shelve(client, admin, book["id"], image["id"])

        assert res.status_code == 200, res.text
        assert covers.unversioned(res.json()["cover_url"]) == f"/covers/{book['id']}.png"
        assert client.get(f"/api/books/{book['id']}/cover-images", headers=admin["headers"]).json() == []
        assert _slot_files(covers_dir) == set()

    def test_another_books_image_answers_404(self, client, admin, make_book, covers_dir):
        first = make_book(admin["headers"], title="First")
        second = make_book(admin["headers"], title="Second")
        [image] = _upload(client, admin, first["id"]).json()

        res = _shelve(client, admin, second["id"], image["id"])

        assert res.status_code == 404

    def test_a_swap_in_the_same_format_gives_the_cover_a_new_url(self, client, admin, make_book, covers_dir):
        """Both are `<id>.jpg`, so an unchanged URL would leave the old cover
        in a browser's cache for a week. Two swaps, so neither URL compared is
        the upload's."""
        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("front.jpg", JPEG_BYTES, "image/jpeg")},
            headers=admin["headers"],
        )
        [image] = _upload(client, admin, book["id"], JPEG_BYTES + b"back", "back.jpg").json()
        back = _shelve(client, admin, book["id"], image["id"]).json()["cover_url"]
        [front] = client.get(_images_of(book["id"]), headers=admin["headers"]).json()

        shelved = _shelve(client, admin, book["id"], front["id"]).json()["cover_url"]

        assert shelved != back
        assert client.get(shelved, headers=admin["headers"]).content == JPEG_BYTES


def _meanwhile(monkeypatch, change) -> None:
    """Run `change` just before a cover route's lock is granted, standing for
    what another transaction committed while this one waited for it."""

    def change_then_hold(db, book_id):
        change(db, book_id)
        return database.hold_book_ceilings(db, book_id)

    monkeypatch.setattr("routers.books.hold_book_ceilings", change_then_hold)


def _deleted_by_another(db, book_id: int) -> None:
    """Raw SQL, as another transaction's delete would be: an ORM delete in this
    session would also take the book out of the identity map."""
    db.execute(text("DELETE FROM books WHERE id = :book"), {"book": book_id})


class TestASwapReadsTheBookUnderTheLock:
    @pytest.fixture
    def shelved_front(self, client, admin, make_book, covers_dir):
        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("front.jpg", JPEG_BYTES, "image/jpeg")},
            headers=admin["headers"],
        )
        [image] = _upload(client, admin, book["id"], JPEG_BYTES + b"back", "back.jpg").json()
        return book, image

    def test_an_image_another_swap_took_meanwhile_answers_404(
        self, client, admin, covers_dir, monkeypatch, shelved_front
    ):
        """Read before the lock, the image was shelved a second time and the
        delete of its row found nothing to delete."""
        book, image = shelved_front
        _meanwhile(
            monkeypatch, lambda db, _: db.execute(delete(CoverImage).where(CoverImage.id == image["id"]))
        )

        res = _shelve(client, admin, book["id"], image["id"])

        assert res.status_code == 404
        assert (covers_dir / f"{book['id']}.jpg").read_bytes() == JPEG_BYTES

    def test_a_book_a_merge_took_meanwhile_answers_404(
        self, client, admin, covers_dir, monkeypatch, shelved_front
    ):
        book, image = shelved_front
        _meanwhile(monkeypatch, _deleted_by_another)

        res = _shelve(client, admin, book["id"], image["id"])

        assert res.status_code == 404
        assert (covers_dir / f"{book['id']}.jpg").read_bytes() == JPEG_BYTES


class TestAnUploadOnABookAMergeTookMeanwhile:
    """The lock found no row, and the upload went on to write a file named for
    a dead id before its UPDATE or its insert failed as a 500."""

    def test_a_shelf_cover_upload_answers_404_and_writes_no_file(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        book = make_book(admin["headers"])
        _meanwhile(monkeypatch, _deleted_by_another)

        res = client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("front.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )

        assert res.status_code == 404
        assert cover_store.on_disk(book["id"]) == frozenset()

    def test_a_further_image_upload_answers_404_and_writes_no_file(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        book = make_book(admin["headers"])
        _meanwhile(monkeypatch, _deleted_by_another)

        res = _upload(client, admin, book["id"])

        assert res.status_code == 404
        assert _slot_files(covers_dir) == set()


class TestTheFilesFollowTheRows:
    def test_trashing_a_book_keeps_its_images(self, client, admin, make_book, covers_dir):
        """A trashed book can be restored, with everything it had."""
        book = make_book(admin["headers"])
        _upload(client, admin, book["id"])

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert len(_slot_files(covers_dir)) == 1

    def test_purging_a_book_deletes_its_images(self, client, admin, make_book, covers_dir, db):
        book = make_book(admin["headers"])
        _upload(client, admin, book["id"])
        _upload(client, admin, book["id"], JPEG_BYTES, "spine.jpg")

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{book['id']}/permanent", headers=admin["headers"])

        assert _slot_files(covers_dir) == set()
        assert db.query(CoverImage).count() == 0

    def test_a_merge_carries_the_images_to_the_survivor_without_moving_a_file(
        self, client, admin, make_book, covers_dir, db
    ):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        _upload(client, admin, keeper["id"])
        [moved] = _upload(client, admin, loser["id"], JPEG_BYTES, "jacket.jpg").json()
        before = _slot_files(covers_dir)

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert _slot_files(covers_dir) == before
        listed = client.get(f"/api/books/{keeper['id']}/cover-images", headers=admin["headers"]).json()
        assert moved["id"] in {image["id"] for image in listed}
        carried = next(image for image in listed if image["id"] == moved["id"])
        assert client.get(carried["url"], headers=admin["headers"]).content == JPEG_BYTES
        assert db.get(Book, loser["id"]) is None
