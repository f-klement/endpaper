"""Tests for backend/google_books.py.

The HTTP calls are intercepted with respx, so nothing here reaches Google. What
is worth pinning is the field mapping and, above all, the merge rule:
enrichment adds what is missing and does not overrule what a member typed.
"""

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

import fetch
from google_books import (
    VOLUME_ID,
    GoogleBooksError,
    _series_from_title,
    _volume_to_fields,
    is_a_volume_id,
    lookup_by_isbn,
    lookup_by_volume_id,
    merge_into,
    search,
)
from models import Book
from schemas import BookMatch

VOLUMES = "https://www.googleapis.com/books/v1/volumes"

#: The checkout root, for the one test that reads the browser's spelling of a
#: rule this module also spells. `__file__` is `backend/tests/`, so two parents.
REPOSITORY = Path(__file__).resolve().parents[2]

#: Twelve characters of the URL safe alphabet, because `lookup_by_volume_id`
#: refuses a payload whose own `id` is not a volume id. The mapping tests below
#: do not care and the door does.
VOLUME = {
    "id": "gbid00000001",
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
        assert fields["google_books_id"] == "gbid00000001"

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

    async def test_an_enormous_volume_body_is_refused_at_the_cap(
        self, google, monkeypatch
    ):
        """Google is trusted for records and not for byte counts.

        `_request` used to hand the whole body to `.json()` whichever size it
        was. Both callers in `metadata.py` catch `httpx.HTTPError`, which is
        what `fetch.ResponseTooLarge` is, so this degrades to "Google Books is
        unavailable" rather than filling a 512Mi pod.
        """
        monkeypatch.setattr(fetch, "MAX_RESPONSE_BYTES", 1024)
        google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, content=b'{"items":[' + b" " * 4096 + b"]}")
        )
        with pytest.raises(httpx.HTTPError):
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


def _as_match(volume: dict) -> BookMatch:
    """A Google volume through the bound `merge_into` now insists on.

    `merge_into` takes a `BookMatch` rather than a dictionary, so a test that
    hands it a dictionary is testing a call the type checker refuses. That is
    the point of the signature and not an inconvenience of it: see
    `TestTheSignatureIsTheBound` below.
    """
    return BookMatch(**_volume_to_fields(volume))


class TestMergeInto:
    """The rule that matters: fill gaps, do not overrule people."""

    def test_fills_an_empty_field(self):
        book = Book(title="Dune", page_count=None)
        changed = merge_into(book, _as_match(VOLUME), overwrite=False)

        assert book.page_count == 412
        assert "page_count" in changed

    def test_leaves_an_existing_value_alone(self):
        # A member who corrected a value should not have Google undo it.
        book = Book(title="Dune", publisher="The edition I actually own")
        merge_into(book, _as_match(VOLUME), overwrite=False)

        assert book.publisher == "The edition I actually own"

    def test_overwrite_replaces_it_when_asked(self):
        book = Book(title="Dune", publisher="Wrong")
        merge_into(book, _as_match(VOLUME), overwrite=True)

        assert book.publisher == "Chilton"

    def test_reports_only_what_actually_changed(self):
        # Enrichment often finds a volume and has nothing to add; saying
        # "done" would look like a no-op bug.
        book = Book(title="Dune", page_count=412, language="en")
        fields = {"page_count": 412, "language": "en"}

        assert merge_into(book, BookMatch(**fields), overwrite=False) == []

    def test_ignores_fields_google_left_empty(self):
        book = Book(title="Dune", publisher="Chilton")
        merge_into(book, BookMatch(publisher=None, page_count=None), overwrite=True)

        assert book.publisher == "Chilton"

    def test_never_replaces_a_locally_uploaded_cover(self):
        # An uploaded cover lives under /covers/ and outranks a remote one,
        # exactly as in the metadata refresh.
        book = Book(title="Dune", cover_url="/covers/12.png")
        merge_into(book, _as_match(VOLUME), overwrite=True)

        assert book.cover_url == "/covers/12.png"

    def test_fills_an_absent_cover(self):
        book = Book(title="Dune", cover_url=None)
        changed = merge_into(book, _as_match(VOLUME), overwrite=False)

        assert book.cover_url == "https://books.google.com/cover.jpg"
        assert "cover_url" in changed

    def test_does_not_touch_the_title(self):
        """Deliberately excluded from the merge list.

        A title is how the book is recognised on the shelf, and Google's
        spelling of it (series numbering, subtitle folded in) is often not the
        one the library uses.
        """
        book = Book(title="Dune (Dune Chronicles, Book 1)")
        merge_into(book, _as_match(VOLUME), overwrite=True)

        assert book.title == "Dune (Dune Chronicles, Book 1)"


