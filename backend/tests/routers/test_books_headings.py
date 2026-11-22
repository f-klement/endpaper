"""A Book's heading field: the vocabularies it offers from, the suggestion, the pick.

The local copy is loaded straight through `vocabulary_copy.load`, so each route is
read on its own; what the suggestion matches is `tests/test_vocabulary_copy.py`.
"""

from datetime import datetime

import pytest
from sqlalchemy import select

import evidence
import marc
import marc_fields
import settings_store
import vocabulary_copy
from catalogue import Heading
from enums import ClassificationScheme, SettingKey
from models import Book, Classification
from ratelimit import HEADING_SUGGEST_LIMIT
from vocabularies import Entry


@pytest.fixture
def library(db) -> None:
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
    db.commit()


def load_gnd(db) -> None:
    entries = [
        Entry(id="(DE-588)4026894-9", scheme="gnd", subject="Informatik", synonyms=("Computerwissenschaft",))
    ]
    vocabulary_copy.load(db, "gnd", iter(entries), datetime(2026, 11, 20), None)


def load_lcsh(db) -> None:
    entries = [
        Entry(
            id="http://id.loc.gov/authorities/subjects/sh89003285",
            scheme="lcsh",
            subject="Computer science",
            synonyms=("Informatics",),
        )
    ]
    vocabulary_copy.load(db, "lcsh", iter(entries), datetime(2026, 11, 20), None)


def suggested(client, headers, book: int, scheme: str, typed: str) -> list[dict]:
    res = client.get(
        f"/api/books/{book}/headings/suggest", params={"scheme": scheme, "q": typed}, headers=headers
    )
    assert res.status_code == 200
    return [{key: row[key] for key in ("scheme", "number", "label")} for row in res.json()]


def switch_off(db) -> None:
    settings_store.set_value(db, SettingKey.HEADINGS_FROM_VOCABULARY, "false")
    db.commit()


def headings(db, book_id: int) -> list[tuple[str, str, str | None]]:
    db.expire_all()
    rows = db.execute(
        select(Classification.scheme, Classification.number, Classification.label).where(
            Classification.book_id == book_id
        )
    )
    return [tuple(row) for row in rows]


#: Bare, as `marc_fields.Subfields.gnd_identifier` stores a DNB record's `$0`.
INFORMATIK = {"scheme": "gnd", "number": "4026894-9", "label": "Informatik"}


