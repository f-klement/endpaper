"""Highlights imported from a KOReader sidecar: who reads them, and re-running.

The import is reached as the browser reaches it, after the Book's file
reference carries the sidecar's fingerprint.
"""

from models import QUOTE_TEXT_MAX, DeletedHighlight, Highlight

DIGEST = "0123456789abcdef0123456789abcdef"
OTHER_DIGEST = "fedcba9876543210fedcba9876543210"
START = "/body/DocFragment[3]/body/p[2]/text().0"
END = "/body/DocFragment[3]/body/p[2]/text().41"


def holding(client, headers, book_id, digest=DIGEST, path="Dune.epub"):
    res = client.post(
        f"/api/books/{book_id}/digital-references",
        json={"root_label": "Books", "relative_path": path, "partial_md5": digest},
        headers=headers,
    )
    assert res.status_code in (200, 201), res.text


def mark(**fields):
    return {
        "pos0": START,
        "pos1": END,
        "text": "Fear is the mind-killer.",
        "chapter": "Book One",
        "page": 12,
        "highlighted_at": "2026-03-01 22:15:09",
    } | fields


def send(client, headers, book_id, *marks, digest=DIGEST):
    return client.post(
        f"/api/books/{book_id}/highlights/koreader",
        json={"partial_md5": digest, "highlights": list(marks or [mark()])},
        headers=headers,
    )


def listed(client, headers, book_id):
    res = client.get(f"/api/books/{book_id}/highlights", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def delete(client, headers, book_id, highlight_id):
    return client.delete(f"/api/books/{book_id}/highlights/{highlight_id}", headers=headers)


def share(client, headers, book_id, highlight_id, is_shared=True):
    return client.put(
        f"/api/books/{book_id}/highlights/{highlight_id}/sharing",
        json={"is_shared": is_shared},
        headers=headers,
    )


class TestAnImportRunsAgainSafely:
    def test_the_same_sidecar_twice_writes_nothing_the_second_time(
        self, client, member, make_book, db
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])

        assert send(client, member["headers"], book["id"]).json() == {
            "created": 1, "updated": 0, "unchanged": 0, "left_deleted": 0,
        }
        assert send(client, member["headers"], book["id"]).json() == {
            "created": 0, "updated": 0, "unchanged": 1, "left_deleted": 0,
        }
        assert db.query(Highlight).count() == 1

    def test_a_note_added_on_the_device_updates_the_row(self, client, member, make_book):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])

        res = send(client, member["headers"], book["id"], mark(note="the litany"))

        assert res.json() == {"created": 0, "updated": 1, "unchanged": 0, "left_deleted": 0}
        assert [h["note"] for h in listed(client, member["headers"], book["id"])] == [
            "the litany"
        ]

    def test_the_same_position_in_another_file_is_another_highlight(
        self, client, member, make_book
    ):
        """Positions are only meaningful inside one file, so the fingerprint is
        part of the key; without it two books' first marks would be one row."""
        dune = make_book(member["headers"], title="Dune")
        emma = make_book(member["headers"], title="Emma")
        holding(client, member["headers"], dune["id"])
        holding(client, member["headers"], emma["id"], OTHER_DIGEST, "Emma.epub")

        send(client, member["headers"], dune["id"])
        res = send(client, member["headers"], emma["id"], digest=OTHER_DIGEST)

        assert res.json()["created"] == 1
        assert len(listed(client, member["headers"], dune["id"])) == 1

    def test_a_reimport_keeps_the_member_s_sharing(self, client, member, make_book):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])
        share(client, member["headers"], book["id"], highlight["id"])

        send(client, member["headers"], book["id"], mark(note="edited"))

        assert listed(client, member["headers"], book["id"])[0]["is_shared"] is True


