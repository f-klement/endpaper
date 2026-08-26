"""Tests for the tag endpoints on backend/routers/books.py.

The curated vocabulary was the whole vocabulary: type, genre and age, seeded at
boot, and no way past it. Jelu and Openreads both make every tag free-form
instead, and neither is right on its own. The curated list is what makes the
picker useful before anybody has typed anything; what was missing was a
library being able to add "Holiday reads" to it.

So the thing worth pinning is the boundary between the two: a seeded tag cannot
be deleted, because `seed_tags()` would put it straight back and the delete
would look like it silently failed.
"""

from models import Tag


class TestCreating:
    def test_a_member_can_invent_one(self, client, member):
        """Not admin-only. A vocabulary only an admin can extend is one nobody
        uses, and public books are a shared shelf anyone may curate."""
        res = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=member["headers"]
        )

        assert res.status_code == 201
        assert res.json()["name"] == "Holiday reads"

    def test_a_non_ascii_duplicate_returns_the_existing_tag(self, client, admin):
        """This answered **500** until 2026-08-26.

        The lookup folded with SQLite's `lower()` and compared against Python's,
        and those are different functions: `lower('Ästhetik')` is `'Ästhetik'`
        in SQLite and `'ästhetik'` here. So the tag was never found, and the
        insert hit the binary unique index on `tags.name` with a name already
        there. See `docs/decisions.md`, "SQLite folds case in ASCII and Python
        does not".
        """
        first = client.post(
            "/api/books/tags", json={"name": "Ästhetik"}, headers=admin["headers"]
        )
        assert first.status_code == 201

        again = client.post(
            "/api/books/tags", json={"name": "Ästhetik"}, headers=admin["headers"]
        )

        assert again.status_code == 201
        assert again.json()["id"] == first.json()["id"]

    def test_a_non_ascii_name_differing_only_in_case_is_the_same_tag(self, client, admin):
        """The other half of the same fold. Without it "Ästhetik" and
        "ästhetik" both exist, which is the promise this route makes broken
        quietly rather than loudly."""
        first = client.post(
            "/api/books/tags", json={"name": "Ästhetik"}, headers=admin["headers"]
        )

        lower = client.post(
            "/api/books/tags", json={"name": "ästhetik"}, headers=admin["headers"]
        )

        assert lower.status_code == 201
        assert lower.json()["id"] == first.json()["id"]

    def test_it_lands_in_the_custom_group(self, client, admin):
        res = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        )
        assert res.json()["category"] == "custom"
        assert res.json()["is_predefined"] is False

    def test_it_appears_in_the_list(self, client, admin):
        client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        )

        names = {
            tag["name"]
            for tag in client.get("/api/books/tags", headers=admin["headers"]).json()
        }
        assert "Holiday reads" in names

    def test_a_name_already_taken_returns_that_tag(self, client, admin, db):
        """Somebody typing a name that exists wants that tag.

        An error would send them to find it by hand, which is worse than the
        thing they were trying to avoid.
        """
        first = client.post(
            "/api/books/tags", json={"name": "Cookbooks"}, headers=admin["headers"]
        ).json()
        second = client.post(
            "/api/books/tags", json={"name": "cookbooks"}, headers=admin["headers"]
        ).json()

        assert first["id"] == second["id"]
        assert db.query(Tag).filter(Tag.name.ilike("cookbooks")).count() == 1

    def test_it_cannot_shadow_a_seeded_tag(self, client, admin, db):
        res = client.post(
            "/api/books/tags", json={"name": "fantasy"}, headers=admin["headers"]
        )

        assert res.json()["category"] == "genre"
        assert db.query(Tag).filter(Tag.name.ilike("fantasy")).count() == 1

    def test_whitespace_is_collapsed(self, client, admin):
        """A name of only spaces renders as a tag nobody can see or find again."""
        res = client.post(
            "/api/books/tags", json={"name": "  Holiday   reads  "}, headers=admin["headers"]
        )
        assert res.json()["name"] == "Holiday reads"

    def test_a_name_of_only_spaces_is_refused(self, client, admin):
        res = client.post(
            "/api/books/tags", json={"name": "   "}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_an_empty_name_is_refused(self, client, admin):
        res = client.post("/api/books/tags", json={"name": ""}, headers=admin["headers"])
        assert res.status_code == 422

    def test_requires_authentication(self, client):
        assert client.post("/api/books/tags", json={"name": "X"}).status_code == 401


class TestDeleting:
    def _custom(self, client, headers, name: str = "Holiday reads") -> dict:
        return client.post(
            "/api/books/tags", json={"name": name}, headers=headers
        ).json()

    def test_a_tag_the_library_invented(self, client, admin, db):
        tag = self._custom(client, admin["headers"])

        res = client.delete(f"/api/books/tags/{tag['id']}", headers=admin["headers"])

        assert res.status_code == 204
        assert db.get(Tag, tag["id"]) is None

    def test_it_comes_off_every_book_carrying_it(self, client, admin, make_book):
        tag = self._custom(client, admin["headers"])
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"])

        client.delete(f"/api/books/tags/{tag['id']}", headers=admin["headers"])

        after = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert after["tags"] == []

    def test_a_seeded_tag_is_refused(self, client, admin, db):
        """`seed_tags()` would put it back at the next restart, so a delete
        that appeared to work would quietly undo itself."""
        seeded = db.query(Tag).filter(Tag.is_predefined.is_(True)).first()

        res = client.delete(f"/api/books/tags/{seeded.id}", headers=admin["headers"])

        assert res.status_code == 400
        assert "built-in" in res.json()["detail"]
        assert db.get(Tag, seeded.id) is not None

    def test_an_unknown_tag_is_404(self, client, admin):
        assert (
            client.delete("/api/books/tags/9999", headers=admin["headers"]).status_code
            == 404
        )

    def test_tags_is_not_read_as_a_book_id(self, client, admin):
        """Declared before `/{book_id}`, which would otherwise claim the word."""
        assert (
            client.get("/api/books/tags", headers=admin["headers"]).status_code == 200
        )


class TestSeeding:
    def test_a_restart_leaves_an_invented_tag_alone(self, client, admin, db):
        """Without the flag, seeding would either delete these or adopt them."""
        import main

        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()

        main.seed_tags()

        db.expire_all()
        stored = db.get(Tag, tag["id"])
        assert stored is not None
        assert stored.is_predefined is False

    def test_the_seeded_tags_are_marked_as_such(self, client, admin):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        fiction = next(tag for tag in tags if tag["name"] == "Fiction")
        assert fiction["is_predefined"] is True


class TestWhoMayDelete:
    """Creating a tag is additive and undoable; deleting one is neither."""

    def test_a_member_cannot_delete_one(self, client, admin, member, db):
        """It strips the tag from every book in the house, with no undo.

        `Tag` records nobody as its author, so one member quietly unpicking
        the shared vocabulary would leave no trace of who or what.
        """
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=member["headers"]
        ).json()

        res = client.delete(f"/api/books/tags/{tag['id']}", headers=member["headers"])

        assert res.status_code == 403
        assert db.get(Tag, tag["id"]) is not None

    def test_a_member_may_still_invent_one(self, client, member):
        """The asymmetry is the point, so it is pinned from both sides."""
        res = client.post(
            "/api/books/tags", json={"name": "Loft boxes"}, headers=member["headers"]
        )
        assert res.status_code == 201


