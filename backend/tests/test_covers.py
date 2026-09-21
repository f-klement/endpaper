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
import asyncio
import gzip
from pathlib import Path
from time import monotonic
from typing import Final
from urllib.parse import urlsplit

import httpx
import pytest
import respx

import cover_store
import covers
import fetch
from tests.conftest import REAL_RESOLVE_AND_STORE
from tests.helpers import (
    AT_ANY_COVER_HOST,
    AT_DNB_COVERS,
    AT_GOOGLE_BOOKS_COVERS,
    AT_OPEN_LIBRARY_COVERS,
    JPEG_BYTES,
    NOT_AN_IMAGE,
    PNG_BYTES,
    WEBP_BYTES,
)
from tests.test_house_rules import _is_vendored

#: The two image services as a member, a candidate builder or a `Location`
#: spells them. Assertions about what this module *produces* use these.
OPEN_LIBRARY = "https://covers.openlibrary.org/"
DNB = "https://portal.dnb.de/opac/mvb/cover"

#: The same two as they are **addressed**, which is what a route has to match.
#: `covers._client` pins the address and respx matches below that transport:
#: `tests/helpers.AT_OPEN_LIBRARY_COVERS` has the whole reason, and the resolver
#: that makes it so is installed for every test by `tests/conftest.py`.
AT_OPEN_LIBRARY = AT_OPEN_LIBRARY_COVERS
AT_DNB = AT_DNB_COVERS

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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_404_moves_on_to_the_next_service(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=AT_DNB).mock(return_value=image())

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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(404))

            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_timeout_keeps_the_url_too(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectTimeout("slow")
            )
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(404))

            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_verified_cover_beats_an_unverifiable_one(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=AT_DNB).mock(return_value=image())

            assert await covers.resolve(ENGLISH) == covers.dnb_url(ENGLISH)


