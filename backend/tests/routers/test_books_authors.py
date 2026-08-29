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
        assert res.json()["identifier"]["provenance"] == "member"

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

    def test_a_subject_heading_scheme_is_422(self, client, admin, make_book):
        """A closed set, so a value outside it is a number with no file behind
        it.

        **The value was `viaf`, then `blbnb`, and both became members of
        `AuthorityScheme` on 2026-08-28.** A refusal test whose subject is a
        plausible future member is a countdown rather than a guard, so this now
        names a `ClassificationScheme` value: `ddc` is what a book is about, and
        the two enums exist so that one column never holds both.
        """
        make_book(admin["headers"], title="Docker", author="Sean P. Kane")

        res = client.post(
            f"{AUTHORS}/identifiers",
            json={
                "author": "Sean P. Kane",
                "scheme": "ddc",
                "identifier": "004",
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
        ).json()["identifier"]["id"]

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
        ).json()["identifier"]["id"]

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
        ).json()["identifier"]["id"]

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
VIAF = "https://viaf.org/"

#: The two people the GND spells `Stevenson, Robert Louis`, trimmed to what this
#: endpoint renders. `tests/test_authority.py` holds the full capture and the
#: note on what was removed from it; these are the same two records.
#:
#: **The first record's `sameAs` used to hold the Wikidata URI alone**, and that
#: stopped being "what this endpoint renders" on 2026-08-28, when confirming a
#: GND began storing the cross references the record carries. A fixture holding
#: one of four made the three that were dropped invisible: every assertion about
#: them would have read as an empty list rather than as a missing fixture. The
#: four are the live values from the same capture.
LOBID_SEARCH: dict[str, Any] = {
    "totalItems": 60,
    "member": [
        {
            "gndIdentifier": "118753711",
            "preferredName": "Stevenson, Robert Louis",
            "dateOfBirth": ["1850-11-13"],
            "dateOfDeath": ["1894-12-03"],
            "sameAs": [
                {"id": "http://id.loc.gov/rwo/agents/n78088964"},
                {"id": "http://viaf.org/viaf/95207986"},
                {"id": "http://www.wikidata.org/entity/Q1512"},
                {"id": "https://isni.org/isni/0000000122831567"},
                # Not a person in any file this app can look up. Kept so the
                # parser is seen to ignore it rather than assumed to.
                {"id": "https://en.wikipedia.org/wiki/Robert_Louis_Stevenson"},
            ],
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
WIKIDATA_ISNI = {
    "claims": {
        "P213": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "property": "P213",
                    "datavalue": {"value": "0000000122831567", "type": "string"},
                    "datatype": "external-id",
                },
                "type": "statement",
                "rank": "normal",
            }
        ]
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


#: `GET viaf.org/viaf/search?query=local.viafID = 95207986&recordSchema=BriefVIAF`,
#: trimmed to one heading block. `tests/test_authority.py` holds the fuller
#: capture and the note on the `v:sid` list-or-string trap; these are the same
#: live values, and the cluster is the one `LOBID_RECORD`'s `sameAs` names.
#:
#: `DNB|118753711` is what makes this a cluster this app will use: it names the
#: confirmed record back, so the person is verified rather than assumed.
VIAF_CLUSTER: dict[str, Any] = {
    "searchRetrieveResponse": {
        "records": {
            "record": {
                "recordData": {
                    "v:VIAFCluster": {
                        "v:viafID": "95207986",
                        "v:mainHeadings": {
                            "v:data": {
                                "v:text": "Stevenson, Robert Louis, 1850-1894.",
                                "v:sources": {
                                    "v:sid": [
                                        "DNB|118753711",
                                        "BLBNB|000560463",
                                        "ARBABN|000035867",
                                        "BNE|981060880923108606",
                                        "PTBNP|27012",
                                        "ICCU|CFIV000439",
                                        "BNCHL|10000000000000000007303",
                                    ]
                                },
                            }
                        },
                    }
                }
            }
        }
    }
}


#: The six national properties on `Q1512` as Wikidata answers them, and the two
#: values that tell the two suppliers apart.
#:
#: Live, measured 2026-08-28. BNE and BNCHL differ from what `VIAF_CLUSTER`
#: carries, because each is one library's old control number against its new
#: one, so a test that sees `XX900250` is looking at Wikidata's answer and
#: nothing else. `tests/test_authority.py` carries the whole table.
WIKIDATA_NATIONAL = {
    "P4619": "000560463",
    "P3788": "000035867",
    "P950": "XX900250",
    "P1005": "27012",
    "P396": "CFIV000439",
    "P1890": "000034753",
}


def _wikidata_claims(prop: str, value: str) -> dict:
    """A `wbgetclaims` body for one property, in the shape `WIKIDATA_VIAF` has."""
    return {
        "claims": {
            prop: [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "property": prop,
                        "datavalue": {"value": value, "type": "string"},
                        "datatype": "external-id",
                    },
                    "type": "statement",
                    "rank": "normal",
                }
            ]
        }
    }


