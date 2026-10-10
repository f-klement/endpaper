"""What turning a stranger's XML into a tree may cost, and the one builder that holds it.

**Three modules parse XML somebody else wrote**: `marc.py` an upload, `metadata.py` a
catalogue's response and `opds.py` a feed page. Each refuses a document type declaration
before it parses, for the reason `metadata.DOCTYPE` gives, and each builds its tree
through `DepthBoundedTree` and `fed` here, which refuse five more constructs that make a
document's size a lie (nesting, a long namespace, many distinct names, a crowded tag and
elements carrying attributes packed close) and bound what refusing them costs. **Measured
constructs, not a complete set**: `MAX_NAMES` says what it leaves.

**A module of its own rather than a corner of any of the three**, because the bound is
about XML and not about catalogues, uploads or feeds, and each of those modules argues for
its own surface elsewhere. What this holds is a builder and a loop; the parse itself stays
at each door, where `tests/test_house_rules.py` requires it and its suppression says why.
"""

import re
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

#: The longest namespace a document this application parses may declare, in
#: UTF-8 bytes.
#:
#: **A construct that makes a document's size a lie and needs no doctype**, as
#: the nest is. The parser keeps one string per distinct name with the whole
#: namespace in it, in UTF-8 and again as text, so a namespace declared once and
#: used by many distinct short names costs their count times its length in
#: bytes. `ElementTree.fromstring` of `_names_under("u" * 100_000, 1_000)`,
#: from `tests/test_xml_parse.py`, peaked near 200 MB from 109 KB, by
#: `tracemalloc` on the suite pod, CPython 3.14.8 with expat 2.8.5.
#:
#: **Refused twice, and the first is what makes refusing cheap.** `fed` refuses
#: a declaration whose value as written is over the bound before the parser
#: sees a byte, because expat expands the names of the declaring tag's own
#: attributes before any handler runs, and its own limit on that, where it has
#: one, grows with the input. `DepthBoundedTree.start_ns` refuses the value as
#: parsed, which is the exact rule: a value in an eight bit encoding can be
#: under the bound as written and over it in UTF-8. That value is refused by
#: the handler alone, after expat has expanded the declaring tag's attributes,
#: so it costs what an accepted declaration at the bound does.
#:
#: **Distinct names are what a long namespace multiplies**, so `MAX_NAMES`
#: bounds how many there are and this bounds what each costs.
#:
#: **256 is over six times the longest namespace recorded in this tree**, 39,
#: the SRU diagnostic namespace, across the test literals and the fixtures.
MAX_NAMESPACE: Final = 256

#: Why a namespace is refused, by `fed` before the parse or by the builder in it.
_TOO_LONG: Final = (
    f"A namespace is longer than {MAX_NAMESPACE} bytes, which no document this "
    "reads ever declares."
)

#: A namespace declaration as written, `xmlns` or `xmlns:prefix` then its
#: value, holding at least `%d` units of value. **Whitespace before `xmlns`**,
#: which XML requires before every attribute, so a name merely ending in it is
#: not read. **The value is read in a lookahead, so a match ends before it**:
#: a single quoted value may hold a `"`, and text reading as a short
#: declaration inside one would otherwise consume the real declaration after
#: it. **It stays one pass**: no quantifier gives back what it took, a prefix
#: holds no colon, and a value read from one quote runs to the next quote of
#: its kind, so each character of a value is read at most once per kind. Text
#: that only looks like a declaration, in character data or a comment, is read
#: as one, and so is a value whose character references would expand to under
#: the bound: each is refused loudly.
_DECLARATION: Final = (
    r"""xmlns(?<=[ \t\r\n]xmlns)(?::[^ \t\r\n=<>"':]*+)?[ \t\r\n]*+=[ \t\r\n]*+"""
    r"""(?=(?:"([^"<]{%d,}+)|'([^'<]{%d,}+)))"""
)

#: In bytes as written, which for UTF-8, what every MARCXML file declares, are
#: the bytes the parser keeps. Blind to UTF-16, as `marc.py`'s doctype scan is,
#: and for the reason it gives that upload refuses one.
_LONG_IN_BYTES: Final = re.compile((_DECLARATION % ((MAX_NAMESPACE + 1,) * 2)).encode("ascii"))

