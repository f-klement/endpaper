"""Tests for backend/harvester.py: the OAI-PMH client, against a fake repository.

The repository is `respx` behind `fetch.pinned_client`, at an address literal, so
the shipped transport runs end to end and no lookup is made: `tests/test_opds.py`
says why a literal reaches no resolver. Nothing here touches the network.
"""

import asyncio
import dataclasses
from dataclasses import dataclass
from typing import Final
from xml.etree import ElementTree

import httpx
import pytest
import respx
from hypothesis import given
from hypothesis import strategies as st

import fetch
import harvester
import settings_store
import xml_parse
from enums import SettingKey
from models import HARVESTED_IDENTIFIER_MAX
from tests.strategies import (
    FAR_PAST_ANY_DEPTH,
    Node,
    answer_of,
    charsets,
    declared_encodings,
    depths,
    encoded,
    marc_records,
    widths,
    witness,
    xml_of,
)

#: A household address, which `fetch.HOUSEHOLD_ADDRESSES` admits.
BASE = "http://10.0.9.9:8080/oai"
OAI = harvester.OAI
MARC = "http://www.loc.gov/MARC21/slim"


def response(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><OAI-PMH xmlns="{OAI}"><responseDate/>{body}</OAI-PMH>'


def marc_record(title: str, isbn: str | None = None) -> str:
    fields = f'<datafield tag="245" ind1="0" ind2="0"><subfield code="a">{title}</subfield></datafield>'
    if isbn:
        fields += f'<datafield tag="020" ind1=" " ind2=" "><subfield code="a">{isbn}</subfield></datafield>'
    return f'<record xmlns="{MARC}"><leader>00000nam a22000003  4500</leader>{fields}</record>'


def oai_record(title: str, *, deleted: bool = False, isbn: str | None = None) -> str:
    if deleted:
        return f'<record><header status="deleted"><identifier>oai:x:{title}</identifier></header></record>'
    return (
        f"<record><header><identifier>oai:x:{title}</identifier></header>"
        f"<metadata>{marc_record(title, isbn)}</metadata></record>"
    )


def list_records(*records: str, token: str | None = None) -> str:
    resumption = f"<resumptionToken>{token}</resumptionToken>" if token is not None else ""
    return response(f"<ListRecords>{''.join(records)}{resumption}</ListRecords>")


def first_page(**params: str) -> dict[str, str]:
    return {"verb": "ListRecords", "metadataPrefix": "marcxml"} | params


def page_after(token: str) -> dict[str, str]:
    return {"verb": "ListRecords", "resumptionToken": token}


def run(coroutine):
    return asyncio.run(coroutine)


async def listed(deadline_seconds: float = harvester.RUN_DEADLINE_SECONDS, **options) -> harvester.Harvested:
    async with harvester.repository(BASE, deadline_seconds=deadline_seconds) as source:
        return await source.list_records("marcxml", **options)


def answered_late(text: str):
    """A respx side effect that answers `text` long after any deadline here."""

    async def late(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200, text=text)

    return late


class TestListRecordsPages:
    @respx.mock
    def test_a_resumption_token_is_followed_to_the_last_page(self):
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token="t1"))
        respx.get(BASE, params=page_after("t1")).respond(text=list_records(oai_record("Two"), token=""))

        got = run(listed())

        assert [record.title for record in got.parsed.records] == ["One", "Two"]
        assert (got.pages_read, got.seen, got.truncated) == (2, 2, False)

    @respx.mock
    def test_a_set_is_asked_for_on_the_first_page(self):
        route = respx.get(BASE, params=first_page(set="theses")).respond(text=list_records(oai_record("One")))

        run(listed(set_spec="theses"))

        assert route.call_count == 1

    @respx.mock
    def test_a_token_handed_back_twice_is_refused(self):
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token="t1"))
        again = respx.get(BASE, params=page_after("t1")).respond(
            text=list_records(oai_record("Two"), token="t1")
        )

        with pytest.raises(harvester.HarvestError, match="resumption token"):
            run(listed())
        assert again.call_count == 1

    @respx.mock
    def test_no_records_match_is_an_empty_run_rather_than_an_error(self):
        respx.get(BASE, params=first_page()).respond(text=response('<error code="noRecordsMatch"/>'))

        got = run(listed())

        assert (got.parsed.records, got.seen, got.truncated) == ((), 0, False)

    @respx.mock
    def test_any_other_error_is_refused_with_its_code(self):
        respx.get(BASE, params=first_page()).respond(text=response('<error code="badArgument">x</error>'))

        with pytest.raises(harvester.HarvestError, match="badArgument"):
            run(listed())

    @respx.mock
    def test_an_error_code_outside_the_protocol_is_not_echoed(self):
        respx.get(BASE, params=first_page()).respond(text=response('<error code="secretHost"/>'))

        with pytest.raises(harvester.HarvestError) as refused:
            run(listed())
        assert "secretHost" not in str(refused.value)


