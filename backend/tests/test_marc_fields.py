"""What `marc_fields.py` reads off a MARC21 record, and what it refuses.

Three callers read these fields and each has its own policy: `metadata._dnb_record`
refuses a volume slot and a disc, `metadata._k10plus_record` refuses neither, and
`marc._record` refuses only a record with no title. The tests here are about the
fields themselves, so a profile's refusal is tested where that profile lives.

`tests/test_marc.py::TestNoModuleReadsAnotherModulesPrivateNames` is the guard
that keeps this module a door rather than a pile of names: no module in the
backend reads another module's private names, with no exemption.
"""

from typing import Any
from xml.etree import ElementTree

import pytest

import marc
import marc_fields
from catalogue import AuthorityAssertion, Heading
from enums import AuthorityScheme, ClassificationScheme, HeadingKind
from marc_fields import Fields
from tests.test_house_rules import BACKEND, _python_sources


def _marc_element(datafields: str) -> ElementTree.Element:
    """One MARC record element, built from the datafields a test cares about.

    Spelled here as well as in `test_metadata.py`, which still builds records to
    test a source profile. Three lines in two files beats a shared helper two
    files import for two different reasons.
    """
    return ElementTree.fromstring(
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f"{datafields}</record>"
    )


class TestTheNamespaceIsDefinedOnce:
    """A reader and a writer disagreeing about it produce a file this app wrote
    and cannot read back, and only the round trip test would notice.

    **Defined once is the claim, so it is counted rather than inferred.** That
    `marc.py` takes this module's value and that `RECORD_TAG` derives from it
    are both consistent with a second literal sitting somewhere else, which is
    the thing that would drift; the two agreement tests below cannot see one.
    The test tree is excluded because it builds MARC fixtures by hand, which is
    a record to parse rather than a definition of the namespace.
    """

    def test_the_backend_spells_the_namespace_in_exactly_one_place(self):
        """A list of paths rather than a count, and never a line number: a
        second spelling has to be findable from the failure, and a line moves
        whenever anything above it is edited."""
        spellings = [
            str(path.relative_to(BACKEND))
            for path in _python_sources(BACKEND)
            for line in path.read_text(encoding="utf-8").splitlines()
            if marc_fields.NAMESPACE in line
        ]

        assert spellings == ["marc_fields.py"], spellings

    def test_the_writer_takes_the_readers_namespace(self):
        assert marc.NAMESPACE == marc_fields.NAMESPACE

    def test_the_qualified_record_tag_is_built_from_that_namespace(self):
        assert f"{{{marc_fields.NAMESPACE}}}record" == marc_fields.RECORD_TAG

    def test_a_record_written_by_this_app_is_found_by_that_tag(self):
        """The property the two constants exist for, run rather than asserted."""
        written = ElementTree.fromstring(
            f'<collection xmlns="{marc.NAMESPACE}"><record/></collection>'
        )

        assert list(written.iter(marc_fields.RECORD_TAG)) != []


class TestFieldsCarriesTheRecordItParsed:
    """The datafields and the node they came from are one value.

    Before this they were two, and `describes_a_book` took both plus a title:
    three positional arguments a caller could line up wrongly, and a lookup that
    carried `(node, fields, record)` triples to keep them together. A `Fields`
    built from one node cannot answer about another.
    """

    LEADER = "<leader>01533ngm a2200505 c 4500</leader>"
    EXTENT = (
        '<datafield tag="300" ind1=" " ind2=" ">'
        '<subfield code="a">300 Seiten</subfield></datafield>'
    )

    def test_the_carrier_codes_come_from_the_node_the_fields_were_built_from(self):
        """`ngm` at leader/06 is a projected medium, and the extent says paper.

        The extent alone passes, so a `Fields` answering False here is answering
        off its own node rather than off the fields it was handed.
        """
        record = ElementTree.fromstring(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            f"{self.LEADER}{self.EXTENT}</record>"
        )

        assert Fields(record).describes_a_book("Ein Film") is False

    def test_the_same_datafields_under_a_book_leader_are_a_book(self):
        """The other half of the diagonal: the extent is doing no work above."""
        record = ElementTree.fromstring(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            f'<leader>01533nam a2200505 c 4500</leader>{self.EXTENT}</record>'
        )

        assert Fields(record).describes_a_book("Ein Buch") is True


