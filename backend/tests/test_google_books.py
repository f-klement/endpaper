"""Tests for backend/google_books.py.

The HTTP calls are intercepted with respx, so nothing here reaches Google. What
is worth pinning is the field mapping and, above all, the merge rule:
enrichment adds what is missing and does not overrule what a member typed.
"""

import httpx
import pytest
import respx

from google_books import (
    GoogleBooksError,
    _series_from_title,
    _volume_to_fields,
    lookup_by_isbn,
    merge_into,
    search,
)
from models import Book

VOLUMES = "https://www.googleapis.com/books/v1/volumes"

VOLUME = {
    "id": "gbid-123",
    "volumeInfo": {
        "title": "Dune",
        "subtitle": "A Novel",
        "authors": ["Frank Herbert"],
        "publisher": "Chilton",
        "publishedDate": "1965-08-01",
        "description": "A story of Arrakis.",
        "pageCount": 412,
        "language": "en",
        "categories": ["Fiction", "Science Fiction"],
        "imageLinks": {"thumbnail": "https://books.google.com/cover.jpg"},
        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780441013593"}],
    },
}


@pytest.fixture
def google():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


class TestFieldMapping:
    def test_maps_the_fields_worth_storing(self):
        fields = _volume_to_fields(VOLUME)

        assert fields["title"] == "Dune"
        assert fields["page_count"] == 412
        assert fields["language"] == "en"
        assert fields["google_books_id"] == "gbid-123"

    def test_a_plain_http_thumbnail_is_upgraded(self):
        """Google really does serve these over http, and the repository's own
        fixtures assumed https, so this was untested. An http image on an https
        page is mixed content and never renders."""
        volume = {
            "volumeInfo": {
                "imageLinks": {"thumbnail": "http://books.google.com/cover.jpg"}
            }
        }
        assert (
            _volume_to_fields(volume)["cover_url"]
            == "https://books.google.com/cover.jpg"
        )

    def test_a_thumbnail_no_image_tag_should_load_is_dropped(self):
        """A search result is rendered in an `<img>` long before anything is
        stored, so the preview path answers the same question the storage path
        does. Google will not send this; the point is that the answer does not
        depend on which side of the database the value is on."""
        volume = {"volumeInfo": {"imageLinks": {"thumbnail": "javascript:alert(1)"}}}
        assert _volume_to_fields(volume)["cover_url"] is None

    def test_an_https_thumbnail_is_left_alone(self):
        assert _volume_to_fields(VOLUME)["cover_url"] == "https://books.google.com/cover.jpg"

    def test_joins_several_authors(self):
        volume = {"volumeInfo": {"authors": ["Frank Herbert", "Brian Herbert"]}}
        assert _volume_to_fields(volume)["author"] == "Frank Herbert, Brian Herbert"

    def test_joins_categories_into_one_string(self):
        # Google's own subject list, not the curated Tag vocabulary.
        assert _volume_to_fields(VOLUME)["categories"] == "Fiction; Science Fiction"

    def test_extracts_the_year_from_a_partial_date(self):
        assert _volume_to_fields(VOLUME)["year"] == 1965

    def test_survives_a_volume_with_almost_nothing(self):
        # Google returns wildly uneven records; a sparse one must not raise.
        fields = _volume_to_fields({"id": "x", "volumeInfo": {}})
        assert fields["title"] is None
        assert fields["categories"] is None
        assert fields["year"] is None


class TestLookupByIsbn:
    async def test_returns_the_first_match(self, google):
        google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": [VOLUME]})
        )
        fields = await lookup_by_isbn("9780441013593", "key")
        assert fields is not None and fields["title"] == "Dune"

    async def test_returns_none_when_google_has_nothing(self, google):
        google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        assert await lookup_by_isbn("9780441013593", "key") is None

    async def test_an_invalid_isbn_is_not_looked_up_at_all(self, google):
        route = google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": [VOLUME]})
        )
        assert await lookup_by_isbn("9780441013594", "key") is None
        assert route.call_count == 0

    async def test_the_key_is_sent(self, google):
        route = google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": [VOLUME]})
        )
        await lookup_by_isbn("9780441013593", "secret-key")
        assert "key=secret-key" in str(route.calls[0].request.url)


class TestErrors:
    @pytest.mark.parametrize("status", [401, 403])
    async def test_a_rejected_key_says_so(self, google, status):
        # The admin can fix this, so the message names the cause.
        google.get(url__startswith=VOLUMES).mock(return_value=httpx.Response(status))
        with pytest.raises(GoogleBooksError, match="API key"):
            await lookup_by_isbn("9780441013593", "bad-key")

    async def test_rate_limiting_says_so(self, google):
        google.get(url__startswith=VOLUMES).mock(return_value=httpx.Response(429))
        with pytest.raises(GoogleBooksError, match="rate limiting"):
            await lookup_by_isbn("9780441013593", "key")

    async def test_any_other_failure_is_generic(self, google):
        google.get(url__startswith=VOLUMES).mock(return_value=httpx.Response(500))
        with pytest.raises(GoogleBooksError, match="not responding"):
            await lookup_by_isbn("9780441013593", "key")


