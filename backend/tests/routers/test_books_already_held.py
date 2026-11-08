"""Whether a member already has the record they are about to save.

The scan card asks this before the save, so a duplicate is seen before the
press; the add door's 409 stays the backstop. What is tested is how strong each
answer says it is, and that it never answers for a Book the asker cannot see.
"""

HELD = "/api/books/already-held"

DUNE = "9780441013593"
#: Another edition of `DUNE`, which shares its title and author only.
DUNE_ELSEWHERE = "9780340960196"


def held(client, headers, **params):
    res = client.get(HELD, params=params, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


class TestHowStrongTheAnswerIs:
    def test_the_same_isbn_is_an_isbn_match(self, client, member, make_book):
        book = make_book(member["headers"], title="Dune", author="Frank Herbert", isbn=DUNE)

        answer = held(client, member["headers"], title="Dune", isbn=DUNE)

        assert answer == {"match": "isbn", "book_ids": [book["id"]]}

    def test_only_the_title_and_author_is_a_title_author_match(self, client, member, make_book):
        book = make_book(member["headers"], title="Dune", author="Frank Herbert", isbn=DUNE)

        answer = held(client, member["headers"], title="Dune", author="Frank Herbert", isbn=DUNE_ELSEWHERE)

        assert answer == {"match": "title_author", "book_ids": [book["id"]]}

    def test_a_record_nobody_holds_matches_nothing(self, client, member, make_book):
        make_book(member["headers"], title="Dune", author="Frank Herbert", isbn=DUNE)

        answer = held(client, member["headers"], title="Small Gods", author="Terry Pratchett")

        assert answer == {"match": None, "book_ids": []}


class TestPrivacy:
    def test_another_members_private_book_answers_as_no_book_does(
        self, client, member, other_user, make_book
    ):
        """Same ISBN, title and author: the answer must be the one an empty
        library gives, or it says a private Book exists (ADR 0003)."""
        make_book(other_user["headers"], title="Dune", author="Frank Herbert", isbn=DUNE, is_private=True)

        answer = held(client, member["headers"], title="Dune", author="Frank Herbert", isbn=DUNE)

        assert answer == {"match": None, "book_ids": []}
