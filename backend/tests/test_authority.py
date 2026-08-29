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
import asyncio
import json as jsonlib
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx

import authority
from authority import AuthorityUnavailable, resolve, search
from enums import AuthorityScheme

LOBID = "https://lobid.org/"
WIKIDATA = "https://www.wikidata.org/w/api.php"
VIAF = "https://viaf.org/"

#: The six VIAF source codes this app stores, spelled as VIAF spells them.
#: Written out rather than read from the module, so a test asserting the parser
#: found them is not asserting the module agrees with itself.
_NATIONAL_CODES = ("BLBNB", "ARBABN", "BNE", "PTBNP", "ICCU", "BNCHL")

#: Every code **the fixtures in this file carry**, which is not every code.
#:
#: Named for what it is after the first name, `_CODES_THE_FIXTURES_CARRY`, said something
#: false: it is an enumerated list of these fixtures' codes, and `_viaf_sources`
#: takes an allowlist, so a code absent from here is invisible to the parser
#: tests whatever VIAF sends.
#:
#: Wider than production's `_WANTED_SOURCES`, on purpose: these tests are about
#: the shapes VIAF writes, and the fixtures carry `WKP`, `ISNI`, `LNL` and `LIH`
#: precisely because those are the blocks where the list-or-string trap and the
#: embedded separator live. Production's narrower set is what
#: `TestTheParserIsAskedForABoundedSetOfCodes` is for.
_CODES_THE_FIXTURES_CARRY = frozenset(
    _NATIONAL_CODES + ("DNB", "LC", "SUDOC", "WKP", "ISNI", "LNL", "EGAXA", "LIH")
)


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

