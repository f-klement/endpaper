"""Tests for backend/vocabulary_dumps.py.

Both first class sources convert from a trimmed capture of their own release
(`tests/fixtures/vocabularies/`, provenance in its README) through the one seam,
and a conversion that does not finish leaves no data file under the declared
name.
"""

import gzip
import io
from pathlib import Path

import pytest

import vocabularies
import vocabulary_dumps
from vocabulary_dumps import ConversionFailed

FIXTURES = Path(__file__).parent / "fixtures" / "vocabularies"
GND = FIXTURES / "gnd_sachbegriff_2026_11_20.jsonld"
LCSH = FIXTURES / "lcsh_subjects_skos_2026_11_20.jsonl"


def _schemes() -> dict[str, vocabularies.Scheme]:
    return {s.id: s for s in vocabularies.load_declaration(vocabularies.DECLARATION.read_text())}


def _release(path: Path) -> io.BytesIO:
    return io.BytesIO(gzip.compress(path.read_bytes()))


def _converted(scheme: str, fixture: Path, out: Path) -> list[vocabularies.Entry]:
    release = vocabulary_dumps.convert(_schemes()[scheme], _release(fixture), out)
    return list(vocabularies.read_entries(out, _schemes()[scheme], release))


def _flipped(release: io.BytesIO, at: int) -> bytes:
    corrupt = bytearray(release.getvalue())
    corrupt[at] ^= 0xFF
    return bytes(corrupt)


class TestTheGndSubjectHeadings:
    def test_each_heading_becomes_an_entry_under_its_stored_identifier(self, tmp_path):
        entries = _converted("gnd", GND, tmp_path / "gnd.jsonl")

        assert [entry.id for entry in entries] == [
            "(DE-588)4000030-8",
            "(DE-588)4000056-4",
            "(DE-588)4000002-3",
            "(DE-588)4000098-9",
            "(DE-588)4000023-0",
        ]

    def test_variant_names_are_the_synonyms_composed_to_nfc(self, tmp_path):
        entries = {entry.subject: entry for entry in _converted("gnd", GND, tmp_path / "gnd.jsonl")}

        assert entries["Abfall"].synonyms == ("Waste", "Müll", "Abfallstoff", "Abfälle")

    def test_a_node_straddling_every_chunk_boundary_still_decodes(self, tmp_path, monkeypatch):
        """Seven characters a chunk cuts objects and decomposed characters alike."""
        monkeypatch.setattr(vocabulary_dumps, "_CHUNK", 7)

        assert len(_converted("gnd", GND, tmp_path / "gnd.jsonl")) == 5


class TestTheLibraryOfCongressSubjectHeadings:
    def test_each_concept_becomes_an_entry_and_a_deprecated_label_does_not(self, tmp_path):
        entries = _converted("lcsh", LCSH, tmp_path / "lcsh.jsonl")

        assert [entry.subject for entry in entries] == [
            "ActionScript (Computer program language)",
            "Chanchera Lake (Argentina)",
            "Rio Oscuro (N.M.)",
            "Beaver Creek (Yavapai County, Ariz.)",
            "Pogo sticks",
        ]

    def test_one_alternate_label_and_several_both_become_synonyms(self, tmp_path):
        entries = {entry.subject: entry for entry in _converted("lcsh", LCSH, tmp_path / "lcsh.jsonl")}

        assert entries["Pogo sticks"].synonyms == ("Pogosticks",)
        assert len(entries["Rio Oscuro (N.M.)"].synonyms) == 4
        assert entries["Pogo sticks"].id == "http://id.loc.gov/authorities/subjects/sh00000034"

    def test_a_labelled_node_outside_the_publishers_id_form_is_passed_over(self, tmp_path):
        foreign = b'{"@id": "http://example.org/x", "skos:prefLabel": "Foreign"}\n'
        release = io.BytesIO(gzip.compress(LCSH.read_bytes() + foreign))
        out = tmp_path / "lcsh.jsonl"

        recorded = vocabulary_dumps.convert(_schemes()["lcsh"], release, out)

        assert "Foreign" not in [
            entry.subject for entry in vocabularies.read_entries(out, _schemes()["lcsh"], recorded)
        ]

    def test_the_nodes_passed_over_for_their_id_form_are_counted_in_one_warning(self, tmp_path, caplog):
        foreign = b'{"@id": "http://example.org/x", "skos:prefLabel": "Foreign"}\n' * 2
        release = io.BytesIO(gzip.compress(LCSH.read_bytes() + foreign))

        with caplog.at_level("WARNING", logger="endpaper.vocabulary_dumps"):
            vocabulary_dumps.convert(_schemes()["lcsh"], release, tmp_path / "lcsh.jsonl")

        assert [record.getMessage() for record in caplog.records] == [
            "lcsh: passed over 2 nodes whose id is not in the publisher's form"
        ]


