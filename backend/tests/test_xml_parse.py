"""Tests for backend/xml_parse.py: the depth and namespace bounds and what refusing costs.

Each of the three byte doors that parse XML holds its own positive control at each
bound, in its own file, through its own refusal. These are the builder's and the
loop's, below any door.
"""

import tracemalloc
from xml.etree import ElementTree

import pytest

import xml_parse
from tests.strategies import FAR_PAST_ANY_DEPTH


def _parser() -> ElementTree.XMLParser:
    return ElementTree.XMLParser(target=xml_parse.DepthBoundedTree())


def _tree(content: str | bytes) -> ElementTree.Element:
    return xml_parse.fed(_parser(), content)


def _nest(depth: int) -> str:
    return "<a>" * depth + "</a>" * depth


class TestTheDepthBound:
    def test_a_document_at_the_bound_is_built(self):
        tree = _tree(_nest(xml_parse.MAX_DEPTH))
        assert sum(1 for _ in tree.iter()) == xml_parse.MAX_DEPTH

    def test_one_level_past_it_is_a_parse_error(self):
        with pytest.raises(ElementTree.ParseError, match="nested more than"):
            _tree(_nest(xml_parse.MAX_DEPTH + 1))

    def test_depth_is_how_deep_and_not_how_many(self):
        """A builder that counted elements rather than open ones would refuse a
        flat document a hundred times wider than the bound."""
        flat = "<r>" + "<a/>" * (xml_parse.MAX_DEPTH * 100) + "</r>"
        assert len(_tree(flat)) == xml_parse.MAX_DEPTH * 100


class TestWhatARefusalCosts:
    """**The chunked feed is what makes a refusal cheap.** Handed a whole nest,
    expat goes on opening an element per tag after the builder has raised, so
    the cost of refusing grows with the document. Fed `PARSE_CHUNK` at a time, it
    stops within one chunk, whatever the size."""

    @pytest.mark.parametrize("depth", [FAR_PAST_ANY_DEPTH, FAR_PAST_ANY_DEPTH * 10])
    def test_a_nest_far_past_the_bound_costs_one_chunk_at_any_size(self, depth):
        """Ten times the nest is not ten times the cost. Fed whole, the smaller
        of these peaked near 2.7 MB."""
        assert _peak_of_refusing(_nest(depth)) <= xml_parse.ALLOCATION_FLOOR


def _peak_of_refusing(content: str | bytes, refusal: str = "nested more than") -> int:
    """The traced peak of refusing `content`, which must be refused."""
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        with pytest.raises(ElementTree.ParseError, match=refusal):
            xml_parse.fed(_parser(), content)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _names_under(namespace: str, count: int) -> str:
    """A namespace declared once and `count` distinct short names using it."""
    return f'<r xmlns:p="{namespace}">' + "".join(f"<p:a{i}/>" for i in range(count)) + "</r>"


def _declared_and_used_in_one_tag(namespace: str, count: int) -> str:
    """A namespace declared on a tag and `count` distinct attributes of that tag using it."""
    names = " ".join(f'p:a{i}=""' for i in range(count))
    return f'<r xmlns:p="{namespace}" {names}/>'


