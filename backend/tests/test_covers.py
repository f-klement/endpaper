"""Tests for backend/covers.py.

The catalogues this app reads are bibliographic: the DNB and K10plus return
MARC and Dublin Core with no image in them, so a cover has always been a guess
at a URL on a separate service. Measured across ten ISBNs, a URL was offered
for 10 and only 8 resolved to an image; the other two were stored anyway, so
those books showed a broken cover for good.

The behaviour worth pinning hardest is the three-way answer. A 404 means the
service has no cover and the next candidate is worth trying. A 503 means
nothing is known, and Open Library really did return one twice in a row for a
book it very likely has, so discarding a cover on that would lose it to a blip.
"""

import ast
import gzip
from pathlib import Path
from time import monotonic, sleep

import httpx
import pytest
import respx

import covers
from tests.conftest import REAL_RESOLVE_AND_STORE
from tests.helpers import JPEG_BYTES, PNG_BYTES, WEBP_BYTES

OPEN_LIBRARY = "https://covers.openlibrary.org/"
DNB = "https://portal.dnb.de/opac/mvb/cover"

GERMAN = "9783423280150"
ENGLISH = "9780441013593"


def image(status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, content=b"\xff\xd8\xff\xe0jpegbytes", headers={"content-type": "image/jpeg"}
    )


class TestOrder:
    def test_a_german_isbn_asks_the_dnb_first(self):
        """The book trade's own service is the one that has them."""
        assert covers.candidates(GERMAN)[0].startswith(DNB)

    def test_anything_else_asks_open_library_first(self):
        assert covers.candidates(ENGLISH)[0].startswith(OPEN_LIBRARY)

    def test_default_false_is_kept_on_the_open_library_url(self):
        """Without it every request answers with a grey placeholder image.

        A book with no cover then gets one that looks broken rather than no
        cover at all, and nothing downstream can tell the difference.
        """
        assert "default=false" in covers.open_library_url(ENGLISH)


class TestChecking:
    @pytest.mark.asyncio
    async def test_a_verified_cover_is_returned(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_404_moves_on_to_the_next_service(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=DNB).mock(return_value=image())

            assert await covers.resolve(ENGLISH) == covers.dnb_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_no_service_having_it_is_no_cover(self):
        """Better than a link that renders as a broken image for good."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=r".*").mock(return_value=httpx.Response(404))
            assert await covers.resolve(ENGLISH) is None

    @pytest.mark.asyncio
    async def test_a_200_that_is_not_an_image_is_refused(self):
        """An error page served with the wrong status is the other failure."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=r".*").mock(
                return_value=httpx.Response(200, text="<html>not found</html>")
            )
            assert await covers.resolve(ENGLISH) is None


class TestTransientFailures:
    """A 503 is not a 404, and treating it as one loses covers to a blip."""

    @pytest.mark.asyncio
    async def test_a_5xx_keeps_the_url_rather_than_discarding_it(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=DNB).mock(return_value=httpx.Response(404))

            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_timeout_keeps_the_url_too(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectTimeout("slow")
            )
            mock.get(url__startswith=DNB).mock(return_value=httpx.Response(404))

            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_verified_cover_beats_an_unverifiable_one(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=DNB).mock(return_value=image())

            assert await covers.resolve(ENGLISH) == covers.dnb_url(ENGLISH)