class TestAConversionThatDoesNotFinish:
    def test_a_cut_release_leaves_the_previous_data_file_in_place(self, tmp_path):
        out = tmp_path / "gnd.jsonl"
        out.write_text("previous\n")
        cut = io.BytesIO(_release(GND).getvalue()[:-40])

        with pytest.raises(ConversionFailed, match="could not be read"):
            vocabulary_dumps.convert(_schemes()["gnd"], cut, out)

        assert out.read_text() == "previous\n"
        assert list(tmp_path.iterdir()) == [out]

    def test_a_release_yielding_no_entry_is_refused_and_writes_nothing(self, tmp_path):
        out = tmp_path / "lcsh.jsonl"
        empty = io.BytesIO(gzip.compress(b'{"@graph": [{"@id": "_:b1"}]}\n'))

        with pytest.raises(ConversionFailed, match="no entry"):
            vocabulary_dumps.convert(_schemes()["lcsh"], empty, out)

        assert list(tmp_path.iterdir()) == []

    def test_a_release_that_is_not_json_is_refused(self, tmp_path):
        with pytest.raises(ConversionFailed, match="not a JSON document"):
            vocabulary_dumps.convert(
                _schemes()["gnd"], io.BytesIO(gzip.compress(b"[ [ {oops} ] ]")), tmp_path / "g"
            )

    @pytest.mark.parametrize(
        ("scheme", "release"),
        [
            ("gnd", gzip.compress(b'{"a":' * 100_000 + b"1" + b"}" * 100_000)),
            ("lcsh", gzip.compress(b"[" * 200_000 + b"]" * 200_000)),
            ("lcsh", gzip.compress(b'{"@id": ' + b"1" * 5_000 + b"}")),
            ("gnd", _flipped(_release(GND), 20)),
        ],
        ids=[
            "nested past the decoder's depth, one document",
            "nested past it, one line",
            "an integer past Python's digit limit",
            "a corrupt deflate stream",
        ],
    )
    def test_every_malformed_release_is_a_conversion_failure(self, tmp_path, scheme, release):
        with pytest.raises(ConversionFailed, match="could not be read"):
            vocabulary_dumps.convert(_schemes()[scheme], io.BytesIO(release), tmp_path / "out.jsonl")

        assert list(tmp_path.iterdir()) == []

    def test_a_conversion_leaves_another_conversions_partial_file_alone(self, tmp_path):
        out = tmp_path / "gnd.jsonl"
        other = tmp_path / ".gnd.jsonl.partial"
        other.write_text("another refresh, still writing\n")

        vocabulary_dumps.convert(_schemes()["gnd"], _release(GND), out)

        assert other.read_text() == "another refresh, still writing\n"


#: Per fixture, its longest value in characters as each reader measures one:
#: the longest GND node object and the longest LCSH line, measured 2026-11-20 by
#: the least `MAX_VALUE` converting the fixture one character a chunk.
_LONGEST_VALUE = [("gnd", GND, 2_869), ("lcsh", LCSH, 2_374)]


class TestTheValueBound:
    """`MAX_VALUE`, at each fixture's longest value and one below it, read one
    character a chunk so that every prefix of a value meets the check."""

    @pytest.mark.parametrize(("scheme", "fixture", "longest"), _LONGEST_VALUE)
    def test_a_release_whose_longest_value_is_the_bound_converts(
        self, tmp_path, monkeypatch, scheme, fixture, longest
    ):
        monkeypatch.setattr(vocabulary_dumps, "_CHUNK", 1)
        monkeypatch.setattr(vocabulary_dumps, "MAX_VALUE", longest)

        assert _converted(scheme, fixture, tmp_path / "out.jsonl")

    @pytest.mark.parametrize(("scheme", "fixture", "longest"), _LONGEST_VALUE)
    def test_a_value_one_past_the_bound_is_refused(self, tmp_path, monkeypatch, scheme, fixture, longest):
        monkeypatch.setattr(vocabulary_dumps, "_CHUNK", 1)
        monkeypatch.setattr(vocabulary_dumps, "MAX_VALUE", longest - 1)

        with pytest.raises(ConversionFailed):
            vocabulary_dumps.convert(_schemes()[scheme], _release(fixture), tmp_path / "out.jsonl")
        assert list(tmp_path.iterdir()) == []


class TestTheDataFileBound:
    """`MAX_DATA_FILE`, at the size the GND fixture converts to and one below."""

    def test_a_release_converting_to_exactly_the_bound_converts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vocabulary_dumps, "MAX_DATA_FILE", 566)

        assert len(_converted("gnd", GND, tmp_path / "gnd.jsonl")) == 5

    def test_a_release_converting_past_the_bound_is_refused_and_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vocabulary_dumps, "MAX_DATA_FILE", 565)

        with pytest.raises(ConversionFailed, match="past 565 bytes"):
            vocabulary_dumps.convert(_schemes()["gnd"], _release(GND), tmp_path / "gnd.jsonl")
        assert list(tmp_path.iterdir()) == []
