"""Whether a route path written in prose names a route the app serves.

**The authority is the app's own route table**, handed in by the caller as
`APIRoute` objects. This module never imports `main`, because importing it opens
the database, so a caller that already holds the app passes its routes.

**A mention is a backtick span**, outside a fenced block, holding a path and
nothing else but an optional method in front. A path written without backticks
is not read, which is how prose writes a route that is gone on purpose: the
backticks are dropped, and the checker never reads tense.

Three matching rules, each closing a hole a plain template match leaves open:

* **A `{name:path}` route matches only prose spelling it exactly.** Matched as a
  template, `/api/{rest:path}` would make every `/api/...` path live.
* **A literal fills a `{name}` slot only where the declared type accepts it.**
  The type is read from every dependency of the route as well as its handler,
  so `5` fills a `{book_id}` an integer dependency declares and `bulk` does not.
* **A placeholder, `{x}`, `<x>` or `:x`, fills a whole segment** that holds a
  slot, so `/covers/<id>` names `/covers/{book_id}.{extension}`. One inside a
  segment, as in `<id>.<ext>`, stands for one slot; `:x` counts only whole.

A method in front must be one the route declares.

**Absolute and relative.** An absolute mention starts with the first segment of
some live route. It is a **prefix claim** when it ends in `/`, `/*` or `/...`,
and green when a live route other than a catch all extends it, or, for a bare
trailing `/`, when it names a whole route; a plain absolute mention is
green when it names a route or stops at a segment boundary inside one, unless a
method leads it, which makes it a call that must name a whole route. A
relative mention starts with any other segment and is read only where the caller
asks for it, in a paragraph carrying route context: it matches the tail of a live
route at a segment boundary.

**What this does not read**: a fenced block; a method in its own table cell,
whose path in the next cell is read alone; a path on another host, which prose
writes with its host; and a span holding anything besides the method and path.
So these blind spots follow, each one an honest spelling:

* A full URL on this host, `http://localhost:8000/api/...`, is not read.
* A lowercase method is not read, nor a path broken inside a segment across a
  line.
* An unpaired backtick earlier in a paragraph shifts the pairing, and every
  later mention in that paragraph can go unread.
* Both callers hand it Markdown only, so a docstring or a comment in source is
  not read.
"""

import enum
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from fastapi.routing import APIRoute

METHODS: Final = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

_SLOT: Final = re.compile(r"\{([^}:]+)(:path)?\}")
_PLACEHOLDER: Final = re.compile(r"\{[^}]*\}|<[^>]*>")
#: A placeholder filling a whole segment, where Express's `:name` is one too.
#: Inside a segment a colon is ordinary text, as in `{rest:path}`.
_WHOLE_PLACEHOLDER: Final = re.compile(r"\{[^}]*\}|<[^>]*>|:[A-Za-z_]\w*")
#: Where a prefix claim ends: the slash, or what stands for "and below" after it.
_PREFIX_END: Final = re.compile(r"/(\*|\.\.\.)?$")
#: The app's own placeholder spelling, the one that gives a paragraph route context.
_BRACED: Final = re.compile(r"\{[^}]*\}")
_SPAN: Final = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
_FENCE: Final = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_MENTION: Final = re.compile(r"(?:(?P<method>[A-Z]+) )?(?P<path>/\S*)")
_PARAGRAPH_BREAK: Final = re.compile(r"\n[ \t]*\n")


@dataclass(frozen=True)
class Route:
    """One route as the matcher needs it."""

    path: str
    methods: frozenset[str]
    #: Each slot's declared type, by name.
    slots: tuple[tuple[str, object], ...]

    @property
    def catch_all(self) -> bool:
        return ":path}" in self.path

    @property
    def segments(self) -> list[str]:
        return self.path.strip("/").split("/")


@dataclass(frozen=True)
class Mention:
    """One backtick span read as a route mention."""

    document: Path
    line: int
    text: str
    method: str | None
    path: str
    relative: bool


def route_table(routes: Iterable[APIRoute]) -> tuple[Route, ...]:
    """The table, from the app's routes. Slot types come from the whole
    dependency tree, since a dependency declares `{book_id}` where its handler
    does not."""
    table = []
    for route in routes:
        slots: dict[str, object] = {}
        stack = [route.dependant]
        while stack:
            dependant = stack.pop()
            stack.extend(dependant.dependencies)
            for field in dependant.path_params:
                slots[field.name] = field.field_info.annotation
        table.append(Route(route.path, frozenset(route.methods or ()), tuple(sorted(slots.items()))))
    return tuple(table)


def app_segments(table: Iterable[Route]) -> frozenset[str]:
    """The first segment of every live route: what makes a mention absolute."""
    return frozenset(route.segments[0] for route in table)


def _accepts(kind: object, literal: str) -> bool:
    if kind is int:
        return literal.isdigit()
    if isinstance(kind, type) and issubclass(kind, enum.Enum):
        return literal in {str(member.value) for member in kind}
    return literal != ""


