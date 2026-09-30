"""Finding duplicate entries and folding them together.

An accidental exact repeat is already refused by `uq_books_isbn_single_copy`,
so the case worth catching is the one it cannot see: a hardback and a paperback
are the same book and two legitimately different ISBNs. Deliberate copies of one
title are neither, and `tests/routers/test_books_copies.py` holds that line.
Detection is therefore deliberately lossy, and merge is a thing a person
confirms rather than something automatic.
"""

from schemas import DUPLICATE_BOOKS_SHOWN, MERGE_BOOKS_MAX

# `count_selects` lives beside the author index, the other whole catalogue
# scan with a statement count to defend. Imported rather than copied: a second
# copy of a measuring instrument is a second thing that can measure
# differently.
from tests.routers.test_books_authors import count_selects


def merge(client, headers, book_ids, keep_id):
    return client.post(
        "/api/books/merge", json={"book_ids": book_ids, "keep_id": keep_id}, headers=headers
    )


def report(client, headers):
    return client.get("/api/books/duplicates", headers=headers).json()


def groups(client, headers):
    return report(client, headers)["groups"]


class TestDetection:
    def test_finds_the_same_title_and_author_twice(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="Dune", author="Frank Herbert")

        [group] = groups(client, admin["headers"])

        assert len(group["books"]) == 2

    def test_ignores_case_and_punctuation(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune!", author="Frank Herbert")
        make_book(admin["headers"], title="dune", author="frank herbert")

        assert len(groups(client, admin["headers"])) == 1

    def test_ignores_a_leading_article(self, client, admin, make_book):
        make_book(admin["headers"], title="The Hobbit", author="Tolkien")
        make_book(admin["headers"], title="Hobbit", author="Tolkien")

        assert len(groups(client, admin["headers"])) == 1

    def test_ignores_a_german_leading_article(self, client, admin, make_book):
        make_book(admin["headers"], title="Der Steppenwolf", author="Hesse")
        make_book(admin["headers"], title="Steppenwolf", author="Hesse")

        assert len(groups(client, admin["headers"])) == 1

    def test_an_isbd_mark_left_by_a_catalogue_does_not_hide_a_duplicate(
        self, client, admin, make_book
    ):
        """MARC 245 carries this punctuation, so it arrives on real rows.

        The mark used to leave its own space in the key, so the pair was never
        offered and the member kept two rows for one book.
        """
        make_book(admin["headers"], title="Ulysses :", author="James Joyce")
        make_book(admin["headers"], title="Ulysses", author="James Joyce")

        assert len(groups(client, admin["headers"])) == 1

    def test_initials_spaced_two_ways_are_one_author(self, client, admin, make_book):
        make_book(admin["headers"], title="The Hobbit", author="J.R.R. Tolkien")
        make_book(admin["headers"], title="Hobbit", author="J. R. R. Tolkien")

        assert len(groups(client, admin["headers"])) == 1

    def test_two_surnames_differing_by_an_article_word_are_not_a_duplicate(
        self, client, admin, make_book
    ):
        """`Das Gupta` is a surname and the fold used to eat the `Das`.

        Offering these two for merge invites somebody to destroy one of them.
        """
        make_book(admin["headers"], title="Field Notes", author="Das Gupta")
        make_book(admin["headers"], title="Field Notes", author="Gupta")

        assert groups(client, admin["headers"]) == []

    def test_matches_on_the_first_author_only(self, client, admin, make_book):
        """Two editions credit a collaboration differently all the time."""
        make_book(admin["headers"], title="Good Omens", author="Terry Pratchett")
        make_book(admin["headers"], title="Good Omens", author="Terry Pratchett, Neil Gaiman")

        assert len(groups(client, admin["headers"])) == 1

    def test_different_books_are_not_grouped(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="Neuromancer", author="William Gibson")

        assert groups(client, admin["headers"]) == []

    def test_the_same_title_by_different_authors_is_not_a_duplicate(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Ulysses", author="James Joyce")
        make_book(admin["headers"], title="Ulysses", author="Alfred Tennyson")

        assert groups(client, admin["headers"]) == []

    def test_a_single_book_is_not_a_group(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        assert groups(client, admin["headers"]) == []

    def test_another_members_private_book_is_never_grouped(
        self, client, admin, member, make_book
    ):
        # Otherwise the duplicates view discloses a private book's title.
        make_book(admin["headers"], title="Dune", author="Frank Herbert", is_private=True)
        make_book(member["headers"], title="Dune", author="Frank Herbert")

        assert groups(client, member["headers"]) == []

    def test_a_private_sibling_does_not_inflate_a_group_that_exists(
        self, client, admin, member, make_book
    ):
        """Two visible rows and one private one is a group of exactly two.

        The arm above covers the group that must not exist at all. This is the
        group that legitimately does, and the size is what made the arm load
        bearing: `size` is the first count this route has ever published, and
        a count taken over anything but the survivors would announce a book
        the viewer cannot see without naming it.
        """
        make_book(
            admin["headers"], title="Dune", author="Frank Herbert", is_private=True
        )
        make_book(member["headers"], title="Dune", author="Frank Herbert")
        make_book(member["headers"], title="dune", author="frank herbert")

        body = report(client, member["headers"])

        [group] = body["groups"]
        assert (group["size"], len(group["books"]), body["total_groups"]) == (2, 2, 1)

    def test_a_trashed_duplicate_is_not_offered(self, client, admin, make_book):
        """Soft deletion is an arm of the shelf predicate, and the scan reads
        the shelf through a different door than it used to. A projection
        rebuilt from anything but `seen_by`'s own criteria would offer a merge
        into a row sitting in the trash.

        **Three rows rather than two.** With two, trashing one kills the group
        for two reasons at once and the assertion is an empty answer, which
        never reaches the case the merge cares about: a group that still
        exists, carrying an id nobody can act on. That is the same class as
        the dead merge button the member cap closed.
        """
        kept = [
            make_book(admin["headers"], title="Dune", author="Frank Herbert")
            for _ in range(2)
        ]
        gone = make_book(admin["headers"], title="Dune", author="Frank Herbert")

        client.delete(f"/api/books/{gone['id']}", headers=admin["headers"])

        [group] = groups(client, admin["headers"])
        assert group["size"] == 2
        assert {row["id"] for row in group["books"]} == {row["id"] for row in kept}

    def test_the_viewers_own_private_duplicates_are_on_their_own_page(
        self, client, member, make_book
    ):
        """The direction every other arm here is blind to.

        The rest of this class asks whether somebody else's book is absent,
        which a shelf narrowed to **any** wrong viewer satisfies just as well
        as one narrowed to the right viewer. Measured: the viewer id replaced
        by `current_user.id + 10_000` left this file and the copies file
        green. The failure that hides behind that is not a leak, it is an
        erasure: a member's own private duplicates vanish from their own page
        and nothing says so.
        """
        for _ in range(2):
            make_book(
                member["headers"], title="Solaris", author="Lem", is_private=True
            )

        body = report(client, member["headers"])

        assert (len(body["groups"]), body["total_groups"]) == (1, 1)

    def test_the_total_counts_only_groups_this_viewer_can_see(
        self, client, admin, member, make_book
    ):
        """A viewer blind total, beside a group whose size is right.

        The arm above plants the private row **inside** an existing group, so
        a total counted over the library still reads 1 and only the size
        moves. This plants a whole group the viewer has no part of, which is
        the shape only the total can see.
        """
        for _ in range(2):
            make_book(
                admin["headers"], title="Solaris", author="Lem", is_private=True
            )
        make_book(member["headers"], title="Dune", author="Frank Herbert")
        make_book(member["headers"], title="dune", author="frank herbert")

        assert report(client, member["headers"])["total_groups"] == 1

    def test_requires_authentication(self, client):
        assert client.get("/api/books/duplicates").status_code == 401


class TestEveryColumnLandsWhereItBelongs:
    """The projection is positional and nothing else checks it.

    Nine columns in the select, nine fields in the row type, seven names in
    the member construction: three hand ordered lists, five of them mutually
    swappable nullable strings, and a `cast` that asserts the shape rather
    than checking it. Two swaps in that family are not cosmetic.

    **`copy_group` is the one field this route withholds on privacy
    grounds**, because a group token announces that a row has a declared
    sibling even when every sibling is invisible. It sits next to
    `publisher` in the select, both `str | None`, and the withholding is a
    hand written omission in the keyword construction: swap the two and the
    token renders on the card, with the cast agreeing.

    **And three of the nine decide grouping**, whose ids the card posts to an
    undoable merge. An author landing in publisher groups two different works
    as one and offers that merge; a publisher landing in the group token makes
    the collapse dedupe on publisher and silently drop real duplicates.
    """

    def test_each_column_lands_in_its_own_field_and_the_token_lands_nowhere(
        self, client, admin, db
    ):
        """One row, every value distinctive, compared whole.

        A whole dict rather than a field at a time: an equality over the
        emitted object is what catches a swap between two fields that are
        both present and both strings, which is the family a per field
        assertion passes.
        """
        from enums import BookFormat
        from models import Book

        token = "copy-group-token-that-must-not-be-published"
        described = Book(
            title="Dune",
            author="Frank Herbert",
            copy_group=token,
            format=BookFormat.HARDCOVER,
            publisher="Chilton Books",
            year=1965,
            isbn="9780441013593",
            cover_url="https://example.invalid/dune-first.jpg",
            added_by_user_id=admin["user"]["id"],
        )
        # A second row of the same work and a **different** publisher, so the
        # group exists only if the author reached the key. Swap author and
        # publisher and these two stop being one work at all.
        db.add_all(
            [
                described,
                Book(
                    title="Dune",
                    author="Frank Herbert",
                    publisher="Ace Books",
                    added_by_user_id=admin["user"]["id"],
                ),
            ]
        )
        db.commit()

        response = client.get("/api/books/duplicates", headers=admin["headers"])
        [group] = response.json()["groups"]
        [member] = [row for row in group["books"] if row["id"] == described.id]

        assert member == {
            "id": described.id,
            "title": "Dune",
            "format": "hardcover",
            "publisher": "Chilton Books",
            "year": 1965,
            "isbn": "9780441013593",
            "cover_url": "https://example.invalid/dune-first.jpg",
        }
        assert token not in response.text


class TestTheScanCostsOneStatement:
    """One SELECT over `books`, whatever the shelf holds.

    The route used to hydrate the whole visible shelf and serialise every
    duplicate in it, which is nine statements over the library, and before
    that it was two nested N+1s at 4002 statements over 2000 books. Nothing
    measured either; this is what stops the next one being silent.
    """

    def test_it_costs_one_statement_whatever_the_shelf_holds(
        self, client, admin, make_book
    ):
        """Measured at two sizes rather than one: a claim that the cost does
        not grow is a claim about two shelf sizes, and asserting it over one
        would pass just as well on a query issued per book."""

        def over_books() -> int:
            statements = count_selects(
                lambda: client.get("/api/books/duplicates", headers=admin["headers"])
            )
            return len([row for row in statements if "FROM books" in row])

        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="dune", author="frank herbert")
        assert over_books() == 1

        for index in range(40):
            make_book(admin["headers"], title=f"Book {index}", author=f"Author {index}")
        assert over_books() == 1


class TestTheMemberCap:
    """A group larger than one merge is allowed to name.

    The card sends every id it renders and `MergeRequest` refuses more than
    `MERGE_BOOKS_MAX` of them, so a group shown whole above that ceiling
    rendered a button that answered 422 on every click. Reachable from a
    catalogue import of many same titled rows sharing no copy group.

    The cap is that same constant rather than a number chosen beside it,
    because two numbers is how the two drifted apart in the first place.
    """

    def _one_group_of(self, make_book, admin, size: int) -> None:
        for _ in range(size):
            make_book(admin["headers"], title="Dune", author="Frank Herbert")

    def test_it_shows_no_more_members_than_a_merge_accepts(
        self, client, admin, make_book
    ):
        self._one_group_of(make_book, admin, MERGE_BOOKS_MAX + 1)

        [group] = groups(client, admin["headers"])

        assert len(group["books"]) == MERGE_BOOKS_MAX

    def test_it_reports_the_size_it_did_not_show(self, client, admin, make_book):
        """Otherwise a truncated group looks complete and the member stops."""
        self._one_group_of(make_book, admin, MERGE_BOOKS_MAX + 1)

        [group] = groups(client, admin["headers"])

        assert group["size"] == MERGE_BOOKS_MAX + 1

    def test_merging_everything_it_shows_is_accepted(self, client, admin, make_book):
        """The diagonal, and the defect: one member over the cap, and every
        button on the card used to be a guaranteed 422."""
        self._one_group_of(make_book, admin, MERGE_BOOKS_MAX + 1)
        [group] = groups(client, admin["headers"])
        ids = [row["id"] for row in group["books"]]

        assert merge(client, admin["headers"], ids, ids[0]).status_code == 200


class TestTheAnswerCap:
    """The answer is capped; the scan is not.

    `DUPLICATE_BOOKS_SHOWN` bounds books rather than groups, because a cap on
    groups leaves the largest group unbounded. Groups are accumulated whole:
    the merge sends every id the card renders, so a group cut by the budget
    would offer a merge over a subset nobody chose.
    """

    def _pairs(self, db, admin, how_many: int) -> None:
        """Written straight to the table rather than posted.

        Two hundred rows through the create route is the slowest way to say
        the same thing, and nothing here is about creation.
        """
        from models import Book

        db.add_all(
            Book(
                title=f"Title {index}",
                author="One Author",
                added_by_user_id=admin["user"]["id"],
            )
            for index in range(how_many)
            for _ in range(2)
        )
        db.commit()

    def test_it_stops_at_the_book_budget(self, client, admin, db):
        self._pairs(db, admin, DUPLICATE_BOOKS_SHOWN)

        body = report(client, admin["headers"])

        shown = sum(len(group["books"]) for group in body["groups"])
        assert shown == DUPLICATE_BOOKS_SHOWN

    def test_it_says_how_many_groups_there_are_in_all(self, client, admin, db):
        """The number is the point of the cap: a member whose import ran twice
        is told the size of what happened rather than handed it."""
        self._pairs(db, admin, DUPLICATE_BOOKS_SHOWN)

        body = report(client, admin["headers"])

        assert body["total_groups"] == DUPLICATE_BOOKS_SHOWN
        assert len(body["groups"]) < DUPLICATE_BOOKS_SHOWN

    def test_it_never_cuts_a_group_in_half(self, client, admin, db):
        """A pair is two rows, so a budget that split one would leave an odd
        number of books in the answer."""
        self._pairs(db, admin, DUPLICATE_BOOKS_SHOWN)

        body = report(client, admin["headers"])

        assert all(group["size"] == len(group["books"]) == 2 for group in body["groups"])


class TestMerge:
    def test_keeps_the_chosen_book(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.status_code == 200
        assert res.json()["id"] == keeper["id"]

    def test_removes_the_others(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")

        merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert client.get(f"/api/books/{loser['id']}", headers=admin["headers"]).status_code == 404

    def test_absorbs_a_field_the_keeper_lacks(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune", publisher=None)
        loser = make_book(admin["headers"], title="Dune", publisher="Chilton")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["publisher"] == "Chilton"

    def test_never_overwrites_what_the_keeper_has(self, client, admin, make_book):
        """The kept row is the one a person chose."""
        keeper = make_book(admin["headers"], title="Dune", publisher="Ace")
        loser = make_book(admin["headers"], title="Dune", publisher="Chilton")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["publisher"] == "Ace"

    def test_absorbs_an_isbn(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["isbn"] == "9780441013593"

    def test_merges_three_at_once(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        second = make_book(admin["headers"], title="Dune", publisher="Chilton")
        third = make_book(admin["headers"], title="Dune", year=1965)

        res = merge(
            client, admin["headers"], [keeper["id"], second["id"], third["id"]], keeper["id"]
        )

        assert res.json()["publisher"] == "Chilton"
        assert res.json()["year"] == 1965

    def test_moves_the_tags_across(self, client, admin, make_book):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        fiction = next(t for t in tags if t["name"] == "Fiction")
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.post(
            f"/api/books/{loser['id']}/tags/{fiction['id']}", headers=admin["headers"]
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert [t["name"] for t in res.json()["tags"]] == ["Fiction"]

    def test_a_tag_on_both_is_not_duplicated(self, client, admin, make_book):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        fiction = next(t for t in tags if t["name"] == "Fiction")
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        for book in (keeper, loser):
            client.post(f"/api/books/{book['id']}/tags/{fiction['id']}", headers=admin["headers"])

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert len(res.json()["tags"]) == 1

    def test_moves_the_notes_across(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.post(
            f"/api/books/{loser['id']}/notes",
            json={"content": "worth keeping"},
            headers=admin["headers"],
        )

        merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        notes = client.get(f"/api/books/{keeper['id']}/notes", headers=admin["headers"]).json()
        assert [n["content"] for n in notes] == ["worth keeping"]

    def test_moves_a_private_note_across_too(self, client, admin, db, make_book):
        """A merge repoints **every** note on the losing book whatever its
        author or its visibility, and the losing row is then destroyed with its
        cascade. So a rule that skipped a private note here would not hide one,
        it would delete it, and silently: the only rows this feature creates are
        exactly the ones such a filter would drop.
        """
        from models import Note

        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        db.add(
            Note(
                book_id=loser["id"],
                user_id=admin["user"]["id"],
                content="what I actually thought",
                is_private=True,
            )
        )
        db.commit()

        merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        notes = client.get(f"/api/books/{keeper['id']}/notes", headers=admin["headers"]).json()
        assert [(n["content"], n["is_private"]) for n in notes] == [
            ("what I actually thought", True)
        ]

    def test_moves_a_reading_status_across(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["my_status"] == "read"

    def test_a_status_on_both_keeps_the_survivors(self, client, admin, make_book):
        """(user_id, book_id) is unique, so both rows cannot survive. Deleting
        somebody's reading history to satisfy an index is not acceptable, so the
        row already on the keeper wins."""
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{keeper['id']}/status", json={"status": "reading"}, headers=admin["headers"]
        )
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["my_status"] == "reading"

    def test_two_members_statuses_both_survive(self, client, admin, member, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "reading"}, headers=member["headers"]
        )

        merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        as_admin = client.get(f"/api/books/{keeper['id']}", headers=admin["headers"]).json()
        as_member = client.get(f"/api/books/{keeper['id']}", headers=member["headers"]).json()
        assert (as_admin["my_status"], as_member["my_status"]) == ("read", "reading")

    def test_moves_an_active_loan_across(self, client, admin, member, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.post(
            "/api/loans",
            json={"book_id": loser["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["active_loan"] is not None


class TestMergeRefusals:
    def test_the_keeper_must_be_in_the_list(self, client, admin, make_book):
        # Spelled out rather than inferred, so a mistyped request fails instead
        # of silently keeping whichever row sorted first.
        first = make_book(admin["headers"], title="Dune")
        second = make_book(admin["headers"], title="Dune")
        other = make_book(admin["headers"], title="Elsewhere")

        res = merge(client, admin["headers"], [first["id"], second["id"]], other["id"])

        assert res.status_code == 400

    def test_needs_at_least_two_books(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        assert merge(client, admin["headers"], [book["id"], book["id"]], book["id"]).status_code == 400

    def test_an_unknown_id_is_not_silently_dropped(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        res = merge(client, admin["headers"], [book["id"], 9999], book["id"])
        assert res.status_code == 400

    def test_another_members_private_book_cannot_be_merged_in(
        self, client, admin, member, make_book
    ):
        private = make_book(admin["headers"], title="Dune", is_private=True)
        mine = make_book(member["headers"], title="Dune")

        res = merge(client, member["headers"], [mine["id"], private["id"]], mine["id"])

        assert res.status_code == 400

    def test_requires_authentication(self, client):
        assert client.post("/api/books/merge", json={"book_ids": [1, 2], "keep_id": 1}).status_code == 401


class TestTheLoanInvariant:
    """`returned_at IS NULL` is the single active loan, per docs/data-model.md.

    Merging two books that were both lent out broke it: every loan moved to
    the survivor unconditionally, so it ended up with two open. Every later
    lend on that book then 409s forever, and the UI renders one `active_loan`,
    so there is no way to see the other or close it.
    """

    def _lent_book(self, client, admin, member, make_book, title: str):
        book = make_book(admin["headers"], title=title, author="One Author")
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        return book

    def test_merging_two_lent_books_leaves_one_open_loan(
        self, client, admin, member, make_book, db
    ):
        from models import Loan

        first = self._lent_book(client, admin, member, make_book, "Dune")
        second = self._lent_book(client, admin, member, make_book, "Dune")

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [first["id"], second["id"]], "keep_id": first["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        db.expire_all()
        open_loans = (
            db.query(Loan)
            .filter(Loan.book_id == first["id"], Loan.returned_at.is_(None))
            .count()
        )
        assert open_loans == 1

    def test_the_survivor_can_still_be_lent_after_it_comes_back(
        self, client, admin, member, make_book
    ):
        first = self._lent_book(client, admin, member, make_book, "Dune")
        second = self._lent_book(client, admin, member, make_book, "Dune")
        client.post(
            "/api/books/merge",
            json={"book_ids": [first["id"], second["id"]], "keep_id": first["id"]},
            headers=admin["headers"],
        )

        [loan] = [
            row
            for row in client.get("/api/loans", headers=admin["headers"]).json()["items"]
            if row["book_id"] == first["id"]
        ]
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])

        res = client.post(
            "/api/loans",
            json={"book_id": first["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 201

    def test_no_loan_history_is_destroyed(self, client, admin, member, make_book, db):
        """The extra loans are closed, not deleted: they happened."""
        from models import Loan

        first = self._lent_book(client, admin, member, make_book, "Dune")
        second = self._lent_book(client, admin, member, make_book, "Dune")

        client.post(
            "/api/books/merge",
            json={"book_ids": [first["id"], second["id"]], "keep_id": first["id"]},
            headers=admin["headers"],
        )

        db.expire_all()
        assert db.query(Loan).filter(Loan.book_id == first["id"]).count() == 2