class TestASuppliedUrl:
    """A URL from a volume record is not a guess: it exists by construction."""

    SUPPLIED = "https://books.google.com/thumb.jpg"

    @pytest.mark.asyncio
    async def test_it_is_tried_first_and_kept(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(self.SUPPLIED).mock(return_value=image())
            mock.get(url__regex=r".*").mock(return_value=image())

            assert await covers.resolve(ENGLISH, self.SUPPLIED) == self.SUPPLIED

    @pytest.mark.asyncio
    async def test_a_dead_supplied_url_falls_through(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(self.SUPPLIED).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())

            assert await covers.resolve(ENGLISH, self.SUPPLIED) == covers.open_library_url(
                ENGLISH
            )


class TestBadInput:
    @pytest.mark.asyncio
    async def test_a_string_that_is_not_an_isbn_costs_no_request(self):
        with respx.mock(assert_all_called=False) as mock:
            any_call = mock.get(url__regex=r".*").mock(return_value=image())
            assert await covers.resolve("not-an-isbn") is None
            assert not any_call.called

    @pytest.mark.asyncio
    async def test_a_supplied_url_survives_an_unparseable_isbn(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=r".*").mock(return_value=image())
            assert await covers.resolve("nonsense", "https://x/y.jpg") == "https://x/y.jpg"


class TestHttpsUpgrade:
    """Google Books returns its thumbnails over plain http. On an https page
    that is mixed content: the browser blocks it whatever the CSP says, and the
    book gets a cover that is right in the database and invisible in the app.
    """

    def test_an_http_url_is_upgraded(self):
        assert (
            covers.https_url("http://books.google.com/c.jpg")
            == "https://books.google.com/c.jpg"
        )

    def test_the_scheme_is_matched_case_insensitively(self):
        # RFC 3986 says a scheme is case-insensitive, and the one-shot data
        # migration matches with SQLite's LIKE, which is too.
        assert (
            covers.https_url("HTTP://books.google.com/c.jpg")
            == "https://books.google.com/c.jpg"
        )

    def test_an_https_url_is_untouched(self):
        assert covers.https_url("https://x/y.jpg") == "https://x/y.jpg"

    def test_a_local_cover_is_untouched(self):
        # An uploaded cover is a relative path with no scheme at all.
        assert covers.https_url("/covers/1.jpg") == "/covers/1.jpg"

    def test_no_cover_stays_no_cover(self):
        assert covers.https_url(None) is None

    def test_only_the_scheme_changes(self):
        # A naive replace would also rewrite a query parameter that happens to
        # carry a URL of its own.
        assert (
            covers.https_url("http://x/y?src=http://z")
            == "https://x/y?src=http://z"
        )


#: Every URL this module can build, for the two tests that check the host list
#: is complete. Listed here rather than derived, because a builder added
#: without a line here is exactly the omission both tests exist to catch.
def every_buildable_url() -> list[str]:
    return [
        *covers.candidates(GERMAN),
        *covers.candidates(ENGLISH),
        covers.open_library_id_url(1234),
    ]


class TestWhatMayReachAnImageTag:
    """`cover_url` is free text that ends up in an `<img src>`.

    None of these is exploitable as the app stands: `javascript:` is inert in
    an image tag, an SVG rendered through one cannot run script, and `//host`
    is refused because `img-src` lists no bare-host wildcard. All three become
    exploitable the day `img-src` gains a wildcard or a cover is rendered
    somewhere other than an image tag, and none of that is a thing to have to
    remember.
    """

    def test_a_remote_cover_over_tls_is_fine(self):
        assert covers.is_renderable("https://covers.openlibrary.org/b/isbn/1-L.jpg")

    def test_one_of_our_own_uploads_is_fine(self):
        assert covers.is_renderable("/covers/1.jpg")

    def test_a_script_url_is_not(self):
        assert not covers.is_renderable("javascript:alert(1)")

    def test_a_data_url_is_not(self):
        assert not covers.is_renderable("data:image/svg+xml,<svg/>")

    def test_a_scheme_relative_url_is_not(self):
        assert not covers.is_renderable("//evil.invalid/x.jpg")

    def test_some_other_path_on_our_origin_is_not(self):
        # /covers/ is the only directory this app serves images from.
        assert not covers.is_renderable("/api/books/export")

    def test_a_traversal_out_of_that_directory_is_not(self):
        """The prefix is not the invariant; staying inside the directory is.

        Nothing stored here reaches the filesystem, because `routers/covers.py`
        rebuilds the path from the parsed int id and a letters-only extension.
        So this is not a traversal hole, it is the test above meaning what it
        says.
        """
        assert not covers.is_renderable("/covers/../api/books/export")
        assert not covers.is_renderable("/covers/../../etc/passwd")

    def test_plain_http_is_not(self):
        # Reached only if `https_url` was skipped, which is the point of
        # checking after the upgrade rather than instead of it.
        assert not covers.is_renderable("http://books.google.com/c.jpg")


class TestStorable:
    """The two rules as one, which is how every writer of the column reaches
    them. They were three copies, and two of the three repaired the upgrade
    half of a bug while leaving the acceptance half open.
    """

    def test_it_upgrades_before_it_judges(self):
        # The other order would refuse every http cover rather than fix it.
        assert (
            covers.storable("http://books.google.com/c.jpg")
            == "https://books.google.com/c.jpg"
        )

    def test_it_keeps_a_cover_that_is_already_fine(self):
        assert covers.storable("https://x/y.jpg") == "https://x/y.jpg"

    def test_it_keeps_one_of_our_own_uploads(self):
        assert covers.storable("/covers/1.jpg") == "/covers/1.jpg"

    def test_no_cover_stays_no_cover(self):
        assert covers.storable(None) is None

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:image/svg+xml,<svg/>",
            "//evil.invalid/x.jpg",
            "/api/books/export",
            "/covers/../api/books/export",
        ],
    )
    def test_it_refuses_what_an_image_tag_should_not_load(self, url):
        assert covers.storable(url) is None


