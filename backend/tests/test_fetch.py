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
import socket
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import respx

import fetch
import sources

# **Imported, not copied.** What counts as a module of this project is one fact
# and `_is_vendored` is where it is decided. This walk used to be spelled out
# here, excluding `{"tests", "migrations", ".venv"}` by name, which is the
# directory a developer has and not the one the pipeline creates under
# `backend/` for its uv cache.
from tests.test_house_rules import _source_modules

# **Imported, not copied**, for the same reason one line up. "What does this
# statement bind" is one fact, and `test_shelf.py`'s guard already answers it,
# including the `AnnAssign` half that a second implementation would have got
# wrong for the reason its docstring measures. Two rules, one resolver.
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
#: **A transport is a way outwards too, and this rule could not see one.**
#: Measured 2026-09-10 against the four spellings: `httpx.AsyncHTTPTransport()`,
#: the sync one, the imported class, and a subclass calling
#: `.handle_async_request(request)` all returned no offence at all, while the
#: control `httpx.AsyncClient()` was caught. That was tolerable while nothing in
#: the tree used a transport; `fetch.PinnedTransport` makes it the sanctioned
#: way to reach the network, so a module copying the idiom would have walked
#: through the door guard rather than through the door.
TRANSPORT_CLASSES = frozenset(
    {"AsyncHTTPTransport", "HTTPTransport", "AsyncBaseTransport", "BaseTransport"}
)

CLIENT_CLASSES = frozenset({"Client", "AsyncClient"}) | TRANSPORT_CLASSES
REQUEST_VERBS = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "request",
        "stream",
        # The two a transport answers on, which is where a request leaves from
        # once somebody has one.
        "handle_request",
        "handle_async_request",
    }
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
#:
#: **`pinned_client` is here for the same reason and it was missed once.**
#: Measured: `async with fetch.pinned_client(...) as c: await c.get(u)` reported
#: nothing, while the identical shape on `catalogue_client` was caught, so the
#: newer of the two doors handed back a client this rule would not follow.
DOOR_HANDLE_SOURCES = frozenset({"catalogue_client", "pinned_client"})


def _client() -> httpx.AsyncClient:
    return fetch.catalogue_client()


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
    #: Local names for a transport class, which are reported wherever they are
    #: **named** rather than only where they are called. See `_http_offences`.
    transports: set[str]