class TestASuppliedUrl:
    """A URL from a volume record is not a guess: it exists by construction."""

    SUPPLIED = "https://books.google.com/thumb.jpg"
    AT_SUPPLIED = f"{AT_GOOGLE_BOOKS_COVERS}thumb.jpg"

    @pytest.mark.asyncio
    async def test_it_is_tried_first_and_kept(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(self.AT_SUPPLIED).mock(return_value=image())
            mock.get(url__regex=r".*").mock(return_value=image())

            assert await covers.resolve(ENGLISH, self.SUPPLIED) == self.SUPPLIED

    @pytest.mark.asyncio
    async def test_a_dead_supplied_url_falls_through(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(self.AT_SUPPLIED).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())

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

    @pytest.mark.parametrize("entry", covers.COVER_HOSTS)
    def test_every_listed_entry_is_a_host_and_nothing_else(self, entry):
        """Two readers with two grammars, and the shape is what keeps them agreeing.

        `middleware.py` splices each entry verbatim into the CSP's `img-src`,
        where a path and a port are part of the source. `is_fetchable` compares
        `urlsplit(listed).hostname`, which **discards** both. So an entry
        carrying either means two different things, and the one it means to the
        fetch is the wider: the whole host on 443, against the one listed path.
        Wider at the fetch than at the render is the wrong direction for the
        tuple that closed the SSRF.

        **A round trip rather than a list of what an entry may not carry**, and
        the difference is not tidiness. The list was four arms and
        `https://books.google.com?` passed all four: `urlsplit` reads the `?` as
        an empty query, so path, query, fragment, port and userinfo are all
        clean, and the CSP still receives a source the fetch reader does not.
        Reconstructing from what the fetch reader actually reads leaves nothing
        to enumerate. The scheme is the test beside this one; this asserts that
        an entry is that scheme and a host and nothing else.

        **The character arm survives the round trip and is not redundant.**
        `urlsplit` keeps a space inside the netloc, so
        `https://books.google.com evil.test` reconstructs to itself and is two
        sources to the CSP and one impossible host to the fetch. A `;` is the
        sharper half: before any `/` it stays in the netloc too, and in the
        policy it ends `img-src` and starts a directive of the entry's choosing.
        """
        parsed = urlsplit(entry)

        assert entry == f"{parsed.scheme}://{parsed.hostname}", entry
        assert not any(c.isspace() or c == ";" for c in entry), entry


_BACKEND: Final = Path(__file__).resolve().parent.parent


def _our_modules(root: Path = _BACKEND) -> list[Path]:
    """Every module of ours but `covers.py`, which is the one that may.

    **`root` is what lets the diagonal in `test_house_rules.py` drive this**,
    against a tree with vendored code planted in it. Calling the shared
    predicate is what makes the walk right; taking the tree is what lets
    something check that it does.

    **What vendored means is `test_house_rules._is_vendored`.** This walk
    named `.venv` and `site-packages` for itself, which was right about
    `site-packages` and blind to `.uv-cache/`: the pipeline sets
    `UV_CACHE_DIR` inside `backend/`, so it read third party source there
    and nowhere a developer would see it. The `site-packages` half is now in
    the shared predicate, put there because this module and `test_marc.py`
    reached it independently.

    **The two names left are matched relative to `_BACKEND`**, not against
    the whole path: asked absolutely, a checkout under a directory called
    `tests` empties this walk and every rule below it passes on nothing.

    **The one exemption is a path and not a basename**, which is what says
    `routers/covers.py` is walked. Spelled `path.name`, this tree's two files
    called `covers.py` were both exempt, so the router that serves the store
    could hold an image host or the prefix and neither rule below would see
    it. Measured before this exemption became a path: 85 files walked,
    `routers/covers.py` not among them. It is 86 with it.
    """
    found = [
        path
        for path in root.rglob("*.py")
        if not _is_vendored(path, root)
        and not {"tests", "migrations"}
        & set(path.relative_to(root).parts)
        and path.relative_to(root).as_posix() != "covers.py"
    ]
    # The packages it must cover rather than a number: a count is satisfied
    # by a walk that lost a whole directory. See `test_accounts._sources`.
    assert {"routers", "schemas"} <= {path.parent.name for path in found}, found
    return found


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

    def modules(self) -> list[Path]:
        """The walk, kept as a method because three tests below read it."""
        return _our_modules()

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


class TestNoOtherModuleDecidesWhetherACoverIsLocal:
    """House rule: `covers.py` is the only module that answers this question.

    Three readers of `LOCAL_COVER_PREFIX` live there, and `covers.is_local` is
    the one every other module asks.

    "An uploaded cover outranks a remote one" is read by every automated writer,
    and `google_books.py` spelled it `(current_cover or "").startswith(
    "/covers/")` against the constant `covers.py` holds. A second spelling does
    not fail loudly: it answers correctly until the prefix moves, and from then
    on that writer overrules an upload the other one protects, with the stored
    row looking correct from either end.

    **`TestNoOtherModuleBuildsACoverUrl` does not reach this**, which is why
    there are two rules and not one arm on the first. That walk looks for a
    module **building** a cover URL out of a host literal; a module that only
    **classifies** one builds nothing and stays green.

    Two tests, because the constant and its value are two roads to the same
    duplicate: import the name and test it yourself, or write the prefix out
    again. An `import ... as` is caught by the first, which reads the imported
    name rather than the local one.

    **What this does not catch**, measured by the security seat against this
    class rather than guessed: a prefix **assembled** rather than written.
    `(book.cover_url or "").startswith("/cover" + "s/")` passes both tests, and
    so do `"".join(("/cover", "s/"))`, `f"/cover{'s'}/"` and a `getattr` naming
    the constant as a string, because `ast.parse` folds adjacent literals and
    nothing else. **An f-string is only a blind spot when the prefix is what it
    assembles**: `f"/covers/{name}"` carries the whole prefix as one constant
    and is caught, which is how `routers/settings.py` was found. A slice
    comparison, an `in` and a `removeprefix` are not blind spots either: each
    has to name the constant or spell the prefix as one literal, and an arm
    above sees it. The behavioural guard is
    `test_google_books.py::TestMergeInto::test_the_local_cover_rule_is_covers_own`,
    which catches any of them at the one writer it covers.
    """

    PREFIX_NAME: Final = "LOCAL_COVER_PREFIX"

    #: Where the literal stands for some reason other than deciding whether a
    #: cover is local, **and how many times in each**. A count and not a name:
    #: exempting the file admits the next occurrence in it silently, and the
    #: next occurrence is as likely as not to be the thing this rule exists to
    #: refuse. Keyed by path rather than basename, because this tree has two
    #: `settings.py`.
    #:
    #: `errors.API_PREFIXES` routes by path, so that a missing cover requested
    #: by an `<img>` answers JSON rather than a whole HTML error page. Not this
    #: rule's question, and the same string.
    #:
    #: **Two concepts sharing a spelling, rather than one derivable from the
    #: other**, and the tell is the other five members of that tuple: `/api/`,
    #: `/auth/`, `/openapi.json`, `/docs` and `/redoc` have no module to ask,
    #: and a path added to it next may have nothing to do with covers. The two
    #: do move together, but neither derives from the other: both follow the
    #: path the cover route is mounted at, which is a third fact and is spelled
    #: `"/covers"` at `routers/covers.py`'s `APIRouter(prefix=...)`. **That
    #: literal is invisible here because it has no trailing slash**, not
    #: because of where it lives: the walk above reads that file, so the whole
    #: prefix written out in it would be counted like anywhere else.
    ELSEWHERE_FOR_ANOTHER_REASON: Final[dict[str, int]] = {"errors.py": 1}

    @classmethod
    def _names_the_constant(cls, tree: ast.AST) -> list[int]:
        """Line numbers where an expression names the constant.

        The three nodes that can carry the name: the import itself, which
        catches an `as` alias because it reads the imported name; a bare use of
        what that import bound; and the `covers.` attribute spelling, which is
        how every other module in this tree reaches the module.
        """
        found: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                named = any(a.name == cls.PREFIX_NAME for a in node.names)
            elif isinstance(node, ast.Name):
                named = node.id == cls.PREFIX_NAME
            elif isinstance(node, ast.Attribute):
                named = node.attr == cls.PREFIX_NAME
            else:
                continue
            if named:
                found.append(node.lineno)
        return found

    @pytest.mark.parametrize(
        "source",
        [
            "from covers import LOCAL_COVER_PREFIX",
            "from covers import LOCAL_COVER_PREFIX as p",
            "local = url.startswith(LOCAL_COVER_PREFIX)",
            "local = url.startswith(covers.LOCAL_COVER_PREFIX)",
        ],
    )
    def test_the_rule_reports_every_spelling_it_exists_for(self, source: str):
        """**The arm this class did not have**, and the one a mutation walked
        through: with the `Attribute` branch replaced by `named = False` the
        whole file stayed green, because a rule that reports nothing reports no
        offenders either. Four sources over three branches, the import twice
        because an `as` alias is a second way into it, so dropping any branch
        names a case here rather than passing quietly."""
        assert self._names_the_constant(ast.parse(source)) == [1]

    @pytest.mark.parametrize(
        "source",
        ["local = covers.is_local(url)", "prefix = LOCAL_COVER_PREFIXES"],
    )
    def test_asking_covers_is_not_reported(self, source: str):
        assert self._names_the_constant(ast.parse(source)) == []

    def test_no_module_reads_the_constant(self):
        offenders = [
            f"{path.relative_to(_BACKEND)}:{line}"
            for path in _our_modules()
            for line in self._names_the_constant(ast.parse(path.read_text()))
        ]

        assert offenders == [], (
            "only covers.py may read LOCAL_COVER_PREFIX; ask covers.is_local: "
            + ", ".join(offenders)
        )

    #: How many times `covers.py` itself may read the constant: the two
    #: classifiers and the one builder.
    #:
    #: **Recomputed rather than stated.** The class docstring above says three,
    #: and a sentence is what a fourth reader walks past: measured, `local_url`
    #: spelling the prefix itself instead of going through `stored_url` changes
    #: no answer anywhere and no test named it.
    READERS_INSIDE_COVERS: Final = 3

    def test_covers_itself_reads_it_three_times(self):
        source = (_BACKEND / "covers.py").read_text()
        loads = [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Name)
            and node.id == self.PREFIX_NAME
            and isinstance(node.ctx, ast.Load)
        ]

        assert len(loads) == self.READERS_INSIDE_COVERS, loads

    def test_no_module_writes_the_prefix_out_again(self):
        found: dict[str, int] = {}
        for path in _our_modules():
            occurrences = sum(
                1
                for node in ast.walk(ast.parse(path.read_text()))
                if isinstance(node, ast.Constant)
                and node.value == covers.LOCAL_COVER_PREFIX
            )
            if occurrences:
                found[path.relative_to(_BACKEND).as_posix()] = occurrences

        # One equality rather than a list of offenders, so that a new
        # occurrence inside an exempt file is as loud as a new file.
        assert found == self.ELSEWHERE_FOR_ANOTHER_REASON, (
            "this spells the local cover prefix rather than asking "
            "covers.is_local; the counts above say which files may"
        )


