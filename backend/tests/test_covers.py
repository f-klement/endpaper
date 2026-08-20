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
from pathlib import Path

import httpx
import pytest
import respx

import covers

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
            if ".venv" not in path.parts
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
        hosts = [
            host.removeprefix("https://").removeprefix("*.")
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