#: In characters, at a quarter of the bound, since a character is at most four
#: UTF-8 bytes; a value found is then measured in bytes.
_MAYBE_LONG_IN_TEXT: Final = re.compile(_DECLARATION % ((MAX_NAMESPACE // 4 + 1,) * 2))


def _declares_a_long_namespace(content: str | bytes) -> bool:
    """Whether `content` declares a namespace longer than `MAX_NAMESPACE` as written."""
    if isinstance(content, bytes):
        return _LONG_IN_BYTES.search(content) is not None
    for match in _MAYBE_LONG_IN_TEXT.finditer(content):
        start, end = match.span(match.lastindex or 0)
        # Over the bound in characters is over it in bytes, so a long value is
        # never copied to be measured.
        if end - start > MAX_NAMESPACE or len(content[start:end].encode()) > MAX_NAMESPACE:
            return True
    return False


#: The most distinct element and attribute names one document may use, each
#: as expanded with its namespace.
#:
#: **A construct that makes a document's size a lie and needs no doctype**, as
#: the nest is. Expat keeps every distinct name for the whole parse and the
#: builder caches each expanded, so a document that never repeats a name costs
#: more per byte than any door's `ALLOCATION_FACTOR`, and a namespace at
#: `MAX_NAMESPACE` about doubles that. `ElementTree.fromstring` of
#: `_distinct_elements(100_000)`, from `tests/test_xml_parse.py`, peaked at
#: 39.7 times its size, and of `_distinct_elements(50_000, "p:", ...)` under a
#: namespace at the bound at 81.6, by `tracemalloc` on the suite pod, CPython
#: 3.14.8 with expat 2.8.5.
#:
#: **Counted in `DepthBoundedTree.start`, element names apart from attribute
#: names**, because expat keeps the two in separate tables. After a refusal
#: expat reads on to the end of the chunk it holds, as it does past the nest,
#: so the cost stops near the bound: those 50,000 names fed through `fed`
#: peaked at 170 KB. One tag's attribute names are expanded before `start` sees
#: the tag, which is why `MAX_ATTRIBUTES` bounds them ahead of the parse.
#:
#: **What it leaves, measured on the same pod**: a long name, which its own
#: bytes pay for, and distinct prefixes bound to one namespace, which expand to
#: one name here while expat keeps each. Through `fed`, a document of 127
#: distinct names of 1,000 ASCII characters each peaked at 3.5 times its size,
#: and about 1 MiB of `<ab:e xmlns:ab="u" ab:a=""/>`, a new shortest prefix on
#: each, at 21.2.
#: Both are under every door's factor.
#:
#: **The margin is thin, and it is measured on what a catalogue sends.** MODS
#: does not repeat its names from record to record as MARC does, so the names a
#: page uses grow with its size, and that size is ours to choose:
#: `targets.SEEDED[CatalogueSource.LOC].search_cap`, twenty records. The most
#: any Library of Congress page of that size recorded for this bound used is
#: 87, and all of them together over a hundred. That page is
#: `tests/fixtures/loc_mods_search.xml`, and the catalogue door's test reds when
#: the cap and the page's record count part. **Raising the cap means recording
#: a page of the new size and counting its names against this bound again.**
#: **Raising the bound trades that margin against what a refusal costs**: a
#: document using every name the bound allows, then a tag of 64 new attributes
#: under an astral namespace at `MAX_NAMESPACE`, already peaks through `fed`
#: near `ALLOCATION_FLOOR`, and over it with a bound of 192.
MAX_NAMES: Final = 128

#: Why a document is refused by `DepthBoundedTree.start` for its names.
_TOO_MANY_NAMES: Final = (
    f"The document uses more than {MAX_NAMES} distinct element and attribute "
    "names, which no document this reads ever does."
)

#: The most attributes one start tag may carry, namespace declarations included.
#:
#: **Expat expands every attribute name of a tag before any handler sees the
#: tag**, so `MAX_NAMES` in `start` comes after their cost, and this is refused
#: before the parse instead. `ElementTree.fromstring` of
#: `_one_tag_of(100_000)`, from `tests/test_xml_parse.py`, peaked at 29.3 times
#: its size, and as many prefixed names under a namespace at `MAX_NAMESPACE`
#: at 103.5, on the pod as above; `fed` refused each at 9 KB.
#:
#: **64 is sixteen times the most attributes on one tag of
#: `tests/fixtures/loc_mods_search.xml`**, the four on its `mods` root,
#: namespace declarations included as here.
MAX_ATTRIBUTES: Final = 64

#: Why a document is refused by `fed` for one of its tags.
_TOO_MANY_ATTRIBUTES: Final = (
    f"A tag carries more than {MAX_ATTRIBUTES} attributes, which no document "
    "this reads ever does."
)

#: XML's whitespace, the only characters it allows between the parts of a tag.
_SPACE: Final = r"[ \t\r\n]"

#: One attribute as a start tag writes it: whitespace, a name, `=` and a
#: value in either quote, which may hold a `>` and never a `<`.
_ATTRIBUTE: Final = (
    rf"""{_SPACE}++[^ \t\r\n<>/="']++{_SPACE}*+={_SPACE}*+(?:"[^"<]*+"|'[^'<]*+')"""
)

#: A start tag carrying more than `MAX_ATTRIBUTES` attributes, walked by a
#: tag's own grammar: `<`, a name, then attributes until one does not parse.
#: **It reads tags and not text**: markup escaped in character data, which an
#: Atom `summary` of `type="html"` holds, has no `<` and is never walked, and
#: the walk stops at the end of a tag. Text in a comment or CDATA that reads as
#: a crowded tag is walked, and refused loudly. **A tag the walk stops in early
#: is one expat refuses as it reads the tag, before expanding any attribute**:
#: 100,000 attributes behind a break in the first (no whitespace between two,
#: a `<` in a value, a value without quotes) cost 17 KB through `fed`, on the
#: pod as above. **It stays one pass**: an attempt starts at a `<` and no part
#: of it matches one, so it ends before the next; no quantifier gives back what
#: it took, and the two kinds of value open with different quotes. Blind to
#: UTF-16, as `_LONG_IN_BYTES` is.
_CROWDED: Final = rf"""<[^ \t\r\n<>!?/="']++(?:{_ATTRIBUTE}){{{MAX_ATTRIBUTES + 1}}}"""
_CROWDED_IN_TEXT: Final = re.compile(_CROWDED)
_CROWDED_IN_BYTES: Final = re.compile(_CROWDED.encode("ascii"))


def _carries_a_crowded_tag(content: str | bytes) -> bool:
    """Whether a tag in `content` carries more than `MAX_ATTRIBUTES` attributes as written."""
    if isinstance(content, bytes):
        return _CROWDED_IN_BYTES.search(content) is not None
    return _CROWDED_IN_TEXT.search(content) is not None


#: The fewest units of document, bytes or characters as `fed` is handed them,
#: each element carrying an attribute must come with on average, once there are
#: more than `ATTRIBUTED_ALLOWANCE` of them.
#:
#: **A construct that makes a document's size a lie and needs no doctype**, as
#: the nest is. An element costs the tree a node, and one carrying an
#: attribute a dictionary as well, about four times a bare one whatever the
#: attribute says. So the shortest of them repeated, `<e a=""/>`, cost 36.5
#: times its size through `marc.read` and `opds.read_page`, over every door's
#: `ALLOCATION_FACTOR`, where a bare `<e/>` cost 20.0, by `tracemalloc` on the
#: suite pod, CPython 3.14.8 with expat 2.8.5.
#:
#: **Counted in `DepthBoundedTree.start` against what `fed` has handed the
#: parser**, including the chunk being read, so the refusal comes within one
#: chunk of the element that crossed the bound. **A count fixed per document
#: could not hold a factor**, which is per byte: the costliest element costs
#: its door a few dozen bytes more than the factor allows, so a fixed count
#: small enough to keep that excess inside `ALLOCATION_FLOOR` is a few thousand
#: elements, and an honest MARC upload holds far more.
#:
#: **20 is the shortest element carrying an attribute that MARCXML allows**,
#: `<subfield code="a"/>`: the slim schema fixes both names and gives a code
#: one character. So no MARCXML document is refused for its density, whatever
#: wrote it, and `tests/test_marc.py` reads one made of nothing else. MARCXML
#: is the densest grammar these doors read, because every subfield carries its
#: code; the densest document recorded is our own export of one character
#: credits and headings, and `tests/test_marc.py` reads that back too.
#:
#: **Each door's `ALLOCATION_FACTOR` is measured on the costliest shape found
#: at this bound**, so moving it means measuring them again: the test at each
#: door reading that shape reds when the shape is no longer at the bound.
BYTES_PER_ATTRIBUTED: Final = 20

#: How many elements carrying attributes a document may hold whatever its size.
#:
#: **Refusing fewer buys nothing**: at the 36.5 times above, 64 of the
#: costliest element cost under 21 KB, inside `ALLOCATION_FLOOR`, so a short
#: document is never refused for being short.
ATTRIBUTED_ALLOWANCE: Final = 64

#: Why a document is refused by `DepthBoundedTree.start` for its density.
_TOO_DENSE: Final = (
    f"More than one element in every {BYTES_PER_ATTRIBUTED} bytes (characters, "
    "where the document is text) carries an attribute, which no document this "
    "reads ever has."
)


#: What any parse costs before its input counts, in bytes `tracemalloc` traces.
#:
#: **Half of an allocation bound, and the other half is each door's own
#: `ALLOCATION_FACTOR`**: a byte door's traced peak over one call stays under its
#: factor times the bytes it was handed, plus this. Nothing at runtime counts
#: allocation; the bound is what the generated property at each door holds it
#: to. **Its positive control for the tree builder is the width atom in
#: `tests/strategies.py`**: measured, a builder retaining 100 bytes more per
#: element reds the MARC, OPDS and catalogue properties, and none of them clean.
#: A reader's cost per field it reads has a control at the MARC upload only,
#: the same atom repeating an element that reader reads.
#: Measured: a parse of a few bytes peaks near 10 KB, and a nest refused by
#: `MAX_DEPTH` near 190 KB, because `PARSE_CHUNK` bytes of it are parsed
#: whatever the bound says. This is room above both.
ALLOCATION_FLOOR: Final = 256 * 1024


class DepthBoundedTree(ElementTree.TreeBuilder):
    """A tree builder refusing an element deeper than `MAX_DEPTH`, a namespace
    longer than `MAX_NAMESPACE`, more distinct names than `MAX_NAMES` and
    elements carrying attributes denser than `BYTES_PER_ATTRIBUTED`.

    **The refusal is a `ParseError`**, so each of the three byte doors that
    parse turns it into the refusal it already declares, exactly as it does a
    document that is not well formed. Handed to `ElementTree.XMLParser` as its
    target and fed through `fed`, which is what bounds what a refusal costs.
    """

    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self._elements: set[str] = set()
        self._attributes: set[str] = set()
        self._attributed = 0
        self._handed = 0

    def handed(self, length: int) -> None:
        """Count `length` more units of document as handed to the parser.

        `fed` calls this before each chunk, which is what `BYTES_PER_ATTRIBUTED`
        is counted against.
        """
        self._handed += length

    def start(self, tag: str, attrs: dict[str, str], /) -> ElementTree.Element:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise ElementTree.ParseError(
                f"An element is nested more than {MAX_DEPTH} deep, which no "
                "document this reads ever is."
            )
        self._elements.add(tag)
        self._attributes.update(attrs)
        if len(self._elements) + len(self._attributes) > MAX_NAMES:
            raise ElementTree.ParseError(_TOO_MANY_NAMES)
        if attrs:
            self._attributed += 1
            if self._attributed > self._handed // BYTES_PER_ATTRIBUTED + ATTRIBUTED_ALLOWANCE:
                raise ElementTree.ParseError(_TOO_DENSE)
        return super().start(tag, attrs)

    def end(self, tag: str, /) -> ElementTree.Element:
        self._depth -= 1
        return super().end(tag)

    def start_ns(self, prefix: str, uri: str, /) -> None:
        """Refuse a namespace longer than `MAX_NAMESPACE`, as a `ParseError`.

        The parser calls this for each declaration before the element carrying
        it starts, and builds the same tree as without it.
        """
        if len(uri.encode()) > MAX_NAMESPACE:
            raise ElementTree.ParseError(_TOO_LONG)


def fed(parser: ElementTree.XMLParser, content: str | bytes) -> ElementTree.Element:
    """The tree `parser` builds from `content`, handed over `PARSE_CHUNK` at a time.

    `ElementTree.fromstring` is this with one call to `feed`, so every error it
    raised is raised here, from the same parser, in the same order, except that a
    namespace `MAX_NAMESPACE` refuses as written and a tag `MAX_ATTRIBUTES`
    refuses are refused before any of them.

    **The parser's target is a `DepthBoundedTree` or this raises `TypeError`**,
    because the builder counts `BYTES_PER_ATTRIBUTED` against what this hands
    it, and any other target would be fed with that bound silently off.
    """
    target = parser.target
    if not isinstance(target, DepthBoundedTree):
        raise TypeError(f"fed builds through a DepthBoundedTree, not {type(target).__name__}")
    if _declares_a_long_namespace(content):
        raise ElementTree.ParseError(_TOO_LONG)
    if _carries_a_crowded_tag(content):
        raise ElementTree.ParseError(_TOO_MANY_ATTRIBUTES)
    for offset in range(0, len(content), PARSE_CHUNK):
        chunk = content[offset : offset + PARSE_CHUNK]
        target.handed(len(chunk))
        parser.feed(chunk)
    return parser.close()