class TestOutcomesAreCounted:
    """Covers failed silently once: the only trace this module left was a
    WARNING for a URL it refused, so five different failures looked identical
    from outside. Every ending is counted now, and the counts are what a
    backfill reports."""

    async def test_a_verified_cover_counts_as_verified(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            await covers.resolve(ENGLISH)
        assert covers.outcome_counts()[covers.CoverOutcome.VERIFIED.value] == 1

    async def test_a_blip_counts_as_unverified(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(503))
            await covers.resolve(ENGLISH)
        assert covers.outcome_counts()[covers.CoverOutcome.UNVERIFIED.value] == 1

    async def test_two_404s_count_as_no_candidate(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(404))
            assert await covers.resolve(ENGLISH) is None
        assert covers.outcome_counts()[covers.CoverOutcome.NO_CANDIDATE.value] == 1


class _Raw(httpx.AsyncByteStream):
    """Bytes handed over exactly as given, whatever the headers claim.

    `httpx.Response(content=...)` decodes eagerly against `content-encoding`, so
    a response whose header **lies** cannot be built that way: it raises
    `DecodingError` in the test rather than in the code under test. A stream is
    not read at construction.
    """

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def __aiter__(self):
        yield self._payload


class _AsyncTrickle(httpx.AsyncByteStream):
    """A body that arrives slowly and never idles long enough to time out.

    Every chunk arrives inside the client's own read timeout, so httpx is
    satisfied on every read and the connection stays open for as long as the
    sender wants. That is the shape a per operation timeout cannot see, and
    the only thing that stops it is the hop's wall clock bound.

    **`asyncio.sleep`, not `time.sleep`.** Both cover walks are coroutines, and
    a blocking sleep inside one holds the event loop, so the `asyncio.timeout`
    under test never gets to fire and the guard passes on a module that has
    none.

    **Finite, and the count is the guard's own bound rather than realism.** A
    body that genuinely never ends makes a run with the bound removed unbounded
    too: measured, deleting the `asyncio.timeout` from `covers._download` left a
    mutation run at 69 tests and climbing with nothing left to stop it, because
    that wrapper is now the only thing in that loop that watches a clock. Ending
    makes a missing bound a **red** assertion instead of a suite nobody can wait
    out.

    **Each caller picks `chunks`, and one default would break one of them.** The
    download guard wants the body to end soon after the bound would have cut, so
    six is enough. The check guard wants the first 512 bytes to be **far** away,
    because what it is watching for is `aiter_raw(512)` coming back, and at
    three bytes a chunk a short body hands the buffer its remainder at the end
    and answers True inside the budget anyway. 200 is 600 bytes.
    """

    CHUNK = b"\xff\xd8\xff"

    def __init__(self, *, interval: float, chunks: int) -> None:
        self._interval = interval
        self._chunks = chunks

    async def __aiter__(self):
        for _ in range(self._chunks):
            await asyncio.sleep(self._interval)
            yield self.CHUNK


async def _slow_redirect_to_the_dnb(request):
    """A 302 that spends most of a budget arriving, for the two hop guards.

    A redirect carries no body, so a hop cannot be made slow with a stream: the
    delay has to be in answering at all, which is what a `side_effect` is for.
    """
    await asyncio.sleep(0.8)
    return httpx.Response(302, headers={"location": DNB + "?isbn=x"})


class _NeverAnswers(httpx.AsyncByteStream):
    """Headers, and then nothing for longer than any bound here.

    The shape a per read timeout **does** eventually catch, at the client's own
    figure rather than at the caller's budget, which is why a guard using it
    asserts on the seconds and not only on the verdict: without the hop bound
    the answer is still None, ten seconds later. It is here because the trickle
    above cannot reach `_check`, which returns on the first chunk, so a guard on
    that function has to be about a chunk that never comes.
    """

    async def __aiter__(self):
        await asyncio.sleep(30)
        yield b"\xff\xd8\xff"


class TestDownloading:
    """A hotlinked cover depends on the image service, the URL not rotting, the
    pod's egress, every reader's browser and the CSP. Four of the five are
    outside this app, so the bytes are fetched once and served from here."""

    def test_it_returns_the_bytes(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            fetched = covers.download(covers.open_library_url(ENGLISH))
        assert fetched is not None
        assert fetched.startswith(b"\xff\xd8\xff")

    def test_a_200_that_is_not_an_image_is_refused(self):
        """Both services report "no cover" on a bad day with an error page and
        a 200, and the bytes are the only thing that says so."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, content=NOT_AN_IMAGE)
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_a_body_over_the_cap_is_refused(self):
        oversized = httpx.Response(
            200,
            content=b"\xff\xd8\xff" + b"\x00" * (covers.MAX_COVER_BYTES + 1),
            headers={"content-type": "image/jpeg"},
        )
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=oversized)
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_something_that_is_not_an_image_is_refused(self):
        """A 200 carrying an error page is how both services report a bad day."""
        page = httpx.Response(
            200, content=b"<html>no cover</html>", headers={"content-type": "text/html"}
        )
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=page)
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_a_refused_connection_is_not_an_exception(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
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
            route = mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
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
        assert fetched.startswith(b"\xff\xd8\xff")

    def test_a_trickled_body_stops_at_the_budget(self):
        """httpx's timeout is per read, so it does not bound a download at all.

        **The chunks arrive at 0.98x of the budget, which is the shape, and the
        bound is 1.4x of it, which is the measurement.** The version this
        replaces trickled at 0.01s against a 0.2s budget and allowed 3.0s: at
        fifteen times the budget it passed on the code that overshot and on the
        code that does not, so it distinguished nothing. Measured on this tree,
        the overshooting shape returned after **1.973s** against 1.0s, because
        the clock was consulted only once a chunk had already arrived and the
        read in flight had a full budget of its own.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200,
                    stream=_AsyncTrickle(interval=0.98, chunks=6),
                    headers={"content-type": "image/jpeg"},
                )
            )
            started = monotonic()
            fetched = covers.download(
                covers.open_library_url(ENGLISH), deadline=monotonic() + 1.0
            )
            spent = monotonic() - started

        assert fetched is None
        assert spent < 1.4


