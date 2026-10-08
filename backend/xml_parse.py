"""What turning a stranger's XML into a tree may cost, and the one builder that holds it.

**Three modules parse XML somebody else wrote**: `marc.py` an upload, `metadata.py` a
catalogue's response and `opds.py` a feed page. Each refuses a document type declaration
before it parses, for the reason `metadata.DOCTYPE` gives, and each builds its tree
through `DepthBoundedTree` and `fed` here, which refuse a second construct that makes a
document's size a lie, nesting, and bound what refusing it costs. **Two constructs
measured, not a complete set**: a namespaced name, expanded once per distinct name, is a
third nobody has measured yet.

**A module of its own rather than a corner of any of the three**, because the bound is
about XML and not about catalogues, uploads or feeds, and each of those modules argues for
its own surface elsewhere. What this holds is a builder and a loop; the parse itself stays
at each door, where `tests/test_house_rules.py` requires it and its suppression says why.
"""

from typing import Final
from xml.etree import ElementTree

#: The deepest an element of any document this application parses may sit,
#: counting the root as one.
#:
#: **A construct that makes a document's size a lie and needs no doctype.**
#: Every element costs its parser a node and, while it is open, a frame of
#: expat's own; a chain of them costs both at once. Measured by `tracemalloc` on
#: CPython 3.14.0: 140,145 bytes of nested `<a>` peaked at 39.7 times their
#: size, flat empty elements at 22.0 and text bearing ones at 11.9, so the nest
#: is about twice anything else. One 5 MiB MARC upload of it grew a process by
#: 215 MiB, and three of them, which one member may send in a minute, by 546
#: MiB in one process, against a 512Mi pod.
#:
#: **32 is over four times the deepest document recorded in this tree**, 7, an
#: SRU envelope around a record, across 165 test literals and the fixtures; a
#: MODS `relatedItem` nests a description inside another and is the shape that
#: would go deepest, and it is a few levels, not dozens.
MAX_DEPTH: Final = 32

#: How much of a document the parser is handed at once, in bytes or characters.
#:
#: **What makes the depth refusal cheap rather than merely correct.** A handler
#: that raises does not stop expat: it goes on reading whatever it was handed,
#: opening a frame for every element, and only the next call to `feed` sees the
#: error. Handed a whole 140 KB nest, a refused parse still peaked at 19 times
#: its size; handed this much at a time, at 189 KB whatever the size, because
#: the refusal arrives within one chunk of the element that crossed the bound.
#: Chunking costs nothing measurable: on 5 MiB of MARC records, best of five,
#: the default builder took 0.363 seconds in one feed and 0.366 in chunks.
#: **The cost is the builder**, `DepthBoundedTree` running in Python per
#: element where the default runs in C, 0.41 to 0.42 seconds either way. So a
#: larger chunk buys no speed and raises what a refusal costs.
PARSE_CHUNK: Final = 4096


#: What any parse costs before its input counts, in bytes `tracemalloc` traces.
#:
#: **Half of an allocation bound, and the other half is each door's own
#: `ALLOCATION_FACTOR`**: a byte door's traced peak over one call stays under its
#: factor times the bytes it was handed, plus this. Nothing at runtime counts
#: allocation; the bound is what the generated property at each door holds it
#: to. **Its positive control for the tree builder is the width atom in
#: `tests/strategies.py`**: measured, a builder retaining 100 bytes more per
#: element reds the MARC, OPDS and catalogue properties, and none of them clean.
#: A reader's cost per field it reads has no control: no reader reads the atom.
#: Measured: a parse of a few bytes peaks near 10 KB, and a nest refused by
#: `MAX_DEPTH` near 190 KB, because `PARSE_CHUNK` bytes of it are parsed
#: whatever the bound says. This is room above both.
ALLOCATION_FLOOR: Final = 256 * 1024


class DepthBoundedTree(ElementTree.TreeBuilder):
    """An element tree builder that refuses an element deeper than `MAX_DEPTH`.

    **The refusal is a `ParseError`**, so each of the three byte doors that
    parse turns it into the refusal it already declares, exactly as it does a
    document that is not well formed. Handed to `ElementTree.XMLParser` as its
    target and fed through `fed`, which is what bounds what a refusal costs.
    """

    def __init__(self) -> None:
        super().__init__()
        self._depth = 0

    def start(self, tag: str, attrs: dict[str, str], /) -> ElementTree.Element:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise ElementTree.ParseError(
                f"An element is nested more than {MAX_DEPTH} deep, which no "
                "document this reads ever is."
            )
        return super().start(tag, attrs)

    def end(self, tag: str, /) -> ElementTree.Element:
        self._depth -= 1
        return super().end(tag)


def fed(parser: ElementTree.XMLParser, content: str | bytes) -> ElementTree.Element:
    """The tree `parser` builds from `content`, handed over `PARSE_CHUNK` at a time.

    `ElementTree.fromstring` is this with one call to `feed`, so every error it
    raised is raised here, from the same parser, in the same order.
    """
    for offset in range(0, len(content), PARSE_CHUNK):
        parser.feed(content[offset : offset + PARSE_CHUNK])
    return parser.close()
