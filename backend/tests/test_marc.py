"""Tests for backend/marc.py: MARC21 records in and out.

**The seam is bytes.** The reader takes what an upload holds and the writer
produces what a download carries, so every test here works in those terms and
none of them needs a session. What does need one, the matching and the writing,
is `tests/test_importing.py` and `tests/routers/test_imports_marc.py`.

**The round trip is the strongest assertion available and it is not a
tautology.** The writer is this module's and the reader is `metadata.py`'s, the
same one that parses a live DNB or K10plus answer. So a record surviving the
trip is evidence that what this app exports is a record this app's catalogue
parser accepts, rather than one that merely validates against a schema. The
fields that cannot survive it are asserted too, with the reason, because an
undocumented loss is how an export comes to be trusted for something it does
not do.
"""

import ast
import pathlib
import types

import pytest

import marc
import metadata
from catalogue import Heading
from enums import ClassificationScheme
from schemas.book import BookCreate

#: The application's own directory.
#:
#: **Anchored on this test file, never on `marc.__file__`**, and that distinction
#: cost a red pipeline. `pyproject.toml` declares a `[project]`, so `uv sync`
#: builds the backend and installs it into the virtualenv; in CI `import marc`
#: then resolves to the **copy inside `site-packages`**, and this constant became
#: the venv's `site-packages` directory. The scan below walked it, found
#: `pydantic`, `click`, `pyparsing` and `sqlalchemy` reading each other's private
#: names, and reported them as violations of a rule about this application.
#: Locally the same line resolves to the source tree, so the suite was green and
#: only the pipeline could see it.
#:
#: A test file is never installed, so it is the one anchor that means the same
#: thing in both places. `test_the_anchor_is_the_source_tree` fails loudly if
#: this ever stops being true, because every assertion in this class is about
#: whatever tree it points at.
BACKEND = pathlib.Path(__file__).resolve().parent.parent

MARCXML = "http://www.loc.gov/MARC21/slim"


def a_book(**overrides):
    """A stand-in for a Book, carrying only what the writer reads.

    A plain object rather than a `Book`, and that is the seam being honest: the
    writer touches no session, no relationship loader and no column type, so a
    test that built a real row would be testing SQLAlchemy. `test_importing.py`
    drives real Books through the applier, which is where a real Book matters.
    """
    fields = {
        "id": 1,
        "isbn": None,
        "title": "A Title",
        "subtitle": None,
        "author": None,
        "publisher": None,
        "year": None,
        "description": None,
        "language": None,
        "page_count": None,
        "series_name": None,
        "series_index": None,
        "classifications": [],
    } | overrides
    return types.SimpleNamespace(**fields)


def a_heading(scheme, number, label=None):
    return types.SimpleNamespace(scheme=scheme, number=number, label=label)


def round_trip(**overrides):
    """One Book written and read back, as the record the reader saw."""
    parsed = marc.read(marc.write([a_book(**overrides)]).encode("utf-8"))
    assert parsed.skipped == 0
    return parsed.records[0]


