"""Tests for the Google Books surfaces on backend/routers/books.py.

Three endpoints share one gate (`_require_google_books`) and one upstream:

  GET  /api/books/google/search        free text, before a book exists
  POST /api/books/{id}/enrich          fill this book's gaps
  GET  /api/books/{id}/enrich/candidates   other editions of this book

Every outbound call is intercepted with respx, so the suite never touches the
network and never needs a real API key.
"""

import httpx
import pytest
import respx

from enums import SettingKey

GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"


def volume(
    volume_id: str = "abc123",
    title: str = "Dune",
    *,
    categories: list[str] | None = None,
    page_count: int | None = 412,
    isbn13: str | None = "9780441013593",
) -> dict:
    """One item as Google returns it, trimmed to the fields we read."""
    info: dict = {
        "title": title,
        "subtitle": "A Novel",
        "authors": ["Frank Herbert"],
        "publisher": "Chilton",
        "publishedDate": "1965-08-01",
        "description": "Desert planet politics.",
        "language": "en",
        "imageLinks": {"thumbnail": "https://books.google.com/thumb.jpg"},
    }
    if categories is not None:
        info["categories"] = categories
    if page_count is not None:
        info["pageCount"] = page_count
    if isbn13 is not None:
        info["industryIdentifiers"] = [{"type": "ISBN_13", "identifier": isbn13}]
    return {"id": volume_id, "volumeInfo": info}


@pytest.fixture
def google_enabled(client, admin):
    """Switch the feature on and store a key, as an admin would in Settings."""
    client.put(
        "/api/settings",
        json={"google_books_enabled": True, "google_books_api_key": "test-key"},
        headers=admin["headers"],
    )


@pytest.fixture
def google_search():
    """Google answers a search with one volume."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(GOOGLE_BOOKS).mock(
            return_value=httpx.Response(200, json={"items": [volume()]})
        )
        yield mock


class TestSearchGate:
    """The feature is off by default, and the messages say who can fix it."""

    def test_requires_authentication(self, client):
        assert client.get("/api/books/google/search", params={"q": "dune"}).status_code == 401

    def test_refused_while_the_feature_is_off(self, client, admin):
        res = client.get(
            "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
        )

        assert res.status_code == 400
        assert "switched off" in res.json()["detail"]

    def test_refused_when_enabled_without_a_key(self, client, admin):
        client.put(
            "/api/settings", json={"google_books_enabled": True}, headers=admin["headers"]
        )

        res = client.get(
            "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
        )

        assert res.status_code == 400
        assert "API key" in res.json()["detail"]

    def test_the_key_is_never_echoed_back(self, client, admin, google_enabled):
        """A 400 explaining the setup must not leak the secret it is about."""
        client.put(
            "/api/settings", json={"google_books_enabled": False}, headers=admin["headers"]
        )

        res = client.get(
            "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
        )

        assert "test-key" not in res.text

    def test_a_member_may_search(self, client, member, google_enabled, google_search):
        """Configuring it is admin-only; using it is not."""
        res = client.get(
            "/api/books/google/search", params={"q": "dune"}, headers=member["headers"]
        )

        assert res.status_code == 200


class TestSearchResults:
    def test_maps_the_volume_fields(self, client, admin, google_enabled, google_search):
        [match] = client.get(
            "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
        ).json()

        assert match["title"] == "Dune"
        assert match["subtitle"] == "A Novel"
        assert match["author"] == "Frank Herbert"
        assert match["publisher"] == "Chilton"
        assert match["year"] == 1965
        assert match["page_count"] == 412
        assert match["language"] == "en"
        assert match["isbn13"] == "9780441013593"
        assert match["google_books_id"] == "abc123"

    def test_no_results_is_an_empty_list_not_a_404(
        self, client, admin, google_enabled
    ):
        # Nothing is wrong with a search that matches nothing, and the client
        # renders "no results" rather than an error.
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(return_value=httpx.Response(200, json={}))

            res = client.get(
                "/api/books/google/search", params={"q": "zzzz"}, headers=admin["headers"]
            )

        assert res.status_code == 200
        assert res.json() == []

    def test_writes_nothing(self, client, admin, google_enabled, google_search):
        """Search is a lookup. A book appears only when someone confirms one."""
        before = client.get("/api/books", headers=admin["headers"]).json()["total"]

        client.get("/api/books/google/search", params={"q": "dune"}, headers=admin["headers"])

        after = client.get("/api/books", headers=admin["headers"]).json()["total"]
        assert after == before

    def test_suggests_tags_from_the_categories(self, client, admin, google_enabled):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(categories=["Fiction", "Fantasy"])]}
                )
            )

            [match] = client.get(
                "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
            ).json()

        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        names = {tag["id"]: tag["name"] for tag in tags}
        assert {names[tag_id] for tag_id in match["suggested_tag_ids"]} >= {"Fiction", "Fantasy"}

    def test_a_category_containing_a_comma_survives(self, client, admin, google_enabled):
        """The separator is a semicolon precisely because of names like this.

        Google really does return "Fiction, general". Joining on a comma would
        make it impossible to split the list back apart.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(categories=["Fiction, general", "Fantasy"])]}
                )
            )

            [match] = client.get(
                "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
            ).json()

        assert match["categories"] == "Fiction, general; Fantasy"

    def test_honours_the_limit(self, client, admin, google_enabled):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(volume_id=str(n)) for n in range(10)]}
                )
            )

            res = client.get(
                "/api/books/google/search",
                params={"q": "dune", "limit": 3},
                headers=admin["headers"],
            )

        assert len(res.json()) == 3


