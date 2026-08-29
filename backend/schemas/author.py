from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from authors import AUTHOR_NAME_MAX, author_key
from enums import AuthorityProvenance, AuthorityScheme
from models import AUTHOR_KEY_MAX, AUTHORITY_IDENTIFIER_MAX

#: An author key as it arrives from a caller.
#:
#: Bounded for the reason every string field here is: it is compared against
#: keys built from `books.author`, which is 500 characters, so nothing longer
#: can match anything and accepting it only makes a bigger request body to
#: normalise. Not a `RowIdField`, because an author has no row to name, and not
#: an identity either: a key is derived from a name, so a merge retires it with
#: the spelling it came from. A retired one is resolved through the alias rows.
AuthorKeyField = Annotated[str, StringConstraints(min_length=1, max_length=AUTHOR_KEY_MAX)]

#: How many authors one merge may fold at once.
#:
#: A suggestion group is at most a handful, and this is the ceiling on a
#: hand-written request rather than on anything the UI produces. It exists so
#: the alias writer's repointing pass is bounded by a number in this file
#: rather than by how long a list somebody posted.
MAX_MERGE_KEYS = 50


class AuthorMergeOut(BaseModel):
    """A spelling that reached this author through somebody's merge.

    Carries the alias row's id because undoing a merge is deleting that row,
    and the spelling as written because the key it is stored under is
    normalised past the point of being readable ("le guin ursula k").
    """

    alias_id: int
    spelling: str


class RefusedAssertionOut(BaseModel):
    """A catalogue said one thing, this Library already held another.

    **Not stored anywhere**: a fact about the refresh or enrichment that
    produced it, served on that response and nowhere else. The store holds one
    value per spelling per scheme, which is what makes an identifier
    unretypeable, so a second value has no row to go in. Reporting it here is
    the alternative to discarding it silently, which would be resolution by
    precedence and is what this feature refuses to do anywhere else.

    `kept_provenance` is the field to read first. `catalogue` means two
    catalogues disagree, which is somebody else's problem to look at.
    `member` means a person's guess is outranking a national library, and the
    fix is to delete the guess and refresh again.
    """

    name: str
    scheme: AuthorityScheme
    #: What the catalogue said, and what was not stored.
    asserted: str
    #: What this Library holds, and what still stands.
    kept: str
    kept_provenance: AuthorityProvenance


class AuthorityDisagreementOut(BaseModel):
    """Two authority files pointing at different records for one person.

    Reported and never resolved by precedence: neither file is the authority on
    the other, and a rule picking a winner would decide silently exactly where a
    person should be asked. The same call `AuthorOut.identifier_conflicts` makes
    for two local spellings, at the other end of the feature.
    """

    #: Which cross reference they disagree about, `wikidata` or `viaf`. What a
    #: reader has to look up, rather than which service said what.
    about: str
    lobid: str | None = None
    wikidata: str | None = None


class AuthorityCandidateOut(BaseModel):
    """One person an authority file holds, offered for a Member to choose.

    **Nothing here is stored, and there is nowhere to store most of it.** The
    description and the dates exist so somebody can tell two same named people
    apart at the moment they confirm, and the only column this whole path can
    write is an identifier. `docs/featurelist.md` refuses author biographies and
    portraits, and this is the identity and disambiguation half of that line
    rather than an exception to it.

    `certain` says which route produced the row, and it is the **only** bit
    saying it. True where this Library already holds the identifier and it was
    resolved as a key, so there is exactly one record behind it and `name` is a
    spelling that can be offered with confidence. False where a name search
    produced it, which is a guess: two authors share a name. A client offers
    confirmation on exactly the false ones.

    **There was a second field, `stored`, and it carried the same bit.**
    `resolve` set `certain` true unconditionally and only ran for identifiers
    already held, so the two agreed on every reachable path. Their one
    divergence was a defect rather than information: a **superseded** GND
    resolves to the current record, whose `gndIdentifier` differs from the
    number stored, and the pair then read `certain=True, stored=False` while the
    Library did hold one.

    `wikidata_id` being null is a **hint**, not a verdict. Of the two GND
    records spelled `Stevenson, Robert Louis`, only one has a Wikidata item.
    That is worth showing to whoever is confirming and is exactly the wrong
    thing to resolve on automatically.
    """

    scheme: AuthorityScheme
    identifier: str
    #: The authority's own spelling, which is the suggestion. In catalogue order
    #: (`Stevenson, Robert Louis`), because that is how the GND writes a name.
    name: str
    #: The authority's other spellings. Shown, and deliberately not written to
    #: `author_aliases`: an alias row is this Household's decision and this is a
    #: national library's list, and folding one into the other would turn a
    #: curated list into a generated one.
    variants: list[str] = Field(default_factory=list)
    #: As the GND writes them, which is often partial (`1850`, `1850-11-13`) and
    #: often absent. Strings rather than dates: nothing sorts or subtracts them.
    born: str | None = None
    died: str | None = None
    #: Every cross reference the GND record lists. Recorded and shown, never
    #: fetched. This is where a VIAF cluster id arrives without VIAF being
    #: called.
    same_as: list[str] = Field(default_factory=list)
    certain: bool = False
    wikidata_id: str | None = None
    description: str | None = None
    disagreements: list[AuthorityDisagreementOut] = Field(default_factory=list)


