"""Tests for backend/routers/books.py.

Outbound calls to Open Library and Google Books are intercepted with respx so
the suite never touches the network.
"""

import csv
import io

import httpx
import pytest
import respx

from models import Tag
from tests.helpers import (
    JPEG_BYTES,
    NOT_AN_IMAGE,
    PNG_BYTES,
    enable_google_books,
    items,
    selects_for,
    silence_covers,
    silence_nkp,
    silence_nlg,
    silence_oenb,
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


@pytest.fixture
def open_library_hit():
    """Open Library answers with a complete record.

    The fast pair has to be silenced. Open Library is a fallback now, reached
    only once the DNB and K10plus have both said they do not hold the book.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=DNB).mock(return_value=_sru_empty())
        mock.get(url__startswith=K10PLUS).mock(return_value=_sru_empty())
        silence_oenb(mock)
        silence_nlg(mock)
        silence_nkp(mock)
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
        mock.get(url__startswith="https://covers.openlibrary.org/").mock(
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
        silence_oenb(mock)
        silence_nlg(mock)
        silence_nkp(mock)
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
        silence_oenb(mock)
        silence_nlg(mock)
        silence_nkp(mock)
        mock.get(url__startswith=DNB).mock(
            return_value=httpx.Response(
                200, text=DNB_RECORD, headers={"content-type": "text/xml"}
            )
        )
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
        assert res.status_code == 422


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
        "sort,expected",
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

    def test_unknown_book_is_404(self, client, admin):
        assert client.put("/api/books/9999/refresh", headers=admin["headers"]).status_code == 404


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
        """Documents the current rule: admin overrides the author check on edit too."""
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

    def test_csv_has_the_expected_header(self, client, admin, make_book):
        make_book(admin["headers"])
        res = client.get("/api/books/export", headers=admin["headers"])
        header = next(csv.reader(io.StringIO(res.text)))
        assert header == [
            "Title", "Author", "ISBN", "Publisher", "Year",
            "Description", "Tags", "My Status", "Date Added", "Added By",
            "Format", "Condition", "Location", "Collection", "Purchase Price",
            "Purchase Currency", "Purchased On", "Purchased From",
        ]

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

    def test_it_says_nothing_about_another_members_private_book(
        self, client, admin, member, make_book
    ):
        """The uniqueness check sees every row, private ones included, so
        returning the id would turn a 409 into a way to confirm that a member
        owns a particular book."""
        make_book(admin["headers"], title="A diary", isbn=self.ISBN, is_private=True)

        res = client.post(
            "/api/books",
            json={"title": "Dune", "isbn": self.ISBN},
            headers=member["headers"],
        )

        assert res.status_code == 409
        assert isinstance(res.json()["detail"], str)

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
        assert long_cost == 11, f"{long_cost} selects for 25 books"
