"""Tests for backend/fetch.py.

The module exists for one property, so that is what these pin: **no catalogue
can make this process hold more bytes than it agreed to**. Everything else here
is a consequence of that or a thing a caller depends on and would not notice
losing.

Three of these would have been the only warning of a real regression:

* `ResponseTooLarge` being an `httpx.HTTPError` is what makes the cap cost
  nothing at every call site. Break the base class and every one of them turns
  a hostile answer into a 500, silently, because the `except` clauses still
  compile. The count and its unit live in `fetch._walk_hops`; naming one here
  too is how this file came to hold five stale copies of six figures.
* The count is over the **raw wire** bytes, and any encoding other than
  `identity` is refused rather than decoded. Counting the decoded stream
  instead passes every test that sends plain text and caps nothing: httpx
  expands a whole chunk before yielding it, so 65,250 gzipped bytes were
  counted as 67,108,864 against an 8,192 byte limit. This module shipped that
  way, and this paragraph said the opposite for a round after it was fixed.
* `Fetched` holds the body rather than referring to a response, because callers
  read `.text` after the client's context manager has closed.

Every HTTP call is intercepted with respx, so nothing here reaches a real
catalogue.
"""

import ast
import asyncio
import gzip
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import respx

import fetch
import sources

# **Imported, not copied.** "What does this statement bind" is one fact, and
# `test_shelf.py`'s guard already answers it, including the `AnnAssign` half
# that a second implementation would have got wrong for the reason its
# docstring measures. Two rules, one resolver.
from tests.test_shelf import _bindings

URL = "https://catalogue.test/sru"

BACKEND = Path(__file__).resolve().parent.parent


def _concurrent_search_sources() -> int:
    """How many catalogues `metadata.search` can have in flight at once.

    **Derived from the tree rather than written down**, because the literal 6
    that used to sit in `test_the_default_cap_fits_the_pod_it_runs_in` went on
    passing after a seventh source joined: it bounded six sources against the
    pod while `MAX_RESPONSE_BYTES`'s own docstring had started claiming seven,
    so the only enforcement of that arithmetic was enforcing the wrong
    arithmetic.

    **It used to read the list literal handed to `_within_deadline`, and that
    stopped being possible.** The fan out is now built from the library's own
    provider list, so the call takes a comprehension over `plan.searched` and
    there is no literal to count. Reading it would have raised rather than
    guessing, which is what it was written to do.

    **So the number is the roster, not the enabled subset, and that is the
    honest bound rather than a convenient one.** `plan.searched` is a subset of
    `sources.SEARCH_SOURCES` by construction, so the roster is the worst case a
    household can produce by switching everything on, and a worst case is what
    this pins against a 512Mi pod. A count taken from whatever happened to be
    enabled would make the memory bound depend on a settings row.

    What keeps the two in step is
    `test_house_rules.TestEveryTargetResolvesToADoorAndAReader`,
    which pins the fan out's own table of search adapters equal to
    `sources.SEARCH_SOURCES`. Without it a source could be added to one and not
    the other, and this count would follow the wrong one.
    """
    return len(sources.SEARCH_SOURCES)


_CONCURRENT_SOURCES = _concurrent_search_sources()

#: The three modules allowed to speak HTTP without going through this one.
#:
#: `covers.py` fetches a URL a **member** supplied, so it needs
#: `is_fetchable` re-run per hop, which is a different policy rather than a
#: different caller of the same one. `notifications.py` **posts** the library's
#: own book titles outward, so a redirect is a leak and it refuses to follow one
#: at all. `fetch.py` is the door itself.
DOOR_KEEPERS = {"covers.py", "notifications.py", "fetch.py"}

#: The two client classes, and every way httpx will make a request.
#:
#: `stream` and `request` are on this list because they are the two spellings
#: that do not look like a verb, and `stream` is the one this module itself
#: uses: a caller copying `fetch.get` into another module is the likeliest way
#: this rule ever fires.
CLIENT_CLASSES = frozenset({"Client", "AsyncClient"})
REQUEST_VERBS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request", "stream"}
)

#: What `fetch.py` offers that hands back a live client.
#:
#: **Kept apart from `CLIENT_CLASSES` deliberately.** Folding the two together
#: is how the first version of this rule reported the *correct* use of the door
#: as a violation: `from fetch import catalogue_client` then
#: `async with catalogue_client() as c` was flagged "builds a client", under a
#: message saying the module was not going through `fetch.py`. Calling it makes
#: a handle, which this rule has to follow; it does not make a client the
#: module built for itself, which is the thing being refused. A guard that fails
#: the pattern it exists to promote gets worked around, not obeyed.
DOOR_HANDLE_SOURCES = frozenset({"catalogue_client"})


