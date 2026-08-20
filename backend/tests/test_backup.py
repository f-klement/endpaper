"""Tests for backend/backup.py.

The CSV export was never a backup: it dropped the notes, the loans, every
member's reading status, the accounts and every cover. So the first thing to
pin is that a round trip actually returns the library, and the second is that a
bad archive changes nothing.

The archive is a zip, and a zip is a security question as much as a container
format: an entry may name any path it likes, including one outside the
directory being written to.
"""

import json
import zipfile
from io import BytesIO

import pytest

import backup
from backup import RestoreError
from models import Book, Loan, Note, Tag, UserBook


def read_manifest(data: bytes) -> dict:
    return json.loads(zipfile.ZipFile(BytesIO(data)).read(backup.MANIFEST_NAME))


def rewrite(data: bytes, manifest: dict, covers: dict[str, bytes] | None = None) -> bytes:
    """A new archive with the given manifest, keeping the covers."""
    source = zipfile.ZipFile(BytesIO(data))
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(backup.MANIFEST_NAME, json.dumps(manifest))
        for entry in source.namelist():
            if entry != backup.MANIFEST_NAME:
                archive.writestr(entry, source.read(entry))
        for name, body in (covers or {}).items():
            archive.writestr(name, body)
    return buffer.getvalue()


@pytest.fixture
def library(client, admin, member, make_book, db, covers_dir):
    """A library with something in every table, so a round trip can be checked."""
    from tests.helpers import JPEG_BYTES

    book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
    private = make_book(member["headers"], title="Secret", is_private=True)

    client.put(
        f"/api/books/{book['id']}/status",
        json={"status": "read"},
        headers=admin["headers"],
    )
    client.post(
        f"/api/books/{book['id']}/notes",
        json={"content": "Lent to Ana"},
        headers=admin["headers"],
    )
    client.post(
        "/api/loans",
        json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
        headers=admin["headers"],
    )
    tag = db.query(Tag).first()
    client.post(f"/api/books/{book['id']}/tags/{tag.id}", headers=admin["headers"])
    client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("c.jpg", JPEG_BYTES, "image/jpeg")},
        headers=admin["headers"],
    )
    return {"book": book, "private": private, "tag_id": tag.id}