class TestStoring:
    def test_it_writes_the_file_and_returns_a_local_url(self, covers_dir):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            stored = covers.store(7, covers.open_library_url(ENGLISH))

        assert stored == "/covers/7.jpg"
        assert (covers_dir / "7.jpg").read_bytes().startswith(b"\xff\xd8\xff")
        assert covers.outcome_counts()[covers.CoverOutcome.DOWNLOADED.value] == 1

    def test_a_failed_download_stores_nothing_and_says_so(self, covers_dir):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            assert covers.store(7, covers.open_library_url(ENGLISH)) is None

        assert list(covers_dir.iterdir()) == []
        assert covers.outcome_counts()[covers.CoverOutcome.DOWNLOAD_FAILED.value] == 1

    def test_the_name_comes_from_the_bytes_not_the_url(self, covers_dir):
        """The URL is a third party's. `portal.dnb.de/opac/mvb/cover?isbn=` has
        no extension in it at all, and a `.jpg` in a path is not evidence.

        Asserted through the whole store path rather than off `download`, which
        hands the bytes on unnamed: `cover_store` is what names the file.
        """
        png = httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/jpeg"})
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=png)
            stored = covers.store(7, covers.open_library_url(ENGLISH))

        assert stored == "/covers/7.png"
        assert (covers_dir / "7.png").is_file()

    def test_it_replaces_a_cover_stored_in_another_format(self, covers_dir):
        """Two formats of the same book both existing means which one is served
        depends on lookup order. `cover_store.save` owns that rule."""
        (covers_dir / "7.png").write_bytes(PNG_BYTES)

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            covers.store(7, covers.open_library_url(ENGLISH))

        assert not (covers_dir / "7.png").exists()
        assert (covers_dir / "7.jpg").exists()


