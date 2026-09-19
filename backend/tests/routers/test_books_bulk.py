"""One verb applied to a selection of books.

Every verb behind one endpoint, because they share the same three steps:
resolve what the caller may actually touch, apply, and report
updated/unchanged/skipped. The three-way count is the part worth pinning:
reporting a flat success would claim work that did not happen.
"""

from enum import StrEnum
from typing import cast

import pytest

from enums import BulkAction
from routers import books as books_router


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


class TestATagIdPastTheDatabasesRangeIsRefused:
    """`BulkRequest.value` is deliberately untyped, so this is the only bound.

    A Python int has no ceiling. `int(str(value))` accepted `2**63`, `db.get`
    raised `OverflowError` from inside the driver, and the member got a
    **500** for a number they typed. The comment on `BulkRequest.value` named
    this handler and `_checked_collection` as both doing the range check;
    only the second one did.

    404 is the answer an id no row can carry deserves, and is what an id that
    merely does not exist already gets: the test above pins 9999.
    """

    #: One past the largest value SQLite stores in an INTEGER column.
    TOO_BIG = 9_223_372_036_854_775_808

    @pytest.mark.parametrize("action", ["add_tag", "remove_tag"])
    def test_a_tag_id_past_the_range_is_a_404_not_a_500(
        self, client, admin, make_book, action: str
    ):
        """Both verbs reach `_require_tag`, so both had the defect."""
        book = make_book(admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], action, self.TOO_BIG)

        assert res.status_code == 404, res.text

    def test_a_tag_at_the_largest_id_the_column_holds_is_still_applied(
        self, client, admin, make_book, db
    ):
        """The boundary itself, and it needs a row to be worth anything.

        The first version of this asserted a 404 for `MAX_ROW_ID` with no such
        tag, which cannot see the bound at all: `<= MAX_ROW_ID` mutated to
        `< MAX_ROW_ID` passed every test in this file, because a refusal and a
        lookup that finds nothing answer with the identical body. A design
        critic caught it. Only a row that exists at the boundary tells the two
        apart, so this inserts one, through the session rather than the API
        because no route lets a caller choose an id.
        """
        from enums import TagCategory
        from models import Tag
        from schemas.common import MAX_ROW_ID

        book = make_book(admin["headers"])
        # `key` stays null: this is a tag the library invented, not a seeded one.
        db.add(Tag(id=MAX_ROW_ID, name="Edge", category=TagCategory.CUSTOM))
        db.commit()

        res = bulk(client, admin["headers"], [book["id"]], "add_tag", MAX_ROW_ID)

        assert res.status_code == 200, res.text
        assert res.json()["updated"] == 1

    def test_an_unused_id_at_the_boundary_is_the_ordinary_404(
        self, client, admin, make_book
    ):
        """The other side of it: the bound refuses what the column cannot hold
        and nothing else, so the largest id it can hold reaches the lookup and
        gets the answer an unused id gets."""
        from schemas.common import MAX_ROW_ID

        book = make_book(admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], "add_tag", MAX_ROW_ID)

        assert res.status_code == 404, res.text

    def test_a_real_tag_id_still_works(self, client, admin, make_book, fiction_id):
        """The diagonal: the refusal must not be the only thing the guard does."""
        book = make_book(admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], "add_tag", fiction_id)

        assert res.status_code == 200, res.text
        assert res.json()["updated"] == 1


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

    def test_a_book_already_in_that_ownership_is_unchanged(self, client, admin, make_book):
        """Otherwise re-running a confirmation reports work it did not do, and
        confirming an imported shelf is exactly a re-run."""
        book = make_book(admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], "set_ownership", "owned")

        assert res.json() == {"updated": 0, "unchanged": 1, "skipped": 0}

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


class TestEveryVerbHasAHandler:
    """The dispatch table against the enum, which mypy will not pair by itself.

    `_BULK_HANDLERS[payload.action]` is a bare subscript over a dict literal,
    and mypy exhaustiveness checks a `match` rather than a dict. `_dispatch_table`
    refuses to build a table that disagrees with the enum; these are the rule it
    applies, driven with a synthetic enum so both directions are visible.
    """

    def test_the_table_and_the_enum_agree(self):
        """The live pairing, red the day an eighth member lands without one."""
        assert set(books_router._BULK_HANDLERS) == set(BulkAction)

    def test_a_verb_with_no_handler_is_reported(self):
        """The arm that matters: the member is a 500 to anybody who picks it."""

        class Verb(StrEnum):
            KEPT = "kept"
            ADDED = "added"

        assert books_router._undispatched({Verb.KEPT}, set(Verb)) == {Verb.ADDED}

    def test_a_handler_for_a_verb_that_is_gone_is_reported(self):
        """The other arm, which a containment check would pass. A handler no
        member reaches is a claim about a verb nobody can call."""

        class Verb(StrEnum):
            KEPT = "kept"
            REMOVED = "removed"

        assert books_router._undispatched(set(Verb), {Verb.KEPT}) == {Verb.REMOVED}

    def test_nothing_is_reported_when_the_two_agree(self):
        """The baseline. Without it both arms above score a pass they did not
        earn, because a check reporting everything reports those too."""

        class Verb(StrEnum):
            KEPT = "kept"

        assert books_router._undispatched(set(Verb), set(Verb)) == set()