class TestBookCounts:
    def test_a_tag_reports_how_many_books_carry_it(self, client, admin, make_book):
        """The confirmation says what is about to happen.

        "Delete this tag" and "take this off 214 books" are different
        decisions, and only one of them is obvious from the name.
        """
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        for title in ("One", "Two"):
            book = make_book(admin["headers"], title=title)
            client.post(
                f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
            )

        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        counted = next(row for row in tags if row["id"] == tag["id"])
        assert counted["book_count"] == 2

    def test_an_unused_tag_counts_zero(self, client, admin):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        assert all(tag["book_count"] == 0 for tag in tags)

    def test_the_counts_cost_one_query_not_one_each(self, client, admin, make_book):
        """Fetched on nearly every page, so an N+1 here is an N+1 everywhere."""
        from sqlalchemy import event

        from database import engine

        book = make_book(admin["headers"])
        for name in ("A", "B", "C"):
            tag = client.post(
                "/api/books/tags", json={"name": name}, headers=admin["headers"]
            ).json()
            client.post(
                f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
            )

        statements: list[str] = []

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            client.get("/api/books/tags", headers=admin["headers"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        # The tags, the counts, and the caller's own account lookup.
        assert len(selects) <= 4, selects


class TestTheCountsRespectPrivacy:
    """`book_count` is a book query like any other, and it forgot the rule.

    This endpoint is fetched on nearly every page, so a count that included
    another member's private books let one member watch the other's private
    additions accrue in a number their own listing reported as zero.
    """

    def test_another_member_s_private_book_is_not_counted(
        self, client, admin, member, make_book, db
    ):
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        book = make_book(admin["headers"], title="Diary", is_private=True)
        client.post(f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"])

        tags = client.get("/api/books/tags", headers=member["headers"]).json()
        counted = next(row for row in tags if row["id"] == tag["id"])
        assert counted["book_count"] == 0

    def test_a_trashed_book_is_not_counted(self, client, admin, make_book):
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        counted = next(row for row in tags if row["id"] == tag["id"])
        assert counted["book_count"] == 0

    def test_the_owner_still_sees_their_own_private_book(
        self, client, admin, make_book
    ):
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        book = make_book(admin["headers"], title="Diary", is_private=True)
        client.post(f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"])

        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        counted = next(row for row in tags if row["id"] == tag["id"])
        assert counted["book_count"] == 1
