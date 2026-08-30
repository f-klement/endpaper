"""Tests for `GET /api/books/search` on backend/routers/books.py.

Free-text search is how a book with no barcode, a damaged one, or one printed
before ISBNs existed gets into the catalogue. It used to be Google Books only,
which meant a library that had not configured an API key was shown no search
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

from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from tests.helpers import (
    BNF,
    DNB,
    GOOGLE_BOOKS,
    K10PLUS,
    LOC,
    OENB,
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
         subtitle: str = "", extra: str = "", year: str = "2024") -> str:
    """One MARCXML record, as K10plus and the DNB both return it."""
    part_b = f'<subfield code="b">{subtitle}</subfield>' if subtitle else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
        "<zs:records><zs:record><zs:recordData>"
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f'<datafield tag="020"><subfield code="a">{isbn}</subfield></datafield>'
        f'<datafield tag="245"><subfield code="a">{title}</subfield>'
        f"{part_b}</datafield>"
        f'<datafield tag="100"><subfield code="a">{author}</subfield>'
        '<subfield code="4">aut</subfield></datafield>'
        '<datafield tag="264"><subfield code="b">Fischer</subfield>'
        f'<subfield code="c">{year}</subfield></datafield>'
        f'<datafield tag="300"><subfield code="a">{extent}</subfield></datafield>'
        '<datafield tag="041"><subfield code="a">ger</subfield></datafield>'
        f"{extra}"
        "</record></zs:recordData></zs:record></zs:records>"
        "</zs:searchRetrieveResponse>"
    )


def oenb_record(title: str = "&lt;&lt;Das&gt;&gt; angehaltene Leben") -> str:
    """One ÖNB MARCXML record, in that catalogue's own envelope and conventions.

    Two things here are the ÖNB's rather than MARC's in general: the SRU
    namespace is the default rather than prefixed `zs:`, and the non-sorting
    delimiters around a leading article are `<<` and `>>` where every other
    source uses U+0098 and U+009C. The default title carries a bracketed run so
    that the route level assertion sees the stripped form.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
        "<numberOfRecords>1</numberOfRecords><records><record><recordData>"
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        "<leader>01533nam a2200505 c 4500</leader>"
        '<datafield tag="020"><subfield code="a">9783552058217</subfield></datafield>'
        f'<datafield tag="245"><subfield code="a">{title}</subfield></datafield>'
        '<datafield tag="100"><subfield code="a">Torchio, Maurizio</subfield>'
        '<subfield code="4">aut</subfield></datafield>'
        '<datafield tag="264"><subfield code="b">Zsolnay</subfield>'
        '<subfield code="c">2017</subfield></datafield>'
        '<datafield tag="300"><subfield code="a">237 Seiten</subfield></datafield>'
        '<datafield tag="041"><subfield code="a">ger</subfield></datafield>'
        "</record></recordData></record></records></searchRetrieveResponse>"
    )