class TestARunIsBounded:
    @respx.mock
    def test_the_record_cap_stops_the_run_and_says_so(self):
        respx.get(BASE, params=first_page()).respond(
            text=list_records(oai_record("One"), oai_record("Two"), oai_record("Three"), token="t1")
        )
        following = respx.get(BASE, params=page_after("t1")).respond(text=list_records(oai_record("Four")))

        got = run(listed(max_records=2))

        assert [record.title for record in got.parsed.records] == ["One", "Two"]
        assert (got.seen, got.truncated, following.call_count) == (2, True, 0)

    @respx.mock
    def test_the_page_cap_stops_the_run_and_says_so(self):
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token="t1"))
        respx.get(BASE, params=page_after("t1")).respond(text=list_records(oai_record("Two"), token="t2"))
        third = respx.get(BASE, params=page_after("t2")).respond(text=list_records(oai_record("Three")))

        got = run(listed(max_pages=2))

        assert (got.pages_read, got.truncated, third.call_count) == (2, True, 0)

    @respx.mock
    def test_a_run_that_ends_on_its_own_is_not_truncated_at_the_cap(self):
        """Anti vacuity for the two above: the last page carries no token."""
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), oai_record("Two")))

        assert run(listed(max_records=2)).truncated is False

    @respx.mock
    def test_the_run_deadline_reached_mid_request_keeps_the_pages_read(self):
        """A slow repository is the migration case: its run truncates rather
        than being thrown away at the deadline."""
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token="t1"))
        late = answered_late(list_records(oai_record("Two")))
        respx.get(BASE, params=page_after("t1")).mock(side_effect=late)

        got = run(listed(deadline_seconds=0.5))

        assert [record.title for record in got.parsed.records] == ["One"]
        assert (got.pages_read, got.truncated) == (1, True)

    @respx.mock
    def test_a_request_timeout_mid_run_keeps_the_pages_read(self, monkeypatch):
        """The per request bound truncates as the run deadline does, with the
        run deadline left at its default so only the request's can bind."""
        monkeypatch.setattr(fetch, "TIMEOUT_SECONDS", 0.5)
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token="t1"))
        respx.get(BASE, params=page_after("t1")).mock(
            side_effect=answered_late(list_records(oai_record("Two")))
        )

        got = run(listed())

        assert [record.title for record in got.parsed.records] == ["One"]
        assert (got.pages_read, got.truncated) == (1, True)

    @respx.mock
    def test_the_deadline_reached_before_any_page_is_refused(self):
        """Anti vacuity for the truncation: with nothing read there is nothing to keep."""
        respx.get(BASE, params=first_page()).mock(side_effect=answered_late(list_records(oai_record("One"))))

        with pytest.raises(harvester.HarvestError, match="in time"):
            run(listed(deadline_seconds=0.5))

    @respx.mock
    def test_a_busy_repository_mid_run_keeps_the_pages_read(self):
        """A 503 is OAI-PMH's flow control, not a failure of the pages before it."""
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token="t1"))
        respx.get(BASE, params=page_after("t1")).respond(status_code=503)

        got = run(listed())

        assert [record.title for record in got.parsed.records] == ["One"]
        assert got.truncated is True

    @respx.mock
    def test_a_busy_repository_on_the_first_page_is_refused_with_its_status(self):
        respx.get(BASE, params=first_page()).respond(status_code=503)

        with pytest.raises(harvester.HarvestError, match="503"):
            run(listed())

    @respx.mock
    def test_a_repository_that_cannot_be_reached_is_refused_as_unreachable(self):
        respx.get(BASE, params=first_page()).mock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(harvester.HarvestError, match="could not be reached"):
            run(listed())

    @respx.mock
    def test_a_resumption_token_wider_than_the_bound_is_refused(self):
        wide = "t" * (harvester.MAX_TOKEN_LENGTH + 1)
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token=wide))

        with pytest.raises(harvester.HarvestError, match="wider"):
            run(listed())

    @respx.mock
    def test_a_resumption_token_at_the_bound_is_followed(self):
        """Anti vacuity for the width refusal."""
        widest = "t" * harvester.MAX_TOKEN_LENGTH
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), token=widest))
        respx.get(BASE, params=page_after(widest)).respond(text=list_records(oai_record("Two")))

        assert run(listed()).pages_read == 2

    def test_a_link_local_repository_is_refused_before_any_request(self):
        async def refused() -> None:
            async with harvester.repository("http://169.254.169.254/oai") as source:
                await source.identify()

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith="http://169.254.169.254").respond(text=response("<Identify/>"))
            with pytest.raises(harvester.HarvestError, match="will not connect"):
                run(refused())
            assert route.call_count == 0


