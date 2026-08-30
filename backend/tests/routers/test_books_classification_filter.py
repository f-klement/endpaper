"""Classifications as a facet, a filter and a shelf order.

The store landed long before any of this and nothing rendered it, so what is
pinned here is the three surfaces that read it: the facet list the filter panel
draws, the two filters, and the Dewey sort.

**The facet list is the interesting one and it is a privacy test, not a feature
test.** `classifications` carries no member, so nothing about a row says who may
see it. A facet list is exactly the shape that leaks: "every Dewey number in the
library, with a count" publishes what is on other people's private books without
returning one of them.
"""

FACETS = "/api/books/classifications"


def heading(scheme: str, number: str, label: str | None = None) -> dict:
    return {"scheme": scheme, "number": number, "label": label}


class TestTheFacetList:
    def test_counts_the_books_carrying_each_heading(self, client, admin, make_book):
        make_book(admin["headers"], title="One", classifications=[heading("lcsh", "Stress management")])
        make_book(admin["headers"], title="Two", classifications=[heading("lcsh", "Stress management")])
        make_book(admin["headers"], title="Three", classifications=[heading("lcsh", "Mental health")])

        body = client.get(FACETS, headers=admin["headers"]).json()

        counts = {row["number"]: row["book_count"] for row in body["headings"]}
        assert counts == {"Stress management": 2, "Mental health": 1}

    def test_keeps_the_scheme_so_two_schemes_do_not_collapse(self, client, admin, make_book):
        """`004` in Dewey and `004` elsewhere are different assertions."""
        make_book(admin["headers"], classifications=[heading("ddc", "004"), heading("lcc", "004")])

        rows = client.get(FACETS, headers=admin["headers"]).json()["headings"]

        assert sorted(row["scheme"] for row in rows) == ["ddc", "lcc"]

    def test_a_division_counts_a_book_once_however_precisely_it_is_classified(
        self, client, admin, make_book
    ):
        """The `distinct` in `_division_counts`, pinned.

        A catalogue that supplies both `004` and `005.133` describes one book
        twice. Counting the rows would report division 000 as holding two.
        """
        make_book(
            admin["headers"],
            classifications=[heading("ddc", "004"), heading("ddc", "005.133")],
        )

        divisions = client.get(FACETS, headers=admin["headers"]).json()["divisions"]

        assert [(row["division"], row["book_count"]) for row in divisions] == [("000", 1)]

    def test_projects_a_fraction_onto_its_division(self, client, admin, make_book):
        """`155.9042` is filed at 150, not at 155 and not at itself."""
        make_book(admin["headers"], classifications=[heading("ddc", "155.9042")])

        divisions = client.get(FACETS, headers=admin["headers"]).json()["divisions"]

        assert [row["division"] for row in divisions] == ["150"]

    def test_labels_a_division_with_this_librarys_word_or_with_nothing(
        self, client, admin, make_book
    ):
        """Not Dewey's caption: the seeded tag the division maps to.

        080 is quotations and maps to no tag, and an absent label is a real
        answer there rather than a gap. The schema field says why at length.
        """
        make_book(admin["headers"], classifications=[heading("ddc", "150.1")])
        make_book(admin["headers"], classifications=[heading("ddc", "080.5")])

        divisions = client.get(FACETS, headers=admin["headers"]).json()["divisions"]

        labels = {row["division"]: row["label"] for row in divisions}
        assert labels == {"150": "Psychology", "080": None}

    def test_says_nothing_about_another_members_private_book(
        self, client, admin, member, make_book
    ):
        """The disclosure this endpoint was built carefully to avoid.

        The heading is on a private book belonging to somebody else, so it must
        not appear at all: not with a count of zero, not with a count of one.
        """
        book = make_book(admin["headers"], classifications=[heading("lcsh", "Grief")])
        client.patch(
            f"/api/books/{book['id']}/privacy",
            json={"is_private": True},
            headers=admin["headers"],
        )

        body = client.get(FACETS, headers=member["headers"]).json()

        assert body["headings"] == []
        assert body["divisions"] == []

    def test_still_shows_a_member_their_own_private_book(self, client, admin, make_book):
        """The other half, so the test above cannot pass by filtering everything."""
        book = make_book(admin["headers"], classifications=[heading("lcsh", "Grief")])
        client.patch(
            f"/api/books/{book['id']}/privacy",
            json={"is_private": True},
            headers=admin["headers"],
        )

        body = client.get(FACETS, headers=admin["headers"]).json()

        assert [row["number"] for row in body["headings"]] == ["Grief"]

    def test_needs_a_session(self, client):
        assert client.get(FACETS).status_code == 401

    def test_offers_at_most_the_capped_number_of_headings(self, client, admin, make_book):
        """The cap, and that it keeps the headings most of the library shares.

        `/tags` and `/locations` need no cap because a person writes those. This
        list is written by catalogues, at up to eight rows a book.
        """
        from shelf import MAX_HEADING_FACETS

        shared = "Shared by two"
        make_book(admin["headers"], classifications=[heading("lcsh", shared)])
        make_book(
            admin["headers"],
            classifications=[heading("lcsh", shared)]
            + [heading("gnd", f"{n}") for n in range(7)],
        )

        rows = client.get(FACETS, headers=admin["headers"]).json()["headings"]

        assert len(rows) <= MAX_HEADING_FACETS
        # The shared one survives whatever the cap is, because the cap selects
        # by count. Written as a membership check rather than a position, since
        # the router re-sorts for presentation.
        assert {"lcsh", shared} <= {rows[0]["scheme"], rows[0]["number"]} or any(
            row["number"] == shared and row["book_count"] == 2 for row in rows
        )