class TestTheNamespaceBound:
    def test_a_namespace_at_the_bound_is_read(self):
        tree = _tree(_names_under("u" * xml_parse.MAX_NAMESPACE, 2))
        assert [child.tag for child in tree] == [
            "{" + "u" * xml_parse.MAX_NAMESPACE + "}a0",
            "{" + "u" * xml_parse.MAX_NAMESPACE + "}a1",
        ]

    def test_one_byte_past_it_is_a_parse_error(self):
        with pytest.raises(ElementTree.ParseError, match="namespace is longer"):
            _tree(_names_under("u" * (xml_parse.MAX_NAMESPACE + 1), 2))

    def test_an_astral_namespace_at_the_bound_in_bytes_is_read(self):
        astral = "\U0001f600" * (xml_parse.MAX_NAMESPACE // 4)
        assert _tree(_names_under(astral, 1))[0].tag == "{" + astral + "}a0"

    def test_an_astral_namespace_one_character_past_it_is_refused_inside_the_floor(self):
        """**The bound is in UTF-8 bytes**, because what the parser keeps per
        name is: a quarter as many astral characters cost what the bound does.
        Used by the attributes of the tag declaring it, which expat expands
        before any handler runs, so this is refused before the parse or not
        cheaply at all."""
        astral = "\U0001f600" * (xml_parse.MAX_NAMESPACE // 4 + 1)
        assert (
            _peak_of_refusing(_declared_and_used_in_one_tag(astral, 4_000), "namespace is longer")
            <= xml_parse.ALLOCATION_FLOOR
        )

    def test_a_namespace_longer_in_utf8_than_in_its_declared_encoding_is_refused(self):
        """A Latin-1 `é` is one byte as written and two as the parser keeps it,
        so this is under the bound as written and over it as parsed: the case
        only the handler sees. So it is refused after expat has expanded the
        declaring tag's attributes, at what an accepted declaration at the bound
        costs, and no floor is asserted."""
        content = (
            b'<?xml version="1.0" encoding="iso-8859-1"?><r xmlns:p="'
            + b"\xe9" * (xml_parse.MAX_NAMESPACE // 2 + 1)
            + b'"><p:a/></r>'
        )
        with pytest.raises(ElementTree.ParseError, match="namespace is longer"):
            _tree(content)

    def test_the_default_namespace_is_bounded_too(self):
        """`xmlns="..."` names every unprefixed element after it."""
        long = "u" * (xml_parse.MAX_NAMESPACE + 1)
        with pytest.raises(ElementTree.ParseError, match="namespace is longer"):
            _tree(f'<r xmlns="{long}"><a/></r>')

    def test_distinct_names_under_a_long_namespace_are_refused_inside_the_floor(self):
        """**The construct the bound is for.** Unbounded, this shape peaked over
        a thousand times its own size by `tracemalloc` on the suite pod (CPython
        3.14.8, expat 2.8.5), because each distinct name is kept with the whole
        namespace in it."""
        assert (
            _peak_of_refusing(_names_under("u" * 10_000, 2_000), "namespace is longer")
            <= xml_parse.ALLOCATION_FLOOR
        )

    @pytest.mark.parametrize("as_bytes", [False, True], ids=["text", "bytes"])
    def test_attributes_in_the_declaring_tag_are_refused_inside_the_floor(self, as_bytes):
        """**Expat expands these names before any handler runs**, so a refusal
        in the handler comes after the cost: refused there alone, this peaked
        at about a hundred times the floor on the suite pod. So the declaration
        is refused before the parser sees it, by one scan for text and another
        for bytes, which is what a MARC upload is."""
        content = _declared_and_used_in_one_tag("u" * 10_000, 2_000)
        written = content.encode() if as_bytes else content
        assert _peak_of_refusing(written, "namespace is longer") <= xml_parse.ALLOCATION_FLOOR

    def test_a_short_look_alike_in_another_value_does_not_hide_the_declaration_after_it(self):
        """A single quoted value may hold a `"`, so text reading as a short
        declaration can open inside one and run on to the real declaration's
        quote. A scan that consumed the look-alike's value would resume past the
        real `xmlns:p=` and leave this to the handler, after the cost."""
        content = (
            "<r b=' xmlns=\"" + "A" * 70 + "' " + _declared_and_used_in_one_tag("u" * 10_000, 2_000)[3:]
        )
        assert _peak_of_refusing(content, "namespace is longer") <= xml_parse.ALLOCATION_FLOOR


def _distinct_elements(count: int, prefix: str = "", declaration: str = "") -> str:
    """A root and `count - 1` children, each child a name not used before."""
    children = "".join(f"<{prefix}a{i}/>" for i in range(count - 1))
    return f"<r{declaration}>{children}</r>"


def _one_tag_of(count: int, space: str = "", quote: str = '"') -> str:
    """One tag carrying `count` distinct attributes, `space` either side of each `=`
    and each value an empty pair of `quote`."""
    return "<r><e" + "".join(f" a{i}{space}={space}{quote * 2}" for i in range(count)) + "/></r>"


class TestTheNameBound:
    def test_a_document_at_the_bound_is_built(self):
        assert len(_tree(_distinct_elements(xml_parse.MAX_NAMES))) == xml_parse.MAX_NAMES - 1

    def test_one_name_past_it_is_a_parse_error(self):
        with pytest.raises(ElementTree.ParseError, match="distinct element and attribute"):
            _tree(_distinct_elements(xml_parse.MAX_NAMES + 1))

    def test_attribute_names_are_counted_with_element_names(self):
        """Expat keeps an attribute name for the whole parse as it does an
        element name, so a document naming a new attribute on every tag of one
        name costs what one naming a new element does."""
        with pytest.raises(ElementTree.ParseError, match="distinct element and attribute"):
            _tree("<r>" + "".join(f'<e a{i}=""/>' for i in range(xml_parse.MAX_NAMES)) + "</r>")

    @pytest.mark.parametrize("as_bytes", [False, True], ids=["text", "bytes"])
    def test_distinct_names_under_a_namespace_at_its_bound_are_refused_inside_the_floor(
        self, as_bytes
    ):
        """**The construct the bound is for**: every name a new one, each
        carrying the longest namespace `MAX_NAMESPACE` admits, which is what a
        name costs most. Refused at the name past the bound, so the cost stops
        there whatever the size."""
        declaration = f' xmlns:p="{"u" * xml_parse.MAX_NAMESPACE}"'
        content = _distinct_elements(50_000, "p:", declaration)
        written = content.encode() if as_bytes else content
        assert (
            _peak_of_refusing(written, "distinct element and attribute")
            <= xml_parse.ALLOCATION_FLOOR
        )


class TestTheAttributeBound:
    def test_a_tag_at_the_bound_is_built(self):
        assert len(_tree(_one_tag_of(xml_parse.MAX_ATTRIBUTES))[0].attrib) == (
            xml_parse.MAX_ATTRIBUTES
        )

    @pytest.mark.parametrize(
        ("space", "quote"),
        [("", '"'), (" ", '"'), ("\n", '"'), ("\t\r\n", '"'), ("", "'")],
        ids=["none", "space", "newline", "mixed", "single quotes"],
    )
    def test_one_attribute_past_it_is_a_parse_error_however_they_are_written(self, space, quote):
        """XML allows any of its four whitespace characters either side of `=`,
        and either quote around a value."""
        with pytest.raises(ElementTree.ParseError, match="tag carries more than"):
            _tree(_one_tag_of(xml_parse.MAX_ATTRIBUTES + 1, space, quote))

    def test_a_close_angle_in_a_value_does_not_end_the_count(self):
        """XML allows `>` in a value, so a walk ending the tag at the first `>`
        would count one here."""
        content = '<r><e z=">"' + "".join(
            f' a{i}=""' for i in range(xml_parse.MAX_ATTRIBUTES)
        ) + "/></r>"
        with pytest.raises(ElementTree.ParseError, match="tag carries more than"):
            _tree(content)

    @pytest.mark.parametrize("as_bytes", [False, True], ids=["text", "bytes"])
    def test_a_crowded_tag_under_a_namespace_at_its_bound_is_refused_inside_the_floor(
        self, as_bytes
    ):
        """**Expat expands one tag's attribute names before any handler runs**,
        so `MAX_NAMES` in `start` comes after their cost. Refused before the
        parse instead, by one scan for text and another for bytes."""
        namespace = "u" * xml_parse.MAX_NAMESPACE
        content = f'<r xmlns:p="{namespace}"><e' + "".join(
            f' p:a{i}=""' for i in range(50_000)
        ) + "/></r>"
        written = content.encode() if as_bytes else content
        assert _peak_of_refusing(written, "tag carries more than") <= xml_parse.ALLOCATION_FLOOR


def _attributed(count: int, length: int) -> str:
    """`count` elements of one empty attribute, padded with space to `length` in one chunk."""
    content = "<r>" + '<e a=""/>' * count + "</r>"
    assert len(content) <= length <= xml_parse.PARSE_CHUNK
    return content.replace("<r>", "<r>" + " " * (length - len(content)))


class TestTheDensityBound:
    #: Three times the allowance, so the bound's arithmetic has room to be wrong
    #: either side of it.
    COUNT = xml_parse.ATTRIBUTED_ALLOWANCE * 3
    #: The shortest document holding `COUNT` at the bound.
    LENGTH = xml_parse.BYTES_PER_ATTRIBUTED * (COUNT - xml_parse.ATTRIBUTED_ALLOWANCE)

    @pytest.mark.parametrize("as_bytes", [False, True], ids=["text", "bytes"])
    def test_a_document_at_the_bound_is_built(self, as_bytes):
        content = _attributed(self.COUNT, self.LENGTH)
        assert len(_tree(content.encode() if as_bytes else content)) == self.COUNT

    @pytest.mark.parametrize("as_bytes", [False, True], ids=["text", "bytes"])
    def test_one_more_in_the_same_length_is_a_parse_error(self, as_bytes):
        content = _attributed(self.COUNT + 1, self.LENGTH)
        with pytest.raises(ElementTree.ParseError, match="carries an attribute"):
            _tree(content.encode() if as_bytes else content)

    def test_elements_without_attributes_are_not_counted(self):
        """A bare element costs about a quarter of one carrying an attribute,
        and packed as close as XML allows stays under every door's factor. The
        width atom in `tests/strategies.py` is this shape."""
        assert len(_tree("<r>" + "<e/>" * 10_000 + "</r>")) == 10_000

    @pytest.mark.parametrize("as_bytes", [False, True], ids=["text", "bytes"])
    def test_the_shortest_such_element_repeated_is_refused_inside_the_floor(self, as_bytes):
        """**The construct the bound is for**: 36.5 times its size read whole on
        the suite pod. Refused within one chunk, so the cost stops there."""
        content = "<r>" + '<e a=""/>' * 100_000 + "</r>"
        written = content.encode() if as_bytes else content
        assert _peak_of_refusing(written, "carries an attribute") <= xml_parse.ALLOCATION_FLOOR

    def test_a_parser_building_through_another_target_is_refused(self):
        """The builder counts against what `fed` hands it, so a parser built on
        the default target would be fed with the bound silently off."""
        with pytest.raises(TypeError, match="DepthBoundedTree"):
            xml_parse.fed(ElementTree.XMLParser(), "<r/>")


class TestTheFeedIsTheParserItFeeds:
    @pytest.mark.parametrize(
        "content",
        [b"<a>", b"", "not xml", b'<?xml version="1.0" encoding="bogus"?><a/>', "<a>x</a><b/>"],
    )
    def test_it_raises_what_one_feed_raises(self, content):
        """`fed` is `ElementTree.fromstring` in chunks, so a document it refuses
        is refused with the same class and message as one call would."""
        with pytest.raises(Exception) as whole:  # noqa: PT011  the class is the assertion
            ElementTree.fromstring(content)
        with pytest.raises(type(whole.value)) as chunked:
            _tree(content)
        assert str(chunked.value) == str(whole.value)