class TestOneRunAtATime:
    def test_a_second_run_is_refused_while_one_runs(self):
        with harvester.one_run(), pytest.raises(harvester.AlreadyRunning), harvester.one_run():
            pass

    def test_a_run_that_failed_lets_the_next_one_start(self):
        """Anti vacuity: the refusal is the run in progress, not a run that once was."""
        with pytest.raises(harvester.HarvestError, match="failed"), harvester.one_run():
            raise harvester.HarvestError("failed")

        with harvester.one_run():
            pass


class TestWhatARecordBecomes:
    @respx.mock
    def test_a_deleted_header_is_counted_and_reads_as_no_record(self):
        respx.get(BASE, params=first_page()).respond(
            text=list_records(oai_record("Kept"), oai_record("Gone", deleted=True))
        )

        got = run(listed())

        assert [record.title for record in got.parsed.records] == ["Kept"]
        assert (got.seen, got.deleted) == (2, 1)

    @respx.mock
    def test_a_marc_record_is_read_as_the_upload_reader_reads_it(self):
        respx.get(BASE, params=first_page()).respond(
            text=list_records(oai_record("Dune", isbn="978-0-441-17271-9"))
        )

        (record,) = run(listed()).parsed.records

        assert (record.title, record.isbn) == ("Dune", "9780441172719")

    @respx.mock
    def test_a_record_with_no_marc_metadata_is_skipped_and_counted(self):
        respx.get(BASE, params=first_page()).respond(
            text=list_records("<record><header/><metadata><dc/></metadata></record>", oai_record("Kept"))
        )

        got = run(listed())

        assert (len(got.parsed.records), got.parsed.skipped) == (1, 1)

    @respx.mock
    def test_each_record_keeps_its_identifier_past_one_the_reader_skipped(self):
        """`marc.read` drops a record with no title without saying which, so
        the identifiers must stay beside the records they came with."""
        untitled = (
            "<record><header><identifier>oai:x:untitled</identifier></header>"
            f'<metadata><record xmlns="{MARC}"><leader>00000nam a22000003  4500</leader></record>'
            "</metadata></record>"
        )
        respx.get(BASE, params=first_page()).respond(
            text=list_records(oai_record("One"), untitled, oai_record("Two"))
        )

        got = run(listed())

        assert [record.title for record in got.parsed.records] == ["One", "Two"]
        assert got.identifiers == ("oai:x:One", "oai:x:Two")
        assert got.parsed.skipped == 1

    @respx.mock
    def test_each_record_keeps_its_identifier_on_a_page_that_skipped_none(self):
        """The other arm of the same read: one parse for the whole page."""
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record("One"), oai_record("Two")))

        assert run(listed()).identifiers == ("oai:x:One", "oai:x:Two")

    @pytest.mark.parametrize(
        "nested",
        [
            "".join(marc_record(f"Nested {n}") for n in range(3)),
            # Under a wrapper and not a direct child: `marc.read` walks every
            # depth, so a check reading the direct children alone lets it by.
            f'<datafield tag="999" ind1=" " ind2=" ">{marc_record("Wrapped")}</datafield>',
        ],
        ids=["as_children", "under_a_datafield"],
    )
    @respx.mock
    def test_a_marc_record_holding_others_is_unreadable_and_takes_no_identifier(self, nested):
        """A hostile repository's way past the record cap: `marc.read` reads a
        nested record as a record of its own, so three inside one page of two
        would be five Books under a cap of two, each after the first under its
        predecessor's identifier."""
        outer = marc_record("Outer").replace("</record>", f"{nested}</record>", 1)
        hostile = (
            "<record><header><identifier>oai:x:Outer</identifier></header>"
            f"<metadata>{outer}</metadata></record>"
        )
        respx.get(BASE, params=first_page()).respond(text=list_records(hostile, oai_record("Two")))

        got = run(listed(max_records=2))

        assert [record.title for record in got.parsed.records] == ["Two"]
        assert got.identifiers == ("oai:x:Two",)
        assert (got.seen, got.parsed.skipped) == (2, 1)

    @respx.mock
    def test_two_marc_records_side_by_side_in_one_metadata_are_unreadable(self):
        """Otherwise the first is kept under the identifier and the second is
        dropped with nothing counting it."""
        twins = (
            "<record><header><identifier>oai:x:Twins</identifier></header>"
            f"<metadata>{marc_record('First')}{marc_record('Second')}</metadata></record>"
        )
        respx.get(BASE, params=first_page()).respond(text=list_records(twins, oai_record("Two")))

        got = run(listed())

        assert [record.title for record in got.parsed.records] == ["Two"]
        assert got.identifiers == ("oai:x:Two",)
        assert (got.seen, got.parsed.skipped) == (2, 1)

    @respx.mock
    def test_an_identifier_wider_than_its_column_is_not_kept(self):
        wide = "w" * (HARVESTED_IDENTIFIER_MAX + 1)
        respx.get(BASE, params=first_page()).respond(text=list_records(oai_record(wide)))

        got = run(listed())

        assert len(got.parsed.records) == 1
        assert got.identifiers == (None,)

    @respx.mock
    def test_a_doctype_is_refused(self):
        respx.get(BASE, params=first_page()).respond(
            text='<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "a">]>' + list_records(oai_record("One"))
        )

        with pytest.raises(harvester.HarvestError, match="document type"):
            run(listed())

    @respx.mock
    def test_a_response_that_is_not_oai_pmh_is_refused(self):
        respx.get(BASE, params=first_page()).respond(text="<html/>")

        with pytest.raises(harvester.HarvestError, match="OAI-PMH response"):
            run(listed())