class AuthorIdentifierOut(BaseModel):
    """Which record in an authority file one spelling of this name means.

    `spelling` rather than the key it is filed under, for the reason
    `AuthorMergeOut` carries one: the key is normalised past the point of being
    readable, and the whole use of this field is to say *which* of a merged
    author's spellings carries this number when two of them disagree.

    `provenance` is an explicit value and never a null. A member auditing the
    list has to be able to tell an assertion a catalogue made from one somebody
    chose, and inferring it from an absent user id would make a deleted account
    look like a machine. See `enums.AuthorityProvenance`.
    """

    id: int
    spelling: str
    scheme: AuthorityScheme
    identifier: str
    provenance: AuthorityProvenance


class ConfirmedIdentifierOut(BaseModel):
    """What one confirmation wrote: the number asked for, and what came with it.

    **A person confirms a record, not a number.** The GND record a Member picks
    already carries that person's ISNI, LCNAF number, VIAF cluster and Wikidata
    item, and until this existed all four were shown once and dropped.
    `identifier` is what the request named and `cross_references` is what the
    same record asserted beside it.

    **`refused` is not an error and the request that produced it succeeded.**
    A cross reference colliding with a value this Library already holds is
    reported rather than raised, because the confirmation is what the Member
    asked for and a fact arriving alongside it must not undo one. A collision on
    the confirmed identifier itself is the opposite case and is a 409.

    Empty lists are the ordinary answer, not a failure: they mean the authority
    file was not reachable in the moment, or the confirmed scheme is not one
    this app can resolve, or the record carried nothing new. Nothing in this
    feature is blocked by any of the three.
    """

    identifier: AuthorIdentifierOut
    cross_references: list[AuthorIdentifierOut] = Field(default_factory=list)
    refused: list[RefusedAssertionOut] = Field(default_factory=list)


class AuthorIdentifierRequest(BaseModel):
    """Confirm that a candidate identifier is this author's.

    **The write for the uncertain half only.** An identifier on the record a
    catalogue returned for a Book's own ISBN is stored without asking; this is
    what a name search produces, which is a candidate rather than a match, and
    it reaches the store only because a person said so.

    `author` is a key or any spelling, like every other author endpoint.
    `identifier` is bounded by what the column holds rather than by a per scheme
    format: a GND number is digits and hyphens today, and hard coding that here
    would make the next authority file a schema change instead of an enum
    member.
    """

    author: AuthorKeyField
    scheme: AuthorityScheme
    identifier: Annotated[
        str, StringConstraints(min_length=1, max_length=AUTHORITY_IDENTIFIER_MAX)
    ]

    @field_validator("identifier")
    @classmethod
    def tidy_identifier(cls, value: str) -> str:
        """Collapse the whitespace, and refuse what is left if it is nothing.

        A value of only spaces passes `min_length` and then violates
        `ck_author_identifiers_bounds` at the database, which is a 500 rather
        than a 422.
        """
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("An identifier needs a value.")
        return cleaned


