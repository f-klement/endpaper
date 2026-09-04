"""The catalogue targets: what a row may say, and what the seeded nine do say."""

import dataclasses
import re

import pytest

import sources
import targets
import z3950
from enums import CatalogueSource


def _seeded(**overrides: object) -> targets.Target:
    """A valid SRU row, so a test can change one field and see what happens."""
    fields: dict[str, object] = {
        "source": CatalogueSource.K10PLUS,
        "rank": 1,
        "transport": targets.Transport.SRU,
        "base_url": "https://sru.k10plus.de/opac-de-627",
        "reader": targets.Reader.MARC_PLAIN,
        "answers_lookup": True,
        "answers_search": True,
        "metered": False,
        "needs_key": False,
        "sru_version": "1.1",
        "query_parameter": "query",
        "query_language": targets.QueryLanguage.CQL,
        "record_schema": "marcxml",
        "isbn_index": "pica.isb",
        "title_index": "pica.all",
        "title_query_shape": targets.TitleQuery.ANDED_TERMS,
        "lookup_records": 5,
        "search_multiplier": 3,
        "search_cap": 50,
    }
    fields.update(overrides)
    return targets.Target(**fields)  # type: ignore[arg-type]


class TestTheSeededRosterSaysWhatTheRulesSay:
    """The nine rows, against the constants derived from them and beside them."""

    def test_the_roster_is_the_whole_closed_enum(self):
        assert sorted(targets.SEEDED) == sorted(CatalogueSource)

    def test_each_row_names_itself(self):
        """A row filed under the wrong key would label every record it parses."""
        for source, target in targets.SEEDED.items():
            assert target.source is source

    def test_rank_is_the_default_order(self):
        """`rank` is a copy of `sources.DEFAULT_ORDER` and nothing reads it.

        Pinned for exactly that reason: a copy nothing reads is a copy nothing
        notices going stale, and #130 is where it starts being read.
        """
        assert [
            target.source
            for target in sorted(targets.SEEDED.values(), key=lambda t: t.rank)
        ] == list(sources.DEFAULT_ORDER)

    def test_only_the_dnb_waives_the_isbn_claim(self):
        """Everywhere else that check is the identity test, and at the ÖNB it is
        the whole defence against a mistyped index answering with the catalogue.

        A set equality rather than a spot check, so widening it costs an argument
        rather than passing quietly.
        """
        assert {
            target.source
            for target in targets.SEEDED.values()
            if not target.requires_isbn_claim
        } == {CatalogueSource.DNB}

    def test_only_the_dnb_is_read_for_author_identifiers(self):
        """The ÖNB's and the NLG's `100 $0` are withheld rather than unmapped.

        Same shape as the ISBN claim pin, and for the same reason: a decision
        somebody took on a measurement should not be reversible by a default.
        """
        assert {
            target.source
            for target in targets.SEEDED.values()
            if target.reads_author_identifiers
        } == {CatalogueSource.DNB}

    def test_no_seeded_row_carries_a_timeout(self):
        """The column is #132's. Pinned so it cannot be read as working."""
        assert all(target.timeout_seconds is None for target in targets.SEEDED.values())

    def test_every_row_is_seeded_reachable_over_http(self):
        """Every address parses to an origin, and none carries a credential."""
        for target in targets.SEEDED.values():
            origin = targets.origin(target.base_url)
            assert origin in targets.SEEDED_ORIGINS
            assert "@" not in origin
            assert origin.startswith(("http://", "https://"))

    def test_the_origins_are_one_per_host_and_carry_the_scheme(self):
        """Scheme and port, not a bare host: three targets are plaintext by
        necessity and a hostname allowlist would let the other six join them."""
        assert {
            targets.origin(target.base_url) for target in targets.SEEDED.values()
        } == targets.SEEDED_ORIGINS
        plaintext = {o for o in targets.SEEDED_ORIGINS if o.startswith("http://")}
        assert len(plaintext) == 3


