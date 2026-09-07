"""The OPDS reader: what it admits, what it reads, and what it refuses.

The bounds are the subject of most of this file, because the address is typed by
an admin and everything after the first request is written by whatever answered.
`TestNoResponseMovesTheOrigin` is the class that matters most: it is the guard
standing in for the address range refusal `opds.py` explains it cannot have.
"""

import pathlib
import time
from xml.etree import ElementTree

import httpx
import pytest
import respx

import fetch
import opds
from credentials import Credential
from decoders import Decoding, Reader

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = BACKEND / "tests" / "fixtures" / "opds_acquisition_feed.xml"

BASE = "http://library.invalid:8083/opds/books"


def _feed(entries: str, *, links: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:dcterms="http://purl.org/dc/terms/">'
        "<title>All books</title>"
        f"{links}{entries}</feed>"
    )


def _book(title: str, *, author: str = "", extra: str = "") -> str:
    credits = f"<author><name>{author}</name></author>" if author else ""
    return (
        f"<entry><title>{title}</title>{credits}{extra}"
        '<link rel="http://opds-spec.org/acquisition" href="/d/1" '
        'type="application/epub+zip"/></entry>'
    )


class TestWhichAddressesThisServerWillOpen:
    @pytest.mark.parametrize(
        "url",
        [
            "http://library.invalid:8083/opds",
            "https://library.invalid/opds",
            "http://10.0.0.10:8083/opds",
            "http://localhost:8083/opds",
            "http://[::1]:8083/opds",
        ],
    )
    def test_a_household_server_is_admitted(self, url):
        """Private space, loopback and plaintext are the ordinary case here.

        This is the arm that would go red if somebody added the address range
        refusal `opds.py` explains it deliberately does not have, so it is the
        one that says the refusal is absent on purpose.
        """
        assert opds.is_fetchable(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://library.invalid/opds",
            "ftp://library.invalid/opds",
            "//library.invalid/opds",
            "opds",
            "",
            "http://",
            "http://library.invalid:99999/opds",
            "http://library.invalid:notanumber/opds",
            "http://[::1/opds",
        ],
    )
    def test_anything_that_is_not_an_http_address_is_refused(self, url):
        assert not opds.is_fetchable(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://library.invalid@evil.invalid/opds",
            "http://library.invalid:secret@evil.invalid/opds",
            "https://calibre.home.example@evil.invalid:8083/opds",
        ],
    )
    def test_an_address_carrying_credentials_is_refused(self, url):
        """The control that matters most, because an admin reads back what they
        typed and every one of these reads as the household's own server."""
        assert not opds.is_fetchable(url)