def a_record(*fields: str, leader: str = marc.LEADER) -> bytes:
    """A MARCXML collection holding one record built from raw field XML."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<collection xmlns="{MARCXML}"><record>'
        f"<leader>{leader}</leader>{''.join(fields)}"
        f"</record></collection>"
    ).encode()


def datafield(tag: str, *subfields: tuple[str, str], ind1: str = " ", ind2: str = " ") -> str:
    inner = "".join(f'<subfield code="{code}">{value}</subfield>' for code, value in subfields)
    return f'<datafield tag="{tag}" ind1="{ind1}" ind2="{ind2}">{inner}</datafield>'


class TestEveryFieldMapsBothWays:
    """One test per field the ticket names, each asserting the value survives.

    Written one at a time rather than as a single fat record, because a fat
    record that comes back wrong says only "something is wrong": these say
    which subfield.
    """

    def test_the_isbn_survives(self):
        assert round_trip(isbn="9783446249974").isbn == "9783446249974"

    def test_the_title_survives(self):
        assert round_trip(title="Stoner").title == "Stoner"

    def test_the_subtitle_survives(self):
        record = round_trip(title="Stoner", subtitle="A novel")
        assert (record.title, record.subtitle) == ("Stoner", "A novel")

    def test_one_author_survives(self):
        assert round_trip(author="John Williams").author == "John Williams"

    def test_several_authors_survive_in_order(self):
        assert round_trip(author="Terry Pratchett, Neil Gaiman").author == (
            "Terry Pratchett, Neil Gaiman"
        )

    def test_the_publisher_survives(self):
        assert round_trip(publisher="Hanser").publisher == "Hanser"

    def test_the_year_survives(self):
        assert round_trip(year=2005).year == 2005

    def test_the_page_count_survives(self):
        assert round_trip(page_count=352).page_count == 352

    def test_the_description_survives(self):
        assert round_trip(description="A summary.").description == "A summary."

    def test_the_language_survives(self):
        assert round_trip(language="de").language == "de"

    def test_a_series_survives_as_the_part_and_its_collective_title(self):
        record = round_trip(
            title="The Philosopher's Stone", series_name="Harry Potter", series_index=1.0
        )
        assert (record.title, record.series_name, record.series_index) == (
            "The Philosopher's Stone",
            "Harry Potter",
            1.0,
        )

    def test_a_dewey_number_survives(self):
        record = round_trip(classifications=[a_heading(ClassificationScheme.DDC, "830")])
        assert record.headings == (
            Heading(ClassificationScheme.DDC, "830", None),
        )

    def test_a_library_of_congress_call_number_survives(self):
        record = round_trip(
            classifications=[a_heading(ClassificationScheme.LCC, "PT2663.A67 S8 2005")]
        )
        assert record.headings == (
            Heading(ClassificationScheme.LCC, "PT2663.A67 S8 2005", None),
        )

    def test_a_gnd_heading_survives_with_its_caption(self):
        record = round_trip(
            classifications=[a_heading(ClassificationScheme.GND, "4203576-4", "Schatz")]
        )
        assert record.headings == (
            Heading(ClassificationScheme.GND, "4203576-4", "Schatz"),
        )

    def test_a_subject_heading_survives(self):
        record = round_trip(
            classifications=[a_heading(ClassificationScheme.LCSH, "Treasure troves")]
        )
        assert record.headings == (
            Heading(ClassificationScheme.LCSH, "Treasure troves", None),
        )

    def test_a_whole_record_survives_every_field_at_once(self):
        """The fat record too, because a field that only works alone is not a
        field that works: a writer emitting two `245` fields, or a reader taking
        the second `264`, passes every test above."""
        record = round_trip(
            isbn="9783446249974",
            title="Reisen im Licht der Sterne",
            subtitle="Eine Reise",
            author="Alex Capus",
            publisher="Hanser",
            year=2005,
            description="A summary.",
            language="de",
            page_count=352,
            classifications=[
                a_heading(ClassificationScheme.DDC, "830"),
                a_heading(ClassificationScheme.GND, "4203576-4", "Schatz"),
            ],
        )
        assert (
            record.isbn,
            record.title,
            record.subtitle,
            record.author,
            record.publisher,
            record.year,
            record.description,
            record.language,
            record.page_count,
        ) == (
            "9783446249974",
            "Reisen im Licht der Sterne",
            "Eine Reise",
            "Alex Capus",
            "Hanser",
            2005,
            "A summary.",
            "de",
            352,
        )
        assert len(record.headings) == 2


class TestWhatTheRoundTripCannotCarry:
    """The losses, asserted rather than left to be discovered.

    Each of these is a property of the format or of a stored column, not a
    defect this writer can fix, and each one is written down so that somebody
    trusting the export for it finds this file instead of finding out later.
    """

    def test_a_fractional_series_index_comes_back_whole(self):
        """`245 $n` is free text and carries `Bd. 3` and `[1]` in real records,
        so the reader takes the first digit run."""
        assert round_trip(title="A", series_name="S", series_index=2.5).series_index == 2.0

    def test_a_gnd_heading_with_no_caption_is_not_written_at_all(self):
        """`650` without `$a` is a heading with no heading. Putting the
        identifier in `$a` instead would print a number where a catalogue
        prints a phrase."""
        assert round_trip(
            classifications=[a_heading(ClassificationScheme.GND, "4203576-4")]
        ).headings == ()

    def test_a_name_typed_in_catalogue_order_becomes_two_people_in_the_record(self):
        """The cost of `author` being one free text column, and it is a cost to
        the receiving library rather than to this one.

        `Williams, John` is one person typed in catalogue order or two people
        called Williams and John, and nothing in the column says which. The
        writer splits it, so the exported record credits two authors. **The
        round trip cannot see this**, because splitting and rejoining is
        symmetric: the value comes back byte for byte. Only the shape of the
        record shows it, which is why this is asserted against the XML.
        """
        written = marc.write([a_book(author="Williams, John")])
        assert written.count('tag="100"') == 1
        assert written.count('tag="700"') == 1
        assert round_trip(author="Williams, John").author == "Williams, John"

    def test_a_title_carrying_isbd_punctuation_gains_a_subtitle_it_never_had(self):
        """**The one entry here that is a rewrite rather than a loss**, and the
        worst of them.

        `metadata._marc_title` falls back to `_dc_title_statement` whenever
        `245` carries no `$b`, because a record that did not subfield itself
        puts the whole statement in `$a`. A record this app wrote always did
        subfield itself, and there is no way to say so: an empty `$b` is
        stripped to nothing on the way back in.

        The trigger is the ISBD spelling with spaces on both sides, which is
        exactly how a cataloguer writes it. `Dune: Book One` survives.
        """
        record = round_trip(title="Stoner : a novel")
        assert (record.title, record.subtitle) == ("Stoner", "a novel")
        assert round_trip(title="Dune: Book One").title == "Dune: Book One"

    def test_a_title_ending_in_isbd_punctuation_loses_it(self):
        """`metadata._strip_marc_punctuation` drops a trailing `/:;,=` because a
        catalogue ends a subfield with the separator for the next one."""
        assert round_trip(title="Trilogy;").title == "Trilogy"
        assert round_trip(title="Why:").title == "Why"

    def test_a_title_with_a_spaced_elided_article_is_closed_up(self):
        """`metadata._fix_non_filing_space`. MARC puts a space after an elided
        article so sorting can skip it, and it is a filing device rather than
        how the title is printed. A repair rather than a loss, and here because
        the value does change."""
        assert round_trip(title="L' etranger").title == "L'etranger"

    def test_a_series_index_with_no_series_name_is_dropped(self):
        """`245 $n` is the part designation of a collective title, so there is
        nowhere to write a volume number for a book that names no series.
        `schemas/book.py` permits the combination, which is why this is
        reachable rather than hypothetical."""
        assert round_trip(title="A", series_index=3.0).series_index is None

    def test_a_carriage_return_comes_back_as_a_newline(self):
        """XML 1.0 normalises `\r` to `\n` on parse and `ElementTree` does not
        write it as `&#13;`, so the character cannot survive. It is legal to
        carry and impossible to round trip, which is the format's rule rather
        than this writer's."""
        assert round_trip(description="One.\rTwo.").description == "One. Two."

    def test_a_description_written_over_several_lines_comes_back_on_one(self):
        """`metadata._marc_text` collapses whitespace, because MARC pads its
        subfields. The words survive and the layout does not."""
        assert round_trip(description="One.\n\nTwo.").description == "One. Two."