def _sign_in(client, account) -> dict[str, str]:
    """Authorization header for a session opened now.

    A restore invalidates every token issued before it, so a test that acts
    afterwards has to sign in again rather than reuse the fixture's header.
    """
    res = client.post(
        "/auth/login",
        json={"username": account["user"]["username"], "password": account["password"]},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


class TestTheArchive:
    def test_holds_every_table(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content
        tables = read_manifest(data)["tables"]

        assert {"users", "tags", "books", "user_books", "loans", "notes",
                "settings", "book_tags"} <= set(tables)

    def test_holds_the_book_tag_links(self, client, admin, library):
        """No model of its own, so it is the one that gets forgotten.

        Forgetting it loses every book's tags while looking like a complete
        backup.
        """
        data = client.get("/api/backup", headers=admin["headers"]).content
        assert read_manifest(data)["tables"]["book_tags"]

    def test_holds_the_cover_files(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content
        names = zipfile.ZipFile(BytesIO(data)).namelist()
        assert any(name.startswith("covers/") for name in names)

    def test_holds_another_members_private_book(self, client, admin, library):
        """A backup is not filtered by visibility.

        Omitting the private books of everyone but the admin taking it would
        restore to a library missing rows, which is the one thing a backup must
        never do. That is why it is admin only.
        """
        data = client.get("/api/backup", headers=admin["headers"]).content
        titles = {book["title"] for book in read_manifest(data)["tables"]["books"]}
        assert "Secret" in titles

    def test_is_admin_only(self, client, member, library):
        assert client.get("/api/backup", headers=member["headers"]).status_code == 403

    def test_requires_authentication(self, client):
        assert client.get("/api/backup").status_code == 401

    def test_is_offered_as_a_download(self, client, admin, library):
        res = client.get("/api/backup", headers=admin["headers"])
        assert res.headers["content-type"] == "application/zip"
        assert "attachment" in res.headers["content-disposition"]


class TestRoundTrip:
    def test_the_library_comes_back(self, client, admin, library, db):
        data = client.get("/api/backup", headers=admin["headers"]).content
        client.delete("/api/books/trash", headers=admin["headers"])
        # Per object, not a bulk delete: books carry tag associations, and now
        # that foreign keys are enforced a bulk DELETE leaves them dangling and
        # is refused. Going through the ORM clears the association rows first.
        for book in db.query(Book).all():
            db.delete(book)
        db.commit()

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["books"] == 2

    def test_the_notes_come_back(self, client, admin, library, db):
        data = client.get("/api/backup", headers=admin["headers"]).content
        db.query(Note).delete()
        db.commit()

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        assert [note.content for note in db.query(Note).all()] == ["Lent to Ana"]

    def test_the_reading_statuses_come_back(self, client, admin, library, db):
        data = client.get("/api/backup", headers=admin["headers"]).content
        db.query(UserBook).delete()
        db.commit()

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        assert db.query(UserBook).count() == 1

    def test_the_loans_come_back(self, client, admin, library, db):
        data = client.get("/api/backup", headers=admin["headers"]).content
        db.query(Loan).delete()
        db.commit()

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        assert db.query(Loan).count() == 1

    def test_the_tags_on_a_book_come_back(self, client, admin, library, db):
        data = client.get("/api/backup", headers=admin["headers"]).content

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        # A restore ends every pre-restore session, so ask again as somebody
        # signed in afterwards. See TestRestoreEndsLiveSessions.
        book = client.get(
            f"/api/books/{library['book']['id']}", headers=_sign_in(client, admin)
        ).json()
        assert [tag["id"] for tag in book["tags"]] == [library["tag_id"]]

    def test_the_covers_come_back(self, client, admin, library, covers_dir):
        data = client.get("/api/backup", headers=admin["headers"]).content
        for cover in covers_dir.glob("*.jpg"):
            cover.unlink()

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert res.json()["covers"] == 1
        assert list(covers_dir.glob("*.jpg"))

    def test_restoring_replaces_rather_than_merges(self, client, admin, library, db):
        """Merging produces a library neither the backup nor the original."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        client.post(
            "/api/books",
            json={"title": "Added after the backup"},
            headers=admin["headers"],
        )

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        titles = {book.title for book in db.query(Book).all()}
        assert "Added after the backup" not in titles


class TestRefusingABadArchive:
    def test_a_file_that_is_not_a_zip(self, client, admin):
        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("notes.txt", b"hello", "text/plain")},
            headers=admin["headers"],
        )
        assert res.status_code == 400
        assert "not an Endpaper backup" in res.json()["detail"]

    def test_a_zip_with_no_manifest(self, client, admin):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("something.txt", "hello")

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", buffer.getvalue(), "application/zip")},
            headers=admin["headers"],
        )
        assert res.status_code == 400

    def test_a_format_from_another_version(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        manifest["format_version"] = 99

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )
        assert res.status_code == 400
        assert "format 99" in res.json()["detail"]

    def test_an_archive_with_no_accounts(self, client, admin, library):
        """It would restore to a library nobody can sign in to."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        manifest["tables"]["users"] = []

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )
        assert res.status_code == 400
        assert "no accounts" in res.json()["detail"]

    def test_a_missing_table(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        del manifest["tables"]["loans"]

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )
        assert res.status_code == 400
        assert "loans" in res.json()["detail"]

    def test_nothing_is_destroyed_by_a_refused_archive(
        self, client, admin, library, db
    ):
        """Every check runs before the first row is deleted.

        A restore that fails halfway leaves a library that is neither the
        backup nor what was there before, which is worse than either.
        """
        before = db.query(Book).count()

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("notes.txt", b"not a zip", "text/plain")},
            headers=admin["headers"],
        )

        db.expire_all()
        assert db.query(Book).count() == before


class TestTheConfirmation:
    def test_it_refuses_without_confirm(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content

        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 400
        assert "replaces every book" in res.json()["detail"]

    def test_it_changes_nothing_without_confirm(self, client, admin, library, db):
        data = client.get("/api/backup", headers=admin["headers"]).content
        client.post(
            "/api/books", json={"title": "Later"}, headers=admin["headers"]
        )

        client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        assert {book.title for book in db.query(Book).all()} >= {"Later"}

    def test_restoring_is_admin_only(self, client, member, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=member["headers"],
        )

        assert res.status_code == 403


class TestZipSafety:
    """A zip entry may name any path it likes, including one outside ours."""

    @pytest.mark.parametrize(
        "entry",
        [
            "covers/../../escaped.jpg",
            "covers/nested/deep.jpg",
            "covers/",
            "elsewhere/1.jpg",
        ],
    )
    def test_a_cover_path_outside_the_directory_is_ignored(self, entry):
        assert backup._safe_cover_name(entry) is None

    def test_an_ordinary_cover_is_accepted(self):
        assert backup._safe_cover_name("covers/12.jpg") == "12.jpg"

    @pytest.mark.parametrize("entry", ["covers/1.exe", "covers/1.svg", "covers/1"])
    def test_a_file_that_is_not_an_image_is_ignored(self, entry):
        # An SVG is an image and also a script host, which is why it is not on
        # the list anywhere else in this app either.
        assert backup._safe_cover_name(entry) is None

    def test_a_traversing_entry_writes_nothing_outside_the_covers_directory(
        self, client, admin, library, covers_dir, tmp_path
    ):
        data = client.get("/api/backup", headers=admin["headers"]).content
        escaped = tmp_path / "escaped.jpg"
        hostile = rewrite(
            data,
            read_manifest(data),
            covers={f"covers/../../{escaped.name}": b"pwned"},
        )

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", hostile, "application/zip")},
            headers=admin["headers"],
        )

        assert not escaped.exists()
        assert not (covers_dir.parent / "escaped.jpg").exists()