def _authority_mock(mock, *, lobid, national=False):
    """Route the three hosts a confirmation reaches.

    `national` is **False by default**, so a test that has not asked for the
    Wikidata fallback cannot pass because the mock quietly supplied it: an
    unasked-for national property falls through to the `P214` body, which holds
    no such key and therefore answers nothing.
    """
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
        # Split on the property, for the reason `tests/test_authority.py`'s
        # router gives: answering every `wbgetclaims` with the VIAF body means a
        # `P213` request finds no `P213` key, `_claim` returns None, and the
        # ISNI comparison cannot fire. That looks exactly like agreement.
        if request.url.params.get("property") == "P213":
            return httpx.Response(200, json=WIKIDATA_ISNI)
        prop = request.url.params.get("property")
        if national and prop in WIKIDATA_NATIONAL:
            return httpx.Response(
                200, json=_wikidata_claims(prop, WIKIDATA_NATIONAL[prop])
            )
        return httpx.Response(200, json=WIKIDATA_VIAF)

    mock.get(url__startswith=WIKIDATA).mock(side_effect=wikidata)
    # The third host, and it is asked only on a confirmation. Routed here rather
    # than per test because an unrouted host raises inside `_viaf_json`, which
    # swallows it and returns nothing: every assertion about the national
    # identifiers would then read as "VIAF said nothing" rather than as a
    # missing mock. The same trap `LOBID_SEARCH`'s note records for `sameAs`.
    mock.get(url__startswith=VIAF).mock(
        return_value=httpx.Response(200, json=VIAF_CLUSTER)
    )


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

    def test_a_lookup_costs_no_viaf_request_on_either_route(
        self, client, admin, make_book
    ):
        """**The budget argument for the whole feature rests on this**, and
        nothing was pinning it. `authority.py` claims VIAF is asked only on a
        confirmation; five candidates times three VIAF calls would be fifteen
        outbound requests on a read somebody is about to narrow to one.

        The `certain` gate in `national_identifiers` does not stop this path:
        `author_authority` calls `resolve`, which produces `certain=True`. What
        stops it is that `_cross_references_for` is the only caller, and that is
        a fact about the router rather than about `authority.py`, so it is
        asserted here and against a VIAF route that really is mocked. Without
        the mock an unrouted request raises inside `_viaf_json`, which swallows
        it, and this would pass for the wrong reason.

        Both routes, because they are different code paths: a stored identifier
        resolves, and a name searches.
        """
        make_book(admin["headers"], title="Treasure Island", author="R. L. Stevenson")
        confirm(client, admin["headers"], "R. L. Stevenson", "118753711")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            client.get(
                f"{AUTHORS}/authority",
                params={"author": "R. L. Stevenson"},
                headers=admin["headers"],
            )
            _authority_mock(mock, lobid=LOBID_SEARCH)
            client.get(
                f"{AUTHORS}/authority",
                params={"author": "R. L. Stevenson", "q": "Stevenson"},
                headers=admin["headers"],
            )
            hosts = [call.request.url.host for call in mock.calls]

        assert hosts, "no request was made, so this asserts nothing"
        assert "viaf.org" not in hosts

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
        assert res.json()["identifier"]["provenance"] == "member"


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


