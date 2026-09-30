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

import httpx
import respx

from models import Book, Tag
from tags import MAX_TAGS_PER_BOOK
from tests.helpers import (
    DNB,
    GOOGLE_BOOKS,
    OPEN_LIBRARY_SEARCH,
    silence_catalogues,
    sru_response,
)
from tests.routers.test_books_classifications import DNB_RECORD, GERMAN_ISBN
from tests.routers.test_books_search import volume


def _methods(route) -> frozenset[str]:
    """The methods a route answers. `APIRoute.methods` is typed optional."""
    return frozenset(route.methods or ())


def _names_a_route_can_receive(route) -> frozenset[str]:
    """Every name this route can be handed one under, wherever it arrives.

    **Three places, because a body was only one of them.** Measured: the
    repair landed as a **query parameter**, needing no body at all, and an arm
    reading the body alone stayed green while the regression it records was
    closed. Path parameters are read for the same reason and cost nothing.

    Off `body_field` and `dependant`, which FastAPI builds from the handler's
    signature, so this answers for a body declared as a model and for one
    declared inline.
    """
    body = getattr(route, "body_field", None)
    fields: frozenset[str] = frozenset()
    if body is not None:
        annotation = body.field_info.annotation
        fields = frozenset(getattr(annotation, "model_fields", None) or ())
    parameters = frozenset(
        parameter.name
        for parameter in [*route.dependant.query_params, *route.dependant.path_params]
    )
    return fields | parameters


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

    def test_it_appears_in_the_list_once_a_book_carries_it(
        self, client, admin, make_book
    ):
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"])

        names = {
            row["name"]
            for row in client.get("/api/books/tags", headers=admin["headers"]).json()
        }
        assert "Holiday reads" in names

    def test_until_then_it_is_in_nobody_s_list(self, client, admin):
        """A tag on no book is a name and nothing else, and the list is the
        library's vocabulary. Creating one and attaching it are two requests,
        and that gap is where a name typed against a private book used to reach
        everybody. `TestWhoMayBeToldATagExists` is the rule; this is the half
        of it that costs the member who typed the name."""
        client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        )

        names = {
            row["name"]
            for row in client.get("/api/books/tags", headers=admin["headers"]).json()
        }
        assert "Holiday reads" not in names

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

    def test_a_control_character_is_removed_from_the_name(self, client, admin):
        """`name` is unique, so an invisible character is a second tag spelled
        like the first. It is not whitespace, so the collapse alone left it."""
        res = client.post(
            "/api/books/tags",
            json={"name": "Holiday\u0000reads"},
            headers=admin["headers"],
        )

        assert res.json()["name"] == "Holidayreads"

    def test_a_name_pasted_out_of_two_lines_keeps_the_break_as_a_space(
        self, client, admin
    ):
        """The half a strip of every control character would take silently. A
        newline is whitespace, so it separates the words rather than welding
        them: only a value that may be followed as a link wants the weld."""
        res = client.post(
            "/api/books/tags",
            json={"name": "Holiday\nreads"},
            headers=admin["headers"],
        )

        assert res.json()["name"] == "Holiday reads"

    def test_a_name_of_only_control_characters_is_refused(self, client, admin):
        """The same refusal a name of only spaces gets, and for the same
        reason: what it leaves is a row nobody can see or find again."""
        res = client.post(
            "/api/books/tags",
            json={"name": "\u0000\u0001"},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_an_empty_name_is_refused(self, client, admin):
        res = client.post("/api/books/tags", json={"name": ""}, headers=admin["headers"])
        assert res.status_code == 422

    def test_requires_authentication(self, client):
        assert client.post("/api/books/tags", json={"name": "X"}).status_code == 401


class TestPuttingOneOnABook:
    """The ceiling every writer now shares.

    It bound the CSV importer alone while it lived in that parser, so the 4000
    tags on one Book its measured failure produced stayed reachable here, one
    request at a time.

    **Refused rather than dropped, which is where this differs from an import.**
    A member pressed one button for one tag, so a 200 with the tag missing is
    the picker lying to them; an import is a file of thousands and reaches its
    ceiling quietly by design.
    """

    def fill(self, db, book_id, how_many):
        book = db.get(Book, book_id)
        for index in range(how_many):
            row = Tag(name=f"filler {index}", category="custom", is_predefined=False)
            db.add(row)
            book.tags.append(row)
        db.commit()

    def test_a_tag_lands_on_the_book(self, client, admin, make_book):
        book = make_book(admin["headers"])
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()

        res = client.post(
            f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert [carried["name"] for carried in res.json()["tags"]] == ["Holiday reads"]

    def test_a_book_at_its_ceiling_refuses_another(self, client, admin, make_book, db):
        book = make_book(admin["headers"])
        self.fill(db, book["id"], MAX_TAGS_PER_BOOK)
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()

        res = client.post(
            f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
        )

        assert res.status_code == 400
        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert len(detail["tags"]) == MAX_TAGS_PER_BOOK

    def test_a_book_one_short_still_takes_one(self, client, admin, make_book, db):
        """The diagonal, so the refusal above is not an off by one refusing every
        book."""
        book = make_book(admin["headers"])
        self.fill(db, book["id"], MAX_TAGS_PER_BOOK - 1)
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()

        res = client.post(
            f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert len(res.json()["tags"]) == MAX_TAGS_PER_BOOK

    def test_a_full_book_still_answers_for_a_tag_it_already_has(
        self, client, admin, make_book, db
    ):
        """Asking again for something already there is not a refusal, so a client
        retrying a request it did not see the answer to gets the book back."""
        book = make_book(admin["headers"])
        self.fill(db, book["id"], MAX_TAGS_PER_BOOK)
        carried = client.get(
            f"/api/books/{book['id']}", headers=admin["headers"]
        ).json()["tags"][0]

        res = client.post(
            f"/api/books/{book['id']}/tags/{carried['id']}", headers=admin["headers"]
        )

        assert res.status_code == 200


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


class TestTheKeyTheClientTranslatesBy:
    """The name is English; the key is what a German name is looked up by.

    Sent on every tag, because the client has no other way to tell a seeded row
    from one the library invented and named the same thing.
    """

    def test_a_seeded_tag_carries_its_key(self, client, admin):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        computing = next(tag for tag in tags if tag["name"] == "Computing")
        assert computing["key"] == "computing"

    def test_an_invented_tag_carries_none(self, client, admin):
        created = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        )

        assert created.json()["key"] is None

    def test_a_key_this_version_does_not_know_is_forgotten(
        self, client, admin, db, make_book
    ):
        """Not a 500, which is what refusing the row would cost.

        A library moved back to an older image holds keys that version never
        had. The tag list is one response for the whole vocabulary and is
        fetched on nearly every page, so one unrecognised row would take every
        one of them down.

        **A book carries it, which is what puts the row in the list at all.**
        An unrecognised key is not the seeded exemption's subject, by the arm
        below, so without a carrier there would be no row here to read a key
        off and this would pass for the wrong reason.
        """
        stored = db.query(Tag).filter(Tag.name == "Computing").one()
        stored.key = "quantum_gardening"
        db.commit()
        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/tags/{stored.id}", headers=admin["headers"]
        )

        res = client.get("/api/books/tags", headers=admin["headers"])

        assert res.status_code == 200
        computing = next(tag for tag in res.json() if tag["name"] == "Computing")
        assert computing["key"] is None

    def test_a_key_this_version_does_not_know_is_not_the_seeded_exemption(
        self, client, admin, db
    ):
        """What the exemption is for is that the name is in this version's own
        seed list, and a key written by a newer version says the opposite: that
        row was seeded by a release this one does not have, under a name this
        one does not ship. `is_predefined` still says true, which is why the
        rule reads `known_key` and not the flag or a null check.

        The cost is one row leaving the picker until a book carries it, and
        `tags._is_seeded` states it.
        """
        stored = db.query(Tag).filter(Tag.name == "Computing").one()
        stored.key = "quantum_gardening"
        db.commit()

        names = {
            row["name"]
            for row in client.get("/api/books/tags", headers=admin["headers"]).json()
        }
        assert "Computing" not in names


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
        """A tag on one visible book and one private one counts the visible one.

        The row is present here because the public book carries it, which is
        what separates this from `TestWhoMayBeToldATagExists`: that rule is
        about the tag whose **only** books are hidden.
        """
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        shared = make_book(admin["headers"], title="Shared")
        diary = make_book(admin["headers"], title="Diary", is_private=True)
        for book in (shared, diary):
            client.post(
                f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
            )

        tags = client.get("/api/books/tags", headers=member["headers"]).json()
        counted = next(row for row in tags if row["id"] == tag["id"])
        assert counted["book_count"] == 1

    def test_a_trashed_book_is_not_counted(self, client, admin, make_book):
        """Two books carry it and one goes to the trash, so the row stays and
        the number falls. With one book the row leaves the list entirely, which
        is `TestWhoMayBeToldATagExists`'s subject and not this one's."""
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        kept = make_book(admin["headers"], title="Kept")
        binned = make_book(admin["headers"], title="Binned")
        for book in (kept, binned):
            client.post(
                f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
            )
        client.delete(f"/api/books/{binned['id']}", headers=admin["headers"])

        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        counted = next(row for row in tags if row["id"] == tag["id"])
        assert counted["book_count"] == 1

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


class TestTheTagFilterSurvivesADigitThatIsNotOne:
    """`?tags=` and a Unicode digit was a 500, from the same defect as the ISBN.

    `dependencies.row_ids` gated on `str.isdigit()` and then called `int()`.
    A superscript two, `U+00B2`, satisfies the first and raises out of the
    second, so a link with one in it left the route as an unhandled
    `ValueError`. This is the second site of the pair that
    `test_house_rules.py::TestAnAlphanumericPredicateIsAlwaysNarrowedToAscii` now stops
    coming back, and the one reachable without any body at all.

    **The contract that decides the status code is `row_ids`'s own**, stated in
    its docstring and pinned next door as "a link is not a form": a token it
    cannot read is dropped rather than refused, because a filter that 422s turns
    a stale bookmark into an error page. So the answer here is 200 with the
    readable ids honoured, not 422.
    """

    SUPERSCRIPT_TWO = "²"

    def test_an_unreadable_id_is_dropped_rather_than_raising(
        self, client, admin, make_book
    ):
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        book = make_book(admin["headers"], title="Tagged")
        client.post(f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"])
        make_book(admin["headers"], title="Untagged")

        res = client.get(
            "/api/books",
            params={"tags": f"{tag['id']},{self.SUPERSCRIPT_TWO}"},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert [row["title"] for row in res.json()["items"]] == ["Tagged"]

    def test_a_filter_of_nothing_readable_still_answers(self, client, admin, make_book):
        """The arm that keeps the test above from passing on a `row_ids` that
        ignores its argument entirely."""
        make_book(admin["headers"], title="Untagged")

        res = client.get(
            "/api/books",
            params={"tags": self.SUPERSCRIPT_TWO},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert [row["title"] for row in res.json()["items"]] == ["Untagged"]


class TestWhoMayBeToldATagExists:
    """A tag whose every book is hidden from you is not in your vocabulary.

    The channel: a member mints a tag off a book nobody else may read, through
    an import or through create-then-attach, and every other member reads the
    name on their next page load with a `book_count` of zero. The count had
    been scoped for privacy and the row set had not, and scoping the count is
    what made the unscoped rows legible: a zero beside a custom tag selected
    exactly the tags whose every book was invisible.

    `tags.Vocabulary` is where the rule lives and its docstring carries what
    stays open. These are the behaviours, one each.
    """

    def _hidden_tag(self, client, owner, make_book, name="Divorce Law"):
        tag = client.post(
            "/api/books/tags", json={"name": name}, headers=owner["headers"]
        ).json()
        book = make_book(owner["headers"], title="A private matter", is_private=True)
        client.post(
            f"/api/books/{book['id']}/tags/{tag['id']}", headers=owner["headers"]
        )
        return tag

    def _names(self, client, who):
        return {row["name"] for row in client.get("/api/books/tags", headers=who["headers"]).json()}

    def test_a_tag_only_on_another_member_s_private_book_is_not_listed(
        self, client, admin, member, make_book
    ):
        self._hidden_tag(client, admin, make_book)

        assert "Divorce Law" not in self._names(client, member)

    def test_its_owner_still_sees_it(self, client, admin, member, make_book):
        """The diagonal for the arm above: a rule that hid it from everybody
        would pass that test and be a different defect."""
        self._hidden_tag(client, admin, make_book)

        assert "Divorce Law" in self._names(client, admin)

    def test_a_tag_on_a_book_you_can_see_is_listed(
        self, client, admin, member, make_book
    ):
        tag = client.post(
            "/api/books/tags", json={"name": "Holiday reads"}, headers=admin["headers"]
        ).json()
        book = make_book(admin["headers"], title="Shared")
        client.post(f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"])

        assert "Holiday reads" in self._names(client, member)

    def test_the_seeded_vocabulary_is_listed_to_everybody(self, client, member):
        """Seeded rows carry no books, so only the exemption keeps them. Its
        subject is `key`, which the seeder writes and a rename clears."""
        rows = client.get("/api/books/tags", headers=member["headers"]).json()

        assert [row for row in rows if row["is_predefined"]]
        assert all(row["key"] for row in rows if row["is_predefined"])

    def test_attaching_a_tag_you_may_not_see_is_a_404(
        self, client, admin, member, make_book
    ):
        """The stronger channel: `book_to_out` returns the book with its tags,
        so attaching a guessed id to a book you own handed back the name."""
        hidden = self._hidden_tag(client, admin, make_book)
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            f"/api/books/{mine['id']}/tags/{hidden['id']}", headers=member["headers"]
        )

        assert response.status_code == 404

    def test_a_bulk_add_of_a_tag_you_may_not_see_is_a_404(
        self, client, admin, member, make_book
    ):
        hidden = self._hidden_tag(client, admin, make_book)
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            "/api/books/bulk",
            json={"action": "add_tag", "book_ids": [mine["id"]], "value": hidden["id"]},
            headers=member["headers"],
        )

        assert response.status_code == 404

    def test_removing_a_tag_you_may_not_see_is_the_200_an_unused_id_gets(
        self, client, admin, member, make_book
    ):
        """Deliberately ungated. This answers 200 with the unchanged book for an
        unused id and for a hidden one alike, so it confirms nothing; a 404 for
        the second would create the tell rather than close one."""
        hidden = self._hidden_tag(client, admin, make_book)
        mine = make_book(member["headers"], title="Mine")

        response = client.delete(
            f"/api/books/{mine['id']}/tags/{hidden['id']}", headers=member["headers"]
        )

        assert response.status_code == 200
        assert response.json()["tags"] == []

    def test_a_tag_you_have_just_invented_can_go_on_a_book(
        self, client, member, make_book
    ):
        """The false refusal the list rule causes if it is reused for writes.
        Both clients mint a tag and then attach it by id, on the next line at
        the book page and at `confirm()` on the scan form, and the tag is on no
        book in between."""
        fresh = client.post(
            "/api/books/tags", json={"name": "My New Idea"}, headers=member["headers"]
        ).json()
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            f"/api/books/{mine['id']}/tags/{fresh['id']}", headers=member["headers"]
        )

        assert response.status_code == 200
        assert "My New Idea" in self._names(client, member)

    def test_a_tag_whose_last_book_you_trashed_can_go_on_another(
        self, client, member, make_book
    ):
        """Without the trash arm a member who trashes the last carrier can never
        use that tag again: creating it by name returns the existing row and
        attaching that row would 404 forever."""
        tag = client.post(
            "/api/books/tags", json={"name": "Shelved"}, headers=member["headers"]
        ).json()
        first = make_book(member["headers"], title="First")
        client.post(f"/api/books/{first['id']}/tags/{tag['id']}", headers=member["headers"])
        client.delete(f"/api/books/{first['id']}", headers=member["headers"])
        second = make_book(member["headers"], title="Second")

        response = client.post(
            f"/api/books/{second['id']}/tags/{tag['id']}", headers=member["headers"]
        )

        assert response.status_code == 200

    def test_a_renamed_seeded_tag_loses_the_exemption(
        self, client, admin, member, make_book, db
    ):
        """The exemption is keyed on `key`, not on `is_predefined`, so it rests
        on no premise about rename routes: `Tag._drop_the_key_on_a_rename`
        clears the key and the row falls back on the count arm."""
        seeded = db.query(Tag).filter(Tag.is_predefined.is_(True)).first()
        assert seeded is not None and seeded.key is not None
        seeded.name = "A Household's Own Word"
        db.commit()

        assert seeded.key is None
        assert "A Household's Own Word" not in self._names(client, member)


class TestTheSuggestionFeedAnswersWithTheSameVocabulary:
    """A suggestion is a tag **id** on the wire, so an unfiltered feed here
    hands a client an id the list route will not name.

    **The arm the rule shipped without.** `list_tags` had three behaviours
    watching it and the two catalogue doors had none, so the only thing
    covering them was that they were fed from the same call. That is a
    comparison, not a behaviour: a feed pointed at the table again is green
    under it.
    """

    def _lookup(self, client, headers):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(return_value=sru_response(DNB_RECORD))
            silence_catalogues(mock)
            return client.get(
                f"/api/books/lookup?isbn={GERMAN_ISBN}", headers=headers
            )

    def _hidden_tag_named(self, client, owner, make_book, name):
        tag = client.post(
            "/api/books/tags", json={"name": name}, headers=owner["headers"]
        ).json()
        book = make_book(owner["headers"], title="A private matter", is_private=True)
        client.post(
            f"/api/books/{book['id']}/tags/{tag['id']}", headers=owner["headers"]
        )
        return tag

    def test_a_lookup_does_not_suggest_a_tag_the_caller_may_not_see(
        self, client, admin, member, make_book
    ):
        """The record's own caption is "Informatik", so a custom tag of that
        name is exactly what the caption route matches."""
        hidden = self._hidden_tag_named(client, admin, make_book, "Informatik")

        suggested = self._lookup(client, member["headers"]).json()["suggested_tag_ids"]

        assert hidden["id"] not in suggested

    def test_and_still_suggests_the_ones_it_may(
        self, client, admin, member, make_book, db
    ):
        """The diagonal. A feed that suggested nothing at all would pass the
        arm above and be a different defect."""
        self._hidden_tag_named(client, admin, make_book, "Informatik")
        computing = db.query(Tag).filter(Tag.name == "Computing").one()

        suggested = self._lookup(client, member["headers"]).json()["suggested_tag_ids"]

        assert computing.id in suggested

    def test_its_owner_is_still_suggested_it(
        self, client, admin, member, make_book
    ):
        """The second diagonal: the feed is scoped to the **caller**, not to
        the tag's books. A vocabulary built for the wrong viewer passes the
        first arm and leaks to everybody else."""
        hidden = self._hidden_tag_named(client, admin, make_book, "Informatik")

        suggested = self._lookup(client, admin["headers"]).json()["suggested_tag_ids"]

        assert hidden["id"] in suggested

    # ── The search door, which is the other half and had none of the above ──
    #
    # Three arms through `/lookup` and none through `/search` is the state this
    # class's own docstring diagnoses: two doors fed from one call, covered by
    # the comparison rather than by a behaviour. Measured, one line in
    # `search_books` swapping the vocabulary for the Mint's unscoped index
    # passed the whole gate, mypy and ruff included, and served a member the id
    # of a tag on somebody else's private book.
    #
    # **The caption is a name the seeder does not ship**, so what these match
    # is the custom tag under test and never a seeded row that happens to share
    # a word with it.

    def _enable_google(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_enabled": True, "google_books_api_key": "test-key"},
            headers=admin["headers"],
        )

    def _search(self, client, headers, categories):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(categories=categories)]}
                )
            )
            silence_catalogues(mock)
            return client.get(
                "/api/books/search", params={"q": "moby"}, headers=headers
            ).json()["matches"]

    def test_a_search_does_not_suggest_a_tag_the_caller_may_not_see(
        self, client, admin, member, make_book
    ):
        self._enable_google(client, admin)
        hidden = self._hidden_tag_named(client, admin, make_book, "Whaling")

        [match] = self._search(client, member["headers"], ["Whaling"])

        assert hidden["id"] not in match["suggested_tag_ids"]

    def test_and_a_search_still_suggests_the_ones_it_may(
        self, client, admin, member, make_book
    ):
        """The diagonal. A feed that suggested nothing would pass the arm above
        and be a different defect."""
        self._enable_google(client, admin)
        self._hidden_tag_named(client, admin, make_book, "Whaling")

        [match] = self._search(client, member["headers"], ["Whaling", "Fiction"])

        names = {
            row["id"]: row["name"]
            for row in client.get("/api/books/tags", headers=member["headers"]).json()
        }
        assert "Fiction" in {names[i] for i in match["suggested_tag_ids"]}

    def test_and_its_owner_is_still_suggested_it_in_a_search(
        self, client, admin, make_book
    ):
        """Scoped to the caller, not to the tag's books, on this door too."""
        self._enable_google(client, admin)
        hidden = self._hidden_tag_named(client, admin, make_book, "Whaling")

        [match] = self._search(client, admin["headers"], ["Whaling"])

        assert hidden["id"] in match["suggested_tag_ids"]


