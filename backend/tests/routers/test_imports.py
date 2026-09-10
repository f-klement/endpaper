"""Tests for backend/routers/imports.py: importing a library export.

The Goodreads shape is used throughout because it is the one most people
arrive with and the one with the awkward parts (formula-wrapped ISBNs, a status
column that is not the tag column). Every other service's shape is covered at
the parser, in `tests/test_csv_import.py`.
"""

import csv
import dataclasses
import io

import csv_import
from enums import BookFormat, ReadStatus
from models import Book, UserBook
from tests.helpers import items

HEADER = (
    "Book Id,Title,Author,ISBN,ISBN13,My Rating,Publisher,"
    "Number of Pages,Year Published,Date Read,Bookshelves,Exclusive Shelf\n"
)


def csv_bytes(*rows: str) -> bytes:
    return (HEADER + "".join(row + "\n" for row in rows)).encode()


def goodreads_row(title: str, shelf: str, isbn13: str = '=""') -> str:
    return f'1,"{title}","An Author",="",{isbn13},0,Pub,300,2000,,shelf,{shelf}'


def upload(client, headers, content: bytes, **params):
    return client.post(
        "/api/imports/csv",
        files={"file": ("goodreads_library_export.csv", content, "text/csv")},
        headers=headers,
        params=params,
    )


class TestStatusSync:
    def test_sets_the_status_of_a_matching_book(self, client, admin, make_book, db):
        make_book(admin["headers"], title="Dune", isbn="9780441013593")

        res = upload(
            client,
            admin["headers"],
            csv_bytes(goodreads_row("Dune", "read", '="9780441013593"')),
        )

        assert res.status_code == 200
        assert res.json()["statuses_updated"] == 1
        assert db.query(UserBook).one().status == ReadStatus.READ

    def test_matches_by_title_when_there_is_no_isbn(self, client, admin, make_book):
        make_book(admin["headers"], title="Neuromancer")

        res = upload(client, admin["headers"], csv_bytes(goodreads_row("Neuromancer", "read")))

        assert res.json()["matched"] == 1

    def test_title_matching_ignores_case(self, client, admin, make_book):
        make_book(admin["headers"], title="Neuromancer")

        res = upload(client, admin["headers"], csv_bytes(goodreads_row("NEUROMANCER", "read")))

        assert res.json()["matched"] == 1

    def test_want_to_read_survives_the_round_trip(self, client, admin, make_book, db):
        # The reason ReadStatus has a fourth value at all.
        make_book(admin["headers"], title="Dune")

        upload(client, admin["headers"], csv_bytes(goodreads_row("Dune", "to-read")))

        assert db.query(UserBook).one().status == ReadStatus.WANT_TO_READ

    def test_currently_reading_maps_to_reading(self, client, admin, make_book, db):
        make_book(admin["headers"], title="Dune")

        upload(client, admin["headers"], csv_bytes(goodreads_row("Dune", "currently-reading")))

        assert db.query(UserBook).one().status == ReadStatus.READING

    def test_an_unchanged_status_is_not_counted_as_updated(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "read"},
            headers=admin["headers"],
        )

        res = upload(client, admin["headers"], csv_bytes(goodreads_row("Dune", "read")))

        assert res.json()["matched"] == 1
        assert res.json()["statuses_updated"] == 0

    def test_importing_twice_does_not_duplicate_rows(self, client, admin, make_book, db):
        make_book(admin["headers"], title="Dune")
        content = csv_bytes(goodreads_row("Dune", "read"))

        upload(client, admin["headers"], content)
        upload(client, admin["headers"], content)

        assert db.query(UserBook).count() == 1


class TestStatusesArePersonal:
    def test_one_member_importing_does_not_change_another_s_status(
        self, client, admin, member, make_book
    ):
        """The whole point of a per-member status.

        Two people can import their own shelves for the same shared book
        without overwriting each other.
        """
        book = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "reading"},
            headers=admin["headers"],
        )

        upload(client, member["headers"], csv_bytes(goodreads_row("Dune", "read")))

        seen_by_admin = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        seen_by_member = client.get(f"/api/books/{book['id']}", headers=member["headers"]).json()
        assert seen_by_admin["my_status"] == "reading"
        assert seen_by_member["my_status"] == "read"


