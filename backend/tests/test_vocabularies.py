"""Tests for backend/vocabularies.py.

The declaration loader refuses what nothing could answer and keeps a copy only
under a licence it knows; an entry read from a data file keeps four keys, takes
the stored identifier form and is refused unless it is the file its converter
recorded.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

import marc_fields
import vocabularies
from vocabularies import DeclarationRefused, EntriesRefused, Entry, Release


def _declaration(*schemes: str) -> str:
    return "subjects:\n  pid-type: sub\n  schemes:\n" + "".join(schemes)


def _scheme(**keys: str) -> str:
    lines = [f"{key.replace('_', '-')}: {value}" for key, value in keys.items()]
    return "    - " + "\n      ".join(lines) + "\n"


class TestTheDeclaration:
    def test_the_shipped_declaration_loads_both_first_class_vocabularies_with_a_copy(self):
        schemes = vocabularies.load_declaration(vocabularies.DECLARATION.read_text())

        assert [(scheme.id, scheme.data_file is not None) for scheme in schemes] == [
            ("gnd", True),
            ("lcsh", True),
        ]

    def test_a_scheme_id_is_lower_cased_as_a_stored_dollar_2_is(self):
        text = _declaration(_scheme(id="MeSH", licence="public-domain", data_file="m.jsonl"))

        assert vocabularies.load_declaration(text)[0].id == "mesh"

    def test_a_scheme_nothing_could_answer_is_refused(self):
        with pytest.raises(DeclarationRefused, match="nothing can answer"):
            vocabularies.load_declaration(_declaration(_scheme(id="x", licence="CC0-1.0")))

    def test_an_unknown_licence_drops_the_copy_and_keeps_the_live_source(self):
        text = _declaration(_scheme(id="gnd", licence="proprietary", data_file="g.jsonl", suggest="lobid"))

        scheme = vocabularies.load_declaration(text, suggesters={"lobid"})[0]

        assert (scheme.data_file, scheme.suggest) == (None, "lobid")

    def test_a_copy_with_no_licence_and_no_live_source_is_refused(self):
        """An InvenioRDM declaration carries no `licence`; a missing one is not
        permission to keep a copy."""
        with pytest.raises(DeclarationRefused, match="nothing can answer"):
            vocabularies.load_declaration(_declaration(_scheme(id="fos", data_file="f.yaml")))

    def test_a_suggest_naming_a_source_that_cannot_suggest_is_refused(self):
        text = _declaration(_scheme(id="gnd", suggest="dnb"))

        with pytest.raises(DeclarationRefused, match="cannot answer suggestions"):
            vocabularies.load_declaration(text, suggesters={"lobid"})

    @pytest.mark.parametrize("formats", ["[gzip]", "[gzip, rdf]", "[zip, json]", "[]"])
    def test_an_origin_format_no_converter_here_reads_is_refused(self, formats):
        text = _declaration(
            _scheme(id="x", licence="CC0-1.0", data_file="x.jsonl", origin="https://x", origin_format=formats)
        )

        with pytest.raises(DeclarationRefused, match="origin-format"):
            vocabularies.load_declaration(text)

    def test_a_single_origin_format_name_is_the_list_of_one(self):
        text = _declaration(
            _scheme(id="x", licence="CC0-1.0", data_file="x.jsonl", origin="https://x", origin_format="jsonl")
        )

        assert vocabularies.load_declaration(text)[0].origin_format == ("jsonl",)

    def test_an_origin_format_is_refused_even_where_the_licence_drops_the_copy(self):
        text = _declaration(
            _scheme(id="gnd", licence="proprietary", suggest="lobid", origin_format="[zip, json]")
        )

        with pytest.raises(DeclarationRefused, match="origin-format"):
            vocabularies.load_declaration(text, suggesters={"lobid"})

    def test_an_origin_without_its_format_is_refused(self):
        text = _declaration(_scheme(id="x", licence="CC0-1.0", data_file="x.jsonl", origin="https://x"))

        with pytest.raises(DeclarationRefused, match="together"):
            vocabularies.load_declaration(text)

    def test_one_scheme_declared_twice_in_two_cases_is_refused(self):
        twice = _scheme(id="GND", suggest="lobid") + _scheme(id="gnd", suggest="lobid")

        with pytest.raises(DeclarationRefused, match="twice"):
            vocabularies.load_declaration(_declaration(twice), suggesters={"lobid"})


class TestTheStoredIdentifier:
    @pytest.mark.parametrize(
        ("scheme", "raw", "stored"),
        [
            ("gnd", "https://d-nb.info/gnd/4038243-6", "(DE-588)4038243-6"),
            ("gnd", "http://d-nb.info/gnd/11867885X", "(DE-588)11867885X"),
            ("gnd", "(DE-588)4038243-6", "(DE-588)4038243-6"),
            (
                "lcsh",
                "https://id.loc.gov/authorities/subjects/sh85083064",
                "http://id.loc.gov/authorities/subjects/sh85083064",
            ),
            ("mesh", "https://id.nlm.nih.gov/mesh/D000001", "https://id.nlm.nih.gov/mesh/D000001"),
        ],
    )
    def test_a_publisher_spelling_maps_onto_the_form_an_import_stores(self, scheme, raw, stored):
        assert vocabularies.stored_identifier(scheme, raw) == stored


class TestTheClassificationRow:
    def test_a_gnd_entry_is_the_number_the_marc_reader_stores_from_its_dollar_zero(self):
        identifier = vocabularies.stored_identifier("gnd", "https://d-nb.info/gnd/4026894-9")
        imported = marc_fields.Subfields([("a", "Informatik"), ("0", identifier)]).gnd_identifier()

        assert vocabularies.classification_row("gnd", identifier, "Informatik") == (imported, "Informatik")

    def test_an_lcsh_entry_is_its_heading_string_with_no_label(self):
        identifier = "http://id.loc.gov/authorities/subjects/sh89003285"

        assert vocabularies.classification_row("lcsh", identifier, "Computer science") == (
            "Computer science",
            None,
        )

    def test_a_scheme_with_no_rule_keeps_the_identifier_as_the_number(self):
        identifier = "https://id.nlm.nih.gov/mesh/D000001"

        assert vocabularies.classification_row("mesh", identifier, "Calcimycin") == (identifier, "Calcimycin")


def _gnd() -> vocabularies.Scheme:
    return vocabularies.load_declaration(vocabularies.DECLARATION.read_text())[0]


def _recorded(path: Path, entries: int) -> Release:
    return Release(entries=entries, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


class TestADataFile:
    def test_an_invenio_entry_loads_with_its_four_keys_and_the_stored_id(self, tmp_path):
        path = tmp_path / "g.jsonl"
        path.write_text(
            '{"id": "https://d-nb.info/gnd/4038243-6", "scheme": "GND", "subject": "Medizin",'
            ' "synonyms": ["Heilkunst"], "props": {"broader": "x"}, "title": {"en": "Medicine"}}\n'
        )

        assert list(vocabularies.read_entries(path, _gnd(), _recorded(path, 1))) == [
            Entry("(DE-588)4038243-6", "gnd", "Medizin", ("Heilkunst",))
        ]

    def test_a_csv_synonyms_column_is_one_synonym(self, tmp_path):
        path = tmp_path / "g.csv"
        path.write_text('id,scheme,subject,synonyms\n(DE-588)1,gnd,A,"B, C"\n')

        assert next(vocabularies.read_entries(path, _gnd(), _recorded(path, 1))).synonyms == ("B, C",)

    def test_a_decomposed_label_is_composed_as_an_import_stores_it(self, tmp_path):
        path = tmp_path / "g.yaml"
        path.write_text('- {id: "(DE-588)1", scheme: gnd, subject: "Müll"}\n')

        assert next(vocabularies.read_entries(path, _gnd(), _recorded(path, 1))).subject == "Müll"

    def test_a_file_that_is_not_the_one_recorded_is_refused(self, tmp_path):
        path = tmp_path / "g.jsonl"
        path.write_text('{"id": "(DE-588)1", "scheme": "gnd", "subject": "A"}\n')
        recorded = _recorded(path, 1)
        path.write_text('{"id": "(DE-588)1", "scheme": "gnd", "subject": "B"}\n')

        with pytest.raises(EntriesRefused, match="not the file"):
            list(vocabularies.read_entries(path, _gnd(), recorded))

    def test_a_count_that_is_not_the_one_recorded_is_refused(self, tmp_path):
        path = tmp_path / "g.jsonl"
        path.write_text('{"id": "(DE-588)1", "scheme": "gnd", "subject": "A"}\n')

        with pytest.raises(EntriesRefused, match="were recorded"):
            list(vocabularies.read_entries(path, _gnd(), _recorded(path, 2)))

    def test_an_entry_of_another_scheme_is_refused(self, tmp_path):
        path = tmp_path / "g.jsonl"
        path.write_text('{"id": "sh1", "scheme": "lcsh", "subject": "A"}\n')

        with pytest.raises(EntriesRefused, match="names the scheme"):
            list(vocabularies.read_entries(path, _gnd(), _recorded(path, 1)))

    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("g.yaml", '- {id: "(DE-588)1", subject: A, synonyms: [&x [&y [a, a], *y], *x]}\n'),
            ("g.jsonl", '{"id": "(DE-588)1", "subject": "A", "synonyms": 5}\n'),
            ("g.jsonl", '{"id": "(DE-588)1", "subject": "A", "scheme": ["gnd"]}\n'),
        ],
        ids=["a list of aliased lists", "a number", "a scheme that is a list"],
    )
    def test_a_value_that_is_not_text_is_refused_rather_than_spelled_out(self, tmp_path, name, content):
        path = tmp_path / name
        path.write_text(content)

        with pytest.raises(EntriesRefused, match="not text"):
            list(vocabularies.read_entries(path, _gnd(), _recorded(path, 1)))

    @pytest.mark.parametrize(
        "content",
        [b'{"id": "(DE-588)1", "subject": "A"\n', b'{"id": "(DE-588)1", "subject": "\xff"}\n'],
        ids=["bad JSON", "bad UTF-8"],
    )
    def test_a_line_that_is_not_well_formed_is_refused(self, tmp_path, content):
        path = tmp_path / "g.jsonl"
        path.write_bytes(content)

        with pytest.raises(EntriesRefused, match="not well formed"):
            list(vocabularies.read_entries(path, _gnd(), _recorded(path, 1)))


def _declaring(text: str) -> Callable[[Path], object]:
    return lambda _tmp_path: vocabularies.load_declaration(text)


def _reading(line: str) -> Callable[[Path], object]:
    def read(tmp_path: Path) -> object:
        path = tmp_path / "g.jsonl"
        path.write_text(line)
        return list(vocabularies.read_entries(path, _gnd(), _recorded(path, 1)))

    return read


@pytest.mark.parametrize(
    ("act", "refusal", "match"),
    [
        (_declaring("[]"), DeclarationRefused, "no `subjects.schemes` list"),
        (_declaring("subjects: {schemes: []}"), DeclarationRefused, "no `subjects.schemes` list"),
        (_declaring("subjects: {schemes: [gnd]}"), DeclarationRefused, "not a mapping"),
        (_declaring("subjects: {schemes: [{name: GND}]}"), DeclarationRefused, "has no id"),
        (_reading('["(DE-588)1", "A"]\n'), EntriesRefused, "not a mapping"),
        (_reading('{"id": 1, "subject": "A"}\n'), EntriesRefused, "text id and subject"),
        (_reading('{"id": "(DE-588)1", "subject": ["A"]}\n'), EntriesRefused, "text id and subject"),
    ],
    ids=[
        "a declaration that is not a mapping",
        "an empty scheme list",
        "a scheme that is not a mapping",
        "a scheme with no id",
        "an entry that is not a mapping",
        "an id that is not text",
        "a subject that is not text",
    ],
)
def test_a_declaration_or_entry_of_the_wrong_shape_is_refused(tmp_path, act, refusal, match):
    with pytest.raises(refusal, match=match):
        act(tmp_path)
