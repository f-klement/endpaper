"""Tests for `GET /api/books/search` on backend/routers/books.py.

Free-text search is how a book with no barcode, a damaged one, or one printed
before ISBNs existed gets into the catalogue. It used to be Google Books only,
which meant a household that had not configured an API key was shown no search
box at all and had no way to add such a book except by typing every field.

So the case worth pinning hardest is the one that used to be impossible: a
search with **no key configured** returns results. The rest is what merging two
sources has to get right, which is one row per book rather than two, and one
edition per row rather than all of them collapsed into one.

Every outbound call is intercepted with respx.
"""

import httpx
import pytest
import respx

from tests.helpers import (
    BNF,
    DNB,
    GOOGLE_BOOKS,
    K10PLUS,
    LOC,
    OPEN_LIBRARY_SEARCH,
    silence_catalogues,
    sru_response,
)


def ol_doc(
    title: str = "Moby Dick",
    *,
    author: str = "Herman Melville",
    year: int | None = 1851,
    isbn: list[str] | None = None,
    pages: int | None = 452,
    cover: int | None = 10544254,
) -> dict:
    """One row as Open Library's search index returns it."""
    doc: dict = {
        "title": title,
        "author_name": [author],
        "first_publish_year": year,
        "number_of_pages_median": pages,
        "language": ["eng"],
        "publisher": ["Harper"],
    }
    if isbn is not None:
        doc["isbn"] = isbn
    if cover is not None:
        doc["cover_i"] = cover
    return doc


def volume(title: str = "Moby Dick", *, categories: list[str] | None = None) -> dict:
    """One item as Google returns it."""
    info: dict = {
        "title": title,
        "authors": ["Herman Melville"],
        "description": "A whale.",
        "publishedDate": "1851",
    }
    if categories is not None:
        info["categories"] = categories
    return {"id": "abc123", "volumeInfo": info}


@pytest.fixture
def open_library_search():
    """Open Library answers with one row; every other catalogue holds nothing."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
            return_value=httpx.Response(200, json={"docs": [ol_doc()]})
        )
        yield silence_catalogues(mock)


@pytest.fixture
def google_enabled(client, admin):
    client.put(
        "/api/settings",
        json={"google_books_enabled": True, "google_books_api_key": "test-key"},
        headers=admin["headers"],
    )


class TestNoKeyRequired:
    """The regression this endpoint exists for."""

    def test_search_works_with_no_api_key_configured(
        self, client, member, open_library_search
    ):
        res = client.get(
            "/api/books/search", params={"q": "moby dick"}, headers=member["headers"]
        )

        assert res.status_code == 200
        assert res.json()[0]["title"] == "Moby Dick"

    def test_google_is_not_called_when_it_is_switched_off(
        self, client, admin, open_library_search
    ):
        google = open_library_search.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        client.get(
            "/api/books/search", params={"q": "moby dick"}, headers=admin["headers"]
        )

        assert not google.called

    def test_requires_authentication(self, client):
        assert client.get("/api/books/search", params={"q": "dune"}).status_code == 401

    def test_a_member_may_search(self, client, member, open_library_search):
        """Configuring Google is admin-only; searching is not."""
        res = client.get(
            "/api/books/search", params={"q": "moby"}, headers=member["headers"]
        )
        assert res.status_code == 200


class TestResults:
    def test_maps_the_open_library_fields(self, client, admin, open_library_search):
        [match] = client.get(
            "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
        ).json()

        assert match["title"] == "Moby Dick"
        assert match["author"] == "Herman Melville"
        assert match["year"] == 1851
        assert match["page_count"] == 452
        assert match["publisher"] == "Harper"
        assert match["language"] == "en"
        assert match["source"] == "open_library"
        assert match["cover_url"].endswith("/b/id/10544254-M.jpg")

    def test_a_book_printed_before_isbns_still_resolves(
        self, client, admin
    ):
        """The case that has no barcode to scan, and never had one."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(
                    200,
                    json={"docs": [ol_doc(year=1851, isbn=None, cover=None)]},
                )
            )
            silence_catalogues(mock)
            silence_catalogues(mock)
            [match] = client.get(
                "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
            ).json()

        assert match["title"] == "Moby Dick"
        assert match["isbn13"] is None

    def test_skips_an_isbn_that_is_not_one(self, client, admin):
        """Open Library lists every identifier it has merged, valid or not."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(
                    200,
                    json={"docs": [ol_doc(isbn=["not-an-isbn", "0585382948"])]},
                )
            )
            silence_catalogues(mock)
            [match] = client.get(
                "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
            ).json()

        assert match["isbn13"] == "9780585382944"

    def test_no_results_is_an_empty_list_not_a_404(self, client, admin):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            silence_catalogues(mock)
            res = client.get(
                "/api/books/search", params={"q": "zzzz"}, headers=admin["headers"]
            )

        assert res.status_code == 200
        assert res.json() == []

    def test_writes_nothing(self, client, admin, open_library_search):
        """Search is a lookup. A book appears only when someone confirms one."""
        before = client.get("/api/books", headers=admin["headers"]).json()["total"]

        client.get("/api/books/search", params={"q": "moby"}, headers=admin["headers"])

        after = client.get("/api/books", headers=admin["headers"]).json()["total"]
        assert after == before

    def test_honours_the_limit(self, client, admin):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(
                    200,
                    json={"docs": [ol_doc(title=f"Moby {n}") for n in range(10)]},
                )
            )
            silence_catalogues(mock)
            res = client.get(
                "/api/books/search",
                params={"q": "moby", "limit": 3},
                headers=admin["headers"],
            )

        assert len(res.json()) == 3

    def test_an_open_library_outage_is_an_empty_list_not_a_500(self, client, admin):
        """A search that cannot answer is not a crash."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                side_effect=httpx.ConnectError("no route")
            )
            silence_catalogues(mock)
            res = client.get(
                "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
            )

        assert res.status_code == 200
        assert res.json() == []