def _verbs_plus_one() -> type[StrEnum]:
    """Every real verb, and one more. Built here, never routed.

    Derived from `BulkAction` rather than spelled out, so it is the shape of the
    day somebody adds a verb rather than a list that goes stale beside the enum.
    """
    members = {member.name: member.value for member in BulkAction}
    # `cast` because mypy reads the functional Enum API as a constructor call and
    # types the result as a member rather than as the class.
    return cast(type[StrEnum], StrEnum("VerbPlusOne", members | {"SET_SHELF_MARK": "set_shelf_mark"}))


class TestTheTableRefusesToBuild:
    """The refusal itself, which the pairing above cannot see.

    The table is built through `_dispatch_table`, so a check standing beside it
    is not what is being tested: these pin that the call raises rather than
    returning, and that the message names the member. Without them, deleting the
    `raise` inside `_dispatch_table` leaves the whole backend suite green, which
    is measured rather than supposed.
    """

    def test_it_builds_the_real_table(self):
        """The baseline arm. A function that raised whatever it was handed would
        pass the arms below and say nothing."""
        built = books_router._dispatch_table(dict(books_router._BULK_HANDLERS), set(BulkAction))

        assert built == books_router._BULK_HANDLERS

    def test_it_refuses_a_verb_with_no_handler_and_names_it(self):
        """The arm that matters: the member is a `KeyError` and a 500 to whoever
        picks it, and a refusal that does not say which member is one somebody
        deletes rather than answers."""
        verbs = _verbs_plus_one()
        handlers = {
            verb: books_router._BULK_HANDLERS[BulkAction(verb.value)]
            for verb in verbs
            if verb.value != "set_shelf_mark"
        }

        with pytest.raises(RuntimeError, match="set_shelf_mark"):
            books_router._dispatch_table(handlers, set(verbs))

    def test_it_refuses_a_handler_no_verb_reaches(self):
        """The other direction, which a containment check would pass. One member
        short on the other side, so the message can only name the one removed."""
        verbs = _verbs_plus_one()
        real = {verb for verb in verbs if verb.value != "set_shelf_mark"}
        handlers = {verb: books_router._BULK_HANDLERS[BulkAction(verb.value)] for verb in real}
        # `min` rather than a named verb: any member does, and naming one here
        # would put a verb literal in a class written not to hold any.
        gone = min(real)

        with pytest.raises(RuntimeError, match=gone.value):
            books_router._dispatch_table(handlers, real - {gone})

    def test_the_refusal_says_what_to_do_about_it(self):
        """A refusal naming a member and nothing else leaves the reader to guess
        which of the two files to edit."""
        verbs = _verbs_plus_one()
        handlers = {
            verb: books_router._BULK_HANDLERS[BulkAction(verb.value)]
            for verb in verbs
            if verb.value != "set_shelf_mark"
        }

        with pytest.raises(RuntimeError) as raised:
            books_router._dispatch_table(handlers, set(verbs))

        assert "_BULK_HANDLERS" in str(raised.value)


#: Values a member can type that must not reach a driver, a column or a `db.get`
#: unexamined. Hostile in several directions rather than in bulk: one past what
#: the column holds, one below the first row id, one past every length bound,
#: one that parses as no id at all, and none at all.
_HOSTILE = [
    pytest.param(9_223_372_036_854_775_808, id="one_past_the_column"),
    pytest.param(-1, id="below_the_first_row_id"),
    pytest.param("x" * 1000, id="a_long_string"),
    pytest.param("", id="empty"),
    pytest.param(None, id="absent"),
]


class TestNoVerbTurnsAValueIntoA500:
    """Every verb against a hostile `value`, parametrised over `BulkAction`.

    **Driven off the enum, so it enumerates nothing.** An eighth verb is covered
    the day it is added, and that is the whole point: the completeness guards
    above see a member with no handler, and they cannot see a member added to
    both sides that reads `value` its own way with no bound. That is how
    `_require_tag` answered `2**63` with a 500 for months, recorded in
    `docs/decisions.md` under the guard that named two enforcers and had one.

    The assertion is `< 500` rather than a status per verb, because the verbs
    answer differently by design and each answer has a reason recorded at its
    own site. Pinning those here would copy every one of those decisions to one
    more place, and a landscape written out per verb goes stale the day a verb
    moves: the first draft of this docstring named six of them and got four
    wrong. What is pinned here is the exclusion, that none of the answers is a
    500.
    """

    @pytest.mark.parametrize("value", _HOSTILE)
    @pytest.mark.parametrize("action", list(BulkAction), ids=lambda action: action.value)
    def test_a_hostile_value_is_never_a_500(
        self, client, admin, make_book, action: BulkAction, value
    ):
        book = make_book(admin["headers"])

        res = bulk(client, admin["headers"], [book["id"]], action.value, value)

        assert res.status_code < 500, res.text