def _client() -> httpx.AsyncClient:
    return fetch.catalogue_client()


def _source_modules() -> dict[str, str]:
    """Every backend module these rules apply to, keyed by relative path."""
    return {
        str(path.relative_to(BACKEND)): path.read_text()
        for path in BACKEND.rglob("*.py")
        if path.relative_to(BACKEND).parts[0] not in {"tests", "migrations", ".venv"}
    }


def _module_aliases(tree: ast.Module, module: str) -> set[str]:
    """Every local name bound to one imported module.

    `import httpx as h` is one line and defeats a rule that looks for the
    literal word, which is what the first version of this guard did. The second
    version resolved httpx that way and then hardcoded `"fetch"` beside it, so
    `import fetch as f` walked through the half that had just been fixed. One
    function, called for both.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name == module}
        for target, value in _bindings(node):
            if (
                isinstance(target, ast.Name)
                and isinstance(value, ast.Name)
                and value.id in names
            ):
                names.add(target.id)
    return names


@dataclass(frozen=True)
class _Names:
    """What one module calls the things this rule cares about.

    Four sets rather than one, because they are asked four different questions.
    `constructors` called is an offence; `handle_makers` called is not, it just
    produces something to watch; `verbs` called bare is an offence; the module
    aliases qualify all of it.
    """

    httpx: set[str]
    door: set[str]
    #: Names bound to `httpx.Client` or `httpx.AsyncClient`.
    constructors: set[str]
    #: Those, plus names bound to `fetch.catalogue_client`.
    handle_makers: set[str]
    #: Names bound to a module level httpx request function, as in
    #: `from httpx import get`.
    verbs: set[str]


def _resolve(tree: ast.Module) -> _Names:
    """Every local spelling of httpx, of the door, and of what they hand out."""
    httpx_names = _module_aliases(tree, "httpx")
    door_names = _module_aliases(tree, "fetch")
    constructors: set[str] = set()
    handle_makers: set[str] = set()
    verbs: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "httpx":
            for alias in node.names:
                if alias.name in CLIENT_CLASSES:
                    constructors.add(alias.asname or alias.name)
                elif alias.name in REQUEST_VERBS:
                    verbs.add(alias.asname or alias.name)
        elif node.module == "fetch":
            handle_makers |= {
                a.asname or a.name for a in node.names if a.name in DOOR_HANDLE_SOURCES
            }

    # A second pass, because a rebinding may sit above or below its import and
    # this rule does not care which.
    qualified = httpx_names | door_names
    for node in ast.walk(tree):
        for target, value in _bindings(node):
            if not isinstance(target, ast.Name):
                continue
            if isinstance(value, ast.Name):
                if value.id in constructors:
                    constructors.add(target.id)
                elif value.id in handle_makers:
                    handle_makers.add(target.id)
                elif value.id in verbs:
                    verbs.add(target.id)
            elif (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in qualified
            ):
                if value.attr in CLIENT_CLASSES:
                    constructors.add(target.id)
                elif value.attr in DOOR_HANDLE_SOURCES:
                    handle_makers.add(target.id)
                elif value.attr in REQUEST_VERBS and value.value.id in httpx_names:
                    verbs.add(target.id)

    return _Names(
        httpx=httpx_names,
        door=door_names,
        constructors=constructors,
        handle_makers=handle_makers | constructors,
        verbs=verbs,
    )


def _is_client_expression(value: ast.expr, names: _Names) -> bool:
    """Whether an expression evaluates to a client."""
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id in names.handle_makers
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return False
    root = func.value.id
    return (root in names.httpx and func.attr in CLIENT_CLASSES) or (
        root in names.door and func.attr in DOOR_HANDLE_SOURCES
    )


def _client_handles(tree: ast.Module, names: _Names) -> set[str]:
    """Every local name holding a client, however it got one.

    Three bindings. `async with fetch.catalogue_client() as client` is the one
    that matters most, because `client.get(url)` and `fetch.get(client, url)`
    are one word apart at the two sites in `metadata.py` that own a client. An
    **annotated parameter** is the third, and it is not a flourish: the four
    requests in `metadata.py` that take a client take it that way.
    """
    handles = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if isinstance(
                    item.optional_vars, ast.Name
                ) and _is_client_expression(item.context_expr, names):
                    handles.add(item.optional_vars.id)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            arguments = node.args
            for arg in [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ]:
                if arg.annotation is not None and _annotates_client(
                    arg.annotation, names
                ):
                    handles.add(arg.arg)
        for target, value in _bindings(node):
            if isinstance(target, ast.Name) and _is_client_expression(value, names):
                handles.add(target.id)
    return handles


def _annotates_client(node: ast.expr, names: _Names) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names.constructors
    return (
        isinstance(node, ast.Attribute)
        and node.attr in CLIENT_CLASSES
        and isinstance(node.value, ast.Name)
        and node.value.id in names.httpx
    )


def _http_offences(source: str) -> list[str]:
    """Every place a module speaks HTTP without going through `fetch.py`.

    Read with `ast` rather than matched as text, for the reason
    `tests/test_shelf.py` gives about its own guard: a regex has to guess at
    the call's formatting, and eight of the ten sites this rule was written
    against spread the constructor over three lines.
    """
    tree = ast.parse(source)
    names = _resolve(tree)
    handles = _client_handles(tree, names)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in names.constructors:
                found.append(f"builds a client at line {node.lineno}")
            elif func.id in names.verbs:
                found.append(f"an httpx request as {func.id} at line {node.lineno}")
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            root = func.value.id
            if root in names.httpx and func.attr in CLIENT_CLASSES:
                found.append(f"builds a client at line {node.lineno}")
            elif root in names.httpx and func.attr in REQUEST_VERBS:
                found.append(f"httpx.{func.attr} at line {node.lineno}")
            elif root in handles and func.attr in REQUEST_VERBS:
                found.append(f"{root}.{func.attr} at line {node.lineno}")
    return found


class TestTheCapIsTheWholePoint:
    @pytest.mark.asyncio
    async def test_a_body_under_the_cap_comes_back_whole(self):
        body = b"x" * 4096
        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(200, content=body))
            answer = await fetch.get_once(URL, limit=8192)

        assert answer.content == body
        assert answer.status_code == 200

    @pytest.mark.asyncio
    async def test_a_body_over_the_cap_is_refused(self):
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(200, content=b"x" * 9000)
            )
            with pytest.raises(fetch.ResponseTooLarge):
                await fetch.get_once(URL, limit=8192)

    @pytest.mark.asyncio
    async def test_a_body_exactly_at_the_cap_is_allowed(self):
        """The boundary, because an off by one here refuses an honest page."""
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(200, content=b"x" * 8192)
            )
            answer = await fetch.get_once(URL, limit=8192)

        assert len(answer.content) == 8192

    @pytest.mark.asyncio
    async def test_compression_is_not_requested(self):
        """The header is half the fix, and it is the half a reader cannot see.

        `aiter_raw` alone would leave every honest body arriving gzipped and
        unparseable. Measured live, all ten catalogues answer 200 under
        `identity`; five of them gzip when it is not sent. The names and the
        byte counts are in `fetch._IDENTITY`, which is where they belong:
        restating them here is what left this sentence saying six and three
        after a seventh source was added, then again at the eighth, and again
        at the ninth, where `test_roster_counts.py` caught it.
        """
        with respx.mock:
            route = respx.get(URL).mock(return_value=httpx.Response(200))
            await fetch.get_once(URL)

        sent = route.calls.last.request.headers["accept-encoding"]
        assert sent == "identity"

    @pytest.mark.asyncio
    async def test_this_app_says_who_it_is(self):
        """**A requirement rather than a courtesy, and that is measured.**

        lobid's usage policy asks in writing for "a meaningful, recurring
        string". Wikidata does not ask: a request with no `User-Agent` answers
        **403** with "Please set a user-agent and respect our robot policy",
        measured live 2026-08-27. Without this header the authority file half of
        the author feature does not work at all.

        The value is asserted rather than merely tested for presence, because
        the policy asks for it to stay the same for the life of the project:
        httpx would otherwise send its own default and the test would pass.
        """
        with respx.mock:
            route = respx.get(URL).mock(return_value=httpx.Response(200))
            await fetch.get_once(URL)

        assert route.calls.last.request.headers["user-agent"] == "endpaper"

    @pytest.mark.asyncio
    async def test_a_body_carrying_an_encoding_we_did_not_ask_for_is_refused(self):
        """The defect this module shipped with, pinned so it cannot come back.

        The first version counted `aiter_bytes()`, which decodes before it
        yields, so the allocation the cap exists to prevent happened before the
        cap was consulted. Measured on httpx 0.28.1: this 65,250 byte gzip
        counted **67,108,864** bytes against an 8,192 byte limit, at a 215.8 MB
        traced peak. `aiter_raw()` on the same response counted 65,250.

        So the rule is no longer "count what it expands to". It is **never
        expand it**: a server that ignores `identity` is refused on the header,
        on the wire, before any of it is decoded.
        """
        payload = b"x" * (64 * 1024 * 1024)
        compressed = gzip.compress(payload)
        # 65,250 against 67,108,864: a thousandfold, and the wire figure is the
        # only one this loop ever sees.
        assert len(compressed) * 1000 < len(payload)

        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    200,
                    content=compressed,
                    headers={"content-encoding": "gzip"},
                )
            )
            # A cap comfortably above the **wire** bytes and far below the
            # expansion, so the refusal can only be the encoding check.
            with pytest.raises(fetch.UnrequestedEncoding):
                await fetch.get_once(URL, limit=1_000_000)

    @pytest.mark.asyncio
    async def test_an_identity_encoding_header_is_not_treated_as_an_encoding(self):
        """`identity` is what was asked for, so saying so is not a refusal."""
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    200, content=b"fine", headers={"content-encoding": "identity"}
                )
            )
            answer = await fetch.get_once(URL)

        assert answer.content == b"fine"

    def test_the_default_cap_clears_the_largest_honest_page(self):
        """Measured live 2026-08-26, seven worst case queries at 50 records.

        Eight sources are asked now. The eighth, the NLG, was measured at
        604,964 bytes on 2026-08-31, under this figure, so the largest honest
        body is still K10plus's and the bound below is unchanged.

        The largest was K10plus `pica.all=geschichte deutschland` at 687,481
        bytes. This test is here so that lowering the constant has to argue
        with the measurement rather than quietly refuse a real search.

        **The assertion is 3x, not "greater than".** 1 MB cleared this figure
        too, at 1.52x, and the round before had cleared 587,810 at 1.78x with
        the same confidence: the largest honest body moved when somebody widened
        the query sample, so a bare inequality pins the sample rather than the
        bound.
        """
        assert fetch.MAX_RESPONSE_BYTES > 3 * 687_481

    def test_the_default_cap_fits_the_pod_it_runs_in(self):
        """The other side, because a floor alone lets the constant run away.

        `> 3 * 687_481` is satisfied by 512 MiB, which is the failure the cap
        exists to prevent. The ceiling is the arithmetic the constant's own
        docstring states: every source `metadata.search` asks concurrently, each
        retaining a measured 15.28x its wire bytes, inside a 512Mi pod. Today
        that is 256.4 MB against 536,870,912, and it permits growth to about
        4.19 MiB before the two bounds meet. Those read 224.3 MB and 4.79 MiB at
        seven sources: the assertion is derived from `_CONCURRENT_SOURCES` and
        this sentence was not, which is the drift the paragraph below records
        happening to the prose instead of to the code.

        **The source count is read from `metadata`, not written here.** It was
        written here, as a literal 6, and it stayed 6 when the ÖNB became a
        seventh concurrent source: the assertion went on passing because it
        bounded six sources against the pod while the constant it exists to
        enforce had started claiming seven. A test that restates a number the
        tree already holds is a second place for that number to be wrong, and
        this was the only enforcement of that arithmetic.
        """
        pod = 512 * 1024 * 1024
        worst_case = _CONCURRENT_SOURCES * fetch.MAX_RESPONSE_BYTES * 15.28
        assert pod > worst_case

    def test_the_constant_states_the_source_count_the_tree_has(self):
        """The docstring's number and the fan out, compared.

        **The test above does not catch a wrong source count on its own**, and
        that was measured rather than assumed: hardcoding it back to 6 leaves it
        passing, because six sources against the pod is a *weaker* bound than
        seven and the assertion is an inequality. So the count needs pinning
        from the other side, which is what this does: the prose a reader
        believes has to agree with the list the code actually asks.

        Same habit as `test_serialisation.py`'s
        `test_the_number_in_the_docstring_is_the_number_it_costs`, which reads
        its figure back out of the docstring rather than trusting it.

        **What this pair does and does not catch, attacked rather than assumed.**
        Adding a source to the fan out without updating the docstring fails
        here, and so does removing one: both directions measured. Raising
        `MAX_RESPONSE_BYTES` past the pod fails the test above. What neither
        catches is somebody editing that test to name a literal instead of
        `_CONCURRENT_SOURCES`, which still passes, because a smaller count is a
        weaker inequality. That is a deliberate edit rather than the drift these
        exist for, and it is written down instead of chased with a guard on a
        guard.
        """
        source = (BACKEND / "fetch.py").read_text()
        stated = re.search(r"asks (\w+) sources at once", source)
        assert stated is not None, (
            "MAX_RESPONSE_BYTES's docstring no longer states how many sources "
            "`metadata.search` asks at once"
        )
        words = {
            "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10,
        }
        assert words.get(stated.group(1)) == _CONCURRENT_SOURCES, (
            f"the docstring says {stated.group(1)} sources; `metadata.search` "
            f"asks {_CONCURRENT_SOURCES}"
        )

    def test_the_cap_is_resolved_at_call_time_not_at_import(self):
        """`limit` defaults to None so the constant stays the single value.

        Bound as a default argument it is read once when the module is
        imported, and nothing can reach it afterwards.
        """
        import inspect

        assert inspect.signature(fetch.get).parameters["limit"].default is None
        assert inspect.signature(fetch.get_once).parameters["limit"].default is None


class TestCallersDoNotHaveToChangeToGetTheCap:
    def test_too_large_is_an_http_error(self):
        """The base class is load bearing at ten call sites.

        Every caller in `metadata.py` and `google_books.py` already catches
        `httpx.HTTPError` and degrades to "this source is unavailable". If this
        stops being one, all ten keep compiling and start returning 500s.
        """
        assert issubclass(fetch.ResponseTooLarge, httpx.HTTPError)

    @pytest.mark.asyncio
    async def test_the_body_is_readable_after_the_client_has_closed(self):
        """Several callers touch `.text` outside the `async with`.

        A streamed `httpx.Response` raises `ResponseNotRead` there, which is
        why this returns a value object rather than the response.
        """
        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(200, text="<x/>"))
            async with _client() as client:
                answer = await fetch.get(client, URL)

        assert answer.text == "<x/>"

    @pytest.mark.asyncio
    async def test_a_status_code_survives(self):
        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(429))
            answer = await fetch.get_once(URL)

        assert answer.status_code == 429

    @pytest.mark.asyncio
    async def test_query_parameters_reach_the_catalogue(self):
        with respx.mock:
            route = respx.get(URL).mock(return_value=httpx.Response(200))
            await fetch.get_once(URL, params={"query": "num=9783960092353"})

        assert route.calls.last.request.url.params["query"] == "num=9783960092353"


class TestDecodingMatchesWhatHttpxWouldHaveDone:
    @pytest.mark.asyncio
    async def test_the_charset_from_the_header_is_honoured(self):
        """The SRU catalogues send non-ASCII names and declare their charset.

        Decoding as UTF-8 regardless would turn every German author into
        mojibake, and nothing else in the app would report it.
        """
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    200,
                    content="Böll".encode("iso-8859-1"),
                    headers={"content-type": "text/xml; charset=iso-8859-1"},
                )
            )
            answer = await fetch.get_once(URL)

        assert answer.text == "Böll"

    @pytest.mark.asyncio
    async def test_an_unknown_charset_costs_mojibake_and_not_an_exception(self):
        """httpx guards this with `_is_known_encoding`; the fallback stands in.

        A catalogue is free to name a charset Python has never heard of, and a
        `LookupError` out of `.text` is in no caller's `except` clause.
        """
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    200,
                    content=b"plain",
                    headers={"content-type": "text/xml; charset=x-nonesuch"},
                )
            )
            answer = await fetch.get_once(URL)

        assert answer.text == "plain"

    @pytest.mark.asyncio
    async def test_json_raises_value_error_on_a_body_that_is_not_json(self):
        """Every caller catches `ValueError`, which is what httpx raised here."""
        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(200, text="<html>"))
            answer = await fetch.get_once(URL)

        with pytest.raises(ValueError):
            answer.json()


class TestTheRedirectPolicy:
    """Followed on the same host, refused off it.

    Both halves are measurements. Open Library answers `/isbn/{isbn}.json` with
    a 302, so refusing redirects outright breaks a source. Measured live
    2026-08-27 with redirects **off**, it is the only source that redirects at
    all and it redirects to `https://openlibrary.org/books/{key}.json`, its own
    host. So following a hop that changes host buys nothing any catalogue needs
    and is the only place an attacker chooses an address here.
    """

    @pytest.mark.asyncio
    async def test_a_redirect_to_the_same_host_is_followed(self):
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(302, headers={"location": f"{URL}/moved"})
            )
            respx.get(f"{URL}/moved").mock(
                return_value=httpx.Response(200, text="arrived")
            )
            answer = await fetch.get_once(URL)

        assert answer.text == "arrived"

    @pytest.mark.asyncio
    async def test_a_relative_redirect_resolves_against_the_current_hop(self):
        """Open Library's is `location: /books/OL23140636M.json`, not absolute."""
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(302, headers={"location": "/elsewhere"})
            )
            route = respx.get("https://catalogue.test/elsewhere").mock(
                return_value=httpx.Response(200, text="arrived")
            )
            answer = await fetch.get_once(URL)

        assert route.called
        assert answer.text == "arrived"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "location",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://10.43.0.1:8080/",
            "https://evil.test/sru",
        ],
        ids=["link local", "a cluster address", "another public host"],
    )
    async def test_a_redirect_off_the_host_is_refused(self, location):
        """The SSRF this module has, and the only one.

        `targets.SEEDED[CatalogueSource.LOC].base_url` is plaintext
        `http://lx2.loc.gov:210`, so forging this needs
        no compromised catalogue: anyone on the path, or anyone answering DNS
        for the pod, can send back a 302.
        """
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(302, headers={"location": location})
            )
            landed = respx.get(url__startswith=location.rsplit("/", 1)[0]).mock(
                return_value=httpx.Response(200, text="reached")
            )
            with pytest.raises(fetch.RedirectedOffHost):
                await fetch.get_once(URL)

        assert not landed.called

    @pytest.mark.asyncio
    async def test_a_downgrade_to_plaintext_on_the_same_name_is_refused(self):
        """Same host, and still somewhere an on-path attacker can rewrite."""
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    302, headers={"location": "http://catalogue.test/sru"}
                )
            )
            with pytest.raises(fetch.RedirectedOffHost):
                await fetch.get_once(URL)

    @pytest.mark.asyncio
    async def test_a_redirect_to_a_different_port_on_the_same_name_is_refused(self):
        """`lx2.loc.gov:210` to `lx2.loc.gov:22` is a different service."""
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    302, headers={"location": "https://catalogue.test:8443/sru"}
                )
            )
            with pytest.raises(fetch.RedirectedOffHost):
                await fetch.get_once(URL)

    @pytest.mark.asyncio
    async def test_an_explicit_default_port_is_the_same_place(self):
        """`https://host` and `https://host:443` are one address.

        Comparing `httpx.URL.port` raw reads them as two, and would refuse a
        redirect no attacker sent.
        """
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    302, headers={"location": "https://catalogue.test:443/moved"}
                )
            )
            respx.get("https://catalogue.test:443/moved").mock(
                return_value=httpx.Response(200, text="arrived")
            )
            answer = await fetch.get_once(URL)

        assert answer.text == "arrived"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "location",
        ["http://xn--a.gov/x", "http://xn--lx2-loc-.gov:210/x"],
        ids=["an invalid codepoint", "a malformed punycode label"],
    )
    async def test_a_location_naming_an_unusable_host_is_refused(self, location):
        """The hop guard never sees this one, and that is the point.

        httpx builds the redirect request inside `send()` even with
        `follow_redirects=False`, to populate `response.next_request`, so
        `URL.host` calls `idna.decode` before `_same_host_hop` runs.
        `idna.IDNAError` is a `UnicodeError`, so this arrived as a bare
        `ValueError` out of `client.stream`.

        **Eight of the thirteen `try` blocks wrapping a call into this module
        catch `(httpx.HTTPError, ElementTree.ParseError)` and would not have
        caught it**, so one hostile source 500s `GET /api/books/search` instead
        of being dropped. The unit is the block rather than the call, and
        `fetch._walk_hops` carries the count and how it was taken. Both
        spellings here are plain ASCII on the wire, and
        `targets.SEEDED[CatalogueSource.LOC].base_url` is plaintext
        HTTP, so forging it needs no TLS.
        """
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(302, headers={"location": location})
            )
            with pytest.raises(fetch.RedirectedOffHost) as raised:
                await fetch.get_once(URL)

        # The assertion that matters to the call sites: not a bare ValueError.
        assert isinstance(raised.value, httpx.HTTPError)

    @pytest.mark.asyncio
    async def test_a_redirect_with_no_location_is_refused(self):
        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(302))
            with pytest.raises(fetch.RedirectedOffHost):
                await fetch.get_once(URL)

    @pytest.mark.asyncio
    async def test_a_same_host_chain_is_bounded(self):
        """A catalogue redirecting to itself forever is a spin, not a fetch."""
        with respx.mock:
            respx.get(url__startswith=URL).mock(
                return_value=httpx.Response(302, headers={"location": f"{URL}/again"})
            )
            with pytest.raises(fetch.TooManyRedirects):
                await fetch.get_once(URL)

    @pytest.mark.asyncio
    async def test_the_original_query_is_not_reappended_to_the_new_url(self):
        """The Location carries the whole URL, parameters included.

        Passing `params=` again duplicates every one of them, which for an SRU
        `query=` is a different search or a 400.
        """
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    302, headers={"location": f"{URL}/moved?version=1.1"}
                )
            )
            route = respx.get(url__startswith=f"{URL}/moved").mock(
                return_value=httpx.Response(200, text="arrived")
            )
            await fetch.get_once(URL, params={"version": "1.1"})

        assert str(route.calls.last.request.url) == f"{URL}/moved?version=1.1"

    @pytest.mark.asyncio
    async def test_the_cap_still_applies_after_a_redirect(self):
        """The hop that answers is the hop that can be enormous."""
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(302, headers={"location": f"{URL}/moved"})
            )
            respx.get(f"{URL}/moved").mock(
                return_value=httpx.Response(200, content=b"x" * 9000)
            )
            with pytest.raises(fetch.ResponseTooLarge):
                await fetch.get_once(URL, limit=8192)


