"""Tests for backend/authority.py: the two authority files, read for a person.

**Every fixture below was captured live on 2026-08-27** and then trimmed, and
what was trimmed is worth stating because two of the removals are the point.

| fixture | request it answers |
|---|---|
| `LOBID_RECORD` | `GET lobid.org/gnd/118753711.json` |
| `LOBID_SEARCH` | `GET lobid.org/gnd/search`, `q=Robert Louis Stevenson`, filtered to people |
| `WIKIDATA_ITEM` | `haswbstatement:P227=118753711` |
| `WIKIDATA_NO_ITEM` | `haswbstatement:P227=131572873` |
| `WIKIDATA_DESCRIPTION` | `wbgetentities` for `Q1512`, labels and descriptions only |
| `WIKIDATA_VIAF` | `wbgetclaims` for `Q1512`, property `P214` |

**The pair is the ambiguity in one real example.** `Stevenson, Robert Louis` is
two different people in the GND, `118753711` and `131572873`, and exactly one of
them has a Wikidata item. That is the case the confirmation step exists for, and
it is measured rather than invented.

**What was removed from the lobid fixtures, and why the list matters.** The
`sameAs` entries lost a `collection` object naming the publisher and its icon;
`variantName` was cut to three of eleven; the search kept two members of five
and its `totalItems: 60` as answered. Three fields were dropped that this module
must never read, and they are named here rather than silently absent:
`depiction` is a portrait, `biographicalOrHistoricalInformation` reads "Lebte ab
1888 auf Westsamoa, starb in dem Dorf Vailima, nahe Apia, Samoa", and
`professionOrOccupation` is a body of work. `docs/featurelist.md` refuses all
three, and `TestTheRefusalsAreStructural` is what keeps the refusal from
lapsing.

Two Wikidata fixtures were trimmed as well. `WIKIDATA_VIAF` kept one statement
of one and dropped its references. `WIKIDATA_ITEM` lost its `snippet`, which is
the search index's own highlight markup and is the one field in any of these
captures that this module never looks at.
"""

import ast
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

import authority
from authority import AuthorityUnavailable, resolve, search

LOBID = "https://lobid.org/"
WIKIDATA = "https://www.wikidata.org/w/api.php"


LOBID_RECORD = {
    # The three fields `docs/featurelist.md` refuses, kept **in** the fixture so
    # `TestTheRefusalsAreStructural` has something to prove the parser drops.
    # Live values, trimmed. A fixture without them makes that guard vacuous,
    # which is what it did when it checked a docstring against itself.
    "depiction": [
        {
            "id": "https://commons.wikimedia.org/wiki/Special:FilePath/Robert%20Louis%20Stevenson%20by%20Henry%20Walter%20Barnett%20bw.jpg",
            "thumbnail": "https://commons.wikimedia.org/wiki/Special:FilePath/Robert%20Louis%20Stevenson.jpg?width=200",
        }
    ],
    "biographicalOrHistoricalInformation": [
        "Lebte ab 1888 auf Westsamoa, starb in dem Dorf Vailima, nahe Apia, Samoa"
    ],
    "professionOrOccupation": [
        {"id": "https://d-nb.info/gnd/4053309-8", "label": "Schriftsteller"},
        {"id": "https://d-nb.info/gnd/4028781-6", "label": "Journalist"},
    ],
    "wikipedia": [
        {"id": "https://de.wikipedia.org/wiki/Robert_Louis_Stevenson"}
    ],
    "gndIdentifier": "118753711",
    "preferredName": "Stevenson, Robert Louis",
    "variantName": [
        "Stivenson, Robert L-jus",
        "Stevenson, Louis",
        "Stivenson, Robert Luis"
    ],
    "dateOfBirth": [
        "1850-11-13"
    ],
    "dateOfDeath": [
        "1894-12-03"
    ],
    "sameAs": [
        {
            "id": "http://id.loc.gov/rwo/agents/n78088964"
        },
        {
            "id": "http://viaf.org/viaf/95207986"
        },
        {
            "id": "http://www.wikidata.org/entity/Q1512"
        },
        {
            "id": "https://d-nb.info/gnd/1013016130"
        },
        {
            "id": "https://d-nb.info/gnd/118753711/about"
        },
        {
            "id": "https://dbpedia.org/resource/Robert_Louis_Stevenson"
        },
        {
            "id": "https://de.wikipedia.org/wiki/Robert_Louis_Stevenson"
        },
        {
            "id": "https://de.wikisource.org/wiki/Robert_Louis_Stevenson"
        },
        {
            "id": "https://en.wikipedia.org/wiki/Robert_Louis_Stevenson"
        },
        {
            "id": "https://isni.org/isni/0000000122831567"
        },
        {
            "id": "https://kalliope-verbund.info/gnd/118753711"
        },
        {
            "id": "https://www.archivportal-d.de/person/gnd/118753711"
        },
        {
            "id": "https://www.deutsche-digitale-bibliothek.de/person/gnd/118753711"
        },
        {
            "id": "https://www.filmportal.de/44223F53A5044152B909B583FFA7E11F"
        }
    ],
    "type": [
        "AuthorityResource",
        "Person",
        "DifferentiatedPerson"
    ]
}

