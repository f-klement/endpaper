"""Classifications on a book: stored whole, added never replaced.

The store's whole reason is that a catalogue heading has two halves and only
the number is language independent. What is pinned here is the half that used
to be thrown away, the rules that keep re-running enrichment from duplicating
rows, and that nothing in this app turns a heading into a tag by itself.
"""

import httpx
import respx

from models import Book, Classification, Tag
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from tests.helpers import (
    DNB,
    GOOGLE_BOOKS,
    K10PLUS,
    silence_catalogues,
    sru_response,
)

GERMAN_ISBN = "9783960092353"

#: A DNB record carrying one Dewey number and one GND subject heading. Shaped
#: after a live MARC21 response: 082 holds the number with no caption, and the
#: caption arrives on the subject heading instead, with its own identifier.
DNB_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
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
   </datafield>
   <datafield tag="264" ind1=" " ind2="1">
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
   <datafield tag="653" ind1=" " ind2=" ">
    <subfield code="a">20. Jahrhundert</subfield>
   </datafield>
  </record>
 </recordData></record></records>
</searchRetrieveResponse>
"""


def headings(book_id, db):
    """The stored rows, re-read.

    `expire_all` first, because this session is not the app's: a row it loaded
    before the request under test would otherwise come back from its identity
    map and hide a write the request rolled back.
    """
    db.expire_all()
    return (
        db.query(Classification)
        .filter(Classification.book_id == book_id)
        .order_by(Classification.id)
        .all()
    )


class TestAddingABookWithHeadings:
    def test_a_heading_posted_with_a_book_is_stored(self, client, admin, db):
        res = client.post(
            "/api/books",
            json={
                "title": "Praxiswissen Docker",
                "classifications": [
                    {"scheme": "ddc", "number": "004", "label": "Informatik"}
                ],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["classifications"] == [
            {"scheme": "ddc", "number": "004", "label": "Informatik"}
        ]
        assert len(headings(res.json()["id"], db)) == 1

    def test_a_book_added_without_one_carries_none(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])

        assert res.json()["classifications"] == []

    def test_the_same_number_twice_in_one_payload_becomes_one_row(
        self, client, admin, db
    ):
        """Two catalogues agreeing is the ordinary case, and two identical rows
        in one flush trip the unique index rather than the check before it."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "ddc", "number": "004", "label": None},
                    {"scheme": "ddc", "number": "004", "label": "Informatik"},
                ],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert len(headings(res.json()["id"], db)) == 1

    def test_a_scheme_nobody_recognises_is_refused(self, client, admin):
        """A number with no scheme has no reading, so the enum is closed."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [{"scheme": "rvk", "number": "ST 250"}],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_more_headings_than_any_catalogue_returns_are_refused(
        self, client, admin
    ):
        """Every entry becomes a row, so the list is bounded like every other
        caller-supplied one."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "ddc", "number": f"00{index}"} for index in range(9)
                ],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 422


