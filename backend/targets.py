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
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit

import z3950

# `Reader` is aliased to itself deliberately: `Target.reader` is typed on it, so
# it is part of this module's surface even though the decoder registry is
# `decoders.py`'s, and the redundant alias is what says so to mypy under
# `no_implicit_reexport`. Spelling it `targets.Reader` at a call site is not a
# mistake; building a decoder from anything but `Target.decoding` is.
from decoders import IMPORT_READERS, MARC_READERS, Decoding
from decoders import Reader as Reader
from enums import Capability, CatalogueSource, SourceFamily


class Transport(StrEnum):
    """Which door a target's request goes out of.

    `Z3950` is declared and no seeded target uses it: `Target` refuses one, and
    the door is #129's.

    **Declaring it now does not save that ticket a migration**, which an earlier
    version of this paragraph claimed. `ck_catalogue_targets_transport` names the
    two transports a row may carry, SQLite cannot ALTER a constraint, and this
    project sets `render_as_batch=True` for exactly that reason, so widening it
    is a batch rebuild whatever this enum says. What declaring it buys is
    smaller and still worth having: the refusal is stated in one vocabulary in
    both places, so #129 lifts one rule rather than discovering two.
    """

    SRU = "sru"
    Z3950 = "z3950"
    #: Not SRU and not Z39.50: a JSON API of the target's own design, with its
    #: own adapter. Open Library and Google Books, and nothing else. A row here
    #: carries an address and its capabilities and no query fields at all,
    #: because there is no query grammar to name.
    BESPOKE = "bespoke"


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
_RESERVED_SRU_PARAMETERS: Final = frozenset(
    {"version", "operation", "maximumrecords", "recordschema"}
)

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
    source: CatalogueSource
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
    #: The login this build ships for the target, where the library publishes
    #: one about itself. None everywhere else, which is every row but one.
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
    record_schema: str = ""
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

    #: A deadline for this target alone, in seconds, under
    #: `metadata.SEARCH_DEADLINE_SECONDS` as the ceiling over the whole fan out.
    #:
    #: **NULL on every seeded row and read by nothing today.** #132 enforces it;
    #: this ticket is the spine it lands on. `test_targets.py` pins it None
    #: across the roster so the column cannot be read as working.
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.transport is Transport.Z3950:
            raise ValueError(
                f"{self.source}: no Z39.50 door yet, the transport dispatch is #129"
            )
        if self.reader in IMPORT_READERS:
            # **The registry refusing the other family's parser**, which is the
            # one rule `enums.SourceFamily` exists for and the one place a row
            # could break it. `metadata.resolve` catches only a row that also
            # declares a capability, so a row naming this reader and answering
            # nothing would otherwise construct and sit in the roster.
            raise ValueError(
                f"{self.source}: {self.reader} belongs to the import family, "
                "which no catalogue row may name"
            )
        if self.transport is Transport.SRU:
            self._check_sru()
        else:
            self._check_no_sru()
        if self.reader not in MARC_READERS:
            self._check_no_marc_knobs()
        if (
            not self.requires_isbn_claim
            and self.source not in _MAY_WAIVE_THE_ISBN_CLAIM
        ):
            raise ValueError(
                f"{self.source}: only the DNB may waive the ISBN identity check"
            )
        if self.shipped_credential is not None and not self.needs_key:
            # A default on a row that authenticates nothing is a credential
            # published for no reason, and it would put the source in
            # `credentials`' ladder while `sources.NEEDS_A_KEY` says the source
            # asks for nothing. Refused at construction rather than ignored,
            # which is the rule the bespoke fields above already follow.
            raise ValueError(
                f"{self.source}: a shipped login on a row that needs no credential"
            )

    def _check_sru(self) -> None:
        if not self.sru_version or not self.query_parameter:
            raise ValueError(
                f"{self.source}: an SRU target needs a version and a parameter"
            )
        # **The query goes in a dict beside four fixed keys**, so a parameter
        # named like one of them replaces it and no query is sent at all. A
        # critic measured `query_parameter="version"` constructing cleanly and
        # `sru_params` returning a request whose SRU version was the CQL query.
        if self.query_parameter.lower() in _RESERVED_SRU_PARAMETERS:
            raise ValueError(
                f"{self.source}: {self.query_parameter!r} is an SRU parameter already"
            )
        if self.query_language is None:
            raise ValueError(f"{self.source}: an SRU target needs a query language")
        if self.answers_lookup:
            if self.lookup_records < 1:
                raise ValueError(f"{self.source}: answers a lookup and asks for no records")
            if self.query_language is QueryLanguage.CQL:
                if not _INDEX.fullmatch(self.isbn_index):
                    raise ValueError(f"{self.source}: not an index name: {self.isbn_index!r}")
            elif (
                type(self.isbn_attribute) is not int
                or self.isbn_attribute not in _USE_ATTRIBUTES
            ):
                # **`type(...) is not int` and not `isinstance`, and not
                # membership alone.** `7.0 in {7}` is True, because a float
                # compares equal to an integer, so membership admitted a value
                # `z3950.query` then refuses at request time with `BadQuery`.
                # That is the same rule enforced in two places and disagreeing:
                # one arm built a row the other would not send.
                raise ValueError(
                    f"{self.source}: not a PQF use attribute: {self.isbn_attribute!r}"
                )
        if self.answers_search:
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
            raise ValueError(f"{self.source}: a MARC knob on a reader that reads no MARC")

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
            assert self.isbn_attribute is not None  # __post_init__
            return z3950.query(self.isbn_attribute, value)
        return f"{self.isbn_index}={cql_term(value)}"

    def title_query(self, terms: list[str]) -> str:
        """The query that asks this target about a list of title terms."""
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