class TestTheSignatureIsTheBound:
    """`merge_into` takes a `BookMatch`, and that type is the whole guard.

    Both routes that reach this function write third party values into columns.
    Until 2026-09-03 one of them validated its dictionary through the model and
    the other passed `Record.as_match()` straight through, so the identical
    oversized value was a 422 on `POST /{id}/enrich/apply` and a stored row on
    `POST /{id}/enrich`.

    The fix is a type rather than a call site convention, because a convention
    is what the second route already failed to follow. mypy refuses a
    dictionary at any call site; these pin the arms mypy cannot, which are a
    caller that never runs it and a later edit that widens the annotation back.
    """

    #: The five `BookMatch` fields `merge_into` deliberately leaves alone, and
    #: why. Named rather than counted, so the partition below has to sum.
    #:
    #: `source` labels the picker row and has no column. `title` is how a book
    #: is recognised on the shelf and Google's spelling of it is often not the
    #: library's. `isbn13` is one printing among several rather than this copy.
    #: `classifications` and `suggested_tag_ids` are not scalars and are
    #: applied by `add_headings` and by the caller respectively.
    NOT_WRITTEN = frozenset(
        {"source", "title", "isbn13", "classifications", "suggested_tag_ids"}
    )

    def _names_read_off_the_match(self) -> set[str]:
        """Every field name `merge_into` takes off its argument, from the source.

        Two shapes, because the function uses two: a `getattr` over a tuple of
        literal names, and a direct attribute access for the cover. Reading
        both is what makes this a second derivation rather than a re-reading of
        the tuple, and the cover is the name only the second shape sees.
        """
        import ast
        import inspect

        import google_books

        tree = ast.parse(inspect.getsource(google_books))
        fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "merge_into"
        )
        names = {
            node.attr
            for node in ast.walk(fn)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "match"
        }
        for loop in (node for node in ast.walk(fn) if isinstance(node, ast.For)):
            names |= {
                element.value
                for element in getattr(loop.iter, "elts", [])
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
        return names

    def test_every_column_it_writes_is_a_field_the_model_bounds(self):
        """The partition has to sum, which is what stops it going vacuous.

        An empty walk would leave the union short of the model's own fields and
        fail here rather than passing quietly, and a name added to the merge
        list that `BookMatch` does not carry cannot be bounded by anything.
        """
        written = self._names_read_off_the_match()

        assert written & self.NOT_WRITTEN == set()
        assert written | self.NOT_WRITTEN == set(BookMatch.model_fields)

    def test_the_model_is_the_only_channel_into_it(self):
        """Widening the annotation reopens the hole in silence, and so does
        leaving it alone and adding a second parameter beside it.

        mypy is what actually enforces the door, so the annotation is the door,
        and the parameter list is what stops a second door being cut. The
        partition above sees neither: it reads the names taken **off** `match`,
        so an unbounded dictionary arriving under another name writes the same
        columns and leaves that set untouched.

        **The whole argument list, not a list of its parts.** The first version
        of this checked `args`, `kwonlyargs`, `vararg` and `kwarg`, which is
        four of the five kinds an argument list has, and a security seat walked
        a `raw: dict, /` positional only parameter past both guards on the
        fifth, reading it in the body as `raw["series_index"]` where no
        `ast.Attribute` on `match` exists for the partition to see. Enumerating
        the kinds is the shape this repository keeps paying for; unparsing the
        node covers every kind there is, and the defaults and annotations with
        them, leaving no arm to add for the next one.

        Read off the source rather than off `__annotations__`, because the
        import naming the type is `TYPE_CHECKING` only: evaluating it at
        runtime is the cycle the guard on that import exists to avoid.
        """
        import ast
        import inspect

        import google_books

        tree = ast.parse(inspect.getsource(google_books))
        fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "merge_into"
        )

        assert (
            ast.unparse(fn.args) == "book: object, match: BookMatch, *, overwrite: bool"
        )

    def test_a_bare_dictionary_raises_rather_than_writing(self):
        """The runtime arm, for a caller mypy never saw.

        It fails on the first field rather than on the twelfth, so nothing is
        half written when it does.
        """
        book = Book(title="Dune", page_count=None)

        with pytest.raises(AttributeError):
            merge_into(book, _volume_to_fields(VOLUME), overwrite=False)  # type: ignore[arg-type]

        assert book.page_count is None


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


