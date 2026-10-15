"""Which Books already hold a file, asked by location or by KOReader's digest.

The scan queue asks this before it adds anything, so a re-picked folder adds
nothing twice, and KOReader's progress sync will ask it to resolve a document.
What is tested is what the answer may say and to whom.
"""

from models import DIGITAL_REFERENCE_PATH_MAX
from schemas.digital import MAX_FILES_PER_LOOKUP

REPORT = "/api/books/{}/digital-references"
HOLDERS = "/api/books/file-holders"

DIGEST = "0123456789abcdef0123456789abcdef"
OTHER_DIGEST = "fedcba9876543210fedcba9876543210"


def report(client, headers, book_id, **fields):
    payload = {"root_label": "Books", "relative_path": "Le Guin/Dune.epub"} | fields
    return client.post(REPORT.format(book_id), json=payload, headers=headers)


def holders(client, headers, *files):
    return client.post(HOLDERS, json={"files": list(files)}, headers=headers)


def at(root="Books", path="Le Guin/Dune.epub", **extra):
    return {"root_label": root, "relative_path": path} | extra


class TestTheDigestIsStoredOnTheReference:
    def test_a_report_carries_the_digest_back(self, client, admin, make_book):
        book = make_book(admin["headers"])
        body = report(client, admin["headers"], book["id"], partial_md5=DIGEST).json()
        assert body["partial_md5"] == DIGEST

    def test_an_upper_case_digest_is_refused(self, client, admin, make_book):
        """KOReader writes it lower case, so an upper case spelling is a second
        value for one digest and would match nothing a device sends."""
        book = make_book(admin["headers"])
        res = report(client, admin["headers"], book["id"], partial_md5=DIGEST.upper())
        assert res.status_code == 422

    def test_a_report_without_a_digest_clears_the_one_stored(
        self, client, admin, make_book
    ):
        """The report replaces what one client saw in one look, digest included,
        for the reason it replaces the size and the modification time."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"], partial_md5=DIGEST)
        assert report(client, admin["headers"], book["id"]).json()["partial_md5"] is None


class TestWhichBooksHoldAFile:
    def test_a_file_at_a_known_location_names_its_book(self, client, admin, make_book):
        book = make_book(admin["headers"])
        reference = report(client, admin["headers"], book["id"]).json()

        res = holders(client, admin["headers"], at())
        assert res.status_code == 200
        assert res.json() == [
            {
                "holders": [
                    {
                        "book_id": book["id"],
                        "reference_id": reference["id"],
                        "format": None,
                        "same_location": True,
                        "same_partial_md5": False,
                    }
                ]
            }
        ]

    def test_a_moved_file_is_found_by_its_digest(self, client, admin, make_book):
        """The case a location cannot answer: the bytes are the same and the
        path is not."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"], partial_md5=DIGEST)

        moved = at(path="Sorted/Dune.epub", partial_md5=DIGEST)
        [answer] = holders(client, admin["headers"], moved).json()
        assert [one["book_id"] for one in answer["holders"]] == [book["id"]]
        assert answer["holders"][0]["same_partial_md5"] is True
        assert answer["holders"][0]["same_location"] is False

    def test_a_digest_alone_is_a_question(self, client, admin, make_book):
        """What a KOReader device sends: a document digest and no path."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"], partial_md5=DIGEST)

        [answer] = holders(client, admin["headers"], {"partial_md5": DIGEST}).json()
        assert [one["book_id"] for one in answer["holders"]] == [book["id"]]

    def test_the_same_path_under_another_root_is_another_file(
        self, client, admin, make_book
    ):
        """The statement narrows on the path alone and the root is compared
        after it, so this is the case that comparison exists for."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"])

        [answer] = holders(client, admin["headers"], at(root="Laptop")).json()
        assert answer == {"holders": []}

    def test_each_answer_is_in_the_place_its_file_was_asked(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"], partial_md5=DIGEST)

        answers = holders(
            client,
            admin["headers"],
            {"partial_md5": OTHER_DIGEST},
            at(),
        ).json()
        assert [len(answer["holders"]) for answer in answers] == [0, 1]

    def test_a_reference_matching_both_keys_is_one_holder(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"], partial_md5=DIGEST)

        [answer] = holders(client, admin["headers"], at(partial_md5=DIGEST)).json()
        assert len(answer["holders"]) == 1
        assert answer["holders"][0]["same_location"] is True
        assert answer["holders"][0]["same_partial_md5"] is True


class TestABookTheCallerCannotSeeHoldsNothing:
    def test_a_private_book_answers_exactly_as_no_book_does(
        self, client, member, other_user, make_book
    ):
        """**The leak this route must never make**, and the test that goes red if
        the lookup stops starting from the Shelf. A holder here would confirm
        that another member privately holds this exact file."""
        theirs = make_book(member["headers"], is_private=True)
        report(client, member["headers"], theirs["id"], partial_md5=DIGEST)

        hidden = holders(client, other_user["headers"], at(partial_md5=DIGEST))
        unknown = holders(
            client, other_user["headers"], at(path="Nowhere.epub", partial_md5=OTHER_DIGEST)
        )
        assert hidden.status_code == unknown.status_code == 200
        assert hidden.json() == unknown.json() == [{"holders": []}]

    def test_a_book_in_the_trash_holds_nothing(self, client, admin, make_book):
        """A trashed book is off the shelf, so its file is not "already in the
        library" and a re-pick adds it again rather than reporting onto it."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"], partial_md5=DIGEST)
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        [answer] = holders(client, admin["headers"], at(partial_md5=DIGEST)).json()
        assert answer == {"holders": []}

    def test_it_takes_a_session(self, client):
        assert client.post(HOLDERS, json={"files": [at()]}).status_code == 401


class TestTheQuestionIsBounded:
    def test_one_file_past_the_batch_is_refused(self, client, admin):
        files = [at(path=f"{index}.epub") for index in range(MAX_FILES_PER_LOOKUP + 1)]
        assert holders(client, admin["headers"], *files).status_code == 422

    def test_the_batch_exactly_is_answered(self, client, admin):
        files = [at(path=f"{index}.epub") for index in range(MAX_FILES_PER_LOOKUP)]
        res = holders(client, admin["headers"], *files)
        assert res.status_code == 200
        assert len(res.json()) == MAX_FILES_PER_LOOKUP

    def test_a_file_named_by_nothing_is_refused(self, client, admin):
        assert holders(client, admin["headers"], {}).status_code == 422

    def test_a_nul_in_a_path_is_refused(self, client, admin):
        """A 422 rather than whatever the engine makes of it: PostgreSQL's
        driver refuses a NUL in a text parameter, which would be a 500."""
        res = holders(client, admin["headers"], at(path="Dune\x00.epub"))
        assert res.status_code == 422

    def test_a_pair_past_the_path_budget_is_refused(self, client, admin):
        half = DIGITAL_REFERENCE_PATH_MAX // 2 + 1
        res = holders(client, admin["headers"], at(root="a" * half, path="b" * half))
        assert res.status_code == 422

    def test_half_a_location_is_refused(self, client, admin):
        res = holders(client, admin["headers"], {"relative_path": "Dune.epub"})
        assert res.status_code == 422