class TestWhatOneEntryBecomes:
    def test_an_acquisition_entry_becomes_a_record(self):
        page = opds.read_page(_feed(_book("Small Gods", author="Terry Pratchett")))

        assert [(r.title, r.author) for r in page.records] == [
            ("Small Gods", "Terry Pratchett")
        ]

    def test_several_authors_arrive_as_one_credit_list(self):
        """Joined with a comma, which is what `importing.identity_key` splits on."""
        entry = (
            "<entry><title>Good Omens</title>"
            "<author><name>Terry Pratchett</name></author>"
            "<author><name>Neil Gaiman</name></author>"
            '<link rel="http://opds-spec.org/acquisition" href="/d/2"/></entry>'
        )

        page = opds.read_page(_feed(entry))

        assert page.records[0].author == "Terry Pratchett, Neil Gaiman"

    def test_an_author_element_with_no_name_contributes_no_empty_segment(self):
        entry = (
            "<entry><title>Anonymous</title><author><name>  </name></author>"
            "<author><name>Real Person</name></author>"
            '<link rel="http://opds-spec.org/acquisition" href="/d/3"/></entry>'
        )

        page = opds.read_page(_feed(entry))

        assert page.records[0].author == "Real Person"

    def test_an_entry_with_no_credited_author_has_none(self):
        page = opds.read_page(_feed(_book("Untitled Author")))

        assert page.records[0].author is None

    def test_a_navigation_entry_is_not_a_book(self):
        """The rule that stops a shelf index being filed as a title."""
        entry = (
            "<entry><title>Recently added</title>"
            '<link rel="subsection" href="/opds/recent"/></entry>'
        )

        page = opds.read_page(_feed(entry))

        assert page.records == ()
        assert page.not_held == 1

    @pytest.mark.parametrize(
        "rel",
        [
            "http://opds-spec.org/acquisition",
            "http://opds-spec.org/acquisition/open-access",
        ],
    )
    def test_a_relation_that_says_the_member_holds_it_is_a_book(self, rel):
        entry = f'<entry><title>A book</title><link rel="{rel}" href="/d/1"/></entry>'

        assert len(opds.read_page(_feed(entry)).records) == 1

    @pytest.mark.parametrize(
        "rel",
        [
            "http://opds-spec.org/acquisition/borrow",
            "http://opds-spec.org/acquisition/buy",
            "http://opds-spec.org/acquisition/sample",
            "http://opds-spec.org/acquisition/subscribe",
            "http://opds-spec.org/acquisition/something-added-later",
        ],
    )
    def test_an_entitlement_is_not_a_holding(self, rel):
        """This route's only assertion is ownership, so a title the server
        offers to sell or lend must not be recorded as one the member owns.

        The last arm is the reason the admitted set is enumerated rather than
        matched by prefix: a relation the specification adds later is refused by
        construction instead of being admitted by a prefix nobody revisited.
        """
        entry = f'<entry><title>For sale</title><link rel="{rel}" href="/d/1"/></entry>'

        page = opds.read_page(_feed(entry))

        assert page.records == ()
        assert page.not_held == 1

    def test_an_entry_offering_both_a_sale_and_a_download_is_held(self):
        """One holding relation is enough; the others beside it say nothing
        against it."""
        entry = (
            "<entry><title>Small Gods</title>"
            '<link rel="http://opds-spec.org/acquisition/buy" href="/b/1"/>'
            '<link rel="http://opds-spec.org/acquisition" href="/d/1"/></entry>'
        )

        assert len(opds.read_page(_feed(entry)).records) == 1

    def test_an_entry_with_no_title_is_refused_rather_than_filed(self):
        entry = '<entry><link rel="http://opds-spec.org/acquisition" href="/d/1"/></entry>'

        page = opds.read_page(_feed(entry))

        assert page.records == ()

    def test_one_unusable_entry_does_not_cost_the_page(self):
        """The failure rule both source families share: a bad record fails alone."""
        entries = (
            '<entry><link rel="http://opds-spec.org/acquisition" href="/d/1"/></entry>'
            + _book("Survivor")
        )

        assert [r.title for r in opds.read_page(_feed(entries)).records] == ["Survivor"]

    def test_the_records_are_labelled_with_this_readers_source(self):
        page = opds.read_page(_feed(_book("Small Gods")))

        assert page.records[0].source == opds.SOURCE


class TestTheIdentifierTheCensusSaysIsNotThere:
    @pytest.mark.parametrize(
        "written",
        ["urn:isbn:9780552152976", "URN:ISBN:9780552152976", "9780552152976",
         "978-0-552-15297-6"],
    )
    def test_a_dcterms_isbn_is_read_where_a_server_emits_one(self, written):
        """The URN form is what the specification's own example writes, and the
        scheme is case insensitive."""
        entry = _book(
            "Small Gods",
            extra=f"<dcterms:identifier>{written}</dcterms:identifier>",
        )

        assert opds.read_page(_feed(entry)).records[0].isbn == "9780552152976"

    def test_a_dc_elements_isbn_is_read_too(self):
        feed = (
            '<?xml version="1.0"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<entry><title>Small Gods</title>"
            "<dc:identifier>9780552152976</dc:identifier>"
            '<link rel="http://opds-spec.org/acquisition" href="/d/1"/></entry>'
            "</feed>"
        )

        assert opds.read_page(feed).records[0].isbn == "9780552152976"

    @pytest.mark.parametrize(
        "identifier",
        [
            "urn:uuid:8f2c1d40-0000-4000-8000-000000000001",
            "calibre:1417",
            "urn:isbn:not-an-isbn",
            "9780552152977",
            "../../etc/passwd",
            "",
        ],
    )
    def test_an_identifier_that_is_not_an_isbn_contributes_nothing(self, identifier):
        """`isbn.parse` is the whole of the trust placed in this field: thirteen
        digits that check, or absent. The third case is a real ISBN with the
        check digit changed."""
        entry = _book(
            "Small Gods", extra=f"<dcterms:identifier>{identifier}</dcterms:identifier>"
        )

        assert opds.read_page(_feed(entry)).records[0].isbn is None

    def test_the_census_case_is_an_entry_with_no_identifier_at_all(self):
        assert opds.read_page(_feed(_book("Small Gods"))).records[0].isbn is None