class TestAnAdjustedMarkKeepsItsRow:
    def test_new_ends_on_the_same_mark_update_it(self, client, member, make_book, db):
        """KOReader rewrites a mark's ends when it is adjusted and keeps its
        creation time, so the time is the key and the move is an update."""
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])

        res = send(
            client,
            member["headers"],
            book["id"],
            mark(
                pos1="/body/DocFragment[3]/body/p[3]/text().7",
                text="Fear is the mind-killer. Fear",
            ),
        )

        assert res.json() == {"created": 0, "updated": 1, "unchanged": 0, "left_deleted": 0}
        assert db.query(Highlight).count() == 1

    def test_two_marks_made_in_one_second_stay_two(self, client, member, make_book):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])

        res = send(
            client,
            member["headers"],
            book["id"],
            mark(),
            mark(pos0="/body/p[9]/text().0", pos1="/body/p[9]/text().5", text="other"),
        )

        assert res.json()["created"] == 2


class TestASidecarLandsOnlyWhereItsFingerprintMatched:
    def test_a_book_without_that_file_refuses_it(self, client, member, make_book):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"], OTHER_DIGEST)

        res = send(client, member["headers"], book["id"])

        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "not_held"


class TestAnImportOntoAnotherBookTakesTheShareBack:
    """Sharing chose one Book's readers; a move to another Book does not
    carry that choice to readers its author never picked."""

    def _shared_on(self, client, member, book_id):
        holding(client, member["headers"], book_id)
        send(client, member["headers"], book_id)
        [highlight] = listed(client, member["headers"], book_id)
        assert share(client, member["headers"], book_id, highlight["id"]).status_code == 200

    def test_from_a_trashed_book(self, client, member, other_user, make_book):
        first = make_book(member["headers"])
        self._shared_on(client, member, first["id"])
        client.delete(f"/api/books/{first['id']}", headers=member["headers"])
        second = make_book(other_user["headers"])
        holding(client, other_user["headers"], second["id"])

        send(client, member["headers"], second["id"])

        assert listed(client, other_user["headers"], second["id"]) == []

    def test_from_a_private_book_to_a_public_one(
        self, client, member, other_user, make_book
    ):
        first = make_book(member["headers"], is_private=True)
        self._shared_on(client, member, first["id"])
        second = make_book(other_user["headers"])
        holding(client, other_user["headers"], second["id"])

        send(client, member["headers"], second["id"])

        assert listed(client, other_user["headers"], second["id"]) == []
        [moved] = listed(client, member["headers"], second["id"])
        assert moved["is_shared"] is False


class TestAHighlightIsPrivateUntilShared:
    def test_another_member_does_not_see_an_imported_one(
        self, client, member, other_user, make_book
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])

        assert listed(client, other_user["headers"], book["id"]) == []
        assert len(listed(client, member["headers"], book["id"])) == 1

    def test_sharing_shows_it_to_whoever_sees_the_book(
        self, client, member, other_user, make_book
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])

        assert share(client, member["headers"], book["id"], highlight["id"]).status_code == 200

        assert [h["id"] for h in listed(client, other_user["headers"], book["id"])] == [
            highlight["id"]
        ]

    def test_unsharing_withdraws_it(self, client, member, other_user, make_book):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])
        share(client, member["headers"], book["id"], highlight["id"])

        share(client, member["headers"], book["id"], highlight["id"], is_shared=False)

        assert listed(client, other_user["headers"], book["id"]) == []

    def test_a_shared_one_on_a_private_book_stays_hidden(
        self, client, member, other_user, make_book
    ):
        """The book rule comes first: a private Book hides its shared marks."""
        book = make_book(member["headers"], is_private=True)
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])
        share(client, member["headers"], book["id"], highlight["id"])

        res = client.get(f"/api/books/{book['id']}/highlights", headers=other_user["headers"])

        assert res.status_code == 404


class TestWhatTheImportRefuses:
    def test_a_nul_in_the_passage(self, client, member, make_book):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])

        res = send(client, member["headers"], book["id"], mark(text="a\x00b"))

        assert res.status_code == 422

    def test_a_book_the_caller_cannot_see(self, client, member, other_user, make_book):
        book = make_book(other_user["headers"], is_private=True)
        holding(client, other_user["headers"], book["id"])

        assert send(client, member["headers"], book["id"]).status_code == 404