class TestTheWriter:
    def test_the_leader_is_twenty_four_characters(self):
        """A leader of any other length is not a leader, and the positions
        after 04 all shift."""
        assert len(marc.LEADER) == 24

    def test_the_leader_says_the_record_is_abbreviated_rather_than_full(self):
        """Position 17. A record this app writes has no `008` and no notes, and
        coding it full level would tell the receiving cataloguer they need not
        check it."""
        assert marc.LEADER[17] == "3"

    def test_a_book_with_no_publisher_writes_no_publication_field(self):
        """An empty `264` is a publisher whose name is the empty string, to a
        system that stores what it is given."""
        assert 'tag="264"' not in marc.write([a_book()])

    def test_control_characters_are_dropped_so_the_file_stays_parseable(self):
        """One `\\x0c` in a member typed description would otherwise produce a
        download that no XML parser will read, this app's own included, and
        nothing upstream refuses them."""
        written = marc.write([a_book(description="Before\x0cafter")])
        assert "\x0c" not in written
        assert marc.read(written.encode("utf-8")).records[0].description == "Beforeafter"

    def test_the_namespace_is_the_one_the_reader_looks_for(self):
        """A reader and a writer disagreeing here produce a file this app
        cannot read back, and only a round trip would notice."""
        assert metadata._MARC.strip("{}") == marc.NAMESPACE

    def test_german_is_written_as_the_bibliographic_code_marc_uses(self):
        """ISO 639-2 has `ger` and `deu` for German and MARC takes the
        bibliographic one. Both read back as `de`, so the round trip cannot see
        this and a receiving system can."""
        assert '<subfield code="a">ger</subfield>' in marc.write([a_book(language="de")])

    def test_every_language_the_reader_knows_can_be_written(self):
        """Otherwise a book stored in a language the lookup path understands
        exports with no `041` at all, silently."""
        missing = sorted(
            set(metadata._LANGUAGES.values()) - set(marc._BIBLIOGRAPHIC_CODES)
        )
        assert missing == []

    def test_every_code_written_reads_back_as_the_code_it_came_from(self):
        """The inversion is not one to one, so this is the property that
        matters rather than the table's size."""
        for stored, written in marc._BIBLIOGRAPHIC_CODES.items():
            assert metadata._LANGUAGES[written] == stored

    def test_an_added_author_is_marked_as_one_or_the_reader_drops_it(self):
        """`700` without `$4` is a translator or an editor as far as
        `metadata._marc_author_entries` is concerned, so every author after the
        first would vanish with nothing failing."""
        assert '<subfield code="4">aut</subfield>' in marc.write(
            [a_book(author="One Writer, Two Writer")]
        )