class TestTheLookup:
    """The measured defect: a German record whose caption matches no tag."""

    def _lookup(self, client, headers):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD)
            )
            silence_catalogues(mock)
            return client.get(
                f"/api/books/lookup?isbn={GERMAN_ISBN}", headers=headers
            )

    def test_the_number_survives_the_lookup(self, client, admin):
        res = self._lookup(client, admin["headers"])

        assert res.status_code == 200
        assert res.json()["classifications"] == [
            {"scheme": "ddc", "number": "004", "label": None},
            {"scheme": "gnd", "number": "4026894-9", "label": "Informatik"},
        ]

    def test_a_german_caption_still_suggests_the_household_tag(
        self, client, admin, db
    ):
        """"Informatik" matches no seeded tag name. `004` maps to Computing,
        and that is the whole point of storing the number.

        Sharper since the MARC switch: the DNB no longer captions its Dewey
        number at all, so the caption route has nothing to match even by
        accident and the number is the only thing left that can resolve this.
        """
        computing = db.query(Tag).filter(Tag.name == "Computing").one()
        res = self._lookup(client, admin["headers"])

        assert computing.id in res.json()["suggested_tag_ids"]

    def test_a_year_is_not_read_as_a_classification(self, client, admin):
        """`20. Jahrhundert` is a keyword in 653. A looser parse of a field
        that is not 082 reads it as the number `20.`."""
        numbers = [
            entry["number"] for entry in self._lookup(client, admin["headers"]).json()["classifications"]
        ]

        assert numbers == ["004", "4026894-9"]

    def test_a_heading_the_column_could_not_hold_is_dropped(self, client, admin):
        """The lookup response is a draft the client posts straight back, so a
        caption longer than the column has to be refused here. Dropped rather
        than raised: nothing in a record is worth failing the whole lookup for.
        """
        long_caption = "x" * 400
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(
                    DNB_RECORD.replace(
                        '<subfield code="a">Informatik</subfield>',
                        f'<subfield code="a">{long_caption}</subfield>',
                    )
                )
            )
            silence_catalogues(mock)
            res = client.get(
                f"/api/books/lookup?isbn={GERMAN_ISBN}", headers=admin["headers"]
            )

        assert res.status_code == 200
        # The Dewey number is untouched: one unusable entry costs its own row
        # and not the record.
        assert res.json()["classifications"] == [
            {"scheme": "ddc", "number": "004", "label": None}
        ]

    def test_a_second_catalogues_dewey_number_survives_the_ceiling(
        self, client, admin
    ):
        """The ordering that decides what survives cannot live in a parser.

        `_merge` puts the leading source's list first and extends it with each
        other source's, so a DNB record at the ceiling leaves nothing for
        K10plus's Dewey number or the Library of Congress's call number: they
        are last in the list and `_headings` cuts the tail. Sorting by scheme
        before the slice is what makes "the Dewey number survives" true of a
        book rather than of a record.

        The DNB here supplies nine GND headings and no Dewey number at all
        (`082 $a=B` is the Sachgruppe letter, which is not a notation), so the
        only Dewey number in the answer is the one that arrives last.
        """
        headings = "".join(
            f'<datafield tag="650" ind1=" " ind2="7">'
            f'<subfield code="0">(DE-588)400000{index}-1</subfield>'
            f'<subfield code="a">Thema {index}</subfield></datafield>'
            for index in range(8)
        )
        dnb = DNB_RECORD.replace(
            '<subfield code="a">004</subfield>', '<subfield code="a">B</subfield>'
        ).replace("  </record>", f"{headings}\n  </record>")
        k10plus = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
            "<zs:records><zs:record><zs:recordData>"
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            f'<datafield tag="020"><subfield code="a">{GERMAN_ISBN}</subfield>'
            "</datafield>"
            '<datafield tag="245"><subfield code="a">Praxiswissen Docker</subfield>'
            "</datafield>"
            '<datafield tag="082"><subfield code="a">004</subfield></datafield>'
            "</record></zs:recordData></zs:record></zs:records>"
            "</zs:searchRetrieveResponse>"
        )
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(return_value=sru_response(dnb))
            mock.get(url__startswith=K10PLUS).mock(
                return_value=sru_response(k10plus)
            )
            silence_catalogues(mock)
            res = client.get(
                f"/api/books/lookup?isbn={GERMAN_ISBN}", headers=admin["headers"]
            )

        headings_out = res.json()["classifications"]
        assert len(headings_out) == MAX_CLASSIFICATIONS_PER_BOOK
        assert headings_out[0] == {"scheme": "ddc", "number": "004", "label": None}

    def test_the_lookup_writes_no_tag_by_itself(self, client, admin, db):
        """The server offers the ids and writes nothing, not even the book.

        The claim this pins is the server's half only: the web client
        pre-selects the suggestions on the confirm form, which
        `docs/decisions.md` argues for and this test says nothing about.
        """
        self._lookup(client, admin["headers"])

        assert db.query(Book).count() == 0