class TestTheHeadingFilter:
    def test_narrows_to_the_books_carrying_one_heading(self, client, admin, make_book):
        make_book(admin["headers"], title="Kept", classifications=[heading("lcsh", "Mental health")])
        make_book(admin["headers"], title="Dropped")

        body = client.get(
            "/api/books", params={"classification": "lcsh:Mental health"}, headers=admin["headers"]
        ).json()

        assert [row["title"] for row in body["items"]] == ["Kept"]

    def test_two_headings_are_anded(self, client, admin, make_book):
        """The tag filter's operator, for the reason `matching()` gives."""
        make_book(
            admin["headers"],
            title="Both",
            classifications=[heading("lcsh", "Mental health"), heading("lcsh", "Stress management")],
        )
        make_book(admin["headers"], title="One", classifications=[heading("lcsh", "Mental health")])

        body = client.get(
            "/api/books",
            params=[("classification", "lcsh:Mental health"), ("classification", "lcsh:Stress management")],
            headers=admin["headers"],
        ).json()

        assert [row["title"] for row in body["items"]] == ["Both"]

    def test_a_heading_containing_a_colon_survives_the_parse(self, client, admin, make_book):
        """Split on the first colon only. This is why the parameter repeats."""
        make_book(
            admin["headers"],
            title="Kept",
            classifications=[heading("lcsh", "Photography: a history")],
        )
        make_book(admin["headers"], title="Dropped")

        body = client.get(
            "/api/books",
            params={"classification": "lcsh:Photography: a history"},
            headers=admin["headers"],
        ).json()

        assert [row["title"] for row in body["items"]] == ["Kept"]

    def test_a_heading_containing_a_comma_survives_the_parse(self, client, admin, make_book):
        """The measurement the wire format was chosen for."""
        make_book(
            admin["headers"],
            title="Kept",
            classifications=[heading("lcsh", "Mental health, Public")],
        )
        make_book(admin["headers"], title="Dropped")

        body = client.get(
            "/api/books",
            params={"classification": "lcsh:Mental health, Public"},
            headers=admin["headers"],
        ).json()

        assert [row["title"] for row in body["items"]] == ["Kept"]

    def test_the_scheme_is_part_of_the_match(self, client, admin, make_book):
        make_book(admin["headers"], title="Dewey", classifications=[heading("ddc", "004")])

        body = client.get(
            "/api/books", params={"classification": "lcc:004"}, headers=admin["headers"]
        ).json()

        assert body["items"] == []

    def test_an_unrecognised_scheme_is_ignored_rather_than_refused(
        self, client, admin, make_book
    ):
        """`row_ids`'s contract: a link is not a form."""
        make_book(admin["headers"], title="Kept")

        res = client.get(
            "/api/books", params={"classification": "bogus:004"}, headers=admin["headers"]
        )

        assert res.status_code == 200
        assert [row["title"] for row in res.json()["items"]] == ["Kept"]

    def test_too_many_headings_is_refused_with_the_ceiling_named(self, client, admin):
        res = client.get(
            "/api/books",
            params=[("classification", f"lcsh:heading {n}") for n in range(33)],
            headers=admin["headers"],
        )

        assert res.status_code == 422
        assert "32" in res.json()["detail"]

    def test_cannot_reach_another_members_private_book(self, client, admin, member, make_book):
        book = make_book(admin["headers"], classifications=[heading("lcsh", "Grief")])
        client.patch(
            f"/api/books/{book['id']}/privacy",
            json={"is_private": True},
            headers=admin["headers"],
        )

        body = client.get(
            "/api/books", params={"classification": "lcsh:Grief"}, headers=member["headers"]
        ).json()

        assert body["items"] == []