# ── Lookup by volume id ───────────────────────────────────────────────────────
#
# The door a Google Play Books import needs. That export carries a volume id for
# every book and no ISBN anywhere, so this is the only exact key such a library
# has, and the value comes out of a file a member handed over: everything below
# is either about what the id has to be before it becomes a URL, or about what
# the answer has to be before it becomes a Book.

VOLUME_URL = f"{VOLUMES}/gbid00000001"


class TestTheVolumeIdBound:
    """What `google_books.VOLUME_ID` admits, and what it refuses.

    The bound is not a tidiness rule: this value goes into a **path segment** at
    Google, and every character the pattern admits is unreserved in RFC 3986, so
    a value that passes needs no encoding and a value that would have needed
    some never becomes a request.
    """

    @pytest.mark.parametrize(
        "value",
        [
            "s7NIrgEACAAJ",  # calibre's own `google` regression fixture
            "____--------",
            "000000000000",
        ],
    )
    def test_twelve_url_safe_characters_are_a_volume_id(self, value):
        assert is_a_volume_id(value)

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "short",
            "thirteenchars",
            "abcdefghijk/",  # a path separator, which is the sharp one
            "abcdefghijk.",
            "abcdefghij k",
            "abcdefghijk%",
            "../../secret",
            "abcdefghijék",
        ],
    )
    def test_anything_else_is_not(self, value):
        assert not is_a_volume_id(value)

    def test_a_trailing_newline_is_refused(self):
        """The `$` trap, pinned directly rather than left to the anchors.

        Python's `$` also matches immediately before a trailing newline, so
        `^[A-Za-z0-9_-]{12}$` would admit this and put a newline in a URL path.
        `takeout.ts` spells the same rule with `^...$` and is right to, because
        JavaScript's `$` without the `m` flag is end of input.
        """
        assert not is_a_volume_id("abcdefghijkl\n")

    async def test_a_refused_value_makes_no_request(self, google):
        route = google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json=VOLUME)
        )
        assert await lookup_by_volume_id("abcdefghijk/", "key") is None
        assert route.call_count == 0