class TestMergingTheTwoSources:
    def test_one_book_from_both_sources_is_one_row(
        self, client, admin, google_enabled
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(200, json={"docs": [ol_doc()]})
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": [volume()]})
            )
            silence_catalogues(mock)
            matches = client.get(
                "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
            ).json()

        assert len(matches) == 1
        # Open Library has the cover and the page count, Google the blurb.
        # Both survive, which is the reason to merge rather than concatenate.
        assert matches[0]["page_count"] == 452
        assert matches[0]["description"] == "A whale."

    def test_a_book_only_google_knows_is_added_not_dropped(
        self, client, admin, google_enabled
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(200, json={"docs": [ol_doc()]})
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(title="Billy Budd")]}
                )
            )
            silence_catalogues(mock)
            titles = [
                match["title"]
                for match in client.get(
                    "/api/books/search", params={"q": "melville"}, headers=admin["headers"]
                ).json()
            ]

        assert titles == ["Moby Dick", "Billy Budd"]

    def test_two_editions_from_one_source_stay_two_rows(self, client, admin):
        """Deduplication is across sources only.

        Two printings of one book share a title and an author, and choosing
        between them is the entire point of the picker. Collapsing them showed
        two rows where Open Library had returned five.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            ol_doc(year=1851, pages=452),
                            ol_doc(year=2016, pages=784),
                        ]
                    },
                )
            )
            silence_catalogues(mock)
            matches = client.get(
                "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
            ).json()

        # Both survive. The order between them is the ranker's, not the
        # catalogue's, and a tie on relevance goes to the newer printing.
        assert sorted(match["year"] for match in matches) == [1851, 2016]

    def test_a_google_outage_leaves_the_open_library_results(
        self, client, admin, google_enabled
    ):
        """Losing the optional half is not a reason to refuse the search."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(200, json={"docs": [ol_doc()]})
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(429)
            )
            silence_catalogues(mock)
            matches = client.get(
                "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
            ).json()

        assert [match["title"] for match in matches] == ["Moby Dick"]

    def test_suggests_tags_from_the_google_categories(
        self, client, admin, google_enabled
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200,
                    json={"items": [volume(categories=["Fiction", "Adventure"])]},
                )
            )
            silence_catalogues(mock)
            [match] = client.get(
                "/api/books/search", params={"q": "moby"}, headers=admin["headers"]
            ).json()

        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        names = {tag["id"]: tag["name"] for tag in tags}
        assert {names[tag_id] for tag_id in match["suggested_tag_ids"]} >= {
            "Fiction",
            "Adventure",
        }


