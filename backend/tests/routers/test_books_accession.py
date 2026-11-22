"""The accession number through the API: assigning one in bulk, finding a copy by
it, and what a copy, the trash and a restore do to it.

The rules of the code itself are `tests/test_accession.py` and the shared
conformance cases; a merge is `tests/test_folding.py`.
"""

import accession


def assign(client, headers, book_ids):
    return client.post(
        "/api/books/bulk", json={"book_ids": book_ids, "action": "assign_accession"}, headers=headers
    )


def by_accession(client, headers, code):
    return client.get(f"/api/books/accession/{code}", headers=headers)


class TestAssigning:
    def test_an_owned_book_is_numbered_from_its_own_row(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = assign(client, admin["headers"], [book["id"]])

        assert res.json() == {"updated": 1, "unchanged": 0, "skipped": 0}
        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["accession"] == accession.mint(book["id"])

    def test_a_book_starts_with_none(self, client, admin, make_book):
        """Existing and new rows alike read null until somebody asks (owner, 2026-11-22)."""
        assert make_book(admin["headers"])["accession"] is None

    def test_assigning_twice_changes_nothing(self, client, admin, make_book):
        """A peeled label is reprinted with the same number, never renumbered."""
        book = make_book(admin["headers"])
        assign(client, admin["headers"], [book["id"]])

        res = assign(client, admin["headers"], [book["id"]])

        assert res.json() == {"updated": 0, "unchanged": 1, "skipped": 0}

    def test_a_book_the_library_does_not_own_gets_none(self, client, admin, make_book):
        """A label names an object the library holds; a wanted book is not one."""
        wanted = make_book(admin["headers"], ownership="not_owned")

        res = assign(client, admin["headers"], [wanted["id"]])

        assert res.json() == {"updated": 0, "unchanged": 1, "skipped": 0}
        assert client.get(f"/api/books/{wanted['id']}", headers=admin["headers"]).json()["accession"] is None

    def test_another_members_private_book_is_skipped(self, client, admin, member, make_book):
        private = make_book(admin["headers"], is_private=True)

        res = assign(client, member["headers"], [private["id"]])

        assert res.json() == {"updated": 0, "unchanged": 0, "skipped": 1}
        assert client.get(f"/api/books/{private['id']}", headers=admin["headers"]).json()["accession"] is None


class TestFindingACopyByItsLabel:
    def test_a_numbered_copy_is_found(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assign(client, admin["headers"], [book["id"]])

        res = by_accession(client, admin["headers"], accession.mint(book["id"]))

        assert (res.status_code, res.json()["id"]) == (200, book["id"])

    def test_a_valid_code_nobody_carries_is_404(self, client, admin, make_book):
        book = make_book(admin["headers"])

        assert by_accession(client, admin["headers"], accession.mint(book["id"])).status_code == 404

    def test_another_members_private_copy_is_404_not_403(self, client, admin, member, make_book):
        """A 403 would confirm the label exists."""
        private = make_book(admin["headers"], is_private=True)
        assign(client, admin["headers"], [private["id"]])
        code = accession.mint(private["id"])

        assert by_accession(client, admin["headers"], code).status_code == 200
        assert by_accession(client, member["headers"], code).status_code == 404

    def test_a_malformed_code_is_400(self, client, admin):
        """A mistyped check digit says nothing about any Book."""
        assert by_accession(client, admin["headers"], "200047117").status_code == 400

    def test_requires_authentication(self, client):
        assert by_accession(client, {}, accession.mint(1)).status_code == 401


class TestCopyAndTrash:
    def test_a_new_copy_starts_without_one(self, client, admin, make_book):
        """Another object carries another label."""
        book = make_book(admin["headers"])
        assign(client, admin["headers"], [book["id"]])

        copy = client.post(f"/api/books/{book['id']}/copies", json={}, headers=admin["headers"]).json()

        assert copy["accession"] is None

    def test_a_trashed_copy_is_not_found_and_keeps_its_number(self, client, admin, make_book):
        """The unique index covers trashed rows, so a restore can never be refused for it."""
        book = make_book(admin["headers"])
        assign(client, admin["headers"], [book["id"]])
        code = accession.mint(book["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert by_accession(client, admin["headers"], code).status_code == 404

        restored = client.post(f"/api/books/{book['id']}/restore", headers=admin["headers"]).json()
        assert restored["accession"] == code