LOBID_SEARCH: dict[str, Any] = {
    "totalItems": 60,
    "member": [
        {
            "gndIdentifier": "118753711",
            "preferredName": "Stevenson, Robert Louis",
            "variantName": [
                "Stivenson, Robert L-jus",
                "Stevenson, Louis",
                "Stivenson, Robert Luis"
            ],
            "dateOfBirth": [
                "1850-11-13"
            ],
            "dateOfDeath": [
                "1894-12-03"
            ],
            "sameAs": [
                {
                    "id": "http://id.loc.gov/rwo/agents/n78088964"
                },
                {
                    "id": "http://viaf.org/viaf/95207986"
                },
                {
                    "id": "http://www.wikidata.org/entity/Q1512"
                },
                {
                    "id": "https://d-nb.info/gnd/1013016130"
                },
                {
                    "id": "https://d-nb.info/gnd/118753711/about"
                },
                {
                    "id": "https://dbpedia.org/resource/Robert_Louis_Stevenson"
                },
                {
                    "id": "https://de.wikipedia.org/wiki/Robert_Louis_Stevenson"
                },
                {
                    "id": "https://de.wikisource.org/wiki/Robert_Louis_Stevenson"
                },
                {
                    "id": "https://en.wikipedia.org/wiki/Robert_Louis_Stevenson"
                },
                {
                    "id": "https://isni.org/isni/0000000122831567"
                },
                {
                    "id": "https://kalliope-verbund.info/gnd/118753711"
                },
                {
                    "id": "https://www.archivportal-d.de/person/gnd/118753711"
                },
                {
                    "id": "https://www.deutsche-digitale-bibliothek.de/person/gnd/118753711"
                },
                {
                    "id": "https://www.filmportal.de/44223F53A5044152B909B583FFA7E11F"
                }
            ],
            "type": [
                "AuthorityResource",
                "Person",
                "DifferentiatedPerson"
            ]
        },
        {
            "gndIdentifier": "131572873",
            "preferredName": "Stevenson, Robert Louis",
            "sameAs": [
                {
                    "id": "http://viaf.org/viaf/1148462"
                },
                {
                    "id": "https://d-nb.info/gnd/131572873/about"
                }
            ],
            "type": [
                "Person",
                "AuthorityResource",
                "DifferentiatedPerson"
            ]
        }
    ]
}

WIKIDATA_ITEM = {
    "batchcomplete": "",
    "query": {
        "searchinfo": {
            "totalhits": 1
        },
        "search": [
            {
                "ns": 0,
                "title": "Q1512",
                "pageid": 1967,
                "size": 356850,
                "wordcount": 1396,
                "timestamp": "2026-08-26T15:56:47Z"
            }
        ]
    }
}

WIKIDATA_NO_ITEM = {
    "batchcomplete": "",
    "query": {
        "searchinfo": {
            "totalhits": 0
        },
        "search": []
    }
}

WIKIDATA_DESCRIPTION = {
    "entities": {
        "Q1512": {
            "type": "item",
            "id": "Q1512",
            "labels": {
                "de": {
                    "language": "de",
                    "value": "Robert Louis Stevenson"
                },
                "en": {
                    "language": "en",
                    "value": "Robert Louis Stevenson"
                }
            },
            "descriptions": {
                "de": {
                    "language": "de",
                    "value": "schottischer Schriftsteller"
                },
                "en": {
                    "language": "en",
                    "value": "Scottish novelist and poet (1850–1894)"
                }
            }
        }
    },
    "success": 1
}