class TestTheThreeSpellings:
    """One rule, spelled in three files, and only this one is a security bound.

    `takeout.ts` keeps a sidecar line that is not an id out of the browser's
    parse and `calibre.ts` keeps a plugin's invented value out of a stored row.
    Neither runs on the server: `backup.restore` writes `book_identifiers`
    through Core and runs no Pydantic model, so a restored row reaches
    `lookup_by_volume_id` having passed neither. This test is what stops the
    three drifting apart silently.
    """

    #: The character class and length.
    SHAPE = "[A-Za-z0-9_-]{12}"

    #: The **assignment** each browser module makes, not the shape it mentions.
    #:
    #: **Both critic seats evaded the weaker version of this, independently,
    #: which is the strongest signal this process produces.** It asserted that
    #: `SHAPE` appeared anywhere in the file, so every widening that kept those
    #: characters somewhere passed. The design seat rewrote `takeout.ts` to
    #: `/^([A-Za-z0-9_-]{12})+$/`, admitting any multiple of twelve; the
    #: security seat rewrote it to `/^[A-Za-z0-9_.~%-]{1,60}$/` and left the old
    #: class in a trailing comment. Backend 77 passed and frontend `tests/lib/`
    #: 1,185 passed in 42 files under the first; 3 passed under the second.
    #:
    #: **Anchors included, and matching where the value is bound.** A comment
    #: cannot satisfy `const VOLUME_ID = ...`, and the anchors were left out of
    #: the first version on an argument about Python's `$` that is about the
    #: **backend** pattern and was applied to the wrong side: both browser
    #: modules spell `^...$`, where JavaScript's `$` is end of input.
    ASSIGNMENTS = {
        "frontend/src/lib/takeout.ts": f"const VOLUME_ID = /^{SHAPE}$/",
        "frontend/src/lib/calibre.ts": f"google_books: /^{SHAPE}$/",
    }

    @pytest.mark.parametrize("relative", sorted(ASSIGNMENTS))
    def test_the_browser_spells_the_same_shape(self, relative):
        source = (REPOSITORY / relative).read_text()
        expected = self.ASSIGNMENTS[relative]
        assert expected in source, (
            f"{relative} no longer binds the volume id rule as `{expected}`, "
            f"which is the literal this backend bound was derived from. Either "
            f"all three move or none does: widening one alone files a row "
            f"another refuses, and narrowing one alone drops an identifier "
            f"another stores. Only the backend one is a security bound, because "
            f"only it is between a stored value and a URL."
        )

    def test_the_guard_is_not_satisfied_by_a_mention(self):
        """The evasion both critic seats found, pinned so it cannot return.

        A file that spells a wider rule and names the old one in a comment must
        fail. Asserted against the matcher rather than by editing a file,
        because the thing under test is the string this class compares.
        """
        widened = (
            "const VOLUME_ID = /^[A-Za-z0-9_.~%-]{1,60}$/; "
            f"// was {self.SHAPE}\n"
        )
        assert self.ASSIGNMENTS["frontend/src/lib/takeout.ts"] not in widened

    def test_the_backend_pattern_is_that_shape(self):
        """`\\A` and `\\Z` where the browser has `^` and `$`, and that is the one
        difference the comparison above may not make: Python's `$` also matches
        before a trailing newline."""
        assert VOLUME_ID.pattern == rf"\A{self.SHAPE}\Z"