class TestTheTitleFieldIsPickedInOnePlace:
    """Three MARC profiles wanted the first `245` and an empty field where there
    is none. Spelled at each call site that is three chances to write the
    fallback differently, and one of the three is in another module.
    """

    def test_a_record_with_no_245_answers_an_empty_title(self):
        assert Fields(_marc_element("")).title_statement() == ("", None, None, None)

    def test_the_first_245_is_the_one_read(self):
        """MARC allows one `245` and real files carry two."""
        fields = Fields(_marc_element(
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">First</subfield></datafield>'
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">Second</subfield></datafield>'
        ))

        assert fields.title_statement()[0] == "First"


class TestAnAbsentTagReadsAsNoFields:
    """`get` answers `[]` rather than raising, because every reader here is a
    loop over what the record happens to carry and a record carrying nothing is
    ordinary.
    """

    def test_a_tag_the_record_does_not_carry_is_empty(self):
        assert Fields(_marc_element("")).get("650") == []

    def test_an_empty_record_answers_every_scalar_with_none(self):
        fields = Fields(_marc_element(""))

        assert (
            fields.isbn(),
            fields.publisher(),
            fields.year(),
            fields.description(),
            fields.language(),
            fields.extent(),
            fields.authors(),
            fields.credited_names(),
        ) == (None,) * 8

    def test_an_empty_record_answers_every_collection_with_nothing(self):
        fields = Fields(_marc_element(""))

        assert fields.ddc_headings() == []
        assert fields.author_identifiers() == []
        assert fields.controlled_subjects() == ([], [])


class TestMarcSubfields:
    """What a MARC record carries that a Dublin Core crosswalk had cleaned up."""

    def test_a_repeated_subfield_keeps_every_value(self):
        """082 holds `$a=830 $a=B`, and the letter is not a Dewey number."""
        fields = Fields(_marc_element('''
          <datafield tag="082" ind1="7" ind2="4">
           <subfield code="a">830</subfield><subfield code="a">B</subfield>
          </datafield>'''))
        assert fields.get("082")[0].all("a") == ["830", "B"]

    def test_indexing_a_repeated_subfield_gives_the_first_value(self):
        """`$0` arrives as the GND number, then two URIs for the same thing."""
        fields = Fields(_marc_element('''
          <datafield tag="100" ind1="1" ind2=" ">
           <subfield code="0">(DE-588)118181505</subfield>
           <subfield code="0">https://d-nb.info/gnd/118181505</subfield>
           <subfield code="a">Capus, Alex</subfield>
          </datafield>'''))
        assert fields.get("100")[0]["0"] == "(DE-588)118181505"

    def test_the_non_sorting_delimiters_are_stripped(self):
        """MARC brackets a leading article so it can be skipped when filing.

        They are invisible in a terminal, and 28 of 85 live records hold one.
        """
        fields = Fields(_marc_element(
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">\x98Die\x9c Deutschen</subfield></datafield>'
        ))
        assert fields.get("245")[0]["a"] == "Die Deutschen"

    def test_padding_inside_a_subfield_is_collapsed(self):
        """MARC pads subfields. `245 $a` on the live record 9783446249974 reads
        `Reisen im  Licht der Sterne`, where that record's own `776 $t` spells
        it with one space."""
        fields = Fields(_marc_element(
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">Reisen im  Licht der Sterne</subfield>'
            "</datafield>"
        ))
        assert fields.get("245")[0]["a"] == "Reisen im Licht der Sterne"

    def test_decomposed_text_is_normalised(self):
        """The DNB serves MARC21 decomposed and Dublin Core composed.

        Two spellings of one author is enough to store the same person twice.
        """
        fields = Fields(_marc_element(
            '<datafield tag="100" ind1="1" ind2=" ">'
            '<subfield code="a">Mu\u0308ller, Hans</subfield></datafield>'
        ))
        assert fields.get("100")[0]["a"] == "M\u00fcller, Hans"


