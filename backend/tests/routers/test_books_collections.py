"""Filing books into collections, and filtering the library by one.

The half of the feature that lives on books rather than on collections: the
assign endpoint, the two list parameters, the bulk verb, and the export column.

What is being defended throughout is that a collection narrows a view and
**never widens one**. Every filtered query still applies `visible_to`, so no
combination of parameters here shows a book the caller could not otherwise see.
"""

from models import Book


def make_collection(client, headers, name):
    return client.post("/api/collections", json={"name": name}, headers=headers).json()


def file_book(client, headers, book_id, collection_id):
    return client.patch(
        f"/api/books/{book_id}/collection",
        json={"collection_id": collection_id},
        headers=headers,
    )


def listed(client, headers, **params):
    res = client.get("/api/books", params=params, headers=headers)
    assert res.status_code == 200, res.text
    return [book["title"] for book in res.json()["items"]]


class TestFilingABook:
    def test_a_book_starts_unfiled(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        assert book["collection_id"] is None
        assert book["collection_name"] is None

    def test_filing_it_returns_the_name(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune")

        res = file_book(client, admin["headers"], book["id"], shelf["id"])

        assert res.status_code == 200, res.text
        assert res.json()["collection_id"] == shelf["id"]
        assert res.json()["collection_name"] == "Ebooks"

    def test_null_takes_it_out_again(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        res = file_book(client, admin["headers"], book["id"], None)

        assert res.json()["collection_id"] is None
        assert res.json()["collection_name"] is None

    def test_an_id_too_big_for_the_database_is_refused_not_a_500(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"], title="Dune")

        res = client.patch(
            f"/api/books/{book['id']}/collection",
            json={"collection_id": 9999999999999999999999},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_an_unknown_collection_is_refused(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")

        res = file_book(client, admin["headers"], book["id"], 999)

        assert res.status_code == 400
        assert res.json()["detail"] == "No such collection"

    def test_another_member_may_file_a_public_book(self, client, admin, member, make_book):
        """Shelving, not privacy: a public book is a shared shelf, like its tags."""
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune")

        assert file_book(client, member["headers"], book["id"], shelf["id"]).status_code == 200

    def test_somebody_elses_private_book_is_404(self, client, admin, member, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        hidden = make_book(admin["headers"], title="Secret", is_private=True)

        assert file_book(client, member["headers"], hidden["id"], shelf["id"]).status_code == 404

    def test_filing_one_copy_leaves_the_other_alone(self, client, admin, make_book):
        """Two copies are two objects, and which shelf each is on is per object."""
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        copy = client.post(
            f"/api/books/{book['id']}/copies", json={}, headers=admin["headers"]
        ).json()

        file_book(client, admin["headers"], copy["id"], shelf["id"])

        assert copy["collection_id"] is None
        assert (
            client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()[
                "collection_id"
            ]
            is None
        )
        assert (
            client.get(f"/api/books/{copy['id']}", headers=admin["headers"]).json()[
                "collection_id"
            ]
            == shelf["id"]
        )

    def test_a_copy_count_spans_collections(self, client, admin, make_book):
        """It answers "how many do we own", not "how many are on this screen"."""
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        copy = client.post(
            f"/api/books/{book['id']}/copies", json={}, headers=admin["headers"]
        ).json()
        file_book(client, admin["headers"], copy["id"], shelf["id"])

        assert (
            client.get(f"/api/books/{copy['id']}", headers=admin["headers"]).json()[
                "copy_count"
            ]
            == 2
        )


class TestFilingAtCreation:
    def test_a_book_can_be_added_straight_into_one(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")

        book = make_book(admin["headers"], title="Dune", collection_id=shelf["id"])

        assert book["collection_id"] == shelf["id"]
        assert book["collection_name"] == "Ebooks"

    def test_an_unknown_collection_refuses_the_add(self, client, admin):
        res = client.post(
            "/api/books", json={"title": "Dune", "collection_id": 999}, headers=admin["headers"]
        )

        assert res.status_code == 400

    def test_a_refused_add_purges_nothing(self, client, admin, make_book, db):
        """The collection is checked before the ISBN walk, which destroys
        trashed rows to free the number. Refusing afterwards would have taken
        them with it."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        res = client.post(
            "/api/books",
            json={"title": "Dune", "isbn": "9780441013593", "collection_id": 999},
            headers=admin["headers"],
        )

        assert res.status_code == 400
        assert db.get(Book, book["id"]) is not None

    def test_a_copy_can_be_added_into_a_different_one(self, client, admin, make_book):
        physical = make_collection(client, admin["headers"], "Physical")
        digital = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(
            admin["headers"], title="Dune", isbn="9780441013593", collection_id=physical["id"]
        )

        copy = client.post(
            f"/api/books/{book['id']}/copies",
            json={"collection_id": digital["id"]},
            headers=admin["headers"],
        ).json()

        assert copy["collection_id"] == digital["id"]

    def test_a_copy_does_not_inherit_the_collection(self, client, admin, make_book):
        """Unlike the work fields and unlike `is_private`: which shelf a copy
        is on is a fact about the object, and the answer for a new one is not
        known."""
        shelf = make_collection(client, admin["headers"], "Physical")
        book = make_book(
            admin["headers"], title="Dune", isbn="9780441013593", collection_id=shelf["id"]
        )

        copy = client.post(
            f"/api/books/{book['id']}/copies", json={}, headers=admin["headers"]
        ).json()

        assert copy["collection_id"] is None


class TestFilteringTheLibrary:
    def test_one_collection_narrows_the_list(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        filed = make_book(admin["headers"], title="Filed")
        make_book(admin["headers"], title="Loose")
        file_book(client, admin["headers"], filed["id"], shelf["id"])

        assert listed(client, admin["headers"], collection_id=shelf["id"]) == ["Filed"]

    def test_unfiled_is_its_own_question(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        filed = make_book(admin["headers"], title="Filed")
        make_book(admin["headers"], title="Loose")
        file_book(client, admin["headers"], filed["id"], shelf["id"])

        assert listed(client, admin["headers"], unfiled=True) == ["Loose"]

    def test_asking_for_both_is_refused(self, client, admin):
        shelf = make_collection(client, admin["headers"], "Ebooks")

        res = client.get(
            "/api/books",
            params={"collection_id": shelf["id"], "unfiled": True},
            headers=admin["headers"],
        )

        assert res.status_code == 400

    def test_the_filter_still_hides_private_books(self, client, admin, member, make_book):
        """A collection filter that forgot `visible_to` would be the same leak
        wearing a new coat."""
        shelf = make_collection(client, admin["headers"], "Ebooks")
        hidden = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], hidden["id"], shelf["id"])

        assert listed(client, member["headers"], collection_id=shelf["id"]) == []

    def test_an_unknown_collection_lists_nothing(self, client, admin, make_book):
        """A filter, not a lookup: an id nobody uses selects no rows rather
        than answering 404 about a book request."""
        make_book(admin["headers"], title="Dune")

        assert listed(client, admin["headers"], collection_id=999) == []

    def test_an_id_too_big_for_the_database_is_refused_not_a_500(
        self, client, admin, make_book
    ):
        """A Python int has no ceiling and SQLite's does. Unbounded, this
        reached the driver and raised `OverflowError` from inside the query,
        which the unhandled-exception handler answers 500 to: the app calling
        its own code buggy over a value the caller chose. Same measurement as
        `after_id` on the cover backfill."""
        make_book(admin["headers"], title="Dune")

        res = client.get(
            "/api/books",
            params={"collection_id": "9999999999999999999999"},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_the_trash_is_still_excluded(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert listed(client, admin["headers"], collection_id=shelf["id"]) == []


class TestAShelfOnlyYourOwnPrivateBooksAreOnStaysWritable:
    """The viewer the write gate is handed, observed at all four doors.

    **Four call sites hand `_checked_collection` a viewer**: the create door,
    the bulk door, the assign door and the copy door, and there is an arm for
    each. **The population is the call sites and not a sweep's survivor
    list.** Two of the four are route handlers, and a mutation sweep cannot
    enter a decorated body, so it reported survivors only in the two
    undecorated ones. Built from those, this class was one door short and
    nothing said so: planting the viewer to nothing in `add_copy` left all
    four collection test files green, measured 2026-09-30.

    **What these arms buy is a wrong viewer of the right type, not `None`.**
    Mypy refuses `None` at every one of these call sites, by the line, so the
    sweep's three survivors were never shippable and this class must not be
    read as having caught them. What no checker can see is a viewer that type
    checks and names the wrong person: another member's id, the book's owner,
    a literal. Measured with `viewer_id + 1` at the gate, which these arms
    catch and no other test in the four files does.

    The behaviour pinned: under a wrong viewer `visible_to` stops seeing the
    caller's own private books, so a shelf carrying one private book of the
    caller's own falls out of arm 1, arm 3 does not hold because a book
    carries it, and every write into it is refused as an unknown id. **It
    fails closed rather than open, so it is a false refusal and not a
    disclosure**, which is the half a sweep is least likely to be written
    against and this repository has paid for twice.
    """

    @staticmethod
    def _shelf_holding_only_my_private_book(client, headers, make_book):
        shelf = make_collection(client, headers, "Divorce paperwork")
        secret = make_book(headers, title="Secret", is_private=True)
        assert file_book(client, headers, secret["id"], shelf["id"]).status_code == 200
        return shelf

    def test_the_assign_door_still_takes_it(self, client, member, make_book):
        shelf = self._shelf_holding_only_my_private_book(
            client, member["headers"], make_book
        )
        book = make_book(member["headers"], title="Dune")

        res = file_book(client, member["headers"], book["id"], shelf["id"])

        assert res.status_code == 200, res.text
        assert res.json()["collection_name"] == "Divorce paperwork"

    def test_the_create_door_still_takes_it(self, client, member, make_book):
        shelf = self._shelf_holding_only_my_private_book(
            client, member["headers"], make_book
        )

        res = client.post(
            "/api/books",
            json={"title": "Dune", "collection_id": shelf["id"]},
            headers=member["headers"],
        )

        assert res.status_code == 201, res.text
        assert res.json()["collection_id"] == shelf["id"]

    def test_the_bulk_door_still_takes_it(self, client, member, make_book):
        shelf = self._shelf_holding_only_my_private_book(
            client, member["headers"], make_book
        )
        book = make_book(member["headers"], title="Dune")

        res = client.post(
            "/api/books/bulk",
            json={
                "book_ids": [book["id"]],
                "action": "set_collection",
                "value": shelf["id"],
            },
            headers=member["headers"],
        )

        assert res.status_code == 200, res.text
        assert res.json()["updated"] == 1

    def test_the_copy_door_still_takes_it(self, client, member, make_book):
        shelf = self._shelf_holding_only_my_private_book(
            client, member["headers"], make_book
        )
        book = make_book(member["headers"], title="Dune", isbn="9780441013593")

        res = client.post(
            f"/api/books/{book['id']}/copies",
            json={"collection_id": shelf["id"]},
            headers=member["headers"],
        )

        assert res.status_code == 201, res.text
        assert res.json()["collection_id"] == shelf["id"]


class TestTheBulkVerb:
    def test_a_selection_is_filed_at_once(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        first = make_book(admin["headers"], title="One")
        second = make_book(admin["headers"], title="Two")

        res = client.post(
            "/api/books/bulk",
            json={
                "book_ids": [first["id"], second["id"]],
                "action": "set_collection",
                "value": shelf["id"],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert res.json()["updated"] == 2
        assert listed(client, admin["headers"], collection_id=shelf["id"]) == ["One", "Two"]

    def test_an_empty_value_unfiles_them(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        res = client.post(
            "/api/books/bulk",
            json={"book_ids": [book["id"]], "action": "set_collection", "value": None},
            headers=admin["headers"],
        )

        assert res.json()["updated"] == 1
        assert listed(client, admin["headers"], unfiled=True) == ["Dune"]

    def test_a_book_already_there_counts_as_unchanged(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        res = client.post(
            "/api/books/bulk",
            json={"book_ids": [book["id"]], "action": "set_collection", "value": shelf["id"]},
            headers=admin["headers"],
        )

        assert res.json() == {"updated": 0, "unchanged": 1, "skipped": 0}

    def test_an_unknown_collection_changes_nothing(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")

        res = client.post(
            "/api/books/bulk",
            json={"book_ids": [book["id"]], "action": "set_collection", "value": 999},
            headers=admin["headers"],
        )

        assert res.status_code == 400
        assert listed(client, admin["headers"], unfiled=True) == ["Dune"]

    def test_an_id_too_big_for_the_database_is_refused_not_a_500(
        self, client, admin, make_book
    ):
        """`BulkRequest.value` is deliberately loose, so this path validates
        nothing before the id reaches `db.get`. Past SQLite's INTEGER that is an
        `OverflowError` and a 500."""
        book = make_book(admin["headers"], title="Dune")

        res = client.post(
            "/api/books/bulk",
            json={
                "book_ids": [book["id"]],
                "action": "set_collection",
                "value": 9999999999999999999999,
            },
            headers=admin["headers"],
        )

        assert res.status_code == 400

    def test_a_non_numeric_value_is_refused(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")

        res = client.post(
            "/api/books/bulk",
            json={"book_ids": [book["id"]], "action": "set_collection", "value": "shelf"},
            headers=admin["headers"],
        )

        assert res.status_code == 400

    def test_somebody_elses_private_book_is_skipped(self, client, admin, member, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        hidden = make_book(admin["headers"], title="Secret", is_private=True)

        res = client.post(
            "/api/books/bulk",
            json={"book_ids": [hidden["id"]], "action": "set_collection", "value": shelf["id"]},
            headers=member["headers"],
        )

        assert res.json()["skipped"] == 1


class TestMerging:
    def test_the_survivor_inherits_a_collection_it_did_not_have(
        self, client, admin, make_book
    ):
        """Same rule as `location`: a merge fills the keeper's gaps."""
        shelf = make_collection(client, admin["headers"], "Ebooks")
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune ")
        file_book(client, admin["headers"], loser["id"], shelf["id"])

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert res.json()["collection_id"] == shelf["id"]

    def test_a_keeper_already_filed_stays_where_it_is(self, client, admin, make_book):
        physical = make_collection(client, admin["headers"], "Physical")
        digital = make_collection(client, admin["headers"], "Ebooks")
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune ")
        file_book(client, admin["headers"], keeper["id"], physical["id"])
        file_book(client, admin["headers"], loser["id"], digital["id"])

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.json()["collection_id"] == physical["id"]


class TestTheExport:
    def test_the_collection_name_is_a_column(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks")
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        body = client.get("/api/books/export", headers=admin["headers"]).text

        assert "Collection" in body.splitlines()[0]
        assert "Ebooks" in body

    def test_an_unfiled_book_exports_an_empty_cell(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune")

        body = client.get("/api/books/export", headers=admin["headers"]).text

        assert "Dune" in body

    def test_a_name_that_looks_like_a_formula_is_neutralised(self, client, admin, make_book):
        """Collection names are member supplied, so one reaches a CSV cell
        nobody wrote by hand. Same guard as tag names.

        **Not "library wide", which is what this said.** An export is the
        caller's own shelf, so the name reaches an export only where a book
        the caller can see is filed under it. The guard's reason is the cell,
        not the audience."""
        shelf = make_collection(client, admin["headers"], "=HYPERLINK(1)")
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        body = client.get("/api/books/export", headers=admin["headers"]).text

        assert "'=HYPERLINK(1)" in body


class TestAGuessedIdIsNoLongerAnOracle:
    """Every door a caller can name a collection id at answers the same for an
    id that is hidden and an id that is unused.

    **One arm over all five doors, because an arm checking one certifies one.**
    Four of them file a book and are why this class lives in this file; the
    fifth is the rename, which is in the collections router and is the same
    question asked at a different verb. A per door arm would have been five
    chances to close four of them.

    **Byte identical, not merely both refusals.** Two doors answering 400 with
    different bodies, or the same body with a different status, is the oracle
    with an extra step: the caller still learns which of the two ids is real.
    So the differential compares the status and the body as they leave.

    **And a control, because a differential over two refusals nothing produced
    is green on a door that was never reached.** Each door is exercised once
    against a collection the caller may be told about, and that answer has to
    differ from the refusal, or the arm is comparing a route's 404 for
    something else against itself.

    A **sixth** door has its own arm here for the opposite reason. The library
    filter takes a collection id, validates nothing, and answers an empty page
    either way, so it is already not an oracle and adding a refusal to make it
    match the others would create one.
    """

    @staticmethod
    def _doors(client, headers, book_id, collection_id):
        """Every request that names a collection id, as (name, response).

        Built per collection id so the same five requests run against the
        hidden one, the unused one and the visible one.
        """
        return {
            "create a book into it": client.post(
                "/api/books",
                json={"title": "New", "collection_id": collection_id},
                headers=headers,
            ),
            "file a book into it": client.patch(
                f"/api/books/{book_id}/collection",
                json={"collection_id": collection_id},
                headers=headers,
            ),
            "add a copy into it": client.post(
                f"/api/books/{book_id}/copies",
                json={"collection_id": collection_id},
                headers=headers,
            ),
            "file a selection into it": client.post(
                "/api/books/bulk",
                json={
                    "book_ids": [book_id],
                    "action": "set_collection",
                    "value": collection_id,
                },
                headers=headers,
            ),
            "rename it": client.patch(
                f"/api/collections/{collection_id}",
                json={"name": "Renamed"},
                headers=headers,
            ),
        }

    def test_the_library_filter_stays_the_one_door_that_is_not_a_gate(
        self, client, admin, member, make_book
    ):
        """`?collection_id=` validates nothing and must go on validating nothing.

        An unknown id and a real one holding only books the caller cannot see
        both answer with an empty page, so the filter confirms nothing. It is
        the door this branch had to leave alone: adding a refusal here to match
        the others would **create** an oracle where there is none, which is the
        false refusal shape a sweep cannot see.
        """
        hidden = make_collection(client, admin["headers"], "Divorce paperwork")
        secret = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], secret["id"], hidden["id"])
        unused = hidden["id"] + 1000

        withheld = client.get(
            "/api/books", params={"collection_id": hidden["id"]}, headers=member["headers"]
        )
        absent = client.get(
            "/api/books", params={"collection_id": unused}, headers=member["headers"]
        )

        assert (withheld.status_code, withheld.json()["total"]) == (200, 0)
        assert (withheld.status_code, withheld.text) == (absent.status_code, absent.text)

    def test_a_hidden_collection_answers_exactly_as_an_unused_id(
        self, client, admin, member, make_book
    ):
        hidden = make_collection(client, admin["headers"], "Divorce paperwork")
        secret = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], secret["id"], hidden["id"])
        mine = make_book(member["headers"], title="Mine")
        unused = hidden["id"] + 1000

        withheld = self._doors(client, member["headers"], mine["id"], hidden["id"])
        absent = self._doors(client, member["headers"], mine["id"], unused)

        assert [(name, res.status_code, res.text) for name, res in withheld.items()] == [
            (name, res.status_code, res.text) for name, res in absent.items()
        ]

    def test_and_a_collection_the_caller_may_be_told_about_answers_differently(
        self, client, admin, member, make_book
    ):
        """The control. Without it the arm above passes on five doors that all
        answer 404 for a reason of their own."""
        visible = make_collection(client, admin["headers"], "Ebooks")
        shared = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], shared["id"], visible["id"])
        mine = make_book(member["headers"], title="Mine")
        unused = visible["id"] + 1000

        allowed = self._doors(client, member["headers"], mine["id"], visible["id"])
        absent = self._doors(client, member["headers"], mine["id"], unused)

        assert [res.status_code for res in allowed.values()] != [
            res.status_code for res in absent.values()
        ]
        assert all(res.status_code < 400 for res in allowed.values()), {
            name: (res.status_code, res.text) for name, res in allowed.items()
        }