class TestConfirmingStoresTheCrossReferencesThatCameWithTheRecord:
    """`POST /authors/identifiers` re-reads the record and keeps its `sameAs`.

    A person confirms a **record**, not a number, and that record already
    asserts this person's ISNI, LCNAF number, VIAF cluster and Wikidata item,
    and names the VIAF cluster that carries their six national library numbers.
    """

    def test_the_ten_land_beside_the_confirmed_number(
        self, client, admin, make_book
    ):
        """Four from the GND record's own `sameAs`, six from the cluster it
        names. The split matters because only the second half costs a
        request."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            res = confirm(
                client, admin["headers"], "Robert Louis Stevenson", "118753711"
            )

        assert res.status_code == 201, res.text
        body = res.json()
        assert body["identifier"]["scheme"] == "gnd"
        assert {row["scheme"]: row["identifier"] for row in body["cross_references"]} == {
            "isni": "0000000122831567",
            "lcnaf": "n78088964",
            "viaf": "95207986",
            "wikidata": "Q1512",
            "blbnb": "000560463",
            "arbabn": "000035867",
            "bne": "981060880923108606",
            "ptbnp": "27012",
            "iccu": "CFIV000439",
            "bnchl": "10000000000000000007303",
        }

    async def test_one_deadline_covers_all_three_hosts_a_confirmation_reaches(self):
        """**Two places can drop it and neither is observable through a result.**
        `_cross_references_for` builds one absolute deadline and hands it to
        `resolve` and to `national_identifiers`; the VIAF calls then go through
        `fetch.get` while lobid and Wikidata go through `fetch.get_once`, so the
        one deadline test in `test_authority.py` patches a function this path
        never calls. And `fetch.DeadlineExceeded` is an `httpx.HTTPError`, which
        `_viaf_json` turns into the same empty mapping as any other failure, so
        no assertion on the returned identifiers can see it either.

        What it costs to get wrong: `POST /authors/identifiers` holds a
        `DbSession` across every await, so a lost deadline takes the hold from a
        bounded 8.0s to as much as 38s, which is the `QueuePool` exhaustion
        `authority.DEADLINE_SECONDS` exists to prevent.

        Asserting **one distinct value** rather than a specific one, because
        that catches the third mistake in the same family: calling
        `deadline_from_now()` twice would give two values a few microseconds
        apart and bound each half separately.
        """
        import fetch
        from routers import books as books_router

        seen: list[float | None] = []

        async def once(url, *, params=None, limit=None, deadline=None):
            seen.append(deadline)
            body = LOBID_RECORD if "lobid" in url else WIKIDATA_ITEM
            return fetch.Fetched(200, httpx.Response(200, json=body).content, None)

        async def get(client, url, *, params=None, limit=None, deadline=None):
            seen.append(deadline)
            return fetch.Fetched(
                200, httpx.Response(200, json=VIAF_CLUSTER).content, None
            )

        original_once, original_get = fetch.get_once, fetch.get
        fetch.get_once, fetch.get = once, get
        try:
            await books_router._cross_references_for("118753711")
        finally:
            fetch.get_once, fetch.get = original_once, original_get

        assert len(seen) >= 2, seen
        assert len(set(seen)) == 1, seen
        assert None not in seen

    def test_viaf_being_down_costs_the_national_ones_and_nothing_else(
        self, client, admin, make_book
    ):
        """The GND record is the supplier and the cluster is the enrichment, so
        an outage at the second must not cost the first or the confirmation.

        **What this now pins is narrower than its name**, and the narrowing is
        the point rather than an oversight. Since the Wikidata fallback shipped,
        a VIAF outage does not cost the six by itself: it costs them only where
        Wikidata has nothing either, which is what `national=False` on the mock
        arranges. The test below is the other half and stores all six through
        the same outage.
        """
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            mock.get(url__startswith=VIAF).mock(return_value=httpx.Response(503))
            res = confirm(
                client, admin["headers"], "Robert Louis Stevenson", "118753711"
            )

        assert res.status_code == 201, res.text
        schemes = sorted(row["scheme"] for row in res.json()["cross_references"])
        assert schemes == ["isni", "lcnaf", "viaf", "wikidata"]

    def test_wikidata_supplies_them_when_viaf_cannot(
        self, client, admin, make_book
    ):
        """The other side of the test above, and the reason it is no longer the
        whole story: with a second supplier the six survive a VIAF outage.

        **The two disagreeing values are what make this a real assertion.** BNE
        and BNCHL are stored as `XX900250` and `000034753`, which are Wikidata's
        numbers; `VIAF_CLUSTER` carries `981060880923108606` and
        `10000000000000000007303` for the same two. So this cannot pass by
        accidentally reading the cluster. `docs/decisions.md` carries the
        measurement: each pair is one library's old control number against its
        new one, which is why comparing the two suppliers would drop both
        schemes rather than confirming them.
        """
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD, national=True)
            mock.get(url__startswith=VIAF).mock(return_value=httpx.Response(503))
            res = confirm(
                client, admin["headers"], "Robert Louis Stevenson", "118753711"
            )

        assert res.status_code == 201, res.text
        stored = {row["scheme"]: row["identifier"] for row in res.json()["cross_references"]}
        assert stored == {
            "isni": "0000000122831567",
            "lcnaf": "n78088964",
            "viaf": "95207986",
            "wikidata": "Q1512",
            "blbnb": "000560463",
            "arbabn": "000035867",
            "bne": "XX900250",
            "ptbnp": "27012",
            "iccu": "CFIV000439",
            "bnchl": "000034753",
        }

    def test_a_working_viaf_is_never_second_guessed_by_wikidata(
        self, client, admin, make_book
    ):
        """The diagonal of the test above, at the level a Member sees. Both
        suppliers are answering and holding different numbers for two of the
        six, and what is stored is VIAF's: one supplier speaks per confirmation.

        Without this, a change that merged the two would still store ten rows
        and every count and every scheme list would be unchanged."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD, national=True)
            res = confirm(
                client, admin["headers"], "Robert Louis Stevenson", "118753711"
            )

        stored = {row["scheme"]: row["identifier"] for row in res.json()["cross_references"]}
        assert stored["bne"] == "981060880923108606"
        assert stored["bnchl"] == "10000000000000000007303"

    def test_they_show_up_on_the_author(self, client, admin, make_book):
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            confirm(client, admin["headers"], "Robert Louis Stevenson", "118753711")

        listed = author_named(
            client.get(AUTHORS, headers=admin["headers"]).json(),
            "Robert Louis Stevenson",
        )["identifiers"]

        assert sorted(row["scheme"] for row in listed) == [
            "arbabn",
            "blbnb",
            "bnchl",
            "bne",
            "gnd",
            "iccu",
            "isni",
            "lcnaf",
            "ptbnp",
            "viaf",
            "wikidata",
        ]

    def test_a_client_cannot_supply_its_own(self, client, admin, make_book):
        """**The rule `record_catalogue_assertions` states, kept on the other
        write that can reach this table.** A payload the client posted back
        would let a Member type ten numbers and have them stored as though a
        national library had said so. The identifier is the only thing the
        caller contributes and it is a key, so exactly one record answers to it,
        and the record is what is read.
        """
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            res = client.post(
                f"{AUTHORS}/identifiers",
                json={
                    "author": "Robert Louis Stevenson",
                    "scheme": "gnd",
                    "identifier": "118753711",
                    "cross_references": [
                        {"scheme": "isni", "identifier": "0000000000000001"}
                    ],
                },
                headers=admin["headers"],
            )

        assert res.status_code == 201, res.text
        [isni] = [
            row for row in res.json()["cross_references"] if row["scheme"] == "isni"
        ]
        assert isni["identifier"] == "0000000122831567"

    def test_the_authority_file_being_down_does_not_fail_the_confirmation(
        self, client, admin, make_book
    ):
        """The confirmation is what the Member asked for; the cross references
        are what came with it. Nothing in this feature is blocked by lobid being
        unreachable."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=httpx.Response(503))
            res = confirm(
                client, admin["headers"], "Robert Louis Stevenson", "118753711"
            )

        assert res.status_code == 201, res.text
        assert res.json()["cross_references"] == []

    def test_a_scheme_this_app_cannot_resolve_fetches_nothing(
        self, client, admin, make_book
    ):
        """GND is the one scheme with a file this app can read. A confirmation
        under any other is a number a Member typed with no record behind it, so
        there is nothing to read cross references off and nothing is asked."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")

        with respx.mock(assert_all_called=False) as mock:
            lobid = mock.get(url__startswith=LOBID).mock(
                return_value=httpx.Response(200, json=LOBID_RECORD)
            )
            res = confirm(
                client,
                admin["headers"],
                "Robert Louis Stevenson",
                "0000000122831567",
                scheme="isni",
            )

            assert not lobid.called

        assert res.status_code == 201, res.text
        assert res.json()["cross_references"] == []

    def test_a_contested_cross_reference_is_not_stored(
        self, client, admin, make_book
    ):
        """End to end, the rule `authority.cross_references` applies: where the
        two files name different VIAF clusters, storing either is resolution by
        precedence."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")
        disagreeing = {
            "claims": {"P214": [{"mainsnak": {"datavalue": {"value": "999"}}}]}
        }

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(
                return_value=httpx.Response(200, json=LOBID_RECORD)
            )

            def wikidata(request: httpx.Request) -> httpx.Response:
                action = request.url.params.get("action")
                if action == "query":
                    return httpx.Response(200, json=WIKIDATA_ITEM)
                if action == "wbgetentities":
                    return httpx.Response(200, json=WIKIDATA_DESCRIPTION)
                return httpx.Response(200, json=disagreeing)

            mock.get(url__startswith=WIKIDATA).mock(side_effect=wikidata)
            res = confirm(
                client, admin["headers"], "Robert Louis Stevenson", "118753711"
            )

        schemes = [row["scheme"] for row in res.json()["cross_references"]]
        assert "viaf" not in schemes
        assert "lcnaf" in schemes


class TestTheOutwardWikipediaLink:
    """`GET /authors/wikipedia`. #89, the second button on an author card.

    **The gate is identity, not language, and it is what this endpoint is.** A
    row comes back for an author carrying a confirmed Wikidata identifier and
    for nobody else, so the button being offered is a fact about the shelf
    rather than about the network. The language chain and the degradation are
    `authority.wikipedia_articles`' and are tested there; what is tested here is
    the gate, the locale, and that an outage does not cost the button.
    """

    @staticmethod
    def _sitelinks(mock, **by_item):
        """Route `wbgetentities` to a sitelinks body, and count the calls."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("action") != "wbgetentities":
                return httpx.Response(200, json={})
            calls.append(request.url.params.get("sitefilter") or "")
            return httpx.Response(
                200,
                json={
                    "entities": {
                        item: {
                            "id": item,
                            "sitelinks": {
                                site: {"site": site, "title": "T", "url": url}
                                for site, url in links.items()
                            },
                        }
                        for item, links in by_item.items()
                    }
                },
            )

        mock.get(url__startswith=WIKIDATA).mock(side_effect=handler)
        return calls

    def test_an_author_nobody_confirmed_gets_no_row_and_costs_no_request(
        self, client, admin, make_book
    ):
        """**Most libraries are this case**, and the endpoint has to be free in
        it: confirming an identifier is a deliberate act per person, so a shelf
        of a thousand authors with none confirmed must not reach Wikidata at
        all."""
        make_book(admin["headers"], title="Dune", author="Frank Herbert")

        with respx.mock(assert_all_called=False) as mock:
            calls = self._sitelinks(mock)
            res = client.get(f"{AUTHORS}/wikipedia", headers=admin["headers"])

        assert res.status_code == 200, res.text
        assert res.json() == []
        assert calls == []

    def test_a_confirmed_author_gets_a_link_in_the_locale_asked_for(
        self, client, admin, make_book
    ):
        """The locale is the app's, passed explicitly, and never the browser's:
        a German browser reading the app in English must not be sent to German
        Wikipedia. It reaches Wikidata as the `sitefilter`."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")
        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            confirm(client, admin["headers"], "Robert Louis Stevenson", "118753711")

        with respx.mock(assert_all_called=False) as mock:
            calls = self._sitelinks(
                mock,
                Q1512={
                    "dewiki": "https://de.wikipedia.org/wiki/Robert_Louis_Stevenson",
                    "enwiki": "https://en.wikipedia.org/wiki/Robert_Louis_Stevenson",
                },
            )
            res = client.get(
                f"{AUTHORS}/wikipedia",
                params={"lang": "de"},
                headers=admin["headers"],
            )

        assert res.status_code == 200, res.text
        [row] = res.json()
        assert row["key"] == "robert louis stevenson"
        assert row["language"] == "de"
        assert row["url"] == "https://de.wikipedia.org/wiki/Robert_Louis_Stevenson"
        assert calls == ["dewiki|enwiki"]

    def test_wikidata_being_down_costs_the_language_and_not_the_button(
        self, client, admin, make_book
    ):
        """**Never a 503**, which is the difference between this and
        `GET /authors/authority`. Nothing here is a supplier: the row degrades
        to the Wikidata item's own page, which still names the confirmed person,
        so the reader always has somewhere to go."""
        make_book(admin["headers"], title="Kidnapped", author="Robert Louis Stevenson")
        with respx.mock(assert_all_called=False) as mock:
            _authority_mock(mock, lobid=LOBID_RECORD)
            confirm(client, admin["headers"], "Robert Louis Stevenson", "118753711")

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=WIKIDATA).mock(
                return_value=httpx.Response(503, text="down")
            )
            res = client.get(f"{AUTHORS}/wikipedia", headers=admin["headers"])

        assert res.status_code == 200, res.text
        [row] = res.json()
        assert row["url"] == "https://www.wikidata.org/wiki/Q1512"
        assert row["language"] is None

    def test_a_language_this_app_does_not_speak_is_refused(
        self, client, admin
    ):
        """A `Locale`, so the closed set is the server's. Without that the value
        would reach a `sitefilter` this app never wrote."""
        res = client.get(
            f"{AUTHORS}/wikipedia", params={"lang": "xx"}, headers=admin["headers"]
        )

        assert res.status_code == 422, res.text

    def test_it_needs_a_session_like_every_other_author_route(self, client):
        res = client.get(f"{AUTHORS}/wikipedia")

        assert res.status_code == 401, res.text