class AuthorOut(BaseModel):
    """One person, as far as this shelf knows, and what it knows about them.

    `key` is what the book filter and the merge endpoint address an author by,
    and it is derived from `name` rather than being an identity behind it: a
    merge retires the keys it folds, exactly as it retires the spellings. Both
    endpoints therefore accept either, and resolve a retired one through the
    alias rows.

    `book_count` is filtered by `visible_to`, like every count this API serves.
    An unfiltered one would announce that somebody's private books exist and
    how many, on a page every member can read.
    """

    key: str
    name: str
    book_count: int = Field(ge=0)
    #: Every spelling of this name on the shelf, most used first. The one the
    #: display name came from is in here too, unless a merge chose a name that
    #: no book carries.
    spellings: list[str] = Field(default_factory=list)
    #: The spellings folded in by a merge, each with the row that says so.
    #:
    #: **Only the ones this caller can already see.** An alias is a library
    #: wide statement about names, so it is shown like a collection name is;
    #: one whose spelling survives only on somebody else's private book is left
    #: out, because listing it would announce that the book exists.
    merged: list[AuthorMergeOut] = Field(default_factory=list)
    #: What the authority files say this person is, one row per spelling per
    #: scheme. Filtered exactly like `merged` and for the same reason.
    identifiers: list[AuthorIdentifierOut] = Field(default_factory=list)
    #: The schemes on which the spellings folded into this person disagree.
    #:
    #: Reported rather than resolved: either the local merge is wrong or the
    #: upstream cluster is, and nothing here can tell which. Empty is the
    #: ordinary case, including for an author with no identifier at all.
    identifier_conflicts: list[AuthorityScheme] = Field(default_factory=list)


class AuthorWikipediaOut(BaseModel):
    """Where to send a reader who wants to read about one author.

    **A link and never a biography.** `docs/featurelist.md` refuses author
    biographies and portraits, and this is the outward link half of #89's
    decision rather than an exception to it: nothing is fetched but the list of
    which language editions exist, nothing is stored, and no prose, description
    or image reaches this model. A field here carrying an extract would be that
    refusal reversed.

    **Offered only for an author carrying a confirmed Wikidata identifier**, so
    "if it is available" is a property of the data rather than of the network.
    #87 measured why: two GND records are spelled `Stevenson, Robert Louis` and
    only one has a Wikidata item, and an article about the wrong one of them is
    worse than none.

    `language` is the Wikipedia edition `url` points at, and **null means the
    URL is the Wikidata item's own page**: either no edition holds an article,
    or Wikidata could not be reached. A client renders both the same way and can
    say which language it landed on when that is not the reader's own.
    """

    key: str
    url: str
    language: str | None = None


class AuthorSuggestionOut(BaseModel):
    """Names that are probably one person, and the rules that said so.

    A suggestion, never a verdict. `reasons` is returned so a reader can tell a
    certainty from a guess: `spelling` is the same name with the spaces moved,
    `initials` is an abbreviated given name, and `fragment` is one name's words
    sitting inside another's, which is what a credit line stored in catalogue
    order splits into.
    """

    keys: list[str]
    names: list[str]
    reasons: list[str]


class AuthorMergeRequest(BaseModel):
    """Fold these spellings into this name.

    `keys` are authors that exist on the shelf. `keep_name` is free text and
    deliberately need not be one of them: a credit line stored as "Le Guin,
    Ursula K." splits into two people, neither of whom is spelled correctly,
    and the repair is to fold both into a name typed by hand. Nothing about
    that edits the book, and deleting the alias rows puts the shelf back.
    """

    keys: Annotated[
        list[AuthorKeyField],
        Field(min_length=1, max_length=MAX_MERGE_KEYS),
    ]
    keep_name: Annotated[str, StringConstraints(min_length=1, max_length=AUTHOR_NAME_MAX)]

    @field_validator("keep_name")
    @classmethod
    def tidy(cls, value: str) -> str:
        """Collapse the whitespace, and refuse a name that normalises to nothing.

        A name of only punctuation passes `min_length` and then has an empty
        key, which no spelling can ever match: the merge would appear to work
        and fold every named author into an author nothing can reach.
        """
        cleaned = " ".join(value.split())
        if not author_key(cleaned):
            raise ValueError("An author needs a name with a letter or a digit in it.")
        return cleaned