class TestTheDivisionFilter:
    def test_matches_a_fraction_through_its_division(self, client, admin, make_book):
        make_book(admin["headers"], title="Kept", classifications=[heading("ddc", "155.9042")])
        make_book(admin["headers"], title="Dropped", classifications=[heading("ddc", "004")])

        body = client.get(
            "/api/books", params={"ddc": "150"}, headers=admin["headers"]
        ).json()

        assert [row["title"] for row in body["items"]] == ["Kept"]

    def test_two_divisions_are_ored(self, client, admin, make_book):
        """The one place this deliberately disagrees with the tag filter.

        ANDing two divisions would return only books carrying two Dewey numbers
        in different divisions, which is a question nobody asks.
        """
        make_book(admin["headers"], title="Psych", classifications=[heading("ddc", "155.9")])
        make_book(admin["headers"], title="Econ", classifications=[heading("ddc", "330.1")])
        make_book(admin["headers"], title="Neither", classifications=[heading("ddc", "004")])

        body = client.get(
            "/api/books", params={"ddc": "150,330"}, headers=admin["headers"]
        ).json()

        assert sorted(row["title"] for row in body["items"]) == ["Econ", "Psych"]

    def test_a_full_number_asked_for_as_a_division_resolves_rather_than_dropping(
        self, client, admin, make_book
    ):
        """`?ddc=155.9042` is the link a chip would produce if nobody projected."""
        make_book(admin["headers"], title="Kept", classifications=[heading("ddc", "155.1")])

        body = client.get(
            "/api/books", params={"ddc": "155.9042"}, headers=admin["headers"]
        ).json()

        assert [row["title"] for row in body["items"]] == ["Kept"]

    def test_only_dewey_rows_are_projected(self, client, admin, make_book):
        """An LCC number starting with digits must not be read as a division."""
        make_book(admin["headers"], title="LC", classifications=[heading("lcc", "155.9042")])

        body = client.get(
            "/api/books", params={"ddc": "150"}, headers=admin["headers"]
        ).json()

        assert body["items"] == []

    def test_junk_is_ignored_rather_than_refused(self, client, admin, make_book):
        make_book(admin["headers"], title="Kept")

        res = client.get("/api/books", params={"ddc": "junk"}, headers=admin["headers"])

        assert res.status_code == 200
        assert [row["title"] for row in res.json()["items"]] == ["Kept"]


class TestTheDeweySort:
    def test_orders_by_the_number_with_the_unclassified_last(self, client, admin, make_book):
        make_book(admin["headers"], title="Economics", classifications=[heading("ddc", "330.1")])
        make_book(admin["headers"], title="Unclassified")
        make_book(admin["headers"], title="Computing", classifications=[heading("ddc", "004")])
        make_book(admin["headers"], title="Psychology", classifications=[heading("ddc", "155.9042")])

        body = client.get("/api/books", params={"sort": "ddc"}, headers=admin["headers"]).json()

        assert [row["title"] for row in body["items"]] == [
            "Computing",
            "Psychology",
            "Economics",
            "Unclassified",
        ]

    def test_ignores_a_call_number_from_another_scheme(self, client, admin, make_book):
        """Dewey and no other scheme, which is what the enum value is named for."""
        make_book(admin["headers"], title="Dewey", classifications=[heading("ddc", "900")])
        make_book(admin["headers"], title="LC only", classifications=[heading("lcc", "BF575")])

        body = client.get("/api/books", params={"sort": "ddc"}, headers=admin["headers"]).json()

        assert [row["title"] for row in body["items"]] == ["Dewey", "LC only"]

    def test_files_a_book_under_its_lowest_number(self, client, admin, make_book):
        """One value per row, and `min` is which one."""
        make_book(
            admin["headers"],
            title="Two numbers",
            classifications=[heading("ddc", "900"), heading("ddc", "004")],
        )
        make_book(admin["headers"], title="Middle", classifications=[heading("ddc", "500")])

        body = client.get("/api/books", params={"sort": "ddc"}, headers=admin["headers"]).json()

        assert [row["title"] for row in body["items"]] == ["Two numbers", "Middle"]

    def test_returns_each_book_once_however_many_headings_it_carries(
        self, client, admin, make_book
    ):
        """A join would multiply the page; the sort uses a correlated subquery."""
        make_book(
            admin["headers"],
            title="Eight headings",
            classifications=[heading("ddc", f"00{n}") for n in range(1, 9)],
        )

        body = client.get("/api/books", params={"sort": "ddc"}, headers=admin["headers"]).json()

        assert body["total"] == 1
        assert [row["title"] for row in body["items"]] == ["Eight headings"]