WIKIDATA_VIAF = {
    "claims": {
        "P214": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "property": "P214",
                    "datavalue": {
                        "value": "95207986",
                        "type": "string"
                    },
                    "datatype": "external-id"
                },
                "type": "statement",
                "rank": "normal"
            }
        ]
    }
}

def _json(body: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def _wikidata_router(mock, *, item=WIKIDATA_ITEM, description=WIKIDATA_DESCRIPTION,
                     viaf=WIKIDATA_VIAF):
    """Route each Wikidata action to its own answer.

    One route per `action` rather than one catch-all, because the module makes
    three different calls and a catch-all would let a test pass while the module
    asked for the wrong thing.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action")
        if action == "query":
            gnd = request.url.params.get("srsearch", "")
            return _json(item if "118753711" in gnd else WIKIDATA_NO_ITEM)
        if action == "wbgetentities":
            return _json(description)
        if action == "wbgetclaims":
            return _json(viaf)
        return _json({}, 400)

    mock.get(url__startswith=WIKIDATA).mock(side_effect=handler)


class TestResolvingAnIdentifierACatalogueAsserted:
    """The certain route: a GND number is a key, so there is one record."""

    @pytest.mark.asyncio
    async def test_the_authoritys_own_spelling_is_what_comes_back(self):
        """The suggestion the whole feature exists to offer. In catalogue order,
        because that is how the GND writes a name."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock)
            candidate = await resolve("118753711")

        assert candidate is not None
        assert candidate.name == "Stevenson, Robert Louis"
        assert candidate.certain is True

    @pytest.mark.asyncio
    async def test_the_dates_come_from_the_gnd_record_rather_than_wikidata(self):
        """Free, because they are already in the record that was fetched."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock)
            candidate = await resolve("118753711")

        assert candidate is not None
        assert (candidate.born, candidate.died) == ("1850-11-13", "1894-12-03")

    @pytest.mark.asyncio
    async def test_the_viaf_cluster_arrives_without_viaf_being_called(self):
        """`sameAs` is recorded and never followed, which is the whole reason
        VIAF is not a supplier here."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock)
            candidate = await resolve("118753711")

        assert candidate is not None
        assert "http://viaf.org/viaf/95207986" in candidate.same_as
        assert not any(
            "viaf.org" in str(call.request.url) for call in mock.calls
        )

    @pytest.mark.asyncio
    async def test_wikidata_confirms_the_item_independently(self):
        """lobid's `sameAs` says `Q1512` and Wikidata's reverse lookup on `P227`
        says `Q1512`. Neither was told the other's answer, which is what makes a
        disagreement detectable at all."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock)
            candidate = await resolve("118753711")

        assert candidate is not None
        assert candidate.wikidata_id == "Q1512"
        assert candidate.disagreements == ()

    @pytest.mark.asyncio
    async def test_the_one_line_description_is_offered(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock)
            candidate = await resolve("118753711")

        assert candidate is not None
        assert candidate.description is not None
        assert "Scottish novelist" in candidate.description

    @pytest.mark.asyncio
    async def test_a_number_the_file_does_not_hold_is_none_not_an_error(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=httpx.Response(404))
            assert await resolve("999999999") is None

    @pytest.mark.asyncio
    async def test_an_identifier_that_is_not_a_gnd_number_is_never_fetched(self):
        """A path traversal inside lobid, if it reached the URL: httpx percent
        encodes a path segment and does not collapse `..`. A hand edit or a
        restore is how a row like this arrives."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json(LOBID_RECORD)
            )
            assert await resolve("../search?q=x") is None

        assert route.call_count == 0

    @pytest.mark.asyncio
    async def test_lobid_failing_is_reported_rather_than_swallowed(self):
        """lobid is the supplier. An answer that is not there is no answer."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=httpx.Response(500))
            with pytest.raises(AuthorityUnavailable):
                await resolve("118753711")

    @pytest.mark.asyncio
    async def test_wikidata_failing_leaves_the_gnd_answer_standing(self):
        """Wikidata is the cross check rather than the supplier, so an outage
        there costs the description and the cross reference report and nothing
        else."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            mock.get(url__startswith=WIKIDATA).mock(return_value=httpx.Response(503))
            candidate = await resolve("118753711")

        assert candidate is not None
        assert candidate.name == "Stevenson, Robert Louis"
        assert candidate.wikidata_id is None
        assert candidate.description is None