class TestTheDeadlineBoundsTheWholeRequest:
    """httpx's `timeout` is per operation, so it bounds nothing on its own.

    Measured on httpx 0.28.1: twenty bytes trickled at 0.9s apiece completed in
    **18.0s** under a **1.0s** timeout, because each read restarted the clock.
    At `TIMEOUT_SECONDS = 10` and a 2 MiB cap that is roughly 109 days for one
    request. `metadata.search` has `SEARCH_DEADLINE_SECONDS` over its gather;
    `metadata.lookup` and `metadata.editions` have nothing, and both serve
    `GET /api/books/lookup`.
    """

    @pytest.mark.asyncio
    async def test_a_deadline_already_past_makes_no_request(self):
        with respx.mock:
            route = respx.get(URL).mock(return_value=httpx.Response(200))
            with pytest.raises(fetch.DeadlineExceeded):
                await fetch.get_once(URL, deadline=time.monotonic() - 1)

        assert not route.called

    @pytest.mark.asyncio
    async def test_a_slow_trickle_stops_at_the_deadline(self):
        """The shape the per-operation timeout cannot see.

        Each chunk arrives well inside `TIMEOUT_SECONDS`; the body never ends.
        Without a deadline this loop returns when the sender feels like it.
        """

        async def trickle():
            for _ in range(1000):
                await asyncio.sleep(0.01)
                yield b"x" * 8

        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(200, stream=trickle())
            )
            started = time.monotonic()
            with pytest.raises(fetch.DeadlineExceeded):
                await fetch.get_once(URL, deadline=time.monotonic() + 0.2)
            spent = time.monotonic() - started

        assert spent < 2.0

    @pytest.mark.asyncio
    async def test_a_chunk_arriving_just_inside_the_budget_does_not_double_it(self):
        """The overshoot, which the test above was too loose to catch.

        Shrinking each read's timeout and testing the clock between chunks
        misses by a whole budget in both directions at once: the per-read value
        is fixed before the stream opens, and the clock is only consulted once a
        chunk has already arrived. A sender pacing chunks just inside the budget
        therefore got two of them. Measured with the old shape, a 1.0 second
        budget returned after **1.982s**; with `asyncio.timeout` around the
        walk, 1.018s. The assertion is 1.5x, which the old shape fails and the
        new one clears with room.
        """
        budget = 0.4

        async def paced():
            for _ in range(50):
                await asyncio.sleep(budget * 0.98)
                yield b"x" * 8

        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(200, stream=paced()))
            started = time.monotonic()
            with pytest.raises(fetch.DeadlineExceeded):
                await fetch.get_once(URL, deadline=time.monotonic() + budget)
            spent = time.monotonic() - started

        assert spent < budget * 1.5

    @pytest.mark.asyncio
    async def test_the_default_deadline_is_the_timeout(self):
        """One number, so the docstring's claim about holding a worker is true."""
        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(200, text="quick"))
            answer = await fetch.get_once(URL)

        assert answer.text == "quick"
        assert fetch.TIMEOUT_SECONDS == 10


