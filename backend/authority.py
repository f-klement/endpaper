"""The authority files, read for a person rather than for a book.

`metadata.py` asks catalogues about **books**; this module asks five authority
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

**The Library of Congress Name Authority File is the second supplier**, asked
beside lobid on every name search and listed after it. The GND is concentrated on
German, and a name search that asks it alone decides whether a person is
findable at all; the NAF is concentrated on English, which is the point of
asking both. It answers over SRU on the gateway `metadata.py` already reaches for
the Library of Congress catalogue, so it is a database name on a connection that
exists rather than a new host. What its index can and cannot find is on
`_NAF_PAGE`.

**ORCID is the last file, and it is asked only for a name the two before it
both answered with nobody.** It is a researcher's own registration rather than a
national file, so it is strong where both national files are thin and empty
for the novelist and the long dead author a household shelf holds. A miss there
then costs one request on a name nothing else could answer. Its people arrive
under its own scheme, never as an ISNI: why the two are never compared is on
`_ORCID_URI`.

## Why VIAF is not a supplier

**Half of its read API answers, and which half depends on the `Accept` header
alone**, not on the path. That is easy to probe wrongly in either direction,
which is why the finding is recorded here rather than left to be rediscovered.

## Terms, read rather than assumed

**lobid** states its licence in every response. **Wikidata** publishes CC0 through
`rightsinfo`, and its 403 on a default user agent is why `fetch._AGENT` exists.
**VIAF publishes neither**, which is measured rather than assumed and is one
reason it stays out of the resolution path.
**The Library of Congress gateway** states no terms in its responses either; it
is the same gateway, under the same footing, as the catalogue search.
**ORCID**'s public terms and limits are on `_ORCID_SEARCH_URL`.

## The refusal this module is built around

**The only thing any of this can write is an identifier.** Not a name, not a
date, not a description: a person's own record stays what a member typed, and an
authority file can only ever attach a number to it.

## The boundary

Every catalogue source's, plus lobid, Wikidata and `pub.orcid.org`. The NAF
adds none: it is the Library of Congress catalogue's gateway, over the same
plaintext HTTP. **No cover
host is added and none could be**: `covers.COVER_HOSTS` is what the CSP is
derived from, so a host added here would widen what the browser may load.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from typing import Any, Final
from xml.etree import ElementTree

import fetch
import marc_fields
import metadata
import xml_parse
from bibliographic import strip_isbd_punctuation
from deadline import in_
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

#: An ORCID iD as ORCID writes it and this app stores it: four groups of four,
#: hyphenated, an `X` allowed as the ISO 7064 check character. The URI's own
#: form, for the reason `_ISNI_URI` stores the URI's form of an ISNI.
_ORCID_DIGITS: Final = r"[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]"
_ORCID_ID: Final = re.compile(rf"\A{_ORCID_DIGITS}\Z")

#: Where an ORCID iD sits inside the URI lobid records for it.
#:
#: **ORCID and ISNI share one numbering space and are never compared**, because
#: they never number one person with the same digits. ISNI reserved a block for
#: ORCID to mint from (`0000-0001-5000-0007` to `0000-0003-5000-0001`, and
#: `0009-0000-0000-0000` to `0009-0010-0000-0000` since), and assigns nothing
#: in it itself. So a person holding both holds two different numbers, which is
#: two schemes each saying one thing rather than a disagreement, and
#: `AuthorOut.identifier_conflicts` compares within a scheme only. Measured
#: 2026-11-16 over the first 200 GND records lobid returned carrying both: no
#: ORCID equalled the ISNI beside it and no ISNI fell inside ORCID's block.
_ORCID_URI: Final = re.compile(rf"\Ahttps?://orcid\.org/({_ORCID_DIGITS})\Z")

#: The Library of Congress Name Authority File, over SRU 1.1.
#:
#: **The catalogue's own gateway with another database name**: `lcdb` is the
#: catalogue `targets.SEEDED` reaches, `NAF` is this. Plaintext for the reason
#: the catalogue is, which `fetch.RedirectedOffHost` carries: the gateway has no
#: TLS endpoint. Its subject twin `SAF` answers the same way and nothing here
#: asks it, because no part of this app searches a subject heading yet.
_NAF_URL: Final = "http://lx2.loc.gov:210/NAF"

#: The Wikidata property holding an LCNAF number, unspaced (`n78088964`): the
#: form `_LCNAF_URI` reads and `author_identifiers` stores.
_P_LCNAF: Final = "P244"

#: The Wikidata property holding an ORCID iD, hyphenated as `_ORCID_ID` reads it.
_P_ORCID: Final = "P496"

#: An LCNAF number as this app stores it: the prefix, then eight digits for a
#: record made before 2001 or ten after. Anchored, because it goes into a query.
_LCCN: Final = re.compile(r"\A(n[a-z]?)([0-9]{8}|[0-9]{10})\Z")

#: How many records one NAF name search asks for, of which at most
#: `MAX_CANDIDATES` people are kept.
#:
#: **Five times the people kept, because most of what the index answers is not
#: a person.** `bath.personalName` matches the heading's leading words, and a
#: prolific author's name heads hundreds of name and title records, one per
#: translated work, which `_naf_person` drops. The index orders by neither
#: relevance nor date, and no CQL refuses a name and title record: a `not
#: dc.title` clause over every initial left 46 of 429 and took 9 seconds.
#:
#: Measured 2026-11-16 over twelve English language authors, inverted from
#: reading order: the person record was inside the first 5 records for 4, inside
#: the first 25 for 9, and for the other three at 53 (Atwood), past 50 (Mary
#: Shelley) and past 100 (Christie). So **a famous author can be missed here**,
#: and lobid is still asked for them. 25 records measured 24,221 to 80,603 bytes
#: and 0.49 to 0.85 seconds.
_NAF_PAGE: Final = 25

#: The NAF door's half of its allocation bound: see `xml_parse.ALLOCATION_FLOOR`.
#:
#: **The catalogue door's figure, because it is the catalogue door's shape**: the
#: response is decoded inside the call, so one character above U+FFFF makes the
#: whole text four bytes a character, and then built through the same builder.
#: Measured by `tracemalloc` on the suite pod, CPython 3.14.10, per byte of the
#: text as UTF-8: the shape `metadata.ALLOCATION_FACTOR` is measured on, about
#: 1 MiB of it inside one record, peaked at 32.6, and empty `400` fields read by
#: `_naf_person` at 26.7. A spelling of its own rather than that constant,
#: because the two doors read different records and either may move alone.
ALLOCATION_FACTOR: Final = 33

#: The diagnostic the gateway answers when its shared session to the file has
#: dropped: `System temporarily unavailable`, `target closed connection during
#: search`. Both files gave it on their first search of 2026-11-16 and answered
#: the same query at once when it was repeated, so it is asked once more.
#: **Idle time alone did not bring it back**: after 2, 5 and 10 minutes of
#: nothing the first search answered, only slower (0.64s against 0.21s). So
#: what drops the session is not measured, and the retry is for an answer seen
#: twice in a day rather than one expected on every cold start. Any other
#: diagnostic is an answer this module cannot read.
_NAF_COLD_SESSION: Final = "info:srw/diagnostic/1/2"

#: Where an envelope diagnostic is found, `_NAF_COLD_SESSION` among them: the
#: envelope's `diagnostics`, in the SRU 1.1 namespace, and the diagnostic
#: namespace's `uri` inside it, at any depth.
_SRU_DIAGNOSTICS: Final = "{http://www.loc.gov/zing/srw/}diagnostics"
_SRU_DIAGNOSTIC_URI: Final = "{http://www.loc.gov/zing/srw/diagnostic/}uri"

#: The MARC21 slim namespace in ElementTree's `{uri}` spelling.
_MARC: Final = f"{{{marc_fields.NAMESPACE}}}"

#: Every character CQL reads specially inside a quoted term, each escaped. The
#: quote and the backslash would end or break the term; `*`, `?` and `^` are
#: masking and anchoring characters, which a name holding one would otherwise
#: widen into a pattern.
_CQL_ESCAPED: Final = str.maketrans({character: f"\\{character}" for character in '\\"*?^'})

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
_LUCENE_ESCAPED: Final = str.maketrans({character: f"\\{character}" for character in '\\+-!(){}[]^"~*?:|&/'})

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
#: | a NAF page, `_NAF_PAGE` records | (none) | 24,221 to 80,603, on 2026-11-16 |
#: | an ORCID search, `MAX_CANDIDATES` rows | (none) | 284 to 1,037, on 2026-11-16 |
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
#: would be refused here. See `_VIAF_LIMIT`. The NAF page shares this cap with
#: lobid and Wikidata at 3.25x its largest measured answer, so it is not the
#: binding case.
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
#: is roughly 1.3s and the candidates run together. The margin is for a slow
#: day, not for a bigger fan out: that is what `MAX_CANDIDATES` bounds.
#:
#: **A name search waits on the NAF page before its Wikidata pair.** lobid's
#: search runs beside it, so the slower of the two counts: a NAF page measured
#: 0.49 to 0.85s on 2026-11-16, two in sequence when the session is cold, then
#: two Wikidata calls at most 0.29s each. So about **1.4s**, and **2.3s** cold.
#: **ORCID adds one request after the pair, on a miss only**: 0.16 to 0.36s on
#: 2026-11-16, so a name neither national file holds is about **1.8s**, and
#: **2.7s** cold.
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

    Binds this module's budget to `deadline.in_`, which is what a deadline is:
    one value bounding a chain instead of each link.

    **Kept as a name of its own because three call sites read it**, all in
    `routers/books.py`, which would otherwise each import `deadline` and reach
    in here for `DEADLINE_SECONDS`. `covers` and `z3950` own a budget too and
    call `in_` inline, at one site and two, which is what a name of their own
    would be worth.
    """
    return in_(DEADLINE_SECONDS)


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

    `born` and `died` are the dates as the file writes them, which is a partial
    date on many records (`1850-11-13`, or `1850`, or absent): the GND's
    `dateOfBirth`, and the NAF's `046 $f` and `$g`, which are EDTF; ORCID
    carries neither. Kept as strings
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
    #: never fetched. This is where the VIAF cluster id arrives. Empty for an
    #: LCNAF or ORCID candidate, whose cross references are not read.
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
    """A supplier did not answer, or answered something this module cannot read.

    One exception for both, because the caller's options are the same: say the
    suggestion could not be fetched. Nobody is blocked by it, since every write
    in this feature is optional. On a name search it reaches the caller only
    where neither file found anybody: see `search`.

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
        variants=_variants(record),
        born=_first_string(record.get("dateOfBirth")),
        died=_first_string(record.get("dateOfDeath")),
        same_as=_web_links(record),
        certain=certain,
    )


def _variants(record: dict[str, Any]) -> tuple[str, ...]:
    """The other forms of the name a lobid record carries, stripped, blanks dropped."""
    return tuple(
        value.strip() for value in record.get("variantName") or () if isinstance(value, str) and value.strip()
    )


def _web_links(record: dict[str, Any]) -> tuple[str, ...]:
    """The URIs a lobid record's `sameAs` members carry, web ones only.

    **Restricted to `http` and `https`.** Nothing renders this yet, and the
    obvious rendering is a link, so the contract is being frozen now with the
    scheme checked rather than later with a `javascript:` URI from a third
    party already in the shape. The same rule `custom_fields.link_target`
    applies to a value a member typed, applied to one an authority file
    supplied.
    """
    # `sameAs` members are objects carrying an `id`.
    return tuple(
        entry["id"]
        for entry in record.get("sameAs") or ()
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and entry["id"].lower().startswith(("http://", "https://"))
    )


def _linked(pattern: re.Pattern[str], uris: tuple[str, ...]) -> frozenset[str]:
    """Every id these URIs carry for one scheme, whatever their order.

    **A set, and there is deliberately no reader of the first.** Which one a
    record lists first is lobid's serialisation, not a claim, so every reading
    of a record's cross references goes through this or through `_sole`.
    """
    return frozenset(found.group(1) for uri in uris if (found := pattern.match(uri)) is not None)


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


def _reached(body: dict[str, Any], *path: str) -> Any:
    """The value at `path` in a Wikidata answer, or None where a key on the way
    is missing. A step holding nothing is read as an empty mapping, and one
    holding something other than a mapping raises `AttributeError`."""
    value: Any = body
    for key in path:
        value = (value or {}).get(key)
    return value


#: Which Wikidata property holds each supplier's identifier, for the reverse
#: lookup `_item_for` makes. A candidate of a scheme not listed here is not
#: looked up, rather than looked up under the wrong property: a typo there is a
#: zero result, which reads as "Wikidata holds nobody", as `_P_GND` says.
_WIKIDATA_PROPERTY: Final = {
    AuthorityScheme.GND: _P_GND,
    AuthorityScheme.LCNAF: _P_LCNAF,
    AuthorityScheme.ORCID: _P_ORCID,
}


async def _item_for(candidate: AuthorityCandidate, deadline: float | None) -> str | None:
    """The Wikidata item whose `P227` (GND), `P244` (LCNAF) or `P496` (ORCID) is
    this candidate's number, found by Wikidata.

    **Not read from lobid's `sameAs`**, and that is the whole point of the second
    supplier: two independent assertions about one link can be compared, and one
    copied from the other cannot.

    Zero hits is an ordinary answer and means Wikidata holds no item for this
    person. It is a hint for whoever is confirming and never a rule: see
    `AuthorityCandidate`.
    """
    prop = _WIKIDATA_PROPERTY.get(candidate.scheme)
    if prop is None:
        return None
    body = await _wikidata(
        {
            "action": "query",
            "list": "search",
            "srsearch": f"haswbstatement:{prop}={candidate.identifier}",
            "srlimit": "1",
        },
        deadline,
    )
    if not isinstance(body, dict):
        return None
    hits = _reached(body, "query", "search")
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
    descriptions = _reached(body, "entities", item, "descriptions") or {}
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
    body = await _wikidata({"action": "wbgetclaims", "entity": item, "property": prop}, deadline)
    if not isinstance(body, dict):
        return ()
    found: list[str] = []
    for statement in (body.get("claims") or {}).get(prop) or []:
        value = _statement_value(statement)
        if value is not None and value not in found:
            found.append(value)
    return tuple(found)


def _statement_value(statement: Any) -> str | None:
    """The string one Wikidata statement asserts, or None for a deprecated or unusable one."""
    if not isinstance(statement, dict):
        return None
    if statement.get("rank") == "deprecated":
        return None
    value = ((statement.get("mainsnak") or {}).get("datavalue") or {}).get("value")
    return value if isinstance(value, str) and value else None


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
    compared = (
        _disagreement(candidate, AuthorityScheme.WIKIDATA, _ITEM_URI, item),
        _disagreement(candidate, AuthorityScheme.VIAF, _VIAF_URI, viaf),
        _disagreement(candidate, AuthorityScheme.ISNI, _ISNI_URI, isni),
    )
    return tuple(row for row in compared if row is not None)


def _disagreement(
    candidate: AuthorityCandidate, about: AuthorityScheme, pattern: re.Pattern[str], wikidata: str | None
) -> Disagreement | None:
    """One comparison of `_disagreements`, or None where the two agree or either is silent.

    **The two agree only where the record links exactly one value and it is
    Wikidata's**, the rule `_sole` states for storage. A record linking two,
    one of them Wikidata's, is contested rather than settled by Wikidata
    naming one: picking that one would be precedence, and `cross_references`
    then stores neither, in either order. `lobid` is None in that row because
    the record names no single value; every one stays in `same_as`.
    """
    linked = _linked(pattern, candidate.same_as)
    if not linked or wikidata is None or linked == {wikidata}:
        return None
    return Disagreement(about=about.value, lobid=_sole(pattern, candidate.same_as), wikidata=wikidata)


#: Which `sameAs` URI carries which scheme's identifier.
#:
#: A mapping rather than four `if` arms, so `cross_references` cannot grow a
#: scheme the pattern list does not know about, and so the set is readable in
#: one place beside `AuthorityScheme`.
#:
#: **Not every member of `AuthorityScheme` is here, and that is the split
#: between the two writers.** These five arrive in a `sameAs` block for free;
#: the six national files arrive only from a VIAF cluster and are listed in
#: `_NATIONAL_SOURCES`. A scheme in neither is a member nothing writes.
_CROSS_REFERENCE_URIS: Final = {
    AuthorityScheme.ISNI: _ISNI_URI,
    AuthorityScheme.LCNAF: _LCNAF_URI,
    AuthorityScheme.VIAF: _VIAF_URI,
    AuthorityScheme.WIKIDATA: _ITEM_URI,
    AuthorityScheme.ORCID: _ORCID_URI,
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
    be in conflict when only one has spoken. A record linking several items,
    the reverse lookup's among them, is contested by `_disagreement`, so the
    reverse lookup never picks one of several.

    **A scheme only where the record carries exactly one of its values.** A
    record linking two is two claims about one person: GND `1344514472` and
    `1329281446` each carry two `orcid.org` links, and of 4,340 differentiated
    persons carrying an ISNI, spread over ten `gndIdentifier` prefixes, 8 link
    two ISNIs, 8 two Wikidata items and 2 two LCNAF numbers, measured
    2026-11-16. Taking the first would be resolution by ordering, the rule
    `_claims` states, so none is written and every one stays in `same_as`.
    `_disagreement` compares by the same rule, so the record's order decides
    neither what is stored nor what is contested.
    """
    contested = {row.about for row in candidate.disagreements}
    found: dict[AuthorityScheme, str] = {}
    for scheme, pattern in _CROSS_REFERENCE_URIS.items():
        if scheme.value in contested:
            continue
        value = _referenced(candidate, scheme, pattern)
        if value is not None:
            found[scheme] = value
    return found


