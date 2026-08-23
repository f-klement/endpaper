"""Passages copied out of a book.

Shaped after the notes tests, because the feature is shaped after notes. What
is tested here beyond that shape is the three things quotes do differently: a
page number arrives from outside and is bounded, the list comes back in reading
order rather than in the order it was typed, and there is a second listing that
spans the whole shelf and is therefore a book query.
"""

from models import Quote


def add(client, headers, book_id, **fields):
    payload = {"text": "A line worth keeping"} | fields
    return client.post(f"/api/books/{book_id}/quotes", json=payload, headers=headers)


def listing(client, headers, book_id):
    return client.get(f"/api/books/{book_id}/quotes", headers=headers)


class TestAddingAQuote:
    def test_a_quote_comes_back_with_its_text(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = add(client, admin["headers"], book["id"], text="Call me Ishmael")
        assert res.status_code == 201
        assert res.json()["text"] == "Call me Ishmael"

    def test_a_quote_carries_its_author(self, client, member, make_book):
        book = make_book(member["headers"])
        res = add(client, member["headers"], book["id"])
        assert res.json()["author"]["username"] == "member"

    def test_the_page_is_optional(self, client, admin, make_book):
        """Somebody typing a line they remember does not know the page."""
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"]).json()["page"] is None

    def test_the_page_is_kept_when_given(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], page=214).json()["page"] == 214

    def test_the_remark_is_optional(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"]).json()["note"] is None

    def test_the_remark_is_kept_when_given(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = add(client, admin["headers"], book["id"], note="Why this one")
        assert res.json()["note"] == "Why this one"

    def test_a_blank_remark_is_stored_as_no_remark(self, client, admin, make_book):
        """Absent and empty are one state, so only one of them reaches the row."""
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], note="   ").json()["note"] is None

    def test_the_excerpt_is_trimmed(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = add(client, admin["headers"], book["id"], text="  spaced  ")
        assert res.json()["text"] == "spaced"

    def test_the_line_breaks_inside_a_passage_survive(self, client, admin, make_book):
        """A quote is often several lines, so inner whitespace is left alone.

        This is where `QuoteCreate` parts company with `CollectionCreate.tidy`,
        which collapses runs of whitespace: doing that here would rewrite the
        passage.
        """
        book = make_book(admin["headers"])
        res = add(client, admin["headers"], book["id"], text="One line\nand another")
        assert res.json()["text"] == "One line\nand another"

    def test_requires_authentication(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(f"/api/books/{book['id']}/quotes", json={"text": "x"})
        assert res.status_code == 401


class TestRefusingBadInput:
    """Every one of these is a 422 rather than a 500 or a stored row."""

    def test_an_empty_excerpt(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], text="").status_code == 422

    def test_an_excerpt_of_only_whitespace(self, client, admin, make_book):
        """It passes `min_length=1` and then renders as a blank card nobody can
        tell from a rendering fault."""
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], text="   \n  ").status_code == 422

    def test_an_excerpt_past_the_ceiling(self, client, admin, make_book):
        """2,000 characters, which is about one printed page. The bound is both
        the stored-denial-of-service guard and the one place the "this is
        somebody else's copyrighted text" argument has a mechanical effect."""
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], text="x" * 2001).status_code == 422

    def test_an_excerpt_at_the_ceiling_is_accepted(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], text="x" * 2000).status_code == 201

    def test_a_remark_past_its_ceiling(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = add(client, admin["headers"], book["id"], note="x" * 1001)
        assert res.status_code == 422

    def test_page_zero(self, client, admin, make_book):
        """A book has no page zero, and `ck_quotes_page_bounds` says so too."""
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], page=0).status_code == 422

    def test_a_negative_page(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], page=-3).status_code == 422

    def test_an_absurd_page(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], page=100_001).status_code == 422

    def test_a_page_past_what_sqlite_stores(self, client, admin, make_book):
        """Unbounded, this reaches the driver and raises `OverflowError`, which
        answers 500 to a value the caller chose."""
        book = make_book(admin["headers"])
        assert add(client, admin["headers"], book["id"], page=2**63).status_code == 422

    def test_a_quote_id_past_what_sqlite_stores(self, client, admin, make_book):
        """`RowId` bounds the path segment, for the same reason."""
        book = make_book(admin["headers"])
        res = client.delete(
            f"/api/books/{book['id']}/quotes/{2**63}", headers=admin["headers"]
        )
        assert res.status_code == 422