#: `wbgetclaims` for `Q1512`, property `P213`. Captured in the same shape as
#: `WIKIDATA_VIAF` and agreeing with lobid's `sameAs`, which carries
#: `isni.org/isni/0000000122831567`.
WIKIDATA_ISNI = {
    "claims": {
        "P213": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "property": "P213",
                    "datavalue": {
                        "value": "0000000122831567",
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


#: The largest unfiltered `wbgetentities&props=sitelinks/urls` entity sampled.
#:
#: `Q692`, Shakespeare, measured live 2026-08-28 with `accept-encoding:
#: identity`: **64,449 bytes over 336 sitelinks**, about 192 bytes each. The
#: most linked author on Wikidata, so it is the right end of this route's
#: population rather than an invented worst case.
#:
#: **Named "largest sampled" rather than "worst"**, which is the correction the
#: constant it pins also carries: a sample is not a bound, and an earlier
#: version of both cited `_VIAF_LIMIT`'s lesson about a margin set from a sample
#: while setting one from six entities that did not include this one.
_LARGEST_SAMPLED_ENTITY = 64_449


#: The six national properties on `Q1512`, in the shape `WIKIDATA_VIAF` was
#: captured in.
#:
#: **The values are live, measured 2026-08-28** with
#: `action=wbgetclaims&entity=Q1512&property=<p>`, one claim each, 281 to 524
#: bytes. The envelope is built rather than pasted six times because it is the
#: identical envelope `WIKIDATA_VIAF` carries; what is captured is the numbers,
#: and the numbers are what these tests turn on.
#:
#: **Two of them disagree with `VIAF_BRIEF` on purpose**, and that is the
#: measurement `docs/decisions.md` records: BNE and BNCHL are each one library's
#: old control number against its new one. It is what makes
#: `TestWikidataIsAFallbackAndNotAComparator` a real test rather than one that
#: cannot tell the two suppliers apart.
WIKIDATA_NATIONAL_VALUES = {
    "P4619": "000560463",   # BLBNB, agrees with the cluster
    "P3788": "000035867",   # ARBABN, agrees
    "P950": "XX900250",     # BNE, cluster says 981060880923108606
    "P1005": "27012",       # PTBNP, agrees
    "P396": "CFIV000439",   # ICCU, agrees
    "P1890": "000034753",   # BNCHL, cluster says 10000000000000000007303
}


def _claims_body(prop: str, *values: str, rank: str = "normal") -> dict:
    """A `wbgetclaims` body for one property, in the captured envelope.

    `rank` applies to every statement, which is enough for the two shapes the
    tests need: several values at one rank, and one value that is deprecated.
    """
    return {
        "claims": {
            prop: [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "property": prop,
                        "datavalue": {"value": value, "type": "string"},
                        "datatype": "external-id",
                    },
                    "type": "statement",
                    "rank": rank,
                }
                for value in values
            ]
        }
    }


WIKIDATA_NATIONAL = {
    prop: _claims_body(prop, value)
    for prop, value in WIKIDATA_NATIONAL_VALUES.items()
}


def _json(body: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def _wikidata_router(mock, *, item=WIKIDATA_ITEM, description=WIKIDATA_DESCRIPTION,
                     viaf=WIKIDATA_VIAF, isni=WIKIDATA_ISNI, national=None):
    """Route each Wikidata action to its own answer.

    One route per `action` rather than one catch-all, because the module makes
    four different calls and a catch-all would let a test pass while the module
    asked for the wrong thing.

    **`wbgetclaims` is split on `property` for the same reason**, and it is not
    hypothetical: while every `wbgetclaims` answered `WIKIDATA_VIAF`, a request
    for `P213` came back with a body holding only `P214`, `_claim` found nothing
    and returned None, and the ISNI comparison could not fire in any test. It
    would have looked like agreement.

    `national` is that split carried to the six fallback properties, and it is
    **None by default rather than `WIKIDATA_NATIONAL`**: a test that has not
    asked for the fallback should not be able to pass because the router
    silently supplied it. Without it a national property falls through to
    `viaf`, whose body holds `P214` and therefore answers nothing, which is what
    every test written before the fallback existed already expected.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action")
        if action == "query":
            gnd = request.url.params.get("srsearch", "")
            return _json(item if "118753711" in gnd else WIKIDATA_NO_ITEM)
        if action == "wbgetentities":
            return _json(description)
        if action == "wbgetclaims":
            prop = request.url.params.get("property")
            if national is not None and prop in national:
                return _json(national[prop])
            return _json(isni if prop == "P213" else viaf)
        return _json({}, 400)

    mock.get(url__startswith=WIKIDATA).mock(side_effect=handler)


def _national_asks(mock) -> list[str]:
    """Which of the six national properties Wikidata was asked for.

    The evidence for "one supplier speaks at a time": a comparator asks for
    these on a confirmation VIAF answered, and a fallback does not.
    """
    return [
        prop
        for call in mock.calls
        if str(call.request.url).startswith(WIKIDATA)
        and (prop := call.request.url.params.get("property")) in WIKIDATA_NATIONAL_VALUES
    ]


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

        ## The allowlist was widened on 2026-08-28, deliberately, and this is the record

        It held `labels|descriptions` alone and now holds `sitelinks/urls` too,
        for #89's outward Wikipedia link. **That is a budget decision and not
        the refusal**, and the two are worth keeping apart because a reader
        arriving here will wonder:

        * the **refusal** is `docs/featurelist.md`'s "no author biographies or
          portraits", and it is pinned by the three tests above this one, on
          `depiction`, `biographicalOrHistoricalInformation` and
          `professionOrOccupation`. None of them is touched. The boundary the
          owner drew, recorded in `docs/decisions.md`: a list of which language
          editions exist is data about availability, and an article extract is
          the thing the refusal exists to prevent.
        * **this** test is the budget, and what it refuses by name is `claims`,
          which is still refused.

        The number it costs is measured rather than waved at: `sitelinks/urls`
        for `Q1512` is **354 bytes** with a `sitefilter` and 32,571 without,
        against 243,864 for `claims`. So the widening admits a request three
        orders of magnitude smaller than the one this guard exists to stop.

        **`seen` is three rather than two**, because `_sitelinks` spells its
        filtered and unfiltered calls out separately instead of building one
        dict, which is this guard's own rule applied rather than worked around.

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
        allowed = {"labels|descriptions", "sitelinks/urls"}
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

        assert seen == 3, f"expected three `props` arguments, walked {seen}"

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


#: `GET viaf.org/viaf/search?query=local.viafID = 95207986&recordSchema=BriefVIAF`,
#: captured live 2026-08-28 at 27,536 bytes and trimmed to four heading blocks.
#:
#: **Trimmed and not invented.** Four blocks of eleven are kept. The first's
#: `v:sid` was 37 entries and keeps 9: the DNB number, all six national files,
#: and `LC` and `SUDOC` as codes this app deliberately does not store. Of the
#: three below it, **two carry `v:sid` as a bare string** and the third carries
#: a two entry list, which is the trap: that is how VIAF writes a heading with
#: one source, in the same record where the first block writes a list.
#:
#: Counted from the fixture on 2026-08-28 rather than from the sentence this
#: replaces, which said "the two kept below it" and there were three.
#:
#: The cluster is Stevenson's, so `DNB|118753711` matches `LOBID_RECORD` and the
#: round trip these tests turn on is a real one rather than a fixture agreeing
#: with itself.
VIAF_BRIEF: dict[str, Any] = {
    "searchRetrieveResponse": {
        "numberOfRecords": {"xsi:type": "xsd:nonNegativeInteger", "content": 1},
        "records": {
            "record": {
                "recordSchema": {
                    "xsi:type": "xsd:string",
                    "content": "http://viaf.org/BriefVIAFCluster",
                },
                "recordData": {
                    "v:VIAFCluster": {
                        "v:viafID": "95207986",
                        "v:nameType": "Personal",
                        "v:mainHeadings": {
                            "v:data": [
                                {
                                    "v:text": "Stevenson, Robert Louis, 1850-1894.",
                                    "v:sources": {
                                        "v:sid": [
                                            "DNB|118753711",
                                            "LC|n  78088964",
                                            "SUDOC|027149102",
                                            "BNCHL|10000000000000000007303",
                                            "ARBABN|000035867",
                                            "BNE|981060880923108606",
                                            "PTBNP|27012",
                                            "ICCU|CFIV000439",
                                            "BLBNB|000560463",
                                        ],
                                        "v:s": [
                                            "DNB",
                                            "LC",
                                            "SUDOC",
                                            "BNCHL",
                                            "ARBABN",
                                            "BNE",
                                            "PTBNP",
                                            "ICCU",
                                            "BLBNB",
                                        ],
                                    },
                                },
                                {
                                    "v:text": "Robert Louis Stevenson",
                                    "v:sources": {"v:sid": "WKP|Q1512", "v:s": "WKP"},
                                },
                                {
                                    "v:text": "\u0420\u043e\u0431\u0435\u0440\u0442",
                                    "v:sources": {
                                        "v:sid": "ISNI|0000000122831567",
                                        "v:s": "ISNI",
                                    },
                                },
                                {
                                    "v:text": "Stevenson, R. L.",
                                    "v:sources": {
                                        "v:sid": ["EGAXA|vtls959321", "LNL|12963"],
                                        "v:s": ["EGAXA", "LNL"],
                                    },
                                },
                            ]
                        },
                    }
                },
            }
        },
    }
}

#: `GET viaf.org/viaf/56585930`, captured live 2026-08-28 at 185,459 bytes and
#: trimmed to **three** heading blocks of eight: a seven entry list, a bare
#: string, and a two entry list. Counted from the fixture; this said four.
#:
#: **The point of keeping it is the prefix.** The bare record serves `ns1:`
#: where the SRU wrapper serves `v:`, and the cluster sits at the top level
#: rather than under `searchRetrieveResponse`. Everything below `mainHeadings`
#: is otherwise identical, which is why one prefix insensitive walk reads both:
#: measured on cluster 56585930, the SRU headings, these headings and the bare
#: record's own top level `sources` list gave the identical 34 source codes.
#:
#: This is the cluster the plan measured a deterministic HTTP 500 on through
#: `BriefVIAF`, so it is the record the fallback exists for. Its `DNB` is
#: 118508873, which is **not** `LOBID_RECORD`'s, and that is deliberate: two
#: tests below need a cluster that fails the round trip.
VIAF_BARE: dict[str, Any] = {
    "ns1:VIAFCluster": {
        "ns1:viafID": "56585930",
        "ns1:nameType": "Personal",
        "ns1:mainHeadings": {
            "ns1:data": [
                {
                    "ns1:text": "Benedetti, M\u00e1rio, 1920-2009.",
                    "ns1:sources": {
                        "ns1:sid": [
                            "BLBNB|000612368",
                            "ICCU|CFIV101271",
                            "BNE|981060876756508606",
                            "BNCHL|10000000000000000007624",
                            "PTBNP|45871",
                            "ARBABN|000035749",
                            "DNB|118508873",
                        ],
                        "ns1:s": [
                            "BLBNB",
                            "ICCU",
                            "BNE",
                            "BNCHL",
                            "PTBNP",
                            "ARBABN",
                            "DNB",
                        ],
                    },
                },
                {"ns1:sources": {"ns1:s": "SUDOC", "ns1:sid": "SUDOC|02671745X"}},
                {
                    "ns1:sources": {
                        "ns1:s": ["LNB", "ISNI"],
                        "ns1:sid": ["LNB|LNC10-000040318", "ISNI|0000000121339503"],
                    }
                },
            ]
        },
    }
}

#: `GET viaf.org/viaf/AutoSuggest?query=Mario Benedetti`, captured live
#: 2026-08-28 at 2,492 bytes, four of ten results kept.
#:
#: **Three different men and one work.** The top ranked hit is `dnb` 118508873
#: and the second is 123000327, so a route that took rank 0 would store the
#: 1920-2009 Uruguayan's national identifiers under a different author.
#: `uniformtitlework` is kept because that is what `nametype` exists to exclude.
VIAF_AUTOSUGGEST: dict[str, Any] = {
    "query": "Mario Benedetti",
    "result": [
        {
            "term": "M\u00e1rio Benedetti, 1920-2009",
            "nametype": "personal",
            "lc": "n50007687",
            "dnb": "118508873",
            "viafid": "56585930",
            "score": "9454",
        },
        {
            "term": "Mario Benedetti, 1938-",
            "nametype": "personal",
            "lc": "n92115500",
            "dnb": "123000327",
            "viafid": "27967576",
            "score": "1361",
        },
        {
            "term": "Mario Benedetti, 1955-2020",
            "nametype": "personal",
            "lc": "nr95015672",
            "dnb": "1167553616",
            "viafid": "39663959",
            "score": "1334",
        },
        {
            "term": "Mario Benedetti, 1920-2009. | Works. 1993",
            "nametype": "uniformtitlework",
            "lc": "no95006906",
            "viafid": "309530334",
            "score": "1011",
        },
    ],
}

#: The Stevenson candidate as `resolve` builds it, without going near a network.
#:
#: Built from `LOBID_RECORD` through the module's own parser rather than typed
#: out, so a change to `_candidate` cannot leave these tests asserting against a
#: candidate the module no longer produces.
def _certain_candidate(**overrides):
    candidate = authority._candidate(LOBID_RECORD, certain=True)
    assert candidate is not None
    return replace(candidate, **overrides) if overrides else candidate


def _fetched(body: object, status: int = 200) -> Any:
    """A `fetch.Fetched` carrying JSON, for the tests that patch the transport.

    Built rather than imported as a mock, because `_viaf_json` calls `.json()`
    on it and reads `.status_code`: a `Mock` would satisfy both without either
    meaning anything.
    """
    import fetch

    return fetch.Fetched(status, b"" if body is None else jsonlib.dumps(body).encode(), None)


@contextmanager
def _patched_fetch_get(replacement):
    """Swap `fetch.get`, which is what the VIAF calls go through.

    `fetch.get_once` is what the lobid and Wikidata tests patch, and patching it
    here would exercise nothing: see `TestOneDeadlineCoversTheViafCallsToo`.
    """
    import fetch

    original = fetch.get
    fetch.get = replacement
    try:
        yield
    finally:
        fetch.get = original


def _viaf_router(mock, *, brief=VIAF_BRIEF, bare=VIAF_BARE, suggest=VIAF_AUTOSUGGEST,
                 brief_status=200):
    """Route each of VIAF's three endpoints to its own answer.

    One route per endpoint rather than one catch-all, for the reason
    `_wikidata_router` gives: the module makes three different calls and a
    catch-all lets a test pass while the module asks for the wrong one.

    `brief_status` is how the 5xx fallback is exercised. VIAF's own body on that
    failure is XML rather than JSON, which is why the failing answer is text.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/AutoSuggest"):
            return _json(suggest)
        if path.endswith("/search"):
            if brief_status != 200:
                return httpx.Response(
                    brief_status,
                    text="Missing ';' in XML entity: & at 22365 [character 32 line 1012]",
                )
            return _json(brief)
        return _json(bare)

    mock.get(url__startswith=VIAF).mock(side_effect=handler)


class TestTheNationalIdentifiersAGndRecordDoesNotCarry:
    """The half of the cross references that costs a request.

    A GND record's `sameAs` carries ISNI, LCNAF, VIAF and Wikidata and no
    national library number at all. The VIAF cluster it names carries six.
    """

    @pytest.mark.asyncio
    async def test_the_six_national_schemes_come_back_from_the_cluster(self):
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            found = await authority.national_identifiers(_certain_candidate())

        assert found == {
            AuthorityScheme.BLBNB: "000560463",
            AuthorityScheme.ARBABN: "000035867",
            AuthorityScheme.BNE: "981060880923108606",
            AuthorityScheme.PTBNP: "27012",
            AuthorityScheme.ICCU: "CFIV000439",
            AuthorityScheme.BNCHL: "10000000000000000007303",
        }

    @pytest.mark.asyncio
    async def test_a_code_this_app_does_not_store_is_left_where_it_is(self):
        """`LC` and `SUDOC` are in the fixture on purpose. The first is already
        stored as `lcnaf` from lobid's own `sameAs` and must not arrive twice
        under a second spelling; the second is a French union catalogue nobody
        asked for, and adding it is a migration."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            found = await authority.national_identifiers(_certain_candidate())

        assert "n  78088964" not in found.values()
        assert "027149102" not in found.values()

    @pytest.mark.asyncio
    async def test_the_viaf_cluster_id_is_never_returned_as_an_identity(self):
        """VIAF is a discovery route. Its cluster ids split and merge, and #87
        measured one name resolving to four of them, so what is stored as
        `viaf` comes from lobid cross checked against Wikidata's `P214`, never
        from VIAF's own answer."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            found = await authority.national_identifiers(_certain_candidate())

        assert AuthorityScheme.VIAF not in found
        assert "95207986" not in found.values()

    @pytest.mark.asyncio
    async def test_nothing_is_asked_of_viaf_when_the_record_already_names_a_cluster(self):
        """`AutoSuggest` is the fallback, not the entry point: lobid's `sameAs`
        already carries the cluster id, and asking by name would put a guess
        where a key was."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            await authority.national_identifiers(_certain_candidate())
            asked = [call.request.url.path for call in mock.calls]

        assert asked
        assert not any(path.endswith("/AutoSuggest") for path in asked)


class TestTheClusterIsVerifiedRatherThanTrusted:
    """A cluster names the GND record it was built from, as `DNB|118753711`.

    So it is checked against the identifier the Member confirmed, in the same
    both directions way lobid and Wikidata are checked against each other.
    """

    @pytest.mark.asyncio
    async def test_a_cluster_naming_a_different_gnd_record_stores_nothing(self):
        """The fixture is a real one: `VIAF_BARE` is Mario Benedetti and its
        `DNB` is 118508873, so pointing Stevenson's candidate at it is the
        wrong person arriving with six plausible looking numbers."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief=VIAF_BARE)
            found = await authority.national_identifiers(_certain_candidate())

        assert found == {}

    @pytest.mark.asyncio
    async def test_a_cluster_naming_two_gnd_records_stores_nothing(self):
        """A merged cluster fails the check by construction, because a code the
        cluster names twice is dropped rather than picked from."""
        doubled = deepcopy(VIAF_BRIEF)
        block = doubled["searchRetrieveResponse"]["records"]["record"]["recordData"][
            "v:VIAFCluster"
        ]["v:mainHeadings"]["v:data"][0]
        block["v:sources"]["v:sid"].append("DNB|131572873")

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief=doubled)
            found = await authority.national_identifiers(_certain_candidate())

        assert found == {}

    def test_a_file_listed_twice_is_dropped_rather_than_picked_from(self):
        """One level down from the test above, and the reason it works. Cluster
        41844581 carries two `BNCHL` numbers for Onetti; `author_identifiers`
        holds one row per scheme, so keeping the first would decide by ordering
        which record the Chilean library means."""
        doubled = deepcopy(VIAF_BRIEF)
        cluster = doubled["searchRetrieveResponse"]["records"]["record"]["recordData"][
            "v:VIAFCluster"
        ]
        cluster["v:mainHeadings"]["v:data"][0]["v:sources"]["v:sid"].append(
            "BNCHL|10000000000000000853494"
        )
        sources = authority._viaf_sources(authority._viaf_cluster_record(doubled), _CODES_THE_FIXTURES_CARRY)

        assert "BNCHL" not in sources
        assert sources["DNB"] == "118753711"

    @pytest.mark.asyncio
    async def test_a_contested_cluster_is_not_settled_by_asking_viaf(self):
        """lobid and Wikidata disagreeing about which cluster this is means the
        cluster is not known, and asking VIAF which of the two is right is
        adjudication by a third party. `cross_references` omits a contested
        scheme for the same reason."""
        contested = _certain_candidate(
            disagreements=(
                authority.Disagreement(
                    about=AuthorityScheme.VIAF.value,
                    lobid="95207986",
                    wikidata="12345678",
                ),
            )
        )
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            found = await authority.national_identifiers(contested)
            asked = list(mock.calls)

        assert found == {}
        assert not asked

    @pytest.mark.asyncio
    async def test_a_candidate_a_name_search_produced_is_never_enriched(self):
        """A search candidate buys no comparison, so nothing may be written from
        one. This is the caller that makes outbound requests per candidate, so
        it is enforced here rather than documented: five candidates would
        otherwise be fifteen VIAF requests for a list about to be narrowed to
        one."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            found = await authority.national_identifiers(_certain_candidate(certain=False))
            asked = list(mock.calls)

        assert found == {}
        assert not asked


class TestTheClusterIsFoundByKeyWhenLobidNamesNone:
    """7 of 49 lobid person records carry no VIAF URI, and one is Italo Calvino.

    Sampled 2026-08-28 over twenty Romance, Latin American and contemporary
    authors, top three hits each.
    """

    @staticmethod
    def _no_cluster():
        return _certain_candidate(
            name="Benedetti, Mario",
            identifier="123000327",
            same_as=tuple(
                uri
                for uri in _certain_candidate().same_as
                if not uri.startswith("http://viaf.org/")
            ),
        )

    @pytest.mark.asyncio
    async def test_the_hit_is_chosen_on_the_confirmed_gnd_and_not_on_the_name(self):
        """`AutoSuggest` returns three different Mario Benedettis. The top
        ranked one is `dnb` 118508873 and the confirmed record is 123000327, so
        a rank based choice stores another man's identifiers."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief=VIAF_BARE)
            await authority.national_identifiers(self._no_cluster())
            queried = [
                call.request.url.params.get("query")
                for call in mock.calls
                if call.request.url.path.endswith("/search")
            ]

        assert queried == ["local.viafID = 27967576"]

    @pytest.mark.asyncio
    async def test_a_hit_with_an_unusable_cluster_id_is_ambiguity_not_a_skip(self):
        """`if not isinstance(cluster, str): return None`, which had no guard.

        **This is the sentence added when the exactly-one rule was written,
        going unenforced**: a second hit carrying an unusable id still counts as
        ambiguity, and discarding it first would let a bad value silently
        promote a single survivor. Mutating that `return None` to `continue`
        passed 166, exit 0.

        Two `personal` hits carry the confirmed `dnb` here. The **first** has no
        usable `viafid`, so the refusal is what stops the walk; skipping it
        instead leaves exactly one survivor, which the rule below then accepts
        and fetches. That is the whole difference between the two worlds, and it
        is visible only in the requests: both return `{}`.

        It isolates. The `nametype` filter is untouched by this fixture (the
        work hit carries no `dnb`), and the exactly-one rule below is never
        reached on the real code, because the refusal returns before `matched`
        holds anything.
        """
        unusable = deepcopy(VIAF_AUTOSUGGEST)
        unusable["result"][1]["viafid"] = None
        unusable["result"][2]["dnb"] = "123000327"
        # `.get`, because the work hit carries no `dnb` at all: `hit["dnb"]`
        # here raised `KeyError`, the test failed on the real code **and** on
        # the mutant with the same name, and the harness scored the mutation
        # "caught" on an unrelated error. A count says something failed; only
        # the reason says the guard did the noticing.
        assert [hit.get("dnb") for hit in unusable["result"]].count("123000327") == 2

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, suggest=unusable)
            found = await authority.national_identifiers(self._no_cluster())
            paths = [call.request.url.path for call in mock.calls]

        assert found == {}
        assert paths == ["/viaf/AutoSuggest"]

    @pytest.mark.asyncio
    async def test_a_work_cluster_is_never_taken_for_a_person(self):
        """The same query returns `uniformtitlework` clusters, which are books
        rather than people. That is the confusion `_PERSON_FILTER` prevents on
        the lobid side.

        **The assertion is that no cluster was fetched, not that nothing was
        stored**, and the difference is the whole test: with the filter deleted
        a work's cluster is selected, `/search` answers a `DNB` that fails the
        round trip, and the result is `{}` either way. Asserting on the result
        scored the mutation as caught when it was not, at 67 passed, exit 0.

        **Exactly one hit carries the confirmed `dnb`, and it is the work**,
        which is the second thing this had wrong. The first fixture gave every
        hit that `dnb`, so with the filter deleted four clusters matched, the
        "exactly one hit" rule refused them all, and no `/search` happened for
        a reason that had nothing to do with `nametype`. **That is one guard
        masking another**: the mutation survived at 166 passed. A discriminator
        has to be the only difference between the two worlds, so every personal
        hit here is given a `dnb` nobody is looking for.
        """
        works_only = deepcopy(VIAF_AUTOSUGGEST)
        for hit in works_only["result"]:
            hit["dnb"] = "999999999"
        works_only["result"][3]["dnb"] = "123000327"
        assert works_only["result"][3]["nametype"] == "uniformtitlework"
        assert [hit["dnb"] for hit in works_only["result"]].count("123000327") == 1

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, suggest=works_only)
            found = await authority.national_identifiers(self._no_cluster())
            paths = [call.request.url.path for call in mock.calls]

        assert found == {}
        assert paths == ["/viaf/AutoSuggest"]

    @pytest.mark.asyncio
    async def test_two_clusters_under_one_gnd_number_are_an_ambiguity(self):
        """`_viaf_sources` drops a code a cluster names twice because nothing
        here is entitled to say which. Two hits sharing a `dnb` is the same
        ambiguity from the other end, and picking the first would contradict
        that rule one level up."""
        twins = deepcopy(VIAF_AUTOSUGGEST)
        twins["result"][1]["dnb"] = "123000327"
        twins["result"][2]["dnb"] = "123000327"

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, suggest=twins)
            found = await authority.national_identifiers(self._no_cluster())
            paths = [call.request.url.path for call in mock.calls]

        assert found == {}
        assert paths == ["/viaf/AutoSuggest"]

    @pytest.mark.asyncio
    async def test_two_hits_naming_the_same_cluster_are_not_an_ambiguity(self):
        """The diagonal of the test above: what is refused is two *clusters*,
        not two rows saying the same thing. Without this, "return None on more
        than one hit" would pass just as well as "return None on more than one
        distinct id", and those are different rules."""
        repeated = deepcopy(VIAF_AUTOSUGGEST)
        repeated["result"][2]["dnb"] = "123000327"
        repeated["result"][2]["viafid"] = "27967576"

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief=VIAF_BARE, suggest=repeated)
            await authority.national_identifiers(self._no_cluster())
            queried = [
                call.request.url.params.get("query")
                for call in mock.calls
                if call.request.url.path.endswith("/search")
            ]

        assert queried == ["local.viafID = 27967576"]

    @pytest.mark.asyncio
    async def test_a_cluster_id_that_is_not_one_never_reaches_a_url(self):
        r"""`viafid` comes out of somebody else's response body and is
        interpolated into a URL path, which is the case `_GND_NUMBER`'s own
        guard exists for and the stronger one: httpx will not encode a path
        separator away, so `../search` would be a traversal inside viaf.org.

        Mutating `_VIAF_CLUSTER` to `re.compile(r"\A.*\Z", re.S)` passed 67
        tests before this existed.
        """
        traversal = deepcopy(VIAF_AUTOSUGGEST)
        traversal["result"][1]["viafid"] = "../search?query=x"

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            found = await authority.national_identifiers(self._no_cluster())
            paths = [call.request.url.path for call in mock.calls]

        assert found == {}
        # Sanity: the fixture above is the one that *does* reach a cluster, so
        # this assertion is only meaningful once it has been made to fail.
        assert paths != ["/viaf/AutoSuggest"]

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, suggest=traversal)
            found = await authority.national_identifiers(self._no_cluster())
            paths = [call.request.url.path for call in mock.calls]

        assert found == {}
        assert paths == ["/viaf/AutoSuggest"]

    @pytest.mark.asyncio
    async def test_a_name_no_hit_matches_stores_nothing(self):
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, suggest={"query": "nobody", "result": []})
            found = await authority.national_identifiers(self._no_cluster())

        assert found == {}


