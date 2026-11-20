"""Tests for routers/patrons.py: the admin's patron register."""

import pytest

from dependencies import NUL_REFUSED
from models import Loan, Patron

URL = "/api/patrons"
SEARCH = f"{URL}/search"
PAT = {"card_number": "C1", "name": "Pat Lee", "email": "pat@example.org", "city": "Graz"}

#: Every route the router serves, with a body each would accept.
ROUTES = [
    ("post", SEARCH, {"q": "pat"}),
    ("post", URL, PAT),
    ("get", f"{URL}/1", None),
    ("patch", f"{URL}/1", {"name": "Pat Roe"}),
    ("delete", f"{URL}/1", None),
]


def _call(client, method: str, url: str, body, headers=None):
    kwargs = {"headers": headers or {}}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(url, **kwargs)


def _register(client, admin, **overrides) -> dict:
    res = client.post(URL, json=PAT | overrides, headers=admin["headers"])
    assert res.status_code == 201, res.text
    return res.json()


class TestOnlyAnAdminReachesIt:
    @pytest.mark.parametrize(("method", "url", "body"), ROUTES)
    def test_no_session_is_a_401(self, client, admin, method, url, body):
        _register(client, admin)
        assert _call(client, method, url, body).status_code == 401

    @pytest.mark.parametrize(("method", "url", "body"), ROUTES)
    def test_a_member_is_a_403(self, client, admin, member, method, url, body):
        _register(client, admin)
        assert _call(client, method, url, body, member["headers"]).status_code == 403

    def test_a_member_learns_nothing_about_an_id_that_does_not_exist(self, client, member):
        """403 before the lookup, so a missing id answers what an existing one does."""
        assert client.get(f"{URL}/999", headers=member["headers"]).status_code == 403

    def test_every_route_on_the_router_is_in_the_table_above(self):
        from main import app, iter_api_routes

        served = {
            (method.lower(), route.path)
            for route in iter_api_routes(app.routes)
            if route.path.startswith(URL)
            for method in route.methods or ()
        }
        assert served == {
            ("post", SEARCH),
            ("post", URL),
            ("get", f"{URL}/{{patron_id}}"),
            ("patch", f"{URL}/{{patron_id}}"),
            ("delete", f"{URL}/{{patron_id}}"),
        }


class TestTheRecord:
    def test_an_admin_registers_and_reads_one(self, client, admin):
        created = _register(client, admin)

        read = client.get(f"{URL}/{created['id']}", headers=admin["headers"]).json()

        assert read == created
        assert {key: read[key] for key in PAT} == PAT

    def test_a_card_number_another_patron_carries_is_a_409(self, client, admin):
        _register(client, admin)

        res = client.post(URL, json=PAT | {"name": "Sam Roe"}, headers=admin["headers"])

        assert res.status_code == 409

    def test_a_padded_card_number_is_the_same_card(self, client, admin):
        _register(client, admin)

        assert (
            client.post(URL, json=PAT | {"card_number": " C1 "}, headers=admin["headers"]).status_code == 409
        )

    def test_a_card_number_with_a_space_inside_is_a_422(self, client, admin):
        assert (
            client.post(URL, json=PAT | {"card_number": "C 1"}, headers=admin["headers"]).status_code == 422
        )

    def test_a_blank_name_is_a_422(self, client, admin):
        assert client.post(URL, json=PAT | {"name": "   "}, headers=admin["headers"]).status_code == 422

    def test_an_edit_changes_what_it_sends_and_clears_a_null(self, client, admin):
        created = _register(client, admin)

        res = client.patch(
            f"{URL}/{created['id']}", json={"name": "Pat Roe", "city": None}, headers=admin["headers"]
        )

        assert res.status_code == 200
        assert (res.json()["name"], res.json()["city"], res.json()["email"]) == (
            "Pat Roe",
            None,
            PAT["email"],
        )

    def test_an_edit_may_not_clear_the_name(self, client, admin):
        created = _register(client, admin)

        res = client.patch(f"{URL}/{created['id']}", json={"name": None}, headers=admin["headers"])

        assert res.status_code == 422

    def test_an_edit_to_another_patrons_card_number_is_a_409(self, client, admin):
        _register(client, admin)
        second = _register(client, admin, card_number="C2")

        res = client.patch(f"{URL}/{second['id']}", json={"card_number": "C1"}, headers=admin["headers"])

        assert res.status_code == 409

    def test_a_card_number_is_stored_upper_cased(self, client, admin):
        assert _register(client, admin, card_number="ab-12")["card_number"] == "AB-12"

    def test_a_card_number_in_another_case_is_the_same_card(self, client, admin):
        _register(client, admin)

        assert client.post(URL, json=PAT | {"card_number": "c1"}, headers=admin["headers"]).status_code == 409

    def test_an_edit_upper_cases_the_card_number_too(self, client, admin):
        created = _register(client, admin)

        res = client.patch(f"{URL}/{created['id']}", json={"card_number": "c9"}, headers=admin["headers"])

        assert res.json()["card_number"] == "C9"

    def test_an_unknown_id_is_a_404_to_an_admin(self, client, admin):
        assert client.get(f"{URL}/999", headers=admin["headers"]).status_code == 404