def _referenced(
    candidate: AuthorityCandidate, scheme: AuthorityScheme, pattern: re.Pattern[str]
) -> str | None:
    """One scheme's identifier among a candidate's cross references, by the two
    rules `cross_references` states, or None."""
    if scheme is AuthorityScheme.WIKIDATA and candidate.wikidata_id is not None:
        return candidate.wikidata_id
    return _sole(pattern, candidate.same_as)


def _sole(pattern: re.Pattern[str], uris: tuple[str, ...]) -> str | None:
    """The one id these URIs carry, or None where they carry none or several."""
    found = _linked(pattern, uris)
    return next(iter(found)) if len(found) == 1 else None


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
    """
    # None means "named twice with different values", which is the drop rule
    # holding one bit rather than a set. See the docstring: a set here is
    # unbounded in a body this module accepts.
    found: dict[str, str | None] = {}
    for block in _listed(_under(_under(cluster, "mainHeadings"), "data"), dict):
        for entry in _listed(_under(_under(block, "sources"), "sid"), str):
            named = _viaf_source(entry, wanted)
            if named is None:
                continue
            code, identifier = named
            if code not in found:
                found[code] = identifier
            elif found[code] != identifier:
                found[code] = None
    return {code: value for code, value in found.items() if value is not None}


def _listed(value: Any, single: type) -> list[Any]:
    """A VIAF field that is a list in one block and a bare `single` in the next, as a list.

    Anything else is an empty list, so a shape VIAF has not been seen to send
    contributes nothing rather than raising. See `_viaf_sources` for the record
    that carried both shapes at once.
    """
    if isinstance(value, single):
        return [value]
    return value if isinstance(value, list) else []


def _viaf_source(entry: Any, wanted: frozenset[str]) -> tuple[str, str] | None:
    """One `sid` entry as `(code, identifier)`, or None for a malformed or unwanted one.

    `partition` rather than `split`, because an identifier legitimately contains
    a separator of its own: `LIH|LNB:V-174543;=BK` is one code and one number.
    """
    if not isinstance(entry, str):
        return None
    code, separator, identifier = entry.partition("|")
    code, identifier = code.strip(), identifier.strip()
    if not separator or not code or not identifier or code not in wanted:
        return None
    return code, identifier


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
        response = await fetch.get(client, url, params=params, limit=_VIAF_LIMIT, deadline=deadline)
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
    evidence for the loop in `_clusters_naming` is the rule, not a measurement,
    and that is stated rather than dressed up as a bug found in the wild.

    The distinct `viafid` values are collected **before** being validated, so a
    second hit carrying an unusable id still counts as ambiguity. Discarding it
    first would let a bad value silently promote a single survivor.

    No Lucene escaping, because this is not a query language: `query=` here is a
    plain prefix term. It is still truncated to `MAX_QUERY_NAME`, which bounds
    the request rather than the name.
    """
    _, body = await _viaf_json(client, _VIAF_AUTOSUGGEST_URL, {"query": name[:MAX_QUERY_NAME]}, deadline)
    if not isinstance(body, dict):
        return None, False
    matched = _clusters_naming(body.get("result"), gnd)
    if matched is None or len(matched) != 1:
        return None, True
    only = matched.pop()
    return (only, True) if _VIAF_CLUSTER.match(only) else (None, True)