class TestADisagreementIsSurfacedRatherThanResolved:
    """Neither file is the authority on the other, so nothing here picks."""

    @pytest.mark.asyncio
    async def test_two_files_naming_different_items_is_reported(self):
        elsewhere = {
            "query": {"search": [{"title": "Q999999"}]},
        }
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock, item=elsewhere)
            candidate = await resolve("118753711")

        assert candidate is not None
        [row] = [d for d in candidate.disagreements if d.about == "wikidata"]
        assert (row.lobid, row.wikidata) == ("Q1512", "Q999999")
        # Reported, not resolved: both are still on the record.
        assert candidate.wikidata_id == "Q999999"

    @pytest.mark.asyncio
    async def test_two_files_naming_different_viaf_clusters_is_reported(self):
        other = {
            "claims": {
                "P214": [
                    {
                        "mainsnak": {
                            "snaktype": "value",
                            "property": "P214",
                            "datavalue": {"value": "11111111", "type": "string"},
                            "datatype": "external-id",
                        },
                        "type": "statement",
                        "rank": "normal",
                    }
                ]
            }
        }
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock, viaf=other)
            candidate = await resolve("118753711")

        assert candidate is not None
        [row] = [d for d in candidate.disagreements if d.about == "viaf"]
        assert (row.lobid, row.wikidata) == ("95207986", "11111111")

    @pytest.mark.asyncio
    async def test_one_file_being_silent_is_not_a_disagreement(self):
        """Wikidata holding no item is the ordinary case for a minor author.
        Reporting it as a conflict would bury the real ones."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(mock, item=WIKIDATA_NO_ITEM)
            candidate = await resolve("118753711")

        assert candidate is not None
        assert candidate.disagreements == ()


class TestSearchingByName:
    """The uncertain route. A name is not a key, and here is the proof."""

    @pytest.mark.asyncio
    async def test_one_name_returns_two_different_people(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_SEARCH))
            _wikidata_router(mock)
            found = await search("Robert Louis Stevenson")

        assert [row.identifier for row in found] == ["118753711", "131572873"]
        assert all(row.name == "Stevenson, Robert Louis" for row in found)

    @pytest.mark.asyncio
    async def test_nothing_from_a_search_is_certain(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_SEARCH))
            _wikidata_router(mock)
            found = await search("Robert Louis Stevenson")

        assert not any(row.certain for row in found)

    @pytest.mark.asyncio
    async def test_only_one_of_the_two_has_a_wikidata_item(self):
        """The disambiguation signal, and the reason it is shown rather than
        acted on: "the one with an item wins" is the silent merge the
        confirmation step exists to prevent."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_SEARCH))
            _wikidata_router(mock)
            found = await search("Robert Louis Stevenson")

        assert [row.wikidata_id for row in found] == ["Q1512", None]

    @pytest.mark.asyncio
    async def test_a_search_never_asks_wikidata_for_a_cross_reference(self):
        """Five candidates would otherwise be fifteen requests to two services
        for a list the member is about to narrow to one."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_SEARCH))
            _wikidata_router(mock)
            await search("Robert Louis Stevenson")

        actions = [
            call.request.url.params.get("action")
            for call in mock.calls
            if str(call.request.url).startswith(WIKIDATA)
        ]
        assert "wbgetclaims" not in actions

    @pytest.mark.asyncio
    async def test_the_search_is_narrowed_to_people(self):
        """Without the filter the same query answers with a conference and a
        school ahead of either Stevenson. Measured live 2026-08-27: 117 records
        unfiltered against 60 filtered."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json(LOBID_SEARCH)
            )
            _wikidata_router(mock)
            await search("Robert Louis Stevenson")

        assert route.calls[0].request.url.params["filter"] == (
            "type:DifferentiatedPerson"
        )

    @pytest.mark.asyncio
    async def test_more_rows_than_the_ceiling_are_cut(self):
        """The `size` parameter is a request and the answer is somebody else's,
        so a service ignoring it must not decide how many Wikidata requests one
        member action makes."""
        flood = {
            "member": [
                {
                    "gndIdentifier": str(100000000 + index),
                    "preferredName": f"Person {index}",
                }
                for index in range(authority.MAX_CANDIDATES + 10)
            ]
        }
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(flood))
            _wikidata_router(mock, item=WIKIDATA_NO_ITEM)
            found = await search("anybody")

        assert len(found) == authority.MAX_CANDIDATES

    @pytest.mark.asyncio
    async def test_an_empty_name_asks_nobody_anything(self):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json(LOBID_SEARCH)
            )
            assert await search("   ") == []

        assert route.call_count == 0


