"""Tests for backend/metadata.py.

Four things are worth pinning here and none of them is the happy path.

The **source order** is what makes a shelf catalogueable at all. The two
catalogues that measured fastest also measured most complete, so both are asked
together on every lookup and the broad, slow, metered ones only answer when
neither knows the book. A test that only checks "a lookup returns a book" would
pass with that reversed, and the reader would wait three seconds for a thinner
record.

The **merge** is where record quality comes from. Nothing is overwritten, only
filled in, so a page count from one catalogue and a subject heading from the
other end up on the same book.

The **identity checks** are what stop a wrong book being catalogued. Both
remaining SRU sources match an ISBN mentioned anywhere in a record, including
cross references to other editions, and both were observed returning a
different book because of it.

The **outcome** is what stops the reader being lied to. A throttled source and
a genuinely uncatalogued book both used to be "not found", which sends someone
to type in a record that was going to resolve by itself.

Every HTTP call is intercepted with respx, so nothing here reaches a real
catalogue.
"""

import asyncio
from xml.etree import ElementTree

import httpx
import pytest
import respx

import metadata
from enums import ClassificationScheme
from metadata import (
    Outcome,
    _dc_title_statement,
    _flip_catalogue_name,
    _is_placeholder_title,
    _loc_record,
    _marc_fields,
    _pages_from_extent,
    _parsed,
    _union_classifications,
    lookup,
)
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from tests.helpers import silence_covers

OPEN_LIBRARY = "https://openlibrary.org/"
GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"
DNB = "https://services.dnb.de/sru/dnb"
K10PLUS = "https://sru.k10plus.de/opac-de-627"

GERMAN_ISBN = "9783960092353"
ENGLISH_ISBN = "9780743273565"

#: One DNB MARC21 record, in the shape the live endpoint returns since the
#: switch away from Dublin Core. Copied from ISBN 9783446249974's real response
#: and re-labelled onto the book the rest of this file uses, so the subfields,
#: the repeated `$0`, the repeated `082 $a` and the non-sorting delimiters are
#: the catalogue's own and not a guess about them.
DNB_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <records><record><recordData>
  <record xmlns="http://www.loc.gov/MARC21/slim" type="Bibliographic">
   <leader>00000nam a2200000uc 4500</leader>
   <datafield tag="020" ind1=" " ind2=" ">
    <subfield code="a">9783960092353</subfield>
   </datafield>
   <datafield tag="041" ind1=" " ind2=" ">
    <subfield code="a">ger</subfield>
   </datafield>
   <datafield tag="082" ind1="7" ind2="4">
    <subfield code="a">004</subfield>
    <subfield code="a">B</subfield>
    <subfield code="2">23sdnb</subfield>
   </datafield>
   <datafield tag="100" ind1="1" ind2=" ">
    <subfield code="0">(DE-588)1042243212</subfield>
    <subfield code="0">https://d-nb.info/gnd/1042243212</subfield>
    <subfield code="0">(DE-101)1042243212</subfield>
    <subfield code="a">Kane, Sean P.</subfield>
    <subfield code="e">Verfasser</subfield>
    <subfield code="4">aut</subfield>
   </datafield>
   <datafield tag="245" ind1="1" ind2="0">
    <subfield code="a">Praxiswissen Docker</subfield>
    <subfield code="b">Grundlagen und Best Practices</subfield>
    <subfield code="c">Sean P. Kane mit Karl Matthias</subfield>
   </datafield>
   <datafield tag="264" ind1=" " ind2="1">
    <subfield code="a">Heidelberg</subfield>
    <subfield code="b">O'Reilly</subfield>
    <subfield code="c">2024</subfield>
   </datafield>
   <datafield tag="300" ind1=" " ind2=" ">
    <subfield code="a">390 Seiten</subfield>
   </datafield>
   <datafield tag="650" ind1=" " ind2="7">
    <subfield code="0">(DE-588)4026894-9</subfield>
    <subfield code="0">https://d-nb.info/gnd/4026894-9</subfield>
    <subfield code="a">Informatik</subfield>
    <subfield code="2">gnd</subfield>
   </datafield>
   <datafield tag="689" ind1="0" ind2="0">
    <subfield code="0">(DE-588)4026894-9</subfield>
    <subfield code="D">s</subfield>
    <subfield code="a">Informatik</subfield>
   </datafield>
   <datafield tag="700" ind1="1" ind2=" ">
    <subfield code="a">Matthias, Karl</subfield>
    <subfield code="4">aut</subfield>
   </datafield>
   <datafield tag="700" ind1="1" ind2=" ">
    <subfield code="a">Demmig, Thomas</subfield>
    <subfield code="4">trl</subfield>
   </datafield>
  </record>
 </recordData></record></records>
</searchRetrieveResponse>
"""

DNB_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <numberOfRecords>0</numberOfRecords><records/>
</searchRetrieveResponse>
"""

OPEN_LIBRARY_RECORD = {
    "title": "The Great Gatsby",
    "publishers": ["Scribner"],
    "publish_date": "April 10, 1925",
    "subjects": ["Literary Fiction"],
}

GOOGLE_VOLUME = {
    "items": [
        {
            "id": "gbid-1",
            "volumeInfo": {
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "publishedDate": "1965",
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9780441013593"}
                ],
            },
        }
    ]
}


def _marc(*records: str) -> str:
    """An SRU envelope around zero or more MARCXML records."""
    body = "".join(
        f"<zs:record><zs:recordData>{record}</zs:recordData></zs:record>"
        for record in records
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
        f"<zs:records>{body}</zs:records></zs:searchRetrieveResponse>"
    )


def _marc_record(
    *,
    isbn: str = "9780743273565",
    isbn_qualifier: str = "",
    title: str = '<subfield code="a">The Great Gatsby</subfield>',
    extra: str = "",
) -> str:
    qualifier = f'<subfield code="q">{isbn_qualifier}</subfield>' if isbn_qualifier else ""
    return (
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f'<datafield tag="020"><subfield code="a">{isbn}</subfield>{qualifier}</datafield>'
        f'<datafield tag="245">{title}</datafield>'
        '<datafield tag="100"><subfield code="a">Fitzgerald, F. Scott</subfield>'
        '<subfield code="4">aut</subfield></datafield>'
        '<datafield tag="264"><subfield code="b">Scribner</subfield>'
        '<subfield code="c">1925 (copyright)</subfield></datafield>'
        '<datafield tag="300"><subfield code="a">218 S.</subfield></datafield>'
        '<datafield tag="041"><subfield code="a">eng</subfield></datafield>'
        f"{extra}</record>"
    )


K10PLUS_RECORD = _marc(_marc_record())
K10PLUS_EMPTY = _marc()


def _marc_element(datafields: str) -> ElementTree.Element:
    """One MARC record element, built from the datafields a test cares about."""
    return ElementTree.fromstring(
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f"{datafields}</record>"
    )