def _search(client, admin, body: dict):
    return client.post(SEARCH, json=body, headers=admin["headers"])


class TestSearch:
    def test_it_finds_by_card_number(self, client, admin):
        created = _register(client, admin)

        res = _search(client, admin, {"q": "c1"})

        assert [row["id"] for row in res.json()] == [created["id"]]

    def test_a_term_is_required(self, client, admin):
        assert _search(client, admin, {}).status_code == 422

    @pytest.mark.parametrize(
        "term",
        ["   ", "\x1c", "\x1f\x1e", "\x07 \x1b"],
        ids=["spaces", "one_separator", "two_separators", "bell_and_escape"],
    )
    def test_a_term_blank_once_cleaned_is_refused_rather_than_matching_everybody(self, client, admin, term):
        """`\\x1c` to `\\x1f` are whitespace no pattern's `\\s` names; a bell or an escape is removed."""
        _register(client, admin)

        res = _search(client, admin, {"q": term})

        assert res.status_code == 422
        assert isinstance(res.json()["detail"], list), "a 422 carries the array the schema declares"

    @pytest.mark.parametrize("term", ["P\x07at", "\x1bPat"], ids=["bell_inside", "escape_before"])
    def test_a_term_with_a_control_character_finds_the_name_it_was_cleaned_to(self, client, admin, term):
        """Cleaned as the name was on write, so the term matches what the column holds."""
        created = _register(client, admin)

        res = _search(client, admin, {"q": term})

        assert res.status_code == 200, res.text
        assert [row["id"] for row in res.json()] == [created["id"]]

    @pytest.mark.parametrize("term", ["\x00", "Pat\x00"], ids=["nul_alone", "nul_after_a_name"])
    def test_a_term_carrying_a_nul_is_the_declared_refusal_never_a_500(self, client, admin, term):
        """Postgres refuses a NUL in text, so one reaching `ILIKE` would be a 500 there."""
        _register(client, admin)

        res = _search(client, admin, {"q": term})

        assert res.status_code == 422, res.text
        assert [error["msg"] for error in res.json()["detail"]] == [f"Value error, {NUL_REFUSED}"]

    def test_a_limit_past_the_cap_is_a_422(self, client, admin):
        assert _search(client, admin, {"q": "pat", "limit": 51}).status_code == 422

    def test_no_patron_route_takes_a_query_parameter(self):
        """A query lands in every proxy's and server's request log, where no erasure reaches it."""
        from main import app

        in_the_query = [
            (path, method, parameter["name"])
            for path, operations in app.openapi()["paths"].items()
            if path.startswith(URL)
            for method, operation in operations.items()
            for parameter in operation.get("parameters", [])
            if parameter["in"] == "query"
        ]
        assert in_the_query == []


class TestDelete:
    def test_deleting_a_patron_anonymises_their_loans(self, client, db, admin, make_book):
        created = _register(client, admin)
        book = make_book(admin["headers"])
        db.add(
            Loan(book_id=book["id"], loaned_to_patron_id=created["id"], loaned_by_user_id=admin["user"]["id"])
        )
        db.commit()

        res = client.delete(f"{URL}/{created['id']}", headers=admin["headers"])

        db.expire_all()
        loan = db.query(Loan).one()
        assert res.status_code == 204
        assert (loan.loaned_to_patron_id, loan.borrower_anonymised_at is not None) == (None, True)
        assert db.get(Patron, created["id"]) is None