class TestTheHostList:
    """`COVER_HOSTS` is what the CSP is built from, so a builder here that is
    not represented there is a cover the browser will refuse to load. The
    matching assertion against the live policy is in tests/test_middleware.py.
    """

    def test_every_url_this_module_builds_has_a_listed_host(self):
        for url in every_buildable_url():
            assert any(
                url.startswith(f"{host}/") for host in covers.COVER_HOSTS
            ), url

    def test_every_listed_host_is_https(self):
        # An http entry would put the CSP back in the business of permitting
        # mixed content, which the browser blocks anyway.
        assert all(host.startswith("https://") for host in covers.COVER_HOSTS)


class TestNoOtherModuleBuildsACoverUrl:
    """House rule: `covers.py` is the only module that knows an image host.

    It has to be, because the CSP is derived from `COVER_HOSTS` and nothing
    else. A cover URL written out somewhere else points at a host the policy
    may not list, and the browser then blocks the image with a 200 on the
    record, nothing in a log, and every test green. That is not hypothetical:
    `metadata.py` held six such literals, five of them `open_library_url()`
    copied verbatim, and it is how `portal.dnb.de` came to be missing from the
    policy in the first place.

    Walks the AST rather than grepping, so a URL split across an f-string is
    caught too.
    """

    BACKEND = Path(__file__).resolve().parent.parent

    def modules(self) -> list[Path]:
        return [
            path
            for path in self.BACKEND.rglob("*.py")
            # `site-packages` as well as `.venv`: a dependency tree can land
            # outside a directory called .venv depending on how the environment
            # was built, and this walk must never leave first-party code.
            if ".venv" not in path.parts
            and "site-packages" not in path.parts
            and "tests" not in path.parts
            and "migrations" not in path.parts
            and path.name != "covers.py"
        ]

    @staticmethod
    def _literal_parts(node: ast.AST) -> list[str]:
        """Every string literal inside an expression, f-string pieces included."""
        return [
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        ]

    def _cover_url_expressions(self, tree: ast.AST) -> list[ast.expr]:
        """Every expression assigned to a `cover_url`, by either spelling."""
        found: list[ast.expr] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "cover_url"
                        and value is not None
                    ):
                        found.append(value)
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Attribute) and target.attr == "cover_url"
                for target in node.targets
            ):
                found.append(node.value)
        return found

    def test_no_module_writes_a_cover_url_literal(self):
        offenders: list[str] = []
        for path in self.modules():
            tree = ast.parse(path.read_text())
            for expression in self._cover_url_expressions(tree):
                if any(
                    part.startswith("http")
                    for part in self._literal_parts(expression)
                ):
                    offenders.append(f"{path.name}:{expression.lineno}")

        assert offenders == [], (
            "these build a cover URL from a literal; call covers.py instead: "
            + ", ".join(offenders)
        )

    def test_no_module_mentions_an_image_host_at_all(self):
        """The class-level rule, asserted directly.

        The test above inspects expressions assigned to a `cover_url`, so one
        hop of indirection walks past it: move the same literal into a helper
        and call the helper from the dict, and it sees nothing. That is an
        ordinary extract-a-method refactor rather than a contrivance, which
        makes it exactly how the DNB bug would come back.

        This is the rule `covers.py` actually claims: no other module knows an
        image host. String constants only, so the comments in `middleware.py`
        that explain the policy are not offenders.
        """
        # Matched as `//host`, not as a bare substring. `archive.org` joined
        # COVER_HOSTS when Open Library's redirect chain was traced, and it is a
        # real domain that appears in third-party prose: sqlalchemy's Oracle
        # dialect links to it in a docstring, which turned this rule red in CI
        # against code that builds no URL at all. Requiring the scheme separator
        # keeps exactly what the rule is for, a module assembling a cover URL,
        # and cannot match a mention.
        hosts = [
            "//" + host.removeprefix("https://").removeprefix("*.")
            for host in covers.COVER_HOSTS
        ]

        offenders: list[str] = []
        for path in self.modules():
            for node in ast.walk(ast.parse(path.read_text())):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                for host in hosts:
                    if host in node.value:
                        offenders.append(f"{path.name}:{node.lineno} ({host})")

        assert offenders == [], (
            "only covers.py may know an image host: " + ", ".join(offenders)
        )

    def test_it_reads_the_backend_at_all(self):
        # A glob that matched nothing would make both tests above pass forever.
        assert len(self.modules()) > 20