class TestTheVocabularyDecidesWhatAHeadingAsserts:
    """`#162`: the DNB writes a content type and a carrier into the same subject
    fields as a subject, each with a `(DE-588)` number on it, so before this a
    disc was stored as an assertion about what the book is about.

    The measurement that made it a defect rather than a curiosity: `gnd-content`
    carries a `(DE-588)` on 34 of 34 fields at the DNB, 26 of 26 at the OeNB and
    27 of 27 at K10plus, and `Subfields.gnd_identifier` accepts every one of them.
    """

    def _headings(self, datafields):
        return Fields(_marc_element(datafields)).controlled_subjects()[1]

    def test_a_carrier_is_still_a_heading_and_says_it_is_a_carrier(self):
        """Still `scheme=gnd`, because `(DE-588)4139307-7` is a GND record and
        resolves as one whichever `$2` cites it. What changed is the kind."""
        assert self._headings(
            '<datafield tag="655" ind1=" " ind2="7">'
            '<subfield code="a">CD-ROM</subfield>'
            '<subfield code="0">(DE-588)4139307-7</subfield>'
            '<subfield code="2">gnd-carrier</subfield></datafield>'
        ) == [
            Heading(
                ClassificationScheme.GND, "4139307-7", "CD-ROM", HeadingKind.CARRIER
            )
        ]

    def test_a_content_type_is_kept_rather_than_refused(self):
        """The reason the fix is not a filter on the vocabulary code. Refusing
        `gnd-content` outright would drop this heading, which is a content type
        worth keeping and is why `655` is on `marc_fields._DNB_SUBJECT_TAGS` at all."""
        assert self._headings(
            '<datafield tag="655" ind1=" " ind2="7">'
            '<subfield code="a">Fiktionale Darstellung</subfield>'
            '<subfield code="0">(DE-588)1071854844</subfield>'
            '<subfield code="2">gnd-content</subfield></datafield>'
        ) == [
            Heading(
                ClassificationScheme.GND,
                "1071854844",
                "Fiktionale Darstellung",
                HeadingKind.CONTENT,
            )
        ]

    def test_a_plain_gnd_subject_is_left_undeclared(self):
        """`subject` is never written to the column: it is what
        `classifications.kind_of` answers for a null. Storing it would put the
        fallback's own answer in the row, and a stored value cannot be filled in
        later by the record that names the heading properly."""
        assert self._headings(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="a">Informatik</subfield>'
            '<subfield code="0">(DE-588)4026894-9</subfield>'
            '<subfield code="2">gnd</subfield></datafield>'
        ) == [Heading(ClassificationScheme.GND, "4026894-9", "Informatik", None)]

    @pytest.mark.parametrize("code", ["nlgaf", "gatbeg", "bisacsh", "local", "sswd"])
    def test_a_vocabulary_this_app_has_no_reading_for_declares_no_kind(self, code):
        """Twelve distinct `$2` codes turned up in one day's sampling of four
        catalogues, against a MARC source code list holding hundreds. Reading
        any of the rest as a kind is the crosswalk #134 refuses."""
        assert marc_fields._subject_kind(code) is None

    def test_the_reader_is_asked_the_folded_code_and_not_the_field(self):
        """`$2` is the Dewey **edition** on `082`, which is why
        `Subfields.subject_vocabulary` takes a tag and raises. This takes the code that
        reader already folded, so the case rule is not spelled twice."""
        assert marc_fields._subject_kind("GND-CARRIER".lower()) is HeadingKind.CARRIER
        assert marc_fields._subject_kind(None) is None


