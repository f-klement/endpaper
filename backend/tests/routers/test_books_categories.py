"""Subjects posted with a book: stored whole, joined into one column, minted from never.

The column is one delimited string and the request is a list, so this is the one
field of the create body whose request shape is not its stored shape. Two things
are pinned here that no schema test can see: that the route **writes** what it
pops, since a pop with no write answers 201 and stores nothing, and that the
value reaches the column joined rather than as a list, which is an exception on
the INSERT rather than a validation error.
"""

from models import Book, Tag
from schemas import POPPED_BEFORE_THE_ASSIGNMENT, POPPED_BEFORE_THE_CONSTRUCTOR
from schemas.book import (
    CATEGORY_MAX,
    MAX_CATEGORIES_PER_BOOK,
    BookCreate,
    BookDetailsUpdate,
)

SUBJECTS = ["Science Fiction", "Dystopia"]


def stored(book_id: int, db) -> str | None:
    """The column as the database holds it, not as a payload serves it."""
    return db.query(Book.categories).filter(Book.id == book_id).scalar()


class TestAddingABookWithSubjects:
    def test_a_subject_list_posted_with_a_book_is_stored(self, client, admin, db):
        res = client.post(
            "/api/books",
            json={"title": "Brave New World", "categories": SUBJECTS},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["categories"] == SUBJECTS

    def test_the_route_writes_the_field_it_popped(self, client, admin, db):
        """The arm a pop with no write fails, and nothing else here can see it.

        `categories` is popped before the constructor because its stored shape is
        one joined string. A pop that is not paired with an assignment answers
        201 with the field echoed by nothing and the column left null, so this
        reads the column rather than the response.
        """
        res = client.post(
            "/api/books",
            json={"title": "Brave New World", "categories": SUBJECTS},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert stored(res.json()["id"], db) == "Science Fiction; Dystopia"

    def test_a_book_added_without_any_stores_a_null_rather_than_an_empty_string(
        self, client, admin, db
    ):
        """A stored empty string reads back as no subjects and sorts differently
        from a row that never had any, so the default has to reach the column as
        a null."""
        res = client.post(
            "/api/books", json={"title": "Untagged"}, headers=admin["headers"]
        )

        assert res.status_code == 201
        assert stored(res.json()["id"], db) is None
        assert res.json()["categories"] == []

    def test_a_subject_carrying_the_separator_is_refused(self, client, admin):
        """Refused rather than split, because the value is unrepresentable in this
        column: it is stored joined on that character, so a stored subject carrying
        one is served back as two to every reader.

        Not a producer argument, and it stopped being available as one: four file
        readers emit a subject now, and what keeps this refusal off an honest
        client is their browser side bound dropping such an entry rather than the
        absence of a producer. The refusal here is about the value, which is why
        it did not have to move when the producers arrived.
        """
        res = client.post(
            "/api/books",
            json={"title": "Brave New World", "categories": ["Fiction; general"]},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_a_subject_list_past_the_count_is_refused(self, client, admin):
        # Read off the constant rather than retyped, so narrowing the bound leaves
        # this on the boundary instead of leaving it green and past it.
        res = client.post(
            "/api/books",
            json={
                "title": "Brave New World",
                "categories": ["x"] * (MAX_CATEGORIES_PER_BOOK + 1),
            },
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_one_subject_past_the_entry_width_is_refused(self, client, admin):
        res = client.post(
            "/api/books",
            json={"title": "Brave New World", "categories": ["x" * (CATEGORY_MAX + 1)]},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_a_subject_is_normalised_rather_than_refused_for_its_spacing(
        self, client, admin, db
    ):
        """A run of spaces and a control character are a producer's noise rather
        than an assertion, so they are removed. Only the separator is refused."""
        res = client.post(
            "/api/books",
            json={"title": "Brave New World", "categories": ["  Science\x00  Fiction "]},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["categories"] == ["Science Fiction"]

    def test_a_blank_entry_between_two_subjects_drops_and_the_rest_survive(
        self, client, admin, db
    ):
        """An entry with nothing left after normalising is dropped, not
        refused and not kept as an empty member.

        **Mid list on purpose, not at an edge.** An arm placing the blank
        first or last is satisfied by a rule that abandons the whole list
        whenever any entry is blank, which is this repository's own lesson
        about six arms placing their mark at a string edge, one field over.
        The assertion is in two halves for the same reason: that the blank
        goes **and** that its neighbours stay.

        **Read off the column, because the response cannot show it.**
        `split_categories` drops an empty member on the way out, so a stored
        `"Science Fiction; ; Dystopia"` reads back through the payload exactly
        like the canonical value, and the column would carry a value no reader
        in either tree would call wrong.
        """
        res = client.post(
            "/api/books",
            json={
                "title": "Brave New World",
                "categories": ["Science Fiction", "  \x00 ", "Dystopia"],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201, res.text
        assert stored(res.json()["id"], db) == "Science Fiction; Dystopia"

    def test_the_subjects_a_member_sent_read_back_unchanged(
        self, client, admin, make_book
    ):
        """The round trip through the column, over the route rather than over the
        helpers.

        **This does not carry the refusal.** The subject here is separator free, so
        deleting the refusal leaves it green; what it shows is that normalisation
        and the join do not change an accepted value.
        """
        created = client.post(
            "/api/books",
            json={"title": "Brave New World", "categories": ["Fiction, general"]},
            headers=admin["headers"],
        ).json()

        res = client.get(f"/api/books/{created['id']}", headers=admin["headers"])

        assert res.json()["categories"] == ["Fiction, general"]

    def test_a_subject_spelled_like_a_curated_tag_still_mints_nothing(
        self, client, admin, db
    ):
        """The ruling: stored, never interpreted, and this is its sharpest case.

        "Science Fiction" is a **seeded** tag name, so a subject spelled exactly
        like one is where minting or matching would be tempting, and the second
        subject is in no vocabulary so a mint would be visible as a new row.

        **Counted either side of the post rather than against zero.** Against zero
        this arm measures the seed and passes or fails on it: the first version of
        it asserted no tag named "Science Fiction" existed and failed on a tree
        with nothing wrong with it.
        """
        before = db.query(Tag).count()

        res = client.post(
            "/api/books",
            json={
                "title": "Brave New World",
                "categories": ["Science Fiction", "Kitchen Sink Futurism"],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["tags"] == []
        assert db.query(Tag).count() == before
        assert db.query(Tag).filter(Tag.name == "Kitchen Sink Futurism").count() == 0

    def test_the_route_pops_the_reshaped_field_by_name(self):
        """The route loops one list rather than spelling a pop per name, so this
        is what refuses a field silently dropped out of it: without `categories`
        there, the constructor is handed a list and the INSERT fails."""
        assert "categories" in POPPED_BEFORE_THE_CONSTRUCTOR


class TestEditingTheSubjectsOfABookThatExists:
    """`PATCH /api/books/{id}`, which is the only route that removes a subject.

    The create route writes them, the catalogue gap fill and the merge's absorb
    add them, and `google_books.merge_into` skips an empty incoming value, so
    an overwriting enrich replaces and cannot clear. Before this door the only
    removal in the product was deleting the book, over a column
    `schemas/public.PublicBookOut` serves to a reader with no account.

    Read off the column rather than off the response, for the reason
    `test_the_route_writes_the_field_it_popped` gives one class up: a pop with
    no write answers 200 and stores nothing.
    """

    def _a_book_with_subjects(self, client, admin) -> int:
        res = client.post(
            "/api/books",
            json={"title": "Brave New World", "categories": SUBJECTS},
            headers=admin["headers"],
        )
        assert res.status_code == 201
        return int(res.json()["id"])

    def test_a_new_list_replaces_the_stored_one(self, client, admin, db):
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}",
            json={"categories": ["Satire"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert stored(book_id, db) == "Satire"

    def test_an_empty_list_clears_them(self, client, admin, db):
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}", json={"categories": []}, headers=admin["headers"]
        )

        assert res.status_code == 200, res.text
        assert res.json()["categories"] == []

    def test_a_cleared_column_holds_a_null_rather_than_an_empty_string(
        self, client, admin, db
    ):
        """The half the response cannot show. A hand rolled join at the route
        would store `""`, which reads back as no subjects and sorts apart from
        a row that never had any; `google_books.join_categories` answers `None`
        for an empty list, which is what the create door already stores."""
        book_id = self._a_book_with_subjects(client, admin)

        client.patch(
            f"/api/books/{book_id}", json={"categories": []}, headers=admin["headers"]
        )

        assert stored(book_id, db) is None

    def test_leaving_the_field_out_leaves_the_subjects_alone(self, client, admin, db):
        """Absent against empty, which is the whole of what makes this partial.
        A body that edits the title must not clear the subjects."""
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}", json={"title": "Island"}, headers=admin["headers"]
        )

        assert res.status_code == 200, res.text
        assert stored(book_id, db) == "Science Fiction; Dystopia"

    def test_a_null_is_refused_rather_than_taken_as_a_second_clear(
        self, client, admin
    ):
        """One act, one spelling. Every other field here clears on a null, so
        a caller will try it: a 422 says which spelling this column takes
        instead of accepting both and letting the two diverge."""
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}",
            json={"categories": None},
            headers=admin["headers"],
        )

        assert res.status_code == 422, res.text

    def test_a_subject_carrying_the_separator_is_refused_at_this_door_too(
        self, client, admin, db
    ):
        """The second door onto one column applies the same rule, because both
        validators call `schemas.book.normalised_subjects`. Stored unsplit it
        would read back as two subjects nobody asserted."""
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}",
            json={"categories": ["Fiction; general"]},
            headers=admin["headers"],
        )

        assert res.status_code == 422, res.text
        assert stored(book_id, db) == "Science Fiction; Dystopia"

    def test_a_list_past_the_count_is_refused_at_this_door_too(self, client, admin):
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}",
            json={"categories": [f"S{n}" for n in range(MAX_CATEGORIES_PER_BOOK + 1)]},
            headers=admin["headers"],
        )

        assert res.status_code == 422, res.text

    def test_one_subject_past_the_entry_width_is_refused_at_this_door_too(
        self, client, admin
    ):
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}",
            json={"categories": ["x" * (CATEGORY_MAX + 1)]},
            headers=admin["headers"],
        )

        assert res.status_code == 422, res.text

    def test_a_blank_entry_between_two_subjects_drops_at_this_door_too(
        self, client, admin, db
    ):
        """The same rule at the second door, and the same two halves.

        Both validators call one function, so this is the arm that says the
        second door gets the drop rather than a kept empty member. The reason
        it is mid list, and the reason it reads the column instead of the
        payload, are at the create door's twin.
        """
        book_id = self._a_book_with_subjects(client, admin)

        res = client.patch(
            f"/api/books/{book_id}",
            json={"categories": ["Satire", " \x00  ", "Utopia"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert stored(book_id, db) == "Satire; Utopia"

    def test_the_route_pops_the_reshaped_field_by_name(self):
        """The update route loops its own list, so this is what refuses a field
        silently dropped out of it: without `categories` there, the assignment
        loop hands a list to a `Text` column and the flush raises."""
        assert "categories" in POPPED_BEFORE_THE_ASSIGNMENT

    def test_the_two_doors_bound_the_field_the_same_way(self):
        """One column, two bodies. A width or a count that moved on one and not
        the other would let a value in at the door nobody re-read."""
        create = BookCreate.model_fields["categories"]
        update = BookDetailsUpdate.model_fields["categories"]

        assert create.annotation == update.annotation
        assert create.metadata == update.metadata
        assert create.metadata, "neither field states a bound, so this compares nothing"