class TestOutcomesAreCounted:
    """Covers failed silently once: the only trace this module left was a
    WARNING for a URL it refused, so five different failures looked identical
    from outside. Every ending is counted now, and the counts are what a
    backfill reports."""

    async def test_a_verified_cover_counts_as_verified(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            await covers.resolve(ENGLISH)
        assert covers.outcome_counts()[covers.CoverOutcome.VERIFIED.value] == 1

    async def test_a_blip_counts_as_unverified(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=DNB).mock(return_value=httpx.Response(503))
            await covers.resolve(ENGLISH)
        assert covers.outcome_counts()[covers.CoverOutcome.UNVERIFIED.value] == 1

    async def test_two_404s_count_as_no_candidate(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=DNB).mock(return_value=httpx.Response(404))
            assert await covers.resolve(ENGLISH) is None
        assert covers.outcome_counts()[covers.CoverOutcome.NO_CANDIDATE.value] == 1


class _Raw(httpx.SyncByteStream):
    """Bytes handed over exactly as given, whatever the headers claim.

    `httpx.Response(content=...)` decodes eagerly against `content-encoding`, so
    a response whose header **lies** cannot be built that way: it raises
    `DecodingError` in the test rather than in the code under test. A stream is
    not read at construction.
    """

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __iter__(self):
        yield self._payload


class _Trickle(httpx.SyncByteStream):
    """A body that never ends and never idles long enough to time out.

    Every chunk arrives inside `covers.TIMEOUT_SECONDS`, so httpx is satisfied
    on every read and the connection stays open for as long as the sender wants.
    That is the shape a per-operation timeout cannot see.
    """

    def __iter__(self):
        for _ in range(1000):
            sleep(0.01)
            yield b"\xff\xd8\xff"


class TestDownloading:
    """A hotlinked cover depends on the image service, the URL not rotting, the
    pod's egress, every reader's browser and the CSP. Four of the five are
    outside this app, so the bytes are fetched once and served from here."""

    def test_it_returns_the_bytes_and_the_sniffed_extension(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            fetched = covers.download(covers.open_library_url(ENGLISH))
        assert fetched is not None
        assert fetched[1] == "jpg"

    def test_the_extension_comes_from_the_bytes_not_the_url(self):
        """The URL is a third party's. `portal.dnb.de/opac/mvb/cover?isbn=` has
        no extension in it at all, and a `.jpg` in a path is not evidence."""
        png = httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/jpeg"}
        )
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=png)
            fetched = covers.download(covers.open_library_url(ENGLISH))
        assert fetched is not None
        assert fetched[1] == "png"

    def test_a_body_over_the_cap_is_refused(self):
        oversized = httpx.Response(
            200,
            content=b"\xff\xd8\xff" + b"\x00" * (covers.MAX_COVER_BYTES + 1),
            headers={"content-type": "image/jpeg"},
        )
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=oversized)
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_something_that_is_not_an_image_is_refused(self):
        """A 200 carrying an error page is how both services report a bad day."""
        page = httpx.Response(
            200, content=b"<html>no cover</html>", headers={"content-type": "text/html"}
        )
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=page)
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_a_refused_connection_is_not_an_exception(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectError("no route")
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_compression_is_not_requested(self):
        """`iter_raw` alone would hand `sniff_image_extension` a gzip header.

        The pair is the fix. `iter_bytes` decoded a whole chunk before the cap
        could look at it, measured on httpx 0.28.1 at 67,108,864 bytes counted
        against an 8,192 byte limit; `iter_raw` never expands, and `identity`
        is what keeps the raw bytes and the image the same thing. It costs
        nothing: JPEG, PNG and WebP are already compressed.
        """
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            covers.download(covers.open_library_url(ENGLISH))

        assert route.calls.last.request.headers["accept-encoding"] == "identity"

    def test_a_body_carrying_an_encoding_is_not_expanded_to_get_past_the_cap(self):
        """Raw bytes, so what the cap counts is what arrives.

        A 32 MiB image gzipped is a few KB on the wire. Counting the decoded
        stream would allocate all of it before comparing; counting raw lets it
        through as a few KB and then fails the magic byte sniff, which is a
        refusal that costs nothing.
        """
        payload = b"\xff\xd8\xff" + b"\x00" * (32 * 1024 * 1024)
        compressed = gzip.compress(payload)
        assert len(compressed) < covers.MAX_COVER_BYTES

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200,
                    content=compressed,
                    headers={
                        "content-type": "image/jpeg",
                        "content-encoding": "gzip",
                    },
                )
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_a_body_labelled_gzip_is_refused_even_when_the_bytes_look_fine(self):
        """The braces to `identity`'s belt, and the case the sniff cannot catch.

        These bytes are a real JPEG, and the header says gzip. `iter_raw` does
        not decode, so without this check they sniff as `jpg` and are written to
        disk as the cover, having never been the thing the server claimed to
        send. Refusing on the header is what keeps "the raw bytes" and "the
        image" the same thing.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200,
                    stream=_Raw(JPEG_BYTES),
                    headers={
                        "content-type": "image/jpeg",
                        "content-encoding": "gzip",
                    },
                )
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_an_identity_encoding_header_is_what_was_asked_for(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200,
                    content=JPEG_BYTES,
                    headers={
                        "content-type": "image/jpeg",
                        "content-encoding": "identity",
                    },
                )
            )
            fetched = covers.download(covers.open_library_url(ENGLISH))

        assert fetched is not None
        assert fetched[1] == "jpg"

    def test_a_trickled_body_stops_at_the_budget(self):
        """httpx's timeout is per read, so it does not bound a download at all.

        Measured on httpx 0.28.1, twenty bytes at 0.9s apiece completed in 18.0s
        under a 1.0s timeout. The deadline was checked between hops and before
        the read; a service dribbling chunks inside `TIMEOUT_SECONDS` sailed
        past `INTERACTIVE_BUDGET_SECONDS` with a person waiting on it.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200,
                    stream=_Trickle(),
                    headers={"content-type": "image/jpeg"},
                )
            )
            started = monotonic()
            fetched = covers.download(
                covers.open_library_url(ENGLISH), deadline=monotonic() + 0.2
            )
            spent = monotonic() - started

        assert fetched is None
        assert spent < 3.0


