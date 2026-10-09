"""The OPDS reader: what it admits, what it reads, and what it refuses.

The bounds are the subject of most of this file, because the address is typed by
an admin and everything after the first request is written by whatever answered.
Two classes carry the address rules and they answer different questions.
`TestNoResponseMovesTheOrigin` is about every address after the first, which is
written by whatever answered. `TestAnAddressIsResolvedAndPinned` is about the
first, which an admin typed: the range refusal that used to be impossible here
arrived with `fetch.pinned_client`, and it is the only class in this file whose
addresses are resolved rather than written as literals.
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

# **Imported, not copied.** The resolver double is one fact about how a lookup
# is faked here, and `tests/test_fetch.py` is where the pin it feeds is tested.
from tests.test_fetch import _Answers

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = BACKEND / "tests" / "fixtures" / "opds_acquisition_feed.xml"

#: The server the walking tests point at, and it is a literal on purpose.
#:
#: `holdings` goes through `fetch.pinned_client`, which resolves a **name** and
#: connects to the address it got. A literal reaches no resolver, here or in
#: httpcore, so every test in this file runs the shipped transport end to end
#: and makes no lookup of any kind. It is a private address because that is what
#: a household server has and what `fetch.HOUSEHOLD_ADDRESSES` admits.
#:
#: The resolving path is tested where the resolution happens:
#: `TestAnAddressIsResolvedAndPinned` here, and `tests/test_fetch.py`.
BASE = "http://10.0.9.9:8083/opds/books"


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
            "http://10.0.9.9:8083/opds",
            "https://10.0.9.9/opds",
            "http://10.0.0.10:8083/opds",
            "http://localhost:8083/opds",
            "http://[::1]:8083/opds",
        ],
    )
    def test_a_household_server_is_admitted(self, url):
        """Private space, loopback and plaintext are the ordinary case here.

        `is_fetchable` is the parse, not the address policy: it reads the text
        an admin typed and never resolves anything, so a link local literal
        passes it and is refused later, by `fetch.HOUSEHOLD_ADDRESSES` at the
        connection. Two rules, one home each, and this is the arm that says
        private space and loopback stay admitted at both of them.
        """
        assert opds.is_fetchable(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://10.0.9.9/opds",
            "ftp://10.0.9.9/opds",
            "//10.0.9.9/opds",
            "opds",
            "",
            "http://",
            "http://10.0.9.9:99999/opds",
            "http://10.0.9.9:notanumber/opds",
            "http://[::1/opds",
        ],
    )
    def test_anything_that_is_not_an_http_address_is_refused(self, url):
        assert not opds.is_fetchable(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.9.9@evil.invalid/opds",
            "http://10.0.9.9:secret@evil.invalid/opds",
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
    """Every address after the first is written by whatever answered.

    So this is the only place a **response** gets to choose where the next
    request goes, and it does not get to. Separate from the address policy,
    which is about the address an admin typed:
    `TestAnAddressIsResolvedAndPinned` is that one.
    """

    @pytest.mark.parametrize(
        "href",
        [
            "http://evil.invalid/opds",
            "https://10.0.9.9:8083/opds",
            "http://10.0.9.9:9090/opds",
            "http://10.0.9.9/opds",
            "http://10.0.9.9@evil.invalid:8083/opds",
            "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    def test_a_paging_link_off_the_configured_origin_is_refused(self, href):
        """Host, scheme and port each move the origin, and each is refused.

        The metadata endpoint is in this list because it is what an address
        range refusal exists to stop, and this refuses it a second time and for
        a different reason: here because it is not the configured origin, and in
        `fetch.HOUSEHOLD_ADDRESSES` because of the range it is in.
        """
        origin = "http://10.0.9.9:8083"

        with pytest.raises(opds.UnusableAddress):
            opds._next_page(BASE, href, origin)

    def test_a_relative_paging_link_resolves_against_the_page_it_was_on(self):
        following = opds._next_page(
            BASE, "?page=2", "http://10.0.9.9:8083"
        )

        assert following == "http://10.0.9.9:8083/opds/books?page=2"

    def test_an_absolute_path_on_the_same_server_is_admitted(self):
        following = opds._next_page(
            BASE, "/opds/books/2", "http://10.0.9.9:8083"
        )

        assert following == "http://10.0.9.9:8083/opds/books/2"

    def test_the_comparison_is_against_the_configured_origin_not_the_last_hop(self):
        """A chain must not be able to walk one host at a time.

        The page in hand is on the second host already; its own paging link
        pointing at that same second host is still refused, because the origin
        it is compared to is the one an admin configured.
        """
        with pytest.raises(opds.UnusableAddress):
            opds._next_page(
                "http://evil.invalid/opds", "/page/2", "http://10.0.9.9:8083"
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
        respx.get("http://10.0.9.9:8083/opds/books/2").respond(
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
        respx.get("http://10.0.9.9:8083/opds/books/2").respond(
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
        credential = Credential("http://10.0.9.9:8083", "sam", "hunter2")

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

        assert "10.0.9.9" in str(
            fetch.ResponseTooLarge(f"{BASE} answered with more than N bytes")
        ), "the control: this failure kind does name the address"
        assert "10.0.9.9" not in str(refusal.value)
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

        respx.get(url__startswith="http://10.0.9.9:8083/opds/books").mock(
            side_effect=record
        )

        await opds.holdings(BASE)

        assert len(seen) == 3
        assert seen == sorted(seen)


class TestAnAddressIsResolvedAndPinned:
    """The control the OPDS link local ticket was waiting on, at this door.

    **Every other test in this file points at a literal address, which no
    resolver ever sees**, so swapping `fetch.pinned_client` back to
    `fetch.catalogue_client` in `holdings` would leave all of them green. These
    are the ones that go red, and they are why `holdings` takes a `resolver`.

    **respx matches the URL after the pin, not before it.** Its default mocker
    patches httpcore, which is below `PinnedTransport`, so a route registered
    under the name would not match even with a resolver injected: the routes
    here are registered on the address the name resolves to.
    """

    NAME = "http://calibre.test:8083/opds/books"

    async def test_a_name_is_resolved_and_the_request_goes_to_that_address(self):
        with respx.mock:
            route = respx.get(BASE).respond(text=_feed(_book("One")))

            found = await opds.holdings(self.NAME, resolver=_Answers(("10.0.9.9",)))

        assert [record.title for record in found.records] == ["One"]
        assert route.calls[0].request.headers["host"] == "calibre.test:8083"

    async def test_a_name_that_resolves_to_link_local_is_refused(self):
        """The case a refusal on the URL text walks straight past.

        This is what the owner's decision bought: the address is classified
        after resolution, so the name spelling makes no difference to it.
        """
        with respx.mock:
            route = respx.get(url__startswith="http://169.254.169.254").respond(
                text=_feed(_book("Metadata"))
            )

            with pytest.raises(opds.UnusableAddress) as refusal:
                await opds.holdings(
                    "http://metadata.test/latest/meta-data/",
                    resolver=_Answers(("169.254.169.254",)),
                )

        assert route.call_count == 0
        assert "169.254" not in str(refusal.value)
        assert "metadata.test" not in str(refusal.value)

    async def test_the_same_address_typed_as_a_literal_is_refused_too(self):
        """The accident the ticket was raised on, which is the cheaper half."""
        with pytest.raises(opds.UnusableAddress):
            await opds.holdings("http://169.254.169.254/latest/meta-data/")

    @pytest.mark.parametrize(
        "address",
        ["http://127.0.0.1:8083/opds", "http://10.0.9.9:8083/opds"],
    )
    async def test_a_household_address_is_still_admitted(self, address):
        """What this must **not** have refused.

        A household's own server is on the household's own network, so the two
        ranges that would have been the obvious thing to refuse alongside link
        local are the feature itself.
        """
        with respx.mock:
            respx.get(address).respond(text=_feed(_book("One")))

            found = await opds.holdings(address)

        assert [record.title for record in found.records] == ["One"]

    async def test_a_name_that_answers_differently_on_the_second_page_is_refused(self):
        """Rebinding across a walk, which is the case a check alone cannot see.

        The name answers with the household's server, then with the metadata
        endpoint for the next page. Each request resolves and classifies again,
        so the walk stops rather than following the second answer.
        """
        resolver = _Answers(("10.0.9.9",), ("169.254.169.254",))
        with respx.mock:
            respx.get(BASE).respond(
                text=_feed(_book("One"), links='<link rel="next" href="/opds/books/2"/>')
            )
            page_two = respx.get("http://10.0.9.9:8083/opds/books/2").respond(
                text=_feed(_book("Two"))
            )

            with pytest.raises(opds.UnusableAddress):
                await opds.holdings(self.NAME, resolver=resolver)

        assert page_two.call_count == 0
        assert len(resolver.asked) == 2


class TestThePoliciesTheProseNames:
    """The module docstring says which ranges this door admits. Read, not trusted.

    A document stating something the code does not do is the failure this
    converts into one failing test, and the precedent is
    `test_ratelimit.py::TestTheRateLimitTableInTheDocsIsTheModule`.

    **The phrase is derived from the class rather than written beside it**, and
    that is a mutation this guard failed. The first version carried a mapping of
    class to phrase; the other seat rebound one class's phrase to another
    class's, and nothing went red, because the keys were checked as a set and
    the phrases only for presence anywhere. A derived phrase cannot be rebound.

    **What it still does not check, and this is the honest bound**: which
    sentence carries which word. The check is presence plus distinctness, so a
    prose edit that moves a class's name into the wrong sentence, or that says
    a refused class is admitted, passes. Binding a word to its sentence needs
    the prose to be structured rather than read, which is a larger change than
    the drift it would catch.
    """

    @staticmethod
    def _phrase(address_class: fetch.AddressClass) -> str:
        """What the prose has to call this class: its own name, spaced."""
        return address_class.value.replace("-", " ")

    #: Derived from the policy at collection time rather than written out, so a
    #: class added to `AddressClass` and refused arrives here with no edit, and
    #: a class moved into the policy leaves. A skip would have done the same job
    #: and cost the coverage register its "no skips" invariant.
    REFUSED = sorted(set(fetch.AddressClass) - fetch.HOUSEHOLD_ADDRESSES.admits, key=str)

    @pytest.mark.parametrize("address_class", REFUSED)
    def test_a_class_the_policy_refuses_is_named_in_the_module_docstring(
        self, address_class
    ):
        assert self._phrase(address_class) in (opds.__doc__ or "").casefold()

    def test_the_policy_refuses_the_four_classes_this_file_was_written_against(self):
        """An empty parameter set is a green test that checks nothing.

        **Equality rather than a floor, and the name says which**: a class added
        to `AddressClass` and refused by this policy arrives in `REFUSED` with no
        edit, and this is the arm that stops it doing so silently. What it asks
        for is a decision about the prose, not a bigger number.
        """
        assert len(self.REFUSED) == 4

    def test_each_refused_class_asks_the_prose_for_a_different_word(self):
        """The diagonal, and it is what a presence check cannot do on its own.

        **Deriving the phrase from the class did not bind the two together.**
        The other seat's mutation made every class ask for the same word, one
        that is in the docstring, and every arm above stayed green: each was
        only ever asking whether some word was present. This is the arm that
        goes red for that, because four classes asking for one word is three
        classes whose absence from the prose nothing would notice.

        **It watches `_phrase` and never reads the docstring**, so it goes red
        for a degenerate phrase and for nothing a prose edit can do. The arms
        above are the ones that read the prose.
        """
        asked = [self._phrase(address_class) for address_class in self.REFUSED]

        assert len(set(asked)) == len(self.REFUSED)

    def test_the_two_ranges_a_household_needs_are_named_as_admitted(self):
        """The other half: the prose has to say what is still reachable.

        Refusing loopback or RFC 1918 would refuse the feature, so a reader
        arriving at this door needs the admission written down as deliberate
        rather than inferring it from an absence.
        """
        prose = opds.__doc__ or ""

        assert fetch.AddressClass.LOOPBACK in fetch.HOUSEHOLD_ADDRESSES.admits
        assert fetch.AddressClass.PRIVATE in fetch.HOUSEHOLD_ADDRESSES.admits
        assert "Two of the three private ranges are admitted" in prose