class TestTheOtherVerbs:
    @respx.mock
    def test_identify_reads_the_repository_name(self):
        respx.get(BASE, params={"verb": "Identify"}).respond(
            text=response(
                "<Identify><repositoryName>Old Catalogue</repositoryName>"
                "<protocolVersion>2.0</protocolVersion></Identify>"
            )
        )

        async def asked() -> harvester.Identity:
            async with harvester.repository(BASE) as source:
                return await source.identify()

        assert run(asked()) == harvester.Identity(name="Old Catalogue", protocol_version="2.0")

    @respx.mock
    def test_a_repository_name_is_cut_to_its_bound(self):
        respx.get(BASE, params={"verb": "Identify"}).respond(
            text=response(f"<Identify><repositoryName>{'n' * 5000}</repositoryName></Identify>")
        )

        async def asked() -> harvester.Identity:
            async with harvester.repository(BASE) as source:
                return await source.identify()

        assert run(asked()).name == "n" * harvester.NAME_MAX

    @respx.mock
    def test_the_marc_format_is_chosen_by_namespace_not_by_prefix(self):
        respx.get(BASE, params={"verb": "ListMetadataFormats"}).respond(
            text=response(
                "<ListMetadataFormats>"
                "<metadataFormat><metadataPrefix>oai_dc</metadataPrefix>"
                "<metadataNamespace>http://www.openarchives.org/OAI/2.0/oai_dc/</metadataNamespace></metadataFormat>"
                f"<metadataFormat><metadataPrefix>marc21</metadataPrefix><metadataNamespace>{MARC}</metadataNamespace>"
                "</metadataFormat></ListMetadataFormats>"
            )
        )

        async def chosen() -> str:
            async with harvester.repository(BASE) as source:
                return await source.marc_prefix()

        assert run(chosen()) == "marc21"

    @respx.mock
    def test_a_repository_offering_no_marc_is_refused(self):
        respx.get(BASE, params={"verb": "ListMetadataFormats"}).respond(
            text=response(
                "<ListMetadataFormats><metadataFormat><metadataPrefix>oai_dc</metadataPrefix>"
                "</metadataFormat></ListMetadataFormats>"
            )
        )

        async def chosen() -> str:
            async with harvester.repository(BASE) as source:
                return await source.marc_prefix()

        with pytest.raises(harvester.HarvestError, match="no MARCXML"):
            run(chosen())

    @respx.mock
    def test_get_record_reads_one_record(self):
        respx.get(
            BASE, params={"verb": "GetRecord", "identifier": "oai:x:1", "metadataPrefix": "marcxml"}
        ).respond(text=response(f"<GetRecord>{oai_record('Only')}</GetRecord>"))

        async def fetched() -> harvester.Harvested:
            async with harvester.repository(BASE) as source:
                return await source.get_record("oai:x:1", "marcxml")

        assert [record.title for record in run(fetched()).parsed.records] == ["Only"]