class TestARowCannotCarryQueryStructure:
    """`__post_init__` is where an invariant that ties two fields together lives."""

    @pytest.mark.parametrize(
        "index",
        ["num=1 or num", "alma isbn", 'dc."isbn"', "dc.isbn\n", "(num)", "", "1num"],
    )
    def test_an_index_that_is_not_a_name_is_refused(self, index):
        with pytest.raises(ValueError):
            _seeded(isbn_index=index)

    @pytest.mark.parametrize("index", ["num", "WOE", "pica.isb", "alma.isbn", "dc.t_x"])
    def test_an_index_name_is_accepted(self, index):
        assert _seeded(isbn_index=index).isbn_index == index

    @pytest.mark.parametrize(
        "parameter",
        [
            "version",
            "operation",
            "maximumRecords",
            "recordSchema",
            # Case folded, and this arm is the one that was open. A dict key
            # collides only on an exact match, so this displaces nothing in the
            # request we build; a target that reads parameter names case
            # insensitively sees two `recordSchema` values and picks one.
            "RECORDSCHEMA",
            "Version",
        ],
    )
    def test_a_query_parameter_may_not_displace_an_sru_parameter(self, parameter):
        """Otherwise the query replaces the version and no query is sent."""
        with pytest.raises(ValueError):
            _seeded(query_parameter=parameter)

    def test_the_parameter_the_roster_uses_is_still_accepted(self):
        """The other half of the diagonal: it must not refuse everything."""
        assert _seeded(query_parameter="query").query_parameter == "query"

    def test_a_float_use_attribute_is_refused(self):
        """`7.0 in {7}` is True, and `z3950.query` refuses a float.

        So membership alone built a row whose query could not be sent, which is
        one rule enforced in two places and disagreeing about it.
        """
        with pytest.raises(ValueError):
            _seeded(
                query_language=targets.QueryLanguage.PQF,
                isbn_index="",
                answers_search=False,
                title_index="",
                title_query_shape=None,
                isbn_attribute=7.0,
            )

    def test_only_the_dnb_may_waive_the_isbn_claim_at_construction(self):
        """The CHECK constraint refuses this and `__post_init__` did not.

        Three statements of one rule, and they have to agree: the dataclass, the
        constraint a restore writes through, and the roster pin above.
        """
        with pytest.raises(ValueError):
            _seeded(requires_isbn_claim=False)
        waived = dataclasses.replace(
            targets.SEEDED[CatalogueSource.DNB], requires_isbn_claim=False
        )
        assert not waived.requires_isbn_claim

    def test_a_use_attribute_this_application_does_not_know_is_refused(self):
        """The column is an integer and SQLite's affinity is a preference."""
        with pytest.raises(ValueError):
            _seeded(
                query_language=targets.QueryLanguage.PQF,
                isbn_index="",
                answers_search=False,
                title_index="",
                title_query_shape=None,
                isbn_attribute="7 @and @attr 1=4 anything",
            )

    def test_the_seeded_use_attribute_is_accepted(self):
        target = _seeded(
            query_language=targets.QueryLanguage.PQF,
            isbn_index="",
            answers_search=False,
            title_index="",
            title_query_shape=None,
            isbn_attribute=z3950.USE_ISBN,
        )
        assert target.isbn_query("9783319522678") == '@attr 1=7 "9783319522678"'

    def test_a_pqf_target_may_not_answer_a_title_search(self):
        """This is what makes `_sru_search` catching only `targets.BadQuery`
        correct: a PQF query cannot be built on the search path at all."""
        with pytest.raises(ValueError):
            _seeded(query_language=targets.QueryLanguage.PQF, isbn_attribute=7)

    def test_there_is_no_z3950_door_yet(self):
        with pytest.raises(ValueError):
            _seeded(transport=targets.Transport.Z3950)

    def test_a_bespoke_row_carries_no_query_grammar(self):
        """An index sitting unused on a row is a row somebody reads as the one
        being asked."""
        with pytest.raises(ValueError):
            targets.Target(
                source=CatalogueSource.OPEN_LIBRARY,
                rank=2,
                transport=targets.Transport.BESPOKE,
                base_url="https://openlibrary.org",
                reader=targets.Reader.OPEN_LIBRARY,
                answers_lookup=True,
                answers_search=True,
                metered=False,
                needs_key=False,
                isbn_index="dc.isbn",
            )

    def test_a_marc_knob_on_a_reader_that_reads_no_marc_is_refused(self):
        with pytest.raises(ValueError):
            _seeded(
                reader=targets.Reader.MODS,
                answers_lookup=False,
                isbn_index="",
                refuses_component_parts=True,
            )

    def test_a_lookup_that_asks_for_no_records_is_refused(self):
        with pytest.raises(ValueError):
            _seeded(lookup_records=0)