class TestReadManifest:
    def test_it_returns_the_manifest_of_a_good_archive(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = backup.read_manifest(data)
        assert manifest["format_version"] == backup.FORMAT_VERSION

    def test_it_raises_rather_than_returning_none(self):
        with pytest.raises(RestoreError):
            backup.read_manifest(b"not a zip at all")


class TestRestoringAnOlderArchive:
    """A backup taken before a migration must still restore.

    Refusing it would make every schema change throw away the household's
    backups, so a column the archive does not carry takes its database
    default. One default lies, and that one is repaired explicitly.
    """

    def test_a_tag_column_the_archive_predates_is_repaired(
        self, client, admin, library, db
    ):
        from models import Tag

        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        # As an archive written before `is_predefined` existed.
        for row in manifest["tables"]["tags"]:
            row.pop("is_predefined", None)

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        fiction = db.query(Tag).filter(Tag.name == "Fiction").one()
        assert fiction.is_predefined is True

    def test_a_tag_the_household_invented_stays_deletable(
        self, client, admin, library, db
    ):
        """The repair must not adopt every restored tag as a built-in one."""
        from models import Tag

        client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        )
        data = client.get("/api/backup", headers=admin["headers"]).content

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        invented = db.query(Tag).filter(Tag.name == "Holiday reads").one()
        assert invented.is_predefined is False


class TestADecompressionBomb:
    """The upload cap bounds the compressed size, and zip compresses.

    Measured: a 1.38 MB archive with a padded manifest and one enormous cover
    entry drove peak memory to 1.8 GB, against a pod limited to 512Mi. That is
    an OOMKill from a file that passes every other check.
    """

    def _bomb(self, manifest: dict, padding: int) -> bytes:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(backup.MANIFEST_NAME, json.dumps(manifest))
            # Zeroes compress to almost nothing and expand to all of it.
            archive.writestr("covers/1.jpg", b"\0" * padding)
        return buffer.getvalue()

    def test_an_archive_that_expands_too_far_is_refused(
        self, client, admin, library
    ):
        data = client.get("/api/backup", headers=admin["headers"]).content
        bomb = self._bomb(read_manifest(data), backup.MAX_UNCOMPRESSED_BYTES + 1)

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", bomb, "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 400
        assert "expands" in res.json()["detail"]

    def test_an_absurd_compression_ratio_is_refused(self, client, admin, library):
        """A real backup of JSON and JPEGs does not compress a hundredfold."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        bomb = self._bomb(read_manifest(data), 50 * 1024 * 1024)

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", bomb, "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 400

    def test_it_is_refused_before_anything_is_read(self, client, admin, library, db):
        """Reading is what costs the memory, so the check precedes it."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        before = db.query(Book).count()
        bomb = self._bomb(read_manifest(data), backup.MAX_UNCOMPRESSED_BYTES + 1)

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", bomb, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        assert db.query(Book).count() == before

    def test_an_ordinary_backup_is_not_mistaken_for_one(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 200


class TestRestoreEndsLiveSessions:
    """A restore replaces the users table wholesale, so the id a live token
    names may afterwards belong to somebody else."""

    def test_a_token_issued_before_the_restore_stops_working(
        self, client, admin, library
    ):
        data = client.get("/api/backup", headers=admin["headers"]).content
        assert client.get("/auth/me", headers=admin["headers"]).status_code == 200

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert client.get("/auth/me", headers=admin["headers"]).status_code == 401

    def test_signing_in_again_works(self, client, admin, library):
        """Ending the session must not end the account."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert client.get("/auth/me", headers=_sign_in(client, admin)).status_code == 200

    def test_the_archives_own_epoch_does_not_win(self, client, admin, library):
        """The settings table is part of the backup, so a restore writes an old
        epoch back. The bump has to land after that, or a pre-restore token
        starts verifying again."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        for _ in range(2):
            client.post(
                "/api/backup/restore",
                params={"confirm": True},
                files={"file": ("backup.zip", data, "application/zip")},
                headers=admin["headers"],
            )
        assert client.get("/auth/me", headers=admin["headers"]).status_code == 401
