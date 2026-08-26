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
from authors import author_key
from backup import RestoreError
from database import Base, SessionLocal
from models import AuthorAlias, Book, Loan, Note, Quote, Tag, UserBook


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
    client.post(
        f"/api/books/{book['id']}/progress",
        json={"page": 64, "minutes": 30},
        headers=admin["headers"],
    )
    client.post(
        f"/api/books/{book['id']}/quotes",
        json={"text": "Fear is the mind-killer", "page": 214},
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
        """Derived from the metadata, never from a list written by hand.

        **This test was named "every table" and asserted a hand-written subset
        with `<=`.** `author_aliases` was in neither the archive nor the list,
        for as long as the author feature existed, and the symptom was silent:
        a restore produced a library where every merged author had split back
        into its spellings while the books themselves were perfectly intact,
        because a merge never writes to `books`. Nothing errored, and
        `docs/data-model.md` called it "the one stored table in the feature"
        the whole time.

        Equality rather than a subset, so a table added to the schema and
        forgotten here fails, and so does a manifest key naming a table that no
        longer exists.
        """
        data = client.get("/api/backup", headers=admin["headers"]).content
        tables = set(read_manifest(data)["tables"])

        assert tables == set(Base.metadata.tables), (
            "the archive and the schema disagree about which tables exist: "
            f"missing {sorted(set(Base.metadata.tables) - tables)}, "
            f"unexpected {sorted(tables - set(Base.metadata.tables))}"
        )

    def test_holds_the_book_tag_links(self, client, admin, library):
        """No model of its own, so it is the one that gets forgotten.

        Forgetting it loses every book's tags while looking like a complete
        backup.
        """
        data = client.get("/api/backup", headers=admin["headers"]).content
        assert read_manifest(data)["tables"]["book_tags"]

    def test_holds_the_author_merge_decisions(self, client, admin, library):
        """The one stored table in the author feature, and the one that was
        missing. A merge writes no `books` row, so losing these rows loses the
        decision with nothing else looking wrong."""
        client.post(
            "/api/books/authors/merge",
            json={"keys": [author_key("Frank Herbert")], "keep_name": "F. Herbert"},
            headers=admin["headers"],
        )
        data = client.get("/api/backup", headers=admin["headers"]).content

        aliases = read_manifest(data)["tables"]["author_aliases"]
        assert [row["canonical_name"] for row in aliases] == ["F. Herbert"]

    def test_holds_the_cover_files(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content
        names = zipfile.ZipFile(BytesIO(data)).namelist()
        assert f"covers/{library['book']['id']}.jpg" in names

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

    def test_the_author_merges_come_back(self, client, admin, library, db):
        """The bug this table was added for, end to end.

        A merge writes no `books` row, so when the alias table was left out of
        the archive a restore came back looking correct in every visible way
        and quietly split every merged author into its spellings again.
        """
        client.post(
            "/api/books/authors/merge",
            json={"keys": [author_key("Frank Herbert")], "keep_name": "F. Herbert"},
            headers=admin["headers"],
        )
        data = client.get("/api/backup", headers=admin["headers"]).content

        for alias in db.query(AuthorAlias).all():
            db.delete(alias)
        db.commit()
        assert db.query(AuthorAlias).count() == 0

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert res.json()["author_aliases"] == 1
        restored = db.query(AuthorAlias).one()
        assert restored.canonical_name == "F. Herbert"

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

    def test_the_quotes_come_back(self, client, admin, library, db):
        """With their page numbers. A quote is typed by hand and exists nowhere
        else, which is exactly the class of thing a backup is for."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        db.query(Quote).delete()
        db.commit()

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        db.expire_all()
        assert [(q.text, q.page) for q in db.query(Quote).all()] == [
            ("Fear is the mind-killer", 214)
        ]

    def test_an_archive_from_before_quotes_existed_still_restores(
        self, client, admin, library
    ):
        """`quotes` is deliberately absent from `_REQUIRED_TABLES`. Adding a
        table to that set would refuse every backup the library already
        holds, which is the trap the set exists to have escaped once."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        del manifest["tables"]["quotes"]

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["quotes"] == 0

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

    def test_the_login_background_comes_back_too(
        self, client, admin, library, covers_dir
    ):
        """It lives in the same directory and belongs to no book. Losing it on a
        restore would leave the one screen every visitor sees looking wrong."""
        from tests.helpers import PNG_BYTES

        client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        data = client.get("/api/backup", headers=admin["headers"]).content
        for image in covers_dir.glob("login_bg.*"):
            image.unlink()

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert list(covers_dir.glob("login_bg.*"))

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

    Refusing it would make every schema change throw away the library's
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

    def test_a_tag_the_library_invented_stays_deletable(
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


class TestRestoringPreHttpsCovers:
    """A restore inserts through Core, so the ORM validator never fires.

    Demonstrated before it was fixed: the ORM path stored `https://` and the
    Core insert stored `http://` from the same value. Restoring an archive
    taken before this release therefore put every blocked cover back, after
    the one-shot migration had just cleaned them, with nothing saying so.
    """

    def restore_with_cover(
        self, client, admin, library, cover: str | None
    ) -> str | None:
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        for row in manifest["tables"]["books"]:
            row["cover_url"] = cover

        response = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.text

        session = SessionLocal()
        try:
            restored = session.query(Book).first()
            assert restored is not None
            return restored.cover_url
        finally:
            session.close()

    def test_an_http_cover_in_the_archive_is_upgraded(self, client, admin, library):
        assert (
            self.restore_with_cover(
                client, admin, library, "http://books.google.com/c.jpg"
            )
            == "https://books.google.com/c.jpg"
        )

    def test_an_uploaded_cover_path_is_left_alone(self, client, admin, library):
        assert (
            self.restore_with_cover(client, admin, library, "/covers/1.jpg")
            == "/covers/1.jpg"
        )

    def test_a_book_with_no_cover_restores_without_one(self, client, admin, library):
        assert self.restore_with_cover(client, admin, library, None) is None

    @pytest.mark.parametrize(
        "cover",
        [
            "javascript:alert(1)",
            "data:image/svg+xml,<svg/>",
            "//evil.invalid/x.jpg",
            "/api/books/export",
            "/covers/../api/books/export",
        ],
    )
    def test_a_cover_no_image_tag_should_load_is_dropped(
        self, client, admin, library, cover
    ):
        """An archive is admin-supplied, and an admin is not a reason to trust
        a file: it may have come from another deployment or been edited by
        hand. A Core insert fires no validator, so the restore path has to
        repeat the acceptance rule as well as the scheme upgrade.
        """
        assert self.restore_with_cover(client, admin, library, cover) is None

    def test_a_dropped_cover_does_not_fail_the_restore(
        self, client, admin, library, db
    ):
        """One odd cover is not a reason to lose the rest of the library."""
        self.restore_with_cover(client, admin, library, "javascript:alert(1)")

        db.expire_all()
        assert db.query(Book).count() > 0


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


class TestCollectionsSurvive:
    """Added after `FORMAT_VERSION` 1, so an archive predating them restores as
    a library with none rather than being refused."""

    def test_a_round_trip_returns_the_collection_and_its_books(
        self, client, admin, library, db
    ):
        from models import Collection

        shelf = client.post(
            "/api/collections", json={"name": "Ebooks"}, headers=admin["headers"]
        ).json()
        client.patch(
            f"/api/books/{library['book']['id']}/collection",
            json={"collection_id": shelf["id"]},
            headers=admin["headers"],
        )
        data = client.get("/api/backup", headers=admin["headers"]).content

        client.delete(f"/api/collections/{shelf['id']}", headers=admin["headers"])
        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert [row.name for row in db.query(Collection).all()] == ["Ebooks"]
        assert db.get(Book, library["book"]["id"]).collection_id is not None

    def test_the_report_counts_them(self, client, admin, library):
        """A **non-zero** assertion, deliberately. The sibling test below asks
        for 0 from an archive that has none, and it passed identically whether
        or not the handler wired the field up at all: `RestoreResult.collections`
        defaults to 0, so the endpoint reported a clean restore while dropping
        every shelf label. Only a count that has to arrive can catch that.
        """
        client.post("/api/collections", json={"name": "Ebooks"}, headers=admin["headers"])
        client.post("/api/collections", json={"name": "Sold"}, headers=admin["headers"])
        data = client.get("/api/backup", headers=admin["headers"]).content

        body = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        ).json()

        assert body["collections"] == 2

    def test_an_archive_written_before_collections_existed_still_restores(
        self, client, admin, library
    ):
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        del manifest["tables"]["collections"]
        for row in manifest["tables"]["books"]:
            row.pop("collection_id", None)

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["collections"] == 0


class TestTheRestoreReportCannotSilentlyDropATable:
    """The report says a number for every field it declares, and each of those
    numbers has to have been counted.

    The handler builds the result from `RestoreResult.model_fields`, which stops
    a counted table being dropped on the way out. It does **not** stop the
    mirror image: `restored.get(name, 0)` defaults a field the restore never
    counts to 0, and a 0 that was never measured is indistinguishable from a
    table that restored empty. That is the original bug's exact shape, in the
    other direction, and `collections` reported exactly that 0 for a while.

    So the subset is asserted rather than the wiring. Adding a field to the
    schema without teaching `restore()` to count it fails here.
    """

    def test_every_reported_field_is_actually_counted(self, client, admin, library, db):
        from schemas import RestoreResult

        data = client.get("/api/backup", headers=admin["headers"]).content

        counted = backup.restore(db, data)

        missing = set(RestoreResult.model_fields) - set(counted)
        assert not missing, (
            f"RestoreResult declares {sorted(missing)}, which `backup.restore()` never "
            "counts, so the endpoint reports 0 for them whatever the archive held."
        )


class TestReadingProgressSurvives:
    """The newest table in the archive, and the one an older archive lacks."""

    def test_a_round_trip_returns_the_entries(self, client, admin, library, db):
        from models import ReadingProgress

        data = client.get("/api/backup", headers=admin["headers"]).content
        db.query(ReadingProgress).delete()
        db.commit()

        client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        )

        assert [row.page for row in db.query(ReadingProgress).all()] == [64]

    def test_the_report_counts_them(self, client, admin, library):
        data = client.get("/api/backup", headers=admin["headers"]).content
        body = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", data, "application/zip")},
            headers=admin["headers"],
        ).json()

        assert body["reading_progress"] == 1
        assert body["user_books"] >= 1

    def test_an_archive_written_before_the_table_existed_still_restores(
        self, client, admin, library
    ):
        """`FORMAT_VERSION` promises an older archive stays restorable. Making
        every entry in `_TABLES` mandatory would have refused every backup the
        library already holds the moment a table was added.
        """
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        del manifest["tables"]["reading_progress"]

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["reading_progress"] == 0

    def test_a_missing_baseline_table_is_still_refused(self, client, admin, library):
        """The optional-table rule must not turn the guard off."""
        data = client.get("/api/backup", headers=admin["headers"]).content
        manifest = read_manifest(data)
        del manifest["tables"]["books"]

        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            files={"file": ("backup.zip", rewrite(data, manifest), "application/zip")},
            headers=admin["headers"],
        )

        assert res.status_code == 400
        assert "books" in res.json()["detail"]