def _clusters_naming(hits: Any, gnd: str) -> set[str] | None:
    """The distinct clusters `AutoSuggest` offers as this GND number's person, read up to the second.

    **None where a matching hit names its cluster in a shape that is not a
    string**, which answers the question with nobody, whatever the hits before
    it said. `_viaf_cluster_by_gnd` applies the one rule to what comes back.
    """
    matched: set[str] = set()
    for hit in hits or []:
        if not _offers_the_person(hit, gnd):
            continue
        cluster = hit.get("viafid")
        if not isinstance(cluster, str):
            return None
        matched.add(cluster)
        # **Stops reading, and decides nothing.** `result` is somebody else's
        # list and two distinct clusters already answer the question, so there
        # is no reason to walk the rest. The rule itself is the single check
        # in `_viaf_cluster_by_gnd`.
        #
        # This used to `return None` here, which put the rule in two places and
        # made that check unreachable for the case it exists for. A mutation
        # replacing it with `if not matched` was then **equivalent**, and
        # survived at 166 passed: the early return was silently doing all the
        # work. A guard whose subject is enforced somewhere else is not a guard.
        if len(matched) > 1:
            logger.info("VIAF offered more than one cluster for one GND number")
            break
    return matched


def _offers_the_person(hit: Any, gnd: str) -> bool:
    """Whether one `AutoSuggest` hit is a personal cluster carrying this GND number."""
    return isinstance(hit, dict) and hit.get("nametype") == "personal" and hit.get("dnb") == gnd


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
        _, body = await _viaf_json(client, _VIAF_RECORD_URL.format(cluster=cluster), None, deadline)
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
    route. Where lobid and Wikidata name different items for one person, or
    lobid links several and Wikidata names one of them, reading
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
        cluster, heard = await _cluster_for(client, candidate, deadline)
        if cluster is not None and _VIAF_CLUSTER.match(cluster):
            sources = await _viaf_cluster_sources(client, cluster, deadline, _WANTED_SOURCES)
        elif heard:
            # VIAF answered and named nobody, or named two people, or named a
            # cluster id that is not one. That is an answer and it stands: the
            # fallback is for an outage, not for a second opinion on a question
            # VIAF has already refused.
            return {}

    if sources is None:
        logger.info("VIAF produced no cluster; asking Wikidata for the national files")
        return await _national_from_wikidata(candidate, deadline)

    return _national_from_cluster(candidate, sources)