class TestANameTypedAgainstAHiddenTagIsNotAttached:
    """**The repair for the regression this class used to record**, pinned at
    what it closed and at what it left open.

    Typing a name that collides with a Tag whose Books are all hidden answered
    201 with that row and then 404 on the attach, silently on the scan form,
    and the same operation succeeded through the CSV import with no gate at
    all. Both doors ask one question, may a member put a name they typed on a
    book they may write, and it was being answered by `Vocabulary.writable`,
    which is a question about **an id the caller guessed**. One rule keyed on
    the wrong thing: `tags.Naming` is keyed on the name instead, and both
    doors ask it.

    **The attach was the harm and the refusal was the cheap half.** The
    import's attach put a hidden name on a Book that defaults to public, which
    counted it for every member and so made it `listable` to all of them,
    permanently and with no member level undo, and on an instance publishing
    its catalogue it reached a reader with no session.

    **Which arms moved and which did not, so a red is read rather than
    fixed.** The create and the attach by id are untouched, and their arms
    assert exactly what they asserted before this repair: a red in either
    means it reached something it did not mean to. The import's arm is
    **inverted**, and that inversion is the repair rather than a regression in
    it.

    **What this does not close, recorded rather than claimed.** The create
    still answers a colliding name with the existing row, so the confirmation
    channel is open and unrated; no arm below asserts otherwise, and the first
    one asserts that it is open. The name space is globally unique of
    necessity, so refusing, attaching and dropping are three answers and each
    of them answers. Closing it is a migration.

    **The false refusal this was predicted to buy does not exist, and the arm
    that says so stays.** The prediction was that a Tag whose only carrier is
    another member's trashed Book would be lost to everybody, on the reading
    that `Vocabulary`'s third arm is the viewer's **own** trash. Measured:
    `Shelf.trashed_by` is `in_trash_for`, trashed **and visible** rather than
    trashed and theirs, so a trashed public Book carries the name for every
    member and the arm admits it. `tags.py`'s prose said "own trash" and is
    corrected; the entry for that statement in `tests/test_shelf.py` still
    says "the caller's own trash and nobody else's" and is not this file's to
    edit. A false refusal is invisible to a sweep by construction, which is
    why the arm is kept rather than deleted along with the prediction.

    **Named blind spot, corrected from the version this replaces.**
    `/api/books/bulk` carries neither `{book_id}` nor a tag segment, so the
    structural arm does not see it, and a name arriving as a bulk verb's
    `value` would reach the tag table without `Naming`. What stops that today
    is `_require_tag` parsing `int(str(value))`, and nothing pins it. The
    paragraph this replaces also said that spelling "needs no schema the merge
    has to regenerate", which is **false**: `BulkAction` is a committed schema
    component and a committed generated file, so a new member of it moves both
    exactly as a new route does.
    """

    def _hidden_tag(self, client, owner, make_book):
        """A tag whose only carrier is a private book of `owner`'s."""
        tag = client.post(
            "/api/books/tags", json={"name": "Divorce Law"}, headers=owner["headers"]
        ).json()
        book = make_book(owner["headers"], title="A private matter", is_private=True)
        client.post(
            f"/api/books/{book['id']}/tags/{tag['id']}", headers=owner["headers"]
        )
        return tag

    def test_the_create_still_hands_back_the_hidden_row(
        self, client, admin, member, make_book
    ):
        """Unchanged, and asserted so that the residue is a fact in the suite
        rather than a sentence in a docstring."""
        hidden = self._hidden_tag(client, admin, make_book)

        response = client.post(
            "/api/books/tags", json={"name": "Divorce Law"}, headers=member["headers"]
        )

        assert response.status_code == 201
        assert response.json()["id"] == hidden["id"]

    def test_and_the_attach_by_id_still_refuses(
        self, client, admin, member, make_book
    ):
        """The gate this branch did not widen. It is asked about an id, which
        the caller may have guessed, and that is a different question from the
        one the door beside it answers."""
        self._hidden_tag(client, admin, make_book)
        same = client.post(
            "/api/books/tags", json={"name": "Divorce Law"}, headers=member["headers"]
        ).json()
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            f"/api/books/{mine['id']}/tags/{same['id']}", headers=member["headers"]
        )

        assert response.status_code == 404

    def test_the_import_no_longer_puts_it_on_the_member_s_book(
        self, client, admin, member, make_book
    ):
        """**The inverted arm, and the one the repair is for.** One CSV row
        carrying the name used to attach it with no gate in the way, which is
        what made the hidden name public."""
        self._hidden_tag(client, admin, make_book)
        mine = make_book(member["headers"], title="Mine")

        client.post(
            "/api/imports/csv",
            files={
                "file": ("shelf.csv", b"Title,Tags\nMine,Divorce Law\n", "text/csv")
            },
            headers=member["headers"],
            params={"apply_tags": True},
        )

        carried = client.get(
            f"/api/books/{mine['id']}", headers=member["headers"]
        ).json()["tags"]
        assert "Divorce Law" not in {tag["name"] for tag in carried}

    def test_and_says_how_many_names_it_left_off(
        self, client, admin, member, make_book
    ):
        """Read off the report rather than the book, because a drop nobody can
        see is a loss with nowhere to read it off. The number folds four
        causes on purpose: `Import._apply_tags` says which and what that
        costs."""
        self._hidden_tag(client, admin, make_book)
        make_book(member["headers"], title="Mine")

        result = client.post(
            "/api/imports/csv",
            files={
                "file": ("shelf.csv", b"Title,Tags\nMine,Divorce Law\n", "text/csv")
            },
            headers=member["headers"],
            params={"apply_tags": True},
        ).json()

        assert result["tags_dropped"] == 1

    def test_nor_does_the_by_name_door_attach_it(
        self, client, admin, member, make_book
    ):
        """**200 with the book, not a 404 and not a 409.** A status telling a
        refused name from an accepted one would answer in the status line the
        question this refusal exists to narrow."""
        self._hidden_tag(client, admin, make_book)
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            f"/api/books/{mine['id']}/tags",
            json={"name": "Divorce Law"},
            headers=member["headers"],
        )

        assert response.status_code == 200
        assert "Divorce Law" not in {tag["name"] for tag in response.json()["tags"]}

    def test_the_hidden_name_stays_out_of_the_member_s_vocabulary(
        self, client, admin, member, make_book
    ):
        """**The harm, which is not the refusal.** Attaching the name to a
        member's book is what counts it for everybody and puts it in the list
        the client draws on nearly every page. Read off that list rather than
        off the book, because a repair that reports honestly and attaches
        anyway would pass the arm above."""
        self._hidden_tag(client, admin, make_book)
        mine = make_book(member["headers"], title="Mine")
        client.post(
            f"/api/books/{mine['id']}/tags",
            json={"name": "Divorce Law"},
            headers=member["headers"],
        )

        listed = client.get("/api/books/tags", headers=member["headers"]).json()

        assert "Divorce Law" not in {tag["name"] for tag in listed}

    def test_while_a_name_the_member_may_use_lands_in_one_request(
        self, client, member, make_book
    ):
        """The door, doing the thing it was added for: a name nobody has typed
        before is invented and put on the book in one gesture, where the
        clients used to send two requests and reconcile the answers."""
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            f"/api/books/{mine['id']}/tags",
            json={"name": "Holiday reads"},
            headers=member["headers"],
        )

        assert response.status_code == 200
        assert "Holiday reads" in {tag["name"] for tag in response.json()["tags"]}

    def test_including_one_the_library_holds_and_no_book_carries(
        self, client, member, make_book
    ):
        """The state every invented tag is in before something carries it, and
        the reason `Vocabulary.writable` keeps its last arm."""
        client.post(
            "/api/books/tags",
            json={"name": "Holiday reads"},
            headers=member["headers"],
        )
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            f"/api/books/{mine['id']}/tags",
            json={"name": "holiday READS"},
            headers=member["headers"],
        )

        assert "Holiday reads" in {tag["name"] for tag in response.json()["tags"]}

    def test_a_name_carried_only_by_a_trashed_public_book_is_still_usable(
        self, client, admin, member, make_book
    ):
        """**The false refusal this repair was predicted to buy, and does
        not.** The prediction read `Vocabulary.writable`'s third arm as the
        viewer's own trash, so a name whose last carrier somebody else trashed
        would be lost to everybody with nothing private in the story.
        Measured here: `Shelf.trashed_by` is `in_trash_for`, which is trashed
        **and** visible rather than trashed **and** theirs, so a trashed
        public book carries the name for every member and the arm admits it.

        Kept as an arm because the refusal it rules out is the expensive kind,
        invisible to a sweep by construction, and because the prose that
        invited the misreading was in `tags.py` and in the shelf register
        rather than only in the prediction."""
        tag = client.post(
            "/api/books/tags", json={"name": "Divorce Law"}, headers=admin["headers"]
        ).json()
        theirs = make_book(admin["headers"], title="Theirs")
        client.post(
            f"/api/books/{theirs['id']}/tags/{tag['id']}", headers=admin["headers"]
        )
        client.delete(f"/api/books/{theirs['id']}", headers=admin["headers"])
        mine = make_book(member["headers"], title="Mine")

        response = client.post(
            f"/api/books/{mine['id']}/tags",
            json={"name": "Divorce Law"},
            headers=member["headers"],
        )

        assert "Divorce Law" in {tag["name"] for tag in response.json()["tags"]}

    def test_one_book_scoped_write_route_receives_a_name(self):
        """**The structural arm, keyed on the API rather than on one request.**
        Exactly one operation under the books prefix, on a path carrying a
        book, whose method writes, can be handed a `name` anywhere a route
        receives one. That one is the door this class is about, and a second
        arriving is a second writer resolving a tag from a name, which must ask
        `tags.Naming` rather than invent its own answer.

        **Read off the route table and not off a request**, and the version
        this replaces measured why: with a `DELETE` added on a path, a `POST`
        to it still answers 404 rather than 405, because the SPA catch all
        mount finds a full match once the API routes have returned a partial
        one. So a request cannot tell "no route here" from "routes here under
        other methods".

        **The tag segment is deliberately not in the predicate**, so a by name
        door written at a path that does not say "tags" is still seen. Over
        reporting is the safe direction: a route that legitimately takes a
        `name` about something else lands here, and the answer is to re-read
        this class rather than to edit the predicate.

        **A response model pin was proposed for this job and is refused, with
        the measurement**: this arm names the route it expects, so pinning the
        response would narrow it, and a repair answering with the tag rather
        than the book would go unseen.
        """
        import main

        by_name = {
            f"{sorted(_methods(route))} {route.path}"
            for route in main.iter_api_routes(main.app.routes)
            if route.path.startswith("/api/books")
            and "{book_id}" in route.path
            and _methods(route) - {"GET", "DELETE", "HEAD", "OPTIONS"}
            and "name" in _names_a_route_can_receive(route)
        }

        assert by_name == {"['POST'] /api/books/{book_id}/tags"}, (
            f"the book scoped write routes that can be handed a name are {by_name}, "
            "and this class expects exactly the attach by name door.\n\n"
            "  A new one is a second writer resolving a tag from a name. Send it "
            "through `tags.Naming`, which is what applies the viewer to a matched "
            "row, and then add it here. If its `name` is about something else "
            "entirely, this arm is over reporting on purpose: say so here in one "
            "sentence beside the path.\n\n"
            "  A missing one means the door was removed or renamed, and the "
            "clients that send one request instead of two went with it."
        )
