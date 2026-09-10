"""A note's own visibility, over the four note routes.

`tests/routers/test_books.py::TestNotes` holds the rest of the notes API,
which is unchanged: a note written through the app is shared, and this file is
about the one an import writes. The rows are made through the ORM rather than
through the API on purpose: `NoteCreate` deliberately carries no `is_private`,
so there is no request that produces one and a fixture that pretended otherwise
would be testing an endpoint this app does not have.
"""

import pytest

from models import Note


@pytest.fixture
def private_note(db, member):
    """A private note the `member` account wrote, on whichever book is passed."""

    def _write(book_id: int, content: str = "what I actually thought") -> Note:
        note = Note(
            book_id=book_id,
            user_id=member["user"]["id"],
            content=content,
            is_private=True,
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        return note

    return _write


class TestAPrivateNoteIsNotListed:
    def test_its_author_sees_it(self, client, member, make_book, private_note):
        book = make_book(member["headers"])
        private_note(book["id"])
        listed = client.get(f"/api/books/{book['id']}/notes", headers=member["headers"]).json()
        assert [n["content"] for n in listed] == ["what I actually thought"]

    def test_another_member_does_not(
        self, client, member, other_user, make_book, private_note
    ):
        """The defect this column was added for: a book anybody may read, and a
        note on it that only its author may."""
        book = make_book(member["headers"])
        private_note(book["id"])
        listed = client.get(
            f"/api/books/{book['id']}/notes", headers=other_user["headers"]
        ).json()
        assert listed == []

    def test_an_admin_does_not_either(self, client, admin, member, make_book, private_note):
        """An admin moderates what other members read. Nobody reads this one,
        so there is nothing to moderate, and an admin arm here would make this
        the one route where admin bypasses a visibility predicate."""
        book = make_book(admin["headers"])
        private_note(book["id"])
        listed = client.get(f"/api/books/{book['id']}/notes", headers=admin["headers"]).json()
        assert listed == []

    def test_a_shared_note_beside_it_is_still_listed(
        self, client, admin, member, make_book, private_note
    ):
        """The half that would go quiet if the predicate matched nothing."""
        book = make_book(admin["headers"])
        private_note(book["id"])
        client.post(
            f"/api/books/{book['id']}/notes",
            json={"content": "everyone can read this"},
            headers=member["headers"],
        )
        listed = client.get(f"/api/books/{book['id']}/notes", headers=admin["headers"]).json()
        assert [n["content"] for n in listed] == ["everyone can read this"]

    def test_the_listing_says_which_of_the_caller_s_notes_are_private(
        self, client, member, make_book, private_note
    ):
        book = make_book(member["headers"])
        private_note(book["id"])
        client.post(
            f"/api/books/{book['id']}/notes",
            json={"content": "shared"},
            headers=member["headers"],
        )
        listed = client.get(f"/api/books/{book['id']}/notes", headers=member["headers"]).json()
        assert {n["content"]: n["is_private"] for n in listed} == {
            "what I actually thought": True,
            "shared": False,
        }

    def test_a_note_written_through_the_app_is_shared(self, client, member, make_book):
        created = client.post(
            f"/api/books/{make_book(member['headers'])['id']}/notes",
            json={"content": "typed"},
            headers=member["headers"],
        ).json()
        assert created["is_private"] is False


class TestAPrivateNoteIsFourOhFourAndNotFourOhThree:
    """A 403 confirms that the row exists, which is exactly what the privacy
    withholds. `dependencies._not_found` states the same rule for a book."""

    def test_a_plain_member_editing_it_gets_404_where_a_shared_note_gives_403(
        self, client, member, other_user, make_book, private_note
    ):
        """**The arm that tells the two codes apart**, and the reason it is a
        plain member rather than an admin: an admin overrides the authorship
        check, so on a note they can read they get 200, and a test using one
        cannot distinguish 404 from 403. This caller is refused either way, so
        which refusal arrives is the whole assertion. Its pair is
        `test_a_shared_note_somebody_else_wrote_is_still_403`, the same caller
        against a note they can see."""
        book = make_book(member["headers"])
        note = private_note(book["id"])
        res = client.put(
            f"/api/books/{book['id']}/notes/{note.id}",
            json={"content": "hijacked"},
            headers=other_user["headers"],
        )
        assert res.status_code == 404

    def test_an_admin_editing_it_gets_404(
        self, client, admin, member, make_book, private_note
    ):
        """The admin arm stops at the visibility: without it this is a 200, not
        a 403, because an admin overrides the authorship check."""
        book = make_book(admin["headers"])
        note = private_note(book["id"])
        res = client.put(
            f"/api/books/{book['id']}/notes/{note.id}",
            json={"content": "hijacked"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_an_admin_deleting_it_gets_404(
        self, client, admin, member, make_book, private_note
    ):
        book = make_book(admin["headers"])
        note = private_note(book["id"])
        res = client.delete(
            f"/api/books/{book['id']}/notes/{note.id}", headers=admin["headers"]
        )
        assert res.status_code == 404

    def test_a_plain_member_deleting_it_gets_404(
        self, client, member, other_user, make_book, private_note
    ):
        book = make_book(member["headers"])
        note = private_note(book["id"])
        res = client.delete(
            f"/api/books/{book['id']}/notes/{note.id}", headers=other_user["headers"]
        )
        assert res.status_code == 404

    def test_a_shared_note_somebody_else_wrote_is_still_403(
        self, client, admin, member, other_user, make_book
    ):
        """The 404 is scoped to the visibility and does not swallow the
        authorship rule: a shared note's existence is not a secret, only who
        may change it is. A plain member rather than an admin, who overrides
        the authorship check and answers 200 here."""
        book = make_book(admin["headers"])
        note = client.post(
            f"/api/books/{book['id']}/notes", json={"content": "shared"}, headers=member["headers"]
        ).json()
        res = client.put(
            f"/api/books/{book['id']}/notes/{note['id']}",
            json={"content": "hijacked"},
            headers=other_user["headers"],
        )
        assert res.status_code == 403

    def test_its_author_can_still_edit_and_delete_it(
        self, client, member, make_book, private_note
    ):
        book = make_book(member["headers"])
        note = private_note(book["id"])
        edited = client.put(
            f"/api/books/{book['id']}/notes/{note.id}",
            json={"content": "revised"},
            headers=member["headers"],
        )
        assert edited.status_code == 200
        assert (edited.json()["content"], edited.json()["is_private"]) == ("revised", True)
        assert (
            client.delete(
                f"/api/books/{book['id']}/notes/{note.id}", headers=member["headers"]
            ).status_code
            == 204
        )

    def test_editing_it_does_not_un_private_it(self, client, member, make_book, private_note):
        """`NoteCreate` carries no `is_private`, so an edit must leave the flag
        where it is rather than take a payload's silence for a false."""
        book = make_book(member["headers"])
        note = private_note(book["id"])
        client.put(
            f"/api/books/{book['id']}/notes/{note.id}",
            json={"content": "revised"},
            headers=member["headers"],
        )
        listed = client.get(f"/api/books/{book['id']}/notes", headers=member["headers"]).json()
        assert [n["is_private"] for n in listed] == [True]