class TestTheReaderRefusesAWholeFile:
    """`MarcError` is the file being the wrong thing, which is not the same
    answer as a record this reader skipped."""

    def test_a_doctype_is_refused_because_it_unbounds_the_cost(self):
        """`xml.etree` expands internal entities, so the upload cap stops
        bounding the work. `metadata._parsed` has the measurement."""
        bomb = (
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            b'<collection xmlns="http://www.loc.gov/MARC21/slim"><record>'
            b"<leader>&b;</leader></record></collection>"
        )
        with pytest.raises(marc.MarcError, match="document type"):
            marc.read(bomb)

    def test_a_utf16_file_is_refused_rather_than_scanned_blind(self):
        """The doctype check is a byte scan, so it is exact for the ASCII
        compatible encodings and blind to the rest. Refusing the rest is what
        makes the scan a guarantee."""
        with pytest.raises(marc.MarcError, match="UTF-8"):
            marc.read(a_record().decode("utf-8").encode("utf-16"))

    def test_a_utf16_doctype_cannot_slip_past_the_byte_scan(self):
        """The evasion the refusal above exists for, spelled out.

        **This test was written twice, and the first version pinned nothing.**
        It used an empty `<collection/>` and a bare `pytest.raises(MarcError)`,
        so with the NUL check deleted the file parsed, found no record, and
        raised `"That file holds no MARC records."`: green either way. Both
        critic seats found that independently, and `docs/security.md` was citing
        it as the evidence.

        Two things fix it and neither is enough alone. The fixture **references**
        the entity from a real `245 $a`, so a parse that gets this far expands
        it; and `match=` names the refusal, so falling through to any other
        `MarcError` fails. Measured on a mutant with the NUL check removed: 10
        source characters became a 1,000,000 character title.
        """
        bomb = (
            '<?xml version="1.0"?>'
            "<!DOCTYPE lolz ["
            '<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
            '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">'
            '<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">'
            '<!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;">'
            "]>"
            f'<collection xmlns="{MARCXML}"><record>'
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">&f;</subfield>'
            "</datafield></record></collection>"
        ).encode("utf-16")
        # The byte scan cannot see it, which is the whole point of the encoding
        # refusal that runs first.
        assert b"<!DOCTYPE" not in bomb
        with pytest.raises(marc.MarcError, match="UTF-8"):
            marc.read(bomb)

    def test_a_declared_multi_byte_encoding_is_refused_rather_than_a_500(self):
        """`ElementTree.fromstring` raises `ValueError`, not `ParseError`, for
        an XML declaration naming a multi-byte codec, and a `ValueError` walks
        past a handler that catches only the other one. Measured through the
        route before this arm existed: a 92 byte body was a 500 with a
        traceback."""
        body = (
            '<?xml version="1.0" encoding="EUC-JP"?>'
            f'<collection xmlns="{MARCXML}"><record/></collection>'
        ).encode("ascii")
        with pytest.raises(marc.MarcError, match="multi-byte"):
            marc.read(body)

    def test_something_that_is_not_xml_is_refused_with_a_reason(self):
        with pytest.raises(marc.MarcError, match="not XML"):
            marc.read(b"Title,Author\nStoner,John Williams\n")

    def test_a_file_with_no_records_is_refused(self):
        with pytest.raises(marc.MarcError, match="no MARC records"):
            marc.read(b'<collection xmlns="http://www.loc.gov/MARC21/slim"/>')

    def test_records_without_the_namespace_are_named_rather_than_reported_empty(self):
        """Several tools write MARCXML without declaring the namespace, and the
        difference is invisible in a text editor."""
        with pytest.raises(marc.MarcError, match="namespace"):
            marc.read(b"<collection><record><leader>x</leader></record></collection>")

    def test_more_records_than_the_cap_aborts_rather_than_truncating(self):
        """**The opposite of `csv_import.MAX_ROWS`, deliberately.** A truncated
        reading history is a partial reading history. A truncated catalogue
        transfer is an institution being told its holdings moved when most of
        them did not, silently."""
        record = f"<record><leader>{marc.LEADER}</leader>{datafield('245', ('a', 'T'))}</record>"
        many = (
            f'<collection xmlns="{MARCXML}">'
            + record * (marc.MAX_RECORDS + 1)
            + "</collection>"
        ).encode("utf-8")
        with pytest.raises(marc.MarcError, match="Split it"):
            marc.read(many)


