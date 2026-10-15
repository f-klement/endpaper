"""A catalogue's online links on a Book: the delete route and the merge.

The import and the export are `tests/routers/test_imports_marc.py`; what is here
is the correction a member has (a delete, whoever may write the Book) and what a
merge does with two Books' links.
"""

from models import MAX_ONLINE_LINKS_PER_BOOK, OnlineLink


def links(book_id, db):
    """The stored rows, re-read past this session's identity map."""
    db.expire_all()
    return db.query(OnlineLink).filter(OnlineLink.book_id == book_id).order_by(OnlineLink.id).all()


def with_links(db, book_id, *urls):
    db.add_all(OnlineLink(book_id=book_id, url=url) for url in urls)
    db.commit()
    return links(book_id, db)


class TestForgettingALink:
    def test_the_member_who_added_the_book_removes_one_and_the_rest_stay(
        self, client, admin, db, make_book
    ):
        book = make_book(admin["headers"], title="Stoner")
        first, second = with_links(db, book["id"], "https://a.example/", "https://b.example/")

        res = client.delete(f"/api/books/{book['id']}/online-links/{first.id}", headers=admin["headers"])

        assert res.status_code == 204
        assert [row.id for row in links(book["id"], db)] == [second.id]

    def test_another_member_removes_one_from_a_public_book(self, client, admin, member, db, make_book):
        book = make_book(admin["headers"], title="Stoner")
        [row] = with_links(db, book["id"], "https://a.example/")

        res = client.delete(f"/api/books/{book['id']}/online-links/{row.id}", headers=member["headers"])

        assert res.status_code == 204
        assert links(book["id"], db) == []

    def test_a_link_of_another_book_is_404_and_survives(self, client, admin, db, make_book):
        mine = make_book(admin["headers"], title="Stoner")
        theirs = make_book(admin["headers"], title="Augustus")
        [row] = with_links(db, theirs["id"], "https://a.example/")

        res = client.delete(f"/api/books/{mine['id']}/online-links/{row.id}", headers=admin["headers"])

        assert res.status_code == 404
        assert [stored.id for stored in links(theirs["id"], db)] == [row.id]

    def test_a_link_id_naming_nothing_is_404(self, client, admin, db, make_book):
        book = make_book(admin["headers"], title="Stoner")
        [row] = with_links(db, book["id"], "https://a.example/")

        res = client.delete(
            f"/api/books/{book['id']}/online-links/{row.id + 1000}", headers=admin["headers"]
        )

        assert res.status_code == 404
        assert [stored.id for stored in links(book["id"], db)] == [row.id]

    def test_it_takes_a_session(self, client, admin, db, make_book):
        book = make_book(admin["headers"], title="Stoner")
        [row] = with_links(db, book["id"], "https://a.example/")

        res = client.delete(f"/api/books/{book['id']}/online-links/{row.id}")

        assert res.status_code == 401
        assert [stored.id for stored in links(book["id"], db)] == [row.id]

    def test_another_members_private_book_answers_what_an_absent_one_does(
        self, client, admin, member, db, make_book
    ):
        private = make_book(admin["headers"], title="Stoner", is_private=True)
        [row] = with_links(db, private["id"], "https://a.example/")

        refused = client.delete(
            f"/api/books/{private['id']}/online-links/{row.id}", headers=member["headers"]
        )
        absent = client.delete(
            f"/api/books/{private['id'] + 5000}/online-links/{row.id}", headers=member["headers"]
        )

        assert refused.status_code == absent.status_code == 404
        assert refused.json() == absent.json()
        assert [stored.id for stored in links(private["id"], db)] == [row.id]


class TestAMergeCarriesTheLinks:
    def merge(self, client, headers, keeper, loser):
        return client.post(
            "/api/books/merge",
            json={"book_ids": [keeper, loser], "keep_id": keeper},
            headers=headers,
        )

    def test_a_url_both_books_carry_is_kept_once(self, client, admin, db, make_book):
        """Two rows for one Book imported from one file carry the same link, and
        `uq_online_links_book_url` would refuse a plain repoint."""
        keeper = make_book(admin["headers"], title="Stoner")["id"]
        loser = make_book(admin["headers"], title="Stoner")["id"]
        with_links(db, keeper, "https://a.example/")
        with_links(db, loser, "https://a.example/", "https://b.example/")

        res = self.merge(client, admin["headers"], keeper, loser)

        assert res.status_code == 200, res.text
        assert [row.url for row in links(keeper, db)] == ["https://a.example/", "https://b.example/"]

    def test_a_merge_cannot_carry_the_survivor_past_the_ceiling(self, client, admin, db, make_book):
        keeper = make_book(admin["headers"], title="Stoner")["id"]
        loser = make_book(admin["headers"], title="Stoner")["id"]
        with_links(db, keeper, *(f"https://a{n}.example/" for n in range(MAX_ONLINE_LINKS_PER_BOOK)))
        with_links(db, loser, "https://extra.example/")

        res = self.merge(client, admin["headers"], keeper, loser)

        assert res.status_code == 200, res.text
        kept = [row.url for row in links(keeper, db)]
        assert len(kept) == MAX_ONLINE_LINKS_PER_BOOK
        assert "https://extra.example/" not in kept