class TestEnrichment:
    def test_enrichment_stores_the_headings_it_finds(
        self, client, admin, make_book, db
    ):
        book = make_book(admin["headers"], isbn=GERMAN_ISBN)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD)
            )
            silence_catalogues(mock)
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.status_code == 200
        assert "classifications" in res.json()["updated_fields"]
        assert [entry.number for entry in headings(book["id"], db)] == [
            "004",
            "4026894-9",
        ]

    def test_running_it_twice_does_not_duplicate_a_heading(
        self, client, admin, make_book, db
    ):
        """Enrichment is re-runnable and the catalogues answer the same way, so
        an appending writer would deposit a second copy on every run."""
        book = make_book(admin["headers"], isbn=GERMAN_ISBN)
        for _ in range(2):
            with respx.mock(assert_all_called=False) as mock:
                mock.get(url__startswith=DNB).mock(
                    return_value=sru_response(DNB_RECORD)
                )
                silence_catalogues(mock)
                client.post(
                    f"/api/books/{book['id']}/enrich", headers=admin["headers"]
                )

        # The Dewey number and the GND subject heading, once each.
        assert len(headings(book["id"], db)) == 2

    def test_a_caption_already_stored_is_not_overwritten(
        self, client, admin, db
    ):
        """A heading already here came from a catalogue too, and the last
        writer is not the better one."""
        created = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "isbn": GERMAN_ISBN,
                "classifications": [
                    {"scheme": "ddc", "number": "004", "label": "Computer science"}
                ],
            },
            headers=admin["headers"],
        ).json()

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD)
            )
            silence_catalogues(mock)
            client.post(
                f"/api/books/{created['id']}/enrich", headers=admin["headers"]
            )

        assert headings(created["id"], db)[0].label == "Computer science"

    def test_a_missing_caption_is_filled_in(self, client, admin, db):
        """The exception to the rule above: a caption where there was none is
        strictly more than before.

        On the GND heading rather than the Dewey one, because since the MARC
        switch no source supplies a Dewey caption for this to fill in with.
        """
        created = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "isbn": GERMAN_ISBN,
                "classifications": [{"scheme": "gnd", "number": "4026894-9"}],
            },
            headers=admin["headers"],
        ).json()

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD)
            )
            silence_catalogues(mock)
            client.post(
                f"/api/books/{created['id']}/enrich", headers=admin["headers"]
            )

        assert headings(created["id"], db)[0].label == "Informatik"

    def test_a_caption_is_the_only_change_and_still_commits(
        self, client, admin, db
    ):
        """The isolated case, which the test above cannot reach.

        `enrich` and `enrich/apply` both commit only `if updated:`, and
        `get_db` closes the session in its `finally` without committing, so a
        writer that did not report a filled in caption as a change would have
        it rolled back. `test_a_missing_caption_is_filled_in` passes either way,
        because that book is empty enough for `merge_into` to report a column
        and commit for its own reasons. Here the payload carries **nothing but
        the caption**, so the classification write is the only thing that can
        cause a commit.
        """
        created = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [{"scheme": "ddc", "number": "004"}],
            },
            headers=admin["headers"],
        ).json()

        res = client.post(
            f"/api/books/{created['id']}/enrich/apply",
            json={
                "classifications": [
                    {"scheme": "ddc", "number": "004", "label": "Informatik"}
                ]
            },
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["updated_fields"] == ["classifications"]
        assert headings(created["id"], db)[0].label == "Informatik"

    def test_a_refresh_adds_a_heading_and_never_clears_one(
        self, client, admin, db
    ):
        """Unlike the columns a refresh rewrites: a catalogue that has no DDC
        number this time has not withdrawn the one another asserted."""
        created = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "isbn": GERMAN_ISBN,
                "classifications": [
                    {"scheme": "lcc", "number": "QA76.73.P98"}
                ],
            },
            headers=admin["headers"],
        ).json()

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=DNB).mock(
                return_value=sru_response(DNB_RECORD)
            )
            silence_catalogues(mock)
            res = client.put(
                f"/api/books/{created['id']}/refresh", headers=admin["headers"]
            )

        assert res.status_code == 200
        assert sorted(entry.number for entry in headings(created["id"], db)) == [
            "004",
            "4026894-9",
            "QA76.73.P98",
        ]