class TestSearch:
    async def test_returns_candidates(self, google):
        google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": [VOLUME, VOLUME]})
        )
        assert len(await search("dune herbert", "key")) == 2

    async def test_respects_the_limit(self, google):
        google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": [VOLUME] * 10})
        )
        assert len(await search("dune", "key", limit=3)) == 3

    async def test_an_empty_query_makes_no_request(self, google):
        route = google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        assert await search("   ", "key") == []
        assert route.call_count == 0


class TestMergeInto:
    """The rule that matters: fill gaps, do not overrule people."""

    def test_fills_an_empty_field(self):
        book = Book(title="Dune", page_count=None)
        changed = merge_into(book, _volume_to_fields(VOLUME), overwrite=False)

        assert book.page_count == 412
        assert "page_count" in changed

    def test_leaves_an_existing_value_alone(self):
        # A member who corrected a value should not have Google undo it.
        book = Book(title="Dune", publisher="The edition I actually own")
        merge_into(book, _volume_to_fields(VOLUME), overwrite=False)

        assert book.publisher == "The edition I actually own"

    def test_overwrite_replaces_it_when_asked(self):
        book = Book(title="Dune", publisher="Wrong")
        merge_into(book, _volume_to_fields(VOLUME), overwrite=True)

        assert book.publisher == "Chilton"

    def test_reports_only_what_actually_changed(self):
        # Enrichment often finds a volume and has nothing to add; saying
        # "done" would look like a no-op bug.
        book = Book(title="Dune", page_count=412, language="en")
        fields = {"page_count": 412, "language": "en"}

        assert merge_into(book, fields, overwrite=False) == []

    def test_ignores_fields_google_left_empty(self):
        book = Book(title="Dune", publisher="Chilton")
        merge_into(book, {"publisher": None, "page_count": None}, overwrite=True)

        assert book.publisher == "Chilton"

    def test_never_replaces_a_locally_uploaded_cover(self):
        # An uploaded cover lives under /covers/ and outranks a remote one,
        # exactly as in the metadata refresh.
        book = Book(title="Dune", cover_url="/covers/12.png")
        merge_into(book, _volume_to_fields(VOLUME), overwrite=True)

        assert book.cover_url == "/covers/12.png"

    def test_fills_an_absent_cover(self):
        book = Book(title="Dune", cover_url=None)
        changed = merge_into(book, _volume_to_fields(VOLUME), overwrite=False)

        assert book.cover_url == "https://books.google.com/cover.jpg"
        assert "cover_url" in changed

    def test_does_not_touch_the_title(self):
        """Deliberately excluded from the merge list.

        A title is how the book is recognised on the shelf, and Google's
        spelling of it (series numbering, subtitle folded in) is often not the
        one the library uses.
        """
        book = Book(title="Dune (Dune Chronicles, Book 1)")
        merge_into(book, _volume_to_fields(VOLUME), overwrite=True)

        assert book.title == "Dune (Dune Chronicles, Book 1)"


class TestSeriesParsing:
    """Google carries series info on some volumes and nothing on most.

    Deliberately conservative: a wrong series silently regroups the shelf and
    invents gaps that are not there, so anything unrecognised is left for a
    person to fill in.
    """

    def test_reads_a_hash_numbered_title(self):
        assert _series_from_title("Dune (Dune Chronicles #1)") == ("Dune Chronicles", 1.0)

    def test_reads_a_book_numbered_title(self):
        assert _series_from_title("Dune (Dune Chronicles, Book 1)") == ("Dune Chronicles", 1.0)

    def test_reads_a_trailing_book_number(self):
        # This shape names no series, only a position in one. Reporting the
        # number without a name would put the book in a nameless series.
        assert _series_from_title("Dune, Book 1") == (None, 1.0)

    def test_a_plain_title_has_no_series(self):
        assert _series_from_title("Dune") == (None, None)

    def test_a_parenthetical_that_is_not_a_series_is_ignored(self):
        assert _series_from_title("Some Book (Illustrated Edition)") == (None, None)

    def test_a_half_number_survives(self):
        assert _series_from_title("Novella (Discworld #2.5)") == ("Discworld", 2.5)

    def test_a_multi_word_series_name_survives(self):
        assert _series_from_title("A Game of Thrones (A Song of Ice and Fire #1)") == (
            "A Song of Ice and Fire",
            1.0,
        )

    def test_the_volume_mapper_surfaces_it(self):
        fields = _volume_to_fields(
            {"id": "x", "volumeInfo": {"title": "Dune (Dune Chronicles #1)"}}
        )
        assert (fields["series_name"], fields["series_index"]) == ("Dune Chronicles", 1.0)

    def test_series_info_improves_the_index_but_not_the_name(self):
        """`bookDisplayNumber` is a number despite the field name, and the name
        is not in that payload at all."""
        fields = _volume_to_fields(
            {
                "id": "x",
                "volumeInfo": {
                    "title": "Dune (Dune Chronicles #1)",
                    "seriesInfo": {
                        "bookDisplayNumber": "2",
                        "volumeSeries": [{"orderNumber": 2}],
                    },
                },
            }
        )
        assert (fields["series_name"], fields["series_index"]) == ("Dune Chronicles", 2.0)

    def test_a_volume_with_no_series_reports_none(self):
        fields = _volume_to_fields({"id": "x", "volumeInfo": {"title": "Plain"}})
        assert fields["series_name"] is None
        assert fields["series_index"] is None
