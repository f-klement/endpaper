"""Author pages and deduplication, over a column that holds free text.

There is no author table. Everything here is a `GROUP BY` over `books.author`,
plus one stored table holding the decisions that grouping cannot make. Three
things are therefore worth testing more than the happy path: that the privacy
rule reaches a page nobody thought of as a book listing, that a merge writes
nothing to `books`, and that undoing one really does restore what was there.
"""

from typing import Any

import httpx
import respx
from sqlalchemy import event

from authors import author_key
from database import engine
from models import AuthorAlias, AuthorIdentifier
from tests.helpers import DNB, silence_catalogues, sru_response

AUTHORS = "/api/books/authors"

GERMAN_ISBN = "9783960092353"


def author_named(body: list[dict], name: str) -> dict:
    return next(row for row in body if row["name"] == name)


def merge(client, headers, keys: list[str], keep: str):
    return client.post(
        f"{AUTHORS}/merge", json={"keys": keys, "keep_name": keep}, headers=headers
    )


def confirm(client, headers, author: str, identifier: str, scheme: str = "gnd"):
    return client.post(
        f"{AUTHORS}/identifiers",
        json={"author": author, "scheme": scheme, "identifier": identifier},
        headers=headers,
    )


def count_selects(fn) -> list[str]:
    """Every SELECT one call issues, in order."""
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements


class TestTheAuthorIndex:
    def test_every_person_on_the_shelf_is_listed_once(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="Messiah", author="Frank Herbert")

        body = client.get(AUTHORS, headers=admin["headers"]).json()

        assert [(row["name"], row["book_count"]) for row in body] == [
            ("Frank Herbert", 2)
        ]

    def test_a_credit_line_with_two_people_makes_two_authors(
        self, client, admin, make_book
    ):
        make_book(
            admin["headers"], title="Good Omens", author="Terry Pratchett, Neil Gaiman"
        )

        body = client.get(AUTHORS, headers=admin["headers"]).json()

        assert [row["name"] for row in body] == ["Neil Gaiman", "Terry Pratchett"]
        assert all(row["book_count"] == 1 for row in body)

    def test_two_spellings_of_one_name_are_one_person(self, client, admin, make_book):
        make_book(admin["headers"], title="Nana", author="Émile Zola")
        make_book(admin["headers"], title="Germinal", author="Emile Zola")

        body = client.get(AUTHORS, headers=admin["headers"]).json()

        assert len(body) == 1
        assert body[0]["book_count"] == 2
        assert sorted(body[0]["spellings"]) == ["Emile Zola", "Émile Zola"]

    def test_a_book_with_nobody_credited_adds_nobody(self, client, admin, make_book):
        make_book(admin["headers"], title="Anonymous", author=None)

        assert client.get(AUTHORS, headers=admin["headers"]).json() == []

    def test_a_trashed_book_leaves_no_author_behind(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert client.get(AUTHORS, headers=admin["headers"]).json() == []

    def test_it_needs_a_session(self, client):
        assert client.get(AUTHORS).status_code == 401


class TestTheIndexKeepsThePrivacyRule:
    """An author page is a book listing and a book count.

    Both halves leak. A name in the list says somebody owns a book by that
    person; the count beside it says how many. This is the defect the tag
    counts and the collection counts were each fixed for, arriving a third
    time through a page nobody would call a book listing.
    """

    def test_another_members_private_author_is_not_listed(
        self, client, admin, member, make_book
    ):
        make_book(admin["headers"], title="Diary", author="Anne Frank", is_private=True)

        assert client.get(AUTHORS, headers=member["headers"]).json() == []

    def test_another_members_private_book_is_not_counted(
        self, client, admin, member, make_book
    ):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(
            admin["headers"], title="Messiah", author="Frank Herbert", is_private=True
        )

        body = client.get(AUTHORS, headers=member["headers"]).json()

        assert author_named(body, "Frank Herbert")["book_count"] == 1

    def test_the_owner_still_sees_their_own(self, client, admin, make_book):
        make_book(admin["headers"], title="Diary", author="Anne Frank", is_private=True)

        body = client.get(AUTHORS, headers=admin["headers"]).json()

        assert author_named(body, "Anne Frank")["book_count"] == 1


class TestFilteringTheLibraryByAuthor:
    def test_by_key(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="Neuromancer", author="William Gibson")

        res = client.get("/api/books", params={"author": "frank herbert"}, headers=admin["headers"])

        assert [book["title"] for book in res.json()["items"]] == ["Dune"]

    def test_by_any_spelling_of_the_name(self, client, admin, make_book):
        make_book(admin["headers"], title="Nana", author="Émile Zola")

        res = client.get("/api/books", params={"author": "emile zola"}, headers=admin["headers"])

        assert res.json()["total"] == 1

    def test_a_name_nobody_has_a_book_by_is_an_empty_shelf_not_an_error(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")

        res = client.get("/api/books", params={"author": "Nobody At All"}, headers=admin["headers"])

        assert res.status_code == 200
        assert res.json()["total"] == 0

    def test_another_members_private_book_is_not_in_the_results(
        self, client, admin, member, make_book
    ):
        make_book(
            admin["headers"], title="Diary", author="Anne Frank", is_private=True
        )

        res = client.get("/api/books", params={"author": "Anne Frank"}, headers=member["headers"])

        assert res.json()["total"] == 0

    def test_a_spelling_no_book_carries_any_more_still_finds_them(
        self, client, admin, make_book
    ):
        """A link to the middle of a chain.

        Fold "Le Guin" into "Ursula K. Le Guin", then that into "U. K. Le
        Guin", and the middle name is on no book at all. Resolving through the
        shelf rather than through the mapping answered this with an empty
        library, which reads as "we own nothing by her".
        """
        make_book(admin["headers"], title="Rocannon", author="Le Guin")
        merge(client, admin["headers"], ["le guin"], "Ursula K. Le Guin")
        merge(client, admin["headers"], ["ursula k le guin"], "U. K. Le Guin")

        res = client.get(
            "/api/books",
            params={"author": "Ursula K. Le Guin"},
            headers=admin["headers"],
        )

        assert [book["title"] for book in res.json()["items"]] == ["Rocannon"]

    def test_a_folded_spelling_still_finds_the_books(
        self, client, admin, make_book
    ):
        """An old link keeps working after a tidy-up, which is the point of
        resolving the filter through the aliases rather than comparing text."""
        make_book(admin["headers"], title="Nana", author="Zola")
        merge(client, admin["headers"], ["zola"], "Émile Zola")

        res = client.get("/api/books", params={"author": "Zola"}, headers=admin["headers"])

        assert [book["title"] for book in res.json()["items"]] == ["Nana"]


class TestTheCreditLineOnABook:
    def test_the_payload_carries_the_names_as_well_as_the_line(
        self, client, admin, make_book
    ):
        book = make_book(
            admin["headers"], title="Good Omens", author="Terry Pratchett, Neil Gaiman"
        )

        body = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()

        assert body["author"] == "Terry Pratchett, Neil Gaiman"
        assert body["authors"] == ["Terry Pratchett", "Neil Gaiman"]

    def test_nobody_credited_is_an_empty_list(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Anonymous", author=None)

        body = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()

        assert body["authors"] == []


class TestSuggestions:
    def test_a_catalogue_order_split_is_offered_beside_the_whole_name(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Rocannon", author="Le Guin, Ursula K.")
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin")

        [group] = client.get(f"{AUTHORS}/suggestions", headers=admin["headers"]).json()

        assert set(group["names"]) == {"Le Guin", "Ursula K.", "Ursula K. Le Guin"}
        assert "fragment" in group["reasons"]

    def test_a_shelf_with_nothing_to_merge_offers_nothing(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="Neuromancer", author="William Gibson")

        assert client.get(f"{AUTHORS}/suggestions", headers=admin["headers"]).json() == []

    def test_another_members_private_author_is_not_suggested(
        self, client, admin, member, make_book
    ):
        make_book(admin["headers"], title="Rocannon", author="Le Guin, Ursula K.", is_private=True)
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin", is_private=True)

        assert client.get(f"{AUTHORS}/suggestions", headers=member["headers"]).json() == []


class TestMerging:
    def test_two_spellings_become_one_person(self, client, admin, make_book):
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin")

        res = merge(
            client, admin["headers"], ["u k le guin", "ursula k le guin"], "Ursula K. Le Guin"
        )

        assert res.status_code == 200
        assert res.json()["book_count"] == 2
        body = client.get(AUTHORS, headers=admin["headers"]).json()
        assert [row["name"] for row in body] == ["Ursula K. Le Guin"]

    def test_the_books_are_not_touched(self, client, admin, make_book):
        """The whole reason the design is a table of decisions rather than a
        rewrite. The credit line still says what the cover says."""
        book = make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")

        merge(client, admin["headers"], ["u k le guin"], "Ursula K. Le Guin")

        body = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert body["author"] == "U. K. Le Guin"

    def test_a_name_no_book_carries_is_allowed(self, client, admin, make_book):
        """The catalogue order repair: neither half is spelled correctly, so
        the name to keep has to be typed."""
        make_book(admin["headers"], title="Rocannon", author="Le Guin, Ursula K.")

        res = merge(client, admin["headers"], ["le guin", "ursula k"], "Ursula K. Le Guin")

        assert res.status_code == 200
        assert res.json()["name"] == "Ursula K. Le Guin"
        assert res.json()["book_count"] == 1

    def test_the_folded_spellings_come_back_with_the_author(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin")

        merge(client, admin["headers"], ["u k le guin"], "Ursula K. Le Guin")

        [author] = client.get(AUTHORS, headers=admin["headers"]).json()
        assert [row["spelling"] for row in author["merged"]] == ["U. K. Le Guin"]

    def test_the_author_is_not_listed_as_folded_into_themselves(
        self, client, admin, make_book
    ):
        """A merge writes a row for every key it was given, the kept one
        included, and that row is what pins the display name. Listing it as a
        spelling folded **in** put "Folded in: J. R. R. Tolkien" under the
        heading "J. R. R. Tolkien", with an undo beside it.

        Both keys are passed here, which is what the page sends: the earlier
        test merges only the losing key and cannot see this.
        """
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin")

        res = merge(
            client,
            admin["headers"],
            ["u k le guin", "ursula k le guin"],
            "Ursula K. Le Guin",
        )

        assert [row["spelling"] for row in res.json()["merged"]] == ["U. K. Le Guin"]
        [author] = client.get(AUTHORS, headers=admin["headers"]).json()
        assert [row["spelling"] for row in author["merged"]] == ["U. K. Le Guin"]

    def test_a_merge_can_be_reversed_by_merging_the_other_way(
        self, client, admin, make_book, db
    ):
        """The same two keys, the other name kept.

        This answered 200 with nothing changed: the handler followed the row
        saying "B means A" and rewrote the request back into itself. A silent
        no-op on the one correction somebody is most likely to make.
        """
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin")
        keys = ["u k le guin", "ursula k le guin"]
        merge(client, admin["headers"], keys, "Ursula K. Le Guin")

        res = merge(client, admin["headers"], keys, "U. K. Le Guin")

        assert res.json()["name"] == "U. K. Le Guin"
        assert {row.canonical_name for row in db.query(AuthorAlias)} == {
            "U. K. Le Guin"
        }
        [author] = client.get(AUTHORS, headers=admin["headers"]).json()
        assert author["name"] == "U. K. Le Guin"

    def test_an_author_nobody_has_is_not_found(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")

        res = merge(client, admin["headers"], ["nobody at all"], "Somebody")

        assert res.status_code == 404

    def test_another_members_private_author_is_also_not_found(
        self, client, admin, member, make_book
    ):
        """404 and not 403, exactly as an invisible book is: the other answer
        confirms that somebody owns a book by that name."""
        make_book(admin["headers"], title="Diary", author="Anne Frank", is_private=True)

        res = merge(client, member["headers"], ["anne frank"], "Anne Frank")

        assert res.status_code == 404

    def test_a_name_is_library_wide_and_the_shelf_is_not(
        self, client, admin, member, make_book
    ):
        """Where the privacy line actually sits, in one request.

        Folding into a spelling somebody else already folded resolves to their
        canonical name, and that name is not withheld: it is library wide,
        exactly like a collection's name. What is withheld is the **shelf**,
        so the private book credited to that spelling is not counted.

        Withholding the name instead was tried and withdrawn: it made the merge
        gate and the index gate disagree, and the narrower one then leaked what
        the wider one refused.
        """
        make_book(admin["headers"], title="Diary", author="Anne Frank", is_private=True)
        merge(client, admin["headers"], ["anne frank"], "Annelies Marie Frank")
        make_book(member["headers"], title="Night", author="E. Wiesel")

        res = merge(client, member["headers"], ["e wiesel"], "Anne Frank")

        assert res.status_code == 200
        assert res.json()["name"] == "Annelies Marie Frank"
        assert res.json()["book_count"] == 1

    def test_an_author_whose_every_book_is_private_appears_for_nobody_else(
        self, client, admin, member, make_book
    ):
        """The argument the library wide mapping rests on.

        The mapping says who a name means. It never says a book exists, and an
        entry exists only because a book the caller can see is credited to a
        spelling resolving to that person.
        """
        make_book(admin["headers"], title="Diary", author="Anne Frank", is_private=True)
        merge(client, admin["headers"], ["anne frank"], "Annelies Marie Frank")

        assert client.get(AUTHORS, headers=member["headers"]).json() == []
        res = client.get(
            "/api/books",
            params={"author": "Annelies Marie Frank"},
            headers=member["headers"],
        )
        assert res.json()["total"] == 0

    def test_any_member_may_merge(self, client, admin, member, make_book):
        """Reversible, like renaming a collection. Deleting a collection is
        admin only because it cannot be undone; this can."""
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")

        res = merge(client, member["headers"], ["u k le guin"], "Ursula K. Le Guin")

        assert res.status_code == 200

    def test_merging_the_same_spelling_twice_replaces_rather_than_repeats(
        self, client, admin, make_book, db
    ):
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")

        merge(client, admin["headers"], ["u k le guin"], "Ursula Le Guin")
        merge(client, admin["headers"], ["u k le guin"], "Ursula K. Le Guin")

        rows = db.query(AuthorAlias).all()
        assert [(row.alias_key, row.canonical_name) for row in rows] == [
            ("u k le guin", "Ursula K. Le Guin")
        ]

    def test_a_name_already_folded_into_somebody_resolves_to_them(
        self, client, admin, make_book, db
    ):
        """Keeps the map one lookup deep. Without this the new row would point
        at a name that itself points elsewhere."""
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")
        make_book(admin["headers"], title="The Dispossessed", author="Le Guin")
        merge(client, admin["headers"], ["u k le guin"], "Ursula K. Le Guin")

        merge(client, admin["headers"], ["le guin"], "U. K. Le Guin")

        assert {row.canonical_name for row in db.query(AuthorAlias).all()} == {
            "Ursula K. Le Guin"
        }

    def test_rows_pointing_at_a_folded_name_come_along(
        self, client, admin, make_book, db
    ):
        """The other half of keeping the map flat: a row that named somebody
        who has just become a spelling of somebody else."""
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin")
        merge(client, admin["headers"], ["u k le guin"], "Ursula K. Le Guin")

        merge(client, admin["headers"], ["ursula k le guin"], "Le Guin, Ursula K.")

        assert {row.canonical_name for row in db.query(AuthorAlias).all()} == {
            "Le Guin, Ursula K."
        }

    def test_one_lookup_is_always_enough(self, client, admin, make_book, db):
        """The invariant, asserted after the shapes that could break it: three
        merges in a ring, each naming somebody the previous one folded away.

        Following any row one hop further has to change nothing. A row that
        names *itself* satisfies that and is the ordinary way a display name
        gets pinned; a row that names somebody else's spelling does not, and
        would resolve differently the moment the middle row was deleted.

        `authors.resolve_alias_map` flattens whatever it is given, so a chain
        would not be visible from the outside until then.
        """
        make_book(admin["headers"], title="One", author="A One")
        make_book(admin["headers"], title="Two", author="B Two")
        make_book(admin["headers"], title="Three", author="C Three")
        merge(client, admin["headers"], ["a one"], "B Two")
        merge(client, admin["headers"], ["b two"], "C Three")
        merge(client, admin["headers"], ["c three"], "A One")

        rows = {row.alias_key: row.canonical_name for row in db.query(AuthorAlias)}
        assert all(
            rows.get(author_key(name), name) == name for name in rows.values()
        ), rows


class TestMergeRefusesRubbish:
    def test_an_empty_name_to_keep(self, client, admin):
        assert merge(client, admin["headers"], ["someone"], "").status_code == 422

    def test_a_name_with_no_letter_in_it(self, client, admin):
        """It would have an empty key, which no spelling can ever match: the
        merge would look like it worked and fold everybody into nowhere."""
        assert merge(client, admin["headers"], ["someone"], "...").status_code == 422

    def test_no_keys_at_all(self, client, admin):
        assert merge(client, admin["headers"], [], "Somebody").status_code == 422

    def test_more_keys_than_the_ceiling(self, client, admin):
        keys = [f"author {index}" for index in range(51)]
        assert merge(client, admin["headers"], keys, "Somebody").status_code == 422

    def test_a_key_longer_than_the_column(self, client, admin):
        assert merge(client, admin["headers"], ["x" * 501], "Somebody").status_code == 422

    def test_a_name_longer_than_the_column(self, client, admin):
        assert merge(client, admin["headers"], ["someone"], "y" * 301).status_code == 422


class TestUndoingAMerge:
    def test_the_spelling_becomes_its_own_author_again(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Rocannon", author="U. K. Le Guin")
        make_book(admin["headers"], title="The Dispossessed", author="Ursula K. Le Guin")
        merged = merge(
            client, admin["headers"], ["u k le guin"], "Ursula K. Le Guin"
        ).json()
        alias_id = merged["merged"][0]["alias_id"]

        res = client.delete(f"{AUTHORS}/aliases/{alias_id}", headers=admin["headers"])

        assert res.status_code == 204
        body = client.get(AUTHORS, headers=admin["headers"]).json()
        assert [row["name"] for row in body] == ["U. K. Le Guin", "Ursula K. Le Guin"]

    def test_an_alias_that_does_not_exist(self, client, admin):
        assert client.delete(f"{AUTHORS}/aliases/999", headers=admin["headers"]).status_code == 404

    def test_an_id_past_what_the_database_can_hold(self, client, admin):
        """422 rather than the 500 an unbounded id reaches from inside the
        query. Same rule as every other path id in this app."""
        res = client.delete(f"{AUTHORS}/aliases/{2**63}", headers=admin["headers"])
        assert res.status_code == 422

    def test_an_alias_the_caller_cannot_see_is_not_found(
        self, client, admin, member, make_book, db
    ):
        """A member must not be able to confirm, by undoing it, that somebody
        merged a spelling that survives only on a private book."""
        make_book(admin["headers"], title="Diary", author="Anne Frank", is_private=True)
        merge(client, admin["headers"], ["anne frank"], "Annelies Frank")
        alias_id = db.query(AuthorAlias).one().id

        res = client.delete(f"{AUTHORS}/aliases/{alias_id}", headers=member["headers"])

        assert res.status_code == 404


class TestTheCost:
    def test_the_author_index_costs_two_statements(self, client, admin, make_book):
        """One scan of the visible credit lines and one read of the aliases,
        whatever the shelf holds.

        Measured at both ends rather than at one: a claim that the cost does
        not grow is a claim about two shelf sizes, and asserting it over 40
        books alone would pass just as well on a query issued per book.
        """

        def counts() -> tuple[int, int]:
            selects = count_selects(
                lambda: client.get(AUTHORS, headers=admin["headers"])
            )
            # SQLAlchemy renders a newline before FROM, so the space is not
            # part of the match.
            return (
                len([s for s in selects if "FROM books" in s]),
                len([s for s in selects if "FROM author_aliases" in s]),
            )

        make_book(admin["headers"], title="Book 0", author="Author 0")
        assert counts() == (1, 1)

        for index in range(1, 40):
            make_book(admin["headers"], title=f"Book {index}", author=f"Author {index}")
        assert counts() == (1, 1)

    def test_filtering_by_author_costs_two_statements_more(
        self, client, admin, make_book
    ):
        """The listing pays for the index it has to resolve the name against,
        and nothing else: the page and its count are the same two queries they
        were."""
        for index in range(10):
            make_book(admin["headers"], title=f"Book {index}", author="Frank Herbert")

        plain = count_selects(lambda: client.get("/api/books", headers=admin["headers"]))
        filtered = count_selects(
            lambda: client.get(
                "/api/books", params={"author": "Frank Herbert"}, headers=admin["headers"]
            )
        )

        assert len(filtered) - len(plain) == 2


class TestConfirmingAnAuthorityIdentifier:
    """`POST /authors/identifiers`, the uncertain half of the store.

    An identifier on the record a catalogue returned for a Book's own ISBN is
    stored without asking, by `refresh` and by `enrich`. This is what a name
    search produces, and a name is not a key: two authors share one.
    """

    def test_a_confirmed_identifier_is_marked_as_a_persons(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")

        res = confirm(client, admin["headers"], "Sean P. Kane", "1042243212")

        assert res.status_code == 201, res.text
        assert res.json()["provenance"] == "member"

    def test_it_shows_up_on_the_author(self, client, admin, make_book):
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")
        confirm(client, admin["headers"], "Sean P. Kane", "1042243212")

        body = client.get(AUTHORS, headers=admin["headers"]).json()

        [row] = author_named(body, "Sean P. Kane")["identifiers"]
        assert (row["scheme"], row["identifier"]) == ("gnd", "1042243212")

    def test_an_author_nobody_can_see_is_404_not_403(
        self, client, admin, member, make_book
    ):
        """A 403 would confirm that somebody owns a book by that name, which is
        exactly what privacy withholds."""
        make_book(
            admin["headers"], title="Docker", author="Sean P. Kane", is_private=True
        )

        res = confirm(client, member["headers"], "Sean P. Kane", "1042243212")

        assert res.status_code == 404

    def test_retyping_it_to_another_value_is_409(self, client, admin, make_book):
        """The refusal asserted through the API, not merely the absence of a
        PATCH. Retyping is the one operation that can launder a guess into
        something reading like a national library's assertion."""
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")
        confirm(client, admin["headers"], "Sean P. Kane", "1042243212")

        res = confirm(client, admin["headers"], "Sean P. Kane", "9999")

        assert res.status_code == 409
        body = client.get(AUTHORS, headers=admin["headers"]).json()
        [row] = author_named(body, "Sean P. Kane")["identifiers"]
        assert row["identifier"] == "1042243212"

    def test_a_scheme_no_authority_file_is_read_for_is_422(
        self, client, admin, make_book
    ):
        """A closed set, so an unrecognised scheme is a number with no file to
        look it up in."""
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")

        res = client.post(
            f"{AUTHORS}/identifiers",
            json={
                "author": "Sean P. Kane",
                "scheme": "viaf",
                "identifier": "95160850",
            },
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_an_identifier_of_only_spaces_is_422_not_500(
        self, client, admin, make_book
    ):
        """`min_length` passes it and `ck_author_identifiers_bounds` would then
        raise at the database, which is a 500."""
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")

        res = confirm(client, admin["headers"], "Sean P. Kane", "   ")

        assert res.status_code == 422


class TestRemovingAnAuthorityIdentifier:
    def test_a_wrong_one_can_be_removed(self, client, admin, make_book):
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")
        identifier_id = confirm(
            client, admin["headers"], "Sean P. Kane", "1042243212"
        ).json()["id"]

        res = client.delete(
            f"{AUTHORS}/identifiers/{identifier_id}", headers=admin["headers"]
        )

        assert res.status_code == 204
        body = client.get(AUTHORS, headers=admin["headers"]).json()
        assert author_named(body, "Sean P. Kane")["identifiers"] == []

    def test_removing_one_you_cannot_see_the_effect_of_is_404(
        self, client, admin, member, make_book
    ):
        make_book(
            admin["headers"], title="Docker", author="Sean P. Kane", is_private=True
        )
        identifier_id = confirm(
            client, admin["headers"], "Sean P. Kane", "1042243212"
        ).json()["id"]

        res = client.delete(
            f"{AUTHORS}/identifiers/{identifier_id}", headers=member["headers"]
        )

        assert res.status_code == 404

    def test_there_is_no_verb_that_edits_one(self, client, admin, make_book):
        """Tried against the running app rather than asserted in prose. The
        store has `POST` and `DELETE` and deliberately no `PATCH` or `PUT`.

        404 rather than 405 because `main.py`'s API catch-all answers anything
        under `/api` that matched no route, so an unrouted method never reaches
        Starlette's method-not-allowed. What is being pinned is that the request
        changed nothing, which the reread below is the actual evidence for.
        """
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")
        identifier_id = confirm(
            client, admin["headers"], "Sean P. Kane", "1042243212"
        ).json()["id"]

        for verb in (client.patch, client.put):
            res = verb(
                f"{AUTHORS}/identifiers/{identifier_id}",
                json={"identifier": "9999"},
                headers=admin["headers"],
            )
            assert res.status_code in (404, 405), res.text

        body = client.get(AUTHORS, headers=admin["headers"]).json()
        [row] = author_named(body, "Sean P. Kane")["identifiers"]
        assert row["identifier"] == "1042243212"


class TestTheIdentifierListingKeepsThePrivacyRule:
    def test_a_row_for_a_spelling_only_on_a_private_book_is_not_shown(
        self, client, admin, member, make_book
    ):
        """The rows are Library wide, like the aliases. Listing one whose
        spelling survives only on somebody else's Private Book would announce
        that the Book exists."""
        make_book(
            admin["headers"], title="Docker", author="Sean P. Kane", is_private=True
        )
        confirm(client, admin["headers"], "Sean P. Kane", "1042243212")
        make_book(member["headers"], title="Dune", author="Frank Herbert")

        body = client.get(AUTHORS, headers=member["headers"]).json()

        assert all(row["identifiers"] == [] for row in body)
        assert "1042243212" not in str(body)


#: A DNB record carrying an author's GND number in `100 $0`.
#:
#: Shaped after a live MARC21 response. The identifier is the whole reason the
#: DNB is read as MARC rather than Dublin Core, which drops every identifier a
#: record holds.
DNB_RECORD_WITH_GND = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <records><record><recordData>
  <record xmlns="http://www.loc.gov/MARC21/slim">
   <datafield tag="020" ind1=" " ind2=" ">
    <subfield code="a">9783960092353</subfield>
   </datafield>
   <datafield tag="100" ind1="1" ind2=" ">
    <subfield code="0">(DE-588)1042243212</subfield>
    <subfield code="a">Kane, Sean P.</subfield>
    <subfield code="4">aut</subfield>
   </datafield>
   <datafield tag="245" ind1="1" ind2="0">
    <subfield code="a">Praxiswissen Docker</subfield>
   </datafield>
   <datafield tag="300" ind1=" " ind2=" ">
    <subfield code="a">390 Seiten</subfield>
   </datafield>
  </record>
 </recordData></record></records>
 <numberOfRecords>1</numberOfRecords>
</searchRetrieveResponse>"""


class TestWhichBranchMayWriteAnIdentifier:
    """The certain and the uncertain half, exercised against the real handlers.

    This used to be a guard counting call sites in `routers/books.py`, and that
    guard was worth nothing: aliasing the bound method past it took one line,
    and the count stayed at two. What decides the question is which branch the
    handler took, so the branches are driven.
    """

    def test_a_record_found_by_the_books_own_isbn_asserts_its_author(
        self, client, admin, make_book, db
    ):
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="Sean P. Kane")
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        row = db.query(AuthorIdentifier).one()
        assert (row.identifier, row.provenance) == ("1042243212", "catalogue")

    def test_a_record_found_by_title_and_author_asserts_nothing(
        self, client, admin, make_book, db
    ):
        """The book has **no ISBN**, so `enrich` falls to the ranked search
        across every catalogue. A row there is somebody with a similar name,
        which is a candidate and not a match: storing it would merge two people
        behind the Member's back.

        The DNB is given exactly the same record. What differs is the branch.
        """
        book = make_book(admin["headers"], author="Sean P. Kane")
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.json()["found"] is True, res.text
        assert db.query(AuthorIdentifier).count() == 0

    def test_a_refresh_asserts_it_too(self, client, admin, make_book, db):
        """`refresh` is the other handler holding a `Record` the server fetched
        for a verified ISBN, and it already overwrites the author's name from
        it."""
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="Sean P. Kane")
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])

        assert db.query(AuthorIdentifier).one().identifier == "1042243212"

    def test_a_member_picking_a_record_writes_no_identifier_from_the_payload(
        self, client, admin, make_book, db
    ):
        """`enrich/apply` takes a `BookMatch` the client posted, so anything in
        it is a value a Member could have typed. An identifier written from
        there would carry `CATALOGUE` provenance while being somebody's guess,
        which is the laundering the whole store is shaped against.
        """
        book = make_book(admin["headers"], isbn=GERMAN_ISBN)

        res = client.post(
            f"/api/books/{book['id']}/enrich/apply",
            json={
                "source": "dnb",
                "title": "Praxiswissen Docker",
                "author": "Sean P. Kane",
                "isbn13": GERMAN_ISBN,
            },
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert db.query(AuthorIdentifier).count() == 0


LOBID = "https://lobid.org/"
WIKIDATA = "https://www.wikidata.org/w/api.php"

#: The two people the GND spells `Stevenson, Robert Louis`, trimmed to what this
#: endpoint renders. `tests/test_authority.py` holds the full capture and the
#: note on what was removed from it; these are the same two records.
LOBID_SEARCH: dict[str, Any] = {
    "totalItems": 60,
    "member": [
        {
            "gndIdentifier": "118753711",
            "preferredName": "Stevenson, Robert Louis",
            "dateOfBirth": ["1850-11-13"],
            "dateOfDeath": ["1894-12-03"],
            "sameAs": [{"id": "http://www.wikidata.org/entity/Q1512"}],
        },
        {
            "gndIdentifier": "131572873",
            "preferredName": "Stevenson, Robert Louis",
            "sameAs": [{"id": "http://viaf.org/viaf/1148462"}],
        },
    ],
}
LOBID_RECORD = LOBID_SEARCH["member"][0]
WIKIDATA_ITEM: dict[str, Any] = {"query": {"search": [{"title": "Q1512"}]}}
WIKIDATA_NO_ITEM: dict[str, Any] = {"query": {"search": []}}
WIKIDATA_DESCRIPTION = {
    "entities": {
        "Q1512": {
            "descriptions": {
                "en": {"language": "en", "value": "Scottish novelist and poet"}
            }
        }
    }
}
WIKIDATA_VIAF = {
    "claims": {
        "P214": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "property": "P214",
                    "datavalue": {"value": "95207986", "type": "string"},
                }
            }
        ]
    }
}


def _authority_mock(mock, *, lobid):
    mock.get(url__startswith=LOBID).mock(return_value=httpx.Response(200, json=lobid))

    def wikidata(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action")
        if action == "query":
            found = "118753711" in request.url.params.get("srsearch", "")
            return httpx.Response(
                200, json=WIKIDATA_ITEM if found else WIKIDATA_NO_ITEM
            )
        if action == "wbgetentities":
            return httpx.Response(200, json=WIKIDATA_DESCRIPTION)
        return httpx.Response(200, json=WIKIDATA_VIAF)

    mock.get(url__startswith=WIKIDATA).mock(side_effect=wikidata)


class TestWhatTheAuthorityFilesSay:
    """`GET /authors/authority`. Two routes, and `certain` says which one ran."""

    def test_a_stored_identifier_resolves_to_one_certain_record(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Treasure Island", author="R. L. Stevenson")
        confirm(client, admin["headers"], "R. L. Stevenson", "118753711")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            res = client.get(
                f"{AUTHORS}/authority",
                params={"author": "R. L. Stevenson"},
                headers=admin["headers"],
            )

        assert res.status_code == 200, res.text
        [row] = res.json()
        assert row["certain"] is True
        assert row["name"] == "Stevenson, Robert Louis"

    def test_the_suggestion_is_offered_and_nothing_is_renamed(
        self, client, admin, make_book
    ):
        """Settled on 2026-08-24: suggest the authority's spelling and let it be
        overwritten. Taking it is a separate, deliberate merge."""
        make_book(admin["headers"], title="Treasure Island", author="R. L. Stevenson")
        confirm(client, admin["headers"], "R. L. Stevenson", "118753711")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            client.get(
                f"{AUTHORS}/authority",
                params={"author": "R. L. Stevenson"},
                headers=admin["headers"],
            )

        body = client.get(AUTHORS, headers=admin["headers"]).json()
        assert [row["name"] for row in body] == ["R. L. Stevenson"]

    def test_an_author_with_no_identifier_gets_candidates(
        self, client, admin, make_book
    ):
        """A name is not a key: two people are spelled this way in the GND, and
        neither is stored by asking."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_SEARCH)
            res = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Robert Louis Stevenson"},
                headers=admin["headers"],
            )

        rows = res.json()
        assert [row["identifier"] for row in rows] == ["118753711", "131572873"]
        assert not any(row["certain"] for row in rows)

    def test_the_disambiguation_hint_reaches_the_client(
        self, client, admin, make_book
    ):
        """Only one of the two has a Wikidata item. Shown to whoever is
        confirming, never used to pick for them."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_SEARCH)
            rows = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Robert Louis Stevenson"},
                headers=admin["headers"],
            ).json()

        assert [row["wikidata_id"] for row in rows] == ["Q1512", None]
        assert rows[0]["description"] == "Scottish novelist and poet"

    def test_asking_stores_nothing(self, client, admin, make_book, db):
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_SEARCH)
            client.get(
                f"{AUTHORS}/authority",
                params={"author": "Robert Louis Stevenson"},
                headers=admin["headers"],
            )

        assert db.query(AuthorIdentifier).count() == 0

    def test_an_author_nobody_can_see_is_404_not_403(
        self, client, admin, member, make_book
    ):
        """And nothing is asked of an outside service on their behalf either."""
        make_book(
            admin["headers"],
            title="Kidnapped",
            author="Robert Louis Stevenson",
            is_private=True,
        )

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=httpx.Response(200, json=LOBID_SEARCH)
            )
            res = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Robert Louis Stevenson"},
                headers=member["headers"],
            )

        assert res.status_code == 404
        assert route.call_count == 0

    def test_an_unreachable_authority_file_is_503_not_500(
        self, client, admin, make_book
    ):
        """Nothing in this feature is blocked by it, so the client can offer
        "try again" rather than an error page."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=httpx.Response(502))
            res = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Robert Louis Stevenson"},
                headers=admin["headers"],
            )

        assert res.status_code == 503

    def test_a_candidate_can_then_be_confirmed(self, client, admin, make_book):
        """The two halves joined up: a name search offers two people, a person
        picks one, and the row records that a person picked it."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")
        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_SEARCH)
            rows = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Robert Louis Stevenson"},
                headers=admin["headers"],
            ).json()

        res = confirm(
            client, admin["headers"], "Robert Louis Stevenson", rows[0]["identifier"]
        )

        assert res.status_code == 201
        assert res.json()["provenance"] == "member"


class TestSteeringTheAuthoritySearch:
    def test_a_retyped_name_is_what_gets_searched(self, client, admin, make_book):
        """The shelf spells somebody in a form the GND does not use, so the
        author's own name returns the wrong people and there has to be a way to
        retype it."""
        make_book(admin["headers"], title="Kidnapped", author="Bob Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=httpx.Response(200, json=LOBID_SEARCH)
            )
            mock.get(url__startswith=WIKIDATA).mock(
                return_value=httpx.Response(200, json=WIKIDATA_NO_ITEM)
            )
            res = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Bob Stevenson", "q": "Robert Louis Stevenson"},
                headers=admin["headers"],
            )

        assert res.status_code == 200, res.text
        assert route.calls[0].request.url.params["q"] == "Robert Louis Stevenson"

    def test_it_forces_the_search_route_even_when_one_is_stored(
        self, client, admin, make_book
    ):
        """A stored identifier would otherwise resolve as a key and ignore the
        retyped name entirely."""
        make_book(admin["headers"], title="Treasure Island", author="Bob Stevenson")
        confirm(client, admin["headers"], "Bob Stevenson", "118753711")

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=httpx.Response(200, json=LOBID_SEARCH)
            )
            mock.get(url__startswith=WIKIDATA).mock(
                return_value=httpx.Response(200, json=WIKIDATA_NO_ITEM)
            )
            rows = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Bob Stevenson", "q": "Robert Louis Stevenson"},
                headers=admin["headers"],
            ).json()

        assert "/gnd/search" in str(route.calls[0].request.url)
        assert not any(row["certain"] for row in rows)

    def test_an_author_nobody_can_see_is_still_404_with_a_query(
        self, client, admin, member, make_book
    ):
        """`q` steers the search; it does not bypass the access check."""
        make_book(
            admin["headers"], title="Kidnapped", author="Bob Stevenson", is_private=True
        )

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=httpx.Response(200, json=LOBID_SEARCH)
            )
            res = client.get(
                f"{AUTHORS}/authority",
                params={"author": "Bob Stevenson", "q": "Robert Louis Stevenson"},
                headers=member["headers"],
            )

        assert res.status_code == 404
        assert route.call_count == 0


class TestACatalogueLosingToAStoredValueIsReported:
    def test_a_refresh_reports_what_it_could_not_store(
        self, client, admin, make_book
    ):
        """A member's guess outranking a national library used to be a log line.
        It is now on the response of the request that produced it."""
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="Sean P. Kane")
        confirm(client, admin["headers"], "Sean P. Kane", "1111")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            res = client.put(
                f"/api/books/{book['id']}/refresh", headers=admin["headers"]
            )

        [refused] = res.json()["refused_identifiers"]
        assert (refused["asserted"], refused["kept"]) == ("1042243212", "1111")
        assert refused["kept_provenance"] == "member"

    def test_an_ordinary_refresh_reports_nothing(self, client, admin, make_book):
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="Sean P. Kane")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            res = client.put(
                f"/api/books/{book['id']}/refresh", headers=admin["headers"]
            )

        assert res.json()["refused_identifiers"] == []

    def test_a_plain_read_carries_the_field_empty(self, client, admin, make_book):
        """It is on `BookOut`, so every response has it; only the two handlers
        that fetch a catalogue record can ever fill it."""
        book = make_book(admin["headers"], author="Sean P. Kane")

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])

        assert res.json()["refused_identifiers"] == []


class TestAnEnrichmentOnlyStoresASpellingTheBookAdopts:
    """`TestWhichBranchMayWriteAnIdentifier` credits the Book with the
    catalogue's own spelling, so its keys coincide by accident of the fixture
    and it cannot see this. These use a Library spelling the catalogue does not
    share, which is the ordinary case.
    """

    def test_an_ordinary_enrich_stores_nothing_it_cannot_reach(
        self, client, admin, make_book, db
    ):
        """`merge_into` skips `author` when the Book has one and `overwrite` is
        false, which is the default, so the catalogue's spelling is never
        adopted and there is nothing to hang an identifier on."""
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="S. P. Kane")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.json()["book"]["author"] == "S. P. Kane"
        assert db.query(AuthorIdentifier).count() == 0

    def test_an_overwriting_enrich_adopts_the_spelling_and_stores(
        self, client, admin, make_book, db
    ):
        """The other side of the same ordering: with the credit line replaced
        the assertion is evidenced, so it is stored."""
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="S. P. Kane")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            res = client.post(
                f"/api/books/{book['id']}/enrich",
                params={"overwrite": "true"},
                headers=admin["headers"],
            )

        assert res.json()["book"]["author"] == "Sean P. Kane"
        assert db.query(AuthorIdentifier).one().author_key == author_key(
            "Sean P. Kane"
        )

    def test_whatever_an_enrich_stores_can_be_seen_and_deleted(
        self, client, admin, make_book
    ):
        """The end to end form of the guarantee. A row that is written and then
        invisible is unreclaimable, and every author listing reads the whole
        table."""
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="S. P. Kane")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            client.post(
                f"/api/books/{book['id']}/enrich",
                params={"overwrite": "true"},
                headers=admin["headers"],
            )

        body = client.get(AUTHORS, headers=admin["headers"]).json()
        [row] = author_named(body, "Sean P. Kane")["identifiers"]
        assert (
            client.delete(
                f"{AUTHORS}/identifiers/{row['id']}", headers=admin["headers"]
            ).status_code
            == 204
        )

    def test_a_refresh_still_stores_because_it_adopts_the_name(
        self, client, admin, make_book, db
    ):
        """The regression the credit line filter could have caused: `refresh`
        assigns the catalogue's author unconditionally, and the write happens
        after that commit, so it still qualifies."""
        book = make_book(admin["headers"], isbn=GERMAN_ISBN, author="S. P. Kane")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD_WITH_GND)
            )
            silence_catalogues(mock)
            res = client.put(
                f"/api/books/{book['id']}/refresh", headers=admin["headers"]
            )

        assert res.json()["author"] == "Sean P. Kane"
        assert db.query(AuthorIdentifier).one().identifier == "1042243212"