async def _cluster_for(
    client: Any, candidate: AuthorityCandidate, deadline: float | None
) -> tuple[str | None, bool]:
    """The VIAF cluster to read for this person, lobid's own or one asked of
    VIAF by name, and whether VIAF has answered.

    lobid's own only where the record links exactly one, by `_sole`; a record
    linking several is asked by name, which still has to name the GND number
    back before anything is read.
    """
    cluster = _sole(_VIAF_URI, candidate.same_as)
    # `heard` is the whole reason this is a tuple. A cluster read out of
    # lobid's `sameAs` costs no VIAF request, so reaching this branch and
    # coming back empty is the only place "VIAF is down" and "VIAF knows
    # nobody by that name" have to be told apart.
    #
    # **A cluster lobid named returns `heard` as False, because `heard` means
    # "VIAF has answered" and nothing has asked VIAF yet.** True there was
    # the trigger line inverted, and it was reachable: a
    # `sameAs` id is matched by `_VIAF_URI`, whose digits are unbounded,
    # and then rejected by `_VIAF_CLUSTER`, which allows twenty. A
    # twenty-one digit id therefore reached `elif heard: return {}` in
    # `national_identifiers` with no request made at all, which is a supply
    # failure recorded as an answer.
    if cluster is None:
        return await _viaf_cluster_by_gnd(client, candidate.name, candidate.identifier, deadline)
    return cluster, False