class TestMerging:
    def test_the_survivor_absorbs_the_loser_headings(self, client, admin, db):
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [{"scheme": "ddc", "number": "004"}],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "lcc", "number": "QA76.73.P98"}
                ],
            },
            headers=admin["headers"],
        ).json()

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert sorted(entry.number for entry in headings(keeper["id"], db)) == [
            "004",
            "QA76.73.P98",
        ]

    def test_the_survivor_absorbs_a_caption_it_lacked(self, client, admin, db):
        """The keeper may hold `(ddc, 004, NULL)` from K10plus while the loser
        holds the same number captioned by the DNB. Deleting that row without
        taking its caption loses it for good: nothing re-enriches a survivor."""
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [{"scheme": "ddc", "number": "004"}],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "ddc", "number": "004", "label": "Informatik"}
                ],
            },
            headers=admin["headers"],
        ).json()

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert [entry.label for entry in headings(keeper["id"], db)] == ["Informatik"]

    def test_a_merge_cannot_carry_the_survivor_past_the_ceiling(
        self, client, admin, db
    ):
        """The merge is the second writer of this table, and the larger hole if
        it is left out: `MergeRequest.book_ids` takes 20 books and carries no
        rate limiter, so one request could move 8 x 19 = 152 rows onto the
        survivor, which then becomes the next merge's baseline."""
        books = [
            client.post(
                "/api/books",
                json={
                    "title": f"Docker {book}",
                    "classifications": [
                        {"scheme": "ddc", "number": f"{book}{index}0"}
                        for index in range(1, 6)
                    ],
                },
                headers=admin["headers"],
            ).json()
            for book in range(1, 4)
        ]

        res = client.post(
            "/api/books/merge",
            json={
                "book_ids": [book["id"] for book in books],
                "keep_id": books[0]["id"],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert len(headings(books[0]["id"], db)) == MAX_CLASSIFICATIONS_PER_BOOK

    def test_the_survivor_own_headings_are_the_ones_that_survive(
        self, client, admin, db
    ):
        """Keeper first, then losers in id order: what survives is what was
        already stored, the same tie-break `_write_classifications` uses. The
        overflow is deleted, which is where it was going before this round
        anyway, since the cascade took every one of a loser's headings."""
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "ddc", "number": f"{index}00"} for index in range(1, 9)
                ],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [{"scheme": "ddc", "number": "990"}],
            },
            headers=admin["headers"],
        ).json()

        client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        numbers = {entry.number for entry in headings(keeper["id"], db)}
        assert "990" not in numbers
        assert len(numbers) == MAX_CLASSIFICATIONS_PER_BOOK

    def test_a_caption_is_still_absorbed_at_the_ceiling(self, client, admin, db):
        """The ceiling stops moves, not completions: a duplicate is already
        counted, so absorbing its caption spends no budget."""
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "ddc", "number": f"{index}00"} for index in range(1, 9)
                ],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "ddc", "number": "100", "label": "Philosophie"}
                ],
            },
            headers=admin["headers"],
        ).json()

        client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        stored = {entry.number: entry.label for entry in headings(keeper["id"], db)}
        assert stored["100"] == "Philosophie"
        assert len(stored) == MAX_CLASSIFICATIONS_PER_BOOK

    def test_a_heading_both_rows_carry_is_not_duplicated(self, client, admin, db):
        """Two rows for one book usually carry the same number, and the unique
        index would refuse the second on the flush."""
        pair = [
            client.post(
                "/api/books",
                json={
                    "title": f"Docker {index}",
                    "classifications": [{"scheme": "ddc", "number": "004"}],
                },
                headers=admin["headers"],
            ).json()
            for index in range(2)
        ]

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [pair[0]["id"], pair[1]["id"]], "keep_id": pair[0]["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert len(headings(pair[0]["id"], db)) == 1


class TestTheCeiling:
    """`MAX_CLASSIFICATIONS_PER_BOOK` has to bound the **book**, not the
    request. Every caller is bounded per request and the writer is additive
    across requests, so counting only the payload leaves the per book total
    unbounded, and `books_to_out` selectin-loads this relationship onto every
    row of every page."""

    def _apply(self, client, admin, book_id, numbers):
        return client.post(
            f"/api/books/{book_id}/enrich/apply",
            json={
                "classifications": [
                    {"scheme": "ddc", "number": number} for number in numbers
                ]
            },
            headers=admin["headers"],
        )

    def test_repeated_calls_cannot_grow_a_book_past_the_ceiling(
        self, client, admin, db
    ):
        book = client.post(
            "/api/books", json={"title": "Docker"}, headers=admin["headers"]
        ).json()

        for batch in range(4):
            res = self._apply(
                client,
                admin,
                book["id"],
                [f"{batch}{index}0" for index in range(1, 5)],
            )
            assert res.status_code == 200

        assert len(headings(book["id"], db)) == MAX_CLASSIFICATIONS_PER_BOOK

    def test_the_ones_already_stored_are_kept_rather_than_the_newest(
        self, client, admin, db
    ):
        """Dropping the incoming entry rather than evicting a stored one: a
        heading already here was asserted by a catalogue too, and churn is what
        the additive rule exists to avoid."""
        book = client.post(
            "/api/books", json={"title": "Docker"}, headers=admin["headers"]
        ).json()
        self._apply(client, admin, book["id"], [f"{index}00" for index in range(1, 9)])

        self._apply(client, admin, book["id"], ["990"])

        assert "990" not in {entry.number for entry in headings(book["id"], db)}

    def test_a_caption_still_fills_in_on_a_full_book(self, client, admin, db):
        """The ceiling stops inserts, not completions. A book at the ceiling
        must still be able to learn the caption for a heading it already has."""
        book = client.post(
            "/api/books", json={"title": "Docker"}, headers=admin["headers"]
        ).json()
        self._apply(client, admin, book["id"], [f"{index}00" for index in range(1, 9)])

        res = client.post(
            f"/api/books/{book['id']}/enrich/apply",
            json={
                "classifications": [
                    {"scheme": "ddc", "number": "100", "label": "Philosophie"}
                ]
            },
            headers=admin["headers"],
        )

        assert res.status_code == 200
        stored = {entry.number: entry.label for entry in headings(book["id"], db)}
        assert stored["100"] == "Philosophie"


class TestDeletion:
    def test_purging_a_book_takes_its_headings(self, client, admin, db):
        book = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [{"scheme": "ddc", "number": "004"}],
            },
            headers=admin["headers"],
        ).json()
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(
            f"/api/books/{book['id']}/permanent", headers=admin["headers"]
        )

        assert headings(book["id"], db) == []


def test_google_is_not_a_source_of_classifications(client, admin):
    """Google Books has no classification field, so a lookup that only Google
    answers carries none rather than an invented one."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=GOOGLE_BOOKS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "gb-1",
                            "volumeInfo": {
                                "title": "Docker",
                                "categories": ["Computers"],
                            },
                        }
                    ]
                },
            )
        )
        silence_catalogues(mock)
        res = client.get(
            f"/api/books/lookup?isbn={GERMAN_ISBN}", headers=admin["headers"]
        )

    assert res.status_code == 200
    assert res.json()["classifications"] == []
