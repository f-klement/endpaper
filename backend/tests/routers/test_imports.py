"""Tests for backend/routers/imports.py: importing a library export.

The Goodreads shape is used throughout because it is the one most people
arrive with and the one with the awkward parts (formula-wrapped ISBNs, a status
column that is not the tag column). Every other service's shape is covered at
the parser, in `tests/test_csv_import.py`.
"""

import csv_import
from enums import ReadStatus
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
    """Measured: 200 rows of one title created 4032 household-wide tags."""

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