def _national_from_cluster(
    candidate: AuthorityCandidate, sources: dict[str, str]
) -> dict[AuthorityScheme, str]:
    """The six national numbers a cluster names, once it has named the confirmed GND record back.

    The second direction of the check `national_identifiers` describes: a
    cluster found from lobid's `sameAs` or by name must carry this GND number
    itself, or nothing it names is read.
    """
    if sources.get(_GND_SOURCE) != candidate.identifier:
        logger.info("A VIAF cluster did not name the confirmed GND record back")
        return {}
    return {scheme: sources[code] for code, scheme in _NATIONAL_SOURCES.items() if code in sources}


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
    item = await _item_for(candidate, deadline)
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


async def resolve(identifier: str, *, deadline: float | None = None) -> AuthorityCandidate | None:
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


async def resolve_stored(
    stored: list[tuple[AuthorityScheme, str]], *, deadline: float | None = None
) -> list[AuthorityCandidate]:
    """The people this Library's stored identifiers name, at most `MAX_CANDIDATES`.

    **One file's numbers, the first in `_STORED_ORDER` that has any.** A GND
    record confirmed here arrives with its LCNAF number and its ORCID as cross
    references, so asking every file would show one person several times and
    pay a request for each. An LCNAF number or an ORCID stands alone only where
    a Member confirmed that file's record, and then it is the one key there is.
    A scheme no file here can be asked by is passed over rather than spent: it
    used to take one of the five places and answer nothing.

    **Certain**, as `resolve` is, and None is dropped: a number the file no
    longer holds answers nothing rather than an error.
    """
    for wanted, resolver in _STORED_ORDER:
        # `==` and not `is`: `AuthorIdentifier.scheme` is a `String` column, so
        # a stored row hands back a plain `str` whatever its annotation says,
        # and `is` matched no row at all.
        numbers = [identifier for scheme, identifier in stored if scheme == wanted]
        if numbers:
            found = await asyncio.gather(*(resolver(number, deadline) for number in numbers[:MAX_CANDIDATES]))
            return [candidate for candidate in found if candidate is not None]
    return []


async def search(name: str, *, deadline: float | None = None) -> list[AuthorityCandidate]:
    """The people the authority files hold under one name. A guess, every time.

    **A name is not a key**, which is the entire reason the confirmation step
    exists, and it is demonstrated rather than asserted: `Stevenson, Robert
    Louis` matches two differentiated persons. Nothing here decides between them
    and nothing here writes: `POST /authors/identifiers` is where a Member says
    which one it is.

    **lobid's people first, then the NAF's**, each file bounded by
    `MAX_CANDIDATES`, and asked together rather than one after the other. A NAF
    record whose number a GND record's `sameAs` already carries is the same
    person and is dropped, because that is two files asserting the link rather
    than two names looking alike. This adds a file; it does not decide which
    file a search should trust first.

    **ORCID only where both answered and found nobody**, the rank the owner
    set on 2026-09-05: a fallback for the names the national files do not
    carry, so its request is paid on a miss and never on an ordinary search.
    A file that did not answer has not found nobody, so a national file down
    raises before ORCID is asked, as it did before ORCID was a file: its
    researchers sharing the name are not an answer to "try again".

    **One file failing costs its own people and no more.** The search raises
    only where nobody was found and a file did not answer, because an empty
    list then would say "nobody by that name" when the truth is "not asked".
    ORCID down after both found nobody raises for the same reason.

    An empty or unusable name answers an empty list rather than putting a
    useless query to somebody else's service.
    """
    query = name.strip()
    if not _escaped(query):
        return []
    gnd, naf = await asyncio.gather(
        _gnd_people(query, deadline), _naf_people(query, deadline), return_exceptions=True
    )
    people = _merged(gnd, naf)
    if not people:
        people = await _orcid_people(query, deadline)
    return list(
        await asyncio.gather(
            *(_cross_check(row, compare_references=False, deadline=deadline) for row in people)
        )
    )