class TestOneBadRecordCostsOneRecord:
    def test_a_record_with_no_title_is_counted_and_the_rest_complete(self):
        """The ticket's third user story. A catalogue export is the product of
        years and is not uniformly clean."""
        good = f"<record><leader>{marc.LEADER}</leader>{datafield('245', ('a', 'Kept'))}</record>"
        bad = f"<record><leader>{marc.LEADER}</leader>{datafield('020', ('a', '123'))}</record>"
        parsed = marc.read(
            f'<collection xmlns="{MARCXML}">{bad}{good}{bad}</collection>'.encode()
        )

        assert [record.title for record in parsed.records] == ["Kept"]
        assert parsed.skipped == 2
        assert parsed.total == 3

    def test_a_record_naming_a_volume_slot_is_kept_where_a_lookup_refuses_it(self):
        """`metadata._dnb_record` refuses `[Hauptbd.]` because the DNB's `num=`
        index matches cross references, so the catalogue answers about a
        different object. An upload is a cataloguer's own file: what they wrote
        is what they meant."""
        parsed = marc.read(a_record(datafield("245", ("a", "[Hauptbd.]"))))
        assert [record.title for record in parsed.records] == ["[Hauptbd.]"]

    def test_an_online_resource_is_kept_where_a_lookup_refuses_a_disc(self):
        """Same rule, other refusal."""
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "A Title")),
                datafield("300", ("a", "1 DVD-Video")),
            )
        )
        assert [record.title for record in parsed.records] == ["A Title"]

    def test_an_authority_identifier_is_not_read_off_an_uploaded_record(self):
        """`100 $0` is the same subfield the DNB is read for, and the rule is
        `_k10plus_record`'s: a catalogue is not read for a person's identifier
        until somebody has compared it live. Nobody can compare an arbitrary
        upload."""
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "A Title")),
                datafield("100", ("a", "Williams, John"), ("0", "(DE-588)118181505")),
            )
        )
        assert parsed.records[0].author_identifiers == ()

    def test_the_source_names_the_format_and_never_a_catalogue(self):
        """Writing `dnb` on a record somebody uploaded would attribute a
        stranger's cataloguing to the German National Library."""
        assert marc.read(a_record(datafield("245", ("a", "T")))).records[0].source == "marc"