class TestSearchValidation:
    @pytest.mark.parametrize("query", ["", "a"])
    def test_a_query_that_is_too_short_is_rejected(
        self, client, admin, google_enabled, query
    ):
        # Guarded before the upstream call: a one-character search would spend
        # a request on a result nobody wants.
        res = client.get(
            "/api/books/google/search", params={"q": query}, headers=admin["headers"]
        )

        assert res.status_code == 422

    def test_a_missing_query_is_rejected(self, client, admin, google_enabled):
        assert (
            client.get("/api/books/google/search", headers=admin["headers"]).status_code == 422
        )

    @pytest.mark.parametrize("limit", [0, 21])
    def test_a_limit_outside_the_range_is_rejected(
        self, client, admin, google_enabled, limit
    ):
        res = client.get(
            "/api/books/google/search",
            params={"q": "dune", "limit": limit},
            headers=admin["headers"],
        )

        assert res.status_code == 422


class TestUpstreamFailures:
    def test_a_rejected_key_becomes_a_502_naming_the_cause(
        self, client, admin, google_enabled
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(return_value=httpx.Response(403))

            res = client.get(
                "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
            )

        assert res.status_code == 502
        assert "API key" in res.json()["detail"]

    def test_rate_limiting_is_reported_as_such(self, client, admin, google_enabled):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(return_value=httpx.Response(429))

            res = client.get(
                "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
            )

        assert res.status_code == 502
        assert "rate limiting" in res.json()["detail"]

    def test_an_upstream_outage_does_not_surface_as_a_500(
        self, client, admin, google_enabled
    ):
        # 502, not 500: the fault is Google's, and a 500 would send whoever is
        # on call looking at the wrong service.
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(return_value=httpx.Response(503))

            res = client.get(
                "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
            )

        assert res.status_code == 502


class TestEnrichBook:
    def test_fills_the_gaps(self, client, admin, make_book, google_enabled, google_search):
        book = make_book(admin["headers"])

        res = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        assert res.status_code == 200
        assert res.json()["found"] is True
        assert res.json()["book"]["page_count"] == 412

    def test_reports_which_fields_changed(
        self, client, admin, make_book, google_enabled, google_search
    ):
        """A run that finds the volume but adds nothing is the common case."""
        book = make_book(admin["headers"])

        first = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"]).json()
        second = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"]).json()

        assert "page_count" in first["updated_fields"]
        assert second["found"] is True
        assert second["updated_fields"] == []

    def test_does_not_overrule_a_typed_value(
        self, client, admin, make_book, google_enabled, google_search
    ):
        # Somebody corrected the publisher by hand. Upstream does not win.
        book = make_book(admin["headers"], publisher="Ace Books")

        res = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        assert res.json()["book"]["publisher"] == "Ace Books"

    def test_another_members_private_book_is_not_enrichable(
        self, client, admin, member, make_book, google_enabled, google_search
    ):
        book = make_book(admin["headers"], is_private=True)

        res = client.post(f"/api/books/{book['id']}/enrich", headers=member["headers"])

        assert res.status_code == 404

    def test_requires_authentication(self, client, admin, make_book, google_enabled):
        book = make_book(admin["headers"])
        assert client.post(f"/api/books/{book['id']}/enrich").status_code == 401


class TestEnrichmentCandidates:
    def test_offers_other_editions(
        self, client, admin, make_book, google_enabled, google_search
    ):
        book = make_book(admin["headers"])

        res = client.get(
            f"/api/books/{book['id']}/enrich/candidates", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert res.json()[0]["title"] == "Dune"

    def test_does_not_suggest_tags(
        self, client, admin, make_book, google_enabled, google_search
    ):
        """The book already has tags, and they are somebody's deliberate choice."""
        book = make_book(admin["headers"])

        res = client.get(
            f"/api/books/{book['id']}/enrich/candidates", headers=admin["headers"]
        )

        assert res.json()[0]["suggested_tag_ids"] == []

    def test_another_members_private_book_is_invisible(
        self, client, admin, member, make_book, google_enabled, google_search
    ):
        book = make_book(admin["headers"], is_private=True)

        res = client.get(
            f"/api/books/{book['id']}/enrich/candidates", headers=member["headers"]
        )

        assert res.status_code == 404


class TestCategoriesSerialisation:
    """`categories` is one string in the database and a list on the wire."""

    def test_served_as_a_list(self, client, admin, make_book, google_enabled):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(categories=["Fiction", "Fantasy"])]}
                )
            )
            book = make_book(admin["headers"])
            client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])

        assert res.json()["categories"] == ["Fiction", "Fantasy"]

    def test_a_comma_inside_a_category_is_not_split(
        self, client, admin, make_book, google_enabled
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(categories=["Fiction, general"])]}
                )
            )
            book = make_book(admin["headers"])
            client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])

        assert res.json()["categories"] == ["Fiction, general"]

    def test_a_book_with_no_categories_gets_an_empty_list(self, client, admin, make_book):
        # Not null: a client that has to handle both an absent list and an
        # empty one will eventually handle one of them wrong.
        book = make_book(admin["headers"])

        assert client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()[
            "categories"
        ] == []


class TestKeyHandling:
    def test_the_stored_key_is_sent_to_google(self, client, admin, google_enabled):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )

            client.get(
                "/api/books/google/search", params={"q": "dune"}, headers=admin["headers"]
            )

        assert route.calls.last.request.url.params["key"] == "test-key"

    def test_the_key_is_stored_unmasked(self, client, admin, google_enabled, db):
        """The masking in SettingsOut is presentation, not storage.

        Worth pinning: masking the stored value instead of the response would
        break every lookup while still looking right in the settings screen.
        """
        import settings_store

        assert (
            settings_store.get_raw(db, SettingKey.GOOGLE_BOOKS_API_KEY) == "test-key"
        )
