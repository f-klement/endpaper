"""Tests for backend/xml_parse.py: the depth bound and what refusing it costs.

Each of the three byte doors that parse XML holds its own positive control at the
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


def _peak_of_refusing(content: str) -> int:
    """The traced peak of refusing `content`, which must be refused."""
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        with pytest.raises(ElementTree.ParseError, match="nested more than"):
            xml_parse.fed(_parser(), content)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


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