class TestValidation:
    @pytest.mark.parametrize("query", ["", "a"])
    def test_a_query_that_is_too_short_is_rejected(self, client, admin, query):
        # Guarded before the upstream call: a one-character search would spend
        # a request on a result nobody wants.
        res = client.get(
            "/api/books/search", params={"q": query}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_a_missing_query_is_rejected(self, client, admin):
        assert client.get("/api/books/search", headers=admin["headers"]).status_code == 422

    @pytest.mark.parametrize("limit", [0, 21])
    def test_a_limit_outside_the_range_is_rejected(self, client, admin, limit):
        res = client.get(
            "/api/books/search",
            params={"q": "moby", "limit": limit},
            headers=admin["headers"],
        )
        assert res.status_code == 422


# ── Fixtures for the other four catalogues ────────────────────────────────────


def marc(title: str = "Der Zauberberg", *, author: str = "Mann, Thomas",
         extent: str = "992 Seiten", isbn: str = "9783596294336",
         extra: str = "") -> str:
    """One MARCXML record, as K10plus returns it."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
        "<zs:records><zs:record><zs:recordData>"
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f'<datafield tag="020"><subfield code="a">{isbn}</subfield></datafield>'
        f'<datafield tag="245"><subfield code="a">{title}</subfield></datafield>'
        f'<datafield tag="100"><subfield code="a">{author}</subfield>'
        '<subfield code="4">aut</subfield></datafield>'
        '<datafield tag="264"><subfield code="b">Fischer</subfield>'
        '<subfield code="c">2024</subfield></datafield>'
        f'<datafield tag="300"><subfield code="a">{extent}</subfield></datafield>'
        '<datafield tag="041"><subfield code="a">ger</subfield></datafield>'
        f"{extra}"
        "</record></zs:recordData></zs:record></zs:records>"
        "</zs:searchRetrieveResponse>"
    )


def dublin_core(title: str = "Der Zauberberg : Roman / Thomas Mann",
                *, creator: str = "Mann, Thomas [Verfasser]",
                extent: str = "992 Seiten") -> str:
    """One Dublin Core record, as the DNB returns it."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
        "<records><record><recordData>"
        '<dc xmlns="http://www.openarchives.org/OAI/2.0/oai_dc/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{title}</dc:title>"
        f"<dc:creator>{creator}</dc:creator>"
        "<dc:publisher>Frankfurt : Fischer</dc:publisher>"
        "<dc:date>2024</dc:date><dc:language>ger</dc:language>"
        f"<dc:format>{extent}</dc:format>"
        "</dc></recordData></record></records></searchRetrieveResponse>"
    )


def bnf_record(title: str = "L'etranger / Albert Camus",
               creator: str = "Camus, Albert (1913-1960). Auteur du texte") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">'
        "<srw:records><srw:record><srw:recordData>"
        '<dc xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{title}</dc:title><dc:creator>{creator}</dc:creator>"
        "<dc:type>texte imprimé</dc:type><dc:date>1942</dc:date>"
        "<dc:language>fre</dc:language><dc:format>159 p. ; 19 cm</dc:format>"
        "<dc:publisher>Gallimard (Paris)</dc:publisher>"
        "</dc></srw:recordData></srw:record></srw:records>"
        "</srw:searchRetrieveResponse>"
    )