class TestUnmatched:
    def test_a_book_not_in_the_catalogue_is_reported(self, client, admin):
        res = upload(client, admin["headers"], csv_bytes(goodreads_row("Some Other Book", "read")))

        body = res.json()
        assert body["matched"] == 0
        assert "Some Other Book" in body["unmatched_titles"]

    def test_nothing_is_created_by_default(self, client, admin, db):
        from models import Book

        upload(client, admin["headers"], csv_bytes(goodreads_row("Some Other Book", "read")))

        assert db.query(Book).count() == 0

    def test_create_missing_adds_them(self, client, admin, db):
        from models import Book

        res = upload(
            client,
            admin["headers"],
            csv_bytes(goodreads_row("Some Other Book", "read", '="9780441013593"')),
            create_missing=True,
        )

        assert res.json()["created"] == 1
        created = db.query(Book).one()
        assert created.title == "Some Other Book"
        assert created.isbn == "9780441013593"

    def test_a_shelf_we_do_not_recognise_leaves_the_status_alone(
        self, client, admin, make_book, db
    ):
        """This used to drop the whole row, and dropping it was wrong.

        A row on a custom shelf is still a book. The status is the part that
        cannot be read, so the status is the part left unset; the book itself
        is matched and reported like any other.
        """
        make_book(admin["headers"], title="Dune")

        res = upload(client, admin["headers"], csv_bytes(goodreads_row("Dune", "borrowed")))

        body = res.json()
        assert body["matched"] == 1
        assert body["skipped"] == 0
        assert db.query(UserBook).count() == 0


class TestPrivacy:
    def test_another_member_s_private_book_is_not_matched(
        self, client, admin, member, make_book
    ):
        # Matching it would confirm the book exists, and would let someone set
        # a status on a book they cannot see.
        make_book(admin["headers"], title="Diary", is_private=True)

        res = upload(client, member["headers"], csv_bytes(goodreads_row("Diary", "read")))

        assert res.json()["matched"] == 0