def _xml(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/xml"})


@pytest.fixture(autouse=True)
def _clear_cache():
    """The cache is process-global, so one test's answer would serve the next."""
    metadata.clear_cache()
    yield
    metadata.clear_cache()


class TestSourceOrder:
    @pytest.mark.asyncio
    async def test_a_german_isbn_asks_the_dnb_first(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            dnb = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            open_library = mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            result = await lookup(GERMAN_ISBN)

        assert result.source == "dnb"
        assert dnb.called
        # Reaching Open Library at all would mean the order is wrong, since the
        # fast pair already answered.
        assert not open_library.called

    @pytest.mark.asyncio
    async def test_a_non_german_isbn_also_starts_with_the_fast_pair(self):
        """Open Library used to be first here, and it is the wrong first.

        Measured over ten ISBNs it answered most often and answered worst: 2.7
        of 5 fields against K10plus's 3.5, at 1.64s against 0.36s. Leading with
        it cost a second of latency to get a thinner record.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_RECORD)
            )
            open_library = mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json=OPEN_LIBRARY_RECORD)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "k10plus"
        assert not open_library.called

    @pytest.mark.asyncio
    async def test_open_library_answers_when_the_fast_pair_misses(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json=OPEN_LIBRARY_RECORD)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "open_library"

    @pytest.mark.asyncio
    async def test_the_fast_pair_is_asked_together_not_in_turn(self):
        """Both are asked even when the first would have answered.

        That is the trade this makes: one extra free request per scan, for a
        merged record and a wall clock equal to the slower of the two rather
        than the sum of the chain.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            k10plus = mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            dnb = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            await lookup(GERMAN_ISBN)

        assert dnb.called
        assert k10plus.called

    @pytest.mark.asyncio
    async def test_google_is_tried_after_open_library_misses(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json=GOOGLE_VOLUME)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "google_books"
        assert result.data is not None
        assert result.data["title"] == "Dune"

    @pytest.mark.asyncio
    async def test_the_google_request_carries_the_api_key(self):
        """The bug this module replaced: a second hand-rolled request without it.

        Every fallback lookup went to the unauthenticated endpoint, which is
        throttled per source address, so a household behind one address got a
        429 and a "book not found" for every scan.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            google = mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json=GOOGLE_VOLUME)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            await lookup(ENGLISH_ISBN, "secret-key")

        assert google.calls.last.request.url.params["key"] == "secret-key"


class TestOutcome:
    @pytest.mark.asyncio
    async def test_a_throttled_source_is_reported_as_rate_limited(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(429)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_being_throttled_outranks_a_genuine_miss(self):
        """One source having no record does not make the answer "no such book".

        With two sources reporting nothing and one throttled, the useful advice
        is to try again, not to start typing.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(429)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_every_source_answering_nothing_is_not_found(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_a_network_failure_is_unavailable_not_missing(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectError("no route")
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                side_effect=httpx.ConnectError("no route")
            )
            mock.get(url__startswith=DNB).mock(
                side_effect=httpx.ConnectError("no route")
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_string_that_is_not_an_isbn_costs_no_request(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            any_call = mock.get(url__regex=r".*").mock(
                return_value=httpx.Response(200, json={})
            )
            result = await lookup("not-an-isbn")

        assert result.outcome is Outcome.NOT_FOUND
        assert not any_call.called


class TestCache:
    @pytest.mark.asyncio
    async def test_a_repeat_lookup_reuses_the_record(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            route = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            await lookup(GERMAN_ISBN)
            await lookup(GERMAN_ISBN)

        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_the_hyphenated_form_hits_the_same_entry(self):
        """Canonicalising before the cache is what makes one book one entry."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            route = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            await lookup(GERMAN_ISBN)
            await lookup("978-3-96009-235-3")

        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_clearing_the_cache_lets_a_source_answer_again(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            route = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            await lookup(GERMAN_ISBN)
            metadata.clear_cache()
            await lookup(GERMAN_ISBN)

        assert route.call_count == 2


class TestDnbRecord:
    """The DNB record, read as MARC21 since 2026-08-24.

    Dublin Core packed a whole catalogue statement into each field and carried
    no identifier at all. What is pinned here is that the fields that worked
    under it still work, and that the identifiers it never had now arrive.
    """

    @pytest.mark.asyncio
    async def test_maps_the_record_onto_book_fields(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["title"] == "Praxiswissen Docker"
        assert result.data["subtitle"] == "Grundlagen und Best Practices"
        assert result.data["publisher"] == "O'Reilly"
        assert result.data["year"] == 2024
        assert result.data["language"] == "de"
        assert result.data["page_count"] == 390

    @pytest.mark.asyncio
    async def test_keeps_the_authors_and_drops_the_translator(self):
        """A translator credited as the author is worse than no author at all."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["author"] == "Sean P. Kane, Karl Matthias"

    @pytest.mark.asyncio
    async def test_the_subject_heading_is_the_caption_without_its_number(self):
        """A heading reaches `subjects` as words, so a tag name can match it."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["subjects"] == ["Informatik"]

    @pytest.mark.asyncio
    async def test_the_same_heading_in_650_and_689_is_one_subject(self):
        """A record restates its 650 headings in the 689 chain."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert len(result.data["classifications"]) == 2

    @pytest.mark.asyncio
    async def test_the_subject_heading_arrives_with_its_gnd_number(self):
        """The identifier is the whole reason this source reads MARC."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert {
            "scheme": ClassificationScheme.GND,
            "number": "4026894-9",
            "label": "Informatik",
        } in result.data["classifications"]

    @pytest.mark.asyncio
    async def test_the_dewey_number_comes_before_the_subject_headings(self):
        """`_headings` keeps the first eight, and the Dewey number is the one
        a tag suggestion is projected from."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["classifications"][0] == {
            "scheme": ClassificationScheme.DDC,
            "number": "004",
            "label": None,
        }

    @pytest.mark.asyncio
    async def test_the_sachgruppe_letter_does_not_hide_the_dewey_number(self):
        """082 carries `$a=004` and `$a=B` in one field, in that order.

        Reading a single `$a` per field would take whichever came second.
        """
        record = DNB_RECORD.replace(
            '<subfield code="a">004</subfield>\n    <subfield code="a">B</subfield>',
            '<subfield code="a">B</subfield>\n    <subfield code="a">004</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(record))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert [
            entry["number"]
            for entry in result.data["classifications"]
            if entry["scheme"] is ClassificationScheme.DDC
        ] == ["004"]

    @pytest.mark.asyncio
    async def test_a_free_text_heading_starting_with_three_digits_is_not_dewey(self):
        """"100 Jahre Bauhaus" is a subject heading, and `ddc.parse_heading`
        would read it as Dewey 100 with the caption "Jahre Bauhaus".

        The floor in `ddc` cannot tell the two apart, so the separation is
        structural: 082 is the only field handed to `ddc`, and a subject field
        never is. Remove that and this book is filed under Philosophy.
        """
        record = DNB_RECORD.replace(
            '<subfield code="a">Informatik</subfield>',
            '<subfield code="a">100 Jahre Bauhaus</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(record))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert [
            entry["number"]
            for entry in result.data["classifications"]
            if entry["scheme"] is ClassificationScheme.DDC
        ] == ["004"]
        assert {
            "scheme": ClassificationScheme.GND,
            "number": "4026894-9",
            "label": "100 Jahre Bauhaus",
        } in result.data["classifications"]

    @staticmethod
    def _two_records(first: str, second: str) -> str:
        """One DNB answer holding two records, which `maximumRecords=5` allows.

        No fixture held more than one before, so the ranking in `_dnb` was
        exercised by nothing.
        """
        head, _, tail = DNB_RECORD.partition("<records>")
        body = tail.replace("</records>\n</searchRetrieveResponse>\n", "")
        return (
            head
            + "<records>"
            + body.replace('<subfield code="a">390 Seiten</subfield>', first)
            + body.replace('<subfield code="a">390 Seiten</subfield>', second)
            + "</records>\n</searchRetrieveResponse>\n"
        )

    @pytest.mark.asyncio
    async def test_a_printed_edition_outranks_the_online_one(self):
        """`num=` matches the ebook record through its "also published as" note,
        and the DNB answers with it first. The extra four records are what let
        the printed edition win."""
        answer = self._two_records(
            '<subfield code="a">Online-Ressource</subfield>',
            '<subfield code="a">390 Seiten</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(answer))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["page_count"] == 390

    @pytest.mark.asyncio
    async def test_an_online_record_is_taken_rather_than_reporting_a_miss(self):
        """Dublin Core carried no `dc:format` on an online record, so every one
        of them was accepted. Refusing now would turn 21 of 74 live lookups into
        misses for records that name the scanned ISBN in their own 020."""
        answer = DNB_RECORD.replace(
            '<subfield code="a">390 Seiten</subfield>',
            '<subfield code="a">Online-Ressource</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(answer))
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is Outcome.FOUND
        assert result.data is not None
        assert result.data["title"] == "Praxiswissen Docker"

    @pytest.mark.asyncio
    async def test_a_disc_is_refused_rather_than_ranked_down(self):
        """A DVD is a different object, not this book in another form, and the
        Dublin Core parser refused it whenever `dc:format` was present."""
        answer = DNB_RECORD.replace(
            '<subfield code="a">390 Seiten</subfield>',
            '<subfield code="a">1 DVD-Video</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(answer))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_the_author_identifier_is_read_by_nothing(self):
        """`100 $0` is a person, and this app has no person to hang it on.

        Recorded rather than implied: see `docs/decisions.md`, "The author\'s
        GND is read by nothing". A row here would answer the author identity
        question `implementation_plan.md` §30g defers, and that answer is
        expensive to change once data exists.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert "1042243212" not in str(result.data)

    @pytest.mark.asyncio
    async def test_an_empty_result_set_is_a_miss_not_an_outage(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is Outcome.NOT_FOUND


class TestTitleStatement:
    """The BnF still writes a whole statement into `dc:title`, and so does a
    MARC record old enough not to have subfielded itself."""

    def test_drops_the_statement_of_responsibility(self):
        assert _dc_title_statement("Dune / Frank Herbert") == ("Dune", None)

    def test_splits_the_subtitle_off_the_colon(self):
        assert _dc_title_statement("Docker : eine Einfuehrung") == (
            "Docker",
            "eine Einfuehrung",
        )

    def test_drops_the_bracketed_original_title_of_a_translation(self):
        """The brackets hold a different book's title, in another language."""
        assert _dc_title_statement("[Docker: up and running] ; Praxiswissen Docker") == (
            "Praxiswissen Docker",
            None,
        )

    def test_keeps_a_colon_that_is_part_of_the_title(self):
        """Only " : " separates a subtitle. A bare colon is punctuation."""
        assert _dc_title_statement("Docker: up and running") == (
            "Docker: up and running",
            None,
        )

    def test_drops_a_second_work_bound_into_the_same_volume(self):
        assert _dc_title_statement("Erstes Werk ; Zweites Werk") == ("Erstes Werk", None)


class TestSearchMatches:
    """`_as_match` is the shape every search result arrives in."""

    def test_a_match_carries_no_more_headings_than_the_schema_accepts(self):
        """`BookMatch` refuses a ninth entry and `main.py` catches no
        `ValidationError`, so an unbounded match is a 500 waiting for the next
        endpoint that builds one without a guard. That is not hypothetical: it
        is what `GET /{id}/enrich/candidates` did while the search endpoint was
        being fixed.

        The routers bound it again, which is deliberate rather than an
        oversight: this is the bound that travels with the record, and theirs is
        the one that also drops an entry the column cannot hold.
        """
        record = {
            "title": "Ein Buch",
            "classifications": [
                {"scheme": ClassificationScheme.GND, "number": f"{index}", "label": "x"}
                for index in range(12)
            ],
        }

        match = metadata._as_match(record, "dnb")

        assert len(match["classifications"]) == MAX_CLASSIFICATIONS_PER_BOOK


class TestCatalogueXml:
    """Every catalogue response goes through one reader."""

    @pytest.mark.asyncio
    async def test_a_response_carrying_a_doctype_is_refused(self):
        """`xml.etree` expands internal entities, so a doctype is a body whose
        size says nothing about what it costs to parse: ten characters nested
        three deep expand to 1,000. It degrades to "unavailable", not a 500."""
        hostile = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE searchRetrieveResponse [<!ENTITY a "aaaaaaaaaa">]>'
            '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
            "<records/></searchRetrieveResponse>"
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(hostile))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is not Outcome.FOUND

    def test_an_ordinary_response_still_parses(self):
        """225 live DNB and K10plus responses carry no doctype, so the refusal
        above costs nothing."""
        assert _parsed(DNB_RECORD).tag.endswith("searchRetrieveResponse")


class TestMarcSubfields:
    """What a MARC record carries that a Dublin Core crosswalk had cleaned up."""

    def test_a_repeated_subfield_keeps_every_value(self):
        """082 holds `$a=830 $a=B`, and the letter is not a Dewey number."""
        fields = _marc_fields(_marc_element('''
          <datafield tag="082" ind1="7" ind2="4">
           <subfield code="a">830</subfield><subfield code="a">B</subfield>
          </datafield>'''))
        assert fields["082"][0].all("a") == ["830", "B"]

    def test_indexing_a_repeated_subfield_gives_the_first_value(self):
        """`$0` arrives as the GND number, then two URIs for the same thing."""
        fields = _marc_fields(_marc_element('''
          <datafield tag="100" ind1="1" ind2=" ">
           <subfield code="0">(DE-588)118181505</subfield>
           <subfield code="0">https://d-nb.info/gnd/118181505</subfield>
           <subfield code="a">Capus, Alex</subfield>
          </datafield>'''))
        assert fields["100"][0]["0"] == "(DE-588)118181505"

    def test_the_non_sorting_delimiters_are_stripped(self):
        """MARC brackets a leading article so it can be skipped when filing.

        They are invisible in a terminal, and 28 of 85 live records hold one.
        """
        fields = _marc_fields(_marc_element(
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">\x98Die\x9c Deutschen</subfield></datafield>'
        ))
        assert fields["245"][0]["a"] == "Die Deutschen"

    def test_padding_inside_a_subfield_is_collapsed(self):
        """MARC pads subfields. `245 $a` on the live record 9783446249974 reads
        `Reisen im  Licht der Sterne`, where that record's own `776 $t` spells
        it with one space."""
        fields = _marc_fields(_marc_element(
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">Reisen im  Licht der Sterne</subfield>'
            "</datafield>"
        ))
        assert fields["245"][0]["a"] == "Reisen im Licht der Sterne"

    def test_decomposed_text_is_normalised(self):
        """The DNB serves MARC21 decomposed and Dublin Core composed.

        Two spellings of one author is enough to store the same person twice.
        """
        fields = _marc_fields(_marc_element(
            '<datafield tag="100" ind1="1" ind2=" ">'
            '<subfield code="a">Mu\u0308ller, Hans</subfield></datafield>'
        ))
        assert fields["100"][0]["a"] == "M\u00fcller, Hans"


class TestPersonName:
    def test_turns_catalogue_order_into_a_readable_name(self):
        assert _flip_catalogue_name("Kane, Sean P.") == "Sean P. Kane"

    def test_keeps_the_full_stop_that_belongs_to_an_initial(self):
        """`Pohl, Robert O.` means nothing as `Robert O`, and the ISBD full stop
        stripped off `Melville, Herman.` looks the same to a regex."""
        assert _flip_catalogue_name("Pohl, Robert O.") == "Robert O. Pohl"

    def test_drops_the_life_dates_a_catalogue_hangs_off_a_name(self):
        assert _flip_catalogue_name("Melville, Herman, 1819-1891") == "Herman Melville"

    def test_leaves_a_corporate_name_alone(self):
        """Two commas is not "Surname, Forenames" and reordering would mangle it."""
        assert (
            _flip_catalogue_name("Springer Verlag, Berlin, Heidelberg")
            == "Springer Verlag, Berlin, Heidelberg"
        )


class TestPageCount:
    """Shared by the DNB and K10plus parsers, which spell the extent differently."""

    def test_reads_the_german_form(self):
        assert _pages_from_extent("390 Seiten") == 390

    def test_reads_the_english_form(self):
        assert _pages_from_extent("412 pages") == 412

    def test_returns_nothing_for_an_extent_it_cannot_parse(self):
        assert _pages_from_extent("1 Online-Ressource") is None

    def test_reads_the_abbreviated_form_k10plus_uses(self):
        assert _pages_from_extent("348 S.") == 348

    def test_ignores_the_dimensions_that_follow_the_extent(self):
        """A bare first number picks up "23 cm" as a page count."""
        assert _pages_from_extent("528 p. : ill. ; 23 cm") == 528

    def test_returns_nothing_for_an_absent_field(self):
        assert _pages_from_extent(None) is None


class TestK10plusIdentity:
    """Matching an ISBN is not the same as being the book it belongs to."""

    @pytest.mark.asyncio
    async def test_a_qualified_isbn_is_a_cross_reference_not_a_match(self):
        """`020 $q` names another edition, and taking it returns another book.

        Observed live: searching Dune's American ISBN returned a Ukrainian
        translation whose record carries `9780441013593 $q amerik. Original`.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=ENGLISH_ISBN,
                            isbn_qualifier="amerik. Original",
                            title='<subfield code="a">Velykyj Hetsbi</subfield>',
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_matches_a_record_holding_the_isbn_10_form(self):
        """020 often holds the ISBN-10 even for a search by ISBN-13.

        Comparing the strings would miss the record, which is most of what a
        pre-2007 printing is catalogued under.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc_record(isbn="0743273567"))
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "k10plus"
        assert result.data is not None
        assert result.data["title"] == "The Great Gatsby"

    @pytest.mark.asyncio
    async def test_prefers_the_fullest_of_several_printings(self):
        """One ISBN returns a handful of near-identical records."""
        sparse = _marc_record(title='<subfield code="a">The Great Gatsby</subfield>')
        full = _marc_record(
            title='<subfield code="a">The Great Gatsby</subfield>',
            extra='<datafield tag="520"><subfield code="a">Long Island, 1922.</subfield></datafield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc(sparse, full))
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.data is not None
        assert result.data["description"] == "Long Island, 1922."


class TestK10plusRecord:
    """MARC packs the shape of a catalogue card, not the shape of a book."""

    async def _lookup(self, record: str, isbn: str = ENGLISH_ISBN):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(_marc(record)))
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(isbn)
        assert result.data is not None
        return result.data

    @pytest.mark.asyncio
    async def test_maps_the_record_onto_book_fields(self):
        data = await self._lookup(_marc_record())
        assert data["title"] == "The Great Gatsby"
        assert data["author"] == "F. Scott Fitzgerald"
        assert data["publisher"] == "Scribner"
        assert data["year"] == 1925
        assert data["page_count"] == 218
        assert data["language"] == "en"

    @pytest.mark.asyncio
    async def test_reads_the_year_out_of_a_free_text_date(self):
        """`$c` really does arrive as "1925 (copyright)"."""
        data = await self._lookup(_marc_record())
        assert data["year"] == 1925

    @pytest.mark.asyncio
    async def test_drops_the_punctuation_that_introduces_the_next_subfield(self):
        """A record ends `$a` with the separator for `$b`, so titles carry a colon."""
        data = await self._lookup(
            _marc_record(
                title=(
                    '<subfield code="a">The Great Gatsby :</subfield>'
                    '<subfield code="b">a novel</subfield>'
                )
            )
        )
        assert data["title"] == "The Great Gatsby"
        assert data["subtitle"] == "a novel"

    @pytest.mark.asyncio
    async def test_closes_the_filing_space_after_an_elided_article(self):
        """`L' etranger` is a sorting device, not how the title is printed."""
        data = await self._lookup(
            _marc_record(title="<subfield code=\"a\">L' etranger</subfield>")
        )
        assert data["title"] == "L'etranger"

    @pytest.mark.asyncio
    async def test_a_numbered_volume_becomes_a_title_and_a_series(self):
        """`$a` is the collective title and `$p` the book somebody is holding.

        Without this the whole series is catalogued seven times under one name.
        """
        data = await self._lookup(
            _marc_record(
                title=(
                    '<subfield code="a">Harry Potter</subfield>'
                    '<subfield code="n">[1]</subfield>'
                    '<subfield code="p">The philosopher\'s stone</subfield>'
                )
            )
        )
        assert data["title"] == "The philosopher's stone"
        assert data["series_name"] == "Harry Potter"
        assert data["series_index"] == 1

    @pytest.mark.asyncio
    async def test_keeps_the_author_and_drops_the_translator(self):
        """A translator arrives in the same field as an author, marked `$4`."""
        data = await self._lookup(
            _marc_record(
                extra=(
                    '<datafield tag="700"><subfield code="a">Robben, Bernhard</subfield>'
                    '<subfield code="4">trl</subfield></datafield>'
                )
            )
        )
        assert data["author"] == "F. Scott Fitzgerald"

    @pytest.mark.asyncio
    async def test_ignores_an_added_entry_for_the_original_work(self):
        """A 700 carrying `$t` links a title, and its name is already the author's."""
        data = await self._lookup(
            _marc_record(
                extra=(
                    '<datafield tag="700"><subfield code="a">Fitzgerald, F. Scott</subfield>'
                    '<subfield code="t">The Great Gatsby</subfield>'
                    '<subfield code="4">aut</subfield></datafield>'
                )
            )
        )
        assert data["author"] == "F. Scott Fitzgerald"

    @pytest.mark.asyncio
    async def test_leaves_a_corporate_name_in_catalogue_order(self):
        """Two commas is not "Surname, Forenames", and flipping it mangles it."""
        data = await self._lookup(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            f'<datafield tag="020"><subfield code="a">{ENGLISH_ISBN}</subfield></datafield>'
            '<datafield tag="245"><subfield code="a">A report</subfield></datafield>'
            '<datafield tag="100">'
            '<subfield code="a">Springer, Berlin, Heidelberg</subfield>'
            '<subfield code="4">aut</subfield></datafield></record>'
        )
        assert data["author"] == "Springer, Berlin, Heidelberg"


class TestCrossReferenceGuard:
    """The DNB's identifier index matches a mention, not an identity."""

    def test_a_volume_slot_is_not_a_title(self):
        assert _is_placeholder_title("[Hauptbd.].")
        assert _is_placeholder_title("Bd. 3")
        assert _is_placeholder_title("Volume 2")
        assert _is_placeholder_title("")

    def test_a_real_title_is_kept(self):
        assert not _is_placeholder_title("Stoner")
        # "Band" is a prefix of this and must not match it.
        assert not _is_placeholder_title("Banditen")

    @pytest.mark.asyncio
    async def test_a_placeholder_record_is_a_miss_so_another_source_can_answer(self):
        """Observed live: a French ISBN returned a German set titled `[Hauptbd.].`

        Accepting it poisons the catalogue entry for good, and the record it
        displaced was sitting in the other source all along.
        """
        placeholder = DNB_RECORD.replace(
            '<subfield code="a">Praxiswissen Docker</subfield>',
            '<subfield code="a">[Hauptbd.].</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc(_marc_record(isbn=GERMAN_ISBN)))
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(placeholder))
            result = await lookup(GERMAN_ISBN)

        assert result.source == "k10plus"


class TestMerge:
    """Taking the first hit and stopping left fields empty that the other had."""

    @pytest.mark.asyncio
    async def test_fills_gaps_from_the_other_catalogue(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="520">'
                                '<subfield code="a">Long Island, 1922.</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        # The DNB leads for a German ISBN and keeps its own title.
        assert result.data["title"] == "Praxiswissen Docker"
        # The blurb exists only on the K10plus record. A DNB record never
        # carries one, so this is the field that proves a merge happened.
        assert result.data["description"] == "Long Island, 1922."
        assert result.source == "dnb+k10plus"

    @pytest.mark.asyncio
    async def test_a_field_that_is_already_set_is_never_overwritten(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            title='<subfield code="a">Wrong title</subfield>',
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["title"] == "Praxiswissen Docker"

    @pytest.mark.asyncio
    async def test_subjects_are_unioned_because_both_feed_the_tag_guess(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="650"><subfield code="a">Science Fiction</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert set(result.data["subjects"]) == {"Informatik", "Science Fiction"}

    @pytest.mark.asyncio
    async def test_a_classification_is_kept_whole_and_its_caption_too(self):
        """Both halves, because they catch opposite records.

        The caption is what a substring match against an English tag name
        needs; the number is what a German record has instead. Dropping either
        narrows the suggestion rather than sharpening it.

        **What supplies which half moved on 2026-08-24.** Under Dublin Core the
        DNB captioned its Dewey number, `830 Deutsche Literatur`; MARC 082
        carries the number alone, and it is the GND subject heading that now
        arrives with words attached.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["classifications"] == [
            {"scheme": ClassificationScheme.DDC, "number": "004", "label": None},
            {
                "scheme": ClassificationScheme.GND,
                "number": "4026894-9",
                "label": "Informatik",
            },
        ]

    @pytest.mark.asyncio
    async def test_a_marc_dewey_number_arrives_with_no_caption(self):
        """082 carries the notation and the printed schedule carries the words,
        so a caption here would be ours rather than the catalogue's."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="082"><subfield code="a">005.133</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["classifications"] == [
            {
                "scheme": ClassificationScheme.DDC,
                "number": "005.133",
                "label": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_the_marc_segmentation_prime_is_stripped(self):
        """`005.13/3` is how K10plus spells what the DNB stores as `005.133`.
        Measured live 2026-08-23: 53 of 463 082 `$a` values carry the prime, so
        storing it raw makes two rows for one heading."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="082"><subfield code="a">005.13/3</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["classifications"] == [
            {
                "scheme": ClassificationScheme.DDC,
                "number": "005.133",
                "label": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_a_marc_field_that_is_not_a_dewey_number_is_dropped(self):
        """084 holds RVK and BK notations in the same shape. A number whose
        scheme nothing here reads cannot be sorted, matched or shown."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="082"><subfield code="a">ST 250</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(GERMAN_ISBN)

        assert result.data is not None
        assert result.data["classifications"] == []

    @pytest.mark.asyncio
    def test_one_number_from_two_sources_keeps_the_caption(self):
        """Taking the leading source whole would throw a caption away.

        **No live source pair exercises this for DDC any more**, and that is
        the reason it is pinned at the unit level rather than through a lookup.
        Until 2026-08-24 the DNB captioned its Dewey number and K10plus did
        not; both now answer with the number alone, so the case a merge can
        still meet is a stored heading being re-enriched, which
        `_write_classifications` resolves with this same rule.
        """
        assert metadata._union_classifications(
            [
                {"scheme": ClassificationScheme.DDC, "number": "004", "label": None},
                {
                    "scheme": ClassificationScheme.DDC,
                    "number": "004",
                    "label": "Informatik",
                },
            ]
        ) == [
            {
                "scheme": ClassificationScheme.DDC,
                "number": "004",
                "label": "Informatik",
            }
        ]

    @pytest.mark.asyncio
    async def test_k10plus_leads_for_a_non_german_isbn(self):
        """The DNB holds foreign books mostly as cross references, not records."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc(_marc_record(isbn=ENGLISH_ISBN)))
            )
            mock.get(url__startswith=DNB).mock(
                return_value=_xml(
                    DNB_RECORD.replace("Praxiswissen Docker", "Etwas anderes")
                )
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.data is not None
        assert result.data["title"] == "The Great Gatsby"


class TestSearchTerms:
    """A typed query goes into a query language, so it has to be made safe."""

    def test_splits_on_whitespace(self):
        assert metadata._search_terms("moby dick melville") == [
            "moby",
            "dick",
            "melville",
        ]

    def test_strips_cql_metacharacters(self):
        """No book's title depends on an unbalanced quote."""
        assert '"' not in "".join(metadata._search_terms('moby "dick" =(x)'))

    def test_drops_boolean_keywords(self):
        """A search for "black and white" must not become an operator."""
        assert metadata._search_terms("black and white") == ["black", "white"]

    def test_drops_single_letters(self):
        """Initials and articles are noise in a catalogue index."""
        assert metadata._search_terms("j k rowling") == ["rowling"]

    def test_an_empty_query_yields_nothing(self):
        assert metadata._search_terms("   ") == []


class TestDenoising:
    """What the catalogues return that is not a book on a shelf."""

    @pytest.mark.parametrize(
        "extent",
        [
            "1 Online-Ressource (100 Seiten)",
            "1 online resource",
            "1 audio disc",
            "1 sound recording",
        ],
    )
    def test_a_digitised_or_recorded_copy_is_not_a_book(self, extent):
        assert not metadata._is_physical_book(extent, "Der Zauberberg")

    def test_a_printed_extent_is_a_book(self):
        assert metadata._is_physical_book("992 Seiten", "Der Zauberberg")

    def test_a_record_with_no_extent_is_allowed(self):
        """Plenty of good records omit it, and refusing them loses real books."""
        assert metadata._is_physical_book(None, "Der Zauberberg")

    def test_a_volume_slot_is_still_rejected(self):
        assert not metadata._is_physical_book("992 Seiten", "[Hauptbd.].")


class TestPersonNames:
    """Catalogues hang life dates and roles off a name. None of it is the name."""

    def test_strips_bnf_life_dates_and_role(self):
        assert (
            metadata._flip_catalogue_name("Zafón, Carlos (1964-2020). Auteur du texte")
            == "Carlos Zafón"
        )

    def test_strips_marc_life_dates(self):
        assert metadata._flip_catalogue_name("Melville, Herman, 1819-1891") == (
            "Herman Melville"
        )

    def test_leaves_an_ordinary_name_alone(self):
        assert metadata._flip_catalogue_name("Mann, Thomas") == "Thomas Mann"

    def test_leaves_a_corporate_name_in_catalogue_order(self):
        assert (
            metadata._flip_catalogue_name("Springer, Berlin, Heidelberg")
            == "Springer, Berlin, Heidelberg"
        )


class TestAccentsAndNearSpellings:
    """Half the shelf is not English and phone keyboards have no umlauts."""

    def test_folds_accents(self):
        assert metadata._normalise_words("Schätzing") == {"schatzing"}

    def test_matches_an_unaccented_spelling(self):
        assert metadata._matches_any("schatzing", {"schatzing"})

    def test_matches_a_genitive(self):
        """`Manns` against `mann`, which an exact set membership missed."""
        assert metadata._matches_any("manns", {"mann"})

    def test_does_not_match_a_different_word(self):
        assert not metadata._matches_any("code", {"coder", "encode"})


class TestRanking:
    """The catalogues return catalogue order, so the ranking here is the ranking."""

    def match(self, **overrides):
        base = {
            "source": "open_library",
            "title": None,
            "subtitle": None,
            "author": None,
            "series_name": None,
            "language": None,
            "year": None,
            "publisher": None,
            "page_count": None,
            "isbn13": None,
            "cover_url": None,
        }
        return {**base, **overrides}

    def rank(self, matches, query, prefer_language=None):
        terms = metadata._search_terms(query)
        return sorted(
            matches,
            key=lambda match: metadata._relevance(match, terms, prefer_language),
            reverse=True,
        )

    def test_the_novel_outranks_a_book_about_it(self):
        """The study guide carries the author's name inside its own title.

        Weighting a title match above an author match let it win, which is why
        they are worth the same and why the precision term exists.
        """
        novel = self.match(title="Der Zauberberg", author="Thomas Mann")
        guide = self.match(
            title="Textanalyse und Interpretation zu Thomas Manns Der Zauberberg",
            author="Nadine Heckner",
        )
        assert self.rank([guide, novel], "der zauberberg thomas mann")[0] is novel

    def test_a_row_matching_both_title_and_author_wins(self):
        """How people search: the title, then who wrote it."""
        novel = self.match(title="L'etranger", author="Albert Camus")
        study = self.match(title="L'Etranger, Camus", author="Pierre Louis Rey")
        assert self.rank([study, novel], "l'etranger camus")[0] is novel

    def test_a_complete_row_never_outranks_a_matching_one(self):
        """"Christmas at Hogwarts" came second for "harry potter" this way."""
        matching = self.match(title="Harry Potter and the Philosopher's Stone")
        unrelated = self.match(
            title="Christmas at Hogwarts",
            author="J. K. Rowling",
            year=2024,
            publisher="Bloomsbury",
            page_count=100,
            isbn13="9780747532699",
            cover_url="https://example.test/cover.jpg",
        )
        ranked = self.rank([unrelated, matching], "harry potter philosopher stone")
        assert ranked[0] is matching

    def test_completeness_breaks_a_tie_between_equal_matches(self):
        sparse = self.match(title="Dune", author="Frank Herbert")
        full = self.match(
            title="Dune",
            author="Frank Herbert",
            year=1965,
            publisher="Chilton",
            page_count=412,
            isbn13="9780441013593",
        )
        assert self.rank([sparse, full], "dune herbert")[0] is full

    def test_the_readers_language_breaks_a_tie(self):
        german = self.match(title="Der Schwarm", author="Frank Schätzing", language="de")
        english = self.match(title="Der Schwarm", author="Frank Schätzing", language="en")
        assert self.rank([english, german], "der schwarm schatzing", "de")[0] is german

    def test_the_readers_language_does_not_outrank_a_title_match(self):
        """A German household searching an English title still gets it."""
        wanted = self.match(title="Moby Dick", author="Herman Melville", language="en")
        other = self.match(title="Etwas anderes", author="Herman Melville", language="de")
        assert self.rank([other, wanted], "moby dick melville", "de")[0] is wanted

    def test_a_regional_only_row_ranks_below_an_equal_primary_one(self):
        primary = self.match(title="Dune", author="Frank Herbert", source="open_library")
        regional = self.match(title="Dune", author="Frank Herbert", source="loc")
        assert self.rank([regional, primary], "dune herbert")[0] is primary

    def test_a_regional_row_a_primary_also_found_is_not_penalised(self):
        """Being confirmed by a second catalogue is not a reason to demote."""
        confirmed = self.match(
            title="Der Schwarm", author="Frank Schätzing", source="bnf+k10plus",
            isbn13="9783596164530",
        )
        thin = self.match(title="Der Schwarm", author="Frank Schätzing", source="k10plus")
        assert self.rank([thin, confirmed], "der schwarm schatzing")[0] is confirmed

    def test_a_subtitle_does_not_dilute_the_score(self):
        """It counts for matching and not for precision.

        Including it in the denominator put "Clean Code: A Handbook of Agile
        Software Craftsmanship" three points below a reprint with no subtitle.
        """
        with_subtitle = self.match(
            title="Clean Code",
            subtitle="A Handbook of Agile Software Craftsmanship",
            author="Robert C. Martin",
            year=2008,
            isbn13="9780132350884",
            publisher="Prentice Hall",
            page_count=444,
        )
        without = self.match(title="Clean Code", author="Robert Martin", year=2025)
        assert self.rank([without, with_subtitle], "clean code robert martin")[0] is (
            with_subtitle
        )

    def test_a_row_matching_nothing_scores_zero(self):
        unrelated = self.match(title="Something else", author="Nobody")
        assert metadata._relevance(unrelated, ["dune"], None)[0] == 0


class TestSearchDeadline:
    """Six sources are asked at once, so the slowest one sets the wall clock."""

    @pytest.mark.asyncio
    async def test_a_slow_catalogue_is_dropped_rather_than_waited_for(
        self, monkeypatch
    ):
        monkeypatch.setattr(metadata, "SEARCH_DEADLINE_SECONDS", 0.05)

        async def quick() -> list[dict[str, object]]:
            return [{"title": "Fast"}]

        async def slow() -> list[dict[str, object]]:
            await asyncio.sleep(5)
            return [{"title": "Slow"}]

        results = await metadata._within_deadline([quick(), slow()])

        assert results == [[{"title": "Fast"}]]

    @pytest.mark.asyncio
    async def test_everything_that_answers_in_time_is_kept_in_order(self):
        async def first() -> list[dict[str, object]]:
            return [{"title": "One"}]

        async def second() -> list[dict[str, object]]:
            await asyncio.sleep(0.01)
            return [{"title": "Two"}]

        # Order matters downstream: the merge reads source precedence from the
        # order rows arrive in, and `asyncio.wait` returns an unordered set.
        results = await metadata._within_deadline([first(), second()])

        assert results == [[{"title": "One"}], [{"title": "Two"}]]


class TestLibraryOfCongressClassifications:
    """The one source that returns two schemes for one book.

    `<classification authority="lcc">QA76.73.P98 V53 2021</classification>`
    beside `authority="ddc"`, measured against the live endpoint on 2026-08-23.
    That pair is why the store carries a scheme column rather than a Dewey
    column.
    """

    MODS = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        "<typeOfResource>text</typeOfResource>"
        "<titleInfo><title>Clean Code</title></titleInfo>"
        "<physicalDescription><extent>464 p.</extent></physicalDescription>"
        '<classification authority="lcc">QA76.73.P98 V53 2021</classification>'
        '<classification authority="ddc" edition="23">005.133</classification>'
        '<classification authority="rvk">ST 250</classification>'
        "</mods>"
    )

    def _classifications(self) -> list[dict[str, object]]:
        parsed = _loc_record(ElementTree.fromstring(self.MODS))
        assert parsed is not None
        found = parsed["classifications"]
        assert isinstance(found, list)
        return found

    def test_both_schemes_are_kept(self):
        assert self._classifications() == [
            {
                "scheme": ClassificationScheme.LCC,
                "number": "QA76.73.P98 V53 2021",
                "label": None,
            },
            {
                "scheme": ClassificationScheme.DDC,
                "number": "005.133",
                "label": None,
            },
        ]

    def test_a_dewey_number_goes_through_the_same_normaliser(self):
        """MODS carries the prime too, so the LoC path must not be the one
        source that stores a spelling the others normalise away."""
        mods = self.MODS.replace(
            '<classification authority="ddc" edition="23">005.133</classification>',
            '<classification authority="ddc" edition="23">005.13/3</classification>',
        )
        parsed = _loc_record(ElementTree.fromstring(mods))
        assert parsed is not None
        numbers = [
            entry["number"]
            for entry in parsed["classifications"]
            if entry["scheme"] is ClassificationScheme.DDC
        ]

        assert numbers == ["005.133"]

    def test_an_authority_with_no_reading_here_is_dropped(self):
        """RVK is a German shelving scheme this app has no mapping for, and a
        number nothing can read is a string pretending to be a citation."""
        schemes = {entry["scheme"] for entry in self._classifications()}

        assert ClassificationScheme.DDC in schemes
        assert "rvk" not in schemes


class TestLibraryOfCongressSubjectHeadings:
    """LCSH out of the record the search path already fetches.

    A parser extension rather than a source: `<subject authority="lcsh">` sits
    beside the `<classification>` elements the class above reads, in the same
    MODS document, so it costs no request. Measured over 900 live records on
    2026-08-24: 769 of them carry at least one, 1,559 headings in all.
    """

    MODS = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        "<typeOfResource>text</typeOfResource>"
        "<titleInfo><title>Clean Code</title></titleInfo>"
        "<physicalDescription><extent>464 p.</extent></physicalDescription>"
        '<classification authority="lcc">QA76.73.P98 V53 2021</classification>'
        '<classification authority="ddc" edition="23">005.133</classification>'
        '<subject authority="lcsh"><topic>Computer programming</topic></subject>'
        '<subject authority="lcsh"><topic>Computer software</topic>'
        "<topic>Development</topic></subject>"
        '<subject authority="rvm"><topic>Genie logiciel</topic></subject>'
        "</mods>"
    )

    def _classifications(self, mods: str | None = None) -> list[dict[str, object]]:
        parsed = _loc_record(ElementTree.fromstring(mods or self.MODS))
        assert parsed is not None
        found = parsed["classifications"]
        assert isinstance(found, list)
        return found

    def _lcsh(self, mods: str | None = None) -> list[str]:
        return [
            str(entry["number"])
            for entry in self._classifications(mods)
            if entry["scheme"] is ClassificationScheme.LCSH
        ]

    def test_a_heading_becomes_a_row_under_its_own_scheme(self):
        assert {
            "scheme": ClassificationScheme.LCSH,
            "number": "Computer programming",
            "label": None,
        } in self._classifications()

    def test_a_subdivided_heading_is_one_row_and_not_two(self):
        """`Computer software` alone is a different heading with a different
        set of books under it, so the subdivisions belong in the string."""
        assert "Computer software -- Development" in self._lcsh()
        assert "Computer software" not in self._lcsh()

    def test_the_heading_is_the_number_and_no_caption_is_stored(self):
        """The record supplies no identifier, so the string is the access
        point. Writing it into `label` as well would store one fact twice."""
        rows = [
            entry
            for entry in self._classifications()
            if entry["scheme"] is ClassificationScheme.LCSH
        ]

        assert rows
        assert all(entry["label"] is None for entry in rows)

    def test_a_vocabulary_this_app_has_no_reading_for_is_dropped(self):
        """The Library of Congress mixes 23 authority values into one record.
        `rvm` is the French one; `fast` and `lcshac` are separate authority
        files whose headings are not LCSH's, so folding them in would make the
        scheme name a lie."""
        crowded = self.MODS.replace(
            "</mods>",
            '<subject authority="fast"><topic>Software engineering</topic></subject>'
            '<subject authority="lcshac"><topic>Computers</topic></subject>'
            "</mods>",
        )

        assert self._lcsh(crowded) == self._lcsh()

    def test_a_subject_with_no_authority_at_all_is_dropped(self):
        """289 of 2,280 live `<subject>` elements name no authority. A heading
        whose vocabulary is unstated cannot be matched against another
        catalogue, which is the only thing this store is for."""
        anonymous = self.MODS.replace(
            "</mods>", "<subject><topic>Uncontrolled</topic></subject></mods>"
        )

        assert self._lcsh(anonymous) == self._lcsh()

    def test_a_work_named_as_a_subject_reads_its_nested_title(self):
        """`<titleInfo>` nests a `<title>` rather than carrying text, which is
        one of the two nested shapes. 21 of 1,559 live headings are it."""
        about_a_work = self.MODS.replace(
            "</mods>",
            '<subject authority="lcsh"><titleInfo>'
            "<title>Microsoft Windows (Computer file)</title>"
            "</titleInfo></subject></mods>",
        )

        assert "Microsoft Windows (Computer file)" in self._lcsh(about_a_work)

    def test_a_person_named_as_a_subject_keeps_their_name(self):
        """`<name>` nests one to four `<namePart>` elements, and reading it as
        empty does not drop the heading, it shortens it: `Catholic Church --
        History` would arrive as `History`, which asserts a different thing
        about the book. 116 of 1,559 live LCSH elements are that shape."""
        about_a_person = self.MODS.replace(
            "</mods>",
            '<subject authority="lcsh"><name type="personal">'
            "<namePart>S\u00fcssheim, Karl,</namePart>"
            '<namePart type="date">1878-1947</namePart></name>'
            "<topic>Sources</topic></subject></mods>",
        )

        assert "S\u00fcssheim, Karl, 1878-1947 -- Sources" in self._lcsh(about_a_person)

    def test_a_subject_element_with_no_text_yields_no_row(self):
        empty = self.MODS.replace(
            "</mods>", '<subject authority="lcsh"><topic>  </topic></subject></mods>'
        )

        assert self._lcsh(empty) == self._lcsh()

    def test_a_subject_heading_is_never_read_as_a_dewey_number(self):
        """`ddc.parse_heading` accepts any three digit token, so a heading that
        opens with one would be stored as a Dewey number and would suggest a
        household tag from it. The guard is structural: `<classification>` is
        the only element handed to `ddc`, and this path does not import it."""
        numeric = self.MODS.replace(
            "<topic>Computer programming</topic>",
            "<topic>004 Jahre Bauhaus</topic>",
        )
        dewey = [
            entry["number"]
            for entry in self._classifications(numeric)
            if entry["scheme"] is ClassificationScheme.DDC
        ]

        assert dewey == ["005.133"]
        assert "004 Jahre Bauhaus" in self._lcsh(numeric)

    def test_the_shelf_classifications_come_before_the_subject_headings(self):
        """Which is load bearing rather than tidy. `_as_match` slices this list
        to eight and `routers/books._headings` applies `_SCHEME_ORDER` only
        afterwards, so on the search path a record's own order is the only
        thing keeping its Dewey number. One live record carries 14 LCSH
        headings against at most two classifications."""
        crowded = self.MODS.replace(
            "</mods>",
            "".join(
                f'<subject authority="lcsh"><topic>Thema {index}</topic></subject>'
                for index in range(14)
            )
            + "</mods>",
        )
        found = self._classifications(crowded)
        kept = _union_classifications(found)[:MAX_CLASSIFICATIONS_PER_BOOK]
        schemes = [entry["scheme"] for entry in kept]

        assert schemes[:2] == [ClassificationScheme.LCC, ClassificationScheme.DDC]
        assert ClassificationScheme.LCSH in schemes


# ── Open Library, deepened ────────────────────────────────────────────────────
#
# Open Library is the only source here that clusters printings under a work,
# and the only one whose subjects are a folksonomy rather than a vocabulary.
# Both facts are load bearing and both are pinned below.

OL_ISBN = "https://openlibrary.org/isbn/"
OL_WORKS = "https://openlibrary.org/works/"
OL_AUTHORS = "https://openlibrary.org/authors/"

#: One edition record, in the shape the live endpoint returns.
OL_EDITION = {
    "title": "Introduction to Algorithms",
    "publishers": ["MIT Press"],
    "publish_date": "2009",
    "number_of_pages": 1292,
    "languages": [{"key": "/languages/eng"}],
    "works": [{"key": "/works/OL4781294W"}],
    "authors": [{"key": "/authors/OL23919A"}],
    "dewey_decimal_class": ["005.1"],
    # Four spellings of one call number, which is what a live record carries.
    "lc_classifications": [
        "QA76.6 .I5858 2009",
        "QA76.6.I5858 2009",
        "QA76.6 .C662 2009",
    ],
}

OL_WORK = {
    "title": "Introduction to Algorithms",
    "subjects": ["Computer algorithms", "Algorithms", "open_syllabus_project"],
    "authors": [{"author": {"key": "/authors/OL23919A"}}],
}

OL_AUTHOR = {"name": "Thomas H. Cormen"}


def _ol_edition(**overrides: object) -> dict[str, object]:
    return {**OL_EDITION, **overrides}


def _open_library_routes(mock: respx.Router, **parts: httpx.Response) -> None:
    """Register one route per Open Library path shape.

    One catch-all would answer the edition, the work and the author with the
    same body, which is exactly the confusion these tests exist to rule out.
    """
    mock.get(url__startswith=OL_ISBN).mock(
        return_value=parts.get("edition", httpx.Response(404))
    )
    mock.get(url__startswith=OL_AUTHORS).mock(
        return_value=parts.get("author", httpx.Response(404))
    )
    mock.get(url__startswith=OL_WORKS).mock(
        return_value=parts.get("work", httpx.Response(404))
    )


class TestMergingTwoSearchRows:
    """`_merge_matches` when one row has classifications and the other does not."""

    def test_a_populated_list_beats_an_empty_one(self):
        """The regression this was written for, measured live before fixing.

        Every scalar a catalogue omits arrives as None, so "fill where the value
        `is None`" was the whole rule until `classifications` became the one list
        valued key `_as_match` writes. It always writes a list, so a source that
        found nothing wrote `[]`, which is not None, so it beat a populated list
        from the next source. Over 30 live title searches, 6 of the 10 merged
        rows whose Library of Congress half carried LCSH lost every heading, and
        in 6 of 6 the leading row's list was empty.
        """
        leading = {
            "source": "bnf",
            "title": "Les Miserables",
            "classifications": [],
        }
        following = {
            "source": "loc",
            "title": "Les Miserables",
            "classifications": [{"scheme": "lcsh", "number": "France -- History"}],
        }

        merged = metadata._merge_matches([leading, following])

        assert len(merged) == 1
        assert merged[0]["classifications"] == [
            {"scheme": "lcsh", "number": "France -- History"}
        ]

    def test_a_zero_is_a_value_and_not_an_absence(self):
        """`== []` rather than `not current`, pinned.

        Falsiness would reclassify a `page_count` of 0, a `year` of 0, a
        `series_index` of 0.0 and any empty string from present to absent, and
        the next source would overwrite them. Nothing else in this file
        distinguishes the two conditions, because `[]` is falsy under both.
        """
        leading = {"source": "bnf", "title": "A pamphlet", "page_count": 0}
        following = {"source": "loc", "title": "A pamphlet", "page_count": 480}

        merged = metadata._merge_matches([leading, following])

        assert merged[0]["page_count"] == 0

    def test_a_populated_list_is_not_replaced_by_a_later_one(self):
        """Only absence is filled. Unioning two populated lists would be a
        change to how every field merges, and is deliberately not what this does.
        """
        leading = {
            "source": "open_library",
            "title": "Les Miserables",
            "classifications": [{"scheme": "ddc", "number": "843.7"}],
        }
        following = {
            "source": "loc",
            "title": "Les Miserables",
            "classifications": [{"scheme": "lcsh", "number": "France -- History"}],
        }

        merged = metadata._merge_matches([leading, following])

        assert merged[0]["classifications"] == [{"scheme": "ddc", "number": "843.7"}]


class TestTheOpenLibraryLookup:
    """What the edition record, the work record and the author call each add."""

    @staticmethod
    async def _lookup(mock: respx.Router) -> metadata.Lookup:
        return await metadata._open_library(ENGLISH_ISBN, "")

    @pytest.mark.asyncio
    async def test_the_work_record_supplies_the_subjects_the_edition_lacks(self):
        """Measured over nine live editions: two carried subjects, seven did not
        while their work did. Reading only the edition is why Open Library used
        to contribute nothing to the tag suggestion."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.data is not None
        assert result.data["subjects"] == [
            "Computer algorithms",
            "Algorithms",
            "open_syllabus_project",
        ]

    @pytest.mark.asyncio
    async def test_a_subject_list_is_bounded(self):
        """A live work carries up to 137 subjects, and every one of them is
        another chance to pre-select a tag nobody meant."""
        crowded = {"subjects": [f"subject {index}" for index in range(50)]}
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=crowded),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert len(result.data["subjects"]) == metadata._OPEN_LIBRARY_MAX_SUBJECTS

    @pytest.mark.asyncio
    async def test_the_editions_own_subjects_come_first(self):
        """The printing's cataloguer beats the work's crowd where both spoke."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200, json=_ol_edition(subjects=["Set theory"])
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["subjects"][0] == "Set theory"

    @pytest.mark.asyncio
    async def test_a_subject_is_never_a_classification(self):
        """The decision this round turned on. Open Library subjects are
        uncontrolled strings (`open_syllabus_project`, `fiction classics`), and
        §30i's rule for the store is an assertion from a published scheme."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200,
                    json=_ol_edition(dewey_decimal_class=None, lc_classifications=None),
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["subjects"]
        assert result.data["classifications"] == []

    @pytest.mark.asyncio
    async def test_a_dewey_number_and_one_call_number_become_classifications(self):
        """The controlled half, and only the first LC value: the repeats are one
        call number written several ways, not several assertions."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["classifications"] == [
            {
                "scheme": ClassificationScheme.DDC,
                "number": "005.1",
                "label": None,
            },
            {
                "scheme": ClassificationScheme.LCC,
                "number": "QA76.6 .I5858 2009",
                "label": None,
            },
        ]

    @pytest.mark.asyncio
    async def test_a_dewey_value_that_is_not_a_number_is_dropped(self):
        """Through `ddc.parse_heading` like every other source path."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200,
                    json=_ol_edition(
                        dewey_decimal_class=["[Fic]"], lc_classifications=None
                    ),
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["classifications"] == []

    @pytest.mark.asyncio
    async def test_the_work_supplies_the_author_the_edition_does_not_credit(self):
        """Measured over five live lookups: four credited nobody on the edition
        and every one of the four credited somebody on the work."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition(authors=None)),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["author"] == "Thomas H. Cormen"

    @pytest.mark.asyncio
    async def test_the_page_count_and_the_language_are_read(self):
        """Both were missing entirely until this round, so a fallback lookup
        answered without two of the seven fields `_completeness` scores."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["page_count"] == 1292
        assert result.data["language"] == "en"

    @pytest.mark.asyncio
    async def test_a_key_that_is_not_open_librarys_is_never_fetched(self):
        """A key out of a third party response goes into a URL, and
        `@example.com/` moves the host rather than the path. The request that
        would make is ours, from our network position.

        **The author key here is `/authors/OL1A@example.com/`, deliberately.** A
        bare `@example.com/` is refused by `match`, `search` and `fullmatch`
        alike, so a regression from `fullmatch` to one of the other two would
        reopen the hole with this test still green. Only `fullmatch` refuses a
        key that *starts* with a valid one.
        """
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200,
                    json=_ol_edition(
                        authors=[{"key": "/authors/OL1A@example.com/"}],
                        works=[{"key": "/works/OL1W/../../evil"}],
                    ),
                ),
            )
            elsewhere = mock.get(url__startswith="https://example.com").mock(
                return_value=httpx.Response(200, json={"name": "Nobody"})
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["author"] is None
        assert not elsewhere.called

    @pytest.mark.asyncio
    async def test_a_work_refusing_with_a_status_costs_the_subjects_only(self):
        """A failure in either extra call costs that field, not the record."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(500),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.data is not None
        assert result.data["title"] == "Introduction to Algorithms"
        assert result.data["subjects"] == []

    @pytest.mark.asyncio
    async def test_a_work_timing_out_costs_the_subjects_only(self):
        """The half a 500 does not reach, and the one that mattered.

        All three requests used to share one `try`, so a timeout on the work
        fetch discarded an edition record that had already answered 200, and
        `_remember` cached that miss for `_MISS_TTL_SECONDS`: one blip made the
        ISBN uncatalogueable for five minutes. A stubbed 500 is the one failure
        the code always handled, so it passed while this did not.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json=_ol_edition())
            )
            mock.get(url__startswith=OL_AUTHORS).mock(
                return_value=httpx.Response(200, json=OL_AUTHOR)
            )
            mock.get(url__startswith=OL_WORKS).mock(
                side_effect=httpx.ReadTimeout("too slow")
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.data is not None
        assert result.data["title"] == "Introduction to Algorithms"
        assert result.data["subjects"] == []

    @pytest.mark.asyncio
    async def test_an_author_timing_out_costs_the_author_only(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json=_ol_edition())
            )
            mock.get(url__startswith=OL_WORKS).mock(
                return_value=httpx.Response(200, json=OL_WORK)
            )
            mock.get(url__startswith=OL_AUTHORS).mock(
                side_effect=httpx.ReadTimeout("too slow")
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.data is not None
        assert result.data["author"] is None
        assert result.data["subjects"]

    @pytest.mark.asyncio
    async def test_a_body_that_is_valid_json_but_not_an_object_is_not_a_500(self):
        """`[]` and `null` parse cleanly and then raise `AttributeError` on
        `.get`, which is a `ValueError` in no `except` clause on this path. A
        CDN error page served as `application/json` is enough to reach it."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=["not", "a", "record"]),
            )
            result = await self._lookup(mock)

        assert not result.found
        # `UNAVAILABLE`, not `NOT_FOUND`: a fault at the other end is not an
        # absence, and the two send the reader to different actions.
        assert result.outcome is Outcome.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_work_body_that_is_not_an_object_costs_the_subjects_only(self):
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=["nope"]),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.data is not None
        assert result.data["subjects"] == []

    @pytest.mark.asyncio
    async def test_a_page_count_no_book_could_have_is_dropped(self):
        """`BookLookup.page_count` is unbounded and `PUT /{id}/refresh` writes
        it straight onto a column with no CHECK: `10**19` raises
        `OverflowError` on the commit, and 100,001 upward stores silently past
        the app's own ceiling. Open Library is a wiki and this field is
        editable by any account."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200, json=_ol_edition(number_of_pages=10**19)
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.data is not None
        assert result.data["page_count"] is None


#: An editions listing, in the shape `/works/{key}/editions.json` returns.
OL_EDITIONS = {
    "size": 3,
    "entries": [
        {
            "title": "Introduction to Algorithms",
            "publishers": ["MIT Press"],
            "publish_date": "2009",
            "number_of_pages": 1320,
            "languages": [{"key": "/languages/eng"}],
            "isbn_13": ["9780262270830"],
            "authors": [{"key": "/authors/OL23919A"}],
            "covers": [12345],
            "dewey_decimal_class": ["005.1"],
        },
        {
            "title": "Algorithmen: Eine Einfuehrung",
            "publishers": ["Oldenbourg"],
            "publish_date": "2010",
            "languages": [{"key": "/languages/ger"}],
            "isbn_13": ["9783486590029"],
        },
        {
            "title": "Introduction to Algorithms",
            "publish_date": "1990",
        },
    ],
}


class TestTheEditionCluster:
    """`thingISBN` clustering, without LibraryThing's terms attached."""

    @staticmethod
    def _routes(mock: respx.Router, listing: object = OL_EDITIONS) -> None:
        mock.get(url__startswith=OL_ISBN).mock(
            return_value=httpx.Response(200, json=_ol_edition())
        )
        mock.get(url__regex=r"https://openlibrary\.org/works/[^/]+/editions\.json.*").mock(
            return_value=httpx.Response(200, json=listing)
        )
        mock.get(url__startswith=OL_AUTHORS).mock(
            return_value=httpx.Response(200, json=OL_AUTHOR)
        )

    @pytest.mark.asyncio
    async def test_the_cluster_answers_with_the_other_printings(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await metadata.editions(ENGLISH_ISBN, 5)

        assert [row["isbn13"] for row in rows] == [
            "9780262270830",
            "9783486590029",
            None,
        ]

    @pytest.mark.asyncio
    async def test_the_most_complete_printing_leads(self):
        """`_completeness`, the same function `_merge` uses to choose between
        printings: a row with a publisher, a year and a page count is one
        somebody can recognise their copy from."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await metadata.editions(ENGLISH_ISBN, 5)

        assert rows[0]["page_count"] == 1320
        assert rows[-1]["publisher"] is None

    @pytest.mark.asyncio
    async def test_a_printing_in_another_language_is_not_a_candidate(self):
        """A work spans translations. An English printing of a German book is
        the same work and cannot fill in that copy's publisher or page count."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await metadata.editions(ENGLISH_ISBN, 5, prefer_language="de")

        assert [row["isbn13"] for row in rows] == ["9783486590029", None]

    @pytest.mark.asyncio
    async def test_a_printing_declaring_the_wanted_language_leads(self):
        """The blocking defect of this round, and a filter alone did not fix it.

        22% to 33% of live entries declare no language, so a cluster whose
        foreign printings are unlabelled passed the filter whole and filled
        every row: King's *Es* (`9783453435773`) showed Turkish, Spanish,
        English and French, while the one printing declaring `ger` ranked fifth
        and was never shown. The language match is the first term of the sort,
        ahead of completeness, which is what puts it back on the page.
        """
        listing = {
            "size": 2,
            "entries": [
                # More complete, and unlabelled: it wins on completeness alone.
                {
                    "title": "Es, Turkish printing",
                    "publishers": ["Altin Kitaplar"],
                    "publish_date": "2019",
                    "number_of_pages": 900,
                    "isbn_13": ["9789751027788"],
                },
                {
                    "title": "Es",
                    "publish_date": "1988",
                    "languages": [{"key": "/languages/ger"}],
                },
            ],
        }
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock, listing)
            rows = await metadata.editions(ENGLISH_ISBN, 5, prefer_language="de")

        assert [row["title"] for row in rows] == ["Es", "Es, Turkish printing"]

    @pytest.mark.asyncio
    async def test_a_printing_declaring_no_language_survives_the_filter(self):
        """110 of 129 live entries declare one, and both German printings in
        the Der Zinker cluster are among the 19 that do not."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await metadata.editions(ENGLISH_ISBN, 5, prefer_language="fr")

        assert [row["title"] for row in rows] == ["Introduction to Algorithms"]
        assert rows[0]["language"] is None

    @pytest.mark.asyncio
    async def test_one_author_request_serves_every_row(self):
        """A cluster names its authors by key and the keys repeat, so resolving
        each row's own would be one request per row."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            author = mock.get(url__startswith=OL_AUTHORS).mock(
                return_value=httpx.Response(200, json=OL_AUTHOR)
            )
            rows = await metadata.editions(ENGLISH_ISBN, 5)

        assert author.call_count == 1
        assert rows[0]["author"] == "Thomas H. Cormen"

    @pytest.mark.asyncio
    async def test_a_classification_on_a_sibling_printing_is_carried(self):
        """24 of 129 live entries carry a Dewey number, and a picked one is
        applied to the book by `POST /{id}/enrich/apply`."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await metadata.editions(ENGLISH_ISBN, 5)

        assert rows[0]["classifications"] == [
            {"scheme": ClassificationScheme.DDC, "number": "005.1", "label": None}
        ]

    @pytest.mark.asyncio
    async def test_an_isbn_that_is_not_one_asks_nothing(self):
        with respx.mock(assert_all_called=False) as mock:
            edition = mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json=_ol_edition())
            )
            rows = await metadata.editions("not-an-isbn", 5)

        assert rows == []
        assert not edition.called

    @pytest.mark.asyncio
    async def test_a_listing_that_is_not_an_object_costs_no_rows(self):
        """From `editions` an `AttributeError` escapes `_work_cluster`, which
        catches `TimeoutError` only, and then `candidates`' bare `gather`, so it
        answers 500 for the whole page rather than losing the cluster."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock, ["not", "a", "listing"])
            rows = await metadata.editions(ENGLISH_ISBN, 5)

        assert rows == []

    @pytest.mark.asyncio
    async def test_an_edition_body_that_is_not_an_object_costs_no_rows(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json="just a string")
            )
            rows = await metadata.editions(ENGLISH_ISBN, 5)

        assert rows == []

    @pytest.mark.asyncio
    async def test_a_book_open_library_does_not_hold_costs_no_rows(self):
        """Open Library returns 404 for a good deal of German publishing,
        including round 2's own reference record."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OL_ISBN).mock(return_value=httpx.Response(404))
            rows = await metadata.editions(GERMAN_ISBN, 5)

        assert rows == []


class TestTheCandidates:
    """The cluster and the search, and the rule between them."""

    @staticmethod
    def _routes(mock: respx.Router) -> None:
        TestTheEditionCluster._routes(mock)
        mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
        mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
        mock.get(url__startswith="https://openlibrary.org/search.json").mock(
            return_value=httpx.Response(200, json={"docs": []})
        )
        mock.get(url__startswith="https://catalogue.bnf.fr").mock(
            return_value=httpx.Response(500)
        )
        mock.get(url__startswith="http://lx2.loc.gov").mock(
            return_value=httpx.Response(500)
        )

    @pytest.mark.asyncio
    async def test_the_cluster_leads(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await metadata.candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert rows[0]["isbn13"] == "9780262270830"

    @pytest.mark.asyncio
    async def test_the_cluster_never_takes_the_whole_page(self):
        """A work merged wrongly must not be the entire answer: the search row
        underneath it is the way out."""
        crowded = {
            "size": 9,
            "entries": [
                {"title": f"Printing {index}", "publish_date": str(2000 + index)}
                for index in range(9)
            ],
        }
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(
                url__regex=r"https://openlibrary\.org/works/[^/]+/editions\.json.*"
            ).mock(return_value=httpx.Response(200, json=crowded))
            rows = await metadata.candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert len(rows) == 4

    @pytest.mark.asyncio
    async def test_a_search_row_sharing_a_title_and_an_author_is_still_a_row(self):
        """The bug a live run found. `_match_key` is title plus author, and
        every row on this page shares both by construction, so deduplicating on
        it collapsed a five row answer to one. Two printings of one book are
        exactly what this endpoint exists to show."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {
                                "title": "Introduction to Algorithms",
                                "author_name": ["Thomas H. Cormen"],
                                "isbn": ["9780262046305"],
                            }
                        ]
                    },
                )
            )
            rows = await metadata.candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert rows[0]["title"] == rows[-1]["title"]
        assert "9780262046305" in [row["isbn13"] for row in rows]

    @pytest.mark.asyncio
    async def test_a_search_row_repeating_a_cluster_isbn_is_dropped(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {
                                "title": "Introduction to Algorithms",
                                "author_name": ["Thomas H. Cormen"],
                                "isbn": ["9780262270830"],
                            }
                        ]
                    },
                )
            )
            rows = await metadata.candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert [row["isbn13"] for row in rows].count("9780262270830") == 1

    @pytest.mark.asyncio
    async def test_a_book_with_no_isbn_still_gets_the_search(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {"title": "Introduction to Algorithms", "isbn": ["9780262046305"]}
                        ]
                    },
                )
            )
            rows = await metadata.candidates(
                "Introduction to Algorithms", isbn=None, limit=5
            )

        assert [row["isbn13"] for row in rows] == ["9780262046305"]

    @pytest.mark.asyncio
    async def test_a_slow_cluster_costs_its_rows_and_not_the_response(
        self, monkeypatch
    ):
        """One live editions listing answered in 10.1s against a 0.64s to 2.19s
        norm, which is what the deadline is for."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {"title": "Introduction to Algorithms", "isbn": ["9780262046305"]}
                        ]
                    },
                )
            )

            async def _forever(
                isbn: str, limit: int, prefer_language: str | None = None
            ) -> list[dict[str, object]]:
                await asyncio.sleep(30)
                return []

            monkeypatch.setattr(metadata, "editions", _forever)
            monkeypatch.setattr(metadata, "SEARCH_DEADLINE_SECONDS", 0.05)
            rows = await metadata.candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert [row["isbn13"] for row in rows] == ["9780262046305"]