class TestTheSruSerialiserFailsOnSomeRecordsAndRetryingIsUseless:
    """A bare `&` in VIAF's data breaks their own SRU XML serialisation.

    Their body names the cause: `Missing ';' in XML entity: & at 22365`. It is a
    property of the record rather than an outage, so the same call answers 500
    every time and the only thing that works is asking for the record in JSON.
    """

    @pytest.mark.asyncio
    async def test_a_5xx_falls_back_to_the_bare_record_and_still_answers(self):
        confirmed = _certain_candidate(identifier="118508873", name="Benedetti, Mario")
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=500)
            found = await authority.national_identifiers(confirmed)
            paths = [call.request.url.path for call in mock.calls]

        assert found[AuthorityScheme.BLBNB] == "000612368"
        assert len(found) == 6
        assert paths[-1] == "/viaf/95207986"

    @pytest.mark.asyncio
    async def test_the_bare_record_is_not_asked_for_when_the_cheap_route_answers(self):
        """It is nine times the bytes: 781,687 against 276,610 at their measured
        worst. A fallback that always runs is not a fallback."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            await authority.national_identifiers(_certain_candidate())
            paths = [call.request.url.path for call in mock.calls]

        assert paths == ["/viaf/search"]

    @pytest.mark.asyncio
    async def test_a_403_is_an_answer_and_is_not_asked_again_nine_times_larger(self):
        """Only a 5xx buys the expensive route. A refusal or a missing record is
        an answer, and repeating it larger would not change it."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            found = await authority.national_identifiers(_certain_candidate())
            paths = [call.request.url.path for call in mock.calls]

        assert found == {}
        assert paths == ["/viaf/search"]

    @pytest.mark.asyncio
    async def test_a_200_carrying_html_is_not_read_as_an_answer(self):
        """The trap this module records is a 200 with 93,813 bytes of Next.js
        page. `fetch.Fetched` carries no headers, so the content type is not
        reachable; decoding as JSON is the stronger check for the same fault."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=VIAF).mock(
                return_value=httpx.Response(200, text="<!DOCTYPE html>")
            )
            found = await authority.national_identifiers(_certain_candidate())

        assert found == {}


class TestBothOfViafsResponseShapesReadTheSame:
    """They differ only by namespace prefix, `v:` against `ns1:`.

    Measured on cluster 56585930: the SRU headings, the bare record's headings
    and the bare record's own top level source list gave the identical 34 codes.
    """

    def test_the_sru_wrapper_and_the_bare_record_are_read_by_one_walk(self):
        brief = authority._viaf_sources(authority._viaf_cluster_record(VIAF_BRIEF), _CODES_THE_FIXTURES_CARRY)
        bare = authority._viaf_sources(authority._viaf_cluster_record(VIAF_BARE), _CODES_THE_FIXTURES_CARRY)

        assert brief["DNB"] == "118753711"
        assert bare["DNB"] == "118508873"
        assert set(_NATIONAL_CODES) <= set(brief)
        assert set(_NATIONAL_CODES) <= set(bare)

    def test_a_bare_string_and_a_list_both_yield_whole_identifiers(self):
        """`v:sid` is a list on a heading with several sources and a bare string
        on a heading with one, **in the same record**.

        **The symptom of iterating the string is absence, not rubbish**, and
        working that out is what this test's assertions are. `"WKP|Q1512"`
        iterated yields `'W'`, `'K'`, `'P'`, `'|'`, ...; every one of those is
        dropped by `_viaf_sources` before the allowlist is consulted, because a
        single character has no separator and `'|'` alone has no code. So no
        junk key can ever appear, and the only observable difference is that
        `WKP` is missing.

        This used to carry `assert all(len(code) > 1 for code in sources)` as a
        second guard. It could not bite under any allowlist and it could not
        bite without one either, for the reason above, so it is gone rather than
        left looking like cover. The three lookups below are the whole guard.
        """
        sources = authority._viaf_sources(
            authority._viaf_cluster_record(VIAF_BRIEF), _CODES_THE_FIXTURES_CARRY
        )

        assert sources["WKP"] == "Q1512"
        assert sources["ISNI"] == "0000000122831567"
        assert sources["LNL"] == "12963"

    def test_an_identifier_carrying_a_separator_of_its_own_survives(self):
        """`LIH|LNB:V-174543;=BK` is one code and one number. `split` on the
        pipe with no bound would be fine; `split(":")` anywhere near this would
        not, which is why the prefix strip and the code split are two steps."""
        record = deepcopy(VIAF_BRIEF)
        record["searchRetrieveResponse"]["records"]["record"]["recordData"][
            "v:VIAFCluster"
        ]["v:mainHeadings"]["v:data"][1]["v:sources"]["v:sid"] = "LIH|LNB:V-174543;=BK"
        sources = authority._viaf_sources(authority._viaf_cluster_record(record), _CODES_THE_FIXTURES_CARRY)

        assert sources["LIH"] == "LNB:V-174543;=BK"

    def test_a_body_in_neither_shape_is_nothing_rather_than_a_crash(self):
        bodies: tuple[Any, ...] = ({}, {"searchRetrieveResponse": {}}, [], "text", None)
        for body in bodies:
            record = authority._viaf_cluster_record(body)

            assert authority._viaf_sources(record, _CODES_THE_FIXTURES_CARRY) == {}


class TestWikidataIsAFallbackAndNotAComparator:
    """The second route to the six national files, settled by the owner
    2026-08-28.

    **One supplier speaks per confirmation.** Wikidata is asked only where VIAF
    produced no cluster record, so the two never both contribute and no
    disagreement between them can arise. That is not a stylistic preference: on
    `Q1512` the two differ on BNE and BNCHL, `cross_references` omits a
    contested scheme, and comparing them would therefore *remove* two of the six
    from storage. `docs/decisions.md` carries the measurement.

    The pair that pins it is `test_the_two_suppliers_are_told_apart_by_the
    _fixtures` plus the two behaviour tests either side of it: without the
    disagreement in the fixtures, a comparator and a fallback would return the
    identical mapping and neither test could tell them apart.
    """

    @staticmethod
    def _confirmable(**overrides):
        """The Stevenson candidate as a confirmation sees it.

        `wikidata_id` is what `_cross_check` sets from Wikidata's own reverse
        lookup on `P227`, and the fallback needs it: `_certain_candidate()`
        comes straight out of the lobid parser and carries None, which is why
        every test written before the fallback existed is untouched by it.
        """
        # Merged rather than passed as a keyword beside `**overrides`, which is
        # a duplicate argument the moment a test wants to override the item id
        # itself. It did, and the failure was a `TypeError` in the test rather
        # than anything about the module.
        return _certain_candidate(**{"wikidata_id": "Q1512", **overrides})

    @staticmethod
    def _no_cluster(**overrides):
        return TestWikidataIsAFallbackAndNotAComparator._confirmable(
            name="Benedetti, Mario",
            identifier="123000327",
            same_as=tuple(
                uri
                for uri in _certain_candidate().same_as
                if not uri.startswith("http://viaf.org/")
            ),
            **overrides,
        )

    def test_the_two_suppliers_are_told_apart_by_the_fixtures(self):
        """The diagonal, and it is what makes the two tests below mean anything.

        Four of the six agree, so asserting on those cannot say which supplier
        answered. BNE and BNCHL are the two that can, and they are the two
        `docs/decisions.md` measured: each is one library's old control number
        against its new one, not a data error.
        """
        cluster = authority._viaf_sources(
            authority._viaf_cluster_record(VIAF_BRIEF), _CODES_THE_FIXTURES_CARRY
        )

        assert cluster["BNE"] != WIKIDATA_NATIONAL_VALUES["P950"]
        assert cluster["BNCHL"] != WIKIDATA_NATIONAL_VALUES["P1890"]
        assert cluster["BLBNB"] == WIKIDATA_NATIONAL_VALUES["P4619"]

    @pytest.mark.asyncio
    async def test_a_cluster_that_answers_costs_no_wikidata_request(self):
        """The comparator test. A change that asks both and compares them fails
        here on the request list, before it fails on any value."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._confirmable())
            asked = _national_asks(mock)

        assert asked == []
        assert found[AuthorityScheme.BNE] == "981060880923108606"
        assert found[AuthorityScheme.BNCHL] == "10000000000000000007303"
        assert len(found) == 6

    @pytest.mark.asyncio
    async def test_viaf_answering_nothing_readable_is_what_buys_the_second_supplier(self):
        """A 403 from the gateway is the outage this exists for: VIAF returned a
        status and no cluster, so there is nothing of VIAF's to overrule."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._confirmable())
            asked = _national_asks(mock)

        assert sorted(asked) == sorted(WIKIDATA_NATIONAL_VALUES)
        assert found == {
            AuthorityScheme.BLBNB: "000560463",
            AuthorityScheme.ARBABN: "000035867",
            AuthorityScheme.BNE: "XX900250",
            AuthorityScheme.PTBNP: "27012",
            AuthorityScheme.ICCU: "CFIV000439",
            AuthorityScheme.BNCHL: "000034753",
        }

    @pytest.mark.asyncio
    async def test_a_200_carrying_html_buys_it_too(self):
        """The other half of "nothing readable": VIAF answered 200 and the body
        was a Next.js page. `_viaf_cluster_sources` returns None for both, which
        is the distinction it was given a nullable return type to make."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=VIAF).mock(
                return_value=httpx.Response(200, text="<!DOCTYPE html>")
            )
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._confirmable())

        assert found[AuthorityScheme.BNE] == "XX900250"

    @pytest.mark.asyncio
    async def test_a_body_that_parses_and_holds_no_cluster_buys_it_too(self):
        """**The gateway case, and it is the one the fallback was asked for.**

        `viaf.org` sits behind Kong, which answers a route it does not know with
        103 bytes of `{"message":"no Route matched with those values"}`. That is
        valid JSON, so `_viaf_json` returns a body and only
        `_viaf_cluster_record` can tell it is not a cluster.

        **Written because a mutation survived without it.** Collapsing
        `_viaf_cluster_sources` to `return _viaf_sources(_viaf_cluster_record(
        body), wanted)` passed 96 tests: every other fixture that reaches the
        parser really does hold a cluster, so the empty mapping and the missing
        answer were never told apart, and the row of `national_identifiers`'
        own table reading "a body that parsed and held no `VIAFCluster`" was
        pinned by nothing.
        """
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(
                mock, brief={"message": "no Route matched with those values"}
            )
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._confirmable())
            asked = _national_asks(mock)

        assert sorted(asked) == sorted(WIKIDATA_NATIONAL_VALUES)
        assert found[AuthorityScheme.BNE] == "XX900250"

    @pytest.mark.asyncio
    async def test_an_item_id_that_is_not_one_never_reaches_a_request(self):
        """`_ITEM_ID` again, on the value the fallback interpolates.

        **Defence in depth rather than the traversal guard `_VIAF_CLUSTER` is**,
        and the difference is worth stating: `entity` is a query parameter, so
        httpx encodes it and no path separator escapes, where a cluster id goes
        into a URL path. What it buys is that a hand edited or restored value
        cannot become an outbound request at all.

        **Written because a mutation survived without it.** Deleting the check
        passed 96 tests: nothing supplied a candidate whose `wikidata_id` was
        not a Q number, because in production `_item_for` has already validated
        it, and a guard whose subject is enforced somewhere else is a guard
        nothing pins.
        """
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(
                self._confirmable(wikidata_id="../w/api.php?action=x")
            )
            asked = _national_asks(mock)

        assert found == {}
        assert asked == []

    @pytest.mark.asyncio
    async def test_a_cluster_naming_a_different_person_is_an_answer_and_buys_nothing(self):
        """**The line is supply, not coverage.** VIAF answered, and this
        function refused the answer on a rule of its own. Asking a second file
        to overrule that refusal is the adjudication the whole feature avoids,
        and it would store six numbers for the person VIAF says this is not."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief=VIAF_BARE)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._confirmable())
            asked = _national_asks(mock)

        assert found == {}
        assert asked == []

    @pytest.mark.asyncio
    async def test_a_cluster_carrying_none_of_the_six_is_an_answer_and_buys_nothing(self):
        """The case the trigger is narrowest against. VIAF served a cluster that
        names the confirmed GND back and carries no national file, which is
        coverage rather than supply, so the fallback stays shut."""
        empty = deepcopy(VIAF_BRIEF)
        block = empty["searchRetrieveResponse"]["records"]["record"]["recordData"][
            "v:VIAFCluster"
        ]["v:mainHeadings"]["v:data"]
        for heading in block:
            sid = heading["v:sources"]["v:sid"]
            keep = [entry for entry in sid if entry.startswith("DNB|")] if isinstance(sid, list) else []
            heading["v:sources"]["v:sid"] = keep or ["DNB|118753711"]

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief=empty)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._confirmable())
            asked = _national_asks(mock)

        assert found == {}
        assert asked == []

    @pytest.mark.asyncio
    async def test_viaf_naming_nobody_by_that_name_is_an_answer_and_buys_nothing(self):
        """`AutoSuggest` answered and matched no hit. That is VIAF speaking, so
        `heard` is true and the fallback never runs. It is the one case the
        return value alone cannot express, which is why
        `_viaf_cluster_by_gnd` returns a pair."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, suggest={"query": "nobody", "result": []})
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._no_cluster())
            asked = _national_asks(mock)

        assert found == {}
        assert asked == []

    @pytest.mark.asyncio
    async def test_autosuggest_not_answering_at_all_does_buy_it(self):
        """The diagonal of the test above, and the reason the pair is returned
        rather than inferred: the same `None` cluster, the opposite outcome.

        The candidate is Benedetti, whose GND is 123000327, so the item lookup
        is not what decides it: `wikidata_id` is supplied the way `_cross_check`
        supplies it."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=VIAF).mock(
                return_value=httpx.Response(200, text="<!DOCTYPE html>")
            )
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(self._no_cluster())
            asked = _national_asks(mock)

        assert sorted(asked) == sorted(WIKIDATA_NATIONAL_VALUES)
        assert found[AuthorityScheme.BNE] == "XX900250"

    @pytest.mark.asyncio
    async def test_a_cluster_id_lobid_supplied_that_viaf_would_refuse_is_an_outage(self):
        """**The trigger line inverted, and it was reachable rather than
        theoretical.**

        `heard` means "VIAF has answered", and it defaulted to True. A cluster
        id read out of lobid's `sameAs` costs no VIAF request, so an id that
        `_VIAF_URI` matches and `_VIAF_CLUSTER` rejects fell into
        `elif heard: return {}` with **nothing having been asked of VIAF at
        all**: a supply failure recorded as an answer, and the one shape where
        the fallback is most obviously owed.

        The two patterns really do disagree, which is what makes this
        reachable: `_VIAF_URI` captures unbounded digits and `_VIAF_CLUSTER`
        allows twenty. That is asserted here rather than assumed, so the test
        cannot go quiet if either is tightened.

        The assertion is that **no VIAF request was made** as well as that the
        fallback ran, because a version that asked VIAF and ignored the answer
        would satisfy the second alone.
        """
        long_id = "9" * 21
        assert authority._VIAF_URI.match(f"https://viaf.org/viaf/{long_id}")
        assert not authority._VIAF_CLUSTER.match(long_id)

        candidate = self._confirmable(
            same_as=tuple(
                f"https://viaf.org/viaf/{long_id}"
                if uri.startswith("http://viaf.org/")
                else uri
                for uri in _certain_candidate().same_as
            )
        )
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(candidate)
            viaf_calls = [
                call for call in mock.calls if str(call.request.url).startswith(VIAF)
            ]

        assert viaf_calls == []
        assert found[AuthorityScheme.BNE] == "XX900250"

    @pytest.mark.asyncio
    async def test_a_candidate_with_no_wikidata_item_has_no_second_supplier(self):
        """The ordinary case for a minor author, and the identity gate: without
        Wikidata's own reverse lookup on `P227` there is nothing joining an item
        to the confirmed record, and a national number read off a guess is a
        durable row about the wrong person."""
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(_certain_candidate())
            asked = _national_asks(mock)

        assert found == {}
        assert asked == []

    @pytest.mark.asyncio
    async def test_a_contested_item_is_never_read_for_national_numbers(self):
        """The same refusal `national_identifiers` makes for a contested
        cluster, one file over. lobid and Wikidata naming different items means
        the item is not known, and reading six numbers off it would resolve by
        precedence what `cross_references` refuses to resolve at all."""
        contested = self._confirmable(
            disagreements=(
                authority.Disagreement(
                    about=AuthorityScheme.WIKIDATA.value,
                    lobid="Q1512",
                    wikidata="Q99999",
                ),
            )
        )
        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=WIKIDATA_NATIONAL)
            found = await authority.national_identifiers(contested)
            asked = _national_asks(mock)

        assert found == {}
        assert asked == []

    @pytest.mark.asyncio
    async def test_a_property_held_twice_is_dropped_rather_than_picked_from(self):
        """`_viaf_sources`' rule, one file over, and it is not exotic: measured
        2026-08-28 through the query service, 4,955 humans carry more than one
        `P950` and `Q5682` carries eight `P3788` values.

        **It isolates.** Only `P950` is doubled, so the other five still land:
        a version that dropped the whole mapping on any ambiguity would fail
        the second assertion.
        """
        doubled = dict(WIKIDATA_NATIONAL)
        doubled["P950"] = _claims_body("P950", "XX900250", "981060880923108606")

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=doubled)
            found = await authority.national_identifiers(self._confirmable())

        assert AuthorityScheme.BNE not in found
        assert len(found) == 5

    @pytest.mark.asyncio
    async def test_one_value_stated_twice_is_one_fact_and_not_an_ambiguity(self):
        """The diagonal of the test above. Without it, "drop on more than one
        statement" would pass just as well as "drop on more than one distinct
        value", and those are different rules."""
        repeated = dict(WIKIDATA_NATIONAL)
        repeated["P950"] = _claims_body("P950", "XX900250", "XX900250")

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=repeated)
            found = await authority.national_identifiers(self._confirmable())

        assert found[AuthorityScheme.BNE] == "XX900250"

    @pytest.mark.asyncio
    async def test_a_deprecated_statement_is_not_stored(self):
        """`deprecated` is Wikidata saying the value is known wrong. Reading one
        would write a number the source itself has withdrawn.

        **It isolates from the drop rule above**: this property carries exactly
        one statement, so a version that ignored rank would store it rather than
        finding an ambiguity."""
        withdrawn = dict(WIKIDATA_NATIONAL)
        withdrawn["P950"] = _claims_body("P950", "XX900250", rank="deprecated")

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=withdrawn)
            found = await authority.national_identifiers(self._confirmable())

        assert AuthorityScheme.BNE not in found
        assert len(found) == 5

    @pytest.mark.asyncio
    async def test_a_preferred_statement_is_read_like_a_normal_one(self):
        """The diagonal of the test above: what is skipped is `deprecated` and
        nothing else. A rank check written as "only normal" would pass every
        assertion above and lose a value on the many items whose best statement
        is marked preferred."""
        preferred = dict(WIKIDATA_NATIONAL)
        preferred["P950"] = _claims_body("P950", "XX900250", rank="preferred")

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            _wikidata_router(mock, national=preferred)
            found = await authority.national_identifiers(self._confirmable())

        assert found[AuthorityScheme.BNE] == "XX900250"

    @pytest.mark.asyncio
    async def test_the_six_are_asked_one_at_a_time(self):
        """Wikidata answers **429** to a burst: roughly fifty `wbgetclaims` from
        one address inside two minutes, measured 2026-08-28, and it kept
        answering it for minutes afterwards. `search` gathers its fan out and
        this deliberately does not.

        Asserted on the transport rather than on the code: a `gather` here would
        have all six in flight at once, so no request would complete before the
        last one started."""
        overlapped: list[list[str]] = []
        live: set[str] = set()

        # **Async, and the `sleep` is the whole test.** A synchronous side
        # effect runs to completion inside the transport, so `live` could never
        # hold two names and the assertion below would pass under `gather` as
        # well. With the sleep, six gathered calls are all in flight at once.
        async def handler(request: httpx.Request) -> httpx.Response:
            prop = request.url.params.get("property")
            if prop not in WIKIDATA_NATIONAL_VALUES:
                return _json(WIKIDATA_VIAF)
            live.add(prop)
            await asyncio.sleep(0.01)
            if len(live) > 1:
                overlapped.append(sorted(live))
            live.discard(prop)
            return _json(WIKIDATA_NATIONAL[prop])

        with respx.mock(assert_all_called=False) as mock:
            _viaf_router(mock, brief_status=403)
            mock.get(url__startswith=WIKIDATA).mock(side_effect=handler)
            found = await authority.national_identifiers(self._confirmable())

        assert overlapped == []
        assert len(found) == 6