class TestLookupByVolumeId:
    async def test_returns_the_volume(self, google):
        google.get(VOLUME_URL).mock(return_value=httpx.Response(200, json=VOLUME))

        fields = await lookup_by_volume_id("gbid00000001", "key")

        assert fields is not None
        assert fields["title"] == "Dune"
        assert fields["page_count"] == 412

    async def test_the_id_goes_in_the_path_and_not_in_a_query(self, google):
        route = google.get(VOLUME_URL).mock(
            return_value=httpx.Response(200, json=VOLUME)
        )
        await lookup_by_volume_id("gbid00000001", "key")

        url = route.calls[0].request.url
        assert url.path.endswith("/volumes/gbid00000001")
        assert "q" not in url.params

    async def test_the_key_is_sent(self, google):
        route = google.get(VOLUME_URL).mock(
            return_value=httpx.Response(200, json=VOLUME)
        )
        await lookup_by_volume_id("gbid00000001", "key")

        assert route.calls[0].request.url.params["key"] == "key"

    async def test_nothing_about_the_member_travels_with_it(self, google):
        """A volume id is a fact about a book. Nothing else may ride along.

        The request carries the id, the key, and the two headers
        `fetch.catalogue_client` sets for every catalogue. No cookie, no
        `Authorization`, no member name and no `Referer`.
        """
        route = google.get(VOLUME_URL).mock(
            return_value=httpx.Response(200, json=VOLUME)
        )
        await lookup_by_volume_id("gbid00000001", "key")

        request = route.calls[0].request
        assert set(request.url.params) == {"key"}
        assert set(request.headers) <= {
            "host",
            "accept",
            "accept-encoding",
            "connection",
            "user-agent",
        }

    async def test_a_volume_google_does_not_have_is_none(self, google):
        google.get(VOLUME_URL).mock(return_value=httpx.Response(404))
        assert await lookup_by_volume_id("gbid00000001", "key") is None

    @pytest.mark.parametrize(
        "identifier",
        ["x" * 60, "short", "", "abcdefghijk/", 12, None],
    )
    async def test_a_volume_whose_id_is_not_a_volume_id_is_not_an_answer(
        self, google, identifier
    ):
        """The bound is the id's own, not merely that it is a string.

        `models.GOOGLE_BOOKS_ID_MAX` is 50, so a 60 character id is a string
        that `BookMatch` then drops, which writes nothing and leaves the Book a
        candidate: an answer reported on every press for ever, one metered
        request each. Requiring the shape is what makes "an answered book gained
        a field" true by construction.
        """
        payload: dict[str, Any] = {"volumeInfo": {"title": "Dune"}}
        if identifier is not None:
            payload["id"] = identifier
        google.get(VOLUME_URL).mock(return_value=httpx.Response(200, json=payload))

        assert await lookup_by_volume_id("gbid00000001", "key") is None

    async def test_a_search_page_is_not_a_volume(self, google):
        """The two endpoints share a host and a prefix and answer differently.

        `{"items": []}` is what the search endpoint says for a query nothing
        matches. Read as a volume it is a record with every field absent, which
        would be reported as an answer and enrich nothing.
        """
        google.get(VOLUME_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        assert await lookup_by_volume_id("gbid00000001", "key") is None

    @pytest.mark.parametrize("status", [401, 403])
    async def test_a_rejected_key_says_so(self, google, status):
        google.get(VOLUME_URL).mock(return_value=httpx.Response(status))
        with pytest.raises(GoogleBooksError, match="rejected the API key"):
            await lookup_by_volume_id("gbid00000001", "key")

    async def test_rate_limiting_says_so(self, google):
        google.get(VOLUME_URL).mock(return_value=httpx.Response(429))
        with pytest.raises(GoogleBooksError, match="rate limiting"):
            await lookup_by_volume_id("gbid00000001", "key")

    async def test_any_other_failure_is_generic(self, google):
        google.get(VOLUME_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(GoogleBooksError, match="not responding"):
            await lookup_by_volume_id("gbid00000001", "key")

    async def test_an_enormous_volume_body_is_refused_at_the_cap(
        self, google, monkeypatch
    ):
        """The same bound the search path has, on the new door.

        A cap that covered one entry point and not its neighbour would be a
        stated bound rather than an applied one.
        """
        monkeypatch.setattr(fetch, "MAX_RESPONSE_BYTES", 1024)
        google.get(VOLUME_URL).mock(
            return_value=httpx.Response(
                200, content=b'{"volumeInfo":{"title":"' + b"x" * 4096 + b'"}}'
            )
        )
        with pytest.raises(httpx.HTTPError):
            await lookup_by_volume_id("gbid00000001", "key")


class TestThePayloadGuardsHoldOnTheTwoDoorlessPaths:
    """`_mapping` is the only thing standing on `/volumes`, and it was untested.

    **`TestAHostileVolumePayload` below cannot cover this by construction.** It
    reaches the parser through `lookup_by_volume_id`, which since 2026-09-11
    refuses an envelope that is not a volume before any accessor runs, so every
    arm there proves the **door**. `lookup_by_isbn` and `search` hand
    `items[i]` straight to `_volume_to_fields` with no door at all.

    **Measured at the "stated" rung by a design critic**: reverting
    `_mapping(volume.get("volumeInfo"))` to the old `or {}` idiom passed the
    whole backend suite, 6,870 tests, while raising `AttributeError` through
    `metadata._google_books` on a `volumeInfo` of `"ab"`. That exception is in
    neither adapter's `except`, so it was a 500 on a member's scan. These two
    tests are what move it to "tested".
    """

    ODD = {"id": "gbid00000001", "volumeInfo": "ab"}

    async def test_the_isbn_path_answers_rather_than_raising(self, google):
        google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": [self.ODD]})
        )

        fields = await lookup_by_isbn("9780441013593", "key")

        assert fields is not None
        assert fields["title"] is None

    async def test_the_search_path_answers_rather_than_raising(self, google):
        google.get(url__startswith=VOLUMES).mock(
            return_value=httpx.Response(200, json={"items": [self.ODD]})
        )

        matches = await search("dune", "key")

        assert len(matches) == 1
        assert matches[0]["title"] is None


class TestAHostileVolumePayload:
    """What an odd body does, which used to be a 500 in four shapes.

    Each case below raised out of `_volume_to_fields` before the accessors were
    added, and none of them is caught by `metadata._google_volume`'s handler:
    an `AttributeError` and a `TypeError` are neither.
    """

    #: A real volume id, because the door refuses a payload whose own `id` is
    #: not one before any accessor below it runs. These tests are about what the
    #: **parser** does with an odd `volumeInfo`, so the envelope has to be
    #: well formed or every one of them would pass for the wrong reason.
    ID = "gbid00000001"

    async def _fields(self, google, info):
        google.get(VOLUME_URL).mock(
            return_value=httpx.Response(
                200, json={"id": self.ID, "volumeInfo": info}
            )
        )
        return await lookup_by_volume_id(self.ID, "key")

    async def test_a_body_that_is_not_an_object(self, google):
        google.get(VOLUME_URL).mock(return_value=httpx.Response(200, json=["ab"]))
        with pytest.raises(GoogleBooksError, match="unreadable"):
            await lookup_by_volume_id("gbid00000001", "key")

    async def test_volume_info_that_is_a_list(self, google):
        assert await self._fields(google, []) is None

    async def test_authors_that_is_a_string(self, google):
        """`", ".join("Dune")` is `"D, u, n, e"`, silently."""
        fields = await self._fields(
            google, {"title": "Dune", "authors": "Herbert"}
        )
        assert fields is not None
        assert fields["author"] is None

    async def test_industry_identifiers_of_strings(self, google):
        fields = await self._fields(
            google, {"title": "Dune", "industryIdentifiers": ["a"]}
        )
        assert fields is not None
        assert fields["isbn13"] is None

    async def test_an_identifier_entry_naming_a_type_and_no_value(self, google):
        fields = await self._fields(
            google,
            {"title": "Dune", "industryIdentifiers": [{"type": "ISBN_13"}]},
        )
        assert fields is not None
        assert fields["isbn13"] is None

    async def test_a_title_that_is_a_number(self, google):
        fields = await self._fields(google, {"title": 1965})
        assert fields is not None
        assert fields["series_name"] is None

    async def test_series_info_that_is_a_string(self, google):
        fields = await self._fields(
            google, {"title": "Dune", "seriesInfo": {"volumeSeries": "ab"}}
        )
        assert fields is not None
        assert fields["series_index"] is None

    @pytest.mark.parametrize(
        "links",
        ["http://x/y", ["a"], 5, {"thumbnail": 5}, {"thumbnail": ["a"]},
         {"thumbnail": {"a": 1}}, {"thumbnail": True}],
    )
    async def test_image_links_of_any_wrong_shape(self, google, links):
        """Seven shapes, and every one of them was a 500 until 2026-09-11.

        This field kept the `or {}` idiom after the others moved to `_mapping`,
        and the value inside it was unguarded too. `AttributeError`, `TypeError`
        and `KeyError` are none of them what `metadata._google_volume` catches,
        so each escaped the handler; on the backfill that loses the whole batch
        before the commit rather than one book. Found by the security seat.
        """
        fields = await self._fields(
            google, {"title": "Dune", "imageLinks": links}
        )
        assert fields is not None
        assert fields["cover_url"] is None

    async def test_a_body_nested_past_the_recursion_limit(self, google):
        """600 KB, inside the response cap, and a `ValueError` out of this module.

        `json.loads` raises `RecursionError`, a `RuntimeError` subclass that no
        adapter's `except` clause saw. `fetch.Fetched.json` converts it at the
        one place a body is parsed, so what leaves here is the `ValueError` a
        body this module cannot read has always been. Asserted as an exception
        here and as an outcome in `tests/test_metadata.py`, because this
        module's job is to raise it and that module's is to absorb it.

        **`ValueError` and not `GoogleBooksError`**: the conversion happens
        before `_object` sees a payload, so this is the unreadable body arm
        rather than the not-an-object one.
        """
        body = b'{"a":' * 100_000 + b"1" + b"}" * 100_000
        assert len(body) < fetch.MAX_RESPONSE_BYTES
        google.get(VOLUME_URL).mock(return_value=httpx.Response(200, content=body))

        with pytest.raises(ValueError):
            await lookup_by_volume_id("gbid00000001", "key")

    async def test_categories_of_mixed_types(self, google):
        fields = await self._fields(
            google, {"title": "Dune", "categories": ["Fiction", 7]}
        )
        assert fields is not None
        assert fields["categories"] == "Fiction"