class TestTheQueryIsBuiltHereAndNowhereElse:
    """`cql_term` and `z3950.pqf_term` are the only two doors a value goes through."""

    @pytest.mark.parametrize(
        "value",
        ['a"b', "a=b", "a<b", "a(b", "a)b", "a/b", "a\\b", "a b", "a\x00b", "", "a\nb"],
    )
    def test_a_value_that_is_not_a_term_is_refused(self, value):
        with pytest.raises(targets.BadQuery):
            targets.cql_term(value)

    @pytest.mark.parametrize("value", ["a*b", "a?b", "a^b", "*", "??"])
    def test_cqls_masking_characters_are_refused(self, value):
        """`*` and `?` mask and `^` anchors, inside a quoted phrase as well, so a
        term carrying one is a wildcard rather than a word."""
        with pytest.raises(targets.BadQuery):
            targets.cql_term(value)

    def test_a_phrase_refuses_a_term_before_the_quotes_are_added(self):
        with pytest.raises(targets.BadQuery):
            targets.cql_phrase(["moby", 'dick"'])

    def test_the_seeded_lookup_queries_are_what_the_adapters_built(self):
        """Byte for byte against the five constants this ticket deleted."""
        isbn = "9783825354077"
        assert {
            source.value: targets.SEEDED[source].isbn_query(isbn)
            for source in targets.SEEDED
            if targets.SEEDED[source].transport is targets.Transport.SRU
            and targets.SEEDED[source].answers_lookup
        } == {
            "dnb": f"num={isbn}",
            "k10plus": f"pica.isb={isbn}",
            "oenb": f"alma.isbn={isbn}",
            "nlg": f"dc.isbn={isbn}",
            "nkp": f'@attr 1=7 "{isbn}"',
        }

    def test_the_seeded_search_queries_are_what_the_adapters_built(self):
        terms = ["wien", "geschichte"]
        assert {
            source.value: targets.SEEDED[source].title_query(terms)
            for source in targets.SEEDED
            if targets.SEEDED[source].transport is targets.Transport.SRU
            and targets.SEEDED[source].answers_search
        } == {
            "dnb": "WOE=wien geschichte",
            "k10plus": "pica.all=wien and pica.all=geschichte",
            "oenb": "alma.title=wien and alma.title=geschichte",
            "nlg": "dc.title=wien and dc.title=geschichte",
            "bnf": 'bib.anywhere all "wien geschichte"',
            "loc": 'dc.title="wien geschichte"',
        }

    def test_the_request_parameters_are_what_the_adapters_built(self):
        """The whole dict, not only the query: a version or a record schema is as
        able to be wrong as an index."""
        dnb = targets.SEEDED[CatalogueSource.DNB]
        assert dnb.sru_params(dnb.isbn_query("9783825354077"), dnb.lookup_records) == {
            "version": "1.1",
            "operation": "searchRetrieve",
            "query": "num=9783825354077",
            "recordSchema": "MARC21-xml",
            "maximumRecords": "5",
        }
        nkp = targets.SEEDED[CatalogueSource.NKP]
        assert nkp.sru_params(nkp.isbn_query("9783319522678"), nkp.lookup_records) == {
            "version": "1.1",
            "operation": "searchRetrieve",
            "x-pquery": '@attr 1=7 "9783319522678"',
            "maximumRecords": "1",
        }

    def test_a_target_that_takes_no_record_schema_sends_none(self):
        """The NKP answers with its own Dublin Core whatever is asked for."""
        nkp = targets.SEEDED[CatalogueSource.NKP]
        assert "recordSchema" not in nkp.sru_params("x", 1)

    def test_the_search_page_size_is_the_multiplier_under_the_cap(self):
        assert targets.SEEDED[CatalogueSource.DNB].search_records(10) == 30
        assert targets.SEEDED[CatalogueSource.DNB].search_records(100) == 50
        assert targets.SEEDED[CatalogueSource.BNF].search_records(10) == 20


class TestAnAddressThatWillNotParseFailsClosed:
    def test_an_unterminated_ipv6_literal_is_an_empty_origin(self):
        """`urlsplit` raises on it, which is neither `BadQuery` nor an
        `httpx.HTTPError`, so it would escape both of the SRU door's handlers."""
        assert targets.origin("http://[::1/x") == ""
        assert "" not in targets.SEEDED_ORIGINS

    def test_a_credential_in_an_address_is_a_different_origin(self):
        """`netloc` and not `hostname`, which is what refuses this by comparison
        alone: the host a person reads is not the host a client connects to."""
        assert (
            targets.origin("https://services.dnb.de@evil.test/sru/dnb")
            not in targets.SEEDED_ORIGINS
        )


class TestTheIndexPatternIsExact:
    def test_it_is_anchored_at_both_ends_without_a_trailing_newline(self):
        """`$` matches before a trailing newline, so this is `fullmatch`."""
        assert targets._INDEX.fullmatch("alma.isbn")
        assert not targets._INDEX.fullmatch("alma.isbn\n")

    def test_the_pattern_source_names_no_dollar(self):
        """A `$` back in the pattern would restore the newline hole under
        `fullmatch` for a caller that later switched back to `match`."""
        assert "$" not in targets._INDEX.pattern

    def test_every_seeded_index_matches_it(self):
        for target in targets.SEEDED.values():
            for index in (target.isbn_index, target.title_index):
                if index:
                    assert re.fullmatch(targets._INDEX.pattern, index)