class TestTheOutwardWikipediaLink:
    """#89: a link, never a fetch of prose, and never an absent button.

    Three product rules, in the owner's order: the app's current locale first,
    fall back rather than give up, and the gate is identity rather than
    language. Each has a test named for it below.

    **The refusal is untouched and the tests above are the ones that say so.**
    Nothing here reads a description, an extract or an image; what it reads is
    which language editions exist, which `docs/decisions.md` puts on the
    permitted side of that line by name.
    """

    @staticmethod
    def _sitelinks(**by_item):
        """A `wbgetentities` body, `{item: {site: url}}` in, API shape out."""
        return {
            "entities": {
                item: {
                    "type": "item",
                    "id": item,
                    "sitelinks": {
                        site: {"site": site, "title": "T", "url": url}
                        for site, url in links.items()
                    },
                }
                for item, links in by_item.items()
            },
            "success": 1,
        }

    def _router(self, mock, *, filtered, unfiltered=None, status=200):
        """Route `wbgetentities` by whether it carried a `sitefilter`.

        Split on the parameter rather than answered with one body, for the
        reason every other router in this file gives: the module makes two
        different calls and a catch-all lets a test pass while it made the wrong
        one. Here it would hide the whole two pass design.
        """
        seen: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("action") != "wbgetentities":
                return _json({}, 400)
            site = request.url.params.get("sitefilter")
            seen.append(site)
            if status != 200:
                return httpx.Response(status, text="down")
            return _json(filtered if site else (unfiltered or {"entities": {}}))

        mock.get(url__startswith=WIKIDATA).mock(side_effect=handler)
        return seen

    @pytest.mark.asyncio
    async def test_the_readers_own_language_wins_when_it_has_an_article(self):
        """Rule one. Not the browser's language and not the book's: what the
        reader chose, which is what the caller passes as `prefer`."""
        body = self._sitelinks(
            Q1512={
                "dewiki": "https://de.wikipedia.org/wiki/Robert_Louis_Stevenson",
                "enwiki": "https://en.wikipedia.org/wiki/Robert_Louis_Stevenson",
            }
        )
        with respx.mock(assert_all_called=False) as mock:
            self._router(mock, filtered=body)
            found = await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert found["Q1512"].language == "de"
        assert found["Q1512"].url == "https://de.wikipedia.org/wiki/Robert_Louis_Stevenson"

    @pytest.mark.asyncio
    async def test_the_other_locale_is_taken_when_the_readers_has_no_article(self):
        """The diagonal of the test above, and the reason `prefer` is a sequence
        rather than one code: with only the first tier a German reader would
        fall straight past English to the item page for the 12.8% of authors
        measured to have no German article."""
        body = self._sitelinks(
            Q1512={"enwiki": "https://en.wikipedia.org/wiki/Robert_Louis_Stevenson"}
        )
        with respx.mock(assert_all_called=False) as mock:
            self._router(mock, filtered=body)
            found = await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert found["Q1512"].language == "en"

    @pytest.mark.asyncio
    async def test_a_language_nobody_here_reads_beats_no_link_at_all(self):
        """Rule two, in the owner's own words: a Chinese Wikipedia page rather
        than none, because the identity is confirmed and a reader can translate
        it.

        **The unfiltered second pass is the only thing that can find it**, which
        is why it exists: `sitefilter=dewiki|enwiki` cannot report an article it
        was not asked about. Measured 2026-08-28 over 300 GND carrying writers,
        3 have neither, so this pass is about 1% of authors."""
        with respx.mock(assert_all_called=False) as mock:
            seen = self._router(
                mock,
                filtered=self._sitelinks(Q1512={}),
                unfiltered=self._sitelinks(
                    Q1512={"zhwiki": "https://zh.wikipedia.org/wiki/%E7%BE%85"}
                ),
            )
            found = await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert seen == ["dewiki|enwiki", None]
        assert found["Q1512"].language == "zh"

    @pytest.mark.asyncio
    async def test_the_expensive_pass_is_not_paid_when_the_cheap_one_answered(self):
        """32,571 bytes against 354, measured on `Q1512`. A fallback that always
        runs is not a fallback, the same sentence the VIAF bare record carries."""
        with respx.mock(assert_all_called=False) as mock:
            seen = self._router(
                mock,
                filtered=self._sitelinks(
                    Q1512={"dewiki": "https://de.wikipedia.org/wiki/X"}
                ),
            )
            await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert seen == ["dewiki|enwiki"]

    @pytest.mark.asyncio
    async def test_a_pass_that_did_not_answer_does_not_buy_the_expensive_one(self):
        """**"No article" and "no answer" are different**, and conflating them
        turns an outage into the most expensive request this route can make, for
        every author at once. The same distinction `_viaf_cluster_sources` draws
        one feature over."""
        with respx.mock(assert_all_called=False) as mock:
            seen = self._router(mock, filtered={}, status=503)
            found = await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert seen == ["dewiki|enwiki"]
        assert found["Q1512"].url == "https://www.wikidata.org/wiki/Q1512"

    @pytest.mark.asyncio
    async def test_an_author_with_no_article_anywhere_still_gets_a_link(self):
        """Rule two at its floor. The Wikidata item always resolves, always names
        the confirmed person, and lists every edition one click away, so the
        button is never absent.

        `language` is null, which is how a client knows this is the item page
        rather than an article in a language it should name."""
        with respx.mock(assert_all_called=False) as mock:
            self._router(
                mock,
                filtered=self._sitelinks(Q1512={}),
                unfiltered=self._sitelinks(Q1512={}),
            )
            found = await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert found["Q1512"] == authority.WikipediaArticle(
            url="https://www.wikidata.org/wiki/Q1512", language=None
        )

    @pytest.mark.asyncio
    async def test_wikidata_being_down_costs_the_language_and_not_the_button(self):
        """The degradation rule stated as behaviour: a failure is a link to the
        right person rather than no link.

        This is what `Special:GoToLinkedPage` was measured against and lost to:
        it answers **200 with a 39,003 byte Wikidata maintenance form** when the
        article does not exist, so a reader is dropped on an edit form with
        nothing to tell them why. Right every time and sometimes a data page
        beats right 97.3% of the time and failing invisibly."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=WIKIDATA).mock(side_effect=httpx.ConnectError("no"))
            found = await authority.wikipedia_articles(
                ("Q1512", "Q909"), prefer=("de", "en")
            )

        assert found["Q1512"].url == "https://www.wikidata.org/wiki/Q1512"
        assert found["Q909"].url == "https://www.wikidata.org/wiki/Q909"
        assert all(row.language is None for row in found.values())

    @pytest.mark.asyncio
    async def test_a_url_that_is_not_a_wikipedia_article_is_dropped(self):
        """**The one URL this module takes from a response, and the check that
        makes it safe.** `commonswiki` is the case that is not hypothetical:
        `Q1512` carries 153 sitelinks, 101 of which end in `wiki`, and exactly
        one of those 101 is `commons.wikimedia.org`, a media repository. A code
        to host rule would have to know that; an anchored pattern does not.

        The other three are the shapes a pattern gets wrong: a suffix that only
        looks like the host, a scheme that is not https, and a `javascript:`
        URI, which is the rule `custom_fields.link_target` applies to a value a
        member typed, applied to one a third party supplied.
        """
        body = self._sitelinks(
            Q1512={
                "commonswiki": "https://commons.wikimedia.org/wiki/Robert_Louis_Stevenson",
                "aawiki": "https://de.wikipedia.org.evil.example/wiki/X",
                "abwiki": "http://de.wikipedia.org/wiki/X",
                "acwiki": "javascript:alert(1)",
            }
        )
        with respx.mock(assert_all_called=False) as mock:
            self._router(mock, filtered=body, unfiltered=body)
            found = await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert found["Q1512"].url == "https://www.wikidata.org/wiki/Q1512"
        assert found["Q1512"].language is None

    @pytest.mark.asyncio
    async def test_a_real_wikipedia_url_beside_them_still_lands(self):
        """The diagonal of the test above. Without it, a pattern that matched
        nothing at all would pass just as well as the right one."""
        body = self._sitelinks(
            Q1512={
                "commonswiki": "https://commons.wikimedia.org/wiki/X",
                "bat_smgwiki": "https://bat-smg.wikipedia.org/wiki/X",
            }
        )
        with respx.mock(assert_all_called=False) as mock:
            self._router(mock, filtered=body, unfiltered=body)
            found = await authority.wikipedia_articles(("Q1512",), prefer=("de", "en"))

        assert found["Q1512"].language == "bat-smg"

    @pytest.mark.asyncio
    async def test_the_last_tier_does_not_move_when_wikidata_reorders_itself(self):
        """`min` rather than "whichever came first". A link that changes because
        somebody else's JSON object was serialised in another order is a link
        nobody can reason about or reproduce from a bug report."""
        links = {
            "zhwiki": "https://zh.wikipedia.org/wiki/X",
            "arwiki": "https://ar.wikipedia.org/wiki/X",
            "frwiki": "https://fr.wikipedia.org/wiki/X",
        }
        for order in (list(links), list(reversed(list(links)))):
            body = self._sitelinks(Q1512={site: links[site] for site in order})
            with respx.mock(assert_all_called=False) as mock:
                self._router(mock, filtered=self._sitelinks(Q1512={}), unfiltered=body)
                found = await authority.wikipedia_articles(
                    ("Q1512",), prefer=("de", "en")
                )
            assert found["Q1512"].language == "ar"

    @pytest.mark.asyncio
    async def test_an_item_id_that_is_not_one_is_dropped_from_the_batch(self):
        """The same rule `national_identifiers` applies, on the other value this
        module puts into a query. An id is dropped rather than refused for the
        whole call, so one bad row cannot cost a page its buttons."""
        with respx.mock(assert_all_called=False) as mock:
            self._router(
                mock,
                filtered=self._sitelinks(
                    Q1512={"dewiki": "https://de.wikipedia.org/wiki/X"}
                ),
            )
            found = await authority.wikipedia_articles(
                ("../w/api.php", "Q1512", ""), prefer=("de", "en")
            )
            asked = [
                call.request.url.params.get("ids")
                for call in mock.calls
            ]

        assert asked == ["Q1512"]
        assert set(found) == {"Q1512"}

    @pytest.mark.asyncio
    async def test_nothing_is_asked_for_an_empty_list(self):
        """A library that has confirmed nobody makes no outbound request. The
        route says the client should not call it then; this is the half that
        holds when it does anyway."""
        with respx.mock(assert_all_called=False) as mock:
            self._router(mock, filtered={})
            found = await authority.wikipedia_articles((), prefer=("de", "en"))

        assert found == {}
        assert not mock.calls

    @pytest.mark.asyncio
    async def test_the_fan_out_is_bounded_by_a_constant_and_not_by_the_shelf(self):
        """`MAX_WIKIPEDIA_ITEMS` at 250 and fifty ids per filtered request, so
        five calls whatever the shelf holds. Measured 2026-08-28, fifty ids with
        a `sitefilter` is 15,034 bytes and 0.89s.

        Asserted on the requests rather than on the constant, because a constant
        nothing divides by bounds nothing."""
        many = tuple(f"Q{n}" for n in range(1, 401))
        with respx.mock(assert_all_called=False) as mock:
            self._router(
                mock,
                filtered=self._sitelinks(
                    **{q: {"dewiki": f"https://de.wikipedia.org/wiki/{q}"} for q in many}
                ),
            )
            found = await authority.wikipedia_articles(many, prefer=("de", "en"))
            ids = [call.request.url.params.get("ids") for call in mock.calls]

        assert len(ids) == 5
        assert all(len(one.split("|")) <= 50 for one in ids)
        assert len(found) == len(many)

    @pytest.mark.asyncio
    async def test_an_author_past_the_fetch_cap_still_gets_a_button(self):
        """**The cap bounds the fetch, never the answer**, and this is the test
        that used to pin the opposite.

        `wanted` was sliced before the resolve loop, so author 251 onwards got
        no entry, no row and no button, cut by listing order, while three
        docstrings said the button is never absent. The floor costs no request:
        an item nobody asked about resolves to the Wikidata item page exactly as
        one Wikidata answered nothing for does.

        The 250th and the 251st are asserted separately, because a fix that
        returned rows for everybody and asked about everybody would pass an
        assertion on the count alone.
        """
        many = tuple(f"Q{n}" for n in range(1, 401))
        with respx.mock(assert_all_called=False) as mock:
            self._router(
                mock,
                filtered=self._sitelinks(
                    **{q: {"dewiki": f"https://de.wikipedia.org/wiki/{q}"} for q in many}
                ),
            )
            found = await authority.wikipedia_articles(many, prefer=("de", "en"))
            asked = {
                one
                for call in mock.calls
                for one in (call.request.url.params.get("ids") or "").split("|")
            }

        assert found["Q250"].language == "de"
        assert found["Q251"] == authority.WikipediaArticle(
            url="https://www.wikidata.org/wiki/Q251", language=None
        )
        assert "Q250" in asked and "Q251" not in asked

    @pytest.mark.asyncio
    async def test_the_unfiltered_pass_asks_for_far_fewer_people_at_a_time(self):
        """**The two passes cannot share a chunk size, and sharing one made this
        tier dead code.**

        Measured 2026-08-28: an unfiltered entity is 1,606 to **64,449** bytes
        against about 300 filtered, and eight ids measured 233,815. So fifty
        would be roughly six times `_RESPONSE_LIMIT`, `fetch.get` would refuse
        the body, `_wikidata` would answer None with no log, and every item in
        that chunk would fall to the Wikidata item page. The third tier was
        therefore unreachable for any page with more than about seven authors
        lacking both app locales, which is the library it exists for.

        **The assertion is on the unfiltered requests specifically.** The
        existing fan out test above asserts `<= 50` and passes on the broken
        code, because it only ever provokes the filtered pass.
        """
        many = tuple(f"Q{n}" for n in range(1, 41))
        with respx.mock(assert_all_called=False) as mock:
            self._router(
                mock,
                filtered=self._sitelinks(**{q: {} for q in many}),
                unfiltered=self._sitelinks(
                    **{q: {"zhwiki": f"https://zh.wikipedia.org/wiki/{q}"} for q in many}
                ),
            )
            await authority.wikipedia_articles(many, prefer=("de", "en"))
            unfiltered = [
                call.request.url.params.get("ids")
                for call in mock.calls
                if not call.request.url.params.get("sitefilter")
            ]

        assert unfiltered, "the unfiltered pass never ran, so this asserts nothing"
        assert max(len(one.split("|")) for one in unfiltered) == 2
        # **The margin, not the fit, because the fit does not pin the
        # constant.** The first version of this line asserted
        # `LARGEST * size < _RESPONSE_LIMIT`, which passes at three, four and
        # five: four ids is 257,796 against a 262,144 cap, so "it fits" permits
        # the size this test exists to refuse.
        #
        # What is being pinned is the **2x margin** the constant was chosen for,
        # which `_VIAF_LIMIT`'s comment gives the reason for. At two that is
        # 257,796 and passes; at three it is 386,694 and does not.
        assert (
            _LARGEST_SAMPLED_ENTITY * authority._UNFILTERED_ITEMS_PER_REQUEST * 2
            <= authority._RESPONSE_LIMIT
        )

    @pytest.mark.asyncio
    async def test_the_unfiltered_pass_is_paid_for_a_bounded_number_of_people(self):
        """`MAX_UNFILTERED_ITEMS`, so the route's ceiling is ten requests rather
        than one per author who needs the third tier.

        **The eleventh still gets a button**, which is what makes this a budget
        cut rather than the one the test above exists for: it falls to the
        Wikidata item page, which costs no request."""
        many = tuple(f"Q{n}" for n in range(1, 41))
        with respx.mock(assert_all_called=False) as mock:
            self._router(
                mock,
                filtered=self._sitelinks(**{q: {} for q in many}),
                unfiltered=self._sitelinks(
                    **{q: {"zhwiki": f"https://zh.wikipedia.org/wiki/{q}"} for q in many}
                ),
            )
            found = await authority.wikipedia_articles(many, prefer=("de", "en"))
            unfiltered = [
                call.request.url.params.get("ids")
                for call in mock.calls
                if not call.request.url.params.get("sitefilter")
            ]

        asked = [one for group in unfiltered for one in group.split("|")]
        assert len(asked) == authority.MAX_UNFILTERED_ITEMS
        assert found[asked[0]].language == "zh"
        assert found["Q40"].language is None

    @pytest.mark.asyncio
    async def test_one_person_named_twice_is_asked_about_once(self):
        """Two spellings can carry the same confirmed item, and the API is given
        a `|` separated list where a repeat is wasted budget rather than an
        error, so nothing would have complained."""
        with respx.mock(assert_all_called=False) as mock:
            self._router(
                mock,
                filtered=self._sitelinks(
                    Q1512={"dewiki": "https://de.wikipedia.org/wiki/X"}
                ),
            )
            await authority.wikipedia_articles(
                ("Q1512", "Q1512", "Q1512"), prefer=("de", "en")
            )
            ids = [call.request.url.params.get("ids") for call in mock.calls]

        assert ids == ["Q1512"]

    def test_nothing_but_a_url_and_a_language_can_come_back(self):
        """**The refusal, restated where it can fail.** `WikipediaArticle` is
        what this feature is allowed to carry, and a field holding a
        description, an extract or an image would be `docs/featurelist.md`'s
        refusal reversed rather than #89 extended.

        **The annotations, not the field names, and the first version was the
        name set.** `set(__dataclass_fields__) == {"url", "language"}` compares
        spellings, so it is defeated by nesting rather than by adding a field:
        verified mechanically that `language: Summary | None`, with `Summary`
        carrying `text` and `thumbnail`, passes it, and so does a `url` whose
        type carries an extract. Both are the refusal reversed with the field
        names untouched.

        `get_type_hints` resolves the annotations rather than reading their
        source text, so a quoted forward reference or an alias is compared as
        what it is.
        """
        from typing import get_type_hints

        assert get_type_hints(authority.WikipediaArticle) == {
            "url": str,
            "language": str | None,
        }

    @staticmethod
    def _wire_names(model: Any) -> set[str]:
        """Every property name a model's schema names, or `*` where it names none.

        **Ask pydantic for the wire contract rather than reading Python.** This
        is the shape `test_house_rules.py` arrived at over three versions for
        the address rule, taken rather than re-invented: `model_fields` is the
        Python field list, and several separate things are on the wire without
        being in it.

        One walk over one document, in **both** modes, with no arm for any of
        them. Measured on this checkout's pydantic 2.13.4:

        | Shape | Seen | Why |
        |---|---|---|
        | a fourth field | yes | a new name under `properties` |
        | either alias keyword | yes | the alias **is** the property name, in one mode or the other |
        | a nested model carrying prose | yes | the schema inlines it into `$defs`, flattened, at any depth |
        | `@computed_field` | yes | in the serialization schema, and **absent from `model_fields`** |
        | `RootModel[list[Prose]]` | yes | the member model is in `$defs` |
        | a discriminated union | yes | every arm is in `$defs` |
        | `extra="allow"` | yes | `additionalProperties: true`, the contract saying "and anything else" |
        | `extra="forbid"` or `"ignore"` | **no, rightly** | see below |
        | a schema that cannot be built | **raises** | see below |

        The last two rows are the ones a reader should not take for a gap.
        `forbid` emits a falsy `additionalProperties` and `ignore` drops extras
        before serialising, so neither puts anything in front of a caller and
        neither should be reported. A schema that cannot be built raises
        `PydanticInvalidForJsonSchema` rather than returning an empty set, so it
        fails loud: a model this cannot read is a hole, not an exemption, which
        is the rule `test_house_rules.py` states for the same walk.

        Both modes because they differ: `validation_alias` names what a request
        body may send, `serialization_alias` what a response carries, and a
        computed field is in the serialization schema only.

        ## Why this returns names rather than a boolean

        `extra="allow"` names no property, so a set of property names alone
        cannot see it. `*` is not a name any expected set contains, so it fails
        by construction rather than through a second check.

        **One false positive, named here rather than discovered.** An honest
        `dict[str, str]` field emits the same `additionalProperties` keyword and
        also yields `*`. That is the safe direction and arguably not a false
        positive at all: a mapping field is a way to carry anything, so a model
        that grows one has widened its contract and should be looked at.

        ## Boundary, stated rather than left to be found

        **A `json_schema_extra` callable that deletes a property from the
        document gets through.** Measured: with a real `@computed_field summary`
        and
        `json_schema_extra=lambda s: s.get("properties", {}).pop("summary", None)`,
        this reads `{key, language, url}` and passes while `model_dump()`
        returns the prose.

        That is deliberately not closed, and the reasoning is the one this file
        already applies to `__import__("database")` and to a `props` assembled
        at runtime: evading it means writing a lambda whose only purpose is to
        hide a property from a reader. A rule that chased it would be guessing
        at ways of lying rather than describing the contract.

        **`Field(description=...)` is outside both mechanisms and that is
        correct**: a description is metadata about a field, not a field, so
        nothing it says reaches a caller as data. The line is data, not prose in
        the document.

        ## This is one of two mechanisms and neither contains the other

        `test_what_reaches_the_client_carries_no_more_than_that` asserts this
        **and** `model_dump()` on a real instance. Deleting either as redundant
        is the mistake the measurement below refuses:

        | Shape | this walk | `model_dump()` |
        |---|---|---|
        | `@computed_field` | yes | yes |
        | either alias keyword | **yes** | no |
        | a nested model | **yes** | no |
        | `extra="allow"` | **yes** | no |
        | `@model_serializer` returning `dict[str, Any]` | yes, as `*` | yes |
        | `@model_serializer` with **no return annotation** | no | **yes** |

        The last row is the same family as the `@computed_field` hole that
        defeated version two: a serialization hook the schema does not describe.
        The schema sees the **contract**, including shapes one instance never
        exercises; the dump sees what actually **leaves**.
        """
        found: set[str] = set()

        def walk(node: object) -> None:
            if isinstance(node, dict):
                properties = node.get("properties")
                if isinstance(properties, dict):
                    found.update(properties)
                if node.get("additionalProperties"):
                    found.add("*")
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for mode in ("validation", "serialization"):
            walk(model.model_json_schema(mode=mode))
        return found

    def test_what_reaches_the_client_carries_no_more_than_that(self):
        """**The same refusal on the object a reader actually receives.**

        The test above guards `authority.WikipediaArticle`, which is internal.
        `AuthorWikipediaOut` is what `GET /authors/wikipedia` serialises, and a
        field added there would ship prose to a browser whether or not the
        dataclass ever carried it.

        **This is the third version and the first two were both defeated.** It
        began as a set of field names, which compares spellings; it then read
        `model_fields`' annotations, which a `@computed_field` is not in at all.
        Reproduced in this checkout on pydantic 2.13.4: a `summary` computed
        field left `model_fields` reading exactly the three declared names while
        `model_dump()` returned `{'key': ..., 'url': ..., 'language': ...,
        'summary': 'Scottish novelist and poet, a body of prose'}`.

        **The answer is not a third arm.** Two other trios met the same family
        this wave, on `serialization_alias` and on `validation_alias`, and the
        general fix is a net deletion: ask pydantic what the model puts on the
        wire. `_wire_names` carries the table of what that covers.

        **Two mechanisms, and neither contains the other**, which is the one
        thing to read before deleting either as redundant. The schema sees the
        **contract**, including shapes a single instance never exercises: an
        alias, a nested model and `extra="allow"` are all invisible to a dump of
        this instance. The dump sees what actually **leaves**: a
        `@model_serializer` with no return annotation adds a key the schema does
        not describe, which is the same family as the `@computed_field` hole
        that defeated version two. `_wire_names`' docstring has the measured
        table of which column catches which.
        """
        from schemas.author import AuthorWikipediaOut

        expected = {"key", "url", "language"}

        assert self._wire_names(AuthorWikipediaOut) == expected
        assert set(AuthorWikipediaOut(key="k", url="u").model_dump()) == expected

    def test_that_guard_sees_the_shapes_a_field_list_does_not(self):
        """**A guard is not evidence until somebody has tried to evade it.**

        Four models, each carrying prose in a way that leaves the three declared
        field names untouched. Asserted here rather than described, because the
        two previous versions of the guard above were both written believing
        they covered these.

        The pair is a diagonal: the same four are built from the *permitted*
        shape too, and that one must pass, or a guard that simply refused
        everything would satisfy the four assertions below.
        """
        from pydantic import (
            BaseModel,
            ConfigDict,
            Field,
            computed_field,
            model_serializer,
        )

        class Permitted(BaseModel):
            key: str
            url: str
            language: str | None = None

        class Prose(BaseModel):
            text: str
            thumbnail: str

        class Computed(Permitted):
            # `type: ignore` for a mypy limitation rather than a defect: mypy
            # does not model a decorator stacked on `@property`, which is the
            # only way pydantic's `@computed_field` can be written. Pydantic's
            # own documentation prescribes exactly this. The fixture has to use
            # the real decorator, because a hand rolled stand in would not put
            # the field in the serialization schema and would therefore not
            # reproduce the evasion it exists to reproduce.
            @computed_field  # type: ignore[prop-decorator]
            @property
            def summary(self) -> str:
                return "prose"

        class Aliased(BaseModel):
            key: str
            url: str
            language: str | None = Field(default=None, serialization_alias="summary")

        class Nested(BaseModel):
            key: str
            url: str
            language: Prose | None = None

        class Open(Permitted):
            model_config = ConfigDict(extra="allow")

        class Serialised(Permitted):
            # **No return annotation, deliberately.** Annotated
            # `-> dict[str, Any]` the schema reports `*` and the walk catches
            # it; unannotated, pydantic describes nothing and the walk reads the
            # three declared names while `model_dump()` returns a fourth. It is
            # the one shape in this tuple the schema half does not see, which is
            # why the assertion below is on both mechanisms.
            @model_serializer
            def _dump(self):
                return {
                    "key": self.key,
                    "url": self.url,
                    "language": self.language,
                    "summary": "prose",
                }

        expected = {"key", "url", "language"}

        def escapes(model: Any) -> bool:
            """Does this model get prose past **either** mechanism?"""
            instance = model(key="k", url="u")
            return (
                self._wire_names(model) != expected
                or set(instance.model_dump()) != expected
            )

        # The diagonal: the permitted shape must pass both, or a guard that
        # refused everything would satisfy the loop below.
        assert self._wire_names(Permitted) == expected
        assert set(Permitted(key="k", url="u").model_dump()) == expected

        for evasion in (Computed, Aliased, Nested, Open, Serialised):
            assert escapes(evasion), evasion.__name__


class TestTheParserIsAskedForABoundedSetOfCodes:
    """`wanted` is a bound on memory, and a bound nothing exercises is a comment.

    A 2,097,151 byte body at `_VIAF_LIMIT` holding 196,998 distinct `code|id`
    entries peaked at 81.8 MB with an unfiltered accumulator, measured with
    `tracemalloc` on this tree, against 13.1 MB for `json.loads` on the same
    bytes.
    """

    @staticmethod
    def _cluster(entries):
        """A cluster object, not a whole response: `_viaf_sources` is handed the
        output of `_viaf_cluster_record`, and the first version of this helper
        returned the wrapper, so every assertion here read an empty mapping and
        the filter under test was never reached."""
        return {"ns1:mainHeadings": {"ns1:data": [{"ns1:sources": {"ns1:sid": entries}}]}}

    def test_a_code_outside_the_wanted_set_is_never_accumulated(self):
        """The filter, seen from the only side a test can see it from."""
        cluster = self._cluster(["DNB|118753711", "SELIBR|94215", "NKC|jn19990008249"])

        assert authority._viaf_sources(cluster, frozenset({"DNB"})) == {
            "DNB": "118753711"
        }

    def test_one_wanted_code_repeated_with_new_values_does_not_grow(self):
        """**Filtering by code alone is a step short of the family.** A body
        naming one allowlisted code two hundred thousand times with a different
        value each time is inside any code filter. What bounds it is holding one
        value per code rather than a set of them, and the drop rule needs no
        more than that.

        Asserted behaviourally, because the accumulator is a local: a code named
        with differing values is absent however many times it is named, and a
        third differing value cannot revive it.
        """
        cluster = self._cluster([f"DNB|{number}" for number in range(500)])

        assert authority._viaf_sources(cluster, frozenset({"DNB"})) == {}

    def test_the_wanted_set_covers_every_scheme_the_writer_can_store(self):
        """A scheme in `_NATIONAL_SOURCES` that the parser is not asked for
        would look exactly like VIAF not carrying it: no error, no log line, an
        empty column. Derived rather than written out for that reason."""
        from_the_mapping = frozenset(authority._NATIONAL_SOURCES) | {
            authority._GND_SOURCE
        }

        assert from_the_mapping == authority._WANTED_SOURCES

    def test_production_asks_for_the_seven_and_nothing_else(self):
        """The count, against what the two constants hold rather than against
        the number seven written here twice."""
        assert len(authority._WANTED_SOURCES) == len(authority._NATIONAL_SOURCES) + 1
        assert "SUDOC" not in authority._WANTED_SOURCES


class TestTheViafResponseBoundIsSeparateAndLargerThanTheOthers:
    """`_VIAF_LIMIT` exists because a measured `BriefVIAF` exceeds `_RESPONSE_LIMIT`.

    Mutating it to `_RESPONSE_LIMIT` passed 67 tests before this existed, though
    the constant's own docstring records the 276,610 byte response that made it
    necessary.
    """

    def test_a_measured_cluster_fits_the_viaf_bound_and_not_the_other_one(self):
        """**The relationship, not the value.** `_VIAF_LIMIT` is spelled
        `fetch.MAX_RESPONSE_BYTES`, so asserting a number here would pass while
        that global moved underneath it and the documented 2.68x margin
        vanished. 276,610 is the largest `BriefVIAF` measured on 2026-08-28,
        cluster 32197206.
        """
        import fetch

        assert authority._VIAF_LIMIT >= 276_610
        assert authority._RESPONSE_LIMIT < 276_610
        assert authority._VIAF_LIMIT <= fetch.MAX_RESPONSE_BYTES

    def test_the_general_bound_still_clears_the_largest_measured_search(self):
        """**The margin is the finding, not the reassurance.**

        241,691 bytes, `q=Lee` with the module's own `size=MAX_CANDIDATES` and
        person filter, measured live 2026-08-28. Against `_RESPONSE_LIMIT` at
        262,144 that is **1.08x**, and nine other ordinary surnames measured
        between 180,000 and 241,691. So the binding case for this constant is a
        name search rather than the GND record its comment used to describe, and
        one more field per record turns `GET /authors/authority` into a 503.

        Asserted rather than fixed: raising the constant is a change to the
        relationship the test below rests on. `_RESPONSE_LIMIT`'s own comment
        carries the whole table and says why.
        """
        assert authority._RESPONSE_LIMIT >= 241_691

    def test_the_largest_measured_bare_record_fits_too(self):
        """781,687 bytes, cluster 96987389, which is the fallback path and the
        reason the bound is the general cap rather than a tighter number."""
        assert authority._VIAF_LIMIT >= 781_687

    @pytest.mark.asyncio
    async def test_the_bound_is_the_one_actually_passed_to_the_transport(self):
        """A constant nothing hands to `fetch.get` bounds nothing."""
        seen: list[int | None] = []

        async def record(client, url, *, params=None, limit=None, deadline=None):
            seen.append(limit)
            return _fetched(VIAF_BRIEF)

        with _patched_fetch_get(record):
            await authority.national_identifiers(_certain_candidate())

        assert seen and set(seen) == {authority._VIAF_LIMIT}


class TestOneDeadlineCoversTheViafCallsToo:
    """`national_identifiers` goes through `fetch.get`, not `fetch.get_once`.

    **So the only deadline test in this file could not see it.** That test
    patches `fetch.get_once`, and the property is not observable through a
    result either: `fetch.DeadlineExceeded` is an `httpx.HTTPError` and
    `_viaf_json` turns every failure into the same empty mapping. Deleting
    `deadline=deadline` from either the transport call or the router's would
    have passed, and the `DbSession` held across `POST /authors/identifiers`
    would go from a bounded 8.0s to up to 38s, which is the `QueuePool`
    exhaustion `DEADLINE_SECONDS` exists to prevent.
    """

    @pytest.mark.asyncio
    async def test_every_viaf_request_carries_the_deadline_it_was_given(self):
        seen: list[float | None] = []

        async def record(client, url, *, params=None, limit=None, deadline=None):
            seen.append(deadline)
            # A 5xx on the SRU call, so all three steps run and all three are
            # checked rather than only the one the happy path makes.
            if url.endswith("/search"):
                return _fetched(None, status=500)
            if url.endswith("/AutoSuggest"):
                return _fetched(VIAF_AUTOSUGGEST)
            return _fetched(VIAF_BARE)

        candidate = _certain_candidate(
            name="Benedetti, Mario",
            identifier="118508873",
            same_as=tuple(
                uri for uri in _certain_candidate().same_as if not uri.startswith("http://viaf.org/")
            ),
        )
        with _patched_fetch_get(record):
            found = await authority.national_identifiers(candidate, deadline=1234.5)

        assert len(seen) == 3, seen
        assert set(seen) == {1234.5}
        # The fallback really ran, so the three above are the three steps and
        # not one step called three times.
        assert found


class TestTheEnumAndTheParserDescribeOneSet:
    """A member with nothing to write it and a code with nowhere to store it are
    the two ways this drifts, and both are silent."""

    def test_every_national_scheme_has_a_viaf_code_and_the_reverse(self):
        assert set(authority._NATIONAL_SOURCES.values()) == {
            AuthorityScheme.BLBNB,
            AuthorityScheme.ARBABN,
            AuthorityScheme.BNE,
            AuthorityScheme.PTBNP,
            AuthorityScheme.ICCU,
            AuthorityScheme.BNCHL,
        }

    def test_the_fallback_reads_the_same_six_the_cluster_does(self):
        """A property with no scheme is a request nothing can store, and a
        scheme with no property is a file the fallback silently loses. Both are
        invisible: the confirmation succeeds either way and the row is just not
        there.

        Written as an equality against `_NATIONAL_SOURCES` rather than against a
        list typed out again, because the list above is already the one that
        pins the six by name. Two hand written lists would drift together."""
        assert set(authority._NATIONAL_PROPERTIES) == set(
            authority._NATIONAL_SOURCES.values()
        )

    def test_every_property_is_named_once(self):
        """A copied line with the wrong scheme beside it would read `P950` twice
        and never ask for one of the six, and the mapping is keyed on the scheme
        so nothing else would complain."""
        properties = list(authority._NATIONAL_PROPERTIES.values())

        assert len(set(properties)) == len(properties) == 6

    def test_no_scheme_is_written_by_both_readers(self):
        """`cross_references` reads a `sameAs` block and `national_identifiers`
        reads a cluster. `_cross_references_for` merges them with `|`, which is
        a merge only while the two are disjoint: an overlap would make the
        result depend on which side of that operator a scheme sat."""
        assert not set(authority._CROSS_REFERENCE_URIS) & set(
            authority._NATIONAL_SOURCES.values()
        )

    def test_every_member_of_the_enum_has_exactly_one_writer(self):
        """The one that catches a member added with nothing to produce it. GND
        is the entry point and is written by the confirmation itself, so it is
        named here rather than being in either mapping."""
        written = (
            {AuthorityScheme.GND}
            | set(authority._CROSS_REFERENCE_URIS)
            | set(authority._NATIONAL_SOURCES.values())
        )

        assert written == set(AuthorityScheme)


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


class TestTheCrossReferencesThatArriveWithTheRecord:
    """`cross_references`, which reads four identifiers off a record already in
    hand.

    **Free, and that is the whole argument for it.** Every one of these is in
    the `sameAs` block of a response `resolve` has already fetched and parsed,
    and until 2026-08-28 every one was handed to the client and dropped. See
    `enums.AuthorityScheme` for the fourteen record measurement behind the
    claim that all four are ordinarily present.
    """

    @staticmethod
    async def _resolved(mock_router, **wikidata):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(mock_router))
            _wikidata_router(mock, **wikidata)
            return await resolve("118753711")

    @pytest.mark.asyncio
    async def test_all_four_are_read_off_one_record(self):
        candidate = await self._resolved(LOBID_RECORD)

        assert authority.cross_references(candidate) == {
            AuthorityScheme.ISNI: "0000000122831567",
            AuthorityScheme.LCNAF: "n78088964",
            AuthorityScheme.VIAF: "95207986",
            AuthorityScheme.WIKIDATA: "Q1512",
        }

    @pytest.mark.asyncio
    async def test_the_records_own_scheme_is_never_among_them(self):
        """This returns the cross references and not the identity. A caller
        stores the confirmed GND from the candidate and these beside it, so a
        GND appearing here could overwrite the thing that was confirmed."""
        candidate = await self._resolved(LOBID_RECORD)

        assert AuthorityScheme.GND not in authority.cross_references(candidate)

    @pytest.mark.asyncio
    async def test_a_contested_scheme_is_shown_and_not_stored(self):
        """A disagreement means the two files name different records, so
        storing either side is resolution by precedence, which is the one thing
        this feature refuses to do anywhere."""
        disagreeing = {"claims": {"P214": [{"mainsnak": {"datavalue": {"value": "999"}}}]}}
        candidate = await self._resolved(LOBID_RECORD, viaf=disagreeing)

        assert [row.about for row in candidate.disagreements] == ["viaf"]
        assert AuthorityScheme.VIAF not in authority.cross_references(candidate)
        # Shown, not hidden: the URI is still on the candidate for a person to
        # look at, and the conflict is reported beside it.
        assert "http://viaf.org/viaf/95207986" in candidate.same_as

    @pytest.mark.asyncio
    async def test_an_isni_disagreement_is_detected_at_all(self):
        """The comparison `_disagreements` used to refuse to make, and the entry
        there names storing ISNI as the trigger that would reverse it."""
        disagreeing = {"claims": {"P213": [{"mainsnak": {"datavalue": {"value": "0000000000000001"}}}]}}
        candidate = await self._resolved(LOBID_RECORD, isni=disagreeing)

        assert [row.about for row in candidate.disagreements] == ["isni"]
        assert AuthorityScheme.ISNI not in authority.cross_references(candidate)

    @pytest.mark.asyncio
    async def test_wikidatas_own_answer_is_used_where_lobid_names_no_item(self):
        """The reverse lookup on `P227` is Wikidata's assertion about itself,
        and lobid's `sameAs` is another service's claim about it. Where only the
        first has spoken there is no conflict and the answer stands."""
        # `LOBID_RECORD` is annotated `dict[str, object]`, so a member has to be
        # narrowed before it can be walked. Cast rather than annotated: the
        # fixture is a captured JSON body and giving it a precise type here
        # would be a second, drifting description of the capture.
        same_as = cast(list[dict[str, str]], LOBID_RECORD["sameAs"])
        without_item = LOBID_RECORD | {
            "sameAs": [
                entry for entry in same_as if "wikidata.org/entity" not in entry["id"]
            ]
        }
        candidate = await self._resolved(without_item)

        assert candidate.wikidata_id == "Q1512"
        assert authority.cross_references(candidate)[AuthorityScheme.WIKIDATA] == "Q1512"

    def test_a_subject_heading_is_not_read_as_a_person(self):
        """`id.loc.gov` serves several files under one host and the two shapes
        differ only in the path. A subject heading in the person column is
        exactly the confusion `ClassificationScheme` and `AuthorityScheme` exist
        as two enums to prevent."""
        candidate = authority.AuthorityCandidate(
            scheme=AuthorityScheme.GND,
            identifier="118753711",
            name="Stevenson, Robert Louis",
            same_as=("http://id.loc.gov/authorities/subjects/sh85009003",),
        )

        assert authority.cross_references(candidate) == {}

    def test_a_uri_on_another_host_is_never_read_as_one_of_these(self):
        """Every pattern is anchored on its own host. A `sameAs` block carries
        Wikipedia, DBpedia, Kalliope and a film database, and none of them names
        a person in a file this app can look up."""
        candidate = authority.AuthorityCandidate(
            scheme=AuthorityScheme.GND,
            identifier="118753711",
            name="Stevenson, Robert Louis",
            same_as=(
                "https://en.wikipedia.org/wiki/Robert_Louis_Stevenson",
                "https://dbpedia.org/resource/Robert_Louis_Stevenson",
                "https://kalliope-verbund.info/gnd/118753711",
                "https://evil.example/isni.org/isni/0000000122831567",
                "https://isni.org.evil.example/isni/0000000122831567",
            ),
        )

        assert authority.cross_references(candidate) == {}

    @pytest.mark.asyncio
    async def test_a_name_search_buys_no_comparison_and_so_offers_nothing_to_store(self):
        """`_cross_check(compare_references=False)` is the search branch, and a
        candidate it produced was never compared. It therefore carries no
        disagreements, which is not the same as agreeing, and
        `Authorship.record_cross_references` is documented as taking a resolved
        candidate for exactly this reason."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=LOBID).mock(return_value=_json(LOBID_SEARCH))
            _wikidata_router(mock)
            found = await search("Robert Louis Stevenson")
            # Read inside the router's own context: `mock.calls` is emptied when
            # it pops, and the module level `respx.calls` belongs to a different
            # router, so a list built outside here is empty and the assertion
            # passes without having looked at anything.
            asked = [
                call.request.url.params.get("action")
                for call in mock.calls
                if str(call.request.url).startswith(WIKIDATA)
            ]

        assert found
        assert all(row.disagreements == () for row in found)
        assert asked and "wbgetclaims" not in asked
