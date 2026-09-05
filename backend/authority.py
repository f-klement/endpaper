"""The authority files, read for a person rather than for a book.

`metadata.py` asks catalogues about **books**; this module asks three authority
files about **people**. A book record describes a printing and dies with it; an
authority record describes somebody who outlives every printing.

## Two suppliers, one comparator, one enrichment

**lobid.org** serves the GND, which the DNB already cites in MARC `100 $0`.
**Wikidata** is the cross check: where the two disagree the disagreement is
**surfaced and never resolved by precedence**, which is `Disagreement`.

**The join is verifiable in both directions**, and that is what makes it worth
two requests. lobid's `sameAs` on a GND number asserts a Wikidata item, and
Wikidata's `haswbstatement:P227` independently returns the same one. Neither was
told the other's answer.

**Wikidata has a second job and the two must not be confused.** On the six
national library numbers it is a **fallback supplier**, asked only where VIAF
produced no cluster, never a comparator. One supplier speaks per confirmation, so
the report-never-adjudicate rule is untouched.

**VIAF is never an entry point.** `resolve` and `search` do not touch it, so a
lookup a member is reading costs nothing extra. It is asked by
`national_identifiers` alone, after a member has confirmed a GND record, for the
numbers that record's `sameAs` does not carry. A cluster names the GND record it
was built from, so it is checked against an identifier already in hand rather
than trusted on a name.

## Why VIAF is not a supplier

**Half of its read API answers, and which half depends on the `Accept` header
alone**, not on the path. That is easy to probe wrongly in either direction,
which is why the finding is recorded here rather than left to be rediscovered.

## Terms, read rather than assumed

**lobid** states its licence in every response. **Wikidata** publishes CC0 through
`rightsinfo`, and its 403 on a default user agent is why `fetch._AGENT` exists.
**VIAF publishes neither**, which is measured rather than assumed and is one
reason it stays out of the resolution path.

## The refusal this module is built around

**The only thing any of this can write is an identifier.** Not a name, not a
date, not a description: a person's own record stays what a member typed, and an
authority file can only ever attach a number to it.

## The boundary

Every catalogue source's, plus lobid and Wikidata. **No cover host is added and
none could be**: `covers.COVER_HOSTS` is what the CSP is derived from, so a host
added here would widen what the browser may load.
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

#: The Wikidata properties this module reads: the GND identifier it joins on,
#: and the two cross references it compares.
#:
#: Written as constants because they appear in a query string where a typo is a
#: **zero result rather than an error**: `haswbstatement:P228=...` is a valid
#: search for a property that is not this one, and it answers 200 with no hits,
#: which reads exactly like "this person has no Wikidata item".
_P_GND: Final = "P227"
_P_VIAF: Final = "P214"
_P_ISNI: Final = "P213"

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

#: Where an ISNI sits inside the URI lobid records for it.
#:
#: Sixteen characters, digits with an optional `X` as the last, which is the ISO
#: 27729 check character. Unspaced here: the URI form carries no separators even
#: though the printed form does, and storing the URI's form is what keeps one
#: person from arriving under two spellings that
#: `uq_author_identifiers_key_scheme` cannot collapse. The same rule
#: `AuthorIdentifier.identifier` states for MARC's `(DE-588)` wrapper.
_ISNI_URI: Final = re.compile(r"\Ahttps?://(?:www\.)?isni\.org/isni/([0-9]{15}[0-9X])\Z")

#: Where an LCNAF control number sits inside the URI lobid records for it.
#:
#: **Two paths, because `id.loc.gov` serves several files under one host and
#: lobid uses whichever the record was written with.** `rwo/agents` is the real
#: world object and `authorities/names` is the authority record about it;
#: measured 2026-08-28, fourteen GND records all carried the first. Both are
#: matched and neither is preferred, because they carry the same control number.
#:
#: **`authorities/subjects` is deliberately unmatched.** It is the same host and
#: the same shape and it names a subject heading rather than a person, which is
#: the exact confusion `ClassificationScheme` and `AuthorityScheme` exist as two
#: enums to prevent.
_LCNAF_URI: Final = re.compile(
    r"\Ahttps?://id\.loc\.gov/(?:rwo/agents|authorities/names)/(n[a-z]?[0-9]{6,10})\Z"
)

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
#: Re-measured live 2026-08-28, and **two of the four figures this comment used
#: to carry were wrong**, one of them by a factor that changes what the constant
#: is guarding:
#:
#: | Ask | Was stated | Measures |
#: |---|---|---|
#: | a GND record | 7,731 | **13,249**, three times of three |
#: | a name search | 17,760 at `size=3` | **37,923 to 241,691** at `size=5` |
#: | a `haswbstatement` search | 606 | 606 |
#: | labels and descriptions | 341 | 341 |
#:
#: **The search is the binding case and it is asked for at `MAX_CANDIDATES`,
#: which is five, not three.** Its size is driven by the five records rather
#: than by the query: `Robert Louis Stevenson` is 37,923 bytes and a bare common
#: surname is 180,000 to 241,691, measured over ten names on 2026-08-28
#: (`Lee` 241,691, `Schmidt` 239,314, `Bach` 238,107, `Muller` 237,293,
#: `Fischer` 237,111).
#:
#: **So this is 1.08x the largest measured answer, not "far above" it**, and
#: that sentence is gone rather than softened. `_VIAF_LIMIT`'s own comment
#: records what happened the last time a margin near 1.5x was set from a sample.
#: Raising it is not free and is deliberately not done here: it is asserted
#: **below** 276,610 by
#: `tests/test_authority.py::TestTheViafResponseBoundIsSeparateAndLargerThanTheOthers`,
#: which is how `_VIAF_LIMIT` is shown to have a reason to exist, so moving this
#: number rewrites that relationship and both entries describing it.
#: `test_the_general_bound_still_clears_the_largest_measured_search` pins the
#: margin so it is visible rather than asserted.
#:
#: It is still far below `fetch.MAX_RESPONSE_BYTES`, which is the other half of
#: the point: the general cap is sized for a catalogue record carrying a
#: thousand subject headings.
#:
#: **A VIAF cluster is that shape**, which is why it does not use this constant.
#: Measured 2026-08-28, a `BriefVIAF` response alone reaches 276,610 bytes and
#: would be refused here. See `_VIAF_LIMIT`, which is why this comment now says
#: "lobid or Wikidata" where it used to say "here".
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
#: 8.0 against a measured worst path of about 1.3s for a lookup: live on
#: 2026-08-27 a lobid record is 0.11 to 0.13s, its search 0.13 to 0.22s, and
#: Wikidata's calls 0.22 to 0.29s each. `_cross_check` is **four** of those in
#: sequence on the resolve branch since `P213` joined `P214`, so one candidate
#: is roughly 1.3s and the candidates run together. The search branch is two,
#: unchanged. The margin is for a slow day, not for a bigger fan out: that is
#: what `MAX_CANDIDATES` bounds.
#:
#: **A confirmation is the longer path and the figure above is not it.** It is
#: one resolve plus `national_identifiers`, whose three VIAF calls measured 0.56,
#: 0.75 and 1.81 seconds at their worst on 2026-08-28, so about **4.4s** in
#: total against this 8.0. That is 1.8x rather than 6x, and it is the number to
#: re-derive before adding a fourth call to that path. The third of the three is
#: paid only on a 5xx, so the common confirmation is nearer 2.6s.
#:
#: **The Wikidata fallback does not move that worst case, and the reason is the
#: shape of the branch rather than the size of the calls.** Its six
#: `wbgetclaims` measured 1.49s together on 2026-08-28, but they run only where
#: VIAF produced no cluster, which means the 0.75 and the 1.81 above were not
#: paid: the fallback's own path is one resolve at about 1.3s plus whatever the
#: failing VIAF calls cost before they gave up, plus 1.49s. Two calls timing out
#: at `fetch.TIMEOUT_SECONDS` would exceed 8.0 on their own, and that is what
#: the absolute deadline is for: the fallback then runs against a budget already
#: spent and answers nothing, which is the same empty mapping VIAF being down
#: gave before it existed.
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
    which item this person is, `viaf` when they disagree about the cluster,
    `isni` when they disagree about the person's ISO 27729 number.

    **It is an `AuthorityScheme` value, and that is load bearing rather than a
    coincidence.** `authority.cross_references` refuses to store a scheme named
    here, and it matches on this string, so the three literals are written as
    `AuthorityScheme.X.value` rather than spelled out. Typed `str` because the
    field is a report about a cross reference and not a claim that one is
    storable, and because a fourth thing two files can disagree about need not
    be a scheme at all.
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


async def _claims(item: str, prop: str, deadline: float | None) -> tuple[str, ...]:
    """Every distinct value an item carries for one property, asked for by name.

    `wbgetclaims` with a `property` filter, which is 3,461 bytes for `P214` and
    281 to 524 for the six national properties, against 243,864 for every claim
    the item carries.

    **All of them rather than the first, because one of the two callers stores
    what it gets.** `_claim` below wants the first and says so; the national
    fallback wants to know whether there *is* only one, which is the same drop
    rule `_viaf_sources` applies to a code a cluster names twice. Measured
    2026-08-28 through the Wikidata query service, humans (`P31=Q5`) carrying
    more than one truthy value: `P950` 4,955 of 235,481, `P396` 3,270, `P1005`
    899, `P3788` 156 of 8,645, `P4619` 72 of 24,420, `P1890` 44 of 4,081. One
    of them is `Q5682`, Cervantes, with **eight** `P3788` values. So taking the
    first would be resolution by ordering for nine thousand people.

    **A `deprecated` statement is skipped**, and it is the one rank that means
    something here: Wikidata uses it for a value known to be wrong, so reading
    one would store a number the source itself has withdrawn. `preferred` and
    `normal` are both kept, because a property with one preferred value and one
    normal value is still a property this app cannot pick between.

    Repeats are collapsed rather than counted. Two statements carrying the same
    number are one fact stated twice, which is not the ambiguity the caller is
    testing for: the same call `_viaf_sources` makes with `found[code] !=
    identifier`.
    """
    body = await _wikidata(
        {"action": "wbgetclaims", "entity": item, "property": prop}, deadline
    )
    if not isinstance(body, dict):
        return ()
    found: list[str] = []
    for statement in (body.get("claims") or {}).get(prop) or []:
        if not isinstance(statement, dict):
            continue
        if statement.get("rank") == "deprecated":
            continue
        value = ((statement.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value and value not in found:
            found.append(value)
    return tuple(found)


async def _claim(item: str, prop: str, deadline: float | None) -> str | None:
    """One property's first value on an item, asked for by name.

    The comparison half of `_claims`. `_disagreements` reports a mismatch and
    never stores one, so the first value is enough: what it needs to know is
    whether the two files are saying the same thing, and a second value on the
    Wikidata side cannot make a first one match.
    """
    values = await _claims(item, prop, deadline)
    return values[0] if values else None


def _disagreements(
    candidate: AuthorityCandidate,
    item: str | None,
    viaf: str | None,
    isni: str | None,
) -> tuple[Disagreement, ...]:
    """Where the two files point at different records for one person.

    **Only where both have said something.** One file being silent is not a
    disagreement: Wikidata holding no item is the ordinary case for a minor
    author, and reporting it as a conflict would bury the real ones.

    Three comparisons, and the first is the only free one:

    * **the item itself**, lobid's `sameAs` against Wikidata's reverse lookup on
      `P227`. Free, because both are already in hand, and it is the comparison
      that matters: it says whether the two files agree this is one person.
    * **the VIAF cluster**, lobid's `sameAs` against `P214`. One request.
    * **the ISNI**, lobid's `sameAs` against `P213`. One request.

    ## ISNI used to be excluded here, and this is the entry that says why it is
    ## not any more

    The previous version of this docstring recorded a deliberate refusal to
    compare ISNI, and it named its own trigger: "raise it rather than adding it
    quietly if ISNI ever becomes something this app cites". **That trigger has
    fired**, and this replaces the entry rather than deleting it, because the
    old reasoning is what makes the new decision checkable.

    The refusal rested on ISNI being neither stored nor cited, so a comparison
    would have been "a third detector of a fault two already detect, at one more
    request per candidate". Both halves have changed:

    * **ISNI is now stored.** `cross_references` writes it, and
      `authorship.IDENTITY_SPINE` is the one line that makes it the spine. A
      wrong VIAF cluster shown on a screen is corrected by looking again; a
      wrong ISNI written to `author_identifiers` is a durable row, and
      `AuthorIdentifier` refuses to retype one, so the correction is a delete.
    * **The detectors are no longer redundant**, because `cross_references`
      refuses to store any scheme named here. Without a `P213` comparison an
      ISNI disagreement is undetectable, and the rule that keeps a contested
      identifier out of the table would have nothing to act on for the one
      scheme it matters most for.

    The cost is unchanged in shape and known in size: one `wbgetclaims` request,
    on the resolve branch only, alongside the `P214` one that was already there.
    A name search still buys neither: see `_cross_check`.
    """
    found: list[Disagreement] = []
    lobid_item = _matched(_ITEM_URI, candidate.same_as)
    if lobid_item is not None and item is not None and lobid_item != item:
        found.append(Disagreement(about=AuthorityScheme.WIKIDATA.value, lobid=lobid_item, wikidata=item))
    lobid_viaf = _matched(_VIAF_URI, candidate.same_as)
    if lobid_viaf is not None and viaf is not None and lobid_viaf != viaf:
        found.append(Disagreement(about=AuthorityScheme.VIAF.value, lobid=lobid_viaf, wikidata=viaf))
    lobid_isni = _matched(_ISNI_URI, candidate.same_as)
    if lobid_isni is not None and isni is not None and lobid_isni != isni:
        found.append(Disagreement(about=AuthorityScheme.ISNI.value, lobid=lobid_isni, wikidata=isni))
    return tuple(found)


#: Which `sameAs` URI carries which scheme's identifier.
#:
#: A mapping rather than four `if` arms, so `cross_references` cannot grow a
#: scheme the pattern list does not know about, and so the set is readable in
#: one place beside `AuthorityScheme`.
#:
#: **Not every member of `AuthorityScheme` is here, and that is the split
#: between the two writers.** These four arrive in a `sameAs` block for free;
#: the six national files arrive only from a VIAF cluster and are listed in
#: `_NATIONAL_SOURCES`. A scheme in neither is a member nothing writes.
_CROSS_REFERENCE_URIS: Final = {
    AuthorityScheme.ISNI: _ISNI_URI,
    AuthorityScheme.LCNAF: _LCNAF_URI,
    AuthorityScheme.VIAF: _VIAF_URI,
    AuthorityScheme.WIKIDATA: _ITEM_URI,
}


def cross_references(candidate: AuthorityCandidate) -> dict[AuthorityScheme, str]:
    """The other files' identifiers this GND record already carries.

    **Free.** Every one of these arrives in the `sameAs` block of a response
    this module has already fetched and parsed, and until now every one was
    handed to the client and dropped. Measured 2026-08-28 over fourteen GND
    records spanning Spanish, Portuguese, Brazilian, Argentine, Uruguayan and
    Italian authors: all fourteen carried ISNI, LCNAF, VIAF and Wikidata.

    **The candidate's own scheme is never in the result.** This returns the
    cross references and not the identity, so a caller storing both stores the
    GND from the candidate and these beside it, and nothing here can overwrite
    the thing that was confirmed.

    **A scheme this candidate disagrees about is omitted, and that rule is the
    reason `_disagreements` now compares ISNI.** A disagreement means the two
    files name different records, so storing either side is resolution by
    precedence, which is the one thing this whole feature refuses to do. The
    identifier is still shown: `AuthorityCandidateOut.same_as` carries every URI
    and `disagreements` carries the conflict, so nothing is hidden, it is only
    not written down.

    **Wikidata is taken from `wikidata_id` where there is one**, because that is
    Wikidata's own reverse lookup on `P227` rather than lobid's claim about it,
    and an assertion a service makes about itself beats one another service
    makes about it. Where the reverse lookup found nothing, lobid's `sameAs` is
    used: one file saying so is better than no record at all, and the two cannot
    be in conflict when only one has spoken.
    """
    contested = {row.about for row in candidate.disagreements}
    found: dict[AuthorityScheme, str] = {}
    for scheme, pattern in _CROSS_REFERENCE_URIS.items():
        if scheme.value in contested:
            continue
        value = _matched(pattern, candidate.same_as)
        if scheme is AuthorityScheme.WIKIDATA and candidate.wikidata_id is not None:
            value = candidate.wikidata_id
        if value is not None:
            found[scheme] = value
    return found


#: VIAF's three endpoints, written out whole rather than composed, the way the
#: lobid and Wikidata URLs above are.
#:
#: **`/viaf/<id>` bare, with no trailing slash.** `/viaf/<id>/`, `/viaf/<id>/viaf.json`
#: and `/viaf/<id>/justlinks.json` all answer Kong's 103 byte
#: `{"message":"no Route matched with those values"}`: VIAF sits behind a
#: gateway now and the classic minimal record endpoints did not survive it.
#: Measured again 2026-08-28. Do not reach for them.
_VIAF_AUTOSUGGEST_URL: Final = "https://viaf.org/viaf/AutoSuggest"
_VIAF_SEARCH_URL: Final = "https://viaf.org/viaf/search"
_VIAF_RECORD_URL: Final = "https://viaf.org/viaf/{cluster}"

#: The header VIAF answers JSON on, and the **only** variable that decides
#: whether it answers at all.
#:
#: Not the `User-Agent`, and not `httpAccept=` in the query string, which is
#: VIAF's old convention and is ignored. Without this header a custom agent gets
#: a 307 to `/en/viaf/search?...` and curl's default gets a 403. Following that
#: redirect and reading the status alone gives **200 and 93,813 bytes of Next.js
#: HTML**, which is why nothing here trusts a status code on its own. See
#: `_viaf_json` for what stands in for reading the content type.
_VIAF_ACCEPT: Final = "application/json"

#: The record schema the cluster is asked for, and it is load bearing.
#:
#: `SRWVIAF` answers **2 bytes** and `VIAF` answers **500**. Only this one
#: returns a cluster.
_VIAF_RECORD_SCHEMA: Final = "BriefVIAF"

#: What a VIAF cluster id may contain, anchored at both ends.
#:
#: **A URL safety check before it is a validation**, the same job `_GND_NUMBER`
#: does: the id is interpolated into `_VIAF_RECORD_URL`'s path and formatted
#: into a CQL query, and a path separator in a formatted string is a path
#: separator. Digits only, because that is what VIAF mints: measured over
#: fourteen clusters on 2026-08-28, the longest was nine digits (`108159964`).
_VIAF_CLUSTER: Final = re.compile(r"\A[0-9]{1,20}\Z")

#: The source code a cluster spells the GND with, which is what makes a cluster
#: checkable rather than merely plausible. VIAF's own message catalogue names it
#: "German National Library".
_GND_SOURCE: Final = "DNB"

#: The six national files a cluster carries that a GND record's `sameAs` does
#: not, keyed by the code VIAF writes in `v:sid`.
#:
#: **The code is the key because it is what the data says.** A cluster writes
#: `BLBNB|000560509`, so matching on anything else would be a second spelling of
#: one fact. Checked against VIAF's own catalogue of contributor names rather
#: than against a plan: `ARBABN` is the National Library of Argentina, `BLBNB`
#: Brazil, `BNCHL` Chile, `BNE` Spain, `ICCU` Italy's union catalogue and
#: `PTBNP` Portugal.
#:
#: **`SUDOC` is deliberately absent** though every cluster measured carries one:
#: it is a French union catalogue rather than one of the six national files that
#: were asked for. Adding it is a migration, which is the whole reason this list
#: is closed.
_NATIONAL_SOURCES: Final = {
    "BLBNB": AuthorityScheme.BLBNB,
    "ARBABN": AuthorityScheme.ARBABN,
    "BNE": AuthorityScheme.BNE,
    "PTBNP": AuthorityScheme.PTBNP,
    "ICCU": AuthorityScheme.ICCU,
    "BNCHL": AuthorityScheme.BNCHL,
}

#: The same six files as Wikidata properties, which is the fallback route.
#:
#: **A fallback and never a comparator**, settled by the owner on 2026-08-28
#: and recorded in `docs/decisions.md`. One supplier speaks per confirmation:
#: this mapping is read only where VIAF answered nothing readable, so the two
#: never both contribute and no disagreement can arise between them.
#:
#: **Promoting it to a comparator regresses two of the six, measured rather
#: than feared.** For `Q1512` on 2026-08-28 Wikidata and VIAF cluster 95207986
#: agree on BLBNB, ARBABN, PTBNP and ICCU and differ on BNE (`XX900250` against
#: `981060880923108606`) and BNCHL (`000034753` against
#: `10000000000000000007303`). Neither pair is a data error: each is one
#: library's old control number beside its new one. `cross_references` omits a
#: contested scheme, so comparing these would *remove* BNE and BNCHL from
#: storage rather than making them more reliable, and the normaliser that would
#: fix that is the hard half of the work. Read `docs/decisions.md` before
#: proposing it.
#:
#: `tests/test_authority.py::TestWikidataIsAFallbackAndNotAComparator` fails if
#: a change makes both suppliers speak in one confirmation.
_NATIONAL_PROPERTIES: Final = {
    AuthorityScheme.BLBNB: "P4619",
    AuthorityScheme.ARBABN: "P3788",
    AuthorityScheme.BNE: "P950",
    AuthorityScheme.PTBNP: "P1005",
    AuthorityScheme.ICCU: "P396",
    AuthorityScheme.BNCHL: "P1890",
}

#: Every source code a cluster is read for: the six stored, plus the one that
#: verifies the cluster is the right person.
#:
#: **Derived rather than written out**, so a scheme added to `_NATIONAL_SOURCES`
#: cannot be parsed for and then discarded, which would look exactly like VIAF
#: not carrying it. It is passed to `_viaf_sources` rather than read there,
#: because that function's bound on memory is its caller's business: see its
#: docstring for the 81.8 MB measurement.
_WANTED_SOURCES: Final = frozenset(_NATIONAL_SOURCES) | {_GND_SOURCE}

#: Bytes a VIAF answer may bring back, which is `_RESPONSE_LIMIT` times eight.
#:
#: **Measured rather than chosen, and the plan's figures were floors rather than
#: bounds.** Over fourteen clusters on 2026-08-28: `AutoSuggest` 2,492 to 2,975,
#: `BriefVIAF` 1,511 to **276,610** (Mozart, cluster 32197206), and the bare
#: record 275,252 to **781,687** (Tolstoy, cluster 96987389, 1.81s). So
#: `_RESPONSE_LIMIT` at 262,144 is exceeded by `BriefVIAF` alone, and the
#: sentence beside it that "nothing asked for here is that shape" stopped being
#: true when VIAF became a supplier: a cluster for a canonical author is exactly
#: the shape the general cap is sized for.
#:
#: 2 MiB is 2.68x the largest measured, which is the margin `fetch` chose for
#: the same reason: 1 MiB would be 1.34x, and `MAX_RESPONSE_BYTES`' own comment
#: records what happened the last time a margin near 1.5x was set from a sample.
#: Parsing retains a measured 15.28x the wire bytes, so the honest worst case
#: here is about 12 MB and the cap admits about 32 MB, once, on one confirmation.
_VIAF_LIMIT: Final = fetch.MAX_RESPONSE_BYTES


def _local(name: str) -> str:
    """A JSON key without its XML namespace prefix.

    **VIAF answers in two shapes that differ only by prefix.** The SRU wrapper
    nests the cluster under `v:VIAFCluster` and the bare record serves
    `ns1:VIAFCluster`, and every key below them follows suit. Measured on
    cluster 56585930, 2026-08-28: walking `mainHeadings -> data -> sources ->
    sid` prefix insensitively yields the **identical 34 source codes** from the
    SRU response, from the bare record's headings, and from the bare record's
    own top level `sources` list. So one walk serves both and loses nothing,
    where matching the prefix would need the parser written twice.
    """
    return name.rpartition(":")[2]


def _under(body: Any, name: str) -> Any:
    """The value of the one key whose local name is this, or None."""
    if not isinstance(body, dict):
        return None
    for key, value in body.items():
        if _local(key) == name:
            return value
    return None


def _viaf_cluster_record(body: Any) -> Any:
    """The `VIAFCluster` object, from either shape VIAF answers in.

    The bare record is the cluster at the top level. The SRU response wraps it
    in `searchRetrieveResponse.records.record.recordData`, and `record` is a
    list when more than one was asked for, which is why the first is taken
    rather than assumed to be a mapping.
    """
    direct = _under(body, "VIAFCluster")
    if direct is not None:
        return direct
    record = _under(_under(_under(body, "searchRetrieveResponse"), "records"), "record")
    if isinstance(record, list):
        record = record[0] if record else None
    return _under(_under(record, "recordData"), "VIAFCluster")


def _viaf_sources(cluster: Any, wanted: frozenset[str]) -> dict[str, str]:
    """The authority files a cluster names, as `code -> identifier`, for `wanted`.

    **`sid` is sometimes a list and sometimes a bare string, in one record.**
    Measured on cluster 95207986: one heading block carried a 37 element list,
    three carried plain strings (`"WKP|Q1512"`, `"ISNI|0000000122831567"`,
    `"NLR|RU NLR AUTH 771316"`), and another carried a 2 element list. Code that
    assumes a list raises on the third; code that iterates a string yields
    characters, and `"WKP|Q1512"` then contributes nothing at all rather than
    failing. The same shape as the `numberOfRecords` trap, where the value is
    `{"xsi:type": ..., "content": 44}` rather than a number.

    **A code the cluster names twice is dropped rather than picked from.**
    Cluster 41844581 (Onetti) carries two `BNCHL` numbers, and
    `author_identifiers` holds one row per scheme, so keeping the first would be
    resolution by ordering: the file has two records for this person and nothing
    here is entitled to say which. This is the same call `cross_references`
    makes when two files disagree, one level down.

    ## `wanted` is a bound on memory, not a convenience

    **The accumulator used to be `dict[str, set[str]]` over every code a body
    named, and that is a stored denial of service in a response this module
    accepts by design.** `_VIAF_LIMIT` is 2 MiB, and a 2,097,151 byte body
    holding 196,998 distinct `code|id` entries peaked at **81.8 MB** measured
    with `tracemalloc` on this tree, against 13.1 MB for `json.loads` on the
    same bytes: 39x the wire, where this module's own budget documents 15.28x.

    Filtering to the codes a caller reads brings the measured peak to 13.1 MB,
    which is the parse itself, so the accumulator stops being the dominant term.
    **Filtering by code alone is not the whole family**, and that is why the
    values are held one deep rather than as sets: a body naming `DNB|1`,
    `DNB|2`, ... two hundred thousand times is inside a seven code allowlist and
    would grow the same way. A code seen with a second, differing value is
    parked at `None` and never grows again, which is exactly the information the
    drop rule needs and no more.

    `partition` rather than `split`, because an identifier legitimately contains
    a separator of its own: `LIH|LNB:V-174543;=BK` is one code and one number.
    """
    # None means "named twice with different values", which is the drop rule
    # holding one bit rather than a set. See the docstring: a set here is
    # unbounded in a body this module accepts.
    found: dict[str, str | None] = {}
    data = _under(_under(cluster, "mainHeadings"), "data")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return {}
    for block in data:
        sid = _under(_under(block, "sources"), "sid")
        if isinstance(sid, str):
            sid = [sid]
        if not isinstance(sid, list):
            continue
        for entry in sid:
            if not isinstance(entry, str):
                continue
            code, separator, identifier = entry.partition("|")
            code, identifier = code.strip(), identifier.strip()
            if not separator or not code or not identifier or code not in wanted:
                continue
            if code not in found:
                found[code] = identifier
            elif found[code] != identifier:
                found[code] = None
    return {code: value for code, value in found.items() if value is not None}


async def _viaf_json(
    client: Any, url: str, params: dict[str, str] | None, deadline: float | None
) -> tuple[int | None, Any]:
    """One bounded VIAF call, as `(status, parsed body or None)`.

    Returns the status because the caller branches on it: a 5xx from the SRU
    endpoint is the one condition that buys the nine times larger bare record.
    None for the status means the request never produced one.

    **Parsing is what stands in for reading the content type.** The trap this
    module records is a 200 carrying 93,813 bytes of HTML, and `fetch.Fetched`
    holds the status, the body and the charset but not the headers, so the
    content type is not reachable from here. Decoding the body as JSON is the
    stronger check for the same fault: an HTML page is a `ValueError` rather
    than a success, and a JSON body that came back under the wrong content type
    is still the answer that was asked for.

    Never raises, for the reason `_wikidata` gives: VIAF is an enrichment and
    not the supplier, so an outage costs the national identifiers and leaves the
    confirmation standing.
    """
    try:
        response = await fetch.get(
            client, url, params=params, limit=_VIAF_LIMIT, deadline=deadline
        )
    except Exception:
        logger.info("VIAF did not answer", exc_info=True)
        return None, None
    if response.status_code != 200:
        logger.info("VIAF answered %s", response.status_code)
        return response.status_code, None
    try:
        return 200, response.json()
    except ValueError:
        logger.info("VIAF answered something that is not JSON")
        return 200, None


async def _viaf_cluster_by_gnd(
    client: Any, name: str, gnd: str, deadline: float | None
) -> tuple[str | None, bool]:
    """The cluster whose own `dnb` field is this GND number, found by name.

    Answers `(the cluster or None, whether VIAF answered at all)`. **The second
    is not derivable from the first**, which is why it is returned rather than
    inferred: "VIAF is down" and "VIAF answered and named nobody" are the same
    `None` here, and they are the two sides of `national_identifiers`' fallback.

    **Only reached when lobid's `sameAs` names no cluster**, which is 7 of 49
    `DifferentiatedPerson` records sampled on 2026-08-28. That is not a rare
    corner: one of the seven is Italo Calvino, GND `118518542`.

    **The name is how the question is asked and never how the answer is
    chosen.** `AutoSuggest` returns each hit with its own `dnb`, so the hit is
    selected on a key the Member already confirmed rather than on a spelling.
    That matters here more than anywhere else in this module: `Mario Benedetti`
    returns three different people, `dnb` 118508873, 123000327 and 1167553616,
    and the top ranked one is not the one a search for GND `123000327` means.
    A name match would have stored another man's national identifiers under this
    author, durably, with a 200 everywhere.

    `nametype` must be `personal`: the same query also returns
    `uniformtitlework` clusters, which are works rather than people, and that is
    the confusion `_PERSON_FILTER` exists to prevent on the lobid side.

    **Exactly one matching hit, or none.** The first version returned the first
    match, and that contradicted the rule `_viaf_sources` applies one level
    down: a code a cluster names twice is dropped because "nothing here is
    entitled to say which". Two hits sharing a `dnb` is the same ambiguity seen
    from the other end, and it is the shape #99 records as ordinary rather than
    exotic: clusters split and merge, and #87 measured one name resolving to
    four personal clusters.

    **This is consistency with a recorded rule rather than a reproduction.** A
    reviewing seat probed four names live on 2026-08-28 and could not produce
    two personal hits under one `dnb`; the only duplicates it found were
    `uniformtitlework` hits, which the filter above already drops. So the
    evidence for the loop below is the rule, not a measurement, and that is
    stated rather than dressed up as a bug found in the wild.

    The distinct `viafid` values are collected **before** being validated, so a
    second hit carrying an unusable id still counts as ambiguity. Discarding it
    first would let a bad value silently promote a single survivor.

    No Lucene escaping, because this is not a query language: `query=` here is a
    plain prefix term. It is still truncated to `MAX_QUERY_NAME`, which bounds
    the request rather than the name.
    """
    _, body = await _viaf_json(
        client, _VIAF_AUTOSUGGEST_URL, {"query": name[:MAX_QUERY_NAME]}, deadline
    )
    if not isinstance(body, dict):
        return None, False
    matched: set[str] = set()
    for hit in body.get("result") or []:
        if not isinstance(hit, dict):
            continue
        if hit.get("nametype") != "personal" or hit.get("dnb") != gnd:
            continue
        cluster = hit.get("viafid")
        if not isinstance(cluster, str):
            return None, True
        matched.add(cluster)
        # **Stops reading, and decides nothing.** `result` is somebody else's
        # list and two distinct clusters already answer the question, so there
        # is no reason to walk the rest. The rule itself is the single check
        # below.
        #
        # This used to `return None` here, which put the rule in two places and
        # made the check below unreachable for the case it exists for. A
        # mutation replacing that check with `if not matched` was then
        # **equivalent**, and survived at 166 passed: the early return was
        # silently doing all the work. A guard whose subject is enforced
        # somewhere else is not a guard.
        if len(matched) > 1:
            logger.info("VIAF offered more than one cluster for one GND number")
            break
    if len(matched) != 1:
        return None, True
    only = matched.pop()
    return (only, True) if _VIAF_CLUSTER.match(only) else (None, True)


async def _viaf_cluster_sources(
    client: Any, cluster: str, deadline: float | None, wanted: frozenset[str]
) -> dict[str, str] | None:
    """Every file one cluster names, through the cheap route or the expensive one.

    **`None` and `{}` are different answers and the caller branches on it.**
    `None` is "VIAF produced no cluster record": a transport failure, a 403, a
    gateway 404, a 200 carrying HTML, or a body that parsed and held no
    `VIAFCluster`. `{}` is "here is the cluster, and it names none of the codes
    you asked for", which is VIAF answering. Only the first buys the Wikidata
    fallback: see `national_identifiers`.

    **Two calls, and the second is paid only by the records VIAF cannot
    serialise.** `BriefVIAF` is the answer at 1,511 to 276,610 bytes; the bare
    record is 275,252 to 781,687 for the same identifiers.

    **A 5xx here is a property of the data rather than an outage, so retrying is
    useless.** VIAF's SRU serialiser breaks on a bare `&` in a record and says
    so: `Missing ';' in XML entity: & at 22365 [character 32 line 1012]`,
    returned three times out of three for cluster 56585930 on 2026-08-28. The
    bare record is JSON rather than SRU XML, so the same `&` is just a
    character, and it carried all six national schemes for that cluster where
    the SRU call carried none.

    **That fault did not reproduce later the same day**: the same call answered
    200 and 28,233 bytes, three times out of three. The fallback is kept anyway
    and this paragraph is why: the failure is a property of a record that VIAF
    may repair and may reintroduce, we cannot know which records carry it
    without asking, and the cost of being wrong is losing every national
    identifier for that person. `tests/test_authority.py` pins the behaviour on
    a fixture rather than on VIAF being broken.

    Anything other than a 5xx is not retried by the larger route, deliberately:
    a 403 or a 404 is an answer, and asking the same question again nine times
    larger would not change it.
    """
    status, body = await _viaf_json(
        client,
        _VIAF_SEARCH_URL,
        {
            "query": f"local.viafID = {cluster}",
            "recordSchema": _VIAF_RECORD_SCHEMA,
            "maximumRecords": "1",
        },
        deadline,
    )
    if body is None and status is not None and status >= 500:
        logger.info("VIAF could not serialise a cluster; reading the bare record")
        _, body = await _viaf_json(
            client, _VIAF_RECORD_URL.format(cluster=cluster), None, deadline
        )
    if body is None:
        return None
    record = _viaf_cluster_record(body)
    if record is None:
        return None
    return _viaf_sources(record, wanted)


async def _national_from_wikidata(
    candidate: AuthorityCandidate, deadline: float | None
) -> dict[AuthorityScheme, str]:
    """The six national numbers off the Wikidata item, when VIAF said nothing.

    **The second route to the same six, and it speaks only when the first did
    not.** Settled by the owner on 2026-08-28: Wikidata is a fallback, not a
    comparator. The redundancy that was asked for is redundancy of *supply*, so
    a gateway outage at VIAF costs a slower answer rather than the whole
    feature; it was never cross checking, and cross checking here would cost two
    of the six. `_NATIONAL_PROPERTIES` carries that measurement.

    ## The item is verified in the same both directions way the cluster is

    `candidate.wikidata_id` is **Wikidata's own reverse lookup on `P227`**
    against the GND number the Member confirmed, made by `_item_for`, and never
    lobid's claim about it. So the person this reads from is joined to the
    confirmed record by the same property VIAF's `DNB|118753711` check uses,
    from the other side. Nothing here is chosen on a name.

    A candidate carrying no item is the ordinary case for a minor author and
    answers nothing, which is the same shape `AuthorityCandidate` records: the
    absence is a hint, never a rule, and here it is simply no supply.

    **A contested item stops it**, exactly as a contested cluster stops the VIAF
    route. Where lobid and Wikidata name different items for one person, reading
    national numbers off Wikidata's item is reading them off somebody this app
    is not sure is the author, and a wrong national number is a durable row.

    ## What it refuses to pick between

    A property carrying two different values is **dropped rather than resolved
    by ordering**, which is `_viaf_sources`' rule for a code a cluster names
    twice, one file over. It is not rare: `_claims` carries the counts, and
    `Q5682` holds eight `P3788` values.

    ## The budget

    **Six requests, sequential, and the sequence is measured rather than
    stylistic.** Six `wbgetclaims` for `Q1512` on 2026-08-28 came to 1,942
    bytes and **1.49 seconds** in total, 281 to 524 bytes each. They are not
    gathered because Wikidata rate limits a burst: roughly fifty `wbgetclaims`
    inside two minutes from one address answered **429**, and kept answering it
    for minutes. `search` gathers its fan out and this does not, and that is the
    difference between five candidates on a read and six properties on a write
    nobody is waiting on.

    They are paid only where VIAF produced no cluster, so the common
    confirmation still costs what `DEADLINE_SECONDS` records.
    """
    item = candidate.wikidata_id
    if item is None or not _ITEM_ID.match(item):
        return {}
    if AuthorityScheme.WIKIDATA.value in {row.about for row in candidate.disagreements}:
        logger.info("The two files disagree about the item; not reading it for numbers")
        return {}
    found: dict[AuthorityScheme, str] = {}
    for scheme, prop in _NATIONAL_PROPERTIES.items():
        values = await _claims(item, prop, deadline)
        if len(values) == 1:
            found[scheme] = values[0]
        elif len(values) > 1:
            logger.info("Wikidata holds more than one %s number for one person", scheme)
    return found


async def national_identifiers(
    candidate: AuthorityCandidate, *, deadline: float | None = None
) -> dict[AuthorityScheme, str]:
    """The six national files' numbers for a person, which a GND record omits.

    **The half of the cross references that is not free.** A GND record's
    `sameAs` carries ISNI, LCNAF, VIAF and Wikidata, which `cross_references`
    reads off a response already in hand. It carries **no national library number
    at all**, and those are what a reader of Spanish, Portuguese, Brazilian,
    Argentine, Italian or Chilean books wants. A VIAF cluster carries them, so
    this is the one place the module pays for a request rather than reading one it
    already made.

    **VIAF is a discovery route and never an identity here.** Nothing returned is
    a cluster id: cluster ids split and merge, and one author was measured
    resolving to four of them.

    **The cluster is verified in both directions**: it must name the GND number
    already in hand, rather than being trusted on a name.

    **Wikidata is the fallback for this route and never a comparator**, asked only
    where VIAF produced no cluster. One supplier speaks per confirmation.

    **The budget is three requests on the path that works**, and six more on the
    fallback, which are the cheap ones. A member is not waiting on this: it runs
    after a confirmation rather than inside a lookup.
    """
    if not candidate.certain:
        return {}
    if AuthorityScheme.VIAF.value in {row.about for row in candidate.disagreements}:
        return {}

    sources: dict[str, str] | None = None
    async with fetch.catalogue_client() as client:
        client.headers["accept"] = _VIAF_ACCEPT
        cluster = _matched(_VIAF_URI, candidate.same_as)
        # `heard` is the whole reason this is a tuple. A cluster read out of
        # lobid's `sameAs` costs no VIAF request, so reaching this branch and
        # coming back empty is the only place "VIAF is down" and "VIAF knows
        # nobody by that name" have to be told apart.
        #
        # **False, because it means "VIAF has answered" and nothing has asked it
        # yet.** True was the trigger line inverted, and it was reachable: a
        # `sameAs` id is matched by `_VIAF_URI`, whose digits are unbounded,
        # and then rejected by `_VIAF_CLUSTER`, which allows twenty. A
        # twenty-one digit id therefore reached `elif heard: return {}` with no
        # request made at all, which is a supply failure recorded as an answer.
        heard = False
        if cluster is None:
            cluster, heard = await _viaf_cluster_by_gnd(
                client, candidate.name, candidate.identifier, deadline
            )
        if cluster is not None and _VIAF_CLUSTER.match(cluster):
            sources = await _viaf_cluster_sources(
                client, cluster, deadline, _WANTED_SOURCES
            )
        elif heard:
            # VIAF answered and named nobody, or named two people, or named a
            # cluster id that is not one. That is an answer and it stands: the
            # fallback is for an outage, not for a second opinion on a question
            # VIAF has already refused.
            return {}

    if sources is None:
        logger.info("VIAF produced no cluster; asking Wikidata for the national files")
        return await _national_from_wikidata(candidate, deadline)

    if sources.get(_GND_SOURCE) != candidate.identifier:
        logger.info("A VIAF cluster did not name the confirmed GND record back")
        return {}
    return {
        scheme: sources[code]
        for code, scheme in _NATIONAL_SOURCES.items()
        if code in sources
    }


async def _cross_check(
    candidate: AuthorityCandidate, *, compare_references: bool, deadline: float | None
) -> AuthorityCandidate:
    """The same candidate, with what Wikidata knows about it.

    **`compare_references` splits the cost by how much the answer is worth**,
    and the split is the two routes rather than a tuning knob. A `resolve` has
    one person in hand and the cross references are the point, so it pays for
    the `P214` and `P213` requests. A `search` has up to five people and the
    question is which of them somebody means, so it buys the description and the
    item's existence and stops: five candidates would otherwise be twenty
    requests to two services for a list the member is about to narrow to one
    anyway.

    **A search candidate therefore carries no disagreements, and that is not the
    same as agreeing.** `cross_references` omits a contested scheme, so anything
    it writes has to come from a candidate that was actually compared. The only
    write path is `resolve`, which is this parameter set true. Nothing enforces
    that from here; `Authorship.record_cross_references` is where a caller with
    an uncompared candidate would go wrong, and its docstring says so.

    Never raises. Wikidata is the cross check and not the supplier.
    """
    item = await _item_for(candidate.identifier, deadline)
    if item is None:
        return candidate
    description = await _description_of(item, deadline)
    viaf = await _claim(item, _P_VIAF, deadline) if compare_references else None
    isni = await _claim(item, _P_ISNI, deadline) if compare_references else None
    return replace(
        candidate,
        wikidata_id=item,
        description=description,
        disagreements=_disagreements(candidate, item, viaf, isni),
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
    return await _cross_check(candidate, compare_references=True, deadline=deadline)


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
                _cross_check(row, compare_references=False, deadline=deadline)
                for row in kept
            )
        )
    )


#: Where a Wikipedia article's URL may point, anchored at both ends.
#:
#: **This is the one place this module accepts a URL out of a response, and the
#: pattern is why that is safe.** Everywhere else the rule is absolute: three
#: fixed hosts, and a cross reference is recorded and shown but never fetched.
#: Here the host is still spelled here, `wikipedia.org` and nothing else; only
#: the language subdomain comes from Wikidata, and it is bounded to
#: `[a-z0-9-]{2,32}`. A value that is not exactly this shape is dropped.
#:
#: **Building the URL from the site code instead would be the wrong kind of
#: work, and it is measured rather than argued.** `Q1512` carries 153
#: sitelinks, **101** of which end in `wiki`, and exactly one of those 101 is
#: not Wikipedia: `commonswiki`, which is `commons.wikimedia.org` and a media
#: repository. So a code to host rule needs a denylist of the sites that are
#: not Wikipedia and a transliteration for the ones that are
#: (`zh_yuewiki` is `zh-yue`, `bat_smgwiki` is `bat-smg`), which is exactly the
#: "enumerate something open" shape that has needed four rewrites here before.
#: Matching what the API returns against an anchored pattern needs neither, and
#: `commonswiki` fails it because its host is not `wikipedia.org`.
#:
#: Nothing here fetches it. **Wikipedia is not an outbound host of this app**;
#: it is a link a reader may follow, and that is the whole of #89's decision.
_WIKIPEDIA_ARTICLE: Final = re.compile(
    r"\Ahttps://([a-z0-9-]{2,32})\.wikipedia\.org/wiki/[^\s\"'<>]+\Z"
)

#: The Wikidata item's own page, which is where a person with no article goes.
#:
#: **The floor under the fallback chain, and it is the reason the button is
#: never absent.** It always resolves, it always names the person the confirmed
#: identifier names, it renders that person's label and description in the
#: reader's own browser language, and it lists every Wikipedia edition one click
#: away. A `Special:GoToLinkedPage` link would be the obvious alternative and is
#: refused: measured 2026-08-28, a site with no article answers **200 with a
#: 39,003 byte Wikidata maintenance form**, not a 404, so a reader would be
#: dropped on an edit form with no way to tell that anything had gone wrong.
_WIKIDATA_ITEM_URL: Final = "https://www.wikidata.org/wiki/{item}"

#: How many entities one **filtered** `wbgetentities` call may name.
#:
#: Wikidata's own ceiling, and safe only because `sitefilter` is what makes the
#: answer small: fifty ids with `sitefilter=dewiki|enwiki` measured 15,034 bytes
#: on 2026-08-28, which is 17x under `_RESPONSE_LIMIT`.
_ITEMS_PER_REQUEST: Final = 50

#: How many entities one **unfiltered** call may name, which is two.
#:
#: **The same number cannot serve both calls, and using it made the third tier
#: dead code.** Without `sitefilter` a single entity is 1,606 to **64,449**
#: bytes, and a chunk of eight measured 233,815. So fifty ids is roughly six
#: times `_RESPONSE_LIMIT`:
#: `fetch.get` refuses the body, `_wikidata` answers None, and every item in
#: that chunk falls to the Wikidata item page. The tier that exists for the
#: author with only a Chinese article was therefore unreachable for any page
#: carrying more than about seven of them, which is exactly the library it was
#: written for.
#:
#: **Two, derived from the largest sampled item rather than from the average**,
#: and "largest sampled" is the honest phrase: the first version of this comment
#: cited `_VIAF_LIMIT`'s lesson about a margin set from a sample and then set its
#: own from a sample of six, which is the same mistake one level up.
#:
#: The largest measured is **`Q692`, Shakespeare, at 64,449 bytes over 336
#: sitelinks**, which is the most linked author on Wikidata and squarely in this
#: route's population. At that size two ids is 128,898, **2.03x** under
#: `_RESPONSE_LIMIT`, and four is 257,796, or **1.02x**, which is the cap with
#: nothing to spare.
#:
#: **The rate is what a later reader should bound this with rather than
#: re-sampling: about 192 bytes per sitelink.** So the size that is safe is
#: `_RESPONSE_LIMIT` divided by the margin, divided by 192, divided by the
#: sitelinks the most linked person plausibly has. `_VIAF_LIMIT`'s comment
#: records what happened the last time a margin near 1.5x was set from a
#: sample, which is why this is two and not the four that merely fits.
_UNFILTERED_ITEMS_PER_REQUEST: Final = 2

#: How many people the unfiltered pass may be paid for at all.
#:
#: **A budget on the third tier, not on the button.** At two ids a request this
#: is five requests, so the whole route is at most **ten**: five filtered and
#: five unfiltered. An eleventh author with no article in either app locale
#: still gets a row and still gets a button, because the floor is the Wikidata
#: item page and that costs no request. What is lost is the chance of a Chinese
#: article for the eleventh, which is a smaller loss than the one
#: `MAX_WIKIPEDIA_ITEMS` used to inflict by dropping the row entirely.
#:
#: It is a cut by listing order, and that is stated rather than hidden: the
#: alternative is an unbounded fan out on a page render, and the largest sampled
#: case at this bound is already 5 x 15,034 + 5 x 128,898, about **720 KB**.
MAX_UNFILTERED_ITEMS: Final = 10

#: How many people one call may ask about, and therefore this route's whole
#: outbound budget.
#:
#: **A page's worth of buttons rather than a shelf's worth**, and it bounds the
#: **fetch** rather than the answer: an author past it still gets a row and a
#: button, because the Wikidata item page costs no request. It is a bound on
#: somebody else's service, and it applies only to authors carrying a
#: **confirmed** authority identifier, which is one deliberate act per person.
#:
#: At 250 this is five filtered `wbgetentities` requests. Measured 2026-08-28,
#: fifty ids with `sitefilter=dewiki|enwiki` is 15,034 bytes and 0.89s.
#: **The route's whole ceiling is ten requests and about 720 KB**, not five and
#: 75 KB: the unfiltered pass is five more and is much the larger half. See
#: `MAX_UNFILTERED_ITEMS`.
MAX_WIKIPEDIA_ITEMS: Final = 250


@dataclass(frozen=True, slots=True)
class WikipediaArticle:
    """Where to send a reader who wants to read about this person.

    `language` is the Wikipedia edition the URL points at, or **None** where it
    points at the Wikidata item instead. A client shows the first as an ordinary
    outward link and can say which language it landed on when that is not the
    reader's own; the second is the floor described on `_WIKIDATA_ITEM_URL`.

    **A URL and a language code, and deliberately nothing else.** No title, no
    extract, no description. `docs/featurelist.md` refuses author biographies
    and portraits and this does not touch that refusal: which language editions
    exist is data about availability, and an article's prose is the thing the
    refusal is for. If a later change finds itself reading `extract`,
    `description` or `thumbnail` here, that is the refusal being reversed rather
    than extended.
    """

    url: str
    language: str | None


async def _sitelinks(
    items: tuple[str, ...], sitefilter: str | None, deadline: float | None
) -> dict[str, dict[str, str]] | None:
    """Which Wikipedia editions hold an article about each of these people.

    `{item: {language: url}}`, and **None where Wikidata did not answer**, which
    is the same distinction `_viaf_cluster_sources` draws: an empty mapping for
    one item means "asked, no article", and None for the call means "not asked
    successfully", and only the second must not be retried nine times larger.

    `props=sitelinks/urls` rather than `props=sitelinks`, which costs 354 bytes
    against 232 for one item, measured 2026-08-28. What the extra 122 buys is
    the whole of `_WIKIPEDIA_ARTICLE`'s reasoning: the API states the URL and
    this module checks it, rather than this module deriving a host from a site
    code it has never seen.

    **`sitefilter` is the difference between 354 bytes and 32,571**, measured on
    the same entity, so the common path names the languages it wants and the
    fallback pass, which is the rare one, does not.
    """
    # **Two spelled out calls rather than one dict built up**, and the guard is
    # the reason: `TestTheRefusalsAreStructural` fails a `_wikidata` request body
    # it cannot read statically, because binding a dict to a variable first is
    # ordinary Python and is also how a `props` nobody reviewed would arrive.
    # The duplication buys every request this module makes being readable where
    # it is made.
    if sitefilter is None:
        body = await _wikidata(
            {
                "action": "wbgetentities",
                "ids": "|".join(items),
                "props": "sitelinks/urls",
            },
            deadline,
        )
    else:
        body = await _wikidata(
            {
                "action": "wbgetentities",
                "ids": "|".join(items),
                "props": "sitelinks/urls",
                "sitefilter": sitefilter,
            },
            deadline,
        )
    if not isinstance(body, dict):
        return None
    entities = body.get("entities")
    if not isinstance(entities, dict):
        return None
    found: dict[str, dict[str, str]] = {}
    for item in items:
        entry = entities.get(item)
        links = (entry or {}).get("sitelinks") if isinstance(entry, dict) else None
        articles: dict[str, str] = {}
        for link in (links or {}).values():
            if not isinstance(link, dict):
                continue
            url = link.get("url")
            if not isinstance(url, str):
                continue
            matched = _WIKIPEDIA_ARTICLE.match(url)
            if matched is not None:
                articles[matched.group(1)] = url
        found[item] = articles
    return found


def _preferred(articles: dict[str, str], prefer: tuple[str, ...]) -> tuple[str, str] | None:
    """The article to link to, as `(language, url)`, best first.

    The reader's own language, then the app's other one, then **any** edition,
    which is the owner's rule stated on #89: a page in a language they cannot
    read beats an absent button, because it is still the right person and they
    can machine translate it.

    The last tier is `min` rather than "whichever came first", because the
    answer is a JSON object and a link that moves when Wikidata reorders its
    response is a link that cannot be reasoned about.

    **`min` has a consequence a client has to know about**, and it is not
    obvious from here: it sorts alphabetically, so the legacy Wikipedia codes
    `bat-smg` and `cbk-zam` come **ahead of** `de`, `en`, `fr` and `zh`. Those
    are exactly the codes `Intl.DisplayNames` raises a `RangeError` on, so for
    an author carrying one this tier picks the tag a naive client crashes
    rendering. `frontend/src/lib/languageName.ts` is where that is handled and
    says so.
    """
    for language in prefer:
        url = articles.get(language)
        if url is not None:
            return language, url
    if not articles:
        return None
    language = min(articles)
    return language, articles[language]


async def wikipedia_articles(
    items: tuple[str, ...], *, prefer: tuple[str, ...], deadline: float | None = None
) -> dict[str, WikipediaArticle]:
    """One outward link per person, in the reader's language where there is one.

    **The gate is identity and never language**, and it is the caller's: this is
    given Wikidata item ids, and an item id is only ever in this app because a
    Member confirmed the authority record it hangs off. #87 measured why that
    matters more than staleness does: `Stevenson, Robert Louis` is two GND
    records and only one of them has a Wikidata item, so a link chosen on a name
    would be a biography of the wrong person, which is worse than no biography.

    ## Two passes, and the second is paid by about one author in a hundred

    The first names the languages wanted, which is 354 bytes for one item and
    15,034 for fifty, measured 2026-08-28. The second asks the leftovers with no
    `sitefilter` at **1,606 to 64,449 bytes for one**, and it exists for exactly
    the case the owner named: an author with a Chinese article and no English or
    German one.

    **The two passes therefore do not share a chunk size**, and using one for
    both made this tier dead code rather than merely expensive: see
    `_UNFILTERED_ITEMS_PER_REQUEST`, which is two, and `MAX_UNFILTERED_ITEMS`,
    which bounds how many people it is paid for.

    Sampled 2026-08-28 over 300 people carrying a GND number and the writer
    occupation, 297 have some Wikipedia article and **3** have neither `enwiki`
    nor `dewiki`, so the expensive pass was about 1% of that sample. **That
    figure is a floor rather than a rate**, and the reason is the sample: a GND
    number is a German catalogue's identifier, so the population is one where
    German and English coverage is unusually good. In the library this tier
    exists for, the share is higher and unmeasured.

    **A pass that did not answer does not buy the expensive one.** An outage
    would otherwise turn every item into an unfiltered request, which is the
    cheap path failing into the expensive one. `_sitelinks` returning None is
    what distinguishes them.

    ## What a failure degrades to

    **Never nothing.** Anything unresolved, for any reason, gets the Wikidata
    item's own page: see `_WIKIDATA_ITEM_URL` for why that is the floor and why
    `Special:GoToLinkedPage` is not. So the button renders whether or not
    Wikidata answered, and a reader always lands on the right person.

    That is deliberately stronger than the alternative it was measured against.
    Falling back to `Special:GoToLinkedPage/enwiki` would have worked for 97.3%
    of the sample, and the other 2.7% would have been dropped, silently, on a
    Wikidata edit form. A link that is right 100% of the time and sometimes
    points at a data page beats one that is right 97.3% of the time and fails
    invisibly.

    Nothing is stored by any of this and there is nowhere to store it: the app
    holds identifiers, and which language editions exist is a fact about
    Wikipedia today.
    """
    wanted = tuple(dict.fromkeys(item for item in items if _ITEM_ID.match(item)))
    if not wanted:
        return {}

    # **The cap bounds the fetch and never the answer**, and it used to bound
    # both. Slicing `wanted` here left author 251 onwards with no entry, no row
    # and therefore no button, cut by listing order, while three docstrings and
    # a test all said the button is never absent. The floor costs no request:
    # an item nobody asked Wikidata about resolves to the Wikidata item page
    # below, exactly as one Wikidata answered nothing for does.
    looked_up = wanted[:MAX_WIKIPEDIA_ITEMS]

    sitefilter = "|".join(f"{language}wiki" for language in prefer)
    articles: dict[str, dict[str, str]] = {}
    # Only the items a filtered pass **answered about** may reach the unfiltered
    # one. A chunk whose request failed is not a chunk with no article.
    answered: list[str] = []
    for start in range(0, len(looked_up), _ITEMS_PER_REQUEST):
        chunk = looked_up[start : start + _ITEMS_PER_REQUEST]
        found = await _sitelinks(chunk, sitefilter, deadline)
        if found is None:
            continue
        answered.extend(chunk)
        articles.update(found)

    # Its own chunk size and its own ceiling, and both are the same fault seen
    # twice: an unfiltered entity reaches 64,449 bytes where a filtered one is
    # about 300, so the fifty that is safe above is six times the response cap
    # here. See `_UNFILTERED_ITEMS_PER_REQUEST`.
    missing = tuple(item for item in answered if not articles.get(item))[
        :MAX_UNFILTERED_ITEMS
    ]
    for start in range(0, len(missing), _UNFILTERED_ITEMS_PER_REQUEST):
        chunk = missing[start : start + _UNFILTERED_ITEMS_PER_REQUEST]
        found = await _sitelinks(chunk, None, deadline)
        if found is not None:
            articles.update(found)

    resolved: dict[str, WikipediaArticle] = {}
    for item in wanted:
        best = _preferred(articles.get(item) or {}, prefer)
        resolved[item] = (
            WikipediaArticle(url=best[1], language=best[0])
            if best is not None
            else WikipediaArticle(
                url=_WIKIDATA_ITEM_URL.format(item=item), language=None
            )
        )
    return resolved


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