class TestThisIsTheOnlyDoorOutwards:
    """House rule: an HTTP request is made in exactly one place.

    The defect this closes is not hypothetical, it is the one that produced
    this module. `metadata.py` held **nine** hand built clients and
    `google_books.py` a tenth, each repeating the timeout and the redirect
    policy, and not one of them bounded the body. Nothing said they should:
    `covers.py` had done the careful version since covers were first stored,
    and the two never met.

    **The first version of this rule was decorative and the numbers say so.**
    Run against eleven evasions it caught **two**, and one of those only
    because the shape happened to also construct a client. It matched
    `httpx.AsyncClient(` and nothing else, so `import httpx as h`, `from httpx
    import AsyncClient`, `C = httpx.AsyncClient`, the module level
    `httpx.get`/`post`/`stream`, and `await client.get(url)` on a client from
    this module's own door all walked through it. The last of those is the one
    that matters: `client.get(url)` and `fetch.get(client, url)` are one word
    apart at `metadata.py:427` and `:2929`.

    **Blind spots, listed rather than left to be found, and measured rather
    than guessed.** The first version of this list named three things that are
    not blind spots at all: a client returned by a helper, pulled out of a
    container, or stored on an attribute is caught, because the *construction*
    is flagged where it happens and the handle never has to be followed. What
    is genuinely missed:

    * `getattr(client, "get")(...)`, and any other call assembled at runtime.
    * A handle that reaches a module already built, as a parameter annotated
      with something other than a client class, or off `self`.
    * An annotation given as a string, or one this resolver does not read.
    * Any HTTP library that is not httpx. This rule is httpx shaped; `requests`
      or `aiohttp` would need their own, and would first need adding to
      `pyproject.toml`, which is its own review.

    The first three are all longer to write than the correct call, which is the
    only reason a rule of this shape is worth having.
    """

    def test_no_module_but_the_door_keepers_speaks_http(self):
        offenders = sorted(
            f"{name}:{where}"
            for name, source in _source_modules().items()
            if name not in DOOR_KEEPERS
            for where in _http_offences(source)
        )
        assert offenders == [], (
            "These modules make an HTTP request without going through fetch.py, "
            f"so nothing bounds what they read: {offenders}"
        )

    def test_the_door_keepers_are_exactly_the_modules_that_need_to_be(self):
        """An allowlist naming a module that no longer needs it is how the next
        reader learns the wrong rule."""
        speaking = {
            name
            for name, source in _source_modules().items()
            if _http_offences(source)
        }
        assert speaking == DOOR_KEEPERS

    #: Every shape the first version of this rule let through, plus the two it
    #: caught. A guard with no test that fails when it is removed is not
    #: enforced, and eleven of these were written by two reviewers trying to
    #: get past it.
    EVASIONS = {
        "plain construction": "import httpx\nc = httpx.AsyncClient()\n",
        "sync construction": "import httpx\nc = httpx.Client()\n",
        "spread over lines": (
            "import httpx\n\n\ndef f():\n"
            "    return httpx.AsyncClient(\n        timeout=10,\n    )\n"
        ),
        "imported class": "from httpx import AsyncClient\nc = AsyncClient()\n",
        "imported and renamed": (
            "from httpx import AsyncClient as AC\nc = AC()\n"
        ),
        "module alias": "import httpx as h\nc = h.AsyncClient()\n",
        "rebound constructor": "import httpx\nC = httpx.AsyncClient\nc = C()\n",
        "annotated rebinding": (
            "import httpx\nfrom typing import Any\nC: Any = httpx.AsyncClient\nc = C()\n"
        ),
        "module level verb": "import httpx\nr = httpx.get('u')\n",
        "module level stream": (
            "import httpx\nwith httpx.stream('GET', 'u') as r:\n    pass\n"
        ),
        "aliased module level verb": "import httpx as h\nr = h.post('u')\n",
        "verb on the door's own client": (
            "import fetch\n\n\nasync def f():\n"
            "    async with fetch.catalogue_client() as client:\n"
            "        return await client.get('u')\n"
        ),
        "verb on an annotated parameter": (
            "import httpx\n\n\nasync def f(client: httpx.AsyncClient):\n"
            "    return await client.get('u')\n"
        ),
        "verb on an assigned client": (
            "import httpx\nc = httpx.AsyncClient()\n\n\n"
            "async def f():\n    return await c.stream('GET', 'u')\n"
        ),
        "imported verb": "from httpx import get\nr = get('u')\n",
        "imported and renamed verb": (
            "from httpx import get as hget\nr = hget('u')\n"
        ),
        "verb on a client from an aliased door": (
            "import fetch as f\n\n\nasync def g(url):\n"
            "    async with f.catalogue_client() as c:\n"
            "        return await c.get(url)\n"
        ),
    }

    @pytest.mark.parametrize("shape", EVASIONS.values(), ids=EVASIONS.keys())
    def test_the_rule_catches_every_shape_that_speaks_http(self, shape):
        assert _http_offences(shape)

    #: Calls that must not be reported. The first two are the door being used
    #: **correctly**, and they are here because the rule reported one of them:
    #: `from fetch import catalogue_client` was flagged "builds a client", under
    #: a message saying the module was not going through `fetch.py`. A guard
    #: that fails the pattern it exists to promote gets worked around rather
    #: than obeyed, so both spellings are pinned.
    INNOCENT = {
        "the door, imported by name": (
            "from fetch import catalogue_client, get\n\n\nasync def f(url):\n"
            "    async with catalogue_client() as c:\n        return await get(c, url)\n"
        ),
        "the door, through an alias": (
            "import fetch as f\n\n\nasync def g(url):\n"
            "    async with f.catalogue_client() as c:\n"
            "        return await f.get(c, url)\n"
        ),
        "a response object": "import httpx\nr = httpx.Response(200)\n",
        "an exception type": (
            "import httpx\n\n\ndef f():\n    raise httpx.HTTPError('x')\n"
        ),
        "a dict's own get": (
            "d = {'a': 1}\nv = d.get('a')\n"
        ),
        "an unrelated object's stream": (
            "def f(source):\n    return source.stream('GET', 'u')\n"
        ),
    }

    @pytest.mark.parametrize("shape", INNOCENT.values(), ids=INNOCENT.keys())
    def test_the_rule_leaves_an_unrelated_call_alone(self, shape):
        assert not _http_offences(shape)
