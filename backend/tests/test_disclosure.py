"""Who may be told a vocabulary entry exists: one rule, five id doors.

`disclosure.Disclosure` is the rule, and the three vocabularies (`tags`,
`shelving`, `fields`) are its arms. What is pinned here is what the rule is
for at the doors that take an id a member may have guessed: an id no row
carries and an id the caller may not be told about answer **the same status,
the same body and the same statements**. The statements are counted rather
than timed, because a timing assertion on a shared node is a flake and the
count is the cause a timing difference would be the symptom of.
"""

import ast
from collections.abc import Callable
from typing import Final

import pytest
from sqlalchemy import event

from tests.corpus import application_sources
from tests.test_shelf import _builds_a_query, _sqlalchemy_names
from tests.test_tags import _reaches_private

#: A door: how to ask it about one id as the viewer, given what the fixture built.
Door = Callable[..., object]


def _hidden_tag(client, owner, make_book) -> int:
    tag = client.post(
        "/api/books/tags", json={"name": "Divorce Law"}, headers=owner["headers"]
    ).json()
    book = make_book(owner["headers"], title="A private matter", is_private=True)
    attached = client.post(
        f"/api/books/{book['id']}/tags/{tag['id']}", headers=owner["headers"]
    )
    assert attached.status_code == 200, attached.text
    return tag["id"]


def _hidden_collection(client, owner, make_book) -> int:
    shelf = client.post(
        "/api/collections", json={"name": "Hidden"}, headers=owner["headers"]
    ).json()
    book = make_book(owner["headers"], title="A private matter", is_private=True)
    filed = client.patch(
        f"/api/books/{book['id']}/collection",
        json={"collection_id": shelf["id"]},
        headers=owner["headers"],
    )
    assert filed.status_code == 200, filed.text
    return shelf["id"]


def _hidden_field(client, owner, make_book) -> int:
    field = client.post(
        "/api/books/custom-fields",
        json={"name": "Shelf photo", "kind": "text"},
        headers=owner["headers"],
    ).json()
    book = make_book(owner["headers"], title="A private matter", is_private=True)
    written = client.put(
        f"/api/books/{book['id']}/custom-fields/{field['id']}",
        json={"value": "On the landing"},
        headers=owner["headers"],
    )
    assert written.status_code == 200, written.text
    return field["id"]


#: (door name, how the hidden entry is built, the request for one id).
#: `mine` is a public Book the viewer added, for the doors that write one.
DOORS = [
    (
        "add_book_tag",
        _hidden_tag,
        lambda client, headers, mine, entry_id: client.post(
            f"/api/books/{mine}/tags/{entry_id}", headers=headers
        ),
    ),
    (
        "bulk add_tag",
        _hidden_tag,
        lambda client, headers, mine, entry_id: client.post(
            "/api/books/bulk",
            json={"action": "add_tag", "book_ids": [mine], "value": entry_id},
            headers=headers,
        ),
    ),
    (
        "file a Book",
        _hidden_collection,
        lambda client, headers, mine, entry_id: client.patch(
            f"/api/books/{mine}/collection",
            json={"collection_id": entry_id},
            headers=headers,
        ),
    ),
    (
        "rename a collection",
        _hidden_collection,
        lambda client, headers, mine, entry_id: client.patch(
            f"/api/collections/{entry_id}", json={"name": "Anything"}, headers=headers
        ),
    ),
    (
        "rename a field",
        _hidden_field,
        lambda client, headers, mine, entry_id: client.patch(
            f"/api/books/custom-fields/{entry_id}",
            json={"name": "Anything"},
            headers=headers,
        ),
    ),
    (
        "write a value",
        _hidden_field,
        lambda client, headers, mine, entry_id: client.put(
            f"/api/books/{mine}/custom-fields/{entry_id}",
            json={"value": "Anything"},
            headers=headers,
        ),
    ),
]


@pytest.mark.parametrize(
    ("build", "ask"),
    [(build, ask) for _, build, ask in DOORS],
    ids=[name for name, _, _ in DOORS],
)
def test_an_absent_id_and_a_hidden_one_answer_alike_in_body_and_statements(
    client, db, admin, member, make_book, build, ask
):
    """Status, body and statement count, for an id nothing carries against one
    whose every carrier is another member's Private Book.

    **The absent id is asked once before either is counted**, so whatever a
    first request warms is paid outside the comparison rather than charged to
    whichever id happens to go first.
    """
    hidden = build(client, admin, make_book)
    absent = hidden + 1000
    mine = make_book(member["headers"], title="Mine")["id"]
    engine = db.get_bind()

    def counted(entry_id: int) -> tuple[int, int, object]:
        seen: list[str] = []

        def record(conn, cursor, statement, *rest):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = ask(client, member["headers"], mine, entry_id)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return response.status_code, len(seen), response.json()

    ask(client, member["headers"], mine, absent)
    hidden_status, hidden_cost, hidden_body = counted(hidden)
    absent_status, absent_cost, absent_body = counted(absent)

    assert hidden_status in (400, 404), (hidden_status, hidden_body)
    assert (hidden_status, hidden_body) == (absent_status, absent_body)
    assert hidden_cost > 0, "nothing was counted, so this arm measured nothing"
    assert absent_cost == hidden_cost, (
        f"an absent id costs {absent_cost} statements and a hidden one "
        f"{hidden_cost}, so the two refusals are separable on a clock"
    )


