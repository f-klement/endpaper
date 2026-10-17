"""KOReader's progress sync, driven the way a device and a member drive it.

The device half is held to the reference server's answers, status and body,
because KOReader acts on both: 401 is the only refusal it does not retry, and a
missing `percentage` is how it learns a document is new. The member half is
the sync password and the link from a document to a Book.
"""

import logging
from datetime import timedelta

import pytest

import kosync
from enums import ReadStatus
from models import TITLE_MAX, KosyncDocument, ReadingProgress, User, UserBook

DIGEST = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"
XPOINTER = "/body/DocFragment[11]/body/div/p[7]/text().123"


def sign_in(client, account) -> dict[str, str]:
    """Mint a sync password for `account` and return the headers a device sends."""
    minted = client.post("/api/kosync/account/password", headers=account["headers"])
    assert minted.status_code == 201, minted.text
    password = minted.json()["password"]
    return {
        "accept": "application/vnd.koreader.v1+json",
        "x-auth-user": account["user"]["username"],
        "x-auth-key": kosync.device_key(password),
    }


def push(client, headers, document=DIGEST, **fields):
    body = {
        "document": document,
        "progress": XPOINTER,
        "percentage": 0.4213,
        "device": "Kobo_clara",
        "device_id": "1A2B3C4D5E6F",
    } | fields
    return client.put("/kosync/syncs/progress", json=body, headers=headers)


def pull(client, device, document=DIGEST):
    return client.get(f"/kosync/syncs/progress/{document}", headers=device)


def file_on(client, account, book_id, digest=DIGEST, root="Books"):
    res = client.post(
        f"/api/books/{book_id}/digital-references",
        json={"root_label": root, "relative_path": f"{digest}.epub", "partial_md5": digest},
        headers=account["headers"],
    )
    assert res.status_code in (200, 201), res.text


UNAUTHORIZED = {"message": "Unauthorized", "code": 2001}