class TestOnlyTheAuthorShares:
    def test_another_member_s_private_highlight_is_not_found(
        self, client, member, other_user, make_book
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])

        assert share(client, other_user["headers"], book["id"], highlight["id"]).status_code == 404

    def test_another_member_s_shared_highlight_is_forbidden(
        self, client, member, other_user, make_book
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])
        share(client, member["headers"], book["id"], highlight["id"])

        res = share(client, other_user["headers"], book["id"], highlight["id"], False)

        assert res.status_code == 403

    def test_a_passage_longer_than_a_quote_stays_private(self, client, member, make_book):
        """Stored whole so the import refuses nothing; shown to the shelf only
        within the ceiling a quote has."""
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"], mark(text="x" * (QUOTE_TEXT_MAX + 1)))
        [highlight] = listed(client, member["headers"], book["id"])

        res = share(client, member["headers"], book["id"], highlight["id"])

        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "too_long_to_share"


class TestNoAdminArm:
    def test_an_admin_does_not_read_a_private_highlight(
        self, client, admin, member, make_book
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])

        assert listed(client, admin["headers"], book["id"]) == []


class TestTheDeviceClock:
    def test_the_time_comes_back_as_given_with_no_zone(self, client, member, make_book):
        """KOReader records no zone, so no offset is invented on the way out."""
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])

        [highlight] = listed(client, member["headers"], book["id"])

        assert highlight["highlighted_at"] == "2026-03-01 22:15:09"


class TestAMerge:
    def test_moves_highlights_to_the_survivor(self, client, admin, make_book, db):
        keeper = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        loser = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        holding(client, admin["headers"], loser["id"])
        send(client, admin["headers"], loser["id"])

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert db.query(Highlight).one().book_id == keeper["id"]

    def test_takes_the_share_back_on_the_survivor(
        self, client, member, other_user, make_book
    ):
        """A merge changes a highlight's Book, so it is private again: the
        survivor's readers are not the audience its author chose."""
        keeper = make_book(member["headers"], title="Dune", author="Frank Herbert")
        loser = make_book(member["headers"], title="Dune", author="Frank Herbert")
        holding(client, member["headers"], loser["id"])
        send(client, member["headers"], loser["id"])
        [highlight] = listed(client, member["headers"], loser["id"])
        share(client, member["headers"], loser["id"], highlight["id"])

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=member["headers"],
        )

        assert res.status_code == 200
        assert listed(client, other_user["headers"], keeper["id"]) == []


class TestAPairMadeInOneSecond:
    def test_deleting_one_leaves_the_other_its_row(self, client, member, make_book, db):
        """The pair is keyed on time and position; alone, the survivor is keyed
        on its time, and finds the row it had rather than adding one."""
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        other = mark(pos0="/body/p[9]/text().0", pos1="/body/p[9]/text().5", text="other")
        send(client, member["headers"], book["id"], mark(), other)

        res = send(client, member["headers"], book["id"], mark())

        assert res.json() == {"created": 0, "updated": 0, "unchanged": 1, "left_deleted": 0}
        assert db.query(Highlight).count() == 2


