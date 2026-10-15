"""Re-picking a folder: the references under its root, and the sweep of them.

A folder pick knows which files it holds now. The listing says which it was
said to hold before, and the sweep records the difference: a file still there
is a sighting, a file gone is a miss, and a miss never deletes the row.
"""

from datetime import timedelta

from models import DigitalReference
from schemas.digital import MAX_FILES_PER_LOOKUP

REPORT = "/api/books/{}/digital-references"
UNDER = "/api/books/digital-references"
SWEEP = "/api/books/digital-references/sweep"

DIGEST = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"


def report(client, headers, book_id, root="Books", path="Le Guin/Dune.epub", **fields):
    payload = {"root_label": root, "relative_path": path, "root_confirmed": True} | fields
    res = client.post(REPORT.format(book_id), json=payload, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def under(client, headers, root="Books", **params):
    return client.get(UNDER, params={"root_label": root, **params}, headers=headers)


def sweep(client, headers, root="Books", seen=(), missing=()):
    return client.post(
        SWEEP,
        json={"root_label": root, "seen": list(seen), "missing": list(missing)},
        headers=headers,
    )


def stored(client, headers, book_id):
    return client.get(REPORT.format(book_id), headers=headers).json()


class TestTheReferencesUnderARoot:
    def test_only_references_under_the_root_are_listed(self, client, admin, make_book):
        book = make_book(admin["headers"])
        here = report(client, admin["headers"], book["id"])
        report(client, admin["headers"], book["id"], root="Laptop")

        body = under(client, admin["headers"]).json()
        assert [row["id"] for row in body["items"]] == [here["id"]]
        assert body["total"] == 1

    def test_a_private_book_of_another_member_lists_nothing(
        self, client, member, other_user, make_book
    ):
        theirs = make_book(member["headers"], is_private=True)
        report(client, member["headers"], theirs["id"])

        body = under(client, other_user["headers"]).json()
        assert body == {"items": [], "total": 0, "page": 1, "page_size": body["page_size"]}

    def test_the_listing_is_paginated(self, client, admin, make_book):
        book = make_book(admin["headers"])
        for index in range(3):
            report(client, admin["headers"], book["id"], path=f"{index}.epub")

        body = under(client, admin["headers"], page_size=2, page=2).json()
        assert body["total"] == 3
        assert len(body["items"]) == 1

    def test_a_nul_in_the_root_is_refused(self, client, admin):
        """A 422 rather than whatever the engine makes of it."""
        assert under(client, admin["headers"], root="Bo\x00oks").status_code == 422

    def test_it_takes_a_session(self, client):
        assert client.get(UNDER, params={"root_label": "Books"}).status_code == 401


class TestASweepRecordsWhatThePickFound:
    def test_a_file_that_is_gone_is_flagged_and_kept(self, client, admin, make_book):
        book = make_book(admin["headers"])
        gone = report(client, admin["headers"], book["id"])

        res = sweep(client, admin["headers"], missing=[gone["id"]])
        assert res.json() == {"seen": [], "missing": [gone["id"]]}
        [row] = stored(client, admin["headers"], book["id"])
        assert row["missing_since"] is not None

    def test_a_file_still_there_clears_the_flag_and_takes_the_fingerprint(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        there = report(client, admin["headers"], book["id"])
        sweep(client, admin["headers"], missing=[there["id"]])

        sighting = {"reference_id": there["id"], "size_bytes": 7, "partial_md5": DIGEST}
        res = sweep(client, admin["headers"], seen=[sighting])
        assert res.json() == {"seen": [there["id"]], "missing": []}
        [row] = stored(client, admin["headers"], book["id"])
        assert row["missing_since"] is None
        assert (row["size_bytes"], row["partial_md5"]) == (7, DIGEST)

    def test_a_reference_under_another_root_is_not_written(
        self, client, admin, make_book
    ):
        """A sweep is one folder's account of itself."""
        book = make_book(admin["headers"])
        elsewhere = report(client, admin["headers"], book["id"], root="Laptop")

        res = sweep(client, admin["headers"], missing=[elsewhere["id"]])
        assert res.json() == {"seen": [], "missing": []}
        [row] = stored(client, admin["headers"], book["id"])
        assert row["missing_since"] is None


    def test_a_sighting_beats_a_miss_naming_the_same_reference(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        both = report(client, admin["headers"], book["id"])

        sighting = {"reference_id": both["id"]}
        res = sweep(client, admin["headers"], seen=[sighting], missing=[both["id"]])
        assert res.json() == {"seen": [both["id"]], "missing": []}
        [row] = stored(client, admin["headers"], book["id"])
        assert row["missing_since"] is None

    def test_a_sighting_confirms_the_root(self, client, admin, make_book):
        """A folder pick is a browser corroborating the structure under it."""
        book = make_book(admin["headers"])
        unconfirmed = report(client, admin["headers"], book["id"], root_confirmed=False)

        sweep(client, admin["headers"], seen=[{"reference_id": unconfirmed["id"]}])
        [row] = stored(client, admin["headers"], book["id"])
        assert row["root_confirmed"] is True

    def test_a_second_miss_keeps_the_first_time(self, client, admin, make_book, db):
        book = make_book(admin["headers"])
        gone = report(client, admin["headers"], book["id"])
        sweep(client, admin["headers"], missing=[gone["id"]])
        row = db.query(DigitalReference).filter(DigitalReference.id == gone["id"]).one()
        row.missing_since = row.missing_since - timedelta(days=3)
        db.commit()
        first = stored(client, admin["headers"], book["id"])[0]["missing_since"]

        sweep(client, admin["headers"], missing=[gone["id"]])
        assert stored(client, admin["headers"], book["id"])[0]["missing_since"] == first


class TestASightingNeverRewritesAnotherLook:
    """A root is only a folder name, so the same path under it can be two
    members' different files. A sighting adds a fingerprint where none was
    recorded and leaves a different one alone."""

    def test_a_different_fingerprint_is_kept(self, client, admin, make_book):
        book = make_book(admin["headers"])
        theirs = report(client, admin["headers"], book["id"], size_bytes=7, partial_md5=DIGEST)

        sighting = {"reference_id": theirs["id"], "size_bytes": 9, "partial_md5": OTHER}
        res = sweep(client, admin["headers"], seen=[sighting])
        assert res.json()["seen"] == [theirs["id"]]
        [row] = stored(client, admin["headers"], book["id"])
        assert (row["size_bytes"], row["partial_md5"]) == (7, DIGEST)

    def test_a_fingerprint_missing_a_half_is_filled_in(self, client, admin, make_book):
        book = make_book(admin["headers"])
        older = report(client, admin["headers"], book["id"], size_bytes=7)

        sighting = {"reference_id": older["id"], "size_bytes": 7, "partial_md5": DIGEST}
        sweep(client, admin["headers"], seen=[sighting])
        [row] = stored(client, admin["headers"], book["id"])
        assert (row["size_bytes"], row["partial_md5"]) == (7, DIGEST)


class TestOnlyAMemberWhoMayWriteTheBookFlagsIt:
    def test_a_private_book_of_another_member_is_not_flagged(
        self, client, member, other_user, make_book
    ):
        """Who may flag is who may write the Book, and a private Book of another
        member is neither visible nor writable to the caller. Its id answers as
        an id that does not exist."""
        theirs = make_book(member["headers"], is_private=True)
        reference = report(client, member["headers"], theirs["id"])

        res = sweep(client, other_user["headers"], missing=[reference["id"]])
        assert res.status_code == 200
        assert res.json() == {"seen": [], "missing": []}
        [row] = stored(client, member["headers"], theirs["id"])
        assert row["missing_since"] is None

    def test_a_public_book_somebody_else_added_is_flagged(
        self, client, admin, member, make_book
    ):
        """`book_for_write`'s rule: a public Book is a shared shelf."""
        theirs = make_book(member["headers"])
        reference = report(client, member["headers"], theirs["id"])

        res = sweep(client, admin["headers"], missing=[reference["id"]])
        assert res.json()["missing"] == [reference["id"]]


class TestTheSweepIsBounded:
    def test_one_reference_past_the_batch_is_refused(self, client, admin):
        ids = list(range(1, MAX_FILES_PER_LOOKUP + 2))
        assert sweep(client, admin["headers"], missing=ids).status_code == 422

    def test_a_sweep_naming_nothing_is_refused(self, client, admin):
        assert sweep(client, admin["headers"]).status_code == 422

    def test_it_takes_a_session(self, client):
        assert client.post(SWEEP, json={"root_label": "Books", "missing": [1]}).status_code == 401