class TestSigningADeviceIn:
    def test_registration_is_refused_as_the_reference_refuses_it(self, client):
        res = client.post("/kosync/users/create", json={"username": "a", "password": "b"})
        assert res.status_code == 402
        assert res.json() == {"message": "User registration is disabled.", "code": 2005}

    def test_the_minted_password_signs_a_device_in(self, client, member):
        res = client.get("/kosync/users/auth", headers=sign_in(client, member))
        assert res.status_code == 200
        assert res.json() == {"authorized": "OK"}

    def test_a_wrong_key_and_an_unknown_member_are_one_answer(self, client, member):
        device = sign_in(client, member)
        wrong = client.get("/kosync/users/auth", headers=device | {"x-auth-key": "0" * 32})
        nobody = client.get("/kosync/users/auth", headers=device | {"x-auth-user": "nobody"})
        assert (wrong.status_code, wrong.json()) == (401, UNAUTHORIZED)
        assert (nobody.status_code, nobody.json()) == (401, UNAUTHORIZED)

    def test_a_member_with_no_sync_password_is_refused(self, client, member):
        empty_key = kosync.device_key("")
        res = client.get(
            "/kosync/users/auth",
            headers={"x-auth-user": member["user"]["username"], "x-auth-key": empty_key},
        )
        assert res.status_code == 401

    def test_the_login_password_does_not_sign_a_device_in(self, client, member):
        res = client.get(
            "/kosync/users/auth",
            headers={
                "x-auth-user": member["user"]["username"],
                "x-auth-key": kosync.device_key(member["password"]),
            },
        )
        assert res.status_code == 401

    def test_minting_again_signs_the_old_password_out(self, client, member):
        old = sign_in(client, member)
        sign_in(client, member)
        assert client.get("/kosync/users/auth", headers=old).status_code == 401

    def test_revoking_signs_every_device_out(self, client, member):
        device = sign_in(client, member)
        client.delete("/api/kosync/account/password", headers=member["headers"])
        assert client.get("/kosync/users/auth", headers=device).status_code == 401

    def test_the_account_says_whether_a_password_is_set_and_never_what_it_is(
        self, client, member
    ):
        sign_in(client, member)
        body = client.get("/api/kosync/account", headers=member["headers"]).json()
        assert body["username"] == member["user"]["username"]
        assert body["has_password"] is True
        assert set(body) == {"username", "has_password", "password_set_at"}

    def test_a_username_outside_ascii_signs_in(self, client, db):
        """KOReader sends the name's UTF-8 bytes and the server decodes headers
        as latin-1, so the name has to be decoded again to match."""
        jurgen = User(username="jürgen")
        db.add(jurgen)
        password = kosync.mint(jurgen)
        db.commit()
        res = client.get(
            "/kosync/users/auth",
            headers={
                "x-auth-user": "jürgen".encode(),
                "x-auth-key": kosync.device_key(password),
            },
        )
        assert res.status_code == 200

    def test_a_refused_sign_in_is_logged_without_the_key(self, client, member, caplog):
        key = "f" * 32
        with caplog.at_level(logging.WARNING, logger="endpaper.kosync"):
            client.get(
                "/kosync/users/auth", headers={"x-auth-user": "nobody", "x-auth-key": key}
            )
        logged = [r.getMessage() for r in caplog.records if r.name == "endpaper.kosync"]
        assert len(logged) == 1
        assert "'nobody'" in logged[0]
        assert key not in logged[0]

    def test_an_admin_signs_a_members_devices_out(self, client, admin, member):
        device = sign_in(client, member)
        res = client.delete(
            f"/api/kosync/members/{member['user']['id']}/password", headers=admin["headers"]
        )
        assert res.status_code == 204
        assert client.get("/kosync/users/auth", headers=device).status_code == 401

    def test_the_admin_revoke_ends_the_members_tokens_too(self, client, admin, member):
        """Under directory auth an issued token stays good for its week, so a
        revoke that left it would let the member mint another password."""
        sign_in(client, member)
        client.delete(
            f"/api/kosync/members/{member['user']['id']}/password", headers=admin["headers"]
        )
        res = client.post("/api/kosync/account/password", headers=member["headers"])
        assert res.status_code == 401

    def test_a_member_cannot_sign_another_members_devices_out(
        self, client, member, other_user
    ):
        res = client.delete(
            f"/api/kosync/members/{other_user['user']['id']}/password",
            headers=member["headers"],
        )
        assert res.status_code == 403

    def test_an_unknown_path_is_a_404_in_the_protocols_envelope(self, client):
        res = client.get("/kosync/users/me", headers={"accept": "*/*"})
        assert res.status_code == 404
        assert set(res.json()) == {"message", "code"}

    def test_a_push_needs_the_device_signed_in(self, client, member):
        res = push(client, {"x-auth-user": member["user"]["username"]})
        assert (res.status_code, res.json()) == (401, UNAUTHORIZED)