class TestReadingRealCatalogueShapes:
    """Fields as a live catalogue writes them, which is what `metadata.py`'s
    readers were measured against and what this reader inherits."""

    def test_isbd_punctuation_introducing_the_next_subfield_is_stripped(self):
        parsed = marc.read(
            a_record(datafield("245", ("a", "Stoner :"), ("b", "a novel")))
        )
        assert parsed.records[0].title == "Stoner"

    def test_a_cross_referenced_isbn_is_not_taken_as_this_record_s(self):
        """`020 $q` is a qualifier such as "amerik. Original", and taking it
        returned a Ukrainian translation of Dune for the American ISBN."""
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "T")),
                datafield("020", ("a", "9780441013593"), ("q", "amerik. Original")),
                datafield("020", ("a", "9783446249974")),
            )
        )
        assert parsed.records[0].isbn == "9783446249974"

    def test_a_record_whose_only_isbn_is_qualified_still_carries_it(self):
        """`020 $q` is a binding or a volume, not only a cross reference.

        A Greek or Spanish catalogue file imported by hand used to lose its
        ISBNs here, because this reader shares `metadata._marc_isbn` with the
        lookup path and that rule refused every qualified entry.
        """
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "T")),
                datafield("020", ("a", "9789602118962"), ("q", "(τ.1)")),
            )
        )
        assert parsed.records[0].isbn == "9789602118962"

    def test_a_cancelled_isbn_does_not_hide_the_records_own(self):
        """`020 $z` is a cancelled ISBN and carries no `$q`, so a rule that only
        asked about `$q` counted it as the record's plain identifier and dropped
        the qualified entry that actually names the book."""
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "T")),
                datafield("020", ("z", "9781111111111")),
                datafield("020", ("a", "9789602118962"), ("q", "paperback")),
            )
        )
        assert parsed.records[0].isbn == "9789602118962"

    def test_the_older_260_is_read_where_a_record_has_no_264(self):
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "T")),
                datafield("260", ("b", "Hanser"), ("c", "2005")),
            )
        )
        assert (parsed.records[0].publisher, parsed.records[0].year) == ("Hanser", 2005)

    def test_both_dewey_numbers_of_a_record_that_carries_two_are_kept(self):
        """Two catalogues' answers at different precisions, not a duplicate."""
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "T")),
                datafield("082", ("a", "005.13/3")),
                datafield("082", ("a", "004")),
            )
        )
        assert [heading.number for heading in parsed.records[0].headings] == [
            "005.133",
            "004",
        ]

    def test_a_call_number_split_across_two_subfields_is_read_as_one(self):
        """`050 $a $b` is one shelf position, not two assertions."""
        parsed = marc.read(
            a_record(
                datafield("245", ("a", "T")),
                datafield("050", ("a", "QA76.73.P98"), ("b", "V53 2021")),
            )
        )
        assert parsed.records[0].headings == (
            Heading(ClassificationScheme.LCC, "QA76.73.P98 V53 2021", None),
        )

    def test_a_subject_heading_naming_no_vocabulary_is_not_stored_as_one(self):
        """A `650` with no `$0` and no `$2 lcsh` is somebody's uncontrolled
        word. It feeds the tag suggestion and never the classifications table,
        which is `_dnb_subjects` structurally rather than by a filter."""
        parsed = marc.read(
            a_record(datafield("245", ("a", "T")), datafield("650", ("a", "Cookery")))
        )
        assert parsed.records[0].headings == ()
        assert parsed.records[0].subjects == ("Cookery",)