class TestStoring:
    def test_it_writes_the_file_and_returns_a_local_url(self, covers_dir):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            stored = covers.store(7, covers.open_library_url(ENGLISH))

        assert stored == "/covers/7.jpg"
        assert (covers_dir / "7.jpg").read_bytes().startswith(b"\xff\xd8\xff")
        assert covers.outcome_counts()[covers.CoverOutcome.DOWNLOADED.value] == 1

    def test_a_failed_download_stores_nothing_and_says_so(self, covers_dir):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            assert covers.store(7, covers.open_library_url(ENGLISH)) is None

        assert list(covers_dir.iterdir()) == []
        assert covers.outcome_counts()[covers.CoverOutcome.DOWNLOAD_FAILED.value] == 1

    def test_it_replaces_a_cover_stored_in_another_format(self, covers_dir):
        """Two formats of the same book both existing means which one is served
        depends on lookup order. `uploads.replace_image` owns that rule."""
        (covers_dir / "7.png").write_bytes(PNG_BYTES)

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            covers.store(7, covers.open_library_url(ENGLISH))

        assert not (covers_dir / "7.png").exists()
        assert (covers_dir / "7.jpg").exists()


class TestWhatIsOnDisk:
    """Files are the one thing a database row does not carry with it, so this is
    what the rest of the app asks instead of trusting `cover_url`."""

    def test_it_finds_a_stored_cover_in_any_format(self, covers_dir):
        (covers_dir / "7.webp").write_bytes(WEBP_BYTES)
        assert covers.stored_path(7) is not None
        assert covers.local_url_for(7) == "/covers/7.webp"

    def test_a_book_with_no_file_has_none(self, covers_dir):
        assert covers.stored_path(7) is None
        assert covers.local_url_for(7) is None

    def test_it_lists_every_book_id_with_a_file(self, covers_dir):
        (covers_dir / "7.jpg").write_bytes(JPEG_BYTES)
        (covers_dir / "9.png").write_bytes(PNG_BYTES)

        assert covers.stored_ids() == {7, 9}

    def test_the_login_background_is_not_a_book(self, covers_dir):
        """It lives in this directory and belongs to no book, so a scan that
        counted it would report a cover for whichever id it parsed to."""
        (covers_dir / "login_bg.png").write_bytes(PNG_BYTES)

        assert covers.stored_ids() == set()

    def test_forgetting_removes_every_format(self, covers_dir):
        """SQLite reuses an id once the highest row goes, so a leftover file is
        the next book's cover."""
        (covers_dir / "7.jpg").write_bytes(JPEG_BYTES)
        (covers_dir / "7.png").write_bytes(PNG_BYTES)

        covers.forget(7)

        assert covers.stored_ids() == set()

    def test_adopting_moves_a_cover_to_another_book(self, covers_dir):
        """A merge lets the keeper absorb the loser's `cover_url`, which names a
        file about to be deleted with the loser."""
        (covers_dir / "9.jpg").write_bytes(JPEG_BYTES)

        assert covers.adopt(4, 9) == "/covers/4.jpg"
        assert covers.stored_ids() == {4}

    def test_adopting_a_cover_that_is_not_there_answers_none(self, covers_dir):
        assert covers.adopt(4, 9) is None

    def test_the_adoption_url_is_known_before_anything_moves(self, covers_dir):
        """The half a merge needs before it commits. It has to answer what the
        row will say without writing the file the row will name, or the move
        sits inside a transaction that can still roll back."""
        (covers_dir / "9.jpg").write_bytes(JPEG_BYTES)

        assert covers.adoption_url(4, 9) == "/covers/4.jpg"
        assert covers.stored_ids() == {9}

    def test_the_adoption_url_agrees_with_what_adopting_produces(self, covers_dir):
        """Two spellings of one answer, which is a thing that drifts. A merge
        commits the first and performs the second, so a disagreement is a row
        pointing at a file nobody wrote.

        Pins the code paths at one instant, and deliberately not the gap
        between the two reads: a cover replaced on the loser mid-merge is a
        real, narrow window that `adoption_url`'s docstring states and the
        backfill repairs. A test cannot close it and should not imply it has.
        """
        (covers_dir / "9.png").write_bytes(PNG_BYTES)

        planned = covers.adoption_url(4, 9)

        assert planned == covers.adopt(4, 9)

    def test_there_is_no_adoption_url_without_a_file(self, covers_dir):
        assert covers.adoption_url(4, 9) is None