@dataclass(frozen=True)
class ResponseSpec:
    """A `ListRecords` response as a spec. Drawn by
    `TestAResponseIsReadOrRefusedByName` and rebuilt by `a_response`."""

    #: Each record's MARC `record` element, carried in its OAI `metadata`.
    records: tuple[Node, ...]
    #: The encoding the XML declaration names, or None for no declaration.
    declaration: str | None
    #: How deep a chain of elements inside one extra record goes, 0 for none.
    nest_depth: int
    #: The charset the response is labelled with and written in.
    charset: str
    #: How many empty siblings the extra record carries, 0 for none.
    width: int = 0


#: What the envelope spends of `xml_parse.MAX_DEPTH` above a nest: the
#: response, `ListRecords` and the extra `record`.
_ENVELOPE_DEPTH: Final = 3


def response_text(spec: ResponseSpec) -> str:
    """The response the spec describes, as the repository meant it."""
    records = [
        Node(
            "record",
            children=(
                Node("header", children=(Node("identifier", text=f"oai:x:{index}"),)),
                Node("metadata", children=(dataclasses.replace(marc, attrs=(("xmlns", MARC),)),)),
            ),
        )
        for index, marc in enumerate(spec.records)
    ]
    if spec.nest_depth or spec.width:
        records.append(Node("record", nest=spec.nest_depth, width=spec.width))
    prolog = f'<?xml version="1.0" encoding="{spec.declaration}"?>' if spec.declaration is not None else ""
    listed = "".join(xml_of(record) for record in records)
    return f'{prolog}<OAI-PMH xmlns="{OAI}"><responseDate/><ListRecords>{listed}</ListRecords></OAI-PMH>'