class TestAPushAndAPull:
    def test_a_pull_returns_the_push_field_for_field(self, client, member):
        device = sign_in(client, member)
        pushed = push(client, device)
        assert pushed.status_code == 200
        timestamp = pushed.json()["timestamp"]
        assert pushed.json() == {"document": DIGEST, "timestamp": timestamp}
        assert isinstance(timestamp, int)

        assert pull(client, device).json() == {
            "document": DIGEST,
            "progress": XPOINTER,
            "percentage": 0.4213,
            "device": "Kobo_clara",
            "device_id": "1A2B3C4D5E6F",
            "timestamp": timestamp,
        }

    def test_an_unknown_document_is_an_empty_object_and_a_200(self, client, member):
        res = pull(client, sign_in(client, member))
        assert (res.status_code, res.json()) == (200, {})

    def test_a_push_without_a_device_id_is_pulled_without_one(self, client, member):
        device = sign_in(client, member)
        body = {"document": DIGEST, "progress": "56", "percentage": 0.5, "device": "PB"}
        client.put("/kosync/syncs/progress", json=body, headers=device)
        assert "device_id" not in pull(client, device).json()

    def test_the_last_push_wins_even_when_it_is_behind(self, client, member):
        device = sign_in(client, member)
        push(client, device, percentage=0.9)
        push(client, device, percentage=0.2, progress="12")
        assert pull(client, device).json()["percentage"] == 0.2
        assert pull(client, device).json()["progress"] == "12"

    def test_another_members_document_is_not_theirs_to_pull(self, client, member, other_user):
        push(client, sign_in(client, member))
        assert pull(client, sign_in(client, other_user)).json() == {}

    @pytest.mark.parametrize(
        ("change", "code"),
        [
            ({"document": None}, 2004),
            ({"document": "has:colon"}, 2004),
            ({"document": "has-a-hyphen"}, 2007),
            ({"document": "x" * 65}, 2007),
            ({"percentage": "most"}, 2003),
            ({"percentage": None}, 2003),
            ({"device": None}, 2003),
            ({"progress": "p" * 2049}, 2003),
        ],
    )
    def test_a_malformed_push_is_refused_with_the_references_code(
        self, client, member, change, code
    ):
        res = push(client, sign_in(client, member), **change)
        assert (res.status_code, res.json()["code"]) == (403, code)

    @pytest.mark.parametrize(
        ("raw", "code"),
        [(b"{not json", 103), (b"[]", 104), (b"[" * 100_000, 103)],
        ids=["unparseable", "a list", "too deep"],
    )
    def test_a_body_that_is_not_an_object_is_the_references_400(
        self, client, member, raw, code
    ):
        res = client.put(
            "/kosync/syncs/progress",
            content=raw,
            headers=sign_in(client, member) | {"content-type": "application/json"},
        )
        assert (res.status_code, res.json()["code"]) == (400, code)

    def test_a_lone_surrogate_in_the_position_is_an_invalid_request(self, client, member):
        raw = (
            b'{"document": "%s", "progress": "\\ud800", "percentage": 0.5, '
            b'"device": "d"}' % DIGEST.encode()
        )
        res = client.put(
            "/kosync/syncs/progress", content=raw, headers=sign_in(client, member)
        )
        assert (res.status_code, res.json()["code"]) == (403, 2003)

    def test_a_pull_of_an_unroutable_name_is_refused_with_2004(self, client, member):
        res = pull(client, sign_in(client, member), document="has-a-hyphen")
        assert (res.status_code, res.json()["code"]) == (403, 2004)

    def test_metadata_a_later_push_leaves_out_is_kept(self, client, member):
        device = sign_in(client, member)
        push(client, device, metadata={"title": "Dune", "authors": "Herbert"})
        push(client, device)
        inbox = client.get("/api/kosync/inbox", headers=member["headers"]).json()
        assert (inbox[0]["title"], inbox[0]["authors"]) == ("Dune", "Herbert")

    def test_a_nul_in_the_position_is_an_invalid_request(self, client, member):
        res = push(client, sign_in(client, member), progress="a\x00b")
        assert (res.status_code, res.json()["code"]) == (403, 2003)

    def test_a_title_past_the_column_is_cut_to_it(self, client, member, db):
        push(client, sign_in(client, member), metadata={"title": "t" * (TITLE_MAX + 1)})
        assert len(db.query(KosyncDocument).one().title or "") == TITLE_MAX

    def test_two_first_pushes_at_once_leave_one_row(
        self, client, member, db, monkeypatch
    ):
        """The second push looked before the first committed, so it inserts and
        the unique index refuses it: it updates the row that won instead."""
        device = sign_in(client, member)
        push(client, device, percentage=0.2)
        looked = kosync._existing
        missed: list[bool] = []

        def late(*args):
            # The first look misses the row, as a look racing the other
            # push's commit would; every later look sees it.
            if not missed:
                missed.append(True)
                return None
            return looked(*args)

        monkeypatch.setattr(kosync, "_existing", late)
        res = push(client, device, percentage=0.7)
        assert res.status_code == 200
        assert [row.percentage for row in db.query(KosyncDocument)] == [0.7]

    def test_metadata_that_does_not_fit_is_dropped_not_refused(self, client, member):
        res = push(client, sign_in(client, member), metadata={"title": 5, "authors": None})
        assert res.status_code == 200