class TestWhatIsOnDisk:
    """The URL a stored file is served at, which is this module's half.

    **Finding the file is `cover_store`'s and is tested there.** This class held
    three assertions on `stored_path` and `stored_ids`, which were re-exports of
    `cover_store.path_of` and `book_ids` and are gone: a test of a forwarding
    function is a test of forwarding. `tests/test_cover_store.py::
    TestFindingWhatIsStored` covers the lookups, the login background not being
    a book among them.
    """

    def test_it_builds_a_url_for_whatever_format_is_there(self, covers_dir):
        (covers_dir / "7.webp").write_bytes(WEBP_BYTES)

        assert covers.local_url_for(7) == "/covers/7.webp"

    def test_a_file_the_store_names_itself_has_a_url_too(self):
        """The login background is stored under a name rather than a book id,
        and `local_url` cannot answer for it. Its router asks this instead of
        spelling the prefix a third time."""
        assert covers.stored_url("login_bg.png") == "/covers/login_bg.png"

    def test_a_book_with_no_file_has_no_url(self, covers_dir):
        assert covers.local_url_for(7) is None

    def test_the_url_is_stable_when_a_book_holds_two_formats(
        self, covers_dir, monkeypatch
    ):
        """`ALLOWED_IMAGE_EXTENSIONS` is a frozenset and its iteration order is
        not stable between processes, and a book can hold two formats: an upload
        sweeps the losers and `backup.restore` deliberately does not.

        **`merge_books` compares against this, not against the path**, which is
        why the URL needs its own arm: `cover_store.path_of`'s stability is
        pinned in that module's tests, and a stable path with an unstable URL
        would make a merge decide differently on two runs.

        Stability, not a winner: the order is arbitrary and being the same order
        twice is the whole requirement.
        """
        (covers_dir / "7.jpg").write_bytes(JPEG_BYTES)
        (covers_dir / "7.png").write_bytes(PNG_BYTES)

        seen = set()
        for order in (["jpg", "png", "webp", "jpeg"], ["webp", "png", "jpeg", "jpg"]):
            monkeypatch.setattr(cover_store, "ALLOWED_IMAGE_EXTENSIONS", order)
            seen.add(covers.local_url_for(7))

        # `None not in`, because a lookup that stopped finding anything returns
        # {None}, which is the most stable answer there is.
        assert None not in seen
        assert len(seen) == 1

    def test_forgetting_removes_every_format(self, covers_dir):
        """SQLite reuses an id once the highest row goes, so a leftover file is
        the next book's cover."""
        (covers_dir / "7.jpg").write_bytes(JPEG_BYTES)
        (covers_dir / "7.png").write_bytes(PNG_BYTES)

        cover_store.remove(7)

        assert cover_store.book_ids() == set()

    def test_adopting_moves_a_cover_to_another_book(self, covers_dir):
        """A merge lets the keeper absorb the loser's `cover_url`, which names a
        file about to be deleted with the loser."""
        (covers_dir / "9.jpg").write_bytes(JPEG_BYTES)

        assert covers.adopt(4, 9) == "/covers/4.jpg"
        assert cover_store.book_ids() == {4}

    def test_adopting_a_cover_that_is_not_there_answers_none(self, covers_dir):
        assert covers.adopt(4, 9) is None

    def test_the_adoption_url_is_known_before_anything_moves(self, covers_dir):
        """The half a merge needs before it commits. It has to answer what the
        row will say without writing the file the row will name, or the move
        sits inside a transaction that can still roll back."""
        (covers_dir / "9.jpg").write_bytes(JPEG_BYTES)

        assert covers.adoption_url(4, 9) == "/covers/4.jpg"
        assert cover_store.book_ids() == {9}

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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            result = covers.resolve_and_store(3, ENGLISH, covers.open_library_url(ENGLISH))
        assert result == "/covers/3.jpg"

    def test_a_dead_download_falls_back_to_the_remote_url(self, covers_dir):
        """Degrading to today's behaviour, not to no cover: the URL may well
        work from the reader's browser even when it does not from the pod."""
        supplied = covers.open_library_url(ENGLISH)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectError("no route")
            )
            assert covers.resolve_and_store(3, ENGLISH, supplied) == supplied

    def test_with_no_supplied_url_it_asks_the_image_services(self, covers_dir):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            assert covers.resolve_and_store(3, ENGLISH, None) == "/covers/3.jpg"

    def test_a_book_with_no_isbn_and_no_url_gets_nothing(self, covers_dir):
        with respx.mock:
            assert covers.resolve_and_store(3, None, None) is None

    def test_a_local_url_with_no_file_behind_it_re_resolves(self, covers_dir):
        """The column and the directory can drift. Trusting the column here is
        what would let a book claim a cover it does not have, for good."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
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

    def test_a_check_of_a_trickling_service_answers_inside_the_budget(self):
        """The arm that was missing, and the one that cost the most.

        The guard this replaces read `request.extensions["timeout"]["read"]` and
        said that figure was "how long the image service's socket would actually
        have been held". It is not: it is what httpx was told to allow **per
        read**, and `_check` used to make as many reads as `aiter_raw(512)`
        needed to fill 512 bytes, consulting the clock on none of them. Measured
        on this tree at 64 bytes a chunk, a 1.0 second budget returned after
        7.900s.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200,
                    stream=_AsyncTrickle(interval=0.02, chunks=200),
                    headers={"content-type": "image/jpeg"},
                )
            )
            started = monotonic()
            verdict = _await(_check_one(covers.open_library_url(ENGLISH), budget=1.0))
            spent = monotonic() - started

        # True at all is the half that catches the buffering coming back: at
        # three bytes a chunk, `aiter_raw(512)` needs 171 of them, so the hop
        # bound cuts first and the verdict is None. `spent` is the half that
        # catches the bound going away instead, since the buffered read would
        # then finish at about 3.4s and answer True.
        assert verdict is True
        assert spent < 0.5

    def test_a_check_of_a_service_that_never_answers_stops_at_the_budget(self):
        """The arm the trickle cannot reach, since `_check` returns on a chunk.

        Without the hop bound this waits out the client's own read timeout,
        which is `fetch.TIMEOUT_SECONDS` and has nothing to do with the budget
        a person is waiting through.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200, stream=_NeverAnswers(), headers={"content-type": "image/jpeg"}
                )
            )
            started = monotonic()
            verdict = _await(_check_one(covers.open_library_url(ENGLISH), budget=1.0))
            spent = monotonic() - started

        assert verdict is None
        assert spent < 1.4

    def test_a_hop_is_bounded_even_when_no_budget_was_given(self, monkeypatch):
        """The backfill passes no deadline, and used to get no bound with it.

        `min(TIMEOUT_SECONDS, remaining)` with nothing remaining is
        `TIMEOUT_SECONDS`, so dropping the `min` and keeping only the budget
        leaves this walk unbounded. `TIMEOUT_SECONDS` is moved rather than
        waited out, because six seconds of suite time is the same evidence.
        """
        monkeypatch.setattr(covers, "TIMEOUT_SECONDS", 0.5)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    200, stream=_NeverAnswers(), headers={"content-type": "image/jpeg"}
                )
            )
            started = monotonic()
            verdict = _await(_check_one(covers.open_library_url(ENGLISH)))
            spent = monotonic() - started

        assert verdict is None
        assert spent < 1.0

    def test_a_second_hop_gets_what_the_first_one_left(self):
        """The only arm that can see `_hop_seconds` being recomputed per hop.

        **Every other guard here drives one hop, so the recomputation was
        stated and nothing could fail on it**: hoisting `_hop_seconds(deadline)`
        out of both `for` loops and reusing one value left the suite green,
        because no test in this file registers a 302 under a clock. What the
        hoist costs is the walk ceiling: each hop gets the **whole** budget
        rather than what is left, so two hops are two budgets.

        Measured with the first hop answering at 0.8 of a 1.0 second budget and
        the second never answering: shipped **1.002s**, hoisted **1.818s**. The
        bound sits between them with room on both sides rather than beside
        either.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                side_effect=_slow_redirect_to_the_dnb
            )
            mock.get(url__startswith=AT_DNB).mock(
                return_value=httpx.Response(
                    200, stream=_NeverAnswers(), headers={"content-type": "image/jpeg"}
                )
            )
            started = monotonic()
            verdict = _await(_check_one(covers.open_library_url(ENGLISH), budget=1.0))
            spent = monotonic() - started

        assert verdict is None
        assert spent < 1.4

    def test_the_budget_is_shorter_than_a_single_timeout_chain(self):
        # Three checks plus a download at six seconds each is the 24 this bounds.
        assert covers.INTERACTIVE_BUDGET_SECONDS < covers.TIMEOUT_SECONDS

    def test_a_hop_is_bounded_before_the_clients_own_read_timeout_is(self):
        """`_client`'s docstring says its `timeout=` "never binds first".

        **The arm above cannot see that, because it only bounds this constant
        from below.** Raising `covers.TIMEOUT_SECONDS` past `fetch`'s leaves it
        green and makes the docstring false with nothing red: at 12 the client's
        read timeout cuts before the hop's wall clock bound does, and the figure
        a reader was told never binds is the one that does.

        `fetch.TIMEOUT_SECONDS` is pinned at its own value one door along, so
        this side is the movable one. Same shape as
        `tests/test_opds.py::test_the_sync_deadline_is_longer_than_one_request`.
        """
        assert covers.TIMEOUT_SECONDS < fetch.TIMEOUT_SECONDS


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
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(404))
            assert await_resolve(ENGLISH, "https://evil.test/x.jpg") is None

    def test_a_redirect_off_the_list_is_refused_rather_than_followed(self):
        """Following it is what turns one allowed host into a way to reach any
        other, including private address space and a scheme downgrade."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(302, headers={"location": "http://10.0.0.1/x.jpg"})
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_a_redirect_to_an_unlisted_host_the_policy_admits_is_refused(self):
        """The arm that keeps the **hand walked** hops guarded, and the one the
        address policy took the teeth out of.

        **`is_fetchable` on every hop is the primary control at this door, and
        adding the address policy left every refusal in this class deliverable
        by something else.** Measured with `follow_redirects=True` forced on at
        both call sites, over this file and `tests/routers/test_books_covers.py`:
        before the policy **1 failed of 154**, the arm above; with the policy
        and without this arm **163 passed**; with this arm **2 failed of 171**,
        and **171 passed** unmutated.

        Every off list target in either file was `http://10.0.0.1/x.jpg`, which
        `fetch.PUBLIC_ADDRESSES` refuses on its own, and `AddressRefused` is an
        `httpx.HTTPError`, so the walk's own handler swallowed it and the
        assertion held for the wrong reason.

        So this target is unlisted **and** at an address the policy admits, and
        it is the only shape that can tell the two controls apart. `elsewhere`
        is where the resolver sends any host it was not told about, so a
        followed redirect is a **request** rather than an absent route:
        asserting on the return value alone would pass on a client that
        followed it to a 404.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    302, headers={"location": "https://evil.test/x.jpg"}
                )
            )
            elsewhere = mock.get(url__startswith=f"https://{AT_ANY_COVER_HOST}").mock(
                return_value=image()
            )

            assert covers.download(covers.open_library_url(ENGLISH)) is None

        assert elsewhere.call_count == 0

    def test_a_check_follows_no_redirect_off_the_list_either(self):
        """`covers.py` makes requests at two sites and the arm above reaches one.

        `resolve` never calls `download`, so the same hop rule on the checking
        side is pinned separately or it is pinned by nothing. The same shape:
        unlisted host, address the policy admits.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    302, headers={"location": "https://evil.test/x.jpg"}
                )
            )
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(404))
            elsewhere = mock.get(url__startswith=f"https://{AT_ANY_COVER_HOST}").mock(
                return_value=image()
            )

            assert _await(covers.resolve(ENGLISH)) is None

        assert elsewhere.call_count == 0

    def test_a_redirect_within_the_list_is_followed(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(302, headers={"location": DNB + "?isbn=x"})
            )
            mock.get(url__startswith=AT_DNB).mock(return_value=image())

            fetched = covers.download(covers.open_library_url(ENGLISH))

        assert fetched is not None

    @pytest.mark.parametrize(
        ("location", "path"),
        [
            ("/b/id/7-M.jpg", "/b/id/7-M.jpg"),
            ("7-M.jpg", "/b/isbn/7-M.jpg"),
        ],
    )
    def test_a_relative_location_is_resolved_against_the_hop_it_came_from(
        self, location, path
    ):
        """`_next_hop` exists to hold that rule in one place, and every other
        `Location` in this file is absolute, so `urljoin(current, location)`
        could be replaced by `location` with nothing red.

        **What it costs is the host, which is the whole point.** A bare
        `location` is not a URL `is_fetchable` can admit, so the next hop would
        be refused and an ordinary relative redirect would stop working. The
        second row is the one that pins the join rather than a prefix: it has no
        leading slash, so the answer depends on the **path** of the hop it came
        from and not only on its origin.
        """
        with respx.mock(assert_all_called=False) as mock:
            # **The route's calls, not the router's.** This file nests a router
            # inside `conftest.refuse_unmocked_network`'s, and `mock.calls`
            # answered one entry for a walk that made two: the first draft of
            # this test read it and failed on the shipped tree, which made an
            # unrelated mutation look caught.
            hops = mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                side_effect=[
                    httpx.Response(302, headers={"location": location}),
                    image(),
                ]
            )
            fetched = covers.download(covers.open_library_url(ENGLISH))

        assert fetched is not None
        assert hops.call_count == 2
        assert hops.calls[1].request.url.path == path
        assert hops.calls[1].request.headers["host"] == "covers.openlibrary.org"

    def test_a_redirect_loop_gives_up(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(
                    302, headers={"location": covers.open_library_url(ENGLISH)}
                )
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None


class TestWhereAListedHostAnswers:
    """`COVER_HOSTS` says which hosts this server may ask. This says which
    **addresses** it will open a connection to, and the two are different
    questions: a listed host whose resolver answers inside this cluster was
    fetched until `covers._client` went through `fetch.pinned_client`.

    **Defence in depth here, not the primary control, and saying so is the
    point.** The member picks the URL and `is_fetchable` is what refuses it;
    this refuses an address behind a host that rule already admitted. Two of
    the six listed hosts are wildcards, so the label under them is not the
    app's to choose either.

    The classification happens after resolution and the connection goes to the
    address that passed, so a name is not a way round it. `tests/test_fetch.py`
    is where the transport itself is tested; these are the two doors.
    """

    #: Inside this cluster, and on this address policy's refused list.
    INSIDE = "10.0.0.7"

    @staticmethod
    def _answering(address: str):
        async def resolve_to(host: str, port: int) -> tuple[str, ...]:
            return (address,)

        return resolve_to

    def test_a_listed_host_answering_inside_the_cluster_is_not_checked(
        self, monkeypatch
    ):
        monkeypatch.setattr(covers, "resolver", self._answering(self.INSIDE))
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=f"https://{self.INSIDE}").mock(
                return_value=image()
            )
            _await(covers.resolve(ENGLISH))

        assert route.call_count == 0
        # Refused reads as "could not be checked", which is what a service that
        # did not answer has always read as: the guess is kept, unverified,
        # rather than a cover being thrown away.
        assert covers.outcome_counts().get(covers.CoverOutcome.VERIFIED.value, 0) == 0

    def test_a_listed_host_answering_inside_the_cluster_is_not_downloaded(
        self, monkeypatch
    ):
        monkeypatch.setattr(covers, "resolver", self._answering(self.INSIDE))
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=f"https://{self.INSIDE}").mock(
                return_value=image()
            )
            fetched = covers.download(covers.open_library_url(ENGLISH))

        assert fetched is None
        assert route.call_count == 0

    def test_a_listed_host_on_a_public_address_is_still_fetched(self):
        """What this must **not** have refused, which is every real cover."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(return_value=image())
            fetched = covers.download(covers.open_library_url(ENGLISH))

        assert fetched is not None

    def test_the_request_still_speaks_as_the_name_it_was_addressed_by(self):
        """The pin moves the address and nothing else.

        A `Host` carrying the literal would reach a different virtual host on
        every one of these services, and the TLS name is checked against the
        certificate.
        """
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=image()
            )
            covers.download(covers.open_library_url(ENGLISH))

        assert route.calls[0].request.headers["host"] == "covers.openlibrary.org"

    def test_a_wildcard_cover_host_is_still_reached(self):
        """Two of the six entries name a label this app never writes down.

        `COVER_HOSTS` carries `*.googleusercontent.com` and `*.us.archive.org`,
        so the host a member supplies under either is one no map in this suite
        could enumerate. `tests/helpers.cover_resolver` answers one address for
        anything it was not told about, which is what keeps those two reachable
        rather than a lookup failure.
        """
        supplied = "https://lh3.googleusercontent.com/x"
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=f"https://{AT_ANY_COVER_HOST}").mock(
                return_value=image()
            )
            assert _await(covers.resolve(ENGLISH, supplied)) == supplied

        assert route.call_count == 1