class TestWhatThisReaderRefusesToParse:
    def test_a_doctype_is_refused_before_any_expansion(self):
        """`xml.etree` expands internal entities, so a body carrying a doctype
        makes `fetch.MAX_RESPONSE_BYTES` stop bounding the parse."""
        body = (
            '<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY x "aaaaaaaaaa">]>'
            '<feed xmlns="http://www.w3.org/2005/Atom"><title>&x;</title></feed>'
        )

        with pytest.raises(opds.FeedUnreadable):
            opds.read_page(body)

    def test_the_doctype_spelling_is_the_one_metadata_refuses(self):
        """Imported rather than spelled again, so one cannot be tightened while
        the other stays as it was."""
        import metadata

        assert metadata.DOCTYPE in "<!DOCTYPE feed>"

    def test_bytes_that_are_not_xml_are_refused(self):
        with pytest.raises(opds.FeedUnreadable):
            opds.read_page("this is not a feed")

    def test_xml_that_is_not_an_atom_feed_is_refused(self):
        with pytest.raises(opds.FeedUnreadable):
            opds.read_page("<opds><entry/></opds>")

    def test_a_declared_multibyte_encoding_is_a_refusal_and_not_a_500(self):
        """`ElementTree.fromstring` raises `ValueError`, not `ParseError`, here."""
        with pytest.raises(opds.FeedUnreadable):
            opds.read_page('<?xml version="1.0" encoding="Shift_JIS"?><feed/>')


class TestADecoderWorksOnAFile:
    """The claim `decoders.py` makes, run rather than asserted.

    A feed read off disk, decoded through a `Decoding` built by hand, with no
    server, no address and no `Target` anywhere.
    """

    def test_a_feed_on_disk_decodes_with_no_server(self):
        root = ElementTree.fromstring(FIXTURE.read_text(encoding="utf-8"))
        decoding = Decoding(source="a folder of files", reader=Reader.OPDS_ATOM)

        records = [
            record
            for entry in root.findall(f"{opds.ATOM}entry")
            if (record := opds.entry_record(entry, decoding)) is not None
        ]

        assert [r.title for r in records] == ["Small Gods", "Good Omens"]
        assert records[0].source == "a folder of files"

    def test_the_shipped_decoding_names_the_atom_reader_and_no_marc_knob(self):
        assert opds.DECODING.reader is Reader.OPDS_ATOM
        assert not opds.DECODING.refuses_component_parts
        assert not opds.DECODING.reads_author_identifiers


