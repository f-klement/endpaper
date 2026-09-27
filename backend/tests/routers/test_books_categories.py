"""Subjects posted with a book: stored whole, joined into one column, minted from never.

The column is one delimited string and the request is a list, so this is the one
field of the create body whose request shape is not its stored shape. Two things
are pinned here that no schema test can see: that the route **writes** what it
pops, since a pop with no write answers 201 and stores nothing, and that the
value reaches the column joined rather than as a list, which is an exception on
the INSERT rather than a validation error.
"""

from models import Book, Tag
from schemas import POPPED_BEFORE_THE_CONSTRUCTOR
from schemas.book import CATEGORY_MAX, MAX_CATEGORIES_PER_BOOK

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

        Not a producer argument: no reader emits a subject, so this door has no
        honest producer to argue about yet.
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