class TestResolveAndStore:
    """The whole add path in one call. The suite stubs this out by default, so
    these put the real one back: see `conftest.offline_covers`."""

    @pytest.fixture(autouse=True)
    def real(self, monkeypatch):
        monkeypatch.setattr(covers, "resolve_and_store", REAL_RESOLVE_AND_STORE)

    def test_a_supplied_url_is_downloaded_and_replaced_by_the_local_one(self, covers_dir):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            result = covers.resolve_and_store(3, ENGLISH, covers.open_library_url(ENGLISH))
        assert result == "/covers/3.jpg"

    def test_a_dead_download_falls_back_to_the_remote_url(self, covers_dir):
        """Degrading to today's behaviour, not to no cover: the URL may well
        work from the reader's browser even when it does not from the pod."""
        supplied = covers.open_library_url(ENGLISH)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectError("no route")
            )
            assert covers.resolve_and_store(3, ENGLISH, supplied) == supplied

    def test_with_no_supplied_url_it_asks_the_image_services(self, covers_dir):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            assert covers.resolve_and_store(3, ENGLISH, None) == "/covers/3.jpg"

    def test_a_spent_budget_keeps_the_url_without_downloading_it(self, covers_dir):
        """The interactive path has a person waiting. Past the budget the best
        candidate is stored unverified and the bytes are left to the backfill,
        which has nothing waiting on it."""
        supplied = covers.open_library_url(ENGLISH)
        with respx.mock:
            result = covers.resolve_and_store(3, ENGLISH, supplied, budget=0)

        assert result == supplied
        assert list(covers_dir.iterdir()) == []

    def test_without_a_budget_it_still_downloads(self, covers_dir):
        """The backfill passes none, so nothing about the ceiling reaches it."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            assert covers.resolve_and_store(3, ENGLISH, None) == "/covers/3.jpg"

    def test_a_book_with_no_isbn_and_no_url_gets_nothing(self, covers_dir):
        with respx.mock:
            assert covers.resolve_and_store(3, None, None) is None

    def test_a_local_url_with_no_file_behind_it_re_resolves(self, covers_dir):
        """The column and the directory can drift. Trusting the column here is
        what would let a book claim a cover it does not have, for good."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            assert covers.resolve_and_store(3, ENGLISH, "/covers/3.jpg") == "/covers/3.jpg"

        assert (covers_dir / "3.jpg").exists()