def _resolve(tree: ast.Module) -> _Names:
    """Every local spelling of httpx, of the door, and of what they hand out."""
    httpx_names = _module_aliases(tree, "httpx")
    door_names = _module_aliases(tree, "fetch")
    constructors: set[str] = set()
    handle_makers: set[str] = set()
    verbs: set[str] = set()
    transports: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "httpx":
            for alias in node.names:
                if alias.name in CLIENT_CLASSES:
                    constructors.add(alias.asname or alias.name)
                    if alias.name in TRANSPORT_CLASSES:
                        transports.add(alias.asname or alias.name)
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
        transports=transports,
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
    called = {
        id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    }

    # **A transport is reported where it is NAMED, not only where it is called**,
    # and that is the one dimension where the paragraph about pulling a client
    # out of a container does not transfer. Measured: a transport class as a
    # default argument called later, one in a tuple, and a bare
    # `AsyncBaseTransport` subclass all reported nothing, and the first of those
    # is `fetch.PinnedTransport`'s own signature, which is the shape a copier
    # copies. A client cannot be used without being constructed at the site; a
    # transport can be handed about as a class and constructed somewhere this
    # walk never looks.
    #
    # The call site is skipped so a plain `httpx.AsyncHTTPTransport()` is one
    # offence and not two.
    for node in ast.walk(tree):
        if id(node) in called:
            continue
        if (isinstance(node, ast.Name) and node.id in names.transports) or (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in names.httpx
            and node.attr in TRANSPORT_CLASSES
        ):
            found.append(f"names a transport at line {node.lineno}")

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
        unparseable. Measured live, all eleven catalogues answer 200 under
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

    @pytest.mark.asyncio
    async def test_a_body_nested_too_deeply_is_a_value_error_and_not_a_500(self):
        """`RecursionError` is a `RuntimeError`, so no reader's except clause sees it.

        The body is built here rather than pinned as a constant so the depth is
        the thing asserted: at 100,000 levels it is 600,001 bytes, under a third
        of `MAX_RESPONSE_BYTES`, so the size cap is not what stops this and the
        conversion in `Fetched.json` is.
        """
        nested = b'{"a":' * 100_000 + b"1" + b"}" * 100_000
        assert len(nested) < fetch.MAX_RESPONSE_BYTES

        with respx.mock:
            respx.get(URL).mock(return_value=httpx.Response(200, content=nested))
            answer = await fetch.get_once(URL)

        with pytest.raises(ValueError):
            answer.json()

    @pytest.mark.asyncio
    async def test_a_body_nested_deeply_but_not_too_deeply_still_parses(self):
        """The conversion turns a parse failure into `ValueError`, not every body.

        Without this arm, `Fetched.json` raising `ValueError` unconditionally
        would pass the one above. 40 levels is well inside the parser's limit.
        """
        with respx.mock:
            respx.get(URL).mock(
                return_value=httpx.Response(
                    200, content=b'{"a":' * 40 + b"1" + b"}" * 40
                )
            )
            answer = await fetch.get_once(URL)

        parsed = answer.json()
        for _ in range(40):
            parsed = parsed["a"]
        assert parsed == 1


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
    is flagged where it happens and the handle never has to be followed.

    **That reasoning holds for a client and not for a transport**, which is why
    a transport is reported where it is named. A client is useless unless it is
    constructed at the site; a transport class is a value, so it travels as a
    default argument or inside a tuple and is constructed somewhere this walk
    never looks. Measured: all three of those shapes reported nothing until the
    naming pass existed, and the first is `fetch.PinnedTransport`'s own
    signature. What is genuinely missed:

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
        "transport construction": "import httpx\nt = httpx.AsyncHTTPTransport()\n",
        "transport class as a default argument": (
            "import httpx\n\n\ndef door(inner=httpx.AsyncHTTPTransport):\n"
            "    return inner()\n"
        ),
        "transport class in a container": (
            "import httpx\nMAKERS = (httpx.AsyncHTTPTransport,)\nt = MAKERS[0]()\n"
        ),
        "a transport subclass": (
            "import httpx\n\n\nclass T(httpx.AsyncBaseTransport):\n"
            "    async def handle_async_request(self, request):\n        ...\n"
        ),
        "sync transport construction": "import httpx\nt = httpx.HTTPTransport()\n",
        "imported transport class": (
            "from httpx import AsyncHTTPTransport\nt = AsyncHTTPTransport()\n"
        ),
        "a request handed to a transport": (
            "import httpx\n\n\nasync def f(t: httpx.AsyncBaseTransport, r):\n"
            "    return await t.handle_async_request(r)\n"
        ),
        "verb on the newer door's own client": (
            "import fetch\n\n\nasync def f():\n"
            "    async with fetch.pinned_client(fetch.PUBLIC_ADDRESSES) as client:\n"
            "        return await client.get('u')\n"
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
        "the pinned door, imported by name": (
            "from fetch import pinned_client, get, PUBLIC_ADDRESSES\n\n\n"
            "async def f(url):\n"
            "    async with pinned_client(PUBLIC_ADDRESSES) as c:\n"
            "        return await get(c, url)\n"
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


class TestACredentialGoesOnlyToTheOriginItWasSetFor:
    """The header is asked for per hop, and it is never set on the client.

    Set on the client, httpx attaches it to whatever that client is next used
    for, which is the one arrangement neither this module's redirect guard nor
    the credential's own rule could see.
    """

    class _Credential:
        """The protocol `fetch` declares, with a record of what it was asked."""

        def __init__(self, origin: str) -> None:
            self.origin = origin
            self.asked: list[str] = []

        def header_for(self, url: str) -> dict[str, str]:
            self.asked.append(url)
            return {"Authorization": "Basic secret"} if url.startswith(self.origin) else {}

    @respx.mock
    async def test_it_is_sent_to_the_target(self):
        route = respx.get("https://catalogue.test/sru").mock(
            return_value=httpx.Response(200, text="ok")
        )
        credential = self._Credential("https://catalogue.test")
        await fetch.get_once("https://catalogue.test/sru", credential=credential)
        assert route.calls.last.request.headers["authorization"] == "Basic secret"

    @respx.mock
    async def test_nothing_is_sent_when_no_credential_is_given(self):
        route = respx.get("https://catalogue.test/sru").mock(
            return_value=httpx.Response(200, text="ok")
        )
        await fetch.get_once("https://catalogue.test/sru")
        assert "authorization" not in route.calls.last.request.headers

    @respx.mock
    async def test_the_credential_is_asked_again_on_a_redirect(self):
        """Per hop, so the second hop's URL is what decides, not the first's."""
        respx.get("https://catalogue.test/a").mock(
            return_value=httpx.Response(302, headers={"location": "https://catalogue.test/b"})
        )
        respx.get("https://catalogue.test/b").mock(
            return_value=httpx.Response(200, text="ok")
        )
        credential = self._Credential("https://catalogue.test")
        await fetch.get_once("https://catalogue.test/a", credential=credential)
        assert credential.asked == [
            "https://catalogue.test/a",
            "https://catalogue.test/b",
        ]

    @respx.mock
    async def test_the_header_is_not_left_on_the_client_for_the_next_request(self):
        first = respx.get("https://catalogue.test/sru").mock(
            return_value=httpx.Response(200, text="ok")
        )
        second = respx.get("https://elsewhere.test/sru").mock(
            return_value=httpx.Response(200, text="ok")
        )
        credential = self._Credential("https://catalogue.test")
        async with fetch.catalogue_client() as client:
            await fetch.get(client, "https://catalogue.test/sru", credential=credential)
            await fetch.get(client, "https://elsewhere.test/sru", credential=credential)
        assert first.calls.last.request.headers["authorization"] == "Basic secret"
        assert "authorization" not in second.calls.last.request.headers


class _Recorder(httpx.AsyncBaseTransport):
    """An inner transport that answers 200 and keeps what it was handed.

    The whole subject of the pin is **which request reaches httpcore**, so the
    double sits exactly where httpcore would and reports it.
    """

    def __init__(self, body: str = "ok") -> None:
        self.body = body
        self.requests: list[httpx.Request] = []
        self.closes = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, text=self.body)

    async def aclose(self) -> None:
        self.closes += 1


class _Answers:
    """A resolver double: one answer per lookup, the last one repeating.

    A class rather than a function because the rebinding case needs the second
    lookup to answer differently from the first, which is the whole shape the
    pin exists to remove.
    """

    def __init__(self, *answers: tuple[str, ...]) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> tuple[str, ...]:
        self.asked.append((host, port))
        return self.answers[min(len(self.asked) - 1, len(self.answers) - 1)]


class TestWhichClassAnAddressIsIn:
    """`fetch.classify`, which is what every policy here is written against."""

    @pytest.mark.parametrize(
        ("address", "expected"),
        [
            ("127.0.0.1", fetch.AddressClass.LOOPBACK),
            ("::1", fetch.AddressClass.LOOPBACK),
            ("0.0.0.0", fetch.AddressClass.UNSPECIFIED),
            ("::", fetch.AddressClass.UNSPECIFIED),
            ("169.254.169.254", fetch.AddressClass.LINK_LOCAL),
            ("fe80::1", fetch.AddressClass.LINK_LOCAL),
            ("10.0.0.5", fetch.AddressClass.PRIVATE),
            ("172.16.0.1", fetch.AddressClass.PRIVATE),
                        ("100.64.0.1", fetch.AddressClass.PRIVATE),
            ("fd00::5", fetch.AddressClass.PRIVATE),
            ("224.0.0.1", fetch.AddressClass.MULTICAST),
            ("ff02::1", fetch.AddressClass.MULTICAST),
            ("8.8.8.8", fetch.AddressClass.PUBLIC),
            ("2606:4700::1111", fetch.AddressClass.PUBLIC),
            ("240.0.0.1", fetch.AddressClass.RESERVED),
            ("2001:db8::1", fetch.AddressClass.RESERVED),
            ("2001::1", fetch.AddressClass.RESERVED),
        ],
    )
    def test_an_address_is_in_the_class_its_registry_entry_says(
        self, address, expected
    ):
        assert fetch.classify(address) == expected

    @pytest.mark.parametrize(
        "spelling",
        [
            "::ffff:169.254.169.254",
            "::169.254.169.254",
            "64:ff9b::a9fe:a9fe",
        ],
    )
    def test_a_v4_address_wrapped_in_a_v6_prefix_is_classed_as_the_v4_one(
        self, spelling
    ):
        """The three prefixes that carry a v4 address and are read as v6.

        **Two of the three are `is_global`**, so a classifier that did not
        unwrap them would call the cloud metadata endpoint public: measured on
        Python 3.14, `::169.254.169.254` and `64:ff9b::a9fe:a9fe` both answer
        True to `is_global` and neither has an `ipv4_mapped`.
        """
        assert fetch.classify(spelling) == fetch.AddressClass.LINK_LOCAL
        assert not fetch.HOUSEHOLD_ADDRESSES.permits(spelling)

    def test_a_household_address_reached_by_its_mapped_form_is_still_private(self):
        """The row that makes the unwrap load bearing, and it is not a refusal.

        **All three spellings above stay green when the unwrap is deleted**, and
        the other seat's mutation run is the evidence: `ipaddress` classes the
        mapped form as link local by itself, and the other two fall to
        `RESERVED`, which is refused either way. The class where the unwrap
        changes the mapped answer is this one: without it `::ffff:10.0.0.1` is
        `RESERVED`, which is a **household server on a dual stack box refused**,
        the one thing this door must not do.
        """
        assert fetch.classify("::ffff:10.0.0.1") == fetch.AddressClass.PRIVATE
        assert fetch.HOUSEHOLD_ADDRESSES.permits("::ffff:10.0.0.1")

    def test_6to4_and_teredo_are_refused_whole_rather_than_unwrapped(self):
        """They carry a v4 address too and both fall to `RESERVED` on their own.

        Unwrapping would move them from refused by every policy to refused by
        most, which is the weaker answer. `2002:a9fe:a9fe::1` is the metadata
        endpoint inside a 6to4 address, and `ipaddress.is_private` answers True
        for it, which is why the private ranges here are written out.
        """
        assert fetch.classify("2002:a9fe:a9fe::1") == fetch.AddressClass.RESERVED
        assert not fetch.HOUSEHOLD_ADDRESSES.permits("2002:a9fe:a9fe::1")
        assert not fetch.PUBLIC_ADDRESSES.permits("2002:a9fe:a9fe::1")

    def test_the_third_rfc_1918_block_is_the_network_it_is_meant_to_be(self):
        """Written as an integer in `fetch.py` because the publish gate refuses
        its dotted form, so this is what stands in for reading it.

        A test carrying that form would not publish either, which is why the
        assertion is on the integer and the prefix length.
        """
        block = fetch._PRIVATE_NETWORKS[2]
        assert (int(block.network_address), block.prefixlen) == (0xC0A80000, 16)
        assert fetch.classify(block[9]) == fetch.AddressClass.PRIVATE

    def test_no_range_iana_marks_unreachable_comes_out_public(self):
        """The arm that keeps the `RESERVED` fallthrough from being a claim.

        **`IPv6Address.is_global` is `not is_private`**, so on that family this
        classifier is only as current as the interpreter, and a range Python's
        list is missing is `PUBLIC` here. Two of these were: `fec0::a9fe:a9fe`
        and `5f00::1` were admitted by `PUBLIC_ADDRESSES` until
        `_NOT_GLOBALLY_REACHABLE` named them. The table is the IANA special
        purpose registry's entries that a catalogue could never be served from.
        """
        unreachable = [
            "0.0.0.0",
            "10.0.0.5",
            "100.64.0.1",
            "127.0.0.1",
            "169.254.169.254",
            "172.16.0.1",
            "192.0.0.170",
            "192.0.2.1",
            "198.18.0.1",
            "198.51.100.1",
            "203.0.113.1",
            "240.0.0.1",
            "255.255.255.255",
            "::",
            "::1",
            "64:ff9b::a9fe:a9fe",
            "100::1",
            "2001::1",
            "2001:db8::1",
            "2002:a9fe:a9fe::1",
            "5f00::1",
            "fc00::1",
            "fe80::1",
            "fec0::a9fe:a9fe",
        ]

        public = [
            address
            for address in unreachable
            if fetch.classify(address) == fetch.AddressClass.PUBLIC
        ]

        assert public == []
        assert not any(fetch.PUBLIC_ADDRESSES.permits(a) for a in unreachable)

    def test_a_range_nobody_named_is_reserved_rather_than_public(self):
        """The fallback arm, which is what keeps a future allocation refused.

        `is_global` is consulted last and everything it refuses lands in
        `RESERVED`, so the classes admitted by a policy are the ones written
        down rather than the ones left over.
        """
        assert fetch.classify("192.0.0.170") == fetch.AddressClass.RESERVED
        assert fetch.classify("198.18.0.1") == fetch.AddressClass.RESERVED

    @pytest.mark.parametrize("nonsense", ["", "not-an-address", "library.test", "1.2.3"])
    def test_a_policy_refuses_what_does_not_parse_as_an_address(self, nonsense):
        """A resolver answering something unreadable is not a reason to connect."""
        assert not fetch.HOUSEHOLD_ADDRESSES.permits(nonsense)
        assert not fetch.PUBLIC_ADDRESSES.permits(nonsense)
        with pytest.raises(ValueError):
            fetch.classify(nonsense)

    def test_the_two_shipped_policies_differ_where_the_doors_differ(self):
        """A household server is on private space; a typed catalogue is not.

        The one class both refuse is the one this pin was built for.
        """
        assert fetch.HOUSEHOLD_ADDRESSES.permits("10.0.0.10")
        assert fetch.HOUSEHOLD_ADDRESSES.permits("127.0.0.1")
        assert not fetch.PUBLIC_ADDRESSES.permits("10.0.0.10")
        assert not fetch.PUBLIC_ADDRESSES.permits("127.0.0.1")
        assert not fetch.HOUSEHOLD_ADDRESSES.permits("169.254.169.254")
        assert not fetch.PUBLIC_ADDRESSES.permits("169.254.169.254")


class TestResolveThenPin:
    """The control another ticket is waiting on: resolve once, refuse, connect there.

    A check on the address a name resolves to is worth nothing if the connection
    then does its own lookup, so what these pin is that the address classified
    is the address connected to.
    """

    def _client(self, policy, resolver, recorder):
        return httpx.AsyncClient(
            transport=fetch.PinnedTransport(
                policy, resolver=resolver, inner=lambda: recorder
            )
        )

    async def test_the_connection_is_made_to_the_address_that_was_classified(self):
        recorder = _Recorder()
        resolver = _Answers(("10.0.0.10",))

        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, resolver, recorder
        ) as client:
            await client.get("http://calibre.test:8083/opds")

        assert str(recorder.requests[0].url) == "http://10.0.0.10:8083/opds"
        assert resolver.asked == [("calibre.test", 8083)]

    async def test_the_name_travels_as_the_host_header_and_as_the_tls_server_name(self):
        """The pin must not become a different request.

        The `Host` header is what a virtual host answers on, and `sni_hostname`
        is what the certificate is checked against: pinning without either one
        would reach the right address as the wrong client, and TLS would then be
        validated against a literal address that no catalogue's certificate
        names.
        """
        recorder = _Recorder()

        async with self._client(
            fetch.PUBLIC_ADDRESSES, _Answers(("93.184.216.34",)), recorder
        ) as client:
            await client.get("https://catalogue.test/sru")

        pinned = recorder.requests[0]
        assert pinned.headers["host"] == "catalogue.test"
        assert pinned.extensions["sni_hostname"] == "catalogue.test"

    async def test_a_name_that_resolves_into_a_refused_range_never_reaches_a_socket(
        self,
    ):
        """Refused before the connection, not after it.

        A policy applied after connecting is a policy that has already made the
        request it was refusing.
        """
        recorder = _Recorder()

        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, _Answers(("169.254.169.254",)), recorder
        ) as client:
            with pytest.raises(fetch.AddressRefused):
                await client.get("http://metadata.test/latest/meta-data/")

        assert recorder.requests == []

    async def test_a_literal_the_policy_refuses_is_refused_without_a_lookup(self):
        recorder = _Recorder()
        resolver = _Answers(("10.0.0.10",))

        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, resolver, recorder
        ) as client:
            with pytest.raises(fetch.AddressRefused):
                await client.get("http://169.254.169.254/latest/meta-data/")

        assert resolver.asked == [], "a literal is nobody's name to resolve"
        assert recorder.requests == []

    async def test_a_second_answer_is_classified_again_rather_than_trusted(self):
        """The rebinding case, and the one a check without a pin fails.

        The name answers with a household address, then with the metadata
        endpoint. The first request is pinned to the address that was checked,
        and the second is refused: no answer is carried over from a previous
        lookup, and no lookup happens between a check and a connection.
        """
        recorder = _Recorder()
        resolver = _Answers(("10.0.1.9",), ("169.254.169.254",))

        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, resolver, recorder
        ) as client:
            await client.get("http://calibre.test:8083/opds")
            with pytest.raises(fetch.AddressRefused):
                await client.get("http://calibre.test:8083/opds?page=2")

        assert [str(r.url.host) for r in recorder.requests] == ["10.0.1.9"]

    async def test_a_name_answering_with_both_is_pinned_to_the_admitted_address(self):
        """Stated at the code as something this does not refuse.

        mDNS routinely gives a household machine a link local address beside its
        real one, so refusing the whole answer would refuse the feature. The
        refused address is simply never connected to.
        """
        recorder = _Recorder()
        resolver = _Answers(("fe80::1", "10.0.1.9"))

        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, resolver, recorder
        ) as client:
            await client.get("http://calibre.test:8083/opds")

        assert recorder.requests[0].url.host == "10.0.1.9"

    async def test_the_callers_request_is_not_rewritten_so_the_hop_guard_sees_the_name(
        self,
    ):
        """`_same_host_hop` compares a `Location` against `response.request.url`.

        Rewriting the caller's own request in place would make that comparison
        read the pinned literal, so a catalogue redirecting to its own name
        would be refused as a redirect off host. The pin belongs to the request
        httpcore is handed and to nothing above it.
        """
        recorder = _Recorder()

        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, _Answers(("10.0.1.9",)), recorder
        ) as client:
            response = await client.get("http://calibre.test:8083/opds")

        assert response.request.url.host == "calibre.test"
        assert recorder.requests[0].url.host == "10.0.1.9"

    async def test_two_names_at_one_address_do_not_share_a_pool(self):
        """A pooled TLS connection does no second handshake.

        httpcore keys its pool on the request's origin, which is the pinned
        literal, so one pool for two names would carry the second name's request
        on a connection whose certificate was checked for the first. Keyed by
        name, there is no such connection to reuse.
        """
        made: list[_Recorder] = []

        def factory() -> _Recorder:
            made.append(_Recorder())
            return made[-1]

        transport = fetch.PinnedTransport(
            fetch.PUBLIC_ADDRESSES,
            resolver=_Answers(("93.184.216.34",)),
            inner=factory,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://one.test/a")
            await client.get("https://two.test/a")
            await client.get("https://one.test/b")

        assert len(made) == 2, "one pool per name, and the third call reuses the first"
        assert [len(recorder.requests) for recorder in made] == [2, 1]

    async def test_closing_the_client_closes_every_pool_it_opened(self):
        made: list[_Recorder] = []

        def factory() -> _Recorder:
            made.append(_Recorder())
            return made[-1]

        transport = fetch.PinnedTransport(
            fetch.PUBLIC_ADDRESSES,
            resolver=_Answers(("93.184.216.34",)),
            inner=factory,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://one.test/a")
            await client.get("https://two.test/a")

        assert [recorder.closes for recorder in made] == [1, 1]

    def test_a_proxy_in_the_environment_cannot_take_the_request_out_of_this_door(
        self, monkeypatch
    ):
        """`trust_env=False`, and it is the difference between a pin and a hope.

        With it on, httpx mounts a proxy transport **in front of** the one it
        was given, so every request would leave through the proxy with the name
        unresolved and none of this would run.

        **The control is the other client**, which shows the environment really
        is set and really does move a request: without that half this assertion
        passes on a machine with no proxy variable, which is every machine that
        runs it.
        """
        monkeypatch.setenv("HTTP_PROXY", "http://proxy.test:3128")
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
        url = httpx.URL("http://catalogue.test/sru")

        pinned = fetch.pinned_client(fetch.PUBLIC_ADDRESSES)
        trusting = fetch.catalogue_client()
        try:
            assert isinstance(
                pinned._transport_for_url(url), fetch.PinnedTransport
            )
            assert not isinstance(
                trusting._transport_for_url(url), fetch.PinnedTransport
            ), "the control: the environment moves a request that trusts it"
        finally:
            # Closing them would need an event loop; neither has opened a socket.
            del pinned, trusting

    async def test_a_resolver_answering_nothing_is_a_refusal_and_not_a_crash(self):
        recorder = _Recorder()

        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, _Answers(()), recorder
        ) as client:
            with pytest.raises(fetch.AddressRefused):
                await client.get("http://calibre.test:8083/opds")

        assert recorder.requests == []

    async def test_a_name_that_does_not_resolve_stays_inside_the_httpx_hierarchy(
        self,
    ):
        """`socket.gaierror` is an `OSError` and not an `httpx.HTTPError`.

        Resolution used to happen inside `httpx.AsyncHTTPTransport`, under
        `map_httpcore_exceptions`, so a name that does not resolve arrived as a
        `ConnectError` and every handler in this tree caught it. Doing it in the
        transport moved it outside all of them: without this arm a typo in a
        settings field is a 500. Same shape as the `UnicodeError` in
        `_walk_hops`.
        """

        async def refuses(host: str, port: int) -> tuple[str, ...]:
            raise socket.gaierror(-2, "Name or service not known")

        recorder = _Recorder()
        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, refuses, recorder
        ) as client:
            with pytest.raises(httpx.HTTPError) as failure:
                await client.get("http://nowhere.test/opds")

        assert not isinstance(failure.value, fetch.AddressRefused), (
            "a name nobody answered for is not an address this door refused"
        )
        assert recorder.requests == []

    async def test_the_next_admitted_address_is_tried_when_one_will_not_connect(
        self,
    ):
        """Pinning one address would have removed anyio's walk over the answer.

        A dual stack household name whose first address is an unroutable ULA
        would then fail as a server that did not answer. Only a connect failure
        moves on, because nothing has been sent at that point.
        """

        class _Unreachable(_Recorder):
            async def handle_async_request(self, request):
                self.requests.append(request)
                if request.url.host == "fd00::5":
                    raise httpx.ConnectError("no route to host")
                return httpx.Response(200, text="ok")

        recorder = _Unreachable()
        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, _Answers(("fd00::5", "10.0.1.9")), recorder
        ) as client:
            response = await client.get("http://calibre.test:8083/opds")

        assert response.status_code == 200
        assert [r.url.host for r in recorder.requests] == ["fd00::5", "10.0.1.9"]

    async def test_a_refused_address_is_not_tried_even_when_the_admitted_one_fails(
        self,
    ):
        """The failover walks the admitted addresses and no others.

        The control for the test above: an answer of one refused address and one
        unreachable admitted address ends in the connect failure, not in a
        request to the refused one.
        """

        class _Unreachable(_Recorder):
            async def handle_async_request(self, request):
                self.requests.append(request)
                raise httpx.ConnectError("no route to host")

        recorder = _Unreachable()
        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES,
            _Answers(("169.254.169.254", "10.0.1.9")),
            recorder,
        ) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("http://calibre.test:8083/opds")

        assert [r.url.host for r in recorder.requests] == ["10.0.1.9"]

    async def test_a_refusal_is_an_httpx_error_so_every_caller_already_handles_it(
        self,
    ):
        """`FetchRefused`'s reason, one door along: thirteen `try` blocks catch
        `httpx.HTTPError` and none of them was changed for this."""
        assert issubclass(fetch.AddressRefused, httpx.HTTPError)
        assert issubclass(fetch.AddressRefused, fetch.FetchRefused)

    async def test_a_request_with_a_body_is_tried_at_one_address_only(self):
        """A stream is read once, so there is no second attempt to make.

        Retrying one would send an empty body to the second address and look
        like a request the caller made. This door only makes GETs, which is why
        the walk above is safe and why this arm exists at all.
        """

        class _Unreachable(_Recorder):
            async def handle_async_request(self, request):
                self.requests.append(request)
                raise httpx.ConnectError("no route to host")

        recorder = _Unreachable()
        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, _Answers(("fd00::5", "10.0.1.9")), recorder
        ) as client:
            with pytest.raises(httpx.ConnectError):
                await client.post("http://calibre.test:8083/opds", content=b"x")

        assert [r.url.host for r in recorder.requests] == ["fd00::5"]

    async def test_only_a_connect_failure_moves_on_to_the_next_address(self):
        """A read timeout is not a reason to try a second address.

        **This test exists because a mutation showed the sentence was stated and
        not tested.** Widening the `except` in `handle_async_request` to
        `httpx.HTTPError` was caught by nothing: every other failover test
        raises a `ConnectError`. What that admits is a request replayed against
        an address the first one never reached, after bytes have already gone
        out, and this door puts a household's `Authorization` header on them.
        """

        class _Slow(_Recorder):
            async def handle_async_request(self, request):
                self.requests.append(request)
                raise httpx.ReadTimeout("the server stopped sending")

        recorder = _Slow()
        async with self._client(
            fetch.HOUSEHOLD_ADDRESSES, _Answers(("fd00::5", "10.0.1.9")), recorder
        ) as client:
            with pytest.raises(httpx.ReadTimeout):
                await client.get("http://calibre.test:8083/opds")

        assert [r.url.host for r in recorder.requests] == ["fd00::5"]