class TestTheNameNeverBecomesQuerySyntax:
    """Both halves measured against the live service on 2026-08-27."""

    @pytest.mark.asyncio
    async def test_a_bracket_in_a_name_is_escaped(self):
        """`q=Stevenson (` answers **HTTP 500 with an HTML body**, and a bracket
        in an author's name is ordinary catalogue data. Escaping is mandatory
        here rather than defensive."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json({"member": []})
            )
            await search("Stevenson (")

        assert route.calls[0].request.url.params["q"] == "Stevenson \\("

    @pytest.mark.asyncio
    async def test_a_second_clause_cannot_be_injected(self):
        """Unescaped, `Stevenson" OR preferredName:"Kane` is two clauses and
        changes the result set. Escaped it is three literal terms."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json({"member": []})
            )
            await search('Stevenson" OR preferredName:"Kane')

        sent = route.calls[0].request.url.params["q"]
        assert '"' not in sent.replace('\\"', "")
        assert ":" not in sent.replace("\\:", "")

    @pytest.mark.asyncio
    async def test_a_hyphenated_name_still_matches(self):
        """`-` is Lucene's NOT, so it is escaped, and escaping it changes
        nothing: `Jean\\-Pierre Naugrette` and `Jean-Pierre Naugrette` both
        answer with one record."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json({"member": []})
            )
            await search("Jean-Pierre Naugrette")

        assert route.calls[0].request.url.params["q"] == "Jean\\-Pierre Naugrette"

    @pytest.mark.asyncio
    async def test_a_very_long_name_is_cut_before_it_is_escaped(self):
        """The bound is on what a member sent, not on what escaping made of it:
        escaping can double the length."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json({"member": []})
            )
            await search("(" * 400)

        sent = route.calls[0].request.url.params["q"]
        assert sent == "\\(" * authority.MAX_QUERY_NAME