def mods_record(title: str = "sombra del viento", non_sort: str = "La ",
                kind: str = "text") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
        "<zs:records><zs:record><zs:recordData>"
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<titleInfo><nonSort>{non_sort}</nonSort><title>{title}</title></titleInfo>"
        f"<typeOfResource>{kind}</typeOfResource>"
        "<name><namePart>Ruiz Zafón, Carlos, 1964-2020</namePart>"
        "<role><roleTerm>author</roleTerm></role></name>"
        "<originInfo><publisher>Planeta</publisher>"
        "<dateIssued>2001</dateIssued></originInfo>"
        "<physicalDescription><extent>576 p. ; 23 cm</extent></physicalDescription>"
        "<language><languageTerm>spa</languageTerm></language>"
        "</mods></zs:recordData></zs:record></zs:records>"
        "</zs:searchRetrieveResponse>"
    )


class TestEveryCatalogueAnswers:
    """Search reaches all six sources, not just the English-language two."""

    def _search(self, client, headers, query="zauberberg mann", **routes):
        with respx.mock(assert_all_called=False) as mock:
            for base, body in routes.items():
                mock.get(url__startswith=base).mock(return_value=sru_response(body))
            silence_catalogues(mock)
            return client.get(
                "/api/books/search", params={"q": query}, headers=headers
            ).json()

    def test_k10plus_contributes(self, client, admin):
        [match] = self._search(client, admin["headers"], **{K10PLUS: marc()})
        assert match["title"] == "Der Zauberberg"
        assert match["author"] == "Thomas Mann"
        assert match["source"] == "k10plus"
        assert match["page_count"] == 992

    def test_the_dnb_contributes(self, client, admin):
        [match] = self._search(client, admin["headers"], **{DNB: dublin_core()})
        assert match["title"] == "Der Zauberberg"
        assert match["subtitle"] == "Roman"
        assert match["source"] == "dnb"

    def test_the_bnf_contributes_for_french(self, client, admin):
        [match] = self._search(
            client, admin["headers"], "etranger camus", **{BNF: bnf_record()}
        )
        assert match["title"] == "L'etranger"
        # The life dates and the role are not part of the name.
        assert match["author"] == "Albert Camus"
        assert match["source"] == "bnf"

    def test_the_library_of_congress_contributes_for_spanish(self, client, admin):
        [match] = self._search(
            client, admin["headers"], "sombra viento zafon", **{LOC: mods_record()}
        )
        # `nonSort` holds the article, and dropping it loses the "La".
        assert match["title"] == "La sombra del viento"
        assert match["author"] == "Carlos Ruiz Zafón"
        assert match["source"] == "loc"

    def test_two_catalogues_holding_one_book_produce_one_row(self, client, admin):
        matches = self._search(
            client, admin["headers"], **{K10PLUS: marc(), DNB: dublin_core()}
        )
        assert len(matches) == 1
        assert set(matches[0]["source"].split("+")) == {"dnb", "k10plus"}

    def test_a_digitised_copy_is_not_offered(self, client, admin):
        """A scanned copy of a novel is a real record and a wrong answer to
        "which book am I holding"."""
        assert (
            self._search(
                client,
                admin["headers"],
                **{K10PLUS: marc(extent="1 Online-Ressource (992 Seiten)")},
            )
            == []
        )

    def test_a_sound_recording_is_not_offered(self, client, admin):
        assert (
            self._search(
                client,
                admin["headers"],
                "sombra viento zafon",
                **{LOC: mods_record(kind="sound recording-nonmusical")},
            )
            == []
        )

    def test_a_regional_row_ranks_below_an_equal_primary_one(self, client, admin):
        """They are here for the books nobody else holds, not to reorder."""
        matches = self._search(
            client,
            admin["headers"],
            "sombra viento zafon",
            **{
                K10PLUS: marc(title="La sombra del viento", author="Ruiz Zafón, Carlos"),
                LOC: mods_record(),
            },
        )
        assert matches[0]["source"] == "k10plus"