class TestThePreview:
    """`POST /api/imports/preview`, which had **no test at all** until
    2026-08-26 while `COVERAGE.md` listed this file as covering the rate limit.

    A column guessed wrong is invisible until after the import, and after the
    import is too late, which is what the endpoint is for.
    """

    def test_it_reports_the_mapping_without_writing(self, client, admin, db):
        res = client.post(
            "/api/imports/preview",
            files={"file": ("export.csv", csv_bytes(goodreads_row("Dune", "read")), "text/csv")},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["total_rows"] == 1
        assert db.query(Book).count() == 0

    def test_it_honours_an_override(self, client, admin):
        """The same overrides the import will use. Without them a reader who
        corrects a mapping cannot see the corrected result."""
        res = client.post(
            "/api/imports/preview",
            files={"file": ("export.csv", csv_bytes(goodreads_row("Dune", "read")), "text/csv")},
            headers=admin["headers"],
            params={"overrides": "title=Author"},
        )

        assert res.status_code == 200
        assert res.json()["mapping"]["title"] == "Author"

    def test_it_is_rate_limited(self, client, admin):
        """Added with the limiter itself. Parsing is the expensive half, 3.081
        seconds of CPU for a 5.02 MB export, and only the import was limited
        while `docs/security.md` promised `/api/imports/*` at three a minute.

        A limiter nothing exercises is a limiter nobody notices removing.
        """
        content = csv_bytes(goodreads_row("Dune", "read"))
        codes = [
            client.post(
                "/api/imports/preview",
                files={"file": ("export.csv", content, "text/csv")},
                headers=admin["headers"],
            ).status_code
            for _ in range(4)
        ]

        assert codes == [200, 200, 200, 429]

    def test_the_window_is_shared_with_the_import(self, client, admin):
        """Three previews spend the window, so the import that follows is
        refused. The flow the UI produces is one preview and one import, which
        is two of the three."""
        content = csv_bytes(goodreads_row("Dune", "read"))
        for _ in range(3):
            client.post(
                "/api/imports/preview",
                files={"file": ("export.csv", content, "text/csv")},
                headers=admin["headers"],
            )

        assert upload(client, admin["headers"], content).status_code == 429


class TestBadInput:
    def test_a_plain_title_and_author_list_is_now_accepted(self, client, admin):
        """This used to be refused for not being a Goodreads export.

        A title column is the whole requirement. Somebody with a list they
        typed themselves, or an export from a service nobody has heard of, has
        the thing this endpoint is for.
        """
        res = upload(client, admin["headers"], b"Title,Author\nDune,Frank Herbert\n")

        assert res.status_code == 200
        assert res.json()["rows_read"] == 1

    def test_a_file_with_no_title_column_is_refused(self, client, admin):
        res = upload(client, admin["headers"], b"Colour,Weight\nred,3kg\n")

        assert res.status_code == 400
        assert "No title column" in res.json()["detail"]
        # The real headers are named, so the reader can pick one by hand
        # rather than guess what the parser wanted.
        assert "Colour" in res.json()["detail"]

    def test_an_empty_file_is_refused(self, client, admin):
        res = upload(client, admin["headers"], b"")
        assert res.status_code == 400

    def test_requires_authentication(self, client):
        res = client.post(
            "/api/imports/csv",
            files={"file": ("export.csv", csv_bytes(goodreads_row("Dune", "read")), "text/csv")},
        )
        assert res.status_code == 401


class TestSummary:
    def test_counts_add_up(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune")

        res = upload(
            client,
            admin["headers"],
            csv_bytes(
                goodreads_row("Dune", "read"),
                goodreads_row("Missing Book", "to-read"),
                goodreads_row("Ignored", "custom-shelf"),
            ),
        )

        body = res.json()
        # All three rows are books. The custom shelf is not a status we can
        # read, which costs that row its status and nothing else.
        assert body["rows_read"] == 3
        assert body["skipped"] == 0
        assert body["matched"] == 1
        assert len(body["unmatched_titles"]) == 2


class TestImportedBooksAreNotAssumedOwned:
    """A reading history is not evidence of possession.

    This is the distinction the whole bulk-confirmation flow exists for: an
    export says what someone read, which is silent on whether a copy was ever
    in the house.
    """

    def test_created_books_arrive_unverified(self, client, admin, db):
        from models import Book

        upload(
            client,
            admin["headers"],
            csv_bytes(goodreads_row("A Library Book", "read")),
            create_missing=True,
        )

        assert db.query(Book).one().ownership == "unknown"

    def test_they_are_findable_as_a_group_afterwards(self, client, admin, make_book):
        # How the member gets a working list to confirm from.
        make_book(admin["headers"], title="Already On The Shelf")
        upload(
            client,
            admin["headers"],
            csv_bytes(goodreads_row("Imported One", "read"), goodreads_row("Imported Two", "to-read")),
            create_missing=True,
        )

        unverified = client.get(
            "/api/books", params={"ownership": "unknown"}, headers=admin["headers"]
        ).json()["items"]

        assert {book["title"] for book in unverified} == {"Imported One", "Imported Two"}

    def test_confirming_them_in_bulk_completes_the_flow(self, client, admin):
        upload(
            client,
            admin["headers"],
            csv_bytes(goodreads_row("Imported One", "read"), goodreads_row("Imported Two", "read")),
            create_missing=True,
        )
        unverified = client.get(
            "/api/books", params={"ownership": "unknown"}, headers=admin["headers"]
        ).json()["items"]

        res = client.post(
            "/api/books/bulk",
            json={
                "book_ids": [book["id"] for book in unverified],
                "action": "set_ownership",
                "value": "owned",
            },
            headers=admin["headers"],
        )

        assert res.json()["updated"] == 2
        # Nothing left waiting to be confirmed.
        remaining = client.get(
            "/api/books", params={"ownership": "unknown"}, headers=admin["headers"]
        ).json()
        assert remaining["total"] == 0

    def test_matching_an_existing_book_does_not_change_its_ownership(
        self, client, admin, make_book
    ):
        # The book was already on the shelf; an import must not cast doubt on
        # something that was previously confirmed.
        make_book(admin["headers"], title="Dune")

        upload(client, admin["headers"], csv_bytes(goodreads_row("Dune", "read")))

        listed = client.get("/api/books", headers=admin["headers"]).json()["items"]
        assert listed[0]["ownership"] == "owned"


class TestImportedRatingsAndDates:
    """The two columns the parser always understood and the importer used to
    throw away, because there was nowhere to put them."""

    def csv_with(self, *, rating: str = "4", date_read: str = "2021/03/14", shelf: str = "read") -> bytes:
        header = (
            "Book Id,Title,Author,ISBN,ISBN13,My Rating,Publisher,"
            "Number of Pages,Year Published,Date Read,Bookshelves,Exclusive Shelf\n"
        )
        row = (
            f'1,"Dune","Frank Herbert",="0441013597",="9780441013593",{rating},'
            f"Chilton,412,1965,{date_read},favourites,{shelf}\n"
        )
        return (header + row).encode()

    def upload(self, client, headers, content: bytes, **params):
        return client.post(
            "/api/imports/csv",
            files={"file": ("export.csv", content, "text/csv")},
            params=params,
            headers=headers,
        )

    def test_a_rating_is_imported(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        self.upload(client, admin["headers"], self.csv_with(rating="4"))

        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["my_rating"] == 4

    def test_a_zero_rating_means_unrated(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        self.upload(client, admin["headers"], self.csv_with(rating="0"))

        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["my_rating"] is None

    def test_an_existing_local_rating_is_not_overwritten(self, client, admin, make_book):
        """Somebody who has rated a book here has expressed a more recent
        opinion than an export taken from another service."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 2}, headers=admin["headers"]
        )

        self.upload(client, admin["headers"], self.csv_with(rating="5"))

        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["my_rating"] == 2

    def test_a_finish_date_is_imported(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        self.upload(client, admin["headers"], self.csv_with(date_read="2021/03/14"))

        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["my_finished_at"].startswith("2021-03-14")

    def test_a_date_is_ignored_for_a_book_not_finished(self, client, admin, make_book):
        """A date on a currently-reading row would be a finish date for a book
        nobody finished."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        self.upload(
            client,
            admin["headers"],
            self.csv_with(shelf="currently-reading", date_read="2021/03/14"),
        )

        detail = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert detail["my_finished_at"] is None
        assert detail["my_status"] == "reading"

    def test_a_rating_alone_counts_as_a_change(self, client, admin, make_book):
        """The status already matches, so only the rating moved. Reporting zero
        updates would say the import did nothing."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        res = self.upload(client, admin["headers"], self.csv_with(rating="4", date_read=""))

        assert res.json()["statuses_updated"] == 1

    def test_the_rating_is_personal(self, client, admin, member, make_book):
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        self.upload(client, admin["headers"], self.csv_with(rating="4"))

        seen_by_member = client.get(f"/api/books/{book['id']}", headers=member["headers"])
        assert seen_by_member.json()["my_rating"] is None


class TestAnotherMembersPrivateBook:
    """`books.isbn` is unique across the whole table, invisible rows included.

    Creating a book whose ISBN belongs to somebody else's private one raises on
    that index, and the raise is two problems at once: it aborts the
    transaction, so the whole import silently writes nothing, and the 500
    against a 200 is a clean oracle for "does this house hold this ISBN",
    which is exactly what the 404-not-403 rule withholds.
    """

    ISBN = "9780441013593"

    def test_the_import_still_succeeds(self, client, admin, member, make_book):
        make_book(admin["headers"], isbn=self.ISBN, title="Diary", is_private=True)

        res = upload(
            client,
            member["headers"],
            csv_bytes(goodreads_row("Something", "read", f'="{self.ISBN}"')),
            create_missing=True,
        )

        assert res.status_code == 200

    def test_the_rest_of_the_file_is_still_imported(
        self, client, admin, member, make_book, db
    ):
        """One unusable row must not cost the other four thousand."""
        make_book(admin["headers"], isbn=self.ISBN, title="Diary", is_private=True)

        res = upload(
            client,
            member["headers"],
            csv_bytes(
                goodreads_row("Blocked", "read", f'="{self.ISBN}"'),
                goodreads_row("Fine", "read"),
            ),
            create_missing=True,
        )

        assert res.json()["created"] == 1
        assert {book.title for book in db.query(Book).all()} == {"Diary", "Fine"}

    def test_the_title_is_not_reported_back(self, client, admin, member, make_book):
        """Naming it would disclose the row the caller may not see."""
        make_book(admin["headers"], isbn=self.ISBN, title="Diary", is_private=True)

        body = upload(
            client,
            member["headers"],
            csv_bytes(goodreads_row("Blocked", "read", f'="{self.ISBN}"')),
            create_missing=True,
        ).json()

        assert body["unmatched_titles"] == []
        assert body["skipped"] == 1

    def test_the_private_book_is_untouched(self, client, admin, member, make_book, db):
        make_book(admin["headers"], isbn=self.ISBN, title="Diary", is_private=True)

        upload(
            client,
            member["headers"],
            csv_bytes(goodreads_row("Blocked", "read", f'="{self.ISBN}"')),
            create_missing=True,
        )

        assert db.query(Book).filter(Book.isbn == self.ISBN).one().title == "Diary"


class TestTagLimits:
    """Measured: 200 rows of one title created 4032 library wide tags."""

    def _rows(self, count: int, per_row: int = 5) -> bytes:
        rows = []
        for index in range(count):
            tags = ";".join(f"tag{index}-{n}" for n in range(per_row))
            rows.append(
                f'1,"Book {index}","An Author",="",="",0,Pub,300,2000,,"{tags}",read'
            )
        return csv_bytes(*rows)

    def test_one_file_cannot_invent_unlimited_tags(self, client, admin, db):
        from models import Tag

        before = db.query(Tag).count()

        upload(
            client,
            admin["headers"],
            self._rows(100),
            create_missing=True,
            apply_tags=True,
        )

        db.expire_all()
        invented = db.query(Tag).count() - before
        assert invented <= csv_import.MAX_NEW_TAGS_PER_IMPORT

    def test_the_books_still_arrive_when_the_cap_is_reached(self, client, admin):
        """The cap stops inventing rather than failing: the books are the point."""
        res = upload(
            client,
            admin["headers"],
            self._rows(100),
            create_missing=True,
            apply_tags=True,
        )
        assert res.json()["created"] == 100

    def test_one_book_cannot_collect_unlimited_tags(self, client, admin):
        many = ";".join(f"tag{n}" for n in range(60))
        upload(
            client,
            admin["headers"],
            csv_bytes(
                f'1,"Solo","An Author",="",="",0,Pub,300,2000,,"{many}",read'
            ),
            create_missing=True,
            apply_tags=True,
        )

        [book] = items(client.get("/api/books", headers=admin["headers"]))
        assert len(book["tags"]) <= csv_import.MAX_TAGS_PER_BOOK

    def test_two_tags_sharing_a_long_prefix_do_not_collide(self, client, admin):
        """Truncating at the insert but not at the lookup violated the unique
        index on the second one, and took the whole import with it."""
        long_a = "x" * 99 + "a"
        long_b = "x" * 99 + "b"
        res = upload(
            client,
            admin["headers"],
            csv_bytes(
                f'1,"One","An Author",="",="",0,Pub,300,2000,,"{long_a}",read',
                f'2,"Two","An Author",="",="",0,Pub,300,2000,,"{long_b}",read',
            ),
            create_missing=True,
            apply_tags=True,
        )
        assert res.status_code == 200

    def test_tags_are_left_alone_by_default(self, client, admin, db):
        from models import Tag

        before = db.query(Tag).count()
        upload(client, admin["headers"], self._rows(5), create_missing=True)

        db.expire_all()
        assert db.query(Tag).count() == before


REVIEW_CSV = (
    b'Title,Author,Exclusive Shelf,My Review\n'
    b'Dune,An Author,read,"A desert planet."\n'
)


class TestImportedReviews:
    def test_a_review_becomes_this_member_s_note(self, client, admin):
        """Parsed all along and thrown away, like the rating used to be."""
        upload(client, admin["headers"], REVIEW_CSV, create_missing=True)

        [book] = items(client.get("/api/books", headers=admin["headers"]))
        notes = client.get(
            f"/api/books/{book['id']}/notes", headers=admin["headers"]
        ).json()
        assert [note["content"] for note in notes] == ["A desert planet."]

    def test_the_note_it_writes_is_private(self, client, admin):
        """The whole of the owner's decision, in one field. `private notes` is
        one of the header names this review is read from, so the column another
        app called private must not arrive here as an instance-visible note
        under the importing member's own name."""
        upload(client, admin["headers"], REVIEW_CSV, create_missing=True)

        [book] = items(client.get("/api/books", headers=admin["headers"]))
        notes = client.get(
            f"/api/books/{book['id']}/notes", headers=admin["headers"]
        ).json()
        assert [note["is_private"] for note in notes] == [True]

    def test_nobody_else_can_read_it(self, client, admin, member):
        """The same claim from the other side, over the wire rather than off a
        field, because the field is only worth what the listing does with it."""
        upload(client, admin["headers"], REVIEW_CSV, create_missing=True)

        [book] = items(client.get("/api/books", headers=member["headers"]))
        notes = client.get(
            f"/api/books/{book['id']}/notes", headers=member["headers"]
        ).json()
        assert notes == []

    def test_importing_twice_does_not_append_it_again(self, client, admin):
        upload(client, admin["headers"], REVIEW_CSV, create_missing=True)
        upload(client, admin["headers"], REVIEW_CSV, create_missing=True)

        [book] = items(client.get("/api/books", headers=admin["headers"]))
        notes = client.get(
            f"/api/books/{book['id']}/notes", headers=admin["headers"]
        ).json()
        assert len(notes) == 1


class TestRateLimit:
    def test_a_burst_of_imports_is_refused(self, client, admin):
        """One import holds the single SQLite writer for its whole duration."""
        content = csv_bytes(goodreads_row("Dune", "read"))
        codes = [
            upload(client, admin["headers"], content).status_code for _ in range(5)
        ]

        assert 429 in codes

    def test_the_refusal_says_when_to_try_again(self, client, admin):
        content = csv_bytes(goodreads_row("Dune", "read"))
        last = None
        for _ in range(5):
            last = upload(client, admin["headers"], content)
        assert last is not None
        if last.status_code == 429:
            assert "Retry-After" in last.headers


class TestUnreadableFile:
    def test_a_field_too_large_is_a_400_not_a_500(self, client, admin):
        """Python's csv module raises past 128k in one field."""
        huge = "x" * 200_000
        res = upload(client, admin["headers"], f'Title,Author\n"{huge}",X\n'.encode())

        assert res.status_code == 400


# ── The round trip ────────────────────────────────────────────────────────────

#: Which importer field each export column fills.
#:
#: Checked against the live export header rather than a fixture, so a column
#: renamed in `routers/books.py` fails here rather than drifting quietly.
_ROUND_TRIPPED: dict[str, str] = {
    "Title": "title",
    "Author": "author",
    "ISBN": "isbn",
    "Publisher": "publisher",
    "Year": "year",
    "Tags": "tags",
    "My Status": "status",
    "Format": "format",
}

#: Export columns the importer does not read, and why each one.
#:
#: A reason per column, because "there is no field for this" and "there is a
#: field and this is not it" are different answers, and only the second is a
#: defect waiting to happen.
_NOT_READ_BACK: dict[str, str] = {
    "Description": "the book's blurb. `notes` is the member's own review, not this",
    "Date Added": "when this library got the book, not when anybody read it",
    "Added By": "a username in this deployment, and meaningless in another",
    "Condition": "no importer field",
    "Location": "a shelf in this house, and no importer field",
    "Collection": "no importer field. `docs/decisions.md`: not an import option",
    "Purchase Price": "no importer field",
    "Purchase Currency": "no importer field",
    "Purchased On": "no importer field",
    "Purchased From": "no importer field",
}

#: Importer fields the export writes no column for.
_NOT_EXPORTED: dict[str, str] = {
    "isbn13": "the export writes one ISBN column, and `isbn` reads it",
    "rating": "the export carries no rating column",
    "date_read": "the export carries no date read column",
    "pages": "the export carries no page count column",
    "notes": "`docs/api.md`: notes, quotes and loans are not in the CSV",
}


class TestEndpapersOwnExportSurvivesItsOwnImporter:
    """The join between `GET /api/books/export` and this router.

    Both halves are in this repository, both were tested, and the pair was not,
    so each was free to be individually correct and jointly lossy. It was: the
    export wrote `My Status`, no candidate named it, and a library exported and
    imported back came home unread.

    The three tables above are the half that stops it returning. Every column
    of the live export is in exactly one of the first two, and every field of
    `COLUMN_GUESSES` is in exactly one of the first and third, so a column or a
    field added to either side fails here until somebody says which it is.
    """

    ISBN = "9780156027601"

    def _library(self, client, headers, make_book) -> dict:
        """One book with every column of the export filled in."""
        book = make_book(
            headers,
            title="Solaris",
            author="Stanislaw Lem",
            isbn=self.ISBN,
            publisher="Harcourt",
            year=1970,
            description="An ocean that thinks.",
            format="paperback",
            location="Shelf 2",
        )
        collection = client.post(
            "/api/collections", json={"name": "Ebooks"}, headers=headers
        ).json()
        client.patch(
            f"/api/books/{book['id']}/collection",
            json={"collection_id": collection["id"]},
            headers=headers,
        )
        for name in ("sci-fi", "translated"):
            tag = client.post("/api/books/tags", json={"name": name}, headers=headers)
            client.post(
                f"/api/books/{book['id']}/tags/{tag.json()['id']}", headers=headers
            )
        client.patch(
            f"/api/books/{book['id']}",
            json={
                "condition": "good",
                "purchase_price_minor": 1200,
                "purchase_currency": "EUR",
                "purchased_at": "2026-01-05",
                "purchase_source": "a shop",
            },
            headers=headers,
        )
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=headers
        )
        return book

    def _export(self, client, headers) -> bytes:
        res = client.get("/api/books/export", headers=headers)
        assert res.status_code == 200, res.text
        return res.content

    def test_every_export_column_is_read_back_or_named_as_not_read(
        self, client, admin, make_book
    ):
        make_book(admin["headers"])
        export = self._export(client, admin["headers"])
        header = next(csv.reader(io.StringIO(export.decode())))

        assert not set(_ROUND_TRIPPED) & set(_NOT_READ_BACK)
        assert sorted(header) == sorted(set(_ROUND_TRIPPED) | set(_NOT_READ_BACK))

    def test_the_importer_reads_each_column_into_the_field_named_here(
        self, client, admin, make_book
    ):
        """The pairing, which the partition above does not check.

        That one compares a set of column names against a set of field names,
        so two rows of `_ROUND_TRIPPED` could swap their fields and stay green.
        This asks the parser what it actually did with the live header row.
        """
        make_book(admin["headers"])
        export = self._export(client, admin["headers"])

        mapping = csv_import.parse(export).mapping

        assert {header: field for field, header in mapping.items() if header} == (
            _ROUND_TRIPPED
        )

    def test_every_importer_field_is_filled_by_the_export_or_named_as_absent(self):
        filled = list(_ROUND_TRIPPED.values())

        assert sorted(filled) == sorted(set(filled))
        assert sorted(field for field, _ in csv_import.COLUMN_GUESSES) == sorted(
            set(filled) | set(_NOT_EXPORTED)
        )

    def test_a_book_carrying_every_exported_field_comes_back_unchanged(
        self, client, admin, make_book
    ):
        """One assertion over the whole row, so a field that quietly stops
        arriving cannot hide behind the ones that still do."""
        self._library(client, admin["headers"], make_book)

        [row] = csv_import.parse(self._export(client, admin["headers"])).rows

        assert dataclasses.replace(row, tags=sorted(row.tags)) == csv_import.ImportRow(
            title="Solaris",
            author="Stanislaw Lem",
            isbn=self.ISBN,
            status=ReadStatus.READ,
            rating=None,
            date_read=None,
            publisher="Harcourt",
            year=1970,
            pages=None,
            format=BookFormat.PAPERBACK,
            tags=["sci-fi", "translated"],
            notes=None,
        )

    def test_a_title_a_spreadsheet_would_run_comes_back_neutralised(
        self, client, admin, make_book
    ):
        """The one cell the export deliberately does not round trip.

        `_csv_safe` prefixes an apostrophe to anything a spreadsheet would
        execute, so for these titles the round trip is not an identity and must
        not become one: an importer that stripped the apostrophe to make this
        test prettier would hand the formula straight back. Asserted here
        rather than avoided, because the equality test above uses a title that
        never reaches the guard.
        """
        make_book(admin["headers"], title='=HYPERLINK("http://evil.test","ok")')

        [row] = csv_import.parse(self._export(client, admin["headers"])).rows

        assert row.title == '\'=HYPERLINK("http://evil.test","ok")'

    def test_the_guard_applied_to_its_own_output_does_not_grow_the_cell(
        self, client, admin, make_book
    ):
        """Otherwise a shelf exported and imported often enough grows a margin
        of apostrophes."""
        make_book(admin["headers"], title="'=already quoted")

        [row] = csv_import.parse(self._export(client, admin["headers"])).rows

        assert row.title == "'=already quoted"

    def test_a_status_crosses_both_routes_and_lands_on_the_importers_shelf(
        self, client, admin, member, make_book, db
    ):
        """The parser is not the deliverable. Both routes are, end to end."""
        book = self._library(client, admin["headers"], make_book)

        res = upload(client, member["headers"], self._export(client, admin["headers"]))

        assert res.status_code == 200, res.text
        mine = (
            db.query(UserBook)
            .filter(
                UserBook.book_id == book["id"],
                UserBook.user_id == member["user"]["id"],
            )
            .one()
        )
        assert mine.status == ReadStatus.READ


#: Amazon's Kindle document listing, header quoted in `tests/test_csv_import.py`
#: from a real 2022 export. One row the member deleted at the source and one
#: they did not, so every assertion below is on the flag rather than on a count.
KINDLE = (
    b"DocumentId,Title,DocumentProvider,HasBeenDeleted,EntryCreationDate\n"
    b"AAAA,Solaris,Stanislaw Lem,true,2019-01-01\n"
    b"BBBB,Roadside Picnic,Arkady Strugatsky,false,2019-01-02\n"
)


class TestATitleTheMemberDeletedAtTheSourceDoesNotComeBack:
    """The half of the import that changes what a member sees.

    A row exclusion names no field, so it cannot be a candidate header name
    under any spelling, and the mapping's only row filter was: no title, so
    skip. Left unread, `HasBeenDeleted` did nothing, and the book was then
    created **visible to everyone on the instance**, because nothing on this
    path sets `is_private` and `Book.is_private` defaults to false.

    **It is the generic mapping's rule and no reader's**, so nothing here rests
    on recognising whose export this is.

    Tested through the route rather than at the parser, because that sentence
    about visibility is about a row in the database and not about a parsed row.
    """

    def test_no_book_is_created_for_it(self, client, admin, db):
        res = client.post(
            "/api/imports/csv",
            files={"file": ("Kindle.KindleDocs.DocumentMetadata.csv", KINDLE, "text/csv")},
            headers=admin["headers"],
            params={"create_missing": True},
        )

        assert res.status_code == 200, res.text
        assert [book.title for book in db.query(Book).all()] == ["Roadside Picnic"]

    def test_and_it_is_absent_rather_than_private(self, client, admin, db):
        """The narrower fix would have been to create it and hide it, and it is
        not what the member said. They deleted it.

        Asserted as a count over the whole table, so a Book created private
        would fail here as loudly as a Book created visible.
        """
        client.post(
            "/api/imports/csv",
            files={"file": ("Kindle.KindleDocs.DocumentMetadata.csv", KINDLE, "text/csv")},
            headers=admin["headers"],
            params={"create_missing": True},
        )

        assert db.query(Book).filter(Book.title == "Solaris").count() == 0

    def test_the_result_says_how_many_rows_the_file_itself_refused(self, client, admin):
        """A member who exported 400 titles and imported 380 is owed the other
        twenty, and this number is read off their own upload, so unlike
        `skipped` it discloses nothing about the instance."""
        res = client.post(
            "/api/imports/csv",
            files={"file": ("Kindle.KindleDocs.DocumentMetadata.csv", KINDLE, "text/csv")},
            headers=admin["headers"],
            params={"create_missing": True},
        )

        body = res.json()
        assert (body["excluded"], body["created"], body["skipped"]) == (1, 1, 0)

    def test_the_preview_says_it_before_anything_is_written(self, client, admin, db):
        """Which reader ran and what it will drop, both on the screen that
        exists so a wrong reading is caught before the write."""
        res = client.post(
            "/api/imports/preview",
            files={"file": ("Kindle.KindleDocs.DocumentMetadata.csv", KINDLE, "text/csv")},
            headers=admin["headers"],
        )

        body = res.json()
        assert (body["reader"], body["excluded"], body["total_rows"]) == ("generic", 1, 1)
        assert body["exclusion_column"] == "HasBeenDeleted"
        assert db.query(Book).count() == 0

    def test_an_ordinary_export_is_read_generically_and_excludes_nothing(
        self, client, admin
    ):
        """The other half of the diagonal: the assertions above pass on a route
        that answered `excluded` for every file."""
        res = client.post(
            "/api/imports/preview",
            files={"file": ("goodreads.csv", csv_bytes(goodreads_row("Dune", "read")), "text/csv")},
            headers=admin["headers"],
        )

        body = res.json()
        assert (body["reader"], body["excluded"]) == ("generic", 0)
        assert body["exclusion_column"] is None