def a_response(spec: ResponseSpec) -> str:
    """The response as `Repository._ask` hands it to `read_response`: built at
    the `fetch.Fetched` seam, as bytes in a charset, and never as a `str`."""
    return fetch.Fetched(200, encoded(response_text(spec), spec.charset), spec.charset).text


RESPONSES: Final = st.builds(
    ResponseSpec,
    records=st.lists(marc_records(), max_size=3).map(tuple),
    declaration=st.none() | declared_encodings(),
    nest_depth=depths(xml_parse.MAX_DEPTH - _ENVELOPE_DEPTH),
    charset=charsets(),
    width=widths(),
)


def _listed(root: ElementTree.Element) -> int:
    return len(root.findall(f"{{{OAI}}}ListRecords/{{{OAI}}}record"))


def _read(spec: ResponseSpec) -> ElementTree.Element | harvester.HarvestError:
    """What `read_response` answered for this response, or the refusal it raised."""
    try:
        return harvester.read_response(a_response(spec))
    except harvester.HarvestError as refusal:
        return refusal


def _within_its_bound(body: str, peak: int) -> bool:
    return peak <= harvester.ALLOCATION_FACTOR * len(body.encode()) + xml_parse.ALLOCATION_FLOOR


class TestAResponseIsReadOrRefusedByName:
    """`harvester.read_response` answers a root element or `HarvestError`, and
    nothing else, inside its allocation bound. Every verb's answer passes it."""

    @pytest.mark.property
    @given(spec=RESPONSES)
    def test_it_answers_a_root_or_refuses_inside_its_allocation_bound(self, spec):
        """**The value is the spec's own**: every record drawn is listed, the
        extra one included. Checked where the charset carried the response
        unchanged, since a codec that rewrites markup writes another one."""
        body = a_response(spec)
        got = answer_of(
            harvester.read_response, body, answers=ElementTree.Element, refuses=harvester.HarvestError
        )
        assert _within_its_bound(body, got.peak)
        if spec.nest_depth > xml_parse.MAX_DEPTH - _ENVELOPE_DEPTH:
            assert got.refusal is not None
        if got.value is not None and body == response_text(spec):
            assert _listed(got.value) == len(spec.records) + (1 if spec.nest_depth or spec.width else 0)

    def test_the_generator_still_reaches_a_response_of_records(self):
        witness(
            RESPONSES,
            lambda spec: not isinstance(root := _read(spec), Exception) and _listed(root) > 0,
            reaches="a response read with records listed",
        )

    def test_the_generator_still_reaches_a_wide_record_read(self):
        """The allocation factor's positive control is this shape reaching the
        parse, asked of what the door answered."""
        witness(
            RESPONSES,
            lambda spec: spec.width > 0 and not isinstance(_read(spec), Exception),
            reaches="a record of `WIDE` empty siblings, read",
        )

    def test_the_generator_still_reaches_the_depth_bound(self):
        witness(
            RESPONSES,
            lambda spec: "nested more than" in str(getattr(_read(spec), "__cause__", "")),
            reaches="a nest past the depth bound",
        )