class TestWhichBookADocumentIs:
    def test_a_fingerprint_on_a_book_the_member_sees_links_it(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"])
        file_on(client, admin, book["id"])
        push(client, sign_in(client, member))
        linked = client.get(
            f"/api/kosync/books/{book['id']}/documents", headers=member["headers"]
        ).json()
        assert [row["document"] for row in linked] == [DIGEST]

    def test_a_fingerprint_on_a_private_book_of_somebody_else_does_not(
        self, client, member, other_user, make_book
    ):
        theirs = make_book(other_user["headers"], is_private=True)
        file_on(client, other_user, theirs["id"])
        push(client, sign_in(client, member))
        inbox = client.get("/api/kosync/inbox", headers=member["headers"]).json()
        assert [row["book_id"] for row in inbox] == [None]

    def test_two_books_holding_the_fingerprint_leave_it_in_the_inbox(
        self, client, admin, member, make_book
    ):
        # The same bytes in two folders: one location is one Book's, so the
        # second copy is at a location of its own.
        for title in ("One", "Two"):
            file_on(client, admin, make_book(admin["headers"], title=title)["id"], root=title)
        push(client, sign_in(client, member))
        inbox = client.get("/api/kosync/inbox", headers=member["headers"]).json()
        assert [row["document"] for row in inbox] == [DIGEST]

    def test_linking_from_the_inbox_is_remembered(self, client, member, make_book):
        book = make_book(member["headers"])
        device = sign_in(client, member)
        push(client, device)
        res = client.put(
            f"/api/kosync/books/{book['id']}/documents/{DIGEST}", headers=member["headers"]
        )
        assert (res.status_code, res.json()["book_id"]) == (200, book["id"])
        push(client, device, percentage=0.5)
        assert client.get("/api/kosync/inbox", headers=member["headers"]).json() == []

    def test_a_book_the_member_cannot_see_cannot_be_linked(
        self, client, member, other_user, make_book
    ):
        theirs = make_book(other_user["headers"], is_private=True)
        push(client, sign_in(client, member))
        res = client.put(
            f"/api/kosync/books/{theirs['id']}/documents/{DIGEST}", headers=member["headers"]
        )
        assert res.status_code == 404

    def test_another_members_document_cannot_be_linked(
        self, client, member, other_user, make_book
    ):
        book = make_book(member["headers"])
        push(client, sign_in(client, other_user))
        res = client.put(
            f"/api/kosync/books/{book['id']}/documents/{DIGEST}", headers=member["headers"]
        )
        assert res.status_code == 404

    def test_an_unlinked_document_stays_in_the_inbox_through_later_pushes(
        self, client, member, make_book, db
    ):
        """The fingerprint links a document when it is first pushed and never
        again, so the member's unlink outlives the device's next push."""
        book = make_book(member["headers"])
        file_on(client, member, book["id"])
        device = sign_in(client, member)
        push(client, device)
        path = f"/api/kosync/books/{book['id']}/documents/{DIGEST}"
        assert client.delete(path, headers=member["headers"]).status_code == 204

        push(client, device, percentage=0.6)

        inbox = client.get("/api/kosync/inbox", headers=member["headers"]).json()
        assert [row["document"] for row in inbox] == [DIGEST]

    def test_purging_the_book_sends_the_document_back_to_the_inbox(
        self, client, member, make_book, db
    ):
        book = make_book(member["headers"])
        push(client, sign_in(client, member))
        client.put(
            f"/api/kosync/books/{book['id']}/documents/{DIGEST}", headers=member["headers"]
        )
        client.delete(f"/api/books/{book['id']}", headers=member["headers"])
        client.delete(f"/api/books/{book['id']}/permanent", headers=member["headers"])
        assert db.query(KosyncDocument).one().book_id is None

    def test_a_merge_carries_the_link_to_the_survivor(self, client, admin, make_book, db):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        push(client, sign_in(client, admin))
        client.put(
            f"/api/kosync/books/{loser['id']}/documents/{DIGEST}", headers=admin["headers"]
        )
        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 200, res.text
        assert db.query(KosyncDocument).one().book_id == keeper["id"]


class TestWhatAPositionDoesToTheReadingRecord:
    """The owner's rulings: a percent row when the whole percent moved, at
    most once a day per Book, and 100 percent marks the Book read."""

    @pytest.fixture
    def linked(self, client, member, make_book):
        book = make_book(member["headers"])
        device = sign_in(client, member)
        push(client, device, percentage=0.1)
        client.put(
            f"/api/kosync/books/{book['id']}/documents/{DIGEST}", headers=member["headers"]
        )
        return book["id"], device

    def rows(self, db, book_id):
        return [
            row.percent
            for row in db.query(ReadingProgress)
            .filter(ReadingProgress.book_id == book_id)
            .order_by(ReadingProgress.id)
        ]

    def status(self, db, book_id):
        db.expire_all()
        row = db.query(UserBook).filter(UserBook.book_id == book_id).one()
        return ReadStatus(row.status)

    def test_linking_logs_the_position_and_starts_the_book(self, linked, db):
        book_id, _ = linked
        assert self.rows(db, book_id) == [10]
        assert self.status(db, book_id) is ReadStatus.READING

    def test_a_second_move_the_same_day_logs_nothing(self, client, linked, db):
        book_id, device = linked
        push(client, device, percentage=0.4)
        assert self.rows(db, book_id) == [10]

    def test_the_next_days_move_is_logged(self, client, linked, db):
        book_id, device = linked
        row = db.query(ReadingProgress).one()
        row.recorded_at = row.recorded_at - timedelta(days=1)
        db.commit()
        push(client, device, percentage=0.4)
        assert self.rows(db, book_id) == [10, 40]

    def test_the_next_day_logs_nothing_when_the_whole_percent_stood_still(
        self, client, linked, db
    ):
        book_id, device = linked
        row = db.query(ReadingProgress).one()
        row.recorded_at = row.recorded_at - timedelta(days=1)
        db.commit()
        push(client, device, percentage=0.1099)
        assert self.rows(db, book_id) == [10]

    def yesterday(self, db):
        """Move the one logged row back a day, so the next move may log."""
        row = db.query(ReadingProgress).one()
        row.recorded_at = row.recorded_at - timedelta(days=1)
        db.commit()

    def test_a_percentage_that_floats_short_of_its_percent_logs_that_percent(
        self, client, linked, db
    ):
        """0.29 * 100 is 28.999999999999996 in binary."""
        book_id, device = linked
        self.yesterday(db)
        push(client, device, percentage=0.29)
        assert self.rows(db, book_id) == [10, 29]

    @pytest.mark.parametrize("percentage", [1.5, -0.1])
    def test_a_percentage_outside_the_book_is_stored_and_logs_nothing(
        self, client, linked, db, percentage
    ):
        book_id, device = linked
        self.yesterday(db)
        assert push(client, device, percentage=percentage).status_code == 200
        assert self.rows(db, book_id) == [10]

    def test_a_book_opened_at_zero_percent_records_nothing(
        self, client, member, make_book, db
    ):
        book = make_book(member["headers"])
        file_on(client, member, book["id"])
        push(client, sign_in(client, member), percentage=0.0)
        assert self.rows(db, book["id"]) == []
        assert db.query(UserBook).count() == 0

    def test_resting_on_the_end_does_not_overrule_the_member(
        self, client, member, linked, db
    ):
        """Only the crossing into 100 marks read: the device pushes 100 on every
        suspend while it sits on the last page."""
        book_id, device = linked
        push(client, device, percentage=1.0)
        client.put(
            f"/api/books/{book_id}/status",
            json={"status": "reading"},
            headers=member["headers"],
        )
        push(client, device, percentage=1.0)
        assert self.status(db, book_id) is ReadStatus.READING

    def test_reaching_the_end_marks_the_book_read(self, client, linked, db):
        book_id, device = linked
        push(client, device, percentage=1.0)
        assert self.status(db, book_id) is ReadStatus.READ

    def test_the_last_percent_short_of_the_end_does_not(self, client, linked, db):
        book_id, device = linked
        push(client, device, percentage=0.9999)
        assert self.status(db, book_id) is ReadStatus.READING

    def test_a_book_finished_before_it_was_linked_is_marked_read_by_the_link(
        self, client, member, make_book, db
    ):
        book = make_book(member["headers"])
        push(client, sign_in(client, member), percentage=1.0)
        client.put(
            f"/api/kosync/books/{book['id']}/documents/{DIGEST}", headers=member["headers"]
        )
        assert self.status(db, book["id"]) is ReadStatus.READ

    def test_a_linked_book_in_the_trash_records_nothing(self, client, member, linked, db):
        book_id, device = linked
        row = db.query(ReadingProgress).one()
        row.recorded_at = row.recorded_at - timedelta(days=1)
        db.commit()
        client.delete(f"/api/books/{book_id}", headers=member["headers"])
        push(client, device, percentage=0.5)
        assert self.rows(db, book_id) == [10]
