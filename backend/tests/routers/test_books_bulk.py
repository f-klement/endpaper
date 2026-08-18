"""One verb applied to a selection of books.

Six verbs behind one endpoint, because they share the same three steps: resolve
what the caller may actually touch, apply, and report updated/unchanged/skipped.
The three-way count is the part worth pinning: reporting a flat success would
claim work that did not happen.
"""

import pytest


def bulk(client, headers, book_ids, action, value=None):
    payload: dict = {"book_ids": book_ids, "action": action}
    if value is not None:
        payload["value"] = value
    return client.post("/api/books/bulk", json=payload, headers=headers)


@pytest.fixture
def fiction_id(client, admin) -> int:
    tags = client.get("/api/books/tags", headers=admin["headers"]).json()
    return next(t["id"] for t in tags if t["name"] == "Fiction")


class TestTagging:
    def test_tags_several_books(self, client, admin, make_book, fiction_id):
        first = make_book(admin["headers"], title="A")
        second = make_book(admin["headers"], title="B")

        res = bulk(client, admin["headers"], [first["id"], second["id"]], "add_tag", fiction_id)

        assert res.json() == {"updated": 2, "unchanged": 0, "skipped": 0}

    def test_a_book_that_already_has_it_is_unchanged(
        self, client, admin, make_book, fiction_id
    ):
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{fiction_id}", headers=admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], "add_tag", fiction_id)

        assert res.json()["unchanged"] == 1
        assert res.json()["updated"] == 0

    def test_removes_a_tag(self, client, admin, make_book, fiction_id):
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{fiction_id}", headers=admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], "remove_tag", fiction_id)

        assert res.json()["updated"] == 1
        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["tags"] == []

    def test_removing_a_tag_the_book_lacks_is_unchanged(
        self, client, admin, make_book, fiction_id
    ):
        book = make_book(admin["headers"])
        res = bulk(client, admin["headers"], [book["id"]], "remove_tag", fiction_id)
        assert res.json()["unchanged"] == 1

    def test_an_unknown_tag_is_a_404(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert bulk(client, admin["headers"], [book["id"]], "add_tag", 9999).status_code == 404

    def test_a_missing_tag_id_is_a_422(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert bulk(client, admin["headers"], [book["id"]], "add_tag").status_code == 422


class TestStatus:
    def test_marks_several_as_read(self, client, admin, make_book):
        first = make_book(admin["headers"], title="A")
        second = make_book(admin["headers"], title="B")

        res = bulk(client, admin["headers"], [first["id"], second["id"]], "set_status", "read")

        assert res.json()["updated"] == 2

    def test_stamps_the_dates_like_the_single_book_route(self, client, admin, make_book):
        """A bulk "mark read" must produce the same dates as doing it one at a
        time would, or the two paths disagree about history."""
        book = make_book(admin["headers"])

        bulk(client, admin["headers"], [book["id"]], "set_status", "read")

        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["my_finished_at"] is not None
        assert detail["my_started_at"] is not None

    def test_a_book_already_in_that_status_is_unchanged(self, client, admin, make_book):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        res = bulk(client, admin["headers"], [book["id"]], "set_status", "read")

        assert res.json()["unchanged"] == 1

    def test_the_status_is_personal(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        bulk(client, admin["headers"], [book["id"]], "set_status", "read")

        seen_by_member = client.get(f"/api/books/{book['id']}", headers=member["headers"])

        assert seen_by_member.json()["my_status"] == "unread"

    def test_an_unknown_status_is_a_422(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = bulk(client, admin["headers"], [book["id"]], "set_status", "devoured")
        assert res.status_code == 422


class TestOwnershipAndLocation:
    def test_sets_ownership(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], "set_ownership", "not_owned")

        assert res.json()["updated"] == 1
        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["ownership"] == "not_owned"

    def test_an_unknown_ownership_is_a_422(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = bulk(client, admin["headers"], [book["id"]], "set_ownership", "borrowed")
        assert res.status_code == 422

    def test_sets_a_location(self, client, admin, make_book):
        """The reason this verb exists: unpacking a box of books at once."""
        first = make_book(admin["headers"], title="A")
        second = make_book(admin["headers"], title="B")

        res = bulk(
            client, admin["headers"], [first["id"], second["id"]], "set_location", "Loft box 2"
        )

        assert res.json()["updated"] == 2
        detail = client.get(f"/api/books/{first['id']}", headers=admin["headers"]).json()
        assert detail["location"] == "Loft box 2"

    def test_an_empty_location_clears_it(self, client, admin, make_book):
        book = make_book(admin["headers"])
        bulk(client, admin["headers"], [book["id"]], "set_location", "Loft")

        bulk(client, admin["headers"], [book["id"]], "set_location", "")

        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["location"] is None

    def test_the_same_location_twice_is_unchanged(self, client, admin, make_book):
        book = make_book(admin["headers"])
        bulk(client, admin["headers"], [book["id"]], "set_location", "Loft")

        res = bulk(client, admin["headers"], [book["id"]], "set_location", "Loft")

        assert res.json()["unchanged"] == 1


class TestDelete:
    def test_removes_the_selection(self, client, admin, make_book):
        first = make_book(admin["headers"], title="A")
        second = make_book(admin["headers"], title="B")

        res = bulk(client, admin["headers"], [first["id"], second["id"]], "delete")

        assert res.json()["updated"] == 2
        assert client.get("/api/books", headers=admin["headers"]).json()["total"] == 0

    def test_another_members_private_book_survives(self, client, admin, member, make_book):
        private = make_book(admin["headers"], is_private=True)

        res = bulk(client, member["headers"], [private["id"]], "delete")

        assert res.json() == {"updated": 0, "unchanged": 0, "skipped": 1}
        assert client.get(f"/api/books/{private['id']}", headers=admin["headers"]).status_code == 200


class TestPermissionsAndCounts:
    def test_an_unknown_id_is_skipped_not_an_error(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = bulk(client, admin["headers"], [book["id"], 9999], "set_ownership", "owned")

        assert res.json()["skipped"] == 1

    def test_skipped_does_not_distinguish_absent_from_forbidden(
        self, client, admin, member, make_book
    ):
        """Reporting which of the two it was would disclose that a private book
        with that id exists."""
        private = make_book(admin["headers"], is_private=True)

        absent = bulk(client, member["headers"], [9999], "set_ownership", "owned").json()
        forbidden = bulk(client, member["headers"], [private["id"]], "set_ownership", "owned").json()

        assert absent == forbidden

    def test_any_member_may_act_on_a_public_book(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        res = bulk(client, member["headers"], [book["id"]], "set_ownership", "not_owned")
        assert res.json()["updated"] == 1

    def test_an_empty_selection_is_rejected(self, client, admin):
        assert bulk(client, admin["headers"], [], "delete").status_code == 422

    def test_too_many_ids_are_rejected(self, client, admin):
        assert bulk(client, admin["headers"], list(range(1, 502)), "delete").status_code == 422

    def test_an_unknown_action_is_rejected(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert bulk(client, admin["headers"], [book["id"]], "incinerate").status_code == 422

    def test_requires_authentication(self, client):
        assert client.post("/api/books/bulk", json={"book_ids": [1], "action": "delete"}).status_code == 401

    def test_the_path_is_not_read_as_a_book_id(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = bulk(client, admin["headers"], [book["id"]], "set_ownership", "owned")
        assert res.status_code == 200
