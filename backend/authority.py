"""The authority files, read for a person rather than for a book.

`metadata.py` asks catalogues about **books** and normalises their answers into
`catalogue.Record`. This module asks two authority files about **people** and
normalises theirs into `AuthorityCandidate`. The question is different: a book
record describes a printing and dies with it, and an authority record describes
somebody who outlives every printing.

## Two suppliers, deliberately, because a disagreement has to be detectable

**lobid.org** serves the GND, which is the file the DNB is already citing in
MARC `100 $0`. **Wikidata** is the cross check. They assert overlapping facts, so
where they disagree the disagreement is **surfaced and never resolved by
precedence**: see `Disagreement`, and `docs/decisions.md` for why a merge of
several sources beats taking the first hit.

The join is verifiable in **both directions**, which is the property that makes
this worth two requests rather than one. Measured 2026-08-27 for
`Stevenson, Robert Louis`:

* lobid's `sameAs` on GND `118753711` asserts `wikidata.org/entity/Q1512`.
* Wikidata's `haswbstatement:P227=118753711` independently returns `Q1512`.

Neither was told the other's answer.

## Why not VIAF, which the ticket was written around

**Half of VIAF's read API answers, and the half that does is easy to probe
wrongly in two opposite directions**, so the whole of it is recorded here rather
than a conclusion. Measured 2026-08-27.

**The variable is the `Accept` request header, and nothing else.** Not the
`User-Agent`, which is what two separate probes of this concluded before the
matrix below was run: both had changed the agent and the header together and
credited the agent.

`GET viaf.org/viaf/search?query=...&httpAccept=application/json`:

| `Accept: application/json` | `User-Agent` | result |
|---|---|---|
| sent | anything, curl's default included | **200 `application/json`**, ten `VIAFCluster` records |
| absent | `endpaper`, `endpaper/1.0`, a Chrome string | **307** to `/en/viaf/search?...` |
| absent | curl's default | **403**, 5,481 bytes of `text/html` |

`httpAccept=application/json` in the query string is VIAF's **old** API
convention and the current site ignores it, which is the trap: following the 307
answers **200 `text/html`**, 93,813 bytes of Next.js page, and that is a 200 for
a request that carried `httpAccept=application/json`. A probe that follows
redirects and checks only the status code concludes the API works. A probe that
sends no `Accept` header concludes it is gone. Both are wrong.

With the header, `AutoSuggest` also answers 200 `application/json`, carrying
`lc`, `dnb` and `viafid`. The record endpoints are gone whatever is sent:
`/viaf/<id>/viaf.json`, `/viaf/<id>/justlinks.json` and `/en/viaf/<id>` all
answer Kong's `{"message":"no Route matched with those values"}`, and
`POST /api/search` answers 403 `{"message":"Forbidden"}`.

**None of it changed a line of this module**, which is the only reason the
correction is cheap: VIAF *aggregates* national authority files and mints
nothing. The identifier this app already receives is a **GND**, so going
through an aggregator is the indirect route to a file that can be read directly.
lobid even carries the VIAF URI in `sameAs`, so the cross reference arrives
without VIAF being called at all, which is exactly what
`AuthorityCandidate.same_as` holds.

## What each supplier's terms permit, read rather than assumed

Both on 2026-08-27, and both from a machine readable statement rather than a
page that says so.

**lobid.** Every response carries `describedBy.license` =
`creativecommons.org/publicdomain/zero/1.0/`, maintainer `DE-101`, which is the
DNB. Its usage policy asks for at most 6,000 simple lookups and 30 complex
searches a minute, a meaningful and stable `User-Agent`, and bulk work off peak.

**Wikidata.** `action=query&meta=siteinfo&siprop=rightsinfo` returns "All
structured data from the main and property namespace is available under the
Creative Commons CC0 License". It asks for a `User-Agent` too, and **not as a
courtesy**: a request without one answers **403** with "Please set a user-agent
and respect our robot policy".

lobid's attribution is explicitly optional and explicitly welcomed. Wikidata's
CC0 covers exactly the namespaces `wbgetentities` and `wbgetclaims` read.

**That 403 is why `fetch._AGENT` exists.** It was added for lobid's written
request and turned out to be a hard requirement for the second supplier.

## The refusal this module is built around

`docs/featurelist.md` refuses author biographies and portraits: the shelf knows
a name and nothing else about a person, which is what keeps an author a derived
fact. Wikidata is read here for **identity and disambiguation only**.

Both suppliers offer more, in fields that are right there in a response already
parsed: lobid's `depiction` is a portrait and its
`biographicalOrHistoricalInformation` reads
"Lebte ab 1888 auf Westsamoa, starb in dem Dorf Vailima, nahe Apia, Samoa", and
Wikidata's `props=claims` is a body of work. None of the three is read, and
`tests/test_authority.py::TestTheRefusalsAreStructural` fails if one starts
being, because a refusal a reviewer has to remember is a refusal that lapses.

**Nothing this module returns is stored.** The one line description and the
dates exist so a person can tell two same named people apart at the moment they
confirm; the only thing any of this can write is an identifier, through
`Authorship.confirm_identifier`. There is no column for a description and this
module has no session.

## The boundary, which is every catalogue source's plus two

* **Two fixed HTTPS hosts**, never a host from a response. `fetch.get_once`
  refuses a cross host redirect on its own, and nothing here follows a `sameAs`
  link: those are recorded and shown, never fetched.
* **The identifiers are validated before they reach a URL.** `_GND_NUMBER` and
  `_ITEM_ID` are anchored. Without the first, a hand edited row holding
  `../search` is a path traversal inside lobid, and httpx will not encode that
  away because a path separator in a formatted string is a path separator.
* **The name is escaped before it reaches the query, and the query is not a
  phrase.** Both halves are measured rather than chosen: a quoted
  `preferredName` phrase cannot match, because this app stores a name in
  reading order and the GND writes it in catalogue order, and an unescaped
  Lucene query makes lobid answer **500** on an author's name containing `(`.
  `_LUCENE_ESCAPED` and `_PERSON_FILTER` carry both measurements.
* **Every response is bounded well under `fetch.MAX_RESPONSE_BYTES`**, and the
  reason is a measurement rather than caution: `wbgetentities` with
  `props=claims` on one well documented person is **243,864 bytes**, against 341
  for the labels and descriptions this module actually asks for. Asking for the
  default would be a quarter of a megabyte per candidate.
* **Both branches are bounded, in count and in time, and the count alone was
  not enough.** A name search costs one lobid request plus two Wikidata requests
  per candidate, capped by `MAX_CANDIDATES`. The **resolve** branch is one
  candidate per stored identifier, which is one per spelling folded into a
  person, so it had no ceiling at all: 40 spellings measured out at 160
  outbound requests and a 1,600 second worst case, with a `DbSession` held
  across every await. The router slices to `MAX_CANDIDATES` and every call in
  one lookup shares one absolute `DEADLINE_SECONDS`.

**No cover host is added**, and none could be: `covers.COVER_HOSTS` is what the
CSP's `img-src` is derived from, and nothing here returns an image. That is the
same sentence as the `depiction` refusal above, arrived at from the other side.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Final

import fetch
from enums import AuthorityScheme

logger = logging.getLogger("endpaper.authority")

#: The two hosts this module talks to. Written out whole rather than composed,
#: so a reader sees the entire URL in one place.
_LOBID_RECORD_URL: Final = "https://lobid.org/gnd/{identifier}.json"
_LOBID_SEARCH_URL: Final = "https://lobid.org/gnd/search"
_WIKIDATA_URL: Final = "https://www.wikidata.org/w/api.php"

#: The Wikidata property that carries a GND identifier, and the one that carries
#: a VIAF cluster id.
#:
#: Written as constants because they appear in a query string where a typo is a
#: **zero result rather than an error**: `haswbstatement:P228=...` is a valid
#: search for a property that is not this one, and it answers 200 with no hits,
#: which reads exactly like "this person has no Wikidata item".
_P_GND: Final = "P227"
_P_VIAF: Final = "P214"

#: What a GND number may contain, anchored at both ends.
#:
#: Digits, an optional check character `X`, and hyphens: `118753711`,
#: `4203576-4`. **A URL safety check before it is a validation**, because the
#: identifier is interpolated into a path.
_GND_NUMBER: Final = re.compile(r"\A[0-9X-]{1,20}\Z")

#: What a Wikidata item id may contain. `Q` and digits, nothing else.
_ITEM_ID: Final = re.compile(r"\AQ[0-9]{1,15}\Z")

#: Where a VIAF cluster id sits inside the URI lobid records for it.
_VIAF_URI: Final = re.compile(r"\Ahttps?://viaf\.org/viaf/([0-9]+)/?\Z")

#: Where a Wikidata item id sits inside the URI lobid records for it.
_ITEM_URI: Final = re.compile(r"\Ahttps?://(?:www\.)?wikidata\.org/entity/(Q[0-9]+)\Z")

#: Every character Lucene reserves, each escaped with a backslash.
#:
#: **The query is unquoted, and that decision is what makes this list long.** A
#: quoted phrase would need only `"` and `\\` escaped, and a quoted phrase is
#: unusable here: this app stores a name in reading order and the GND writes it
#: in catalogue order, so `preferredName:"Robert Louis Stevenson"` answers with
#: **a conference and a school and neither Stevenson**, while the unquoted form
#: matches either order. Measured 2026-08-27, both directions, 60 hits each.
#:
#: **Escaping is then mandatory rather than defensive**, and that is measured
#: too: `q=Stevenson (` answers **HTTP 500 with an HTML body**, and a `(` in an
#: author's name is ordinary catalogue data. It also closes the injection the
#: quoted form had: `Stevenson" OR preferredName:"Kane` is two clauses
#: unescaped and three literal terms escaped.
#:
#: `&` and `|` are escaped singly, which covers Lucene's `&&` and `||`. The bare
#: word operators `AND`, `OR` and `NOT` are **not** escapable and are left
#: alone: lobid's default operator is already OR, so a name containing one
#: broadens the search rather than changing its meaning, and no parse error is
#: reachable through them.
_LUCENE_ESCAPED: Final = str.maketrans(
    {character: f"\\{character}" for character in '\\+-!(){}[]^"~*?:|&/'}
)

#: What a GND search is narrowed to.
#:
#: **Without it a name search answers with things that are not people.**
#: Measured 2026-08-27, `Robert Louis Stevenson` returns 117 records led by a
#: conference and a school; with this filter it returns 60, led by the two
#: people. `UndifferentiatedPerson` is excluded by the same line and that is
#: the sharper half: such a record deliberately conflates several people the
#: GND could not tell apart, so offering one as an identity would store an
#: identifier that means "somebody, we are not sure who".
_PERSON_FILTER: Final = "type:DifferentiatedPerson"

#: How many people a name search may offer, and therefore how far the Wikidata
#: fan out reaches.
#:
#: Small on purpose. This is a list somebody reads and picks from, and a name
#: matching forty people is one to narrow rather than scroll. It is also what
#: bounds this module's share of lobid's "complex search" guidance and of
#: Wikidata's request budget: one lobid request plus two Wikidata requests per
#: candidate, so at most eleven.
MAX_CANDIDATES: Final = 5

#: Bytes any one response may bring back.
#:
#: Measured live 2026-08-27: a GND record is 7,731 bytes, a three result search
#: 17,760, a `haswbstatement` search 606, and labels and descriptions in two
#: languages 341. This is far above all four and far below
#: `fetch.MAX_RESPONSE_BYTES`, which is the point: the general cap is sized for
#: a catalogue record carrying a thousand subject headings, and nothing asked
#: for here is that shape.
_RESPONSE_LIMIT: Final = 262_144

#: How long the whole of one authority lookup may take, in seconds.
#:
#: **A shared, absolute deadline covering every request a call makes**, not a
#: per request timeout. `fetch.get_once` gives each call its own
#: `TIMEOUT_SECONDS` budget when it is passed none, so N calls in one handler
#: were N fresh budgets: the resolve branch with 40 spellings folded into one
#: person was 160 outbound requests and a **1,600 second** worst case, with a
#: `DbSession` held across every await of it. Fifteen such calls exhaust
#: `QueuePool` and the next request anywhere in the app waits 30 seconds and
#: then errors.
#:
#: 8.0 against a measured worst path of about 1.0s: live on 2026-08-27 a lobid
#: record is 0.11 to 0.13s, its search 0.13 to 0.22s, and Wikidata's three calls
#: 0.22 to 0.29s each. `_cross_check` is three of those in sequence, so one
#: candidate is roughly 1.0s and the candidates run together. The margin is for
#: a slow day, not for a bigger fan out: that is what `MAX_CANDIDATES` bounds.
#:
#: The same shape as `metadata.SEARCH_DEADLINE_SECONDS`, which is 4.0 for a
#: fan out one level shallower.
DEADLINE_SECONDS: Final = 8.0


def deadline_from_now() -> float:
    """One absolute deadline for a whole lookup, for a caller making several.

    `fetch.get` takes an absolute monotonic timestamp rather than a duration,
    which is what lets one value bound a chain instead of each link.
    """
    return time.monotonic() + DEADLINE_SECONDS


#: The longest name that may be put to a search.
#:
#: Smaller than `AUTHOR_NAME_MAX`, because a name goes into a query string
#: rather than into a column: escaping doubles the worst case, and a 300
#: character "name" is not a person either file holds.
MAX_QUERY_NAME: Final = 120

#: Which languages a description is asked for, best first.
#:
#: Two rather than the member's own locale, and that is a deliberate narrowing:
#: this is a disambiguation hint rather than content, the app has two locales,
#: and asking for every language is how the 341 byte response becomes a large
#: one.
_DESCRIPTION_LANGUAGES: Final = ("en", "de")


@dataclass(frozen=True, slots=True)
class Disagreement:
    """Two authority files pointing at different records for one person.

    **Surfaced, never resolved by precedence.** Neither file is the authority on
    the other, and a rule picking a winner would decide silently exactly where a
    person should be asked. This is the same call `AuthorOut.identifier_conflicts`
    makes for two local spellings, at the other end of the same feature.

    `about` names the cross reference rather than the source, because that is
    what a reader has to look up: `wikidata` when the two files disagree about
    which item this person is, `viaf` when they disagree about the cluster.
    """

    about: str
    lobid: str | None
    wikidata: str | None


@dataclass(frozen=True, slots=True)
class AuthorityCandidate:
    """One person an authority file holds, as this app reads them.

    **A candidate, whatever route produced it.** `certain` says which route that
    was, and the feature turns on it: an identifier already asserted for this
    Book resolves to exactly one record, so the spelling beside it can be
    offered with confidence. A name search returns people who share a name,
    which is a guess, and the proof is committed as a fixture rather than
    argued: `Stevenson, Robert Louis` matches two distinct differentiated
    persons in the GND, `118753711` and `131572873`.

    **`wikidata_id` being None is a disambiguation hint and never a rule.** Of
    that pair only `118753711` has a Wikidata item; `haswbstatement:P227=131572873`
    returns zero hits. Showing that to the person confirming is the feature.
    Using it to pick for them is the silent merge the confirmation step exists
    to prevent.

    `variants` is the authority's own list of other spellings and is
    deliberately **not** fed to `author_aliases`. Two different kinds of claim:
    an alias row is this Household saying two spellings mean one person, and
    this is a national library saying its record has other forms. Folding one
    into the other turns a curated decision into a generated one, which is what
    `AuthorityProvenance` exists to keep apart. It is shown, so a member can
    make that decision themselves.

    `born` and `died` are the dates as the GND writes them, which is a partial
    date on many records (`1850-11-13`, or `1850`, or absent). Kept as strings
    rather than parsed: nothing here sorts or subtracts them, and parsing would
    turn a record with `XXXX` in it into an error instead of a hint.

    **Nothing here is stored.** The only thing this whole path can write is an
    identifier: see the module docstring.
    """

    scheme: AuthorityScheme
    identifier: str
    name: str
    variants: tuple[str, ...] = ()
    born: str | None = None
    died: str | None = None
    #: Every cross reference the GND record lists, as URIs. Recorded, shown,
    #: never fetched. This is where the VIAF cluster id arrives.
    same_as: tuple[str, ...] = ()
    certain: bool = False
    #: The Wikidata item, from Wikidata's own reverse lookup rather than from
    #: lobid's `sameAs`. None where Wikidata holds no item for this person.
    wikidata_id: str | None = None
    #: Wikidata's one line description, in `en` or `de`. Identity and
    #: disambiguation only: see the refusal in the module docstring.
    description: str | None = None
    disagreements: tuple[Disagreement, ...] = ()


class AuthorityUnavailable(Exception):
    """lobid did not answer, or answered something this module cannot read.

    One exception for both, because the caller's options are the same: say the
    suggestion could not be fetched. Nobody is blocked by it, since every write
    in this feature is optional.

    **Wikidata failing does not raise.** It is the cross check rather than the
    supplier, so an outage there costs the description and the disagreement
    report and leaves the GND answer standing. `_cross_check` swallows and logs.
    """


def _escaped(name: str) -> str:
    """One name as a Lucene query, every reserved character neutralised.

    Truncated **before** escaping, so the bound is on what a member sent rather
    than on what escaping made of it: escaping can double the length, and the
    cap is meant to bound the request rather than the name.
    """
    return name[:MAX_QUERY_NAME].translate(_LUCENE_ESCAPED)


def _first_string(value: Any) -> str | None:
    """The first usable string in a lobid list valued field."""
    if not isinstance(value, list):
        return None
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
    return None


def _candidate(record: Any, *, certain: bool) -> AuthorityCandidate | None:
    """One lobid JSON object as a candidate, or None if it is not usable.

    **Dropped rather than raised**, the call every parser in `metadata.py`
    makes: a record with no `preferredName` or no `gndIdentifier` is nothing
    this app can offer, and one bad member of a search result should not cost
    the other four.
    """
    if not isinstance(record, dict):
        return None
    name = record.get("preferredName")
    identifier = record.get("gndIdentifier")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(identifier, str) or not _GND_NUMBER.match(identifier):
        return None
    return AuthorityCandidate(
        scheme=AuthorityScheme.GND,
        identifier=identifier,
        name=name.strip(),
        variants=tuple(
            value.strip()
            for value in record.get("variantName") or ()
            if isinstance(value, str) and value.strip()
        ),
        born=_first_string(record.get("dateOfBirth")),
        died=_first_string(record.get("dateOfDeath")),
        # `sameAs` members are objects carrying an `id`.
        #
        # **Restricted to `http` and `https`.** Nothing renders this yet, and
        # the obvious rendering is a link, so the contract is being frozen now
        # with the scheme checked rather than later with a `javascript:` URI
        # from a third party already in the shape. The same rule
        # `custom_fields.link_target` applies to a value a member typed, applied
        # to one an authority file supplied.
        same_as=tuple(
            entry["id"]
            for entry in record.get("sameAs") or ()
            if isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and entry["id"].lower().startswith(("http://", "https://"))
        ),
        certain=certain,
    )


def _matched(pattern: re.Pattern[str], uris: tuple[str, ...]) -> str | None:
    """The first id one of these URIs carries, or None if none does."""
    for uri in uris:
        found = pattern.match(uri)
        if found is not None:
            return found.group(1)
    return None


async def _wikidata(params: dict[str, str], deadline: float | None) -> Any:
    """One bounded call to the Wikidata API, or None if it did not work.

    Returns None rather than raising, because every caller is the cross check
    rather than the supplier. See `AuthorityUnavailable`.
    """
    try:
        response = await fetch.get_once(
            _WIKIDATA_URL,
            params={"format": "json", **params},
            limit=_RESPONSE_LIMIT,
            deadline=deadline,
        )
        if response.status_code != 200:
            logger.info("Wikidata answered %s", response.status_code)
            return None
        return response.json()
    except Exception:
        logger.info("Wikidata did not answer", exc_info=True)
        return None


async def _item_for(gnd: str, deadline: float | None) -> str | None:
    """The Wikidata item whose `P227` is this GND number, found by Wikidata.

    **Not read from lobid's `sameAs`**, and that is the whole point of the second
    supplier: two independent assertions about one link can be compared, and one
    copied from the other cannot.

    Zero hits is an ordinary answer and means Wikidata holds no item for this
    person. It is a hint for whoever is confirming and never a rule: see
    `AuthorityCandidate`.
    """
    body = await _wikidata(
        {
            "action": "query",
            "list": "search",
            "srsearch": f"haswbstatement:{_P_GND}={gnd}",
            "srlimit": "1",
        },
        deadline,
    )
    if not isinstance(body, dict):
        return None
    hits = (body.get("query") or {}).get("search") or []
    if not hits or not isinstance(hits[0], dict):
        return None
    title = hits[0].get("title")
    return title if isinstance(title, str) and _ITEM_ID.match(title) else None


async def _description_of(item: str, deadline: float | None) -> str | None:
    """Wikidata's one line description of an item, in English or German.

    **`props=labels|descriptions` and nothing else**, which is the difference
    between 341 bytes and 243,864: see the module docstring. `props=claims` is
    a body of work and is refused rather than merely unasked for.
    """
    body = await _wikidata(
        {
            "action": "wbgetentities",
            "ids": item,
            "props": "labels|descriptions",
            "languages": "|".join(_DESCRIPTION_LANGUAGES),
        },
        deadline,
    )
    if not isinstance(body, dict):
        return None
    entity = (body.get("entities") or {}).get(item) or {}
    descriptions = entity.get("descriptions") or {}
    for language in _DESCRIPTION_LANGUAGES:
        entry = descriptions.get(language)
        if isinstance(entry, dict) and isinstance(entry.get("value"), str):
            return entry["value"].strip() or None
    return None


async def _claim(item: str, prop: str, deadline: float | None) -> str | None:
    """One property's first value on an item, asked for by name.

    `wbgetclaims` with a `property` filter, which is 3,461 bytes for `P214`
    against 243,864 for every claim the item carries.
    """
    body = await _wikidata(
        {"action": "wbgetclaims", "entity": item, "property": prop}, deadline
    )
    if not isinstance(body, dict):
        return None
    for statement in (body.get("claims") or {}).get(prop) or []:
        if not isinstance(statement, dict):
            continue
        value = ((statement.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value:
            return value
    return None


def _disagreements(
    candidate: AuthorityCandidate, item: str | None, viaf: str | None
) -> tuple[Disagreement, ...]:
    """Where the two files point at different records for one person.

    **Only where both have said something.** One file being silent is not a
    disagreement: Wikidata holding no item is the ordinary case for a minor
    author, and reporting it as a conflict would bury the real ones.

    Two comparisons, and the second is the only one that costs a request:

    * **the item itself**, lobid's `sameAs` against Wikidata's reverse lookup on
      `P227`. Free, because both are already in hand, and it is the comparison
      that matters: it says whether the two files agree this is one person.
    * **the VIAF cluster**, lobid's `sameAs` against `P214`. One request.

    **ISNI is deliberately not compared, and the reason has to separate it from
    VIAF, which is.** Both are carried by both files (lobid in `sameAs`,
    Wikidata as `P213` and `P214`) and neither is stored here, so "nothing
    stores it" cannot be the reason or it would rule out both.

    The separating reason is what each cross reference is *for* in this
    codebase. **VIAF is the identifier this whole feature was written around**,
    and it was dropped as a supplier because the GND arrives directly. Carrying
    it and checking it is the evidence that nothing was lost by not calling
    VIAF: `same_as` holds the cluster id and `P214` independently agrees with
    it. ISNI has no such history here, so comparing it would be a third detector
    of a fault two already detect, at one more request per candidate. Raise it
    rather than adding it quietly if ISNI ever becomes something this app cites.
    """
    found: list[Disagreement] = []
    lobid_item = _matched(_ITEM_URI, candidate.same_as)
    if lobid_item is not None and item is not None and lobid_item != item:
        found.append(Disagreement(about="wikidata", lobid=lobid_item, wikidata=item))
    lobid_viaf = _matched(_VIAF_URI, candidate.same_as)
    if lobid_viaf is not None and viaf is not None and lobid_viaf != viaf:
        found.append(Disagreement(about="viaf", lobid=lobid_viaf, wikidata=viaf))
    return tuple(found)


async def _cross_check(
    candidate: AuthorityCandidate, *, compare_viaf: bool, deadline: float | None
) -> AuthorityCandidate:
    """The same candidate, with what Wikidata knows about it.

    **`compare_viaf` splits the cost by how much the answer is worth**, and the
    split is the two routes rather than a tuning knob. A `resolve` has one
    person in hand and the cross reference is the point, so it pays for the
    `P214` request. A `search` has up to five people and the question is which
    of them somebody means, so it buys the description and the item's existence
    and stops: five candidates would otherwise be fifteen requests to two
    services for a list the member is about to narrow to one anyway.

    Never raises. Wikidata is the cross check and not the supplier.
    """
    item = await _item_for(candidate.identifier, deadline)
    if item is None:
        return candidate
    description = await _description_of(item, deadline)
    viaf = await _claim(item, _P_VIAF, deadline) if compare_viaf else None
    return replace(
        candidate,
        wikidata_id=item,
        description=description,
        disagreements=_disagreements(candidate, item, viaf),
    )


async def resolve(
    identifier: str, *, deadline: float | None = None
) -> AuthorityCandidate | None:
    """The one person a GND number names, or None if the file does not hold it.

    **Certain**, and the certainty comes from the argument rather than from
    lobid: an identifier is a key, so there is exactly one record behind it. The
    caller is responsible for the identifier having come from a catalogue record
    for this Book rather than from a guess, which is the same division
    `Authorship.record_catalogue_assertions` documents.

    A number this module would not put in a URL answers None rather than
    raising: a row holding one is a hand edit or a restore, and the honest
    answer to "what does the authority say about this" is nothing.
    """
    if not _GND_NUMBER.match(identifier):
        logger.info("Refused to resolve an identifier that is not a GND number")
        return None
    body = await _lobid(
        _LOBID_RECORD_URL.format(identifier=identifier),
        allow_404=True,
        deadline=deadline,
    )
    if body is None:
        return None
    candidate = _candidate(body, certain=True)
    if candidate is None:
        return None
    return await _cross_check(candidate, compare_viaf=True, deadline=deadline)


async def search(
    name: str, *, deadline: float | None = None
) -> list[AuthorityCandidate]:
    """The people an authority file holds under one name. A guess, every time.

    **A name is not a key**, which is the entire reason the confirmation step
    exists, and it is demonstrated rather than asserted: `Stevenson, Robert
    Louis` matches two differentiated persons. Nothing here decides between them
    and nothing here writes: `POST /authors/identifiers` is where a Member says
    which one it is.

    An empty or unusable name answers an empty list rather than putting a
    useless query to somebody else's service.
    """
    query = _escaped(name.strip())
    if not query:
        return []
    body = await _lobid(
        _LOBID_SEARCH_URL,
        params={
            "q": query,
            "filter": _PERSON_FILTER,
            "format": "json",
            "size": str(MAX_CANDIDATES),
        },
        deadline=deadline,
    )
    if not isinstance(body, dict):
        raise AuthorityUnavailable
    members = body.get("member")
    if not isinstance(members, list):
        return []
    found = [_candidate(record, certain=False) for record in members]
    # Bounded again here rather than trusting `size`: the parameter is a request
    # and the answer is somebody else's, so a service that ignored it would
    # otherwise decide how long this list is, and with it how many Wikidata
    # requests one member action makes.
    kept = [row for row in found if row is not None][:MAX_CANDIDATES]
    return list(
        await asyncio.gather(
            *(
                _cross_check(row, compare_viaf=False, deadline=deadline)
                for row in kept
            )
        )
    )


async def _lobid(
    url: str,
    *,
    params: dict[str, str] | None = None,
    allow_404: bool = False,
    deadline: float | None = None,
) -> Any:
    """One bounded call to lobid, parsed, or `AuthorityUnavailable`.

    Unlike `_wikidata` this raises, because lobid is the supplier: an answer
    that is not there is not a degraded answer, it is no answer.
    """
    try:
        response = await fetch.get_once(
            url, params=params, limit=_RESPONSE_LIMIT, deadline=deadline
        )
    except Exception as failure:
        raise AuthorityUnavailable from failure
    if allow_404 and response.status_code == 404:
        return None
    if response.status_code != 200:
        raise AuthorityUnavailable
    try:
        return response.json()
    except ValueError as failure:
        raise AuthorityUnavailable from failure