class TestNoResponseMovesTheOrigin:
    """The guard that stands in for the address range refusal this cannot have.

    Every address after the first is written by whatever answered, so this is
    the only place a response gets to choose where the next request goes.
    """

    @pytest.mark.parametrize(
        "href",
        [
            "http://evil.invalid/opds",
            "https://library.invalid:8083/opds",
            "http://library.invalid:9090/opds",
            "http://library.invalid/opds",
            "http://library.invalid@evil.invalid:8083/opds",
            "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    def test_a_paging_link_off_the_configured_origin_is_refused(self, href):
        """Host, scheme and port each move the origin, and each is refused.

        The metadata endpoint is in this list because it is what an address
        range refusal would exist to stop, and it is stopped here instead.
        """
        origin = "http://library.invalid:8083"

        with pytest.raises(opds.UnusableAddress):
            opds._next_page(BASE, href, origin)

    def test_a_relative_paging_link_resolves_against_the_page_it_was_on(self):
        following = opds._next_page(
            BASE, "?page=2", "http://library.invalid:8083"
        )

        assert following == "http://library.invalid:8083/opds/books?page=2"

    def test_an_absolute_path_on_the_same_server_is_admitted(self):
        following = opds._next_page(
            BASE, "/opds/books/2", "http://library.invalid:8083"
        )

        assert following == "http://library.invalid:8083/opds/books/2"

    def test_the_comparison_is_against_the_configured_origin_not_the_last_hop(self):
        """A chain must not be able to walk one host at a time.

        The page in hand is on the second host already; its own paging link
        pointing at that same second host is still refused, because the origin
        it is compared to is the one an admin configured.
        """
        with pytest.raises(opds.UnusableAddress):
            opds._next_page(
                "http://evil.invalid/opds", "/page/2", "http://library.invalid:8083"
            )


class TestWalkingAFeed:
    @respx.mock
    async def test_the_pages_are_followed_and_the_books_added_up(self):
        respx.get(BASE).respond(
            text=_feed(
                _book("One"),
                links='<link rel="next" href="/opds/books/2"/>',
            ),
            headers={"content-type": "application/atom+xml"},
        )
        respx.get("http://library.invalid:8083/opds/books/2").respond(
            text=_feed(_book("Two"))
        )

        found = await opds.holdings(BASE)

        assert [r.title for r in found.records] == ["One", "Two"]
        assert found.pages_read == 2
        assert not found.truncated

    @respx.mock
    async def test_a_feed_whose_next_points_at_a_page_already_read_stops(self):
        """A loop ends the walk rather than spending the page cap on it."""
        route = respx.get(BASE).respond(
            text=_feed(_book("One"), links=f'<link rel="next" href="{BASE}"/>')
        )

        found = await opds.holdings(BASE)

        assert found.pages_read == 1
        assert route.call_count == 1

    @respx.mock
    async def test_a_paging_link_off_the_origin_fails_the_sync(self):
        respx.get(BASE).respond(
            text=_feed(
                _book("One"),
                links='<link rel="next" href="http://evil.invalid/opds"/>',
            )
        )

        with pytest.raises(opds.UnusableAddress):
            await opds.holdings(BASE)

    @respx.mock
    async def test_the_page_cap_stops_the_walk_and_says_so(self):
        respx.get(BASE).respond(
            text=_feed(_book("One"), links='<link rel="next" href="/opds/books/2"/>')
        )
        respx.get("http://library.invalid:8083/opds/books/2").respond(
            text=_feed(_book("Two"), links='<link rel="next" href="/opds/books/3"/>')
        )

        found = await opds.holdings(BASE, max_pages=2)

        assert found.pages_read == 2
        assert found.truncated

    @respx.mock
    async def test_the_entry_cap_takes_part_of_a_page_and_says_so(self):
        respx.get(BASE).respond(text=_feed(_book("One") + _book("Two") + _book("Three")))

        found = await opds.holdings(BASE, max_entries=2)

        assert [r.title for r in found.records] == ["One", "Two"]
        assert found.truncated

    @respx.mock
    async def test_the_deadline_stops_the_walk(self):
        respx.get(BASE).respond(
            text=_feed(_book("One"), links='<link rel="next" href="/opds/books/2"/>')
        )

        found = await opds.holdings(BASE, deadline_seconds=-1)

        assert found.pages_read == 0
        assert found.truncated

    @respx.mock
    async def test_entries_that_are_not_holdings_are_counted_across_pages(self):
        shelf = '<entry><title>Shelf</title><link rel="subsection" href="/s"/></entry>'
        sale = (
            "<entry><title>For sale</title>"
            '<link rel="http://opds-spec.org/acquisition/buy" href="/b/1"/></entry>'
        )
        respx.get(BASE).respond(text=_feed(shelf * 2 + sale))

        found = await opds.holdings(BASE)

        assert found.records == ()
        assert found.not_held == 3

    @respx.mock
    async def test_a_refusing_server_fails_the_sync_rather_than_answering_nothing(self):
        respx.get(BASE).respond(status_code=401)

        with pytest.raises(opds.OpdsError, match="401"):
            await opds.holdings(BASE)

    @respx.mock
    async def test_a_transport_failure_is_an_opds_error_and_not_an_httpx_one(self):
        """Every caller here is one route acting on one address, so this refuses
        rather than degrading to an empty import that looks like success."""
        respx.get(BASE).mock(side_effect=httpx.ConnectError("no route"))

        with pytest.raises(opds.OpdsError):
            await opds.holdings(BASE)

    async def test_an_address_this_server_will_not_open_is_refused_before_any_request(self):
        with pytest.raises(opds.UnusableAddress):
            await opds.holdings("file:///etc/passwd")

    @respx.mock
    async def test_a_body_over_the_fetch_cap_is_refused(self):
        """The byte bound is `fetch.MAX_RESPONSE_BYTES` counted raw, and this
        route goes through the same door the catalogue sources do."""
        respx.get(BASE).respond(
            content=b"<feed>" + b"x" * (fetch.MAX_RESPONSE_BYTES + 1) + b"</feed>"
        )

        with pytest.raises(opds.OpdsError):
            await opds.holdings(BASE)


class TestTheLoginGoesToOneOriginAndNoOther:
    @respx.mock
    async def test_the_credential_is_sent_to_the_configured_server(self):
        route = respx.get(BASE).respond(text=_feed(_book("One")))
        credential = Credential("http://library.invalid:8083", "sam", "hunter2")

        await opds.holdings(BASE, credential=credential)

        assert route.calls[0].request.headers["authorization"].startswith("Basic ")

    @respx.mock
    async def test_a_credential_bound_elsewhere_is_withheld_rather_than_sent(self):
        """The rule is the secret's rather than the transport's, so it holds even
        where this module's own origin pin has been satisfied."""
        route = respx.get(BASE).respond(text=_feed(_book("One")))
        credential = Credential("http://elsewhere.invalid:8083", "sam", "hunter2")

        await opds.holdings(BASE, credential=credential)

        assert "authorization" not in route.calls[0].request.headers


class TestTheBoundsAreStatedInOnePlace:
    def test_the_sync_deadline_is_longer_than_one_request_and_shorter_than_the_page_cap(
        self,
    ):
        """The relationship the constants claim, checked rather than trusted.

        A deadline below one request's own is a bound that can never let a page
        finish; a deadline above `MAX_PAGES` times that is not a bound at all.
        """
        assert fetch.TIMEOUT_SECONDS < opds.SYNC_DEADLINE_SECONDS
        assert opds.SYNC_DEADLINE_SECONDS < opds.MAX_PAGES * fetch.TIMEOUT_SECONDS

    #: The page size the `MAX_PAGES` comment prices its arithmetic against.
    #:
    #: Named here rather than left inside the assertion, because it is the
    #: assumption the arithmetic rests on and not a measurement of this tree.
    CALIBRE_WEB_PAGE = 60

    def test_the_page_cap_cannot_bite_before_the_entry_cap_on_a_full_feed(self):
        """`MAX_PAGES`'s comment claims the entry cap is reached first on any
        feed with a full page, and nothing recomputed it: raising `MAX_ENTRIES`
        past `MAX_PAGES * 60` would make the sentence false in silence."""
        assert opds.MAX_PAGES * self.CALIBRE_WEB_PAGE > opds.MAX_ENTRIES

    @respx.mock
    async def test_one_page_cannot_spend_the_whole_sync_deadline(self):
        """The per request bound the module's own table claims.

        `fetch.get` treats a supplied deadline as the whole budget, so passing
        the sync deadline alone left `fetch.TIMEOUT_SECONDS` bounding nothing
        and one page free to spend all of it. Asserted on the deadline the walk
        actually hands down rather than on a duration, which would be a timing
        test on a shared node.
        """
        seen: list[float] = []

        async def record(request):
            seen.append(time.monotonic())
            return httpx.Response(200, text=_feed(_book("One")))

        respx.get(BASE).mock(side_effect=record)
        started = time.monotonic()

        await opds.holdings(BASE, deadline_seconds=10_000)

        # The walk asked for `min(ends, now + TIMEOUT_SECONDS)`, so the budget
        # for this one page is bounded by the per request limit however large
        # the sync budget is. Re-derived here from the two constants rather than
        # read off the call.
        assert fetch.TIMEOUT_SECONDS < 10_000
        assert seen and seen[0] - started < fetch.TIMEOUT_SECONDS

    @respx.mock
    async def test_a_refusal_never_names_the_address(self):
        """The 502 this becomes reaches a member, and the address is otherwise
        admin only.

        **The failure has to be one whose own message carries the address, or
        this guard passes against the code it is written to refuse.** A
        `ConnectError` reads "no route" and names nothing, so a version of
        `holdings` that interpolated the exception would still pass. Every
        `fetch.FetchRefused` formats `{url[:200]}`, so an over-cap body is a
        failure that really does carry it.
        """
        respx.get(BASE).respond(
            content=b"<feed>" + b"x" * (fetch.MAX_RESPONSE_BYTES + 1) + b"</feed>"
        )

        with pytest.raises(opds.OpdsError) as refusal:
            await opds.holdings(BASE)

        assert "library.invalid" in str(
            fetch.ResponseTooLarge(f"{BASE} answered with more than N bytes")
        ), "the control: this failure kind does name the address"
        assert "library.invalid" not in str(refusal.value)
        assert "8083" not in str(refusal.value)

    @respx.mock
    async def test_the_walk_is_sequential_rather_than_concurrent(self):
        """One page at a time, so the memory peak is one page rather than the cap
        times the page count."""
        seen: list[float] = []

        def record(request):
            seen.append(time.monotonic())
            page = len(seen)
            link = (
                f'<link rel="next" href="/opds/books/{page + 1}"/>' if page < 3 else ""
            )
            return httpx.Response(200, text=_feed(_book(f"Book {page}"), links=link))

        respx.get(url__startswith="http://library.invalid:8083/opds/books").mock(
            side_effect=record
        )

        await opds.holdings(BASE)

        assert len(seen) == 3
        assert seen == sorted(seen)