class TestTheVocabularies:
    def test_a_loaded_copy_is_offered_in_library_mode(self, client, member, db, make_book, library):
        load_gnd(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.get(f"/api/books/{book}/headings/vocabularies", headers=member["headers"])

        assert res.status_code == 200
        assert [row["scheme"] for row in res.json()] == ["gnd"]

    def test_none_is_offered_in_a_household(self, client, member, db, make_book):
        load_gnd(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.get(f"/api/books/{book}/headings/vocabularies", headers=member["headers"])

        assert res.json() == []

    def test_none_is_offered_once_an_admin_switches_it_off(self, client, member, db, make_book, library):
        load_gnd(db)
        switch_off(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.get(f"/api/books/{book}/headings/vocabularies", headers=member["headers"])

        assert res.json() == []


class TestTheSuggestion:
    def test_a_variant_typed_offers_the_heading_in_the_form_an_import_stores(
        self, client, member, db, make_book, library
    ):
        load_gnd(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        assert suggested(client, member["headers"], book, "gnd", "Computer") == [INFORMATIK]

    def test_an_lcsh_heading_is_offered_as_its_heading_string_and_no_uri(
        self, client, member, db, make_book, library
    ):
        load_lcsh(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        assert suggested(client, member["headers"], book, "lcsh", "Comp") == [
            {"scheme": "lcsh", "number": "Computer science", "label": None}
        ]

    def test_it_is_refused_once_an_admin_switches_it_off(self, client, member, db, make_book, library):
        load_gnd(db)
        switch_off(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.get(
            f"/api/books/{book}/headings/suggest",
            params={"scheme": "gnd", "q": "Info"},
            headers=member["headers"],
        )

        assert res.status_code == 403

    def test_asking_past_the_limit_is_refused(self, client, member, db, make_book, library):
        book = make_book(member["headers"], title="Stoner")["id"]
        params = {"scheme": "gnd", "q": "Info"}
        url = f"/api/books/{book}/headings/suggest"

        answered = [
            client.get(url, params=params, headers=member["headers"]).status_code
            for _ in range(HEADING_SUGGEST_LIMIT.max_attempts)
        ]
        refused = client.get(url, params=params, headers=member["headers"])

        assert set(answered) == {200}
        assert refused.status_code == 429

    def test_it_is_refused_in_a_household(self, client, member, db, make_book):
        load_gnd(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.get(
            f"/api/books/{book}/headings/suggest",
            params={"scheme": "gnd", "q": "Info"},
            headers=member["headers"],
        )

        assert res.status_code == 403

    def test_a_query_under_the_minimum_is_refused(self, client, member, db, make_book, library):
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.get(
            f"/api/books/{book}/headings/suggest",
            params={"scheme": "gnd", "q": "I" * (vocabulary_copy.SUGGEST_MIN - 1)},
            headers=member["headers"],
        )

        assert res.status_code == 422

    def test_a_book_the_caller_cannot_see_answers_what_an_absent_one_does(
        self, client, member, other_user, db, make_book, library
    ):
        private = make_book(other_user["headers"], title="Diary", is_private=True)["id"]
        params = {"scheme": "gnd", "q": "Info"}

        headers = member["headers"]
        own = make_book(headers, title="Stoner")["id"]
        answered = client.get(f"/api/books/{own}/headings/suggest", params=params, headers=headers)
        refused = client.get(f"/api/books/{private}/headings/suggest", params=params, headers=headers)
        absent = client.get(f"/api/books/{private + 5000}/headings/suggest", params=params, headers=headers)

        # The caller's own book answers, so the 404s are about the book and
        # not a route that is absent.
        assert answered.status_code == 200
        assert refused.status_code == absent.status_code == 404
        assert refused.json() == absent.json()


class TestThePick:
    def test_the_picked_heading_is_written_to_the_book(self, client, member, db, make_book, library):
        load_gnd(db)
        book = make_book(member["headers"], title="Stoner")["id"]
        [picked] = suggested(client, member["headers"], book, "gnd", "Info")

        res = client.post(f"/api/books/{book}/headings", json=picked, headers=member["headers"])

        assert res.status_code == 200
        assert headings(db, book) == [("gnd", "4026894-9", "Informatik")]

    def test_a_pick_on_a_book_holding_the_imported_heading_leaves_one_row(
        self, client, member, db, make_book, library
    ):
        load_gnd(db)
        book = make_book(member["headers"], title="Stoner")["id"]
        dnb_field = marc_fields.Subfields([("a", "Informatik"), ("0", "(DE-588)4026894-9")])
        imported = Heading(ClassificationScheme.GND, dnb_field.gnd_identifier() or "", "Informatik")
        evidence.confirm_file_headings(db.get(Book, book), [imported], db)
        db.commit()
        [picked] = suggested(client, member["headers"], book, "gnd", "Info")

        res = client.post(f"/api/books/{book}/headings", json=picked, headers=member["headers"])

        assert res.status_code == 200
        assert headings(db, book) == [("gnd", "4026894-9", "Informatik")]

    def test_the_marc_export_of_a_picked_gnd_heading_carries_one_prefix(
        self, client, member, db, make_book, library
    ):
        load_gnd(db)
        book = make_book(member["headers"], title="Stoner")["id"]
        [picked] = suggested(client, member["headers"], book, "gnd", "Info")
        client.post(f"/api/books/{book}/headings", json=picked, headers=member["headers"])
        db.expire_all()

        exported = marc.write([db.get(Book, book)])

        assert "(DE-588)(DE-588)" not in exported
        assert exported.count("(DE-588)4026894-9") == 1

    def test_a_picked_lcsh_heading_is_written_as_an_import_writes_one(
        self, client, member, db, make_book, library
    ):
        load_lcsh(db)
        book = make_book(member["headers"], title="Stoner")["id"]
        [picked] = suggested(client, member["headers"], book, "lcsh", "Comp")

        client.post(f"/api/books/{book}/headings", json=picked, headers=member["headers"])

        assert headings(db, book) == [("lcsh", "Computer science", None)]

    def test_it_is_refused_once_an_admin_switches_it_off(self, client, member, db, make_book, library):
        switch_off(db)
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.post(f"/api/books/{book}/headings", json=INFORMATIK, headers=member["headers"])

        assert res.status_code == 403
        assert headings(db, book) == []

    def test_it_is_refused_in_a_household(self, client, member, db, make_book):
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.post(f"/api/books/{book}/headings", json=INFORMATIK, headers=member["headers"])

        assert res.status_code == 403
        assert headings(db, book) == []

    def test_a_scheme_nobody_defined_is_refused_naming_the_field(
        self, client, member, db, make_book, library
    ):
        book = make_book(member["headers"], title="Stoner")["id"]

        res = client.post(
            f"/api/books/{book}/headings",
            json={**INFORMATIK, "scheme": "nosuch"},
            headers=member["headers"],
        )

        assert res.status_code == 422
        assert res.json()["detail"][0]["loc"] == ["body", "scheme"]
        assert headings(db, book) == []

    def test_a_book_the_caller_cannot_see_is_not_written(
        self, client, member, other_user, db, make_book, library
    ):
        private = make_book(other_user["headers"], title="Diary", is_private=True)["id"]
        own = make_book(member["headers"], title="Stoner")["id"]

        written = client.post(f"/api/books/{own}/headings", json=INFORMATIK, headers=member["headers"])
        res = client.post(f"/api/books/{private}/headings", json=INFORMATIK, headers=member["headers"])

        # The caller's own book is written, so the 404 is about the book and
        # not a route that is absent.
        assert written.status_code == 200
        assert res.status_code == 404
        assert headings(db, private) == []