#: Which family `SEEDED` is the registry for.
#:
#: Named rather than left implicit so a guard has a line to read:
#: `tests/test_decoders.py::TestTwoFamiliesMeanTwoRegistries`. The consequence
#: is on `enums.SourceFamily`.
FAMILY: Final = SourceFamily.CATALOGUE

#: The eleven catalogues this application ships knowing about.
#:
#: **This is what the runtime asks, and the table is what it seeds.** The
#: migrations write ten of these rows into `catalogue_targets` and
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
SEEDED: Final[dict[CatalogueSource, Target]] = {
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
        base_url="https://sru.k10plus.de/opac-de-627",
        reader=Reader.MARC_PLAIN,
        answers_lookup=True,
        answers_search=True,
        metered=False,
        needs_key=False,
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
        rank=2,
        transport=Transport.BESPOKE,
        base_url="https://openlibrary.org",
        reader=Reader.OPEN_LIBRARY,
        answers_lookup=True,
        answers_search=True,
        metered=False,
        needs_key=False,
    ),
    CatalogueSource.NKP: Target(
        source=CatalogueSource.NKP,
        rank=3,
        transport=Transport.SRU,
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
        rank=4,
        transport=Transport.SRU,
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
        rank=5,
        transport=Transport.SRU,
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
    CatalogueSource.OENB: Target(
        source=CatalogueSource.OENB,
        rank=6,
        transport=Transport.SRU,
        base_url="https://obv-at-oenb.alma.exlibrisgroup.com/view/sru/43ACC_ONB",
        reader=Reader.MARC_GND,
        answers_lookup=True,
        answers_search=True,
        metered=False,
        needs_key=False,
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
        rank=7,
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
        sru_version="1.1",
        query_parameter="x-pquery",
        query_language=QueryLanguage.PQF,
        # No `recordSchema`: `recordSchema=marcxml` answers SRU diagnostic 1/66
        # and the target renders its own Dublin Core regardless.
        record_schema="",
        isbn_attribute=z3950.USE_ISBN,
        lookup_records=1,
    ),
    CatalogueSource.GOOGLE_BOOKS: Target(
        source=CatalogueSource.GOOGLE_BOOKS,
        rank=8,
        transport=Transport.BESPOKE,
        base_url="https://www.googleapis.com/books/v1/volumes",
        reader=Reader.GOOGLE_BOOKS,
        answers_lookup=True,
        answers_search=True,
        metered=True,
        needs_key=True,
    ),
    CatalogueSource.BNF: Target(
        source=CatalogueSource.BNF,
        rank=9,
        transport=Transport.SRU,
        base_url="https://catalogue.bnf.fr/api/SRU",
        reader=Reader.DUBLIN_CORE,
        answers_lookup=False,
        answers_search=True,
        metered=False,
        needs_key=False,
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
        rank=10,
        transport=Transport.SRU,
        base_url="http://lx2.loc.gov:210/lcdb",
        reader=Reader.MODS,
        answers_lookup=False,
        answers_search=True,
        metered=False,
        needs_key=False,
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
#: TLS target to plaintext or move it to another port on the same name. **Four**
#: targets are plain HTTP by necessity (ports 210, 210, 9991 and 9991 speak no
#: TLS) and an allowlist of bare hostnames would let the other seven join them.
#: One of the four authenticates, so a plaintext origin here is not only a
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
#:   door but covers, and `authority.py` is a caller at three sites with three
#:   origins of its own, `lobid.org`, `viaf.org` and `wikidata.org`, none of them
#:   here. A check derived from this set alone refuses every author identity
#:   lookup in the application.
#:
#: Not merged with `covers.COVER_HOSTS`, which is a different question with a
#: different answer: that tuple generates the CSP's `img-src`, so merging would
#: widen the browser policy to pay for a fetch policy.
#:
#: Derived from `SEEDED` rather than written out, so it cannot drift.
SEEDED_ORIGINS: Final[frozenset[str]] = frozenset(
    origin(target.base_url) for target in SEEDED.values()
)