class TestTheSeamIntoMetadataIsPinned:
    """`marc.py` is the one module here that reads another's private names.

    **Derived with `ast`, never listed.** A test naming the twenty names would
    be the shape this repository records as wrong on every first attempt, a
    guard that enumerates something open: it goes stale the first time the seam
    gains a name, and it passes while doing so. Both tests below read the source
    and find out.

    **What a rename actually breaks, corrected.** The first draft of this said
    "a rename breaks MARC at runtime, not at import", and that is wrong for four
    of the twenty: `_MARC`, `_GND_PREFIX`, `_DOCTYPE` and `_LANGUAGES` are read
    at module scope, so renaming one stops the application importing and every
    router test catches it. The other sixteen are read inside a function body,
    where nothing catches it until a request arrives, and those are what this
    guard is for.

    **`mypy` reports all twenty statically and the CI pipeline does not run it.**
    The build runs `ruff check`, the OpenAPI diff and `pytest`, and its only
    mention of the type checker is a comment. Running it there would pin these
    and `_Subfields`, which is annotation only and which no runtime guard can
    reach. That is a pipeline change and is raised rather than made here.

    The pipeline definition is deliberately not named: it is stripped from the
    published tree, and a published file pointing at a stripped path is what the
    publish gate refuses. This docstring was rejected for exactly that once.
    """

    @staticmethod
    def _private_reads(source: str) -> dict[str, set[str]]:
        """Every `<module>._x` this source reads, keyed by the module.

        **Two import shapes, because one of them was a hole.** The first version
        read only `import x` plus `x._y`, and
        `from metadata import _marc_fields` walked straight past it: the guard
        could be evaded by changing an import style. That is the same blind spot
        `tests/test_shelf.py` records against its own first version, which
        caught a parenthesised list and sailed past a one line
        `from models import Book, visible_to`. Found by attacking this rule, not
        by reading it.

        **Scoped to names the file actually imported as modules**, which is the
        difference between a rule and a substring match. The version before that
        tested `node.value.id` against every module basename in the package and
        reported `shelf.py` three times, because `shelf` is also an ordinary
        local variable there and `shelf._unrated` is a method on an instance.

        **Two remaining blind spots, stated rather than left to be found.**

        A file that does `import shelf` *and* binds `shelf` to something else in
        a local scope is reported for the local. Closing that needs the scope
        and binding machinery the retired `TestEveryBookQueryIsFiltered` was
        made of and was retired for. No file in this package takes that shape
        today, and the failure direction is a false report rather than a missed
        one.

        A relative `from .book import _x` inside a sub-package keys under
        `book`, which is not a top level module name, so the "one of ours"
        filter drops it. The failure direction is the other way round, a missed
        read rather than a false one, which is why it is written down here
        rather than left to be discovered.
        """
        tree = ast.parse(source)
        # **Keyed on the module, not on the local binding.** `import metadata as
        # m` binds `m`, and keying on `m` put the read under a name no caller
        # would ever look for, so the "is it one of ours" filter below skipped
        # it: an aliased import was a clean evasion. This is the failure this
        # repository has recorded against a guard before.
        imported = {
            (alias.asname or alias.name.split(".")[0]): alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        found: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in imported
                and node.attr.startswith("_")
            ):
                found.setdefault(imported[node.value.id], set()).add(node.attr)
            # `from metadata import _marc_fields` reaches the same name by the
            # other door and used to be invisible here.
            elif isinstance(node, ast.ImportFrom) and node.module:
                private = {
                    alias.name for alias in node.names if alias.name.startswith("_")
                }
                if private:
                    found.setdefault(node.module.split(".")[0], set()).update(private)
        return found

    def test_the_anchor_is_the_source_tree_and_not_an_installed_copy(self):
        """Every other assertion in this class is about whatever `BACKEND`
        points at, so a wrong anchor makes all of them vacuous while staying
        green.

        **This is not hypothetical, it is what happened.** `BACKEND` was
        `Path(marc.__file__).parent`, which in CI is the installed copy inside
        `site-packages`, so the scan below reported `pydantic`, `click` and
        `sqlalchemy` reading each other's private names. Locally it resolved to
        the source tree and the suite was green.
        """
        assert (BACKEND / "marc.py").is_file(), (
            f"{BACKEND} does not hold marc.py, so this class is scanning the "
            "wrong tree and every assertion in it is vacuous"
        )
        assert "site-packages" not in BACKEND.parts, (
            f"{BACKEND} is inside a virtualenv, so the scan is walking installed "
            "third party packages rather than this application"
        )
        # The source tree, not a build artefact: these two exist only here.
        assert (BACKEND / "tests").is_dir()
        assert (BACKEND / "pyproject.toml").is_file()

    def test_every_private_name_marc_reads_still_exists_on_metadata(self):
        """A rename in `metadata.py` fails here rather than inside a request."""
        source = (BACKEND / "marc.py").read_text(encoding="utf-8")
        names = self._private_reads(source).get("metadata", set())

        assert names, (
            "marc.py no longer reads metadata's MARC parser, so either this "
            "guard is vacuous or the reader has been rewritten twice"
        )
        missing = sorted(name for name in names if not hasattr(metadata, name))
        assert missing == [], (
            f"marc.py reads {missing} on metadata and metadata no longer has "
            "them. The MARC reader composes that parser rather than restating "
            "it, so a rename there is a break here."
        )

    def test_marc_is_the_only_module_reaching_into_another(self):
        """The exception stays one exception.

        Reading another module's private names is a boundary this tree has
        nowhere else. It is defensible exactly once, because the MARC field
        knowledge was measured against live catalogues and must not be written
        twice; a second module doing it is a second copy of that argument, and
        the argument does not hold twice.
        """
        # **A directory of ours is decided structurally, never by name**, and
        # that took two red pipelines to learn. The first version skipped a set
        # of names, `{"tests", "migrations", ".venv", "__pycache__"}`; CI put an
        # environment inside `backend/` under some other name, the walk went in,
        # and the guard reported `pydantic`, `packaging`, `urllib3` and the
        # standard library's own `xml` reading each other's private names as
        # violations of a rule about this application. A name list is the shape
        # this repository records as wrong every time: it enumerates something
        # open.
        #
        # What is closed is the structure. **A Python environment always has a
        # `pyvenv.cfg` at its root**, whatever the directory is called, and
        # installed packages always sit under `site-packages`. So the walk is
        # bounded to this package's own sub-packages: the top level modules,
        # plus each depth one directory that holds Python and is not an
        # environment, a cache or hidden.
        def is_ours(directory: pathlib.Path) -> bool:
            return (
                directory.is_dir()
                and not directory.name.startswith(".")
                and directory.name not in {"__pycache__", "tests", "migrations"}
                and not (directory / "pyvenv.cfg").exists()
                and "site-packages" not in directory.parts
                and any(directory.rglob("*.py"))
            )

        packages = sorted(d for d in BACKEND.iterdir() if is_ours(d))
        def is_ours_file(f: pathlib.Path) -> bool:
            """Belt and braces under a package of ours: a nested environment or
            cache is excluded by the same structural test, at any depth."""
            parts = f.relative_to(BACKEND).parts
            return not (
                {"__pycache__", "site-packages", "dist-packages"} & set(parts)
                or any(part.startswith(".") for part in parts)
            )

        sources = sorted(BACKEND.glob("*.py")) + [
            f for d in packages for f in sorted(d.rglob("*.py")) if is_ours_file(f)
        ]

        # Only this application's own modules, so `metadata._MARC` counts and a
        # standard library private does not: `os._exit` is a documented name and
        # nothing here is arguing about the standard library's boundaries.
        #
        # Sub-package names as well as module stems, because `import
        # schemas.book as b` then `b._x` keys under `schemas`, and a namespace
        # package such as `routers` has no `__init__.py` to be recognised by.
        ours = {f.stem for f in sources} | {d.name for d in packages}

        offenders = {}
        for path in sources:
            if path.name == "marc.py":
                continue
            found = {
                f"{module}.{attr}"
                for module, attrs in self._private_reads(
                    path.read_text(encoding="utf-8")
                ).items()
                if module in ours
                for attr in attrs
            }
            if found:
                # **Keyed on the path, not the basename.** The first version
                # keyed on `path.name`, so a failure naming `metadata.py` could
                # not be told from one naming an installed package's own
                # `metadata.py`, and two pipelines were spent guessing where the
                # reported files were.
                offenders[str(path.relative_to(BACKEND))] = sorted(found)

        assert offenders == {}, (
            f"These modules read another module's private names: {offenders}. "
            "marc.py is the only one this tree admits, and its reason is in its "
            "own docstring."
        )