class TestWhatTheResponseDoorRefuses:
    @staticmethod
    def _a_record_holding(fill: str) -> str:
        return response(f"<ListRecords><record><header/>{fill}</record></ListRecords>")

    def test_a_record_at_the_depth_bound_is_read_and_one_deeper_is_refused(self):
        """The positive control for `xml_parse.MAX_DEPTH` at this door."""
        at_the_bound = ResponseSpec(
            records=(), declaration=None, nest_depth=xml_parse.MAX_DEPTH - _ENVELOPE_DEPTH, charset="utf-8"
        )
        assert _listed(harvester.read_response(a_response(at_the_bound))) == 1
        one_deeper = dataclasses.replace(at_the_bound, nest_depth=xml_parse.MAX_DEPTH - _ENVELOPE_DEPTH + 1)
        with pytest.raises(harvester.HarvestError) as refused:
            harvester.read_response(a_response(one_deeper))
        assert "nested more than" in str(refused.value.__cause__)

    def test_a_nest_far_past_any_real_response_is_refused_inside_its_bound(self):
        body = a_response(
            ResponseSpec(records=(), declaration=None, nest_depth=FAR_PAST_ANY_DEPTH, charset="037")
        )
        got = answer_of(
            harvester.read_response, body, answers=ElementTree.Element, refuses=harvester.HarvestError
        )
        assert got.refusal is not None
        assert _within_its_bound(body, got.peak)

    def test_a_record_of_one_short_element_repeated_is_refused_inside_its_bound(self):
        """The shortest element carrying an attribute, refused by
        `xml_parse.BYTES_PER_ATTRIBUTED`."""
        body = self._a_record_holding('<e a=""/>' * 100_000)
        got = answer_of(
            harvester.read_response, body, answers=ElementTree.Element, refuses=harvester.HarvestError
        )
        assert got.refusal is not None
        assert "carries an attribute" in str(got.refusal.__cause__)
        assert _within_its_bound(body, got.peak)

    def test_the_costliest_shape_found_at_the_bound_is_read_inside_its_bound(self):
        """**The shape `harvester.ALLOCATION_FACTOR` is held on**, the one
        `opds.ALLOCATION_FACTOR` was measured on: an element carrying an
        attribute at the density bound, counted in characters since this door
        is handed text, the rest bare elements, every tail one character
        outside Latin 1."""
        shape = '<e a=""/>\u0100<x/>\u0100<x/>\u0100'
        assert len(shape) == xml_parse.BYTES_PER_ATTRIBUTED
        body = self._a_record_holding(shape * 45_000)
        got = answer_of(
            harvester.read_response, body, answers=ElementTree.Element, refuses=harvester.HarvestError
        )
        assert got.value is not None
        assert _within_its_bound(body, got.peak)


class TestWhichAddressTheHarvesterMayBePointedAt:
    """`is_harvestable`, read by the settings write and on every run. The
    write's 400 is held in `tests/routers/test_settings.py`; here each arm."""

    @pytest.mark.parametrize(
        "address",
        ["http://10.0.9.9:8080/oai", "https://repository.example/oai", "http://localhost/oai"],
    )
    def test_a_household_or_named_repository_is_admitted(self, address):
        assert harvester.is_harvestable(address)

    @pytest.mark.parametrize(
        "address",
        [
            "ftp://repository.example/oai",
            "https://harvest@repository.example/oai",
            "https://:secret@repository.example/oai",
            "https://repository.example/oai?verb=Identify",
            "https://repository.example/oai#records",
            "https:///oai",
            "https://repository.example:0/oai",
            "https://repository.example:99999/oai",
            "http://[::1/oai",
            "http://169.254.169.254/latest",
        ],
    )
    def test_an_address_it_may_not_reach_is_refused(self, address):
        assert not harvester.is_harvestable(address)


class TestTheConfiguredRepository:
    """`configured_repository`: the stored address, read again through `is_harvestable`."""

    def _stored(self, db, address: str) -> None:
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        settings_store.set_value(db, SettingKey.OAI_HARVEST_ENABLED, "true")
        settings_store.set_value(db, SettingKey.OAI_HARVEST_BASE_URL, address)

    def test_an_admitted_stored_address_is_the_repository(self, db):
        self._stored(db, BASE)
        assert harvester.configured_repository(db) == BASE

    def test_a_stored_address_that_no_longer_validates_names_no_repository(self, db):
        """Read again rather than trusted from the write: a hand edit or a
        restore can store what the route would refuse."""
        self._stored(db, "http://169.254.169.254/latest")
        assert harvester.configured_repository(db) is None
