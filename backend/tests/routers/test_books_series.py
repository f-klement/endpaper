"""Series, shelf location, and editing a catalogue entry by hand.

The series view exists to answer "which ones are we missing", so the gap
calculation is what most of this file is about.
"""

import pytest


def patch_details(client, headers, book_id: int, **fields):
    return client.patch(f"/api/books/{book_id}", json=fields, headers=headers)


def make_series(client, headers, make_book, name: str, indexes) -> list[dict]:
    books = []
    for index in indexes:
        book = make_book(headers, title=f"{name} {index}")
        patch_details(client, headers, book["id"], series_name=name, series_index=index)
        books.append(book)
    return books


class TestEditingDetails:
    def test_sets_a_field(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = patch_details(client, admin["headers"], book["id"], location="Living room")

        assert res.status_code == 200
        assert res.json()["location"] == "Living room"

    def test_leaves_absent_fields_alone(self, client, admin, make_book):
        """The classic PATCH bug: every unsent field arriving as None and wiping
        the record."""
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")

        res = patch_details(client, admin["headers"], book["id"], location="Loft")

        assert res.json()["title"] == "Dune"
        assert res.json()["author"] == "Frank Herbert"

    def test_an_explicit_null_clears(self, client, admin, make_book):
        book = make_book(admin["headers"])
        patch_details(client, admin["headers"], book["id"], series_name="Dune")

        res = patch_details(client, admin["headers"], book["id"], series_name=None)

        assert res.json()["series_name"] is None

    def test_corrects_several_fields_at_once(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = patch_details(
            client,
            admin["headers"],
            book["id"],
            title="Dune",
            author="Frank Herbert",
            year=1965,
            series_name="Dune Chronicles",
            series_index=1,
        )

        body = res.json()
        assert (body["title"], body["author"], body["year"]) == ("Dune", "Frank Herbert", 1965)
        assert (body["series_name"], body["series_index"]) == ("Dune Chronicles", 1.0)

    def test_a_half_number_is_allowed(self, client, admin, make_book):
        # Novellas and omnibus editions really are numbered 2.5.
        book = make_book(admin["headers"])

        res = patch_details(client, admin["headers"], book["id"], series_index=2.5)

        assert res.json()["series_index"] == 2.5

    def test_an_empty_title_is_rejected(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert patch_details(client, admin["headers"], book["id"], title="").status_code == 422

    def test_another_members_private_book_is_not_editable(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], is_private=True)
        res = patch_details(client, member["headers"], book["id"], location="Mine now")
        assert res.status_code == 404

    def test_any_member_may_edit_a_public_book(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        res = patch_details(client, member["headers"], book["id"], location="Kitchen")
        assert res.status_code == 200


class TestSeriesListing:
    def test_lists_a_series_with_its_count(self, client, admin, make_book):
        make_series(client, admin["headers"], make_book, "Dune", [1, 2, 3])

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()

        assert series["name"] == "Dune"
        assert series["book_count"] == 3

    def test_reports_the_gaps(self, client, admin, make_book):
        """The question a series view exists to answer."""
        make_series(client, admin["headers"], make_book, "Dune", [1, 3, 4, 6])

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()

        assert series["missing_indexes"] == [2, 5]

    def test_a_complete_series_has_no_gaps(self, client, admin, make_book):
        make_series(client, admin["headers"], make_book, "Dune", [1, 2, 3])

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()

        assert series["missing_indexes"] == []

    def test_does_not_invent_books_past_the_end(self, client, admin, make_book):
        """A series with no known length has no meaningful missing past the last
        one held. Reporting one would invent a book nobody said exists."""
        make_series(client, admin["headers"], make_book, "Dune", [1, 2])

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()

        assert series["missing_indexes"] == []

    def test_a_series_starting_at_two_reports_the_first_as_missing(
        self, client, admin, make_book
    ):
        make_series(client, admin["headers"], make_book, "Dune", [2, 3])

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()

        assert series["missing_indexes"] == [1]

    def test_a_half_numbered_entry_does_not_create_a_gap(self, client, admin, make_book):
        # 2.5 is not a missing whole number and must not make 2 or 3 look absent.
        make_series(client, admin["headers"], make_book, "Dune", [1, 2, 2.5, 3])

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()

        assert series["missing_indexes"] == []

    def test_a_series_with_no_numbers_at_all_reports_none_missing(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        patch_details(client, admin["headers"], book["id"], series_name="Unnumbered")

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()

        assert series["missing_indexes"] == []
        assert series["book_count"] == 1

    def test_books_with_no_series_are_absent(self, client, admin, make_book):
        make_book(admin["headers"], title="Standalone")
        assert client.get("/api/books/series", headers=admin["headers"]).json() == []

    def test_another_members_private_book_is_not_counted(
        self, client, admin, member, make_book
    ):
        private = make_book(admin["headers"], is_private=True)
        patch_details(client, admin["headers"], private["id"], series_name="Dune", series_index=1)

        assert client.get("/api/books/series", headers=member["headers"]).json() == []

    def test_the_path_is_not_read_as_a_book_id(self, client, admin, make_book):
        """`/series` is declared before `/{book_id}`, or it is a request for the
        book with id "series"."""
        res = client.get("/api/books/series", headers=admin["headers"])
        assert res.status_code == 200
        assert isinstance(res.json(), list)


class TestSeriesFilterAndSort:
    def test_filters_to_one_series(self, client, admin, make_book):
        make_series(client, admin["headers"], make_book, "Dune", [1, 2])
        make_book(admin["headers"], title="Standalone")

        res = client.get("/api/books", params={"series": "Dune"}, headers=admin["headers"])

        assert len(res.json()["items"]) == 2

    def test_sorts_by_series_order(self, client, admin, make_book):
        make_series(client, admin["headers"], make_book, "Dune", [3, 1, 2])

        res = client.get("/api/books", params={"sort": "series"}, headers=admin["headers"])

        assert [b["series_index"] for b in res.json()["items"]] == [1.0, 2.0, 3.0]

    def test_books_with_no_series_sort_last(self, client, admin, make_book):
        """Mixing them in by a NULL index would scatter them through the list."""
        make_book(admin["headers"], title="Aaa Standalone")
        make_series(client, admin["headers"], make_book, "Zzz Series", [1])

        res = client.get("/api/books", params={"sort": "series"}, headers=admin["headers"])

        assert [b["series_name"] for b in res.json()["items"]] == ["Zzz Series", None]


class TestLocations:
    def test_lists_locations_in_use(self, client, admin, make_book):
        for title, place in (("A", "Living room"), ("B", "Living room"), ("C", "Loft")):
            book = make_book(admin["headers"], title=title)
            patch_details(client, admin["headers"], book["id"], location=place)

        rows = client.get("/api/books/locations", headers=admin["headers"]).json()

        # Most-populated first: it doubles as the autocomplete source, and the
        # shelf someone uses most is the one they mean next.
        assert [(r["name"], r["book_count"]) for r in rows] == [
            ("Living room", 2),
            ("Loft", 1),
        ]

    def test_books_with_no_location_are_absent(self, client, admin, make_book):
        make_book(admin["headers"])
        assert client.get("/api/books/locations", headers=admin["headers"]).json() == []

    def test_an_empty_string_is_not_a_location(self, client, admin, make_book):
        book = make_book(admin["headers"])
        patch_details(client, admin["headers"], book["id"], location="")

        assert client.get("/api/books/locations", headers=admin["headers"]).json() == []

    def test_filters_the_listing(self, client, admin, make_book):
        here = make_book(admin["headers"], title="Here")
        make_book(admin["headers"], title="Elsewhere")
        patch_details(client, admin["headers"], here["id"], location="Loft")

        res = client.get("/api/books", params={"location": "Loft"}, headers=admin["headers"])

        assert [b["title"] for b in res.json()["items"]] == ["Here"]

    def test_another_members_private_book_is_not_counted(
        self, client, admin, member, make_book
    ):
        private = make_book(admin["headers"], is_private=True)
        patch_details(client, admin["headers"], private["id"], location="Loft")

        assert client.get("/api/books/locations", headers=member["headers"]).json() == []

    @pytest.mark.parametrize("path", ["/api/books/series", "/api/books/locations"])
    def test_requires_authentication(self, client, path):
        assert client.get(path).status_code == 401