class TestTheRefusalsAreStructural:
    """`docs/featurelist.md` refuses author biographies and portraits.

    A refusal a reviewer has to remember is a refusal that lapses, and all four
    fields are sitting in a response this module parses.

    **Every guard here was rewritten after being attacked.** The first versions
    were a substring scan that flagged the word `DbSession` in a comment, a
    `props=claims` check that read 74% of the file, and a fixture check that
    asserted a docstring quotes itself. None of that was found by reading.
    """

    @staticmethod
    def _source() -> str:
        return (Path(__file__).resolve().parent.parent / "authority.py").read_text()

    def test_a_portrait_and_a_biography_in_a_record_reach_nothing(self):
        """**Behavioural, not textual.** The fixture carries all four fields with
        their live values; what is asserted is that none of those values appears
        anywhere in the parsed candidate."""
        candidate = authority._candidate(LOBID_RECORD, certain=True)

        assert candidate is not None
        rendered = repr(candidate)
        # One value per refused field, and each is unique to that field.
        #
        # **`wikipedia` is deliberately not in this list**, and finding that out
        # is what this test is for: its value is
        # `de.wikipedia.org/wiki/Robert_Louis_Stevenson`, which lobid **also**
        # lists in `sameAs`, a field that is read on purpose. So the Wikipedia
        # URI is not a distinguishing value and asserting on it would fail for
        # the wrong reason. The refusal of the `wikipedia` *field* is the
        # textual guard below: what it buys is not reading a second copy of a
        # cross reference already held.
        for refused in ("commons.wikimedia.org", "Lebte ab 1888", "Schriftsteller"):
            assert refused not in rendered

    def test_the_fixture_really_carries_what_is_being_refused(self):
        """The guard above is evidence only while the fixture holds the fields.
        Asserted against the fixture itself rather than against prose."""
        for refused in (
            "depiction",
            "biographicalOrHistoricalInformation",
            "professionOrOccupation",
            "wikipedia",
        ):
            assert refused in LOBID_RECORD

    def test_no_field_holding_a_portrait_or_a_biography_is_named_in_the_module(self):
        """The textual half, kept beside the behavioural one: a field this
        module never names cannot be read by a later edit either."""
        source = self._source()
        for refused in (
            "depiction",
            "biographicalOrHistoricalInformation",
            "professionOrOccupation",
            "wikipedia",
        ):
            assert f'"{refused}"' not in source
            assert f"'{refused}'" not in source

    def test_wikidata_is_never_asked_for_every_claim(self):
        """`props=claims` on one well documented person is 243,864 bytes against
        341 for what this module asks for, and it is a body of work rather than
        an identity.

        **An `ast` pass over every call to `_wikidata`**, because the first
        version of this read `source.split("def _claim")[0]` and so checked 74%
        of the file: appending a `props: "claims"` call below `_lobid` survived
        it. Reading the calls rather than the text also catches a `props` added
        to a call that does not spell the word `claims` at all.

        **A call whose arguments are not literal fails rather than being
        skipped**, which is the second hole this had. See the assertion below.

        Boundary, stated rather than left to be found: this reads literals, so a
        `props` value assembled at runtime is outside it. The arms are sized so
        that every ordinary spelling is checked and evading it means
        deliberately hiding a request from a reader.
        """
        tree = ast.parse(self._source())
        allowed = {"labels|descriptions"}
        seen = 0
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_wikidata"
            ):
                continue
            # The request body, which is the first positional argument or the
            # `params` keyword. `deadline` is the second and is a variable by
            # design, so the readability check is scoped to the one argument
            # whose contents this guard exists to read.
            body = next(
                (kw.value for kw in node.keywords if kw.arg == "params"),
                node.args[0] if node.args else None,
            )
            # **A body this pass cannot read fails it.** Skipping the
            # non-literal case was the hole: `params = {..., "props": "claims"}`
            # then `await _wikidata(params)` contributed nothing to `seen`, the
            # compliant call still made the count right, and the whole thing
            # passed. Binding params to a variable first is ordinary Python
            # rather than an evasion, so the honest answer is that the guard no
            # longer holds, not that there is nothing to see.
            assert isinstance(body, ast.Dict), (
                "a `_wikidata` request body this pass cannot read statically: "
                "inline the dict, or widen this guard deliberately"
            )
            for key, value in zip(body.keys, body.values, strict=True):
                # **A key this pass cannot read fails it, exactly as the body
                # does.** `props_key = "props"` then `{..., props_key: "claims"}`
                # left the key an `ast.Name`, so the old `continue` skipped it
                # and `seen == 1` still held from the compliant call. It also
                # covers `**spread`, whose key is `None`.
                assert isinstance(key, ast.Constant), (
                    "a computed key in a `_wikidata` body cannot be checked "
                    "here: inline it, or widen this guard deliberately"
                )
                if key.value != "props":
                    continue
                seen += 1
                assert isinstance(value, ast.Constant), (
                    "a computed `props` cannot be checked here"
                )
                assert value.value in allowed, value.value

        assert seen == 1, f"expected one `props` argument, walked {seen}"

    def test_nothing_here_can_touch_a_database(self):
        """`AuthorityCandidate` is evidence, never a row.

        **The module's whole import set, against an allowlist.** The first
        version was four substrings, `("Session", "models", "db.", "commit()")`,
        and `from database import engine; engine.connect()` contains none of
        them. It also flagged the word `DbSession` inside a comment, which is
        the other failure mode: a substring scan cannot tell code from prose.

        Boundary, stated rather than left to be found: this reads `import` and
        `from ... import` nodes, so `__import__("database")` is outside it,
        being a call on a string. That is deliberate rather than overlooked. The
        allowlist makes every ordinary way of reaching a session a failure, and
        the remaining one requires writing a line whose only purpose is to hide
        an import from a reader.
        """
        imported: set[str] = set()
        for node in ast.walk(ast.parse(self._source())):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        assert imported <= {
            "asyncio",
            "logging",
            "re",
            "time",
            "dataclasses",
            "typing",
            "fetch",
            "enums",
        }, sorted(imported)