def dnb_marc(title: str = "Der Zauberberg", *, subtitle: str = "Roman",
             creator: str = "Mann, Thomas", extent: str = "992 Seiten") -> str:
    """One MARC21 record, as the DNB returns it since 2026-08-24.

    The same schema K10plus answers in, which is why this builds on `marc()`
    rather than beside it: what differs between the two sources is which fields
    they fill in, and the search assertions here are about the fields both do.
    """
    return marc(title, author=creator, extent=extent, subtitle=subtitle)


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
    """Search reaches the non-English catalogues, not just the English two.

    **Five of the seven, and the name overstates it.** Open Library and Google
    Books are covered by their own files; the five checked here are K10plus, the
    DNB, the BnF, the Library of Congress and the ÖNB, which are the ones a
    reader would doubt answer at all. The docstring said "all six sources" while
    covering four, so the count moved when a seventh was added and the gap did
    not: it is written out here rather than carried as a number.
    """

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
        [match] = self._search(client, admin["headers"], **{DNB: dnb_marc()})
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

    def test_the_oenb_contributes_for_austrian(self, client, admin):
        """The ÖNB reaches the picker through the route, not just the adapter.

        Everything else about this source is tested at `metadata.py`'s seam.
        This is the one check that it survives the whole request: the fan out,
        the merge, the ranking and the response schema.
        """
        [match] = self._search(
            client,
            admin["headers"],
            "angehaltene leben",
            **{OENB: oenb_record()},
        )
        assert match["title"] == "Das angehaltene Leben"
        assert match["source"] == "oenb"

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
            client, admin["headers"], **{K10PLUS: marc(), DNB: dnb_marc()}
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

    def test_a_digitised_copy_is_not_offered_by_the_dnb_either(self, client, admin):
        """The lookup ranks an online record down and takes it when nothing
        better answers; a search has no ISBN to tell an edition of this book
        from a digitisation of another one, so it refuses. Nothing pinned the
        DNB half of that before."""
        assert (
            self._search(
                client,
                admin["headers"],
                **{DNB: dnb_marc(extent="Online-Ressource, 992 Seiten")},
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

    The lookup path answers the same problem the same way, in `classifications.bounded_headings`.

    **The classifications no longer reach that guard at all.** They go through
    `classifications.bounded_headings` first, like the lookup path, so an unusable heading costs its
    own row and a ninth heading costs the ninth heading. Everything else in the
    record still costs the whole result, `year` being the reachable one: MARC
    writes 9999 for a continuing resource and `MAX_YEAR` is 2200.

    **`page_count` used to be reachable here too and no longer is.**
    `_pages_from_extent` was bounded on 2026-08-27, to close a `ValueError`
    that 500d the whole request, and range checking it against
    `MAX_PAGE_NUMBER_IN_A_BOOK` was part of that fix. An out of range extent
    now costs the page count rather than the row, so a test that wants a record
    the model refuses has to poison the year.
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

    def _two_records(
        self,
        first_extra: str,
        second_title: str,
        first_extent: str = "992 Seiten",
        first_year: str = "2024",
    ) -> str:
        """One K10plus response holding two books, the first one poisoned.

        Two records from one source rather than two sources, because the
        fixtures in this file describe the same book on purpose and
        `_merge_matches` would fold them into a single row carrying the bad
        field, which is not the case under test.
        """
        head, _, tail = marc(
            extra=first_extra, extent=first_extent, year=first_year
        ).partition("<zs:records>")
        second = marc(title=second_title, isbn="9783596294343")
        _, _, body = second.partition("<zs:records>")
        return head + "<zs:records>" + tail.replace(
            "</zs:records></zs:searchRetrieveResponse>", ""
        ) + body

    def test_a_caption_the_column_could_not_hold_costs_the_heading_not_the_row(
        self, client, admin
    ):
        """400 characters against a 200 character column.

        It used to drop the whole result, because the headings went straight
        into `BookMatch`. They go through `classifications.bounded_headings` now, which is what the
        lookup path always did with the same record.
        """
        res = self._search(
            client,
            admin["headers"],
            **{K10PLUS: marc(extra=self._ddc("004", " " + "x" * 400))},
        )

        assert res.status_code == 200
        assert [match["classifications"] for match in res.json()] == [[]]

    def test_a_record_with_more_headings_than_the_ceiling_keeps_its_row(
        self, client, admin
    ):
        """The bound is a bound, not a cliff.

        Three things used to meet: a record was deduplicated and not sliced,
        `BookMatch` refuses a ninth entry, and the handler in `search_books`
        drops the whole row on a `ValidationError`. So before this fix a well
        catalogued record vanished from the search page. Measured over four live
        DNB `WOE=` searches on
        2026-08-24: 8 of 189 records carry more than eight headings, and the
        worst query lost 6 of its 50 results.
        """
        nine = "".join(self._ddc(f"{100 + index}") for index in range(9))
        [match] = self._search(
            client, admin["headers"], **{K10PLUS: marc(extra=nine)}
        ).json()

        assert match["title"] == "Der Zauberberg"
        assert len(match["classifications"]) == 8

    def test_the_dewey_number_is_the_one_kept_at_the_ceiling(self, client, admin):
        """The entry a tag suggestion is projected from survives the cut, even
        though the record writes its subject headings first.

        This pins the parser's own ordering end to end and **not** the sort in
        `classifications.bounded_headings`, which cannot show here: a search result comes from one
        record, so the Dewey number is already at index 0 by the time it
        arrives. The sort is what makes this true of a merged book, and
        `tests/routers/test_books_classifications.py::TestTheLookup::
        test_a_second_catalogues_dewey_number_survives_the_ceiling` is the test
        that fails without it.
        """
        headings = "".join(
            f'<datafield tag="650"><subfield code="0">(DE-588)400000{index}-1'
            f'</subfield><subfield code="a">Thema {index}</subfield></datafield>'
            for index in range(9)
        )
        [match] = self._search(
            client,
            admin["headers"],
            **{DNB: marc(extra=headings + self._ddc("830"))},
        ).json()

        assert match["classifications"][0] == {
            "scheme": "ddc",
            "number": "830",
            "label": None,
        }
        assert len(match["classifications"]) == 8

    def test_the_rest_of_the_page_survives_a_bad_record(self, client, admin):
        """The point of dropping rather than raising: one bad record must not
        take the other results on the page with it. Before the guard this
        answered 500 and lost both.

        **On the year, and it moved there on 2026-08-27.** It used to poison the
        record with `999999 Seiten`, because an out of range page count reached
        `BookMatch` and failed its bound. `_pages_from_extent` now range checks
        what it parses, so that extent costs the page count and nothing else,
        and the record is no longer bad at all. The year is the reachable bound
        this class's docstring already named: MARC writes 9999 for a continuing
        resource and `MAX_YEAR` is 2200.
        """
        res = self._search(
            client,
            admin["headers"],
            **{
                K10PLUS: self._two_records(
                    "",
                    "Der Zauberberg Kommentar",
                    first_year="9999",
                )
            },
        )

        assert res.status_code == 200
        assert [match["title"] for match in res.json()] == [
            "Der Zauberberg Kommentar"
        ]

    def test_a_record_repeating_one_number_yields_one_heading(self, client, admin):
        """Live K10plus returns 082 `$a` values of `['100', '610', '610']` on a
        single record. `catalogue.Record` folds them at construction, which is
        the same rule on both paths; without it the repetition spends the
        payload's budget of eight twice on nothing."""
        [match] = self._search(
            client,
            admin["headers"],
            **{K10PLUS: marc(extra=self._ddc("610") + self._ddc("610"))},
        ).json()

        assert match["classifications"] == [
            {"scheme": "ddc", "number": "610", "label": None}
        ]


class TestSubjectHeadingsOnASearchRow:
    """LCSH, out of the Library of Congress record this path already fetches.

    The search path is the only one that reaches it: the Library of Congress is
    not in `_SOURCES`, so a scan never asks it. A picked row carries the
    headings into `POST /{id}/enrich/apply` like any other, which is how they
    reach a book.
    """

    #: A live shaped MODS record: the two `<classification>` elements the
    #: parser already read, plus the `<subject authority="lcsh">` siblings that
    #: sit beside them, plus one French `rvm` heading the record also carries.
    def _mods(self, subjects: str) -> str:
        return mods_record().replace(
            "</mods>",
            '<classification authority="lcc">QA76.73.P98 V53 2021</classification>'
            '<classification authority="ddc" edition="23">005.133</classification>'
            f"{subjects}"
            '<subject authority="rvm"><topic>Genie logiciel</topic></subject>'
            "</mods>",
        )

    def _search(self, client, headers, subjects: str) -> dict:
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOC).mock(
                return_value=sru_response(self._mods(subjects))
            )
            silence_catalogues(mock)
            [match] = client.get(
                "/api/books/search",
                params={"q": "sombra viento zafon"},
                headers=headers,
            ).json()
        return match

    def test_a_subject_heading_reaches_a_search_row(self, client, admin):
        match = self._search(
            client,
            admin["headers"],
            '<subject authority="lcsh"><topic>Computer software</topic>'
            "<topic>Development</topic></subject>",
        )

        assert {
            "scheme": "lcsh",
            "number": "Computer software -- Development",
            "label": None,
        } in match["classifications"]

    def test_a_heading_longer_than_any_call_number_survives_whole(
        self, client, admin
    ):
        """89 characters, against a column that held 40 before this scheme
        existed. 399 of 1,559 headings measured live on 2026-08-24 are over
        that bound, 25.6%, and truncating one merges two headings that name
        different sets of books."""
        heading = (
            "United States -- History -- Civil War, 1861-1865 -- "
            "Social aspects -- Juvenile literature"
        )
        match = self._search(
            client,
            admin["headers"],
            '<subject authority="lcsh"><topic>United States</topic>'
            "<topic>History</topic><topic>Civil War, 1861-1865</topic>"
            "<topic>Social aspects</topic>"
            "<topic>Juvenile literature</topic></subject>",
        )
        numbers = [entry["number"] for entry in match["classifications"]]

        assert heading in numbers
        assert len(heading) == 89

    def test_the_shelf_classifications_lead_a_row_crowded_with_headings(
        self, client, admin
    ):
        """A record carrying more subject headings than the whole book budget.

        Measured live: one record carries 14 against at most two
        classifications. `Record.match_headings` slices before `classifications.SCHEME_ORDER`
        is applied, so the parser emitting the `<classification>` elements first
        is what keeps the Dewey number and the call number on the row, and
        `classifications.bounded_headings` then puts the Dewey number in front.
        """
        match = self._search(
            client,
            admin["headers"],
            "".join(
                f'<subject authority="lcsh"><topic>Thema {index}</topic></subject>'
                for index in range(14)
            ),
        )
        schemes = [entry["scheme"] for entry in match["classifications"]]

        assert len(schemes) == MAX_CLASSIFICATIONS_PER_BOOK
        assert schemes[:2] == ["ddc", "lcc"]
        assert schemes[2:] == ["lcsh"] * 6