async def _gnd_people(query: str, deadline: float | None) -> list[AuthorityCandidate]:
    """The people lobid holds under one name, at most `MAX_CANDIDATES`."""
    body = await _lobid(
        _LOBID_SEARCH_URL,
        params={
            "q": _escaped(query),
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
    return [row for row in found if row is not None][:MAX_CANDIDATES]


def _merged(
    gnd: list[AuthorityCandidate] | BaseException, naf: list[AuthorityCandidate] | BaseException
) -> list[AuthorityCandidate]:
    """Both files' people as one list, lobid's first, the NAF's duplicates dropped.

    **Only `AuthorityUnavailable` is a file not answering.** Anything else is a
    defect, and it is raised rather than read as an outage, which would turn a
    bug into a quiet empty list. A cancellation is one of those.
    """
    gnd_people, gnd_answered = _answered(gnd)
    naf_people, naf_answered = _answered(naf)
    if not naf_answered:
        logger.info("The Library of Congress name authority file did not answer")
    linked = {number for row in gnd_people for number in _linked(_LCNAF_URI, row.same_as)}
    people = [*gnd_people, *(row for row in naf_people if row.identifier not in linked)]
    if not people and not (gnd_answered and naf_answered):
        raise AuthorityUnavailable
    return people


def _answered(
    outcome: list[AuthorityCandidate] | BaseException,
) -> tuple[list[AuthorityCandidate], bool]:
    """One file's people and whether it answered; a defect raised, for the reason `_merged` gives."""
    if isinstance(outcome, AuthorityUnavailable):
        return [], False
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome, True


def _catalogue_order(name: str) -> str:
    """One name as the NAF heads it: surname first.

    **The NAF's name index matches a heading's leading words, so reading order
    finds nothing**: measured 2026-11-16, `Ursula Le Guin` answers 0 records and
    `Le Guin, Ursula K` 429. A name holding a comma is taken as already in that
    order, which is how a Member retyping the search (`q` on the route) reaches
    a surname of two words; anything else has its last word moved to the front,
    which is right for a surname of one word and wrong for `Le Guin`.
    """
    if "," in name:
        return name
    words = name.split()
    if len(words) < 2:
        return name
    return f"{words[-1]}, {' '.join(words[:-1])}"


def _cql_term(text: str) -> str:
    """One string as the inside of a quoted CQL term, truncated before escaping
    for the reason `_escaped` gives."""
    return text[:MAX_QUERY_NAME].translate(_CQL_ESCAPED)


async def _naf_people(query: str, deadline: float | None) -> list[AuthorityCandidate]:
    """The people the NAF holds under one name, at most `MAX_CANDIDATES`."""
    found = await _naf(
        f'bath.personalName="{_cql_term(_catalogue_order(query))}"',
        _NAF_PAGE,
        certain=False,
        deadline=deadline,
    )
    return found[:MAX_CANDIDATES]


def _lccn_query(identifier: str) -> str | None:
    """A stored LCNAF number as the NAF's `bath.lccn` index matches it, or None.

    **The stored form is unspaced and the index's is not**, so the number
    cannot be put to it as it is: `n78088964` answers 0 records and
    `n 78088964` answers the record. MARC pads the prefix to three characters
    before eight digits and to two before ten, and the index collapses the
    padding to one space. Measured 2026-11-16 over eleven numbers of all six
    shapes the sample held (`n`, `no` with eight digits; `n`, `nb`, `no`, `nr`
    with ten): every one came back as itself.
    """
    found = _LCCN.match(identifier)
    if found is None:
        return None
    prefix, digits = found.groups()
    width = 3 if len(digits) == 8 else 2
    return f"{prefix} {digits}" if len(prefix) < width else f"{prefix}{digits}"


async def _naf_resolve(identifier: str, deadline: float | None) -> AuthorityCandidate | None:
    """The one person an LCNAF number names, or None if the file does not hold it.

    Certain for the reason `resolve` is. Cross checked without the reference
    comparison, which reads a GND record's `sameAs` and has nothing to read
    here.
    """
    query = _lccn_query(identifier)
    if query is None:
        logger.info("Refused to resolve an identifier that is not an LCNAF number")
        return None
    found = await _naf(f'bath.lccn="{query}"', 1, certain=True, deadline=deadline)
    for candidate in found:
        if candidate.identifier == identifier:
            return await _cross_check(candidate, compare_references=False, deadline=deadline)
    return None


class _ColdSession(AuthorityUnavailable):
    """The NAF answered `_NAF_COLD_SESSION`, which is worth asking once more."""


async def _naf(
    query: str, maximum: int, *, certain: bool, deadline: float | None
) -> list[AuthorityCandidate]:
    """One NAF search, asked again once where the gateway's session was cold.

    `AuthorityUnavailable` for anything else `_naf_read` refuses, and for one
    cold answer following another.
    """
    params = {
        "operation": "searchRetrieve",
        "version": "1.1",
        "recordSchema": "marcxml",
        "maximumRecords": str(maximum),
        "query": query,
    }
    try:
        return _naf_read(await _naf_get(params, deadline), certain=certain)
    except _ColdSession:
        return _naf_read(await _naf_get(params, deadline), certain=certain)


async def _naf_get(params: dict[str, str], deadline: float | None) -> fetch.Fetched:
    """One bounded call to the NAF, or `AuthorityUnavailable`."""
    try:
        return await fetch.get_once(_NAF_URL, params=params, limit=_RESPONSE_LIMIT, deadline=deadline)
    except Exception as failure:
        raise AuthorityUnavailable from failure


def _naf_read(response: fetch.Fetched, *, certain: bool = False) -> list[AuthorityCandidate]:
    """The people one NAF response holds, or `AuthorityUnavailable`.

    **The fourth door that turns outside XML into a tree**, on the terms the
    other three keep: a document type declaration is refused before the parse,
    for the reason `metadata.DOCTYPE` gives, the bytes are capped by
    `_RESPONSE_LIMIT` before they arrive, and the tree is built through
    `xml_parse`, which bounds the rest, within `ALLOCATION_FACTOR`. The gateway
    is plaintext, so the body is whatever anybody on the path chose to send.

    **A diagnostic is a refusal, never an empty answer.** The gateway answers
    every error with HTTP 200 and a well formed envelope holding no records, so
    reading one as "nobody" would put an outage in front of a Member as an
    answer. `_ColdSession` is the one worth asking again.

    **But people that parse win, and only the envelope's own diagnostics are
    read**, the rule `metadata._sru_refusal` states and why: SRU lets a
    diagnostic stand in for one record it could not render, and that says
    nothing about the 24 beside it.
    """
    if response.status_code != 200:
        raise AuthorityUnavailable
    body = response.text
    if metadata.DOCTYPE in body:
        raise AuthorityUnavailable
    parser = ElementTree.XMLParser(target=xml_parse.DepthBoundedTree())  # noqa: S314  doctype refused above, bytes capped, depth bounded
    try:
        root = xml_parse.fed(parser, body)
    except ElementTree.ParseError as failure:
        raise AuthorityUnavailable from failure
    found = (_naf_person(node, certain=certain) for node in root.iter(marc_fields.RECORD_TAG))
    people = [row for row in found if row is not None]
    if not people:
        _naf_refuse_on_diagnostic(root)
    return people


def _naf_refuse_on_diagnostic(root: ElementTree.Element) -> None:
    """Raise where the envelope itself carries a diagnostic, a direct child of
    the response; one inside `records` describes one record and is not read."""
    diagnostic = root.find(f"{_SRU_DIAGNOSTICS}//{_SRU_DIAGNOSTIC_URI}")
    if diagnostic is not None:
        raise _ColdSession if diagnostic.text == _NAF_COLD_SESSION else AuthorityUnavailable


#: Where the kind of record and the undifferentiated name flag sit in an
#: authority record's `008`: `a` at 9 is an established heading rather than a
#: reference, and `b` at 32 is a name the file could not tell apart from others.
_KIND_OF_RECORD: Final = 9
_UNDIFFERENTIATED: Final = 32

#: Where a MARC21 leader says what kind of record it is: `z` is an authority.
_RECORD_TYPE: Final = 6


def _naf_person(node: ElementTree.Element, *, certain: bool) -> AuthorityCandidate | None:
    """One MARC21 authority record as a candidate, or None where it is not a person.

    **A person is an established, differentiated personal name heading with no
    title in it**: a `100` without `$t` (a `$t` makes it a work, the name and
    title records `_NAF_PAGE` is sized around), not a family (`100` first
    indicator `3`), not a reference record, and not undifferentiated, which is
    the record `_PERSON_FILTER` refuses on the GND side for the same reason. Of
    the 329 records with a `100` sampled on 2026-11-16, 318 were name and title
    records and the 11 people were all established and differentiated.

    **Only an authority record, leader/06 `z`.** A bibliographic record's `008`
    means something else at 9 and 32, so it would otherwise pass on whatever
    those positions happen to hold. That is also why no carrier test is asked:
    what reaches `Fields` here describes a person and never a book.

    Dropped rather than raised, the call `_candidate` makes.
    """
    identifier = _naf_established(node)
    if identifier is None:
        return None
    fields = marc_fields.Fields(node)
    entry = _naf_personal_heading(node, fields)
    if entry is None:
        return None
    name = strip_isbd_punctuation(entry.get("a", ""))
    if not name:
        return None
    born, died = _naf_dates(fields)
    return AuthorityCandidate(
        scheme=AuthorityScheme.LCNAF,
        identifier=identifier,
        name=name,
        variants=_naf_variants(fields, name),
        born=born,
        died=died,
        certain=certain,
    )


def _naf_established(node: ElementTree.Element) -> str | None:
    """The LCNAF number of an authority record for an established,
    differentiated heading, or None."""
    if node.findtext(f"{_MARC}leader", "")[_RECORD_TYPE : _RECORD_TYPE + 1] != "z":
        return None
    controls = _naf_controls(node)
    identifier = "".join(controls.get("001", "").split())
    fixed = controls.get("008", "")
    if not _LCCN.match(identifier) or len(fixed) <= _UNDIFFERENTIATED:
        return None
    if fixed[_KIND_OF_RECORD] != "a" or fixed[_UNDIFFERENTIATED] == "b":
        return None
    return identifier


def _naf_controls(node: ElementTree.Element) -> dict[str | None, str]:
    """A record's control fields by tag, an empty one as the empty string."""
    return {field.get("tag"): field.text or "" for field in node.findall(f"{_MARC}controlfield")}


def _naf_personal_heading(
    node: ElementTree.Element, fields: marc_fields.Fields
) -> marc_fields.Subfields | None:
    """The `100` of a single person with no title in it, or None: a family is
    first indicator `3`, and a `$t` makes it a work."""
    heading = node.find(f"{_MARC}datafield[@tag='100']")
    if heading is None or heading.get("ind1") == "3":
        return None
    entry = fields.get("100")[0]
    return None if "t" in entry else entry


def _naf_dates(fields: marc_fields.Fields) -> tuple[str | None, str | None]:
    """Birth and death as the `046` gives them, `$f` and `$g`."""
    dates = fields.get("046")
    if not dates:
        return None, None
    return dates[0].get("f"), dates[0].get("g")


def _naf_variants(fields: marc_fields.Fields, name: str) -> tuple[str, ...]:
    """The other personal names a NAF record lists, as `_variants` reads lobid's.

    `400`, which is "see from" this name; one carrying `$t` names a work and is
    left out with the `100` rule's reason. Repeats and the heading itself are
    dropped, since `Stevenson, Robert Lui` arrives twice, once with dates.
    """
    seen: dict[str, None] = {}
    for entry in fields.get("400"):
        variant = strip_isbd_punctuation(entry.get("a", ""))
        if variant and variant != name and "t" not in entry:
            seen.setdefault(variant)
    return tuple(seen)


#: ORCID's public API, version 3.0, asked without a client credential.
#:
#: **The anonymous tier, and its terms were read rather than assumed.** On
#: 2026-11-16 ORCID's API limits page gave the anonymous tier 12 requests a
#: second, a burst of 40, and 25,000 reads a day per IP address. A registered
#: client raises the daily figure and nothing else, so none is used.
#:
#: **ORCID's terms make this API free for non commercial use, and they bind
#: whoever runs a deployment that asks it, not this code.** Its Public APIs
#: Terms of Service (updated 23 October 2024) "describe conditions under which
#: ORCID allows the public to access our Anonymous API and Public API
#: (together the Public APIs)", and say "you may not make use of the public
#: APIs in connection with any revenue-generating product or service". The
#: anonymous tier is named inside that definition, so staying anonymous does
#: not step outside the clause. This module asks once per name search the two files before it
#: answered with nobody, and once per stored ORCID resolved, under
#: `ratelimit.AUTHORITY_LIMIT`.
#:
#: **`expanded-search` rather than `search`**, because it answers the names in
#: the same request: `search` answers bare iDs, and a record per iD would follow.
_ORCID_SEARCH_URL: Final = "https://pub.orcid.org/v3.0/expanded-search/"

#: The header ORCID answers JSON on. Without it the same request answers
#: ORCID's own XML, measured 2026-11-16.
_ORCID_ACCEPT: Final = "application/json"

#: The quote and the backslash, each escaped: the two characters that end or
#: break a quoted Solr phrase. Inside the quotes nothing else is syntax, and
#: unescaped syntax is measured: `family-name:(Stevenson (` answered HTTP 500
#: with a Solr parse error on 2026-11-16.
_PHRASE_ESCAPED: Final = str.maketrans({character: f"\\{character}" for character in '\\"'})


async def _orcid_people(query: str, deadline: float | None) -> list[AuthorityCandidate]:
    """The people ORCID holds under one name, at most `MAX_CANDIDATES`.

    **By surname and first given name, as fields.** ORCID holds the two apart,
    so the name is put in catalogue order the way `_catalogue_order` puts it to
    the NAF and split at its comma. Only the first given name is asked, because
    ORCID's `given-names` is what a researcher typed: `Ursula K.` asked whole
    misses an `Ursula`. A bare surname is asked alone.
    """
    family, _, given = _catalogue_order(query).partition(",")
    if not family.strip():
        return []
    clauses = [
        _orcid_clause("family-name", family),
        *(_orcid_clause("given-names", word) for word in given.split()[:1]),
    ]
    return (await _orcid(" AND ".join(clauses), deadline, certain=False))[:MAX_CANDIDATES]


def _orcid_clause(field: str, text: str) -> str:
    """One field of an ORCID query, its text a quoted phrase, truncated before
    escaping for the reason `_escaped` gives."""
    return f'{field}:"{text.strip()[:MAX_QUERY_NAME].translate(_PHRASE_ESCAPED)}"'


async def _orcid_resolve(identifier: str, deadline: float | None) -> AuthorityCandidate | None:
    """The one person an ORCID iD names, or None if ORCID does not hold it.

    Certain for the reason `resolve` is, and cross checked as `_naf_resolve` is.
    """
    if not _ORCID_ID.match(identifier):
        logger.info("Refused to resolve an identifier that is not an ORCID iD")
        return None
    for candidate in await _orcid(f"orcid:{identifier}", deadline, certain=True):
        if candidate.identifier == identifier:
            return await _cross_check(candidate, compare_references=False, deadline=deadline)
    return None


async def _orcid(query: str, deadline: float | None, *, certain: bool) -> list[AuthorityCandidate]:
    """One ORCID search, or `AuthorityUnavailable`."""
    try:
        async with fetch.catalogue_client() as client:
            client.headers["accept"] = _ORCID_ACCEPT
            response = await fetch.get(
                client,
                _ORCID_SEARCH_URL,
                params={"q": query, "rows": str(MAX_CANDIDATES)},
                limit=_RESPONSE_LIMIT,
                deadline=deadline,
            )
    except Exception as failure:
        raise AuthorityUnavailable from failure
    return _orcid_read(response, certain=certain)


def _orcid_read(response: fetch.Fetched, *, certain: bool) -> list[AuthorityCandidate]:
    """The people one ORCID answer holds, or `AuthorityUnavailable`.

    **`expanded-result` null is nobody, and its absence is not.** ORCID answers
    a search finding nobody with the key present and null, so a body without
    it, or with something other than a list in it, is an answer this module
    cannot read rather than an empty one.
    """
    if response.status_code != 200:
        raise AuthorityUnavailable
    try:
        body = response.json()
    except ValueError as failure:
        raise AuthorityUnavailable from failure
    rows = body.get("expanded-result", False) if isinstance(body, dict) else False
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise AuthorityUnavailable
    found = (_orcid_person(row, certain=certain) for row in rows)
    return [row for row in found if row is not None]


def _orcid_person(row: Any, *, certain: bool) -> AuthorityCandidate | None:
    """One ORCID result as a candidate, or None where it carries no iD or no name.

    **Its names and nothing else.** A result also lists the researcher's email
    addresses and employers, and neither is read: an address is personal data
    with no use here, and an employer is the body of work `docs/featurelist.md`
    refuses, which is why `professionOrOccupation` is not read from lobid.

    Dropped rather than raised, the call `_candidate` makes.
    """
    if not isinstance(row, dict):
        return None
    identifier = row.get("orcid-id")
    if not isinstance(identifier, str) or not _ORCID_ID.match(identifier):
        return None
    name = ", ".join(_orcid_strings(row.get("family-names"), row.get("given-names")))
    if not name:
        return None
    others = row.get("other-name")
    listed = _orcid_strings(row.get("credit-name"), *(others if isinstance(others, list) else ()))
    return AuthorityCandidate(
        scheme=AuthorityScheme.ORCID,
        identifier=identifier,
        name=name,
        variants=tuple(dict.fromkeys(value for value in listed if value != name)),
        certain=certain,
    )


def _orcid_strings(*values: Any) -> list[str]:
    """The non blank strings among these, stripped, in order."""
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


async def _gnd_resolve(identifier: str, deadline: float | None) -> AuthorityCandidate | None:
    """`resolve` in the shape the other two files' resolvers take."""
    return await resolve(identifier, deadline=deadline)


#: Which file a stored identifier is resolved by, in the order `resolve_stored`
#: asks them: the first scheme with a number stored is the only one asked.
_STORED_ORDER: Final = (
    (AuthorityScheme.GND, _gnd_resolve),
    (AuthorityScheme.LCNAF, _naf_resolve),
    (AuthorityScheme.ORCID, _orcid_resolve),
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
_WIKIPEDIA_ARTICLE: Final = re.compile(r"\Ahttps://([a-z0-9-]{2,32})\.wikipedia\.org/wiki/[^\s\"'<>]+\Z")

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
    return {item: _editions(entities.get(item)) for item in items}


def _editions(entity: Any) -> dict[str, str]:
    """One entity's Wikipedia articles as `{language: url}`, each URL checked by `_WIKIPEDIA_ARTICLE`."""
    links = entity.get("sitelinks") if isinstance(entity, dict) else None
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
    return articles


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
    articles, answered = await _filtered_pass(looked_up, sitefilter, deadline)

    # Its own chunk size and its own ceiling, and both are the same fault seen
    # twice: an unfiltered entity reaches 64,449 bytes where a filtered one is
    # about 300, so the fifty of `_ITEMS_PER_REQUEST` that is safe above is six
    # times the response cap here. See `_UNFILTERED_ITEMS_PER_REQUEST`.
    missing = tuple(item for item in answered if not articles.get(item))[:MAX_UNFILTERED_ITEMS]
    articles.update(await _unfiltered_pass(missing, deadline))

    return {item: _article_for(item, articles.get(item) or {}, prefer) for item in wanted}


async def _filtered_pass(
    items: tuple[str, ...], sitefilter: str, deadline: float | None
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """The cheap pass of `wikipedia_articles`: its articles, and the items it answered about.

    Only the items a filtered pass **answered about** may reach the unfiltered
    one. A chunk whose request failed is not a chunk with no article.
    """
    articles: dict[str, dict[str, str]] = {}
    answered: list[str] = []
    for start in range(0, len(items), _ITEMS_PER_REQUEST):
        chunk = items[start : start + _ITEMS_PER_REQUEST]
        found = await _sitelinks(chunk, sitefilter, deadline)
        if found is None:
            continue
        answered.extend(chunk)
        articles.update(found)
    return articles, answered


async def _unfiltered_pass(items: tuple[str, ...], deadline: float | None) -> dict[str, dict[str, str]]:
    """The expensive pass of `wikipedia_articles`, at `_UNFILTERED_ITEMS_PER_REQUEST` a request."""
    articles: dict[str, dict[str, str]] = {}
    for start in range(0, len(items), _UNFILTERED_ITEMS_PER_REQUEST):
        found = await _sitelinks(items[start : start + _UNFILTERED_ITEMS_PER_REQUEST], None, deadline)
        if found is not None:
            articles.update(found)
    return articles


def _article_for(item: str, articles: dict[str, str], prefer: tuple[str, ...]) -> WikipediaArticle:
    """The link for one person: the preferred article, or the Wikidata item page as the floor."""
    best = _preferred(articles, prefer)
    if best is None:
        return WikipediaArticle(url=_WIKIDATA_ITEM_URL.format(item=item), language=None)
    return WikipediaArticle(url=best[1], language=best[0])


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
        response = await fetch.get_once(url, params=params, limit=_RESPONSE_LIMIT, deadline=deadline)
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