class TestASubfieldReaderIsNotTwoReaders:
    """The two `$0` questions, which look like one rule and are not."""

    def test_the_vocabulary_reader_answers_none_where_there_is_no_dollar_two(self):
        entry = Fields(_marc_element(
            '<datafield tag="650"><subfield code="a">X</subfield></datafield>'
        )).get("650")[0]

        assert entry.subject_vocabulary("650") is None

    def test_the_identifier_reader_answers_none_where_there_is_no_dollar_zero(self):
        entry = Fields(_marc_element(
            '<datafield tag="650"><subfield code="a">X</subfield></datafield>'
        )).get("650")[0]

        assert entry.subject_identifier() is None

    def test_the_gnd_reader_still_searches_past_a_leading_house_number(self):
        """`gnd_identifier` asks whether the field names a GND record, so it
        looks at every `$0`. `subject_identifier` asks what the record led
        with, so it looks at one. A field written in the other order separates
        them, and no live catalogue writes that order: this pins the difference
        rather than the data."""
        entry = Fields(_marc_element(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="0">(DE-101)1010836315</subfield>'
            '<subfield code="0">(DE-588)4026894-9</subfield>'
            '<subfield code="a">Informatik</subfield></datafield>'
        )).get("650")[0]

        assert entry.gnd_identifier() == "4026894-9"
        assert entry.subject_identifier() == "(DE-101)1010836315"


class TestTheAuthorsAuthorityIdentifier:
    """`100 $0` and `700 $0`, which say which GND record wrote this book.

    The subject fields carry the identical subfield and go somewhere else: 600
    says a person is what the book is *about*. That split is
    `enums.AuthorityScheme`.
    """

    @staticmethod
    def _fields(*datafields: str):
        return Fields(_marc_element("".join(datafields)))

    MAIN = (
        '<datafield tag="100" ind1="1" ind2=" ">'
        '<subfield code="0">(DE-588)1042243212</subfield>'
        '<subfield code="a">Kane, Sean P.</subfield>'
        '<subfield code="4">aut</subfield></datafield>'
    )

    def test_the_main_entry_identifier_is_stored_bare(self):
        """Without `(DE-588)`: the scheme is a column, and keeping the prefix
        would let one identifier arrive under two spellings the unique index
        cannot collapse. The same rule `gnd_identifier` states for a heading."""
        assert self._fields(self.MAIN).author_identifiers() == [
            AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212")
        ]

    def test_a_record_with_no_identifier_produces_none(self):
        """21 of 73 live 100 fields carry no `(DE-588)` at all, measured over 85
        records on 2026-08-24. Ordinary, not broken."""
        fields = self._fields(
            '<datafield tag="100" ind1="1" ind2=" ">'
            '<subfield code="a">Kane, Sean P.</subfield></datafield>'
        )

        assert fields.author_identifiers() == []

    def test_a_700_that_wrote_the_book_is_read(self):
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)1042243213</subfield>'
            '<subfield code="a">Matthias, Karl</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
        )

        assert fields.author_identifiers() == [
            AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212"),
            AuthorityAssertion("Karl Matthias", AuthorityScheme.GND, "1042243213"),
        ]

    def test_a_700_that_only_translated_it_is_not(self):
        """`$4=trl` is a translator. Reading it would file a translator's GND
        under a name that is not in this Book's credit line at all."""
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)9999</subfield>'
            '<subfield code="a">Meier, Eva</subfield>'
            '<subfield code="4">trl</subfield></datafield>',
        )

        assert [row.identifier for row in fields.author_identifiers()] == [
            "1042243212"
        ]

    def test_an_added_entry_for_a_work_is_not_a_person_here(self):
        """`$t` links the original title, and the name beside it is that work's
        author rather than a second author of this book."""
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)9999</subfield>'
            '<subfield code="a">Melville, Herman</subfield>'
            '<subfield code="t">Moby Dick</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
        )

        assert [row.identifier for row in fields.author_identifiers()] == [
            "1042243212"
        ]

    def test_every_identifier_is_filed_under_a_name_in_the_credit_line(self):
        """The property `Fields._author_entries` exists to make structural.

        Two loops testing the same three conditions would let the credit line
        and the identifiers drift apart, and the symptom would be a row filed
        under a spelling no Book carries: invisible, undeletable through the UI,
        and never matched by anything.
        """
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)1042243213</subfield>'
            '<subfield code="a">Matthias, Karl</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)9999</subfield>'
            '<subfield code="a">Meier, Eva</subfield>'
            '<subfield code="4">trl</subfield></datafield>',
        )

        credited = fields.authors() or ""
        for row in fields.author_identifiers():
            assert row.name in credited

    def test_one_person_named_by_both_100_and_700_is_asserted_once(self):
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)1042243212</subfield>'
            '<subfield code="a">Kane, Sean P.</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
        )

        assert len(fields.author_identifiers()) == 1