class TestAHostIdnaCannotDecode:
    """`idna.IDNAError` is a `UnicodeError` and not an `httpx.HTTPError`, so
    both walks' handlers missed it. Measured on this tree: `covers.resolve`
    raised `idna.core.InvalidCodepoint` into `metadata.lookup`, which catches
    `httpx.HTTPError` and `ElementTree.ParseError` and would have answered 500
    on a member's lookup. `fetch._walk_hops` records the same trap.

    **Two hops reach it, and the first one is the member's**, which is why this
    class is not named for `Location`. On a redirect the raise comes from httpx
    building the request inside `send()` even at `follow_redirects=False`, to
    populate `response.next_request`. On the **first** URL `httpx.URL()` raises
    before any transport runs, and `is_fetchable` admits the shape:
    `*.googleusercontent.com` is a wildcard, so `xn--a.googleusercontent.com` is
    a listed host and `cover_url` is member input on `BookCreate`.
    """

    LOCATION = "http://xn--a.gov/x.jpg"
    #: A listed host, by the wildcard, whose label `idna` refuses to decode.
    SUPPLIED = "https://xn--a.googleusercontent.com/x.jpg"

    def test_a_check_refuses_a_location_rather_than_raising(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(302, headers={"location": self.LOCATION})
            )
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(404))

            assert _await(covers.resolve(ENGLISH)) is None

    def test_a_download_refuses_a_location_rather_than_raising(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(302, headers={"location": self.LOCATION})
            )
            assert covers.download(covers.open_library_url(ENGLISH)) is None

    def test_a_download_refuses_it_on_the_first_hop_with_no_redirect_in_sight(self):
        """The arm a member reaches, and the one the `Location` arms cannot see.

        Nothing is mocked, deliberately: `is_fetchable` admits this URL and the
        raise happens while the request is being built, so a passing test here
        is one that made no request at all. respx fails on any it did make.

        **The first assertion is the precondition, not a second subject.**
        Without it, tightening the wildcard to refuse a punycode label leaves
        this green while testing nothing: the URL would be refused before any
        request and `download` would still answer None.
        """
        assert covers.is_fetchable(self.SUPPLIED) is True

        with respx.mock:
            assert covers.download(self.SUPPLIED) is None

    def test_a_check_refuses_it_on_the_first_hop_too(self):
        """`resolve` puts a supplied URL at the front of its candidate list.

        The first assertion is the precondition. See the arm above for what
        goes green without it.
        """
        assert covers.is_fetchable(self.SUPPLIED) is True

        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=AT_OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=AT_DNB).mock(return_value=httpx.Response(404))

            assert _await(covers.resolve(ENGLISH, self.SUPPLIED)) is None