def test_the_vocabularies_are_the_three_the_doors_above_cover() -> None:
    """`Carrier` is the set of vocabularies `Disclosure` answers for. A member
    added to it with an `onto_books` case reds nothing else in this file, and
    mypy forces no `entry` case for it: `entry` is typed `Any`."""
    from disclosure import Carrier

    assert {carrier.name for carrier in Carrier} == {
        "BOOK_TAGS",
        "COLLECTION",
        "CUSTOM_FIELD_VALUES",
    }, (
        "a vocabulary joined or left `Carrier`. Who may be told one of its "
        "entries exists is a privacy decision: give it an absent against hidden "
        "row in DOORS for every door that takes its id, then update this set."
    )


class TestTheRuleReadsThroughTheShelfAndCarriesOnlyTheEntry:
    """`disclosure.py`'s reads choose their table at run time, by `Carrier`, so
    `tests/test_shelf.py`'s fourth pass cannot see which table they read and no
    register keys them. This holds them by shape instead, the way
    `folding.py`'s reads are held.

    Two things, over the module's source: no query is begun anywhere but a
    `Shelf` (the unscoped arm is `shelf.entries_any_book_carries`, a call and
    not a query here), and what a Shelf read selects is the entry and, for a
    counted vocabulary, a count of Books. A value, a name or a `book_id` in a
    select is a read that applies a viewer and still publishes what it
    should not.

    **What it lets through**: whatever column `Carrier.entry` returns, because
    this reads the spelling `carrier.entry` and not the column it names;
    `tests/test_fields.py` pins the custom field columns. A receiver under any
    local name but `shelf` is refused rather than let through.
    """

    #: What a Shelf read in this module may select, as `ast.unparse` writes it.
    SELECTED: Final = frozenset({"carrier.entry", "func.count(Book.id)"})

    #: What a Shelf read's receiver may be, as `ast.unparse` writes it.
    RECEIVERS: Final = frozenset(
        {
            "shelf",
            "Shelf.seen_by(self._db, self._viewer_id)",
            "Shelf.trashed_by(self._db, self._viewer_id)",
        }
    )

    def _offences(self, source: str) -> list[str]:
        tree = ast.parse(source)
        select_names, module_names = _sqlalchemy_names(tree)
        found = []
        for node in ast.walk(tree):
            # The annotated form binds the same name: `shelf.py` itself
            # annotates its locals, so a `shelf: Shelf = ...` is an ordinary
            # spelling here and not a dodge.
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            if (
                value is not None
                and any(
                    isinstance(target, ast.Name) and target.id == "shelf"
                    for target in targets
                )
                and ast.unparse(value) not in self.RECEIVERS
            ):
                found.append(f"{value.lineno}: shelf = {ast.unparse(value)}")
            if not isinstance(node, ast.Call):
                continue
            if _builds_a_query(node.func, select_names, module_names):
                found.append(f"{node.lineno}: {ast.unparse(node)}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "select":
                if ast.unparse(node.func.value) not in self.RECEIVERS:
                    found.append(f"{node.lineno}: {ast.unparse(node)}")
                found.extend(
                    f"{node.lineno}: selects {ast.unparse(argument)}"
                    for argument in [*node.args, *(k.value for k in node.keywords)]
                    if ast.unparse(argument) not in self.SELECTED
                )
        return found

    def test_every_read_is_a_shelf_selecting_the_entry(self) -> None:
        source = application_sources()["disclosure.py"]

        assert "Shelf.seen_by" in source, "the visible read is no longer spelled"
        assert "Shelf.trashed_by" in source, "the trash read is no longer spelled"
        assert self._offences(source) == [], (
            "`disclosure.py` reads past the Shelf or selects more than the "
            "entry. Its table is chosen at run time, so no register can key the "
            "statement: route it through `Shelf.seen_by` or `Shelf.trashed_by` "
            "and select the entry alone."
        )

    def test_a_query_begun_past_the_shelf_is_reported(self) -> None:
        source = application_sources()["disclosure.py"] + (
            "\n\ndef every_entry(self):\n"
            "    return self._db.query(self._carrier.entry).all()\n"
        )

        assert any("self._db.query" in line for line in self._offences(source))

    def test_a_shelf_bound_with_an_annotation_is_held_to_the_same_receivers(
        self,
    ) -> None:
        source = application_sources()["disclosure.py"] + (
            "\n\ndef owners_entries(self, owner_id):\n"
            "    shelf: Shelf = Shelf.seen_by(self._db, owner_id)\n"
            "    return shelf.select(self._carrier.entry).all()\n"
        )

        assert any(
            "shelf = Shelf.seen_by(self._db, owner_id)" in line
            for line in self._offences(source)
        )

    def test_a_second_column_in_a_shelf_read_is_reported(self) -> None:
        source = application_sources()["disclosure.py"].replace(
            "shelf.select(carrier.entry)", "shelf.select(carrier.entry, Book.title)", 1
        )
        assert source != application_sources()["disclosure.py"], "nothing was planted"

        assert any("selects Book.title" in line for line in self._offences(source))


def test_the_rule_s_private_state_is_reached_from_nowhere_else() -> None:
    """`Disclosure._carried` is every carried entry id with no viewer applied.
    A caller holding it has the broadcast back with no read anywhere.
    `_reaches_private`'s docstring carries what this walk does not see."""
    from disclosure import Disclosure

    private = frozenset(
        name
        for name in set(Disclosure.__slots__) | set(vars(Disclosure))
        if name.startswith("_") and not name.startswith("__")
    )
    assert "_carried" in private, private

    reaching = {
        name: sites
        for name, source in application_sources().items()
        if name != "disclosure.py" and (sites := _reaches_private(source, private))
    }

    assert not reaching, reaching
