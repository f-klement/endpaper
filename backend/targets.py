"""One catalogue target as data: where it is, how it is asked, what reads it back.

**The split from `sources.py` is the one that module's own docstring already
draws.** `sources.py` owns *which* catalogues are asked and *in what order*, and
says so at length. This owns *how one of them is asked*: the address, the
transport, the query language and the parameter it travels in, the index that
means "the ISBN" there, the record schema, and how many records to ask for. Two
subjects, and keeping them apart is what lets a new national catalogue be a row
here plus a reader choice, where the National Library of Greece and the Czech
National Library were each a day of adapter code.

## The line between data and code

**Data**: everything above, plus the capabilities, whether the target is metered
and whether it needs a credential.

**Code**: the parser. A row names a `Reader` and nothing here knows what one
does. What a decoder is, why there are eight of them for six serialisations,
and why a stylesheet could not stand in for one, are `decoders.py`'s subject.
`Target.decoding` is the whole of what this module hands it, and the whole of
what it may hand it: an address or a query grammar reaching a decoder is the
weld that module exists to refuse.

## What a row can be asked for

**One declaration in one vocabulary, `enums.Capability`**, read through
`Target.can`; everything downstream asks the capability rather than a column.
The vocabulary is shared with the other source family, so "answers no ISBN" is
one statement rather than one per family. What the columns underneath still cost
and who reads them is on `Target.capabilities`, once.

## The query is built here and nowhere else

**A row names an index, never a query template.** FOLIO's `copycatprofile`
stores `externalIdQueryMap` as a template with a placeholder, `@attr 1=12
$identifier`, and the ticket's own comment names the substitution point as the
security question in the same breath. A template is a strictly larger grammar
than an index name: it can spell `num=1 or num=$isbn` and an index name cannot
spell anything at all. So the row carries `dnb`'s `num` and the NKP's use
attribute `7`, and the query around it is built by `Target.isbn_query` and
`Target.title_query`, which are the only two functions in this application that
concatenate a value into a catalogue query.

`cql_term` is the CQL half of `z3950.pqf_term`. It refuses rather than escapes,
because every value that reaches it is either thirteen ASCII digits from
`isbn.parse_isbn` or a term `metadata._search_terms` has already stripped, and a
value outside that is a bug here rather than a household's input.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, assert_never
from urllib.parse import urlsplit

import fetch
import z3950

# `Reader` is aliased to itself deliberately: `Target.reader` is typed on it, so
# it is part of this module's surface even though the decoder registry is
# `decoders.py`'s, and the redundant alias is what says so to mypy under
# `no_implicit_reexport`. Spelling it `targets.Reader` at a call site is not a
# mistake; building a decoder from anything but `Target.decoding` is.
from decoders import IMPORT_READERS, MARC_READERS, Decoding
from decoders import Reader as Reader
from enums import Capability, CatalogueSource, RecordCharset, RegisteredCatalogue, SourceFamily

# Re-exported for the reason `Reader` is: `Target.transport` is typed on it, and
# `enums.Transport` says why it lives there.
from enums import Transport as Transport
from isbn import isbn13_to_isbn10


class Secret(StrEnum):
    """Which deployment secret this row's own adapter is handed, by its owner.

    **Named for whose secret it is, and that is the whole of what this type
    buys.** `metadata.Access.api_key` is not "a credential": it is one named
    source's key, this deployment's own Google Books quota, and it travels in a
    query string. A dispatch that decides who receives it by asking whether the
    row is metered, or whether the row needs a credential, is asking a question
    several sources can answer yes to, so the first bespoke credentialled non
    Google source to arrive receives Google's key and sends it wherever its own
    adapter sends things. Both spellings were proposed and both are refused
    here: a member names an owner, so a row can claim only a secret that exists
    for it.

    **A sealed login is deliberately not a member.** Which doors carry one is
    `metadata.carries_a_credential`, which is a claim about the effect of a
    branch and is measured against whether an `Authorization` header left the
    process. A second spelling of that fact on the row would be checked only
    against the first, and the measurement that makes it worth having is the
    thing that would be lost.
    """

    #: This row's adapter is handed no deployment secret. Every SRU row, whose
    #: login travels through `fetch` bound to the origin it was sealed for, and
    #: every bespoke row that pays for nothing.
    NONE = "none"
    #: Google Books' API key, `metadata.Access.api_key`. One source is entitled
    #: to it and the enum is how that is said once.
    GOOGLE_BOOKS_KEY = "google_books_key"


class QueryLanguage(StrEnum):
    """CQL, or the PQF one target speaks instead.

    The Czech National Library answers SRU diagnostic 1/11, unsupported query
    type, to CQL in `query=`, and 1/8, unsupported parameter, to
    `queryType=x-pquery`. Measured 2026-08-31. Its query goes in `x-pquery`,
    which is YAZ's SRU 1.1 extension, and is PQF.
    """

    CQL = "cql"
    PQF = "pqf"


class TitleQuery(StrEnum):
    """The four shapes a title search takes across the roster.

    **A closed set of four rather than three orthogonal columns.** Operator,
    quoting and term joining would admit eight combinations, four of which
    nothing has ever sent to a live catalogue. Enumerating the shapes that were
    measured refuses the other four by construction, which is the direction to
    err in for a string that becomes somebody else's query.
    """

    #: `index=term and index=term`. Precision, and at the OENB a hard
    #: requirement: `alma.title=wien geschichte` answers SRU diagnostic 200812,
    #: `Invalid query`, where the ANDed pair answers with 4,885 records.
    ANDED_TERMS = "anded_terms"
    #: `index=term term`. The DNB's `WOE`, the index that takes several words
    #: and requires all of them.
    WORD_SEQUENCE = "word_sequence"
    #: `index="term term"`.
    QUOTED_PHRASE = "quoted_phrase"
    #: `index all "term term"`.
    QUOTED_ALL = "quoted_all"


#: The SRU parameters `Target.sru_params` writes itself, which a row's own query
#: parameter may not be one of. See `_check_sru`.
#:
#: **Compared case insensitively, and folded here so the comparison cannot
#: forget.** Python dict keys collide only on an exact match, so `RECORDSCHEMA`
#: displaces nothing in the request this builds and the exact spelling was
#: enough for that. It is not enough for the target: a server that reads
#: parameter names case insensitively sees two `recordSchema` values and picks
#: one, and which one it picks is its business rather than ours. Found by
#: attacking the check rather than reading it.
_RESERVED_SRU_PARAMETERS: Final = frozenset({"version", "operation", "maximumrecords", "recordschema"})

#: The sources that may waive the ISBN identity check, which is one.
#:
#: **Stated here as well as in the CHECK constraint and the test, because those
#: two disagreed with the dataclass.** `ck_catalogue_targets_isbn_claim` refuses
#: a waiver on any row but the DNB and `__post_init__` accepted one, so a
#: `Target` built in Python was admitting what the database refuses. That is the
#: shape a critic's round named: a plan and its sinks have to agree about which
#: of them checked.
#:
#: Why the DNB and only the DNB is on `Target.requires_isbn_claim`.
_MAY_WAIVE_THE_ISBN_CLAIM: Final = frozenset({CatalogueSource.DNB})

#: The PQF use attributes a row may name. One today, and a named set rather than
#: an `isinstance` check because the danger is a value that is an integer and is
#: not one of ours as much as one that is not an integer at all. See
#: `Target.isbn_attribute`.
#:
#: **`ck_catalogue_targets_use_attribute` is this set in SQL** and the two have
#: to be widened together: `backup.restore` writes through Core, so the Python
#: half of this rule runs on nothing a database returns.
_USE_ATTRIBUTES: Final = frozenset({z3950.USE_ISBN})

#: The most `Target.timeout_seconds` may be: the lower of the two transports'
#: ceilings on one request, so lowering either narrows every row with it.
#:
#: **`ck_catalogue_targets_timeout` is this figure in SQL**, as a literal, and
#: `test_targets.py` holds the two together: a restore writes through Core, so
#: the dataclass's half of the rule runs on nothing a database returns.
TIMEOUT_CEILING_SECONDS: Final = min(float(fetch.TIMEOUT_SECONDS), z3950.TIMEOUT_SECONDS)

#: A Z39.50 row's address, `z3950://host:port/database`, and nothing else.
#:
#: **A closed grammar rather than `urlsplit`**, because `urlsplit` accepts a
#: userinfo, a query, a missing port and an upper case host, and every one of
#: them is a second spelling of an address or a field the door would drop
#: without saying so. What it admits is what `z3950.Target` takes: a lower case
#: host name, a port spelled without a leading zero, and one database name.
#: Matched with `fullmatch`, for the reason `_INDEX` gives.
_Z3950_ADDRESS = re.compile(
    r"z3950://(?P<host>[a-z0-9.-]+):(?P<port>[1-9][0-9]{0,4})/(?P<database>[A-Za-z0-9_.-]+)"
)

#: The readers that can read what a Z39.50 record syntax arrives as, by syntax.
#:
#: **A syntax absent here is one no row may ask for**, which is how `OTHER` is
#: refused: the door hands a reader MARCXML (`metadata._z3950_root`), and only a
#: reader written for that can be named beside a syntax.
_Z3950_READERS: Final[Mapping[z3950.Syntax, frozenset[Reader]]] = MappingProxyType(
    {
        z3950.Syntax.MARC21: MARC_READERS,
        z3950.Syntax.UNIMARC: frozenset({Reader.UNIMARC}),
    }
)


class BadQuery(ValueError):
    """A value this module refuses to put in a catalogue query.

    Deliberately the same shape as `z3950.BadQuery`: ours, not the target's. A
    caller turns it into an unavailable answer rather than a 500.
    """


#: What an index name may be, and it is a name rather than an expression.
#:
#: Every index across the roster is one of `num`, `WOE`, `pica.isb`, `pica.all`,
#: `alma.isbn`, `alma.title`, `dc.isbn`, `dc.title`, `bib.anywhere`: an optional
#: context set, a dot, a name. Uppercase because the DNB's is `WOE`.
#:
#: **What it refuses is the whole point.** No `=`, no space, no quote, no
#: parenthesis, so a row cannot carry query structure into `isbn_query` even
#: before the value is appended. It is the whole of that defence, since an index
#: name is concatenated into the query unquoted, so its exactness is not
#: cosmetic.
#:
#: **Matched with `fullmatch`, and `$` is why.** `$` matches before a trailing
#: newline, so `_INDEX.match("alma.isbn\n")` is true and `fullmatch` is false.
#: Not exploitable, because httpx percent encodes the newline, and fixed anyway:
#: this is the ticket's stated substitution defence and a defence that admits one
#: character it says it refuses is a defence nobody can quote.
_INDEX = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_]+)?")

#: The characters that **join two things**: the relation characters, the
#: grouping parentheses, the quote that ends a phrase and the backslash that
#: escapes it. `a=b` is two things, so stripping one of these leaves a space.
_JOINS = '=<>"()/\\'

#: The characters that **mask inside one word**: CQL 1.2's `*` and `?`, and its
#: `^` anchor. Special inside a quoted phrase as well as outside one.
#:
#: **Deleted rather than spaced, and that is a measurement rather than a taste.**
#: A critic measured that spacing them turns `har*ry potter` into
#: `har AND ry AND potter`, three title words that find nothing, where the
#: catalogue would have masked it to "harry potter". Deleting gives `harry`,
#: which is what the member meant and what the target would have matched. The
#: earlier round of this had them missing from the class altogether, so the
#: masking reached the catalogue; this one keeps the refusal and fixes the strip.
_MASKS = "*?^"

#: Everything CQL reads as structure rather than as part of a term.
#:
#: **One repertoire, composed from the two halves rather than spelled a third
#: time.** `cql_term` refuses anything matching this; `metadata._search_terms`
#: strips, and needs the halves apart because they are stripped differently.
#: Spelling the union separately is how this had two classes one character
#: apart, which is the `_pqf_literal` defect the Czech National Library block
#: records shipping once already in the other query language.
CQL_STRUCTURE = re.compile(f"[{re.escape(_JOINS + _MASKS)}]+")

#: The half a typed query loses to a space. See `_JOINS`.
CQL_JOINS = re.compile(f"[{re.escape(_JOINS)}]+")

#: The half a typed query loses entirely. See `_MASKS`.
CQL_MASKS = re.compile(f"[{re.escape(_MASKS)}]+")

#: Whitespace and the control characters, which end a term rather than changing
#: the query's structure. Separate from `CQL_STRUCTURE` because
#: `metadata._search_terms` **splits** on whitespace where it **strips**
#: structure, so folding the two would delete the split's own delimiter.
_NOT_IN_A_TERM = re.compile(r"[\s\x00-\x1f\x7f]")


def cql_term(value: str) -> str:
    """One CQL term, refused rather than escaped.

    **Refusal and not escaping, and the difference is which mistake it makes.**
    Escaping would let a malformed value through as a term that finds nothing,
    silently.

    **What reaches here, stated as two cases rather than one.** From the lookup
    path, thirteen ASCII digits out of `isbn.parse_isbn`, and anything else there
    is a defect in this application. From the search path, one word of a member's
    typed query, where a refusal is an ordinary thing a person can type and
    `metadata._search_terms` drops the term rather than failing the search. An
    earlier version of this paragraph gave only the first case and concluded that
    anything refused was a bug, which a typed asterisk is not.

    Empty is refused: `num=` is a syntactically valid CQL query meaning something
    other than the one intended.
    """
    if not value or CQL_STRUCTURE.search(value) or _NOT_IN_A_TERM.search(value):
        raise BadQuery(f"not a CQL term: {value!r}")
    return value


def cql_phrase(terms: list[str]) -> str:
    """Several terms as one quoted CQL phrase.

    Each term goes through `cql_term` first, so the quote and the backslash that
    would end the phrase early are refused before the quotes are added rather
    than escaped inside them.
    """
    return '"' + " ".join(cql_term(term) for term in terms) + '"'


@dataclass(frozen=True)
class ShippedCredential:
    """A login a catalogue publishes about itself, carried in this source tree.

    **This is a credential in a published file, deliberately, and it is the one
    place in this application where that is not a defect.** Everything in
    `credentials.py` exists to keep a login out of a published place: the
    envelope is sealed, the key never travels in an archive, `Credential`
    refuses to render itself. A reader taking this type for an oversight and
    deleting the row that uses it is reversing the owner's decision of
    2026-09-07, which is in `docs/decisions.md` under "The catalogue that
    publishes its own login ships with it". That entry keeps the case against as
    well as the case for, so it is the thing to read before undoing this.

    **What makes it different is who published it.** A pair its issuing library
    prints on its own page, beside a contact address and with no stated
    restriction on use, is not a secret this project is keeping. Shipping it
    discloses nothing that library has not, and it saves every household an
    admin step on a screen most of them never open. A row carrying one names
    where the library published it.

    **It is the bottom of the ladder and it must stay there.**
    `credentials._resolve` walks pinned, stored, shipped, and the decision states
    replaceability as a requirement rather than a consequence: an institution
    with its own arrangement with the library has to be able to use that instead.

    **Both halves print, and that is the point rather than an oversight.**
    Suppressing them would be this file claiming a secrecy it contradicts three
    lines up. The rule that a login is never rendered belongs to
    `credentials.Credential`, which is what an outbound request actually carries
    and what a stored login becomes, and it is unchanged: a pair from here
    reaches a request through that type like any other.
    """

    username: str
    password: str

    def __post_init__(self) -> None:
        # One representation for the shipped pair, the sealed pair and the
        # pinned variable, so there is one rule to state. RFC 7617 forbids a
        # colon in the user-id, and `credentials.from_env` splits on the first
        # one, so a colon here would make the three spellings disagree about
        # where the username ends. Empty is refused for the reason
        # `credentials.put` refuses it: it authenticates as somebody with
        # nothing.
        if not self.username or not self.password:
            raise ValueError("a shipped login needs both a username and a password")
        if ":" in self.username:
            raise ValueError("a username may not contain a colon; RFC 7617 forbids one")


@dataclass(frozen=True)
class Target:
    """One catalogue, as a row.

    **Validated at construction, so a sink never has to re-check.** Every
    invariant that ties two fields together is enforced in `__post_init__`
    rather than at the call site that would trip over it: a transport that has
    no query grammar may carry no index, a reader that does not read MARC may
    carry no MARC knob, and a target that answers a lookup must say how to ask
    it one. That is the shape a critic's round on the enrichment bounds settled
    on, and the reason is that a plan and its sinks otherwise disagree about
    which of them checked.
    """

    #: Which source this is. The primary key, and closed: `sources.Plan.parse`
    #: validates a stored settings row against `CatalogueSource`, so the roster
    #: cannot grow here without growing there.
    #:
    #: **Or a `RegisteredCatalogue`**, for an entry of the curated registry this
    #: build ships, `registry.ENTRIES`. That set is closed too, and keyed apart so
    #: that no registry entry is in any household's roster until an admin picks
    #: it. `SEEDED` holds the first kind only.
    source: CatalogueSource | RegisteredCatalogue
    #: Position in `sources.DEFAULT_ORDER`, seeded from it.
    #:
    #: **Not read at runtime, and reserved for #130**, which is where a row
    #: becomes editable. The order a household actually gets is still the plan's,
    #: exactly as before. `test_targets.py` pins these against `DEFAULT_ORDER`,
    #: so the copy cannot drift while nothing reads it.
    rank: int
    transport: Transport
    #: Scheme, host, optional port and path. **The one field that decides where
    #: a request goes**, and the reason `fetch.ALLOWED_HOSTS` exists: a row is
    #: not a module constant, so the host it names is checked against a closed
    #: set held in code.
    #:
    #: **Changing this in a release invalidates every deployment's stored login
    #: for that source**, because a login is sealed against the origin it may be
    #: sent to and an origin that moved no longer matches. The affected admins
    #: enter theirs again, and nothing warns them first. Stated here rather than
    #: only at `credentials.put`, where the seal happens, because this is the
    #: line somebody edits and that one is not.
    #:
    #: **On a Z39.50 row it is `z3950://host:port/database`**, so the address is
    #: still one field, `origin` still reads it, and `_Z3950_ADDRESS` is the
    #: whole of what such a row may write here.
    base_url: str
    reader: Reader
    #: Whether this target answers an ISBN lookup, a title search, or both.
    #:
    #: **Not cosmetic.** The Czech National Library answers a lookup and not a
    #: search, because its server renders one populated record per response
    #: whatever page size is asked for: 391 of 400 records were empty across
    #: eight title searches at fifty records, measured 2026-08-31, and its ISBN
    #: lookup wants one record and gets one, 20 of 20. The Library of Congress
    #: and the BnF are the other way round: neither was worth an ISBN request.
    answers_lookup: bool
    answers_search: bool
    #: Costs money per request, so asking it about a book another source already
    #: answered is a bill for nothing. `sources.METERED` derives from this.
    metered: bool
    #: Needs a credential the household supplies. `sources.NEEDS_A_KEY` derives
    #: from this.
    needs_key: bool
    #: Which ISBN registration groups this library's collecting remit covers, as
    #: `978-960`. Empty where the catalogue is not asked to have one.
    #: `sources.SERVES_GROUPS` derives from this and `sources._serves` applies
    #: it, to the sources asked one at a time and never to the gathered tier.
    #:
    #: **A fact about the catalogue, so it is a column here rather than a table
    #: in `sources.py`.** What a library collects is the same kind of statement
    #: as what it charges for and what it wants a login for, which are the two
    #: fields above. It was a per source dict in `sources.py` until the owner's
    #: decision of 2026-09-07.
    #:
    #: **Required, with no default, and that is the whole of what the move
    #: buys.** The reason for the field is that every catalogue the breadth work
    #: adds arrives with this question, and a defaulted field asks a new row
    #: nothing: it answers "no remit" on the row's behalf. **What required buys
    #: is the deletion arm and not a recorded decision**, which is worth stating
    #: because the larger claim is the tempting one: typing `frozenset()`
    #: records nothing, and six of the empty rows carry exactly that and no
    #: comment. What it does buy is that the Argentine row's refusal cannot be
    #: tidied away, since deleting that line is a `TypeError` at import rather
    #: than a default silently taking over.
    #:
    #: **Too wide costs a round trip; too narrow loses a book and says
    #: nothing**, and that asymmetry is why the bar for a non empty value is
    #: zero rather than a threshold. `sources.SERVES_GROUPS` carries the rule,
    #: the measurement and which rows fail it.
    serves_groups: frozenset[str]
    #: The login this build ships for the target, where the library publishes
    #: one about itself. None everywhere else, which is every row but two.
    #:
    #: **On the row rather than in `credentials.py`, so the address is not a
    #: fact stored twice.** A shipped default has to be bound to the origin it
    #: was published for, and the row is that origin: `credentials.shipped` reads
    #: the pair back only for a `base_url` whose origin matches this row's, so a
    #: row pointed somewhere else loses the default rather than carrying it
    #: there. Written as a second constant it would be an address beside an
    #: address, kept equal by a guard that duplicates what it checks.
    #:
    #: **Below a stored login and below a pinned one, and that ordering is the
    #: whole of what makes shipping one safe.** `credentials._resolve` is the one
    #: walk, and `ShippedCredential` says why it may exist at all.
    shipped_credential: ShippedCredential | None = None
    #: Which deployment secret this row's own adapter is handed. See `Secret`.
    #:
    #: **A property of the source, never of the reader**, and the roster is what
    #: says so rather than a preference: `dublin_core_bare` serves the Czech
    #: National Library, which authenticates nothing, and the Argentine row,
    #: which needs a credential, so a reader is coarser than this question and
    #: on this roster it always will be. The reader keyed dispatch tables in
    #: `metadata.py` therefore carry no credential slot and this column is what
    #: they read instead.
    #:
    #: **Defaulted, unlike `serves_groups` above, and the asymmetry is
    #: deliberate.** Omission here answers `NONE`, and a row that needs a
    #: credential and answers `NONE` on a bespoke transport is refused by
    #: `metadata.resolve` at boot, because no bespoke door carries a sealed
    #: login. So the value a forgetful row gets is the one that fails loudly,
    #: where a defaulted remit would silently answer "no remit" and be believed.
    secret: Secret = Secret.NONE

    # ── SRU, and empty for every other transport ──────────────────────────────

    sru_version: str = ""
    #: The parameter the query travels in. `query` everywhere but the Czech
    #: National Library, which takes `x-pquery`. See `QueryLanguage`.
    query_parameter: str = ""
    query_language: QueryLanguage | None = None
    #: The `recordSchema` asked for, or empty where the target takes none. The
    #: NKP and the BNA take none: each response carries its own Dublin Core
    #: whatever is asked for.
    #:
    #: **Empty on a target that answers a lookup puts that target in
    #: `metadata._sru_refusal`'s path**, and that is worth knowing here because
    #: it is the field that decides it. The National Library of Greece answers
    #: the true hit count **and** `Unknown schema for retrieval` when no
    #: `recordSchema` is named, so this row's `marcxml` is what keeps an
    #: informational diagnostic out of a rule that reads a diagnostic as a
    #: refusal. Clearing it here, or adding a lookup target that names none,
    #: reinstates that: the symptom is the source reporting `UNAVAILABLE` on
    #: every miss, and no test can see it because it is a property of the live
    #: server. Measured 2026-09-07, all seven SRU lookup targets answer an
    #: honest empty result with no diagnostic at all.
    #:
    #: **On a Z39.50 row it is the record syntax asked for**, a `z3950.Syntax`
    #: value, and required: the protocol's own name for the same question. What
    #: a target labels its answer is read off each record rather than off this.
    record_schema: str = ""
    #: The character set a Z39.50 target's records arrive in, required there
    #: and None on every other transport. See `RecordCharset`.
    record_charset: RecordCharset | None = None
    #: The CQL index that means "the ISBN" at this target.
    #:
    #: **Established by probing, one target at a time**, and `metadata`'s per
    #: source blocks carry the probe tables. The one worth reading before
    #: editing any of these is the ÖNB's: an unknown index there is HTTP 200 with
    #: no diagnostic and the entire catalogue in catalogue order, so a typo ships
    #: plausible MARC for an unrelated book. `requires_isbn_claim` is what stands
    #: between that and a member's shelf.
    isbn_index: str = ""
    #: The PQF use attribute that means "the ISBN", for a PQF target.
    #:
    #: **Checked against a named set and not merely against `None`, because the
    #: column's declared type is not a constraint.** SQLite's INTEGER affinity is
    #: a preference: a critic measured `'7 @and @attr 1=4 anything'` storing in an
    #: INTEGER column with `typeof` **text**, at which point `z3950.query` renders
    #: `@attr 1=7 @and @attr 1=4 anything "978..."`, a two term `@and`. That is
    #: exactly the shape `z3950.pqf_term` exists to refuse, reached **around** it
    #: rather than through it, because the quoting guards the value and nothing
    #: guarded the attribute. `backup.py` documents the same affinity trap one
    #: column along, for `{"name": 1}`.
    #:
    #: So `Target.isbn_query` spells neither half of a PQF query, and that
    #: sentence is now true of the attribute as well as of the quoting.
    isbn_attribute: int | None = None
    title_index: str = ""
    title_query_shape: TitleQuery | None = None
    #: How many records one ISBN lookup asks for.
    #:
    #: Five at four targets, because several printings of one book each carry the
    #: ISBN somewhere and the fullest should win rather than whichever the
    #: catalogue sorted first. One at the NKP, for the reason `answers_lookup`
    #: gives.
    lookup_records: int = 0
    #: Whether a lookup that misses is asked once more, with the ISBN-10 form of
    #: the same book.
    #:
    #: **Some catalogues index a record only under the ISBN it states**, and a
    #: record catalogued before 2007 states the ten digit form, so the thirteen
    #: digit query misses a book the catalogue holds. **Data on the row, and the
    #: retry is `metadata._first_answer`'s**, which reads `isbn_forms` and
    #: nothing about the source: the query for each form is still built by
    #: `isbn_query`, and the reader still checks the record against the
    #: thirteen digit ISBN, which `marc_fields.Fields.claims_isbn` compares in
    #: canonical form.
    #:
    #: **A second search, on a miss only**, and only for a `978` ISBN, the one
    #: prefix with a ten digit form. On a Z39.50 row it shares the first
    #: search's association and deadline; on an SRU row it is a second request
    #: with `fetch`'s bounds. What each row that sets it found only this way is
    #: in `metadata`'s block for that row.
    retries_as_isbn10: bool = False
    #: A title search asks for `limit * search_multiplier`, capped at
    #: `search_cap`. More than asked for, because the ordering is the
    #: catalogue's and the ranking is ours.
    search_multiplier: int = 0
    search_cap: int = 0

    # ── Knobs the MARC readers take ───────────────────────────────────────────

    #: Refuse a record whose MARC leader/07 says it is a component part, an
    #: article or a chapter rather than a thing on a shelf.
    #:
    #: **True at the ÖNB on a measurement and at the NLG on the concept.** 155 of
    #: 280 live ÖNB records on 2026-08-27 were level `a`, 55.4%, and every one
    #: would have reached the picker as a book. The same measurement over 400 NLG
    #: records on 2026-08-30 found **zero**; it is set there anyway because an
    #: article is never a book in any MARC21 catalogue and reading one leader
    #: costs nothing.
    refuses_component_parts: bool = False
    #: Whether a record that does not name the asked ISBN in its own 020 is
    #: refused, or merely ranked below one that does.
    #:
    #: **True everywhere but the DNB, and that exception is measured rather than
    #: preferred.** The DNB's `num=` index matches cross references, so refusing
    #: outright turns a live lookup into a miss for a record that describes the
    #: right book; it ranks instead and takes the best.
    #:
    #: **Where the two arms actually differ, stated precisely because this is the
    #: column a later ticket flips.** Not "when no record claims the ISBN", which
    #: is the obvious reading and is wrong: a critic measured it false in 256 of
    #: 1,752 synthetic responses in which some record names the ISBN in its own
    #: 020. They differ **when no record that survives the reader claims it**, on
    #: which they agreed 712 of 712 over the same sweep. The gap between the two
    #: readings is this arm's whole subject: a record naming the scanned ISBN and
    #: refused by the reader, a disc extent or a volume slot title, beside a
    #: record that does not name it. The ranking arm answers with the second; the
    #: refusing arm reports a miss. Everywhere else this is
    #: the identity check, and at the ÖNB it is the whole defence against a
    #: mistyped index answering with the catalogue. Default True so a new row
    #: gets the safe answer by omission, and
    #: `_MAY_WAIVE_THE_ISBN_CLAIM` refuses it here for any other source, and
    #: `ck_catalogue_targets_isbn_claim` refuses it where a restore writes, so
    #: widening it costs an argument in three places.
    #:
    #: **Refused at construction where `reads_author_identifiers` below is only
    #: pinned by a test, and the two are different kinds of thing.** This one is
    #: a defence: at the ÖNB it is what stands between a mistyped index and an
    #: arbitrary record on a shelf. That one is a decision withheld pending a
    #: live comparison, so flipping it produces worse author identifiers rather
    #: than a wrong book, and a test that fails and asks for the argument is the
    #: right weight for it.
    requires_isbn_claim: bool = True
    #: Whether `100 $0` is read for a GND author identifier.
    #:
    #: **A decision withheld rather than a mapping gap**, at the ÖNB and at the
    #: NLG. The ÖNB's `$0` is if anything better than the DNB's: 158 of 209 live
    #: `100 $a` fields carry one, 75.6%, all `(DE-588)`, measured 2026-08-27. It
    #: stays off because a catalogue is not read for a person's identifier until
    #: somebody has compared it live, and comparing the numbers is not comparing
    #: the people they name.
    reads_author_identifiers: bool = False

    #: A bound for this target alone, in seconds, over one question asked of
    #: it: a lookup with its ISBN-10 retry, or one title search.
    #:
    #: **On a search, the fan out's deadline stays the ceiling**, and by
    #: construction rather than by a comparison: `metadata._search_one` applies
    #: this inside the wait its caller holds, so a bound longer than the time
    #: left is simply never reached. **A lookup holds no shared deadline**, so
    #: there this bound is the only one over the question beyond one request's
    #: own. None means no bound of its own, which is the behaviour every row
    #: had before the field was read.
    #:
    #: **A Z39.50 row's client waits one second less than its bound.** YAZ
    #: takes whole seconds and `z3950_yaz._options` truncates what is left,
    #: which keeps a missed association's thread inside the bound, so a bound
    #: of 3.0 opens YAZ with 2. A Z39.50 seed therefore carries one second
    #: more than its measurement asks for.
    #:
    #: **At most `TIMEOUT_CEILING_SECONDS`**, the lower of the two transports'
    #: ceilings on one request, refused at construction and by
    #: `ck_catalogue_targets_timeout`:
    #: `z3950.association` raises `ValueError` on a deadline further away than
    #: `z3950.TIMEOUT_SECONDS`, which would reach a member as a 500 rather than
    #: as this source being `UNAVAILABLE`, and a bound past
    #: `fetch.TIMEOUT_SECONDS` would widen an SRU row past the wait it had.
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        self._check_reader()
        self._check_transport()
        if self.reader not in MARC_READERS:
            self._check_no_marc_knobs()
        self._check_waivers()
        self._check_secret()
        self._check_retry()
        self._check_timeout()

    def _check_waivers(self) -> None:
        """Refuses a waived ISBN claim off the DNB, and a shipped login on a row needing none."""
        if not self.requires_isbn_claim and self.source not in _MAY_WAIVE_THE_ISBN_CLAIM:
            raise ValueError(f"{self.source}: only the DNB may waive the ISBN identity check")
        if self.shipped_credential is not None and not self.needs_key:
            # A default on a row that authenticates nothing is a credential
            # published for no reason, and it would put the source in
            # `credentials`' ladder while `sources.NEEDS_A_KEY` says the source
            # asks for nothing. Refused at construction rather than ignored,
            # which is the rule the bespoke fields above already follow.
            raise ValueError(f"{self.source}: a shipped login on a row that needs no credential")

    def _check_retry(self) -> None:
        """Refuses an ISBN-10 retry on a row whose lookup query this module does not build.

        A bespoke adapter builds its own request from the ISBN, so a retry
        there would ask the same question twice; a row answering no lookup has
        nothing to retry.
        """
        if self.retries_as_isbn10 and (not self.answers_lookup or self.transport is Transport.BESPOKE):
            raise ValueError(f"{self.source}: retries as an ISBN-10 a lookup this module builds no query for")

    def _check_timeout(self) -> None:
        """Refuses a bound that is not a positive number of seconds within one request's ceiling.

        `not 0 < value <= ceiling` rather than two comparisons the other way
        round, because NaN fails every comparison: written as `value <= 0 or
        value > ceiling` it passes both and reaches `asyncio.timeout`, which
        never fires on it.
        """
        if self.timeout_seconds is None:
            return
        if not 0 < self.timeout_seconds <= TIMEOUT_CEILING_SECONDS:
            raise ValueError(
                f"{self.source}: timeout_seconds must be over 0 and at most "
                f"{TIMEOUT_CEILING_SECONDS}, not {self.timeout_seconds!r}"
            )

    def _check_reader(self) -> None:
        """Refuses a reader that is not a `Reader`, and one of the import family."""
        if not isinstance(self.reader, Reader):
            # **A `StrEnum` member hashes as its own value, so a bare string is
            # a key of a reader table exactly where its member is, and is not
            # the member**, and this field is read
            # under both disciplines. Every site in this class and in `metadata.resolve`
            # asks membership, under which `"marc_plain"` is a MARC reader;
            # `metadata._marc_build` asks `is`, under which it is not, and picks
            # the other MARC reader. A row naming `"marc_plain"` would therefore
            # be parsed by `_dnb_record`, which harvests GND headings and
            # refuses volume slot titles, where the row asked for
            # `_k10plus_record`: a wrong reading of every record, reported as a
            # successful one. `main.seed_catalogue_targets` reads `.value` off
            # the same field and would raise instead.
            #
            # Refused by type at the one site that writes the field, so the
            # readers agree because the value cannot exist rather than because
            # six spellings are kept in step. **Ahead of the import family refusal and
            # the MARC knob check, which both read it, for the same reason the
            # secret's is ahead of its own**: a refusal that reads the value has
            # already trusted it.
            #
            # `Decoding.__post_init__` carries the same line, and needs its own:
            # the `is` site reads `Decoding.reader`, and a decoding built from a
            # file rather than from `Target.decoding` has passed no row.
            # `ValueError` and not `TypeError` on a type test: the reason is at
            # the matching refusal in `decoders.Decoding.__post_init__`.
            raise ValueError(f"{self.source}: {self.reader!r} is not a Reader")  # noqa: TRY004
        if self.reader in IMPORT_READERS:
            # **The registry refusing the other family's parser**, which is the
            # one rule `enums.SourceFamily` exists for and the one place a row
            # could break it. `metadata.resolve` catches only a row that also
            # declares a capability, so a row naming this reader and answering
            # nothing would otherwise construct and sit in the roster.
            raise ValueError(
                f"{self.source}: {self.reader} belongs to the import family, which no catalogue row may name"
            )

    def _check_secret(self) -> None:
        """Refuses a secret this row may not be handed, and a value that is not one."""
        if not isinstance(self.secret, Secret):
            # **A `StrEnum` member equals its own string, so the value has to be
            # refused here or three sites disagree about it.** This class and
            # `metadata.resolve` compare with `is`, under which a bare
            # `"google_books_key"` is not `GOOGLE_BOOKS_KEY`; `_lookup_one`
            # matches, and `match` compares with `==`, under which it is. So a
            # bare string would be read as naming a secret by the two refusals
            # below and routed to the keyed door by the dispatch, which is the
            # leak direction. Refused by type at the one site that writes the
            # field, so all three agree by the value being impossible rather
            # than by three spellings being kept in step.
            #
            # **The exposure this closes is the readback path.** A seeded row is
            # refused at boot by `metadata.resolve`, which `main` runs over the
            # roster; a `Target` built from column values is not, and that is
            # the path `main.seed_catalogue_targets` names as still open.
            # `ValueError` for the reason the reader refusal above gives.
            raise ValueError(f"{self.source}: {self.secret!r} is not a Secret")  # noqa: TRY004
        if self.secret is not Secret.NONE:
            # **The two halves of "this row may be handed that secret", refused
            # here so the dispatch never has to ask.** A row naming a secret and
            # needing no credential is claiming somebody else's key, which is
            # the leak `metadata._lookup_one`'s predicate used to admit; and the
            # SRU door hands its adapter nothing, since its login goes through
            # `fetch` bound to the origin it was sealed for, so a secret on an
            # SRU row is a value nothing would ever read.
            if not self.needs_key:
                raise ValueError(f"{self.source}: names {self.secret} on a row that needs no credential")
            if self.transport is Transport.SRU:
                raise ValueError(f"{self.source}: an SRU row's login is sealed, not an adapter argument")

    def _check_transport(self) -> None:
        """Refuses a transport that is not a `Transport`, then checks what its row must carry."""
        if not isinstance(self.transport, Transport):
            # A bare `"sru"` would match the `case` below by equality, and is
            # refused for the reason the reader's refusal gives.
            raise ValueError(f"{self.source}: {self.transport!r} is not a Transport")  # noqa: TRY004
        self._check_charset_is_z3950s()
        match self.transport:
            case Transport.SRU:
                self._check_sru()
            case Transport.Z3950:
                self._check_z3950()
            case Transport.BESPOKE:
                self._check_no_sru()
            case _:
                assert_never(self.transport)

    def _check_charset_is_z3950s(self) -> None:
        """Refuses a record charset on any row but a Z39.50 one, which `_check_z3950` requires."""
        if self.transport is not Transport.Z3950 and self.record_charset is not None:
            raise ValueError(f"{self.source}: only a Z39.50 row names its records' character set")

    def _check_z3950(self) -> None:
        """Refuses a Z39.50 row missing what the door needs, or carrying what it cannot use.

        **What it must carry**: an address in `_Z3950_ADDRESS`'s grammar, a
        record syntax a reader on the row can read, the character set its
        records arrive in, PQF, and a use attribute where it answers a lookup.
        **What it may not**: any CQL field, and a credential, because
        `z3950.Client.open` takes none and a login on this row would be
        dropped at the door with the request going out unauthenticated, which
        is the failure `metadata.carries_a_credential` exists to make visible.
        """
        address = _Z3950_ADDRESS.fullmatch(self.base_url)
        if address is None or not 0 < int(address["port"]) < 65536:
            raise ValueError(f"{self.source}: not a z3950://host:port/database address: {self.base_url!r}")
        syntax = next((each for each in _Z3950_READERS if each.value == self.record_schema), None)
        if syntax is None or self.reader not in _Z3950_READERS[syntax]:
            raise ValueError(f"{self.source}: {self.reader} cannot read record syntax {self.record_schema!r}")
        if not isinstance(self.record_charset, RecordCharset):
            raise ValueError(f"{self.source}: a Z39.50 row names its records' character set")  # noqa: TRY004
        self._check_z3950_fields()
        self._check_z3950_records()

    def _check_z3950_fields(self) -> None:
        """Refuses a Z39.50 row naming CQL, a title shape or a credential."""
        if self.query_language is not QueryLanguage.PQF:
            raise ValueError(f"{self.source}: a Z39.50 target is asked in PQF")
        if any((self.sru_version, self.query_parameter, self.isbn_index, self.title_index)):
            raise ValueError(f"{self.source}: a Z39.50 target carries no SRU fields")
        if self.title_query_shape is not None:
            raise ValueError(f"{self.source}: a Z39.50 title query has one shape, the seam's")
        if self.needs_key:
            raise ValueError(f"{self.source}: the Z39.50 door carries no credential")

    def _check_z3950_records(self) -> None:
        """Refuses a Z39.50 row asking for no records, or more than `z3950.search` takes.

        **Refused here because the seam raises `ValueError` past
        `z3950.MAX_RECORDS`**, which no door handler catches, so a row asking
        for six would be a 500 on the first scan rather than a boot failure.
        """
        if self.answers_lookup:
            if not 0 < self.lookup_records <= z3950.MAX_RECORDS:
                raise ValueError(f"{self.source}: a Z39.50 lookup asks for 1 to {z3950.MAX_RECORDS} records")
            self._check_use_attribute()
        asks_for_none = self.search_multiplier < 1 or not 0 < self.search_cap <= z3950.MAX_RECORDS
        if self.answers_search and asks_for_none:
            raise ValueError(f"{self.source}: a Z39.50 search asks for 1 to {z3950.MAX_RECORDS} records")

    def _check_use_attribute(self) -> None:
        """Refuses a PQF use attribute this module does not name."""
        if type(self.isbn_attribute) is not int or self.isbn_attribute not in _USE_ATTRIBUTES:
            # **`type(...) is not int` and not `isinstance`, and not
            # membership alone.** `7.0 in {7}` is True, because a float
            # compares equal to an integer, so membership admitted a value
            # `z3950.query` then refuses at request time with `BadQuery`.
            # That is the same rule enforced in two places and disagreeing:
            # one arm built a row the other would not send.
            raise ValueError(f"{self.source}: not a PQF use attribute: {self.isbn_attribute!r}")

    def _check_sru(self) -> None:
        if not self.sru_version or not self.query_parameter:
            raise ValueError(f"{self.source}: an SRU target needs a version and a parameter")
        # **The query goes in a dict beside four fixed keys**, so a parameter
        # named like one of them replaces it and no query is sent at all. A
        # critic measured `query_parameter="version"` constructing cleanly and
        # `sru_params` returning a request whose SRU version was the CQL query.
        if self.query_parameter.lower() in _RESERVED_SRU_PARAMETERS:
            raise ValueError(f"{self.source}: {self.query_parameter!r} is an SRU parameter already")
        if self.query_language is None:
            raise ValueError(f"{self.source}: an SRU target needs a query language")
        if self.answers_lookup:
            self._check_sru_lookup()
        if self.answers_search:
            self._check_sru_search()

    def _check_sru_lookup(self) -> None:
        """Refuses an SRU lookup that asks for nothing or names no usable ISBN index."""
        if self.lookup_records < 1:
            raise ValueError(f"{self.source}: answers a lookup and asks for no records")
        if self.query_language is QueryLanguage.CQL:
            if not _INDEX.fullmatch(self.isbn_index):
                raise ValueError(f"{self.source}: not an index name: {self.isbn_index!r}")
        else:
            self._check_use_attribute()

    def _check_sru_search(self) -> None:
        """Refuses an SRU search a CQL title query could not be built for."""
        if self.query_language is not QueryLanguage.CQL:
            raise ValueError(f"{self.source}: only a CQL target can answer a search")
        if not _INDEX.fullmatch(self.title_index):
            raise ValueError(f"{self.source}: not an index name: {self.title_index!r}")
        if self.title_query_shape is None:
            raise ValueError(f"{self.source}: answers a search and names no query shape")
        if self.search_multiplier < 1 or self.search_cap < 1:
            raise ValueError(f"{self.source}: answers a search and asks for no records")

    def _check_no_sru(self) -> None:
        """A bespoke target carries no query grammar, because it has none.

        Enforced rather than ignored: an index name sitting unused on a row is a
        row somebody later reads as the one being asked.
        """
        empty = (
            self.sru_version,
            self.query_parameter,
            self.record_schema,
            self.isbn_index,
            self.title_index,
        )
        if any(empty) or self.query_language is not None:
            raise ValueError(f"{self.source}: a bespoke target carries no SRU fields")
        if self.isbn_attribute is not None or self.title_query_shape is not None:
            raise ValueError(f"{self.source}: a bespoke target carries no query shape")

    def _check_no_marc_knobs(self) -> None:
        if self.refuses_component_parts or self.reads_author_identifiers:
            raise ValueError(f"{self.source}: a MARC21 knob on a reader that is not a MARC21 reader")

    @property
    def capabilities(self) -> frozenset[Capability]:
        """What this source can be asked for, as one statement.

        **The single reading surface on the asking side**, which is what this
        buys and is less than it first appears. `sources.py` and
        `metadata.resolve` ask `can`; the columns are read here, by
        `main.seed_catalogue_targets` writing the table, and by the tests that
        pin the storage against that table and against the roster.

        **What a fifth capability still costs, stated because the tidier
        sentence was measured false.** An enum member, an arm here, a `bool`
        field, a value on every seeded row, a column on `models.CatalogueTarget`
        and a line in the seeder. What it no longer costs is a module constant
        in `sources.py` and a second spelling at every call site, which is the
        part `enums.Capability` removes.

        **The declaration is still four columns and this is a projection over
        them**, deliberately: making it the stored field changes this class's
        keyword surface, which the seam ticket's scope refuses. The argument for
        taking it later, and what it would cost, is in `docs/decisions.md`.
        """
        declared = {
            Capability.ANSWERS_ISBN: self.answers_lookup,
            Capability.ANSWERS_TITLE_SEARCH: self.answers_search,
            Capability.METERED: self.metered,
            Capability.NEEDS_A_CREDENTIAL: self.needs_key,
        }
        return frozenset(name for name, held in declared.items() if held)

    def can(self, capability: Capability) -> bool:
        """Whether this source can be asked for that."""
        return capability in self.capabilities

    @property
    def decoding(self) -> Decoding:
        """What a decoder is told about this source, and it is never how to reach it.

        **The only place in the application that builds a `Decoding` from a
        catalogue row**, which is what keeps the projection one sided: a decoder
        cannot reach back for an address it was never given. Everything omitted
        here is omitted on purpose, and `decoders.Decoding` says which and why.
        """
        return Decoding(
            source=self.source.value,
            reader=self.reader,
            refuses_component_parts=self.refuses_component_parts,
            requires_isbn_claim=self.requires_isbn_claim,
            reads_author_identifiers=self.reads_author_identifiers,
        )

    def isbn_query(self, value: str) -> str:
        """The query that asks this target about one ISBN.

        **Neither half of a PQF query is spelled here.** The attribute is the
        row's and the quoting is `z3950.pqf_term`'s, which is the rule the
        ticket's own comment asks the guard to be written against: an `@`
        followed by a digit is read before a quoted run and repins the use
        attribute, and a trailing backslash escapes the closing quote. A local
        rule that removed the double quote and stopped there has already shipped
        once here and was wrong.
        """
        if self.query_language is QueryLanguage.PQF:
            assert self.isbn_attribute is not None  # noqa: S101  narrowing, not validation; __post_init__
            return z3950.query(self.isbn_attribute, value)
        return f"{self.isbn_index}={cql_term(value)}"

    def isbn_forms(self, isbn: str) -> tuple[str, ...]:
        """The forms of one ISBN this target is asked about, in the order asked.

        The thirteen digit form, then the ten digit one where the row retries
        and the ISBN has one. See `retries_as_isbn10`.
        """
        ten = isbn13_to_isbn10(isbn) if self.retries_as_isbn10 else None
        return (isbn,) if ten is None else (isbn, ten)

    def title_query(self, terms: list[str]) -> str:
        """The query that asks this target about a list of title terms.

        **A PQF target has one shape, the seam's**: the terms as one phrase on
        BIB-1's title attribute, quoted by `z3950.pqf_term`. How a catalogue
        matches that phrase is its own, as it is for a CQL `all`.
        """
        if self.query_language is QueryLanguage.PQF:
            return z3950.title_query(" ".join(terms))
        shape = self.title_query_shape
        if shape is TitleQuery.ANDED_TERMS:
            return " and ".join(f"{self.title_index}={cql_term(term)}" for term in terms)
        if shape is TitleQuery.WORD_SEQUENCE:
            return f"{self.title_index}={' '.join(cql_term(term) for term in terms)}"
        if shape is TitleQuery.QUOTED_PHRASE:
            return f"{self.title_index}={cql_phrase(terms)}"
        if shape is TitleQuery.QUOTED_ALL:
            return f"{self.title_index} all {cql_phrase(terms)}"
        raise BadQuery(f"{self.source}: no title query shape")

    def sru_params(self, query: str, records: int) -> dict[str, str]:
        """The SRU parameters for one request, query included.

        One builder for both paths, so a target's version and query parameter
        cannot be right on the lookup and stale on the search, which is exactly
        how `targets.SEEDED[CatalogueSource.NKP].query_parameter` would have been missed on a second path.
        """
        params = {
            "version": self.sru_version,
            "operation": "searchRetrieve",
            self.query_parameter: query,
            "maximumRecords": str(records),
        }
        if self.record_schema:
            params["recordSchema"] = self.record_schema
        return params

    def search_records(self, limit: int) -> int:
        return min(limit * self.search_multiplier, self.search_cap)

    @property
    def z3950_target(self) -> z3950.Target:
        """Where the Z39.50 door connects, the syntax it asks for, and the charset it converts from.

        Read off the address `_check_z3950` already refused anything else in, so
        only a Z39.50 row may ask; any other row is a `ValueError`.
        """
        address = _Z3950_ADDRESS.fullmatch(self.base_url)
        if self.transport is not Transport.Z3950 or address is None or self.record_charset is None:
            raise ValueError(f"{self.source}: not a Z39.50 row")
        return z3950.Target(
            host=address["host"],
            port=int(address["port"]),
            database=address["database"],
            syntax=z3950.Syntax(self.record_schema),
            charset=self.record_charset,
        )


#: Which family `SEEDED` is the registry for.
#:
#: Named rather than left implicit so a guard has a line to read:
#: `tests/test_decoders.py::TestTwoFamiliesMeanTwoRegistries`. The consequence
#: is on `enums.SourceFamily`.
FAMILY: Final = SourceFamily.CATALOGUE

#: The twenty one catalogues this application ships knowing about.
#:
#: **This is what the runtime asks, and the table is what it seeds.** The
#: migrations write every one of these rows into `catalogue_targets` and
#: `main.seed_catalogue_targets` reconciles them on every start, and **nothing
#: reads that table back**, deliberately, because #127's decision D2 sends a
#: member supplied host to #131 and an address read off a row is that decision.
#: #130 makes a row editable and is the first reader.
#:
#: **The eleventh row has no revision yet**, so a deployment's boot seeds one
#: that a migrated database does not have.
#: `tests/test_schema.py::TestTheSeededCatalogueTargetsMatchTheCode` is what
#: says so, and it stays red until one is written.
#:
#: So a fresh install behaves exactly as the release before this one did, which
#: is the only property this had to have, and it holds by construction rather
#: than by comparison: it is the same constant the old per source adapters read,
#: rearranged.
#:
#: **`rank` is `sources.DEFAULT_ORDER`'s position**, copied here so #130 has
#: something to reorder, and pinned against it by `test_targets.py` so the copy
#: cannot drift while nothing reads it.
#:
#: The measurement behind every address, index and record count is in
#: `metadata.py`'s per source block for that source. It is not repeated here: a
#: figure written twice is a figure that stops being re-derived.
#: The roster, read only, and the immutability is load bearing rather than tidy.
#:
#: **`credentials._may_open_unbound` compares an address against this one**, so
#: an envelope from the scheme before addresses were bound opens exactly where
#: this says its source lives. Both sides of that comparison read this mapping,
#: so a write here moves the baseline and the envelope opens wherever the write
#: said. Measured 2026-09-07 by both critic seats independently and reproduced:
#: a single `SEEDED[DNB] = replace(row, base_url=...)` opened a superseded
#: envelope at that address.
#:
#: **The literal is inline and there is no private alias**, which is the second
#: half of the same finding. `Final` stops a rebinding and stops nothing else,
#: `Target` is frozen so a field cannot be set, and a proxy guards the view and
#: not the dict, so a name bound to that dict is the same hole one indirection
#: along: `SLF` is not in this project's ruff selection, so `targets._SEEDED[k]`
#: would have passed every check in the gate. Reproduced before removing it.
#:
#: **The bound, because immutability is claimed for this**: a proxy is not a
#: security boundary. `gc.get_referents` on it yields the wrapped dict and that
#: dict is writable. What this buys is that every write **through a name** is
#: refused, at runtime and under mypy, so no ordinary line reaches it.
#:
#: **This is what makes the ticket that edits a catalogue row a code change.**
#: Serving the roster from the table takes one of two shapes and they are
#: refused by different things: replacing this object from another module is a
#: rebinding, which `Final` refuses; changing the initialiser here is not, and
#: what refuses that is `test_credentials.py` holding this module to importing
#: nothing that can reach a database. Either way it is the point at which the
#: superseded scheme must stop being opened at all.
SEEDED: Final[Mapping[CatalogueSource, Target]] = MappingProxyType(
    {
        CatalogueSource.DNB: Target(
            source=CatalogueSource.DNB,
            rank=0,
            transport=Transport.SRU,
            base_url="https://services.dnb.de/sru/dnb",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            answers_search=True,
            metered=False,
            needs_key=False,
            serves_groups=frozenset(),
            sru_version="1.1",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="MARC21-xml",
            isbn_index="num",
            title_index="WOE",
            title_query_shape=TitleQuery.WORD_SEQUENCE,
            lookup_records=5,
            search_multiplier=3,
            search_cap=50,
            # `num=` matches a cross reference, so a record that does not name the
            # ISBN in its own 020 is ranked below one that does rather than refused.
            # The only row in the roster that waives it. See `requires_isbn_claim`.
            requires_isbn_claim=False,
            reads_author_identifiers=True,
        ),
        CatalogueSource.K10PLUS: Target(
            source=CatalogueSource.K10PLUS,
            rank=1,
            transport=Transport.SRU,
            timeout_seconds=6.0,
            base_url="https://sru.k10plus.de/opac-de-627",
            reader=Reader.MARC_PLAIN,
            answers_lookup=True,
            answers_search=True,
            metered=False,
            needs_key=False,
            serves_groups=frozenset(),
            sru_version="1.1",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="pica.isb",
            title_index="pica.all",
            title_query_shape=TitleQuery.ANDED_TERMS,
            lookup_records=5,
            search_multiplier=3,
            search_cap=50,
        ),
        CatalogueSource.OPEN_LIBRARY: Target(
            source=CatalogueSource.OPEN_LIBRARY,
            rank=9,
            transport=Transport.BESPOKE,
            base_url="https://openlibrary.org",
            reader=Reader.OPEN_LIBRARY,
            answers_lookup=True,
            answers_search=True,
            metered=False,
            needs_key=False,
            serves_groups=frozenset(),
        ),
        CatalogueSource.NKP: Target(
            source=CatalogueSource.NKP,
            rank=11,
            transport=Transport.SRU,
            timeout_seconds=3.0,
            # The database path is load bearing: `aleph.nkp.cz:9991` alone, and
            # `/biblios`, both answer SRU diagnostic 1/235, "database does not
            # exist". Measured 2026-08-31.
            base_url="http://aleph.nkp.cz:9991/NKC",
            reader=Reader.DUBLIN_CORE_BARE,
            answers_lookup=True,
            # One populated record per response whatever page size is asked for, so
            # ten candidates would be ten sequential requests inside a shared 4.0s
            # deadline. See `answers_search`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # Empty, and measured rather than assumed: it answers 59 and holds 2
            # outside `978-80` that nothing else **in the sample** does, so it
            # fails the zero book bar in `sources.SERVES_GROUPS` by two books.
            # The sample is eight columns of a twelve row roster, so that is the
            # scope of the claim; one of the two is Argentine and the catalogue
            # most likely to hold it has no column here.
            serves_groups=frozenset(),
            sru_version="1.1",
            query_parameter="x-pquery",
            query_language=QueryLanguage.PQF,
            # No `recordSchema`: this target answers with its own Dublin Core
            # whatever is asked for.
            record_schema="",
            isbn_attribute=z3950.USE_ISBN,
            lookup_records=1,
        ),
        CatalogueSource.BNE: Target(
            source=CatalogueSource.BNE,
            rank=12,
            transport=Transport.SRU,
            timeout_seconds=7.0,
            # **The OPAC hostname, and that is the whole finding.** This library was
            # recorded as having no open interface, measured against
            # `z3950.bne.es`, which authenticates and answers every database name
            # with the identical access control failure. `catalogo.bne.es` is Alma
            # fronted: `/sru` answers an Ex Libris error report and Alma's own SRU
            # path answers a 186,457 byte explain. Measured 2026-09-05.
            base_url="https://catalogo.bne.es/view/sru/34BNE_INST",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # **Its search works and nobody has measured what it would find**,
            # which are two different facts and only the second decides this. 30
            # records answers in 1.117s median over 15 samples; 50 records costs
            # 2.448 to 5.911s against a 4.0s whole fan out. No incumbent search
            # source has that measurement either, so this is a conservative default
            # for a new source rather than a bar the others passed. The full
            # argument is on `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # Empty, and measured: 4 of the 18 books it alone answers fall outside
            # `978-84`, one Portuguese, one Argentine and two Uruguayan. `metadata`'s
            # block for this row carries the pass.
            serves_groups=frozenset(),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="alma.isbn",
            lookup_records=5,
            # 15 of 400 live records on 2026-09-05 are leader/07 `a`, 3.8%. Lower
            # than the OENB's 55.4% and higher than the NLG's zero, and refused for
            # the reason that covers all three: an article is never a book.
            refuses_component_parts=True,
        ),
        CatalogueSource.NLG: Target(
            source=CatalogueSource.NLG,
            rank=2,
            transport=Transport.SRU,
            timeout_seconds=3.0,
            # Plaintext by necessity: port 210 speaks no TLS, and
            # `https://catalogue.nlg.gr` on 443 is a different service that answers
            # 404 to this path. Both measured 2026-08-30. `metadata`'s NLG block
            # carries what that exposes and what stands in front of it.
            base_url="http://catalogue.nlg.gr:210/biblios",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            answers_search=True,
            metered=False,
            needs_key=False,
            # Greek publishing, both groups, and it answers nothing at all
            # outside the two. Naming only `978-960` would cost seven of its 37
            # sampled answers, in silence.
            serves_groups=frozenset({"978-960", "978-618"}),
            sru_version="1.1",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="dc.isbn",
            title_index="dc.title",
            title_query_shape=TitleQuery.ANDED_TERMS,
            lookup_records=5,
            search_multiplier=3,
            # This endpoint does not clamp `maximumRecords`, so this is the only
            # bound there is: asking for 200 returns 200, measured 2026-08-30, where
            # the OENB silently caps at 50.
            search_cap=50,
            refuses_component_parts=True,
        ),
        CatalogueSource.LIBRIS: Target(
            source=CatalogueSource.LIBRIS,
            rank=13,
            transport=Transport.SRU,
            timeout_seconds=3.0,
            # SRU on LIBRIS's own server, so Sweden needs no Z39.50 client. The
            # same records answer Z39.50 on port 210 of this host.
            base_url="https://libris.kb.se/sru/libris",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason: nobody has measured what a search here would
            # find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # **Empty, and measured**: it alone answers one book of the 500, and
            # that book is Italian, so a `978-91` remit would stop it being asked
            # about the one book only it holds. A union catalogue holds foreign
            # editions, which is the whole of why it answers 70 of the 500.
            serves_groups=frozenset(),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="bath.isbn",
            # The server caps `maximumRecords` at 10, so five is inside it.
            lookup_records=5,
            # 0 of 119 live records on 2026-11-16 were leader/07 `a`. Refused
            # for the BNE's reason: an article is never a book.
            refuses_component_parts=True,
        ),
        CatalogueSource.MELINDA: Target(
            source=CatalogueSource.MELINDA,
            rank=14,
            transport=Transport.SRU,
            timeout_seconds=3.0,
            # SRU on Melinda's own server, the National Library of Finland's
            # public API host. Measured 2026-11-16.
            base_url="https://sru.api.melinda.kansalliskirjasto.fi/bib",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason: nobody has measured what a search here would
            # find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # **Empty, and measured**: it alone answers one book of the 500,
            # `9789605032708`, which is Greek, so a `978-951` and `978-952`
            # remit would stop it being asked about the one book only it holds.
            serves_groups=frozenset(),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="bath.isbn",
            lookup_records=5,
            # 0 of 115 live records on 2026-11-16 were leader/07 `a`. Refused
            # for the BNE's reason: an article is never a book.
            refuses_component_parts=True,
        ),
        CatalogueSource.BIBSYS: Target(
            source=CatalogueSource.BIBSYS,
            rank=15,
            transport=Transport.SRU,
            timeout_seconds=3.0,
            # Alma's SRU path on the network zone's own host, where the
            # Norwegian libraries' shared records live. The National Library of
            # Norway's institution view, `47BIBSYS_NB`, finds the same books more
            # slowly. Measured 2026-11-16.
            base_url="https://bibsys.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason: nobody has measured what a search here would
            # find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # **Empty**: a union catalogue holds foreign editions, 48 of the
            # 500 in seven frames. `sources.SERVES_GROUPS` carries the bar.
            serves_groups=frozenset(),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="alma.isbn",
            lookup_records=5,
            # 1 of 182 live records on 2026-11-16 was leader/07 `a`, and none of
            # the books found was one. Refused for the BNE's reason.
            refuses_component_parts=True,
        ),
        CatalogueSource.SBN: Target(
            source=CatalogueSource.SBN,
            rank=5,
            transport=Transport.Z3950,
            # The ICCU's public Z39.50 server for the national union catalogue.
            # It keeps UNIMARC and renders a MARC21 view of the same record when
            # asked for `usmarc`, which is what this row asks.
            base_url="z3950://opac.sbn.it:2100/nopac",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason: nobody has measured what a search here would
            # find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            serves_groups=frozenset({"978-88"}),
            query_language=QueryLanguage.PQF,
            record_schema=z3950.Syntax.MARC21.value,
            # The MARC21 view is UTF-8 and says so in leader/09. `metadata`'s
            # block for this row carries the measurement.
            record_charset=RecordCharset.UTF8,
            isbn_attribute=z3950.USE_ISBN,
            lookup_records=5,
            retries_as_isbn10=True,
            refuses_component_parts=True,
        ),
        CatalogueSource.PORBASE: Target(
            source=CatalogueSource.PORBASE,
            rank=6,
            transport=Transport.Z3950,
            timeout_seconds=5.0,
            base_url="z3950://z3950.catalogo.bnportugal.gov.pt:210/bn",
            reader=Reader.UNIMARC,
            answers_lookup=True,
            # The BNE's reason, and a second one: at about 0.7s a search here
            # would spend most of the 4.0s fan out on one catalogue.
            answers_search=False,
            metered=False,
            needs_key=False,
            serves_groups=frozenset({"978-972", "978-989"}),
            query_language=QueryLanguage.PQF,
            record_schema=z3950.Syntax.UNIMARC.value,
            # Declared as `0103` in `100 $a/26-29` on every record sampled.
            record_charset=RecordCharset.ISO5426,
            isbn_attribute=z3950.USE_ISBN,
            # **One, where every other lookup row asks for five**, because each
            # further record is a Present of its own at about 0.7s and the hits
            # past the first were copies of it. `metadata`'s block for this row
            # carries the measurement.
            lookup_records=1,
            retries_as_isbn10=True,
        ),
        CatalogueSource.OSZK: Target(
            source=CatalogueSource.OSZK,
            rank=7,
            transport=Transport.Z3950,
            timeout_seconds=4.0,
            base_url="z3950://amicus.oszk.hu:1616/ANY",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason: nobody has measured what a search here would
            # find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            serves_groups=frozenset({"978-963", "978-615"}),
            query_language=QueryLanguage.PQF,
            record_schema=z3950.Syntax.MARC21.value,
            # UTF-8 and declared in leader/09, measured with the SBN's.
            record_charset=RecordCharset.UTF8,
            isbn_attribute=z3950.USE_ISBN,
            lookup_records=5,
            retries_as_isbn10=True,
            refuses_component_parts=True,
        ),
        CatalogueSource.SNK: Target(
            source=CatalogueSource.SNK,
            rank=8,
            transport=Transport.Z3950,
            # The national library's Metaproxy in front of its Virtua catalogue.
            # The database is `Default`; the national bibliography's records
            # carry its local fields 919, 949 and 972, which no reader here reads.
            base_url="z3950://z3950.snk.sk:1111/Default",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason: nobody has measured what a search here would
            # find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # **`978-80`, which Czech and Slovak publishers share**, and which
            # the NKP, carrying no remit, is asked about too. `metadata`'s block
            # for this row carries the bar.
            serves_groups=frozenset({"978-80"}),
            query_language=QueryLanguage.PQF,
            record_schema=z3950.Syntax.MARC21.value,
            # UTF-8 and declared in leader/09. `metadata`'s block for this row
            # carries the measurement.
            record_charset=RecordCharset.UTF8,
            isbn_attribute=z3950.USE_ISBN,
            lookup_records=5,
            # No ISBN-10 retry: the index matches the ten digit form too, so
            # a second search would ask the same thing. `metadata`'s block for
            # this row measures it.
            refuses_component_parts=True,
        ),
        CatalogueSource.KB_DK: Target(
            source=CatalogueSource.KB_DK,
            rank=4,
            transport=Transport.SRU,
            timeout_seconds=3.0,
            # Alma's SRU path at the `eu01` data centre, the Royal Danish
            # Library's own institution zone. Measured 2026-11-16.
            base_url="https://eu01.alma.exlibrisgroup.com/view/sru/45KBDK_KGL",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason: nobody has measured what a search here would
            # find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # **Danish publishing, and the bar is met on the committed sample.**
            # Of the 35 of the 500 it answers, every one outside `978-87` is held
            # by a source the remit leaves asked: the one book no older source
            # holds, `9786557145029`, Brazilian, BIBSYS holds, which is why
            # BIBSYS carries no remit. `metadata`'s block for this row carries
            # the pass.
            serves_groups=frozenset({"978-87"}),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="alma.isbn",
            lookup_records=5,
            # 0 of 134 live records on 2026-11-16 were leader/07 `a`. Refused
            # for the BNE's reason: an article is never a book.
            refuses_component_parts=True,
        ),
        CatalogueSource.BN_PL: Target(
            source=CatalogueSource.BN_PL,
            rank=3,
            transport=Transport.SRU,
            timeout_seconds=3.0,
            # The `bn-nl` host and Alma's SRU path. `eu.alma.exlibrisgroup.com`,
            # the address a public Z39.50 registry lists, answers access control
            # failure 101; `bn-nl` answers both doors. Measured 2026-11-16.
            base_url="https://bn-nl.alma.exlibrisgroup.com/view/sru/48OMNIS_NLOP",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            # The BNE's reason, not the NKP's: nobody has measured what a search
            # here would find that the roster does not. See `sources.SEARCH_SOURCES`.
            answers_search=False,
            metered=False,
            needs_key=False,
            # **Polish publishing, and the bar is met on the committed sample
            # rather than on a hope.** All 500 were put to it: it answers 9, all
            # outside `978-83`, and every one of the 9 is held by another source
            # in the chain, so the remit loses no book. `metadata`'s block for
            # this row carries the pass.
            serves_groups=frozenset({"978-83"}),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="alma.isbn",
            lookup_records=5,
            # 0 of 57 live records on 2026-11-16 were leader/07 `a`. Refused for
            # the BNE's reason: an article is never a book, and reading one
            # leader costs nothing.
            refuses_component_parts=True,
        ),
        CatalogueSource.OENB: Target(
            source=CatalogueSource.OENB,
            rank=10,
            transport=Transport.SRU,
            timeout_seconds=5.0,
            base_url="https://obv-at-oenb.alma.exlibrisgroup.com/view/sru/43ACC_ONB",
            reader=Reader.MARC_GND,
            answers_lookup=True,
            answers_search=True,
            metered=False,
            needs_key=False,
            # `978-3` is German language publishing rather than Austria, so this
            # is wider than the country and is the group the catalogue actually
            # collects in. Five of its 55 sampled answers fall outside it, and
            # the leading pair holds every one of the five.
            serves_groups=frozenset({"978-3"}),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="marcxml",
            isbn_index="alma.isbn",
            title_index="alma.title",
            title_query_shape=TitleQuery.ANDED_TERMS,
            lookup_records=5,
            search_multiplier=3,
            search_cap=50,
            refuses_component_parts=True,
        ),
        CatalogueSource.BNA: Target(
            source=CatalogueSource.BNA,
            rank=16,
            transport=Transport.SRU,
            # **Plaintext by necessity and an IP address by necessity**, which are
            # two separate compromises: port 9991 speaks no TLS, and the library
            # publishes a bare address with no hostname behind it. `metadata`'s
            # block carries what a plaintext catalogue connection exposes; what is
            # different here is that the request carries an `Authorization` header,
            # so `credentials.Credential.header_for` binding the login to this
            # origin is load bearing rather than defence in depth.
            base_url="http://200.123.191.9:9991/BNA01",
            reader=Reader.DUBLIN_CORE_BARE,
            answers_lookup=True,
            # One populated record per response whatever page size is asked for, the
            # Czech National Library's property measured at this target too: an ISBN
            # with two hits answers two `<zs:record>` elements and **one**
            # `recordData`, at `maximumRecords=5`. Measured 2026-09-07.
            answers_search=False,
            # **Free and credentialled, which nothing here was before.** It costs
            # nothing per request and answers nothing to a request that does not
            # authenticate. See `sources.NEEDS_A_KEY`.
            metered=False,
            needs_key=True,
            # **The library publishes this pair itself**, on its page for
            # librarians, `bn.gov.ar/bibliotecarios/protocoloZ3950`, beside a contact
            # address and with no stated restriction on use. It is the whole of the
            # argument for carrying it here, and `ShippedCredential` is where that
            # argument is written down: read it before removing this line, because
            # removing it is reversing the owner's decision of 2026-09-07 rather
            # than tidying a secret out of a published file.
            #
            # Verified by hand against the live target on 2026-09-07, not from a
            # test: unauthenticated the endpoint answers SRU diagnostic 1/3,
            # `Authentication error`, and with this pair it answers records.
            shipped_credential=ShippedCredential("Z39.50", "Z39.50"),
            # **Empty because it was measured and refused, which is the one
            # thing this row's emptiness must not be read as not having been.**
            # A remit is worth more here than anywhere else on the roster, since
            # shipping this login made every install ask a plaintext catalogue,
            # carrying HTTP Basic, about every ISBN the chain misses. The
            # committed sample cannot support one, and `metadata`'s block for
            # this row is where that pass and its numbers live.
            serves_groups=frozenset(),
            sru_version="1.1",
            query_parameter="x-pquery",
            query_language=QueryLanguage.PQF,
            # No `recordSchema`: `recordSchema=marcxml` answers SRU diagnostic 1/66
            # and the target renders its own Dublin Core regardless.
            record_schema="",
            isbn_attribute=z3950.USE_ISBN,
            lookup_records=1,
        ),
        CatalogueSource.BNU: Target(
            source=CatalogueSource.BNU,
            rank=17,
            transport=Transport.SRU,
            # **The BNA's two compromises again**: port 9992 speaks no TLS and the
            # library publishes a bare address. That row's comment carries what
            # an `Authorization` header over plaintext costs, and it applies here
            # unchanged. The port is the Z39.50 one the library publishes; the
            # same YAZ front end answers SRU on it, measured 2026-11-07.
            base_url="http://164.73.2.157:9992/BNU01",
            reader=Reader.DUBLIN_CORE_BARE,
            answers_lookup=True,
            # **Not every hit carries a record**, the BNA's property at a second
            # Aleph and looser here: of six sampled ISBNs with several hits, at
            # `maximumRecords=5`, five filled one `recordData` and one filled
            # three. Asked for one record, all three ISBNs tried filled it. So a
            # lookup asks for one, and a search, which would want ten, is not
            # offered. Measured 2026-11-07.
            answers_search=False,
            metered=False,
            needs_key=True,
            # **Published by the library itself**, in its section for
            # librarians at `bibna.gub.uy/protocolo-z39-50`, beside the host,
            # port and database, with no stated restriction on use. The argument
            # is the Argentine row's and is at `ShippedCredential`. Owner's
            # decision of 2026-09-05 on #117.
            #
            # Verified by hand against the live target on 2026-11-07:
            # unauthenticated the endpoint answers SRU diagnostic 1/3,
            # `Authentication error`, and with this pair it answers records.
            shipped_credential=ShippedCredential("Z39.50", "z39.bnu"),
            # **Uruguayan publishing, and measured rather than assumed**, which is
            # what the BNA's row could not say of itself. The whole committed
            # sample was put to this catalogue on 2026-11-07, so it has a column
            # there: it hits 27 of the 500, and all 27 are in this group.
            serves_groups=frozenset({"978-9974"}),
            sru_version="1.1",
            query_parameter="x-pquery",
            query_language=QueryLanguage.PQF,
            # No `recordSchema`: `marcxml` answers diagnostic 1/66, as at the BNA.
            record_schema="",
            isbn_attribute=z3950.USE_ISBN,
            lookup_records=1,
        ),
        CatalogueSource.GOOGLE_BOOKS: Target(
            source=CatalogueSource.GOOGLE_BOOKS,
            rank=18,
            transport=Transport.BESPOKE,
            base_url="https://www.googleapis.com/books/v1/volumes",
            reader=Reader.GOOGLE_BOOKS,
            answers_lookup=True,
            answers_search=True,
            metered=True,
            needs_key=True,
            # **The one row entitled to `metadata.Access.api_key`, and the only
            # row on the roster naming a secret at all.** The dispatch reads
            # this rather than `metered` or `needs_key`, both of which several
            # sources can answer yes to. See `Secret`.
            secret=Secret.GOOGLE_BOOKS_KEY,
            serves_groups=frozenset(),
        ),
        CatalogueSource.BNF: Target(
            source=CatalogueSource.BNF,
            rank=19,
            transport=Transport.SRU,
            timeout_seconds=4.0,
            base_url="https://catalogue.bnf.fr/api/SRU",
            reader=Reader.DUBLIN_CORE,
            answers_lookup=False,
            answers_search=True,
            metered=False,
            needs_key=False,
            serves_groups=frozenset(),
            sru_version="1.2",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="dublincore",
            title_index="bib.anywhere",
            title_query_shape=TitleQuery.QUOTED_ALL,
            search_multiplier=2,
            search_cap=20,
        ),
        CatalogueSource.LOC: Target(
            source=CatalogueSource.LOC,
            rank=20,
            transport=Transport.SRU,
            timeout_seconds=4.0,
            base_url="http://lx2.loc.gov:210/lcdb",
            reader=Reader.MODS,
            answers_lookup=False,
            answers_search=True,
            metered=False,
            needs_key=False,
            serves_groups=frozenset(),
            sru_version="1.1",
            query_parameter="query",
            query_language=QueryLanguage.CQL,
            record_schema="mods",
            title_index="dc.title",
            title_query_shape=TitleQuery.QUOTED_PHRASE,
            search_multiplier=2,
            search_cap=20,
        ),
    }
)


def origin(base_url: str) -> str:
    """`scheme://host[:port]`, the unit the allowlist is written in, or empty.

    **`netloc` and not `hostname`, and that is load bearing.** `netloc` carries
    any userinfo, so `https://services.dnb.de@evil.test/sru/dnb` yields
    `https://services.dnb.de@evil.test`, which is not in `SEEDED_ORIGINS` and is
    therefore refused by comparison alone. `hostname` would drop the userinfo and
    resolve that string to the host a person reads rather than the host a client
    connects to, which is the case `covers.is_fetchable` refuses explicitly.

    **Empty rather than an exception on a URL that will not parse.** `urlsplit`
    raises `ValueError` on an unterminated IPv6 literal, measured on
    `http://[::1/x`, and that is neither `BadQuery` nor `httpx.HTTPError`, so it
    would escape both handlers in `metadata`'s SRU door as a 500.
    `covers.is_fetchable` records this exact trap and puts its parse inside the
    `try` for it; the lesson was written down next door and is carried over here.
    An empty origin matches nothing, so it fails closed.
    """
    try:
        parts = urlsplit(base_url)
    except ValueError:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


#: Every origin this application will open a catalogue connection to.
#:
#: **Scheme, host and port, and not just the host**, so a row cannot downgrade a
#: TLS target to plaintext or move it to another port on the same name. **Nine**
#: targets speak no TLS: five are plain HTTP by necessity (ports 210, 210, 9991,
#: 9991 and 9992 offer nothing else) and four are Z39.50, which has no TLS form
#: here, and an allowlist of bare hostnames would let the HTTPS ones join them.
#: Two of the nine authenticate, so a plaintext origin here is not only a
#: question of what an eavesdropper reads.
#: `tests/test_metadata.py::TestThePlaintextSourcesAreCounted` recomputes that
#: count from the rows and checks this sentence against it, because it had gone
#: stale in the commit that added the fourth.
#:
#: **Declared here and applied nowhere, deliberately, and this is the paragraph
#: to read before applying it.** `fetch.py` and `z3950.py` both argue they need
#: no allowlist because a target's host is a module constant, and both name the
#: day a target comes from stored configuration as the day that stops holding.
#: This ticket does not reach that day: the runtime asks `SEEDED`, which is a
#: module constant, so both arguments survive unamended. #130 makes a row
#: editable and #131 makes a host typeable, and either one is the day.
#:
#: **What applying it has to get right**, measured by a critic on this tree so
#: the next seat does not rediscover it:
#:
#: * it goes in `fetch._walk_hops` before the first stream, not in `get`, because
#:   that is what opens the socket and it is what sees a URL a bespoke adapter
#:   built by concatenation;
#: * it judges the URL through `httpx.URL`, not `urlsplit`, and both sides of the
#:   comparison through the same normaliser: `urlsplit` strips a tab, CR or LF
#:   anywhere in a URL and httpx raises on one, so the string judged is otherwise
#:   not the string sent, and `https://services.dnb.de:443/x` and
#:   `https://SERVICES.DNB.DE/x` are both refused by naive string comparison;
#: * it refuses an unparseable URL, a URL carrying a username or password, and an
#:   origin outside the set, and nothing else, because `fetch._same_host_hop`
#:   already pins every later hop;
#: * it raises a `fetch.FetchRefused` subclass, which is an `httpx.HTTPError`, so
#:   it lands in every existing handler and costs no new arm;
#: * and **this set is not the whole allowlist**. `fetch.py` is every outbound
#:   door but covers, and `authority.py` is a caller with five origins of its
#:   own, `lobid.org`, `viaf.org`, `wikidata.org`, `pub.orcid.org` and
#:   `urn.bnportugal.gov.pt`, none of them here. A check derived from this set
#:   alone refuses every author identity lookup in the application.
#:
#: Not merged with `covers.COVER_HOSTS`, which is a different question with a
#: different answer: that tuple generates the CSP's `img-src`, so merging would
#: widen the browser policy to pay for a fetch policy.
#:
#: Derived from `SEEDED` rather than written out, so it cannot drift.
SEEDED_ORIGINS: Final[frozenset[str]] = frozenset(origin(target.base_url) for target in SEEDED.values())