class TestNoCoverRequestIsMadeOutsideTheDoor:
    def test_covers_constructs_nothing_from_httpx(self):
        """Every request this module makes is made with `covers._client`.

        **Not an enumeration of the two client classes**, which is the shape
        that goes stale: this reports **any** call to anything in the `httpx`
        namespace. `httpx.HTTPError` appears in `except` clauses and
        `httpx.Response` and `httpx.AsyncClient` in annotations, and neither is
        a call, so the rule needs no exceptions today and none for a class httpx
        adds tomorrow.

        What it cannot see is `_client` being pointed at
        `fetch.catalogue_client`, which drops the pin while leaving every other
        bound in place. `TestWhereAListedHostAnswers` is that arm.
        """
        source = (_BACKEND / "covers.py").read_text()
        built = sorted(
            node.func.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "httpx"
        )
        assert built == []


def _await(work):
    """Run one coroutine from a sync test, on a loop of its own."""
    return asyncio.run(work)


async def _check_one(url: str, *, budget: float | None = None) -> bool | None:
    """`_check` against a client of its own, for the tests about one candidate.

    `resolve` asks two services and keeps the first answer it can use, so a
    guard about what one check **costs** cannot read it through `resolve`.
    """
    async with covers._client() as client:
        deadline = None if budget is None else monotonic() + budget
        return await covers._check(client, url, deadline)


def await_resolve(isbn: str, supplied: str) -> str | None:
    """`resolve` from a sync test, on its own loop."""
    return asyncio.run(covers.resolve(isbn, supplied))


def await_resolve_with_deadline(isbn: str, budget: float) -> str | None:
    """`resolve` with an already spent budget, from a sync test."""
    return asyncio.run(covers.resolve(isbn, deadline=monotonic() + budget))