class TestWhichAddedEntryWroteTheBook:
    """What `700 $4` has to say before a name joins the credit line.

    The rule is `marc_fields._AUTHOR_RELATORS` and the measurement behind it is
    there too. These pin the three answers it gives, because the interesting one
    is a refusal: a `700` that states no role is refused even where the credit
    line would otherwise be one name long, and a reader looking at that record
    alone sees a co-author being dropped.
    """

    @staticmethod
    def _fields(*datafields: str):
        return Fields(_marc_element("".join(datafields)))

    MAIN = (
        '<datafield tag="100" ind1="1" ind2=" ">'
        '<subfield code="a">Ferrante, Elena</subfield></datafield>'
    )

    @staticmethod
    def _added(name: str, *relators: str) -> str:
        roles = "".join(f'<subfield code="4">{value}</subfield>' for value in relators)
        return (
            '<datafield tag="700" ind1="1" ind2=" ">'
            f'<subfield code="a">{name}</subfield>{roles}</datafield>'
        )

    def test_a_700_stating_no_role_stays_out_of_the_credit_line(self):
        """The record names the illustrator and the translator in the same
        field as a co-author, and nothing in it says which is which."""
        fields = self._fields(
            self.MAIN,
            self._added("Goldstein, Ann"),
            self._added("Rossi, Marco"),
        )

        assert fields.authors() == "Elena Ferrante"

    def test_a_record_crediting_nobody_still_names_everybody_it_names(self):
        """The other half of the same rule: refusing the bare `700` costs a name
        only where some other field supplied one."""
        fields = self._fields(self._added("Goldstein, Ann"), self._added("Rossi, Marco"))

        assert fields.authors() is None
        assert fields.credited_names() == "Ann Goldstein, Marco Rossi"

    def test_a_second_relator_naming_an_author_is_read(self):
        """`$4=edt $4=aut` is an editor who wrote a chapter too. Reading the
        first `$4` alone dropped them."""
        fields = self._fields(self.MAIN, self._added("Sokolicek, Alexander", "edt", "aut"))

        assert fields.authors() == "Elena Ferrante, Alexander Sokolicek"

    def test_a_relator_written_as_a_uri_says_the_same_thing(self):
        fields = self._fields(
            self.MAIN,
            self._added("Goldstein, Ann", "http://id.loc.gov/vocabulary/relators/aut"),
        )

        assert fields.authors() == "Elena Ferrante, Ann Goldstein"

    def test_a_uri_naming_a_translator_is_still_refused(self):
        """The arm that says the URI is read for what it means rather than
        refused for how it is spelled."""
        fields = self._fields(
            self.MAIN,
            self._added("Goldstein, Ann", "http://id.loc.gov/vocabulary/relators/trl"),
        )

        assert fields.authors() == "Elena Ferrante"


class TestTheComponentPartRefusal:
    """The leader test, alone, so its edges are visible.

    Measured over the same 280 live records: the leader catches 155 of 155
    component parts and loses 0 of 122 monographs, where refusing anything
    carrying a 773 catches the same 155 and loses 3 monographs.
    """

    @pytest.mark.parametrize(
        "leader, expected",
        [
            ("00733naa a2200229zc 4500", True),
            ("00733nab a2200229zc 4500", True),
            ("01533nam a2200505 c 4500", False),
            ("01533nac a2200505 c 4500", False),
            # A truncated leader is a broken record rather than an article, and
            # the fields decide it on their own merits.
            ("00733n", False),
            ("", False),
        ],
    )
    def test_the_bibliographic_level_decides(self, leader, expected):
        record = ElementTree.fromstring(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            f"<leader>{leader}</leader></record>"
        )
        assert marc_fields.is_component_part(record) is expected


