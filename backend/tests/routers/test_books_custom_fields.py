"""The custom fields API: defining one for the library, filling it in on a book.

Tested at the two seams book facts are already tested at, the router and the
ORM, exactly as the ticket asks. Nothing here asserts the shape of a join.

**User story 7 is the one worth reading first.** A value on a private book has
to obey the same visibility rule as the book, and it is asserted through the
API rather than through the ORM, because the API is where a leak would happen.
"""

import pytest


@pytest.fixture
def link_field(client, admin):
    res = client.post(
        "/api/books/custom-fields",
        json={"name": "Calibre-web", "kind": "url"},
        headers=admin["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def text_field(client, admin):
    res = client.post(
        "/api/books/custom-fields",
        json={"name": "Bought from", "kind": "text"},
        headers=admin["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


def _set(client, headers, book_id, field_id, value):
    return client.put(
        f"/api/books/{book_id}/custom-fields/{field_id}",
        json={"value": value},
        headers=headers,
    )


class TestDefiningAFieldForTheLibrary:
    def test_a_field_appears_on_every_book_as_available(
        self, client, admin, make_book, text_field
    ):
        first = make_book(admin["headers"], title="One")
        second = make_book(admin["headers"], title="Two")

        listed = client.get("/api/books/custom-fields", headers=admin["headers"]).json()

        assert [field["name"] for field in listed] == ["Bought from"]
        for book in (first, second):
            filled = client.get(
                f"/api/books/{book['id']}/custom-fields", headers=admin["headers"]
            )
            assert filled.json() == []

    def test_any_member_may_define_one(self, client, member, text_field):
        res = client.post(
            "/api/books/custom-fields",
            json={"name": "Shelf photo", "kind": "text"},
            headers=member["headers"],
        )

        assert res.status_code == 201

    def test_a_name_that_exists_returns_that_field(self, client, admin, text_field):
        res = client.post(
            "/api/books/custom-fields",
            json={"name": "bought FROM", "kind": "url"},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["id"] == text_field["id"]
        assert res.json()["kind"] == "text"

    def test_a_blank_name_is_refused(self, client, admin):
        res = client.post(
            "/api/books/custom-fields", json={"name": "   "}, headers=admin["headers"]
        )

        assert res.status_code == 422

    def test_a_name_past_the_bound_is_refused(self, client, admin):
        res = client.post(
            "/api/books/custom-fields",
            json={"name": "x" * 61},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_the_library_is_capped(self, client, admin):
        for index in range(25):
            assert (
                client.post(
                    "/api/books/custom-fields",
                    json={"name": f"Field {index}"},
                    headers=admin["headers"],
                ).status_code
                == 201
            )

        res = client.post(
            "/api/books/custom-fields",
            json={"name": "One too many"},
            headers=admin["headers"],
        )

        assert res.status_code == 409


class TestFillingItInOnOneBook:
    def test_the_value_lives_with_the_book_it_describes(
        self, client, admin, make_book, text_field
    ):
        book = make_book(admin["headers"])

        res = _set(client, admin["headers"], book["id"], text_field["id"], "Oxfam")

        assert res.status_code == 200
        assert res.json() == [
            {
                "field_id": text_field["id"],
                "name": "Bought from",
                "kind": "text",
                "value": "Oxfam",
                "href": None,
            }
        ]

    def test_a_value_set_on_one_book_is_not_on_another(
        self, client, admin, make_book, text_field
    ):
        first = make_book(admin["headers"], title="One")
        second = make_book(admin["headers"], title="Two")
        _set(client, admin["headers"], first["id"], text_field["id"], "Oxfam")

        res = client.get(
            f"/api/books/{second['id']}/custom-fields", headers=admin["headers"]
        )

        assert res.json() == []

    def test_a_book_with_no_value_shows_nothing(
        self, client, admin, make_book, text_field, link_field
    ):
        book = make_book(admin["headers"])
        _set(client, admin["headers"], book["id"], text_field["id"], "Oxfam")

        res = client.get(f"/api/books/{book['id']}/custom-fields", headers=admin["headers"])

        assert [row["field_id"] for row in res.json()] == [text_field["id"]]

    def test_an_empty_value_clears_it(self, client, admin, make_book, text_field):
        book = make_book(admin["headers"])
        _set(client, admin["headers"], book["id"], text_field["id"], "Oxfam")

        res = _set(client, admin["headers"], book["id"], text_field["id"], "")

        assert res.json() == []

    def test_a_value_past_the_bound_is_refused(self, client, admin, make_book, text_field):
        book = make_book(admin["headers"])

        res = _set(client, admin["headers"], book["id"], text_field["id"], "x" * 501)

        assert res.status_code == 422

    def test_a_field_that_does_not_exist_is_a_404(self, client, admin, make_book):
        book = make_book(admin["headers"])

        assert _set(client, admin["headers"], book["id"], 9999, "x").status_code == 404

    def test_a_field_id_past_the_databases_range_is_refused(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])

        res = _set(client, admin["headers"], book["id"], 2**63, "x")

        assert res.status_code == 422


class TestAUrlRendersAsALink:
    """Asserted on what the API renders, not on a helper.

    `href` is what a client points an `<a>` at, and `value` is what it prints.
    A value that is not a link comes back with `href` null and is text.
    """

    def test_a_url_field_carries_a_target(self, client, admin, make_book, link_field):
        book = make_book(admin["headers"])

        res = _set(
            client,
            admin["headers"],
            book["id"],
            link_field["id"],
            "https://calibre.example/book/12",
        )

        assert res.json()[0]["href"] == "https://calibre.example/book/12"

    def test_a_text_field_never_carries_one(self, client, admin, make_book, text_field):
        book = make_book(admin["headers"])

        res = _set(
            client,
            admin["headers"],
            book["id"],
            text_field["id"],
            "https://calibre.example/book/12",
        )

        assert res.json()[0]["href"] is None

    @pytest.mark.parametrize(
        "value",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "//evil.example/x",
            "https://calibre.example@evil.example/",
            "calibre.example/book/12",
            # **Through the route, not through `write()`.** The schema tidies a
            # value before the seam sees it, so a rule asserted only against
            # `link_target` says nothing about what the API does. A single
            # space survives that tidy, reaches `link_target`, and is refused
            # there: `new URL("https://calibre.example /x")` throws, so an href
            # built from it is a link nothing can follow.
            "https://calibre.example /x",
            "http://calibre.example\\.evil.example/x",
            # WHATWG decodes the host before IDNA maps it, so this resolves to
            # `evil.example` while reading as a host the household trusts.
            # `_one_line` does not touch `%`, so it reaches the column verbatim
            # through an ordinary PUT: the route is the only place this is
            # provable.
            "https://calibre.example%2eevil.example/x",
            "https://calibre.example%ef%bc%8eevil.example/x",
        ],
        ids=[
            "javascript",
            "data",
            "scheme relative",
            "credentials",
            "no scheme",
            "a space in the host",
            "a backslash in the host",
            "a percent encoded full stop",
            "a percent encoded fullwidth stop",
        ],
    )
    def test_a_url_field_refuses_what_is_not_a_web_address(
        self, client, admin, make_book, link_field, value
    ):
        book = make_book(admin["headers"])

        res = _set(client, admin["headers"], book["id"], link_field["id"], value)

        assert res.status_code == 422, res.text
        assert client.get(
            f"/api/books/{book['id']}/custom-fields", headers=admin["headers"]
        ).json() == []


class TestATabIsDroppedRatherThanCollapsed:
    """The ordering finding, end to end.

    `_one_line` used to collapse a tab into a **space**, which `urlsplit` then
    kept, so the tab this rule exists to strip never reached the parser. The
    API answered 200 with `href` set to `https://calibre.example /x`, which
    `new URL()` throws on: the client refused it and the link rendered as text
    with nothing saying why.

    A tab is now removed, so the value is the URL both parsers already read.
    That is an **acceptance**, not a refusal, and the distinction is the point:
    the member typed a good URL with an invisible character in it.
    """

    def test_the_tab_vanishes_and_the_link_works(
        self, client, admin, make_book, link_field
    ):
        book = make_book(admin["headers"])

        res = _set(
            client,
            admin["headers"],
            book["id"],
            link_field["id"],
            "https://calibre.example\t/book/12",
        )

        assert res.status_code == 200, res.text
        assert res.json()[0]["value"] == "https://calibre.example/book/12"
        assert res.json()[0]["href"] == "https://calibre.example/book/12"


class TestAHostABrowserReadsDifferently:
    """The phishing case, end to end.

    A member can type a host that reads as one this household trusts and that a
    browser resolves elsewhere, because `urlsplit` and WHATWG disagree about
    three code points. Asserted on the API rather than on `link_target`,
    because what is **stored** is the half that matters: the value is what the
    next reader sees.
    """

    def test_the_stored_value_names_the_host_that_will_be_reached(
        self, client, admin, make_book, link_field
    ):
        book = make_book(admin["headers"])

        res = _set(
            client,
            admin["headers"],
            book["id"],
            link_field["id"],
            "https://calibre.example\u3002evil.example/x",
        )

        assert res.status_code == 200, res.text
        # Both, and they are two different claims: the href goes where the
        # browser was always going to go, and the text no longer lies about it.
        assert res.json()[0]["href"] == "https://calibre.example.evil.example/x"
        assert res.json()[0]["value"] == "https://calibre.example.evil.example/x"

    def test_it_survives_a_reread(self, client, admin, make_book, link_field):
        """Nothing is repaired on the way out, so the row itself has to be
        right: `link_target` runs again on every read and must agree."""
        book = make_book(admin["headers"])
        _set(
            client,
            admin["headers"],
            book["id"],
            link_field["id"],
            "https://calibre.example\uff61evil.example/x",
        )

        again = client.get(
            f"/api/books/{book['id']}/custom-fields", headers=admin["headers"]
        )

        assert [row["href"] for row in again.json()] == [
            "https://calibre.example.evil.example/x"
        ]


class TestAPercentEscapeIsOnlyRefusedInTheHost:
    def test_a_path_escape_is_stored_and_linked(
        self, client, admin, make_book, link_field
    ):
        """The other half of the host rule, asserted so the refusal above is
        not read as "no percent escapes"."""
        book = make_book(admin["headers"])

        res = _set(
            client,
            admin["headers"],
            book["id"],
            link_field["id"],
            "https://calibre.example/book/12%20a",
        )

        assert res.status_code == 200, res.text
        assert res.json()[0]["href"] == "https://calibre.example/book/12%20a"


class TestControlCharactersDoNotSurvive:
    def test_a_nul_is_removed_from_a_value(self, client, admin, make_book, text_field):
        """`str.split()` does not drop a NUL: it is not whitespace. Measured on
        the live route, `a\x00b` was stored unchanged, serialised as
        `\\u0000`, and invisible everywhere a person could notice it."""
        book = make_book(admin["headers"])

        res = _set(client, admin["headers"], book["id"], text_field["id"], "a\x00b\x01c")

        assert res.json()[0]["value"] == "abc"

    def test_a_nul_is_removed_from_a_name(self, client, admin):
        res = client.post(
            "/api/books/custom-fields",
            json={"name": "Calibre\x00web"},
            headers=admin["headers"],
        )

        assert res.json()["name"] == "Calibreweb"


class TestRenamingAField:
    def test_the_values_survive(self, client, admin, make_book, text_field):
        book = make_book(admin["headers"])
        _set(client, admin["headers"], book["id"], text_field["id"], "Oxfam")

        renamed = client.patch(
            f"/api/books/custom-fields/{text_field['id']}",
            json={"name": "Provenance"},
            headers=admin["headers"],
        )

        assert renamed.status_code == 200
        assert client.get(
            f"/api/books/{book['id']}/custom-fields", headers=admin["headers"]
        ).json() == [
            {
                "field_id": text_field["id"],
                "name": "Provenance",
                "kind": "text",
                "value": "Oxfam",
                "href": None,
            }
        ]

    def test_renaming_onto_another_field_is_refused(
        self, client, admin, text_field, link_field
    ):
        res = client.patch(
            f"/api/books/custom-fields/{text_field['id']}",
            json={"name": "calibre-WEB"},
            headers=admin["headers"],
        )

        assert res.status_code == 409

    def test_any_member_may_rename(self, client, admin, member, text_field):
        res = client.patch(
            f"/api/books/custom-fields/{text_field['id']}",
            json={"name": "Provenance"},
            headers=member["headers"],
        )

        assert res.status_code == 200


class TestDeletingAField:
    def test_it_stops_appearing_and_takes_its_values(
        self, client, admin, make_book, text_field
    ):
        book = make_book(admin["headers"])
        _set(client, admin["headers"], book["id"], text_field["id"], "Oxfam")

        res = client.delete(
            f"/api/books/custom-fields/{text_field['id']}", headers=admin["headers"]
        )

        assert res.status_code == 204
        assert client.get("/api/books/custom-fields", headers=admin["headers"]).json() == []
        assert client.get(
            f"/api/books/{book['id']}/custom-fields", headers=admin["headers"]
        ).json() == []

    def test_it_leaves_another_fields_values_alone(
        self, client, admin, make_book, text_field, link_field
    ):
        book = make_book(admin["headers"])
        _set(client, admin["headers"], book["id"], text_field["id"], "Oxfam")
        _set(
            client,
            admin["headers"],
            book["id"],
            link_field["id"],
            "https://calibre.example/1",
        )

        client.delete(
            f"/api/books/custom-fields/{text_field['id']}", headers=admin["headers"]
        )

        remaining = client.get(
            f"/api/books/{book['id']}/custom-fields", headers=admin["headers"]
        ).json()
        assert [row["field_id"] for row in remaining] == [link_field["id"]]

    def test_a_plain_member_may_not(self, client, admin, member, text_field):
        """Admin only, and deliberately asymmetric with defining one: the same
        split `delete_tag` makes, and the sharper case of it. Deleting a field
        destroys what every member typed, on books the caller may not see."""
        res = client.delete(
            f"/api/books/custom-fields/{text_field['id']}", headers=member["headers"]
        )

        assert res.status_code == 403
        assert len(client.get("/api/books/custom-fields", headers=member["headers"]).json()) == 1


class TestAFieldOnAPrivateBookIsInvisible:
    """User story 7, through the API.

    The rule is not a second copy of `visible_to()`: the routes take
    `BookForRead` and `BookForWrite`, so a book somebody else made private is
    404 before a custom field is mentioned. These pin that it stays that way.
    """

    @pytest.fixture
    def private_book(self, client, admin, make_book, text_field):
        book = make_book(admin["headers"], title="A diary")
        assert (
            client.patch(
                f"/api/books/{book['id']}/privacy",
                json={"is_private": True},
                headers=admin["headers"],
            ).status_code
            == 200
        )
        _set(client, admin["headers"], book["id"], text_field["id"], "A secret shop")
        return book

    def test_another_member_cannot_read_the_value(self, client, member, private_book):
        res = client.get(
            f"/api/books/{private_book['id']}/custom-fields", headers=member["headers"]
        )

        assert res.status_code == 404
        assert "secret" not in res.text

    def test_another_member_cannot_write_one(
        self, client, member, private_book, text_field
    ):
        res = _set(
            client, member["headers"], private_book["id"], text_field["id"], "Mine now"
        )

        assert res.status_code == 404

    def test_it_is_404_and_never_403(self, client, member, private_book):
        """A 403 would confirm the id exists, which is what privacy withholds."""
        res = client.get(
            f"/api/books/{private_book['id']}/custom-fields", headers=member["headers"]
        )

        assert res.status_code == 404
        assert res.json()["detail"] == "Book not found"

    def test_the_owner_still_sees_it(self, client, admin, private_book):
        res = client.get(
            f"/api/books/{private_book['id']}/custom-fields", headers=admin["headers"]
        )

        assert [row["value"] for row in res.json()] == ["A secret shop"]

    def test_the_definition_itself_is_not_a_disclosure(
        self, client, member, private_book, text_field
    ):
        """A field is library wide, exactly like a tag, and carries no count.

        So listing them says which facts the household keeps and nothing about
        which books hold one, which is why there is no `book_count` here and
        `GET /api/books/tags` needs its count filtered through the Shelf.
        """
        listed = client.get("/api/books/custom-fields", headers=member["headers"]).json()

        assert [field["name"] for field in listed] == ["Bought from"]
        assert all("count" not in key for field in listed for key in field)


class TestMergingTwoBooks:
    def test_the_losers_value_is_not_destroyed(
        self, client, admin, make_book, text_field
    ):
        """The cascade would have taken it, silently, exactly as it once would
        have taken the quotes."""
        keeper = make_book(admin["headers"], title="Solaris")
        loser = make_book(admin["headers"], title="Solaris")
        _set(client, admin["headers"], loser["id"], text_field["id"], "Oxfam")

        merged = client.post(
            "/api/books/merge",
            json={"keep_id": keeper["id"], "book_ids": [keeper["id"], loser["id"]]},
            headers=admin["headers"],
        )

        assert merged.status_code == 200, merged.text
        assert [
            row["value"]
            for row in client.get(
                f"/api/books/{keeper['id']}/custom-fields", headers=admin["headers"]
            ).json()
        ] == ["Oxfam"]

    def test_the_keepers_own_value_wins(self, client, admin, make_book, text_field):
        keeper = make_book(admin["headers"], title="Solaris")
        loser = make_book(admin["headers"], title="Solaris")
        _set(client, admin["headers"], keeper["id"], text_field["id"], "A gift")
        _set(client, admin["headers"], loser["id"], text_field["id"], "Oxfam")

        client.post(
            "/api/books/merge",
            json={"keep_id": keeper["id"], "book_ids": [keeper["id"], loser["id"]]},
            headers=admin["headers"],
        )

        assert [
            row["value"]
            for row in client.get(
                f"/api/books/{keeper['id']}/custom-fields", headers=admin["headers"]
            ).json()
        ] == ["A gift"]


class TestPurgingABook:
    def test_its_values_go_with_it(self, client, admin, make_book, text_field, db):
        from models import CustomFieldValue

        book = make_book(admin["headers"])
        _set(client, admin["headers"], book["id"], text_field["id"], "Oxfam")
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        client.delete(f"/api/books/{book['id']}/permanent", headers=admin["headers"])

        assert db.query(CustomFieldValue).count() == 0