class TestLanguagePreference:
    def test_prefers_an_edition_in_the_readers_language(self, client, admin):
        """A tiebreaker, not an override. See the ranking tests for the rule."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY_SEARCH).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {
                                "title": "Der Schwarm",
                                "author_name": ["Frank Schätzing"],
                                "first_publish_year": 2004,
                                "language": ["eng"],
                            },
                            {
                                "title": "Der Schwarm",
                                "author_name": ["Frank Schätzing"],
                                "first_publish_year": 2004,
                                "language": ["ger"],
                            },
                        ]
                    },
                )
            )
            silence_catalogues(mock)
            matches = client.get(
                "/api/books/search",
                params={"q": "der schwarm schatzing", "lang": "de"},
                headers=admin["headers"],
            ).json()

        assert matches[0]["language"] == "de"

    def test_an_unsupported_language_is_rejected_rather_than_ignored(
        self, client, admin
    ):
        res = client.get(
            "/api/books/search",
            params={"q": "dune", "lang": "klingon"},
            headers=admin["headers"],
        )
        assert res.status_code == 422


class TestOneBadRecordCostsOneResult:
    """`BookMatch` is a bounded model built straight from third party data, and
    there is no `ValidationError` handler in the app. Before this guard a single
    record tripping any bound answered 500 and lost every other row on the page.

    The lookup path answers the same problem the same way, in `_headings`.
    """

    def _search(self, client, headers, **routes):
        with respx.mock(assert_all_called=False) as mock:
            for base, body in routes.items():
                mock.get(url__startswith=base).mock(return_value=sru_response(body))
            silence_catalogues(mock)
            return client.get(
                "/api/books/search",
                params={"q": "zauberberg mann"},
                headers=headers,
            )

    def _ddc(self, number: str, caption: str = "") -> str:
        subfields = f'<subfield code="a">{number}{caption}</subfield>'
        return f'<datafield tag="082">{subfields}</datafield>'

    def _two_records(self, first_extra: str, second_title: str) -> str:
        """One K10plus response holding two books, the first one poisoned.

        Two records from one source rather than two sources, because the
        fixtures in this file describe the same book on purpose and
        `_merge_matches` would fold them into a single row carrying the bad
        field, which is not the case under test.
        """
        head, _, tail = marc(extra=first_extra).partition("<zs:records>")
        second = marc(title=second_title, isbn="9783596294343")
        _, _, body = second.partition("<zs:records>")
        return head + "<zs:records>" + tail.replace(
            "</zs:records></zs:searchRetrieveResponse>", ""
        ) + body

    def test_a_caption_the_column_could_not_hold_drops_the_row(self, client, admin):
        """400 characters against a 200 character column. The lookup path has
        the same test; this endpoint is fed by the same records and had none."""
        res = self._search(
            client,
            admin["headers"],
            **{K10PLUS: marc(extra=self._ddc("004", " " + "x" * 400))},
        )

        assert res.status_code == 200
        assert res.json() == []

    def test_the_rest_of_the_page_survives_it(self, client, admin):
        """The point of dropping rather than raising: one bad record must not
        take the other results on the page with it. Before the guard this
        answered 500 and lost both."""
        res = self._search(
            client,
            admin["headers"],
            **{
                K10PLUS: self._two_records(
                    self._ddc("004", " " + "x" * 400),
                    "Der Zauberberg Kommentar",
                )
            },
        )

        assert res.status_code == 200
        assert [match["title"] for match in res.json()] == [
            "Der Zauberberg Kommentar"
        ]

    def test_a_record_repeating_one_number_yields_one_heading(self, client, admin):
        """Live K10plus returns 082 `$a` values of `['100', '610', '610']` on a
        single record. The lookup path deduplicates in `_merge`; the search path
        has no merge, so without `_union_classifications` in `_as_match` the
        repetition spends the payload's budget of eight twice on nothing."""
        [match] = self._search(
            client,
            admin["headers"],
            **{K10PLUS: marc(extra=self._ddc("610") + self._ddc("610"))},
        ).json()

        assert match["classifications"] == [
            {"scheme": "ddc", "number": "610", "label": None}
        ]