class TestListingOneBook:
    def test_quotes_come_back_in_reading_order(self, client, admin, make_book):
        """By page, not by when they were typed. This is where quotes and notes
        part company: notes are a conversation, a book is read front to back."""
        book = make_book(admin["headers"])
        for page in (214, 12, 99):
            add(client, admin["headers"], book["id"], text=f"p{page}", page=page)

        assert [q["page"] for q in listing(client, admin["headers"], book["id"]).json()] == [
            12,
            99,
            214,
        ]

    def test_unpaged_quotes_sort_to_the_end(self, client, admin, make_book):
        """`nullslast`, so they stay together rather than landing wherever
        SQLite puts NULL."""
        book = make_book(admin["headers"])
        add(client, admin["headers"], book["id"], text="unpaged")
        add(client, admin["headers"], book["id"], text="paged", page=5)

        assert [q["text"] for q in listing(client, admin["headers"], book["id"]).json()] == [
            "paged",
            "unpaged",
        ]

    def test_two_quotes_on_one_page_keep_the_order_they_were_added(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        add(client, admin["headers"], book["id"], text="first", page=7)
        add(client, admin["headers"], book["id"], text="second", page=7)

        assert [q["text"] for q in listing(client, admin["headers"], book["id"]).json()] == [
            "first",
            "second",
        ]

    def test_a_member_sees_another_members_quote_on_a_shared_book(
        self, client, admin, member, make_book
    ):
        """The shelf is shared, so a passage copied out of a book on it is the
        household's to read. Same rule as notes, deliberately."""
        book = make_book(admin["headers"])
        add(client, admin["headers"], book["id"], text="Mine")

        assert [q["text"] for q in listing(client, member["headers"], book["id"]).json()] == [
            "Mine"
        ]

    def test_requires_authentication(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert client.get(f"/api/books/{book['id']}/quotes").status_code == 401


class TestPrivacy:
    def test_the_quotes_on_someone_elses_private_book_are_404(
        self, client, admin, member, make_book
    ):
        """404 rather than 403, because a 403 confirms the book exists."""
        private = make_book(member["headers"], title="Secret", is_private=True)
        add(client, member["headers"], private["id"], text="Hidden")

        assert listing(client, admin["headers"], private["id"]).status_code == 404

    def test_a_quote_cannot_be_added_to_someone_elses_private_book(
        self, client, admin, member, make_book
    ):
        private = make_book(member["headers"], is_private=True)
        assert add(client, admin["headers"], private["id"]).status_code == 404

    def test_the_owner_still_sees_their_own(self, client, member, make_book):
        private = make_book(member["headers"], is_private=True)
        add(client, member["headers"], private["id"], text="Hidden")
        assert len(listing(client, member["headers"], private["id"]).json()) == 1


class TestEditing:
    def test_the_author_may_reword_a_quote(self, client, admin, make_book):
        book = make_book(admin["headers"])
        quote = add(client, admin["headers"], book["id"]).json()

        res = client.put(
            f"/api/books/{book['id']}/quotes/{quote['id']}",
            json={"text": "Corrected", "page": 3},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert (res.json()["text"], res.json()["page"]) == ("Corrected", 3)

    def test_an_edit_can_clear_the_page(self, client, admin, make_book):
        """The whole payload is the new state, so an omitted page means none."""
        book = make_book(admin["headers"])
        quote = add(client, admin["headers"], book["id"], page=44).json()

        res = client.put(
            f"/api/books/{book['id']}/quotes/{quote['id']}",
            json={"text": "Corrected"},
            headers=admin["headers"],
        )

        assert res.json()["page"] is None

    def test_another_member_may_not_reword_it(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        quote = add(client, admin["headers"], book["id"]).json()

        res = client.put(
            f"/api/books/{book['id']}/quotes/{quote['id']}",
            json={"text": "Not yours"},
            headers=member["headers"],
        )

        assert res.status_code == 403

    def test_an_admin_may_delete_anyones_quote(self, client, admin, member, make_book):
        book = make_book(member["headers"])
        quote = add(client, member["headers"], book["id"]).json()

        res = client.delete(
            f"/api/books/{book['id']}/quotes/{quote['id']}", headers=admin["headers"]
        )

        assert res.status_code == 204

    def test_the_author_may_delete_their_own(self, client, member, make_book):
        book = make_book(member["headers"])
        quote = add(client, member["headers"], book["id"]).json()

        res = client.delete(
            f"/api/books/{book['id']}/quotes/{quote['id']}", headers=member["headers"]
        )

        assert res.status_code == 204
        assert listing(client, member["headers"], book["id"]).json() == []

    def test_a_quote_id_from_another_book_is_404(self, client, admin, make_book):
        """The book/quote pairing is enforced, so an id from a book the caller
        cannot reach is not editable through one they can."""
        mine = make_book(admin["headers"], title="Mine")
        other = make_book(admin["headers"], title="Other")
        quote = add(client, admin["headers"], other["id"]).json()

        res = client.put(
            f"/api/books/{mine['id']}/quotes/{quote['id']}",
            json={"text": "Wrong book"},
            headers=admin["headers"],
        )

        assert res.status_code == 404


class TestTheCrossBookListing:
    """`GET /api/books/quotes`, which is a book query wearing a different hat."""

    def test_it_is_not_read_as_a_book_id(self, client, admin):
        """Declared before `/{book_id}`. The reverse makes this a request for
        the book with id "quotes"."""
        res = client.get("/api/books/quotes", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["items"] == []

    def test_it_spans_books(self, client, admin, make_book):
        one = make_book(admin["headers"], title="One")
        two = make_book(admin["headers"], title="Two")
        add(client, admin["headers"], one["id"], text="From one")
        add(client, admin["headers"], two["id"], text="From two")

        body = client.get("/api/books/quotes", headers=admin["headers"]).json()

        assert {q["text"] for q in body["items"]} == {"From one", "From two"}
        assert body["total"] == 2

    def test_newest_first(self, client, admin, make_book):
        """A list spanning the shelf has no reading order to be in, and the
        interesting end is the one somebody just added."""
        book = make_book(admin["headers"])
        add(client, admin["headers"], book["id"], text="older")
        add(client, admin["headers"], book["id"], text="newer")

        body = client.get("/api/books/quotes", headers=admin["headers"]).json()

        assert [q["text"] for q in body["items"]] == ["newer", "older"]

    def test_each_row_carries_its_book(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        add(client, admin["headers"], book["id"])

        row = client.get("/api/books/quotes", headers=admin["headers"]).json()["items"][0]

        assert (row["book_id"], row["book_title"], row["book_author"]) == (
            book["id"],
            "Dune",
            "Frank Herbert",
        )

    def test_each_row_names_who_saved_it(self, client, member, make_book):
        """Eager loaded beside the book columns, so a hundred quotes over ninety
        books is not a hundred extra statements for a username."""
        book = make_book(member["headers"])
        add(client, member["headers"], book["id"])

        row = client.get("/api/books/quotes", headers=member["headers"]).json()["items"][0]

        assert row["author"]["username"] == "member"

    def test_it_omits_a_quote_on_someone_elses_private_book(
        self, client, admin, member, make_book
    ):
        """Without `visible_to` this prints the private book's title and cover
        beside the passage, in one 200, to anybody signed in."""
        private = make_book(member["headers"], title="Secret", is_private=True)
        add(client, member["headers"], private["id"], text="Hidden")

        body = client.get("/api/books/quotes", headers=admin["headers"]).json()

        assert body["items"] == []
        assert body["total"] == 0

    def test_the_owner_of_a_private_book_still_sees_their_own(
        self, client, member, make_book
    ):
        private = make_book(member["headers"], is_private=True)
        add(client, member["headers"], private["id"], text="Hidden")

        body = client.get("/api/books/quotes", headers=member["headers"]).json()

        assert [q["text"] for q in body["items"]] == ["Hidden"]

    def test_it_omits_a_quote_on_a_trashed_book(self, client, admin, make_book):
        """`visible_to` carries the soft-delete rule too, so this comes free and
        is pinned here so a later rewrite cannot lose it."""
        book = make_book(admin["headers"])
        add(client, admin["headers"], book["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        body = client.get("/api/books/quotes", headers=admin["headers"]).json()

        assert (body["items"], body["total"]) == ([], 0)

    def test_it_pages(self, client, admin, make_book):
        book = make_book(admin["headers"])
        for index in range(3):
            add(client, admin["headers"], book["id"], text=f"q{index}")

        body = client.get(
            "/api/books/quotes", params={"page": 2, "page_size": 2}, headers=admin["headers"]
        ).json()

        assert (len(body["items"]), body["total"], body["page"]) == (1, 3, 2)

    def test_the_page_size_is_capped(self, client, admin):
        res = client.get(
            "/api/books/quotes", params={"page_size": 10_000}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_the_page_number_is_capped(self, client, admin):
        """Unbounded, `page * page_size` overflows SQLite's INTEGER and answers
        500. Measured on the main listing before `MAX_PAGE_NUMBER` existed."""
        res = client.get(
            "/api/books/quotes",
            params={"page": 9_999_999_999_999_999_999_999},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_requires_authentication(self, client):
        assert client.get("/api/books/quotes").status_code == 401


class TestQuotesAndTheBookTheyCameFrom:
    def test_a_merge_moves_them_to_the_survivor(self, client, admin, make_book, db):
        """Without the repointing, the loser's cascade destroys passages
        somebody typed out by hand."""
        keeper = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        loser = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        add(client, admin["headers"], loser["id"], text="Fear is the mind-killer")

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert [q["text"] for q in listing(client, admin["headers"], keeper["id"]).json()] == [
            "Fear is the mind-killer"
        ]
        assert db.query(Quote).count() == 1

    def test_trashing_a_book_keeps_its_quotes(self, client, admin, make_book, db):
        """A restore has to be whole, which is what makes a delete undoable."""
        book = make_book(admin["headers"])
        add(client, admin["headers"], book["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert db.query(Quote).filter(Quote.book_id == book["id"]).count() == 1

    def test_purging_a_book_cascades_to_its_quotes(self, client, admin, make_book, db):
        """The cascade did not go away, it moved to the irreversible verb."""
        book = make_book(admin["headers"])
        add(client, admin["headers"], book["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{book['id']}/permanent", headers=admin["headers"])

        assert db.query(Quote).filter(Quote.book_id == book["id"]).count() == 0

    def test_a_new_copy_carries_none_of_them(self, client, admin, make_book):
        """A quote belongs to a person and an object, and the new object is one
        nobody has read yet. The page numbers would be wrong for it anyway."""
        book = make_book(admin["headers"], title="Dune")
        add(client, admin["headers"], book["id"], page=214)

        copy = client.post(
            f"/api/books/{book['id']}/copies", json={}, headers=admin["headers"]
        ).json()

        assert listing(client, admin["headers"], copy["id"]).json() == []