def _carrier_record(leader: str = "01533nam a2200505 c 4500", **fields: str) -> Any:
    """One MARC record node from a leader and any control fields it needs.

    Named for what it carries rather than for the schema. In `test_metadata.py`,
    where this used to live, a `_marc_record` two hundred lines above built a
    whole record body and a second function of that name shadowed it, breaking a
    size cap fixture. The suite caught it; nothing else would have.
    """
    controls = "".join(
        f'<controlfield tag="{tag[:3]}">{value}</controlfield>'
        for tag, value in fields.items()
    )
    return ElementTree.fromstring(
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f"<leader>{leader}</leader>{controls}</record>"
    )


class TestTheCarrierDecides:
    """The MARC codes, alone, so their edges are visible.

    **A diagonal, verified by deleting each code rather than by claiming it.**
    Every one of the ten codes in the three frozensets is pinned: drop any one
    and a row goes red. That is the whole point of the block and the first
    version of it did not have the property, while saying it did. A critic
    measured it: **7 of the 10 survived deletion with all 14 rows green**, since
    the two disc rows each carried two refusing features at once, `sd` on a `njm`
    leader and `vd` on a `ngm` leader, so each covered for the other and neither
    name was load bearing.

    **So the rows are of three kinds, and 9 plus 7 plus 5 is 21.** Both critics
    found the previous sentence separately: it said two kinds and accounted for
    16 of the rows, which is the shape CLAUDE.md predicts for a fix round, a
    corrected partition that does not sum. It replaced a claim that every row was
    live, which was false but at least total, so the correction was weaker in the
    dimension nobody re-checked.

    **9 live**, shapes seen in a catalogue during the September 2026 roster
    measurement. **7 constructed**, one per code that no live record refuses on
    its own, and they have to exist: over 2,605 records only two of the ten codes
    ever refuse a record by themselves, `007 c` on exactly one and leader/06 `m`
    on exactly one, so a table drawn only from live shapes cannot pin this rule.
    **5 edge**, none of them a live shape, which was checked rather than assumed:
    of those 2,605, none carries a leader under 8 characters, an 008 under 24, an
    empty `007`, or no control field at all.

    The 5 are not decoration, and they do **three** jobs rather than one. Strip
    the two length tests and **3 of them raise `IndexError`** where the other 18
    rows do not: the truncated leader, the empty leader and the 11 character 008.
    Change `value[:1]` to `value[0]` and leave both length tests alone and the
    empty `007` row is the **only** one of the 21 that goes red, so it is the
    sole pin for reading the carrier by prefix. The fifth, a record declaring
    nothing at all, pins that silence decides nothing. No row is idle, which is a
    better argument against trimming the table than a count of edges.

    **This paragraph has now been wrong twice, and the second time it said 4.**
    That 4 was a true measurement of the wrong thing: the script behind it
    stripped the length tests **and** changed the slice in one pass, so it
    counted a mutation nobody was describing. CLAUDE.md's line for it is that a
    measurement is only evidence about the configuration it was taken under, and
    the tell was available in the file: the row comment below already says an
    empty `007` matches nothing rather than raising, so the sentence contradicted
    a comment eleven lines away.

    Its remaining blind spot: it pins codes, not the vocabulary. A carrier code
    no catalogue here has written yet is invisible to it, and `008/23 s` is
    pinned only by a constructed row because it has never been observed, sitting
    in the constant on MARC's definition as `b` does in
    `marc_fields._COMPONENT_PART_LEVELS`.
    """

    @pytest.mark.parametrize(
        "leader, controls, expected",
        [
            # An online resource: one electronic carrier and nothing else.
            ("01533nam a2200505 c 4500", {"007": "cr#|||||||||||"}, False),
            # An audiobook and a videodisc, by their carrier.
            ("01533njm a2200505 c 4500", {"007": "sd f||||||||||"}, False),
            ("01533ngm a2200505 c 4500", {"007": "vd |||||||||||"}, False),
            # A computer file, the NLG's `E-BOOK`, which carries no 007 at all.
            ("01533nmm a2200505 c 4500", {}, False),
            # ── Constructed, one per code no live record refuses alone ───────
            # The two live disc rows above carry a refusing carrier **and** a
            # refusing leader, so without these seven, seven of the ten codes
            # could be deleted with this table still green.
            ("01533nam a2200505 c 4500", {"007": "sd f||||||||||"}, False),
            ("01533nam a2200505 c 4500", {"007": "vd |||||||||||"}, False),
            ("01533ngm a2200505 c 4500", {}, False),
            ("01533nim a2200505 c 4500", {}, False),
            ("01533njm a2200505 c 4500", {}, False),
            (
                "01533nam a2200505 c 4500",
                {"008": "210224s2020    gw |||||q|||| 00||||ger  "},
                False,
            ),
            (
                "01533nam a2200505 c 4500",
                {"008": "210224s2020    gw |||||s|||| 00||||ger  "},
                False,
            ),
            # Form of item, where the carrier is absent. 195 of the 2,605
            # records measured carry no 007, so this is not a hypothetical.
            ("01533nam a2200505 c 4500", {"008": "210224s2020    gw |||||o|||| 00||||ger  "}, False),
            # A plain printed book: the text carrier, and a blank form of item.
            (
                "01533nam a2200505 c 4500",
                {"007": "tu", "008": "210224s2020    gw ||||| |||| 00||||ger  "},
                True,
            ),
            # **A text carrier beside an electronic one is a text.** 48 of those
            # 2,605 are Austrian Books Online records for real 19th century
            # prints, with the print's collation in the 300 and the scan in an
            # 856. Refusing on any electronic 007 refuses all 48.
            ("00796nam a2200265 cc4500", {"007": "cr#|||||||||||", "007a": "tu"}, True),
            # Nothing declared at all decides nothing, which is the common case:
            # a thin record is not a disc.
            ("01533nam a2200505 c 4500", {}, True),
            # A leader too short to index, and an 008 too short to reach 23.
            ("00733n", {}, True),
            ("", {}, True),
            ("01533nam a2200505 c 4500", {"008": "210224s2020"}, True),
            # An empty 007 is read by prefix and matches nothing rather than
            # raising, which is why the carrier is not read positionally.
            ("01533nam a2200505 c 4500", {"007": ""}, True),
            # The ÖNB writes `#` where the DNB writes a space, and `|` means no
            # attempt to code. 560 ÖNB **records** carry `#` here and the shipped
            # rule keeps **556** of them, so a rule testing "not blank" would
            # refuse 556 books outright.
            ("01533nam a2200505 c 4500", {"008": "000101|1568    |||           ||| | lat c"}, True),
            ("01533nam a2200505 c 4500", {"008": "210224s2020    gw ||||||||||| 00||||ger  "}, True),
        ],
    )
    def test_the_record_states_its_own_carrier(self, leader, controls, expected):
        assert marc_fields._marc_carrier_is_book(_carrier_record(leader, **controls)) is expected

    def test_a_control_field_is_read_raw_and_never_through_marc_text(self):
        """The blanks in an 008 are data, and collapsing them moves position 23.

        Measured over 2,605 live records, and counted in **records**: `_marc_text`
        alters the 008 of 2,043 of them and changes what sits at position 23 on
        1,859. 847 records carry `o` there and 817 of those lose it, this 008
        being one, so routing the control field through the shared subfield
        reader turns this refusal into a pass with nothing failing anywhere.

        **608 is what this paragraph said, and it is the count of distinct 008
        values among those 817 records rather than a count of records.** A
        critic caught it. The instrument had answered a narrower question than
        the prose asked, which is the failure CLAUDE.md names, and it sat here
        beside a comment that had the same slip twice over.
        """
        raw = "210224s2020    gw |||||o|||| 00||||ger  "
        assert raw[23] == "o"
        assert marc_fields._marc_text(raw)[23] != "o"
        assert marc_fields._marc_carrier_is_book(_carrier_record(**{"008": raw})) is False