class TestTheInteractiveBudget:
    """Adding one book was up to three candidate checks and a download at
    `TIMEOUT_SECONDS` each: 24 seconds when both image services blackhole rather
    than refuse. The import path avoids that by deferring to the backfill, which
    the interactive path cannot do, so it gets a ceiling instead."""

    def test_a_spent_budget_stops_the_resolve_asking_anything(self):
        with respx.mock:
            assert await_resolve_with_deadline(ENGLISH, 0.0) is None

    def test_each_request_is_capped_at_what_is_left(self):
        """Otherwise the real ceiling is the budget plus one whole timeout."""
        assert covers._time_left(None) is None
        left = covers._time_left(monotonic() + 1.5)
        assert left is not None and 0 < left <= 1.5

    def test_the_budget_is_shorter_than_a_single_timeout_chain(self):
        # Three checks plus a download at six seconds each is the 24 this bounds.
        assert covers.INTERACTIVE_BUDGET_SECONDS < covers.TIMEOUT_SECONDS


class TestWhatThisServerMayConnectTo:
    """`is_renderable` says what a browser may load; this says what the
    application itself may open a connection to. Different question, different
    answer, and conflating them is the hole.

    `cover_url` arrives on `BookCreate` from a member, so without this an
    authenticated caller chooses which host the server connects to. The blind
    half of that predates covers being stored: `resolve` has put a supplied URL
    at the front of its candidate list and called `_check` on it since the check
    existed. Storing the bytes turned a blind request into a read primitive.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://covers.openlibrary.org/b/isbn/x-L.jpg",
            "https://portal.dnb.de/opac/mvb/cover?isbn=x",
            "https://books.google.com/books/content?id=x",
            "https://lh3.googleusercontent.com/x",
        ],
    )
    def test_the_image_services_are_fetchable(self, url):
        assert covers.is_fetchable(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.test/x.jpg",
            "http://covers.openlibrary.org/b/isbn/x-L.jpg",
            "https://covers.openlibrary.org:8080/x.jpg",
            # Reads as a listed host to a person and resolves to evil.test in
            # every client.
            "https://covers.openlibrary.org@evil.test/x.jpg",
            # A CSP wildcard means any subdomain, not the bare domain.
            "https://googleusercontent.com/x",
            "https://notcovers.openlibrary.org.evil.test/x",
            "/covers/1.jpg",
            "",
            # A URL that cannot be parsed. `urlsplit` raises on an unterminated
            # IPv6 literal and `.port` raises on a port that is not a number or
            # is out of range, and both call sites test this outside their own
            # exception handling. One stored URL of this shape 500ed the
            # backfill for every member, permanently.
            "https://covers.openlibrary.org:99999/x",
            "https://covers.openlibrary.org:abc/x",
            "https://[::1/x",
            # Where Open Library's redirects land, and the shapes that only look
            # like it. `notus.archive.org` matches the suffix `us.archive.org`
            # and is still refused, because the wildcard is a label boundary and
            # not a substring.
            "https://archive.org.attacker.test/x",
            "https://evil.us.archive.org.attacker.test/x",
            "https://us.archive.org.evil.test/x",
            "http://archive.org/x",
            "https://xarchive.org/x",
            "https://notus.archive.org/x",
        ],
    )
    def test_everything_else_is_not(self, url):
        assert covers.is_fetchable(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            # The two hops Open Library actually takes. Measured against the
            # live service: covers.openlibrary.org 302s to archive.org, which
            # 302s to a numbered ia<n>.us.archive.org. Refusing either of these
            # refuses every Open Library cover, which is what the first live
            # backfill reported as `unreachable: 4` of 4.
            "https://archive.org/download/l_covers_0014/x.zip/1-L.jpg",
            "https://ia800505.us.archive.org/view_archive.php?archive=/35/items/x",
        ],
    )
    def test_where_open_library_redirects_to_is_reachable(self, url):
        assert covers.is_fetchable(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://books.google.com:99999/x.jpg",
            "https://books.google.com:abc/x.jpg",
            "https://[::1/x.jpg",
        ],
    )
    def test_an_unparseable_url_is_refused_rather_than_raising(self, url):
        """`storable` admits these: it only tests the `https://` prefix. So they
        reach the fetch, and a raise there is a stored, permanent denial of
        service rather than one bad request."""
        assert covers.is_fetchable(url) is False
        assert covers.download(url) is None

    def test_a_renderable_url_is_not_automatically_fetchable(self):
        """`storable` has to keep admitting any https URL: that is the hotlink
        fallback when a download fails."""
        assert covers.storable("https://evil.test/x.jpg") == "https://evil.test/x.jpg"
        assert covers.is_fetchable("https://evil.test/x.jpg") is False


class TestFetchesAreRefusedBeforeTheyHappen:
    def test_an_unlisted_host_is_never_requested(self):
        """respx fails the test on any unmocked request, and nothing is mocked."""
        with respx.mock:
            assert covers.download("https://evil.test/x.jpg") is None

    def test_a_supplied_url_on_an_unlisted_host_is_not_checked_either(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=DNB).mock(return_value=httpx.Response(404))
            assert await_resolve(ENGLISH, "https://evil.test/x.jpg") is None

    def test_a_redirect_off_the_list_is_refused_rather_than_followed(self):
        """Following it is what turns one allowed host into a way to reach any
        other, including private address space and a scheme downgrade."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(302, headers={"location": "http://10.0.0.1/x.jpg"})
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_a_redirect_within_the_list_is_followed(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(302, headers={"location": DNB + "?isbn=x"})
            )
            mock.get(url__startswith=DNB).mock(return_value=image())

            fetched = covers.download(covers.open_library_url(ENGLISH))

        assert fetched is not None

    def test_a_redirect_loop_gives_up(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    302, headers={"location": covers.open_library_url(ENGLISH)}
                )
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None


def await_resolve(isbn: str, supplied: str) -> str | None:
    """`resolve` from a sync test, on its own loop."""
    import asyncio

    return asyncio.run(covers.resolve(isbn, supplied))


def await_resolve_with_deadline(isbn: str, budget: float) -> str | None:
    """`resolve` with an already spent budget, from a sync test."""
    import asyncio

    return asyncio.run(covers.resolve(isbn, deadline=monotonic() + budget))