def _fills(template: str, written: str, slots: dict[str, object]) -> bool:
    """Whether the prose segment `written` fills the template segment `template`."""
    if _WHOLE_PLACEHOLDER.fullmatch(written):
        return bool(_SLOT.search(template))
    if _PLACEHOLDER.search(written):
        # A placeholder inside a segment, as in `<id>.<ext>`, stands for one slot.
        parts = _PLACEHOLDER.split(written)
        return bool(re.fullmatch(r"\{[^}]+\}".join(map(re.escape, parts)), template))
    pattern = ""
    names = []
    at = 0
    for slot in _SLOT.finditer(template):
        pattern += re.escape(template[at : slot.start()]) + "(.+?)"
        names.append(slot.group(1))
        at = slot.end()
    pattern += re.escape(template[at:])
    match = re.fullmatch(pattern, written)
    if match is None:
        return False
    return all(_accepts(slots.get(name), value) for name, value in zip(names, match.groups(), strict=True))


def _matches(route: Route, written: list[str], *, tail: bool, prefix: bool) -> bool:
    """Whether `written` names `route`: whole, its tail, or a prefix of it."""
    if route.catch_all:
        spelled = route.segments[-len(written) :] if tail else route.segments
        return not prefix and spelled == written
    segments = route.segments
    if prefix:
        if len(written) >= len(segments):
            return False
        segments = segments[: len(written)]
    elif tail:
        if len(written) > len(segments):
            return False
        segments = segments[-len(written) :]
    elif len(written) != len(segments):
        return False
    slots = dict(route.slots)
    return all(_fills(template, word, slots) for template, word in zip(segments, written, strict=True))


def is_live(mention: Mention, table: Iterable[Route]) -> bool:
    """Whether `mention` names a route, or a prefix of one, in `table`."""
    path = re.split(r"[?#]", mention.path, maxsplit=1)[0]
    claims_a_prefix = _PREFIX_END.search(path) is not None
    written = _PREFIX_END.sub("", path).rstrip("*").strip("/").split("/")
    candidates = [route for route in table if mention.method is None or mention.method in route.methods]
    if mention.relative:
        return any(_matches(route, written, tail=True, prefix=False) for route in candidates)
    whole = any(_matches(route, written, tail=False, prefix=False) for route in candidates)
    # A bare trailing slash on a whole route is a spelling of it: nothing
    # extends a leaf, so reading it only as a prefix refuses a live route.
    if whole and (not claims_a_prefix or path.endswith("/")):
        return True
    # A method in front makes a call of it, not a prefix, unless it ends like one.
    if mention.method is not None and not claims_a_prefix:
        return False
    return any(_matches(route, written, tail=False, prefix=True) for route in candidates)


def _unfenced(text: str) -> str:
    """`text` with every fenced block blanked, line numbers kept."""
    lines = text.split("\n")
    fence = None
    for number, line in enumerate(lines):
        opened = _FENCE.match(line)
        if fence is None and opened:
            fence = opened.group(1)[0] * len(opened.group(1))
            lines[number] = ""
        elif fence is not None:
            if line.strip().startswith(fence) and set(line.strip()) <= {fence[0]}:
                fence = None
            lines[number] = ""
    return "\n".join(lines)


def _carries_route_context(spans: list[str], paragraph: str, segments: frozenset[str]) -> bool:
    """A paragraph holding an absolute mention, a span led by a method, a slash
    span holding a `{placeholder}`, or a path under `routers/`."""
    for span in spans:
        found = _MENTION.fullmatch(span)
        if found and (found.group("method") in METHODS or _BRACED.search(found.group("path"))):
            return True
        if found and found.group("path").strip("/").split("/")[0] in segments:
            return True
    return "routers/" in paragraph


def mentions(document: Path, text: str, segments: frozenset[str], *, relative: bool) -> Iterator[Mention]:
    """Every route mention in `text`. A relative one only when `relative` asks,
    and only in a paragraph carrying route context."""
    text = _unfenced(text)
    starts = [0, *(match.end() for match in _PARAGRAPH_BREAK.finditer(text))]
    ends = [*(match.start() for match in _PARAGRAPH_BREAK.finditer(text)), len(text)]
    for start, end in zip(starts, ends, strict=True):
        paragraph = text[start:end]
        found = [
            (start + span.start(), " ".join(span.group(2).split())) for span in _SPAN.finditer(paragraph)
        ]
        context = None
        for offset, span in found:
            mention = _MENTION.fullmatch(span)
            if not mention or (mention.group("method") and mention.group("method") not in METHODS):
                continue
            path = mention.group("path")
            absolute = path.strip("/").split("/")[0] in segments
            if not absolute:
                if not relative:
                    continue
                if context is None:
                    context = _carries_route_context([s for _, s in found], paragraph, segments)
                if not context:
                    continue
            yield Mention(
                document,
                text.count("\n", 0, offset) + 1,
                span,
                mention.group("method"),
                path,
                not absolute,
            )


#: What a refusal tells its author, because the fix is a convention rather
#: than code, and the obvious ways around the check are the forbidden kind.
REMEDY: Final = (
    "a route that is gone on purpose is written without backticks, and a path on another"
    " host is written with its host: tests/route_mentions.py says why"
)


def refusal(dead: list[str]) -> str:
    """The failure message for `dead`: each line, then the remedy."""
    return "\n".join([*dead, REMEDY])


def dead_mentions(
    documents: Iterable[Path], table: tuple[Route, ...], root: Path, *, relative: bool = False
) -> list[str]:
    """Each mention in `documents` that names no live route, as `path:line: text`."""
    segments = app_segments(table)
    return [
        f"{mention.document.relative_to(root)}:{mention.line}: {mention.text}"
        for document in documents
        for mention in mentions(document, document.read_text(encoding="utf-8"), segments, relative=relative)
        if not is_live(mention, table)
    ]