class TestUnusableAnswers:
    @pytest.mark.asyncio
    async def test_a_record_with_no_name_is_dropped_rather_than_raised(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(
                return_value=_json({"gndIdentifier": "118753711"})
            )
            assert await resolve("118753711") is None

    @pytest.mark.asyncio
    async def test_one_bad_member_does_not_cost_the_others(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(
                return_value=_json(
                    {
                        "member": [
                            {"preferredName": "No identifier"},
                            LOBID_SEARCH["member"][0],
                        ]
                    }
                )
            )
            _wikidata_router(mock)
            found = await search("anybody")

        assert [row.identifier for row in found] == ["118753711"]

    @pytest.mark.asyncio
    async def test_a_body_that_is_not_json_is_unavailable_rather_than_a_crash(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(
                return_value=httpx.Response(200, text="<!DOCTYPE html>")
            )
            with pytest.raises(AuthorityUnavailable):
                await search("anybody")

    @pytest.mark.asyncio
    async def test_an_item_id_that_is_not_one_is_ignored(self):
        """The title comes back from somebody else's search index and goes into
        a query parameter."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_RECORD))
            _wikidata_router(
                mock, item={"query": {"search": [{"title": "Not an item"}]}}
            )
            candidate = await resolve("118753711")

        assert candidate is not None
        assert candidate.wikidata_id is None


class TestTheFanOutIsBoundedInTimeAsWellAsInCount:
    """A count alone was not enough, and the resolve branch had neither.

    `fetch.get_once` gives every call its own `TIMEOUT_SECONDS` budget when it
    is passed none, so N calls in one handler were N fresh budgets. The route
    holds a `DbSession` across all of them.
    """

    @pytest.mark.asyncio
    async def test_one_deadline_covers_every_request_a_lookup_makes(self):
        """Passed through, not re-derived per call: the same absolute value has
        to reach lobid and all three Wikidata calls, or the bound is per request
        again."""
        seen: list[float | None] = []

        async def record(url, *, params=None, limit=None, deadline=None):
            seen.append(deadline)
            body = LOBID_RECORD if "lobid" in url else WIKIDATA_ITEM
            return httpx.Response(200, json=body)

        with respx.mock(assert_all_called=False):
            import fetch

            original = fetch.get_once
            fetch.get_once = record
            try:
                await resolve("118753711", deadline=1234.5)
            finally:
                fetch.get_once = original

        assert seen, "no request was made"
        assert set(seen) == {1234.5}

    @pytest.mark.asyncio
    async def test_a_deadline_already_past_costs_the_lookup_not_the_process(self):
        """`fetch.get` raises `DeadlineExceeded` before opening a connection, and
        lobid failing is `AuthorityUnavailable` rather than a 500."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=LOBID).mock(
                return_value=_json(LOBID_RECORD)
            )
            with pytest.raises(AuthorityUnavailable):
                await search("Stevenson", deadline=time.monotonic() - 1)

        assert route.call_count == 0

    def test_the_deadline_is_absolute_rather_than_a_duration(self):
        """`fetch.get` compares it against `time.monotonic()`, so a duration
        passed here would be a deadline in 1970 and every lookup would fail."""
        before = time.monotonic()
        value = authority.deadline_from_now()

        assert before < value <= time.monotonic() + authority.DEADLINE_SECONDS


class TestACrossReferenceIsOnlyEverAWebLink:
    def test_a_scheme_that_is_not_http_is_dropped(self):
        """Nothing renders `same_as` yet and the obvious rendering is a link, so
        the scheme is checked while the contract is being frozen rather than
        after a client is built against it."""
        record = dict(LOBID_RECORD)
        record["sameAs"] = [
            {"id": "javascript:alert(1)"},
            {"id": "data:text/html,<script>"},
            {"id": "http://viaf.org/viaf/95207986"},
            {"id": "https://isni.org/isni/0000000122831567"},
        ]

        candidate = authority._candidate(record, certain=True)

        assert candidate is not None
        assert candidate.same_as == (
            "http://viaf.org/viaf/95207986",
            "https://isni.org/isni/0000000122831567",
        )