class TestAMemberDeletesTheirOwn:
    def test_a_deleted_highlight_leaves_the_book(self, client, member, make_book):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])

        assert delete(client, member["headers"], book["id"], highlight["id"]).status_code == 204

        assert listed(client, member["headers"], book["id"]) == []

    def test_a_reimport_still_carrying_it_leaves_it_deleted(
        self, client, member, make_book, db
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])
        delete(client, member["headers"], book["id"], highlight["id"])

        res = send(client, member["headers"], book["id"], mark(note="edited on the device"))

        assert res.json() == {"created": 0, "updated": 0, "unchanged": 0, "left_deleted": 1}
        assert db.query(Highlight).count() == 0

    def test_the_survivor_of_a_pair_deleted_here_stays_deleted_once_alone(
        self, client, member, make_book, db
    ):
        """Deleted under the time and position key a pair has; alone in its
        second it is keyed on its time, and the old key still holds it."""
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        other = mark(pos0="/body/p[9]/text().0", pos1="/body/p[9]/text().5", text="other")
        send(client, member["headers"], book["id"], mark(), other)
        [first] = [
            h for h in listed(client, member["headers"], book["id"]) if h["text"] != "other"
        ]
        delete(client, member["headers"], book["id"], first["id"])

        res = send(client, member["headers"], book["id"], mark())

        assert res.json()["left_deleted"] == 1
        assert [h.text for h in db.query(Highlight)] == ["other"]

    def test_another_member_importing_the_same_mark_keeps_theirs(
        self, client, member, other_user, make_book
    ):
        """The key is remembered per member: one member's deletion is nothing
        to another's import of the same file."""
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        send(client, other_user["headers"], book["id"])
        [mine] = listed(client, member["headers"], book["id"])
        delete(client, member["headers"], book["id"], mine["id"])

        res = send(client, other_user["headers"], book["id"])

        assert res.json()["unchanged"] == 1
        assert len(listed(client, other_user["headers"], book["id"])) == 1

    def test_a_shared_highlight_of_another_member_is_not_found_and_stays(
        self, client, member, other_user, make_book
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])
        share(client, member["headers"], book["id"], highlight["id"])

        res = delete(client, other_user["headers"], book["id"], highlight["id"])

        assert res.status_code == 404
        assert [h["id"] for h in listed(client, other_user["headers"], book["id"])] == [
            highlight["id"]
        ]

    def test_an_admin_cannot_delete_a_member_s_highlight(
        self, client, admin, member, make_book, db
    ):
        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])
        share(client, member["headers"], book["id"], highlight["id"])

        assert delete(client, admin["headers"], book["id"], highlight["id"]).status_code == 404
        assert db.query(DeletedHighlight).count() == 0

    def test_through_another_book_it_is_not_found(self, client, member, make_book):
        book = make_book(member["headers"])
        elsewhere = make_book(member["headers"], title="Emma")
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [highlight] = listed(client, member["headers"], book["id"])

        assert delete(client, member["headers"], elsewhere["id"], highlight["id"]).status_code == 404
        assert len(listed(client, member["headers"], book["id"])) == 1

    def test_on_a_book_the_caller_cannot_see_it_is_not_found(
        self, client, member, other_user, make_book
    ):
        book = make_book(other_user["headers"], is_private=True)
        holding(client, other_user["headers"], book["id"])
        send(client, other_user["headers"], book["id"])
        [highlight] = listed(client, other_user["headers"], book["id"])

        assert delete(client, member["headers"], book["id"], highlight["id"]).status_code == 404


class TestTheDeleteRefusalSaysNothing:
    def test_another_member_s_highlight_an_absent_id_and_a_hidden_book_answer_alike(
        self, client, member, other_user, make_book
    ):
        """The same body and the same statements for another member's private
        highlight and an absent id, so neither the answer nor its cost says the
        highlight exists. A hidden book stops at the book rule, with that
        rule's own 404 and one statement sooner, which says only what every
        route on that book already says."""
        from sqlalchemy import event

        from database import engine

        book = make_book(member["headers"])
        holding(client, member["headers"], book["id"])
        send(client, member["headers"], book["id"])
        [theirs] = listed(client, member["headers"], book["id"])
        hidden = make_book(member["headers"], is_private=True, title="Emma")

        def refused(book_id, highlight_id):
            statements: list[str] = []

            def record(conn, cursor, statement, *rest):
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                res = delete(client, other_user["headers"], book_id, highlight_id)
            finally:
                event.remove(engine, "before_cursor_execute", record)
            return res.status_code, res.json(), len(statements)

        another = refused(book["id"], theirs["id"])
        absent = refused(book["id"], theirs["id"] + 1000)
        on_hidden = refused(hidden["id"], theirs["id"])

        assert another == absent
        assert another[:2] == (404, {"detail": "Highlight not found"})
        assert on_hidden[:2] == (404, {"detail": "Book not found"})
        assert on_hidden[2] == another[2] - 1