class TestEveryColumnTheImporterWritesIsBounded:
    """No field of a MARC record may be silently uncovered by the guard.

    **This exists because one was.** `within_bounds` reads the bound off
    `BookCreate.model_fields` and the column width off `Book.__table__`, and
    `description` had neither: a `Text` column reports no length and the field
    carried no `max_length`, so the value came back whole while the docstring
    said "strings truncate". Both critic seats found it independently, from
    opposite ends.

    The lesson is not that `description` needed a bound, it is that **a field
    added later inherits the absence rather than the guard**. So the tuple the
    importer walks is enumerated here and every entry is required to derive one,
    which is a rule rather than a list: adding a field to `_MARC_RECORD_FIELDS`
    without giving it a bound reddens this.
    """

    def test_every_field_the_importer_writes_derives_a_bound(self):
        from importing import _MARC_RECORD_FIELDS, within_bounds

        unbounded = []
        for name in _MARC_RECORD_FIELDS:
            # A value no bound could leave alone: past every string width in the
            # schema and past every numeric ceiling.
            probe: object = "x" * 100_000
            if BookCreate.model_fields[name].annotation in (int | None, float | None):
                probe = 10**9
            if within_bounds(name, probe) == probe:
                unbounded.append(name)

        assert unbounded == [], (
            f"{unbounded} pass through `within_bounds` unchanged, so an uploaded "
            "record can write whatever it likes into them. The guard reads the "
            "bound off `BookCreate.model_fields` and the column width off "
            "`Book.__table__`; give the field one of those rather than adding an "
            "arm to the guard."
        )

    def test_the_tuple_the_importer_walks_is_the_one_the_book_has(self):
        """A name in `_MARC_RECORD_FIELDS` that is not a column would be a
        `TypeError` at the first import, and a column missing from it is a field
        the guard never sees."""
        from importing import _MARC_RECORD_FIELDS
        from models import Book

        missing = [name for name in _MARC_RECORD_FIELDS if name not in Book.__table__.c]
        assert missing == [], f"{missing} are not columns of `books`"
