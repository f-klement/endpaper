"""Whether this Library may ask an outside catalogue, and what a Member is told if not.

**The one way a request reaches a catalogue.** `metadata.py` knows *how* to ask: the
rosters, the transports, the ranking, the budget. This module answers the question in
front of that one, which `metadata.py` deliberately cannot: may this deployment ask at
all, with which credentials, under which rate limit, and what does a Member see when the
answer is no. None of that is `metadata.py`'s, because none of it can be known without a
database.

**What a handler stops knowing.** Before this module, six handlers in `routers/books.py`
each rebuilt the same five decisions by hand: which of two resolvers to call, that the
result must be resolved once and never rebuilt, which of two limiters guards this route,
which of four emptiness predicates its own path needs, and which of three refusal
sentences goes with it. A handler now picks a question and asks it.

**A method that can refuse carries its own roster and its own sentence**, so those two
cannot be paired with the wrong one of each other. `lookup`, `search` and `volume` refuse
nothing, each for the reason at its own site, and a caller with fallback paths asks
`refuse_if_nothing_is_asked` instead. What is uniform is the limiter: it is charged by the
constructor, so no method can be reached without it.

**A cataloguer may narrow one request, and only narrow it.** The two narrowed constructors
take a set of catalogues and keep the standing plan's order, so the leading tier and the
fallback are the leading enabled sources of what remains, through the same `Plan` every
other request reads. The narrowing is checked against the plan in force, which is the
institution's policy, and a name outside it is refused rather than dropped: a dropped name
would turn "ask only these" into "ask these, or whatever is left".

**Two types, and the second one is why this is not one class with two constructors.**
`Enquiry` holds a resolved `metadata.Access`, logins included. `GoogleVolumes` holds a
plan and a key and no logins at all, because its single door sends none. A single class
with two named constructors was the obvious simplification and it is refused: the
keyless object would carry `lookup` and `title_search`, methods whose whole purpose is
to send a login they would then not have. That is the defect `metadata.Access.logins`
used to permit by defaulting, moved one level up and harder to see. **They are two
unrelated dataclasses rather than a base and a subclass**, because inheritance would
share the field set and "no logins live here" would become a question of which class a
reader was looking at.

**Every refusal sentence is a module level constant**, never built from a value. This
module holds the deployment's API key and also builds response bodies, which is the one
combination where an interpolated detail puts a secret on the wire. `TestTheDoorSaysNothingItWasNotGiven`
refuses an f-string reachable from an `HTTPException` here.

**What this module deliberately does not own, so the next reader does not move it in.**
How to choose between an ISBN, a store identifier and a title, which is
`enrich_book`'s own ordering policy and carries ADR 0006's rule that only a record found
by the Book's own ISBN asserts authorship. And any query over books: nothing here takes
a `User` or reaches `user.id`, so nothing here can build one, and
`Shelf.seen_by` stays in the handler that pages a shelf. And the outbound cost ceiling a
backfill spends its key through: every value here is read from a settings row and answers
whether this Library may ask, where a concurrency bound is a fact about one pod's memory
that no Member is ever told. Folding them puts a ceiling in the one module built from a
store that degrades rather than refuses, so it would fail open toward a larger bound. All
three were proposed and all three are
refused: this module is one concept, and the reason it can be reviewed for the
credential properties above is that it is only that one.
"""

import dataclasses
import logging
from collections.abc import Callable
from typing import Final, Self

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import catalogue
import credentials
import metadata
import settings_store
import sources
from enums import CatalogueSource
from ratelimit import identifier_backfill_limiter, metadata_limiter

logger = logging.getLogger(__name__)


#: Nothing this Library asks can answer an ISBN.
#:
#: **409 rather than 404, and it is the one refusal here that is about this Library
#: rather than about the book.** Nothing is wrong with the ISBN: a 404 would be the app
#: reporting a fact about a book it never asked anybody about.
#:
#: **It names who can undo it.** Every route that raises one of these needs only a
#: signed in Member, and `GET /api/settings` is admin only, so the sentence used to tell
#: most readers to visit a screen they cannot open.
NOTHING_ANSWERS_AN_ISBN: Final[str] = (
    "No catalogue is switched on that can look up an ISBN. An administrator can "
    "turn one back on under Settings, Catalogue sources."
)

#: Nothing this Library asks can answer a title search.
#:
#: **A separate sentence rather than an argument to a shared one**, because the roster
#: and the wording have to be chosen by the same thing. When one function took the
#: wording as a parameter, a title search refused by naming the ISBN path, and the fix
#: reached one of its two call sites. A constant beside the method that raises it cannot
#: come apart that way.
#:
#: **Keyed on the harder roster wherever it is raised.** A Library whose every enabled
#: search catalogue is a slow one has switched nothing off, so "turn one back on" would
#: name the wrong cause; that Library gets an empty page instead.
NOTHING_ANSWERS_A_TITLE_SEARCH: Final[str] = (
    "No catalogue is switched on that can answer a title search. An administrator "
    "can turn one back on under Settings, Catalogue sources."
)

#: This Library asks no catalogue at all.
#:
#: Raised where a handler reaches outward by more than one route and every one of them
#: is unavailable. Refusing up front is one answer where letting each path fail would be
#: two or three, for one request.
NOTHING_IS_SWITCHED_ON: Final[str] = (
    "No catalogue is switched on, so there is nothing to fill this book in from. "
    "An administrator can turn one back on under Settings, Catalogue sources."
)

#: This Library does not ask Google Books, so a Google volume id cannot be resolved.
#:
#: **Its own sentence because its own cause is specific**: a volume id is Google's
#: accession number and nothing else in the world resolves one, so naming any other
#: catalogue would be useless. Two things have to hold, the section being on and a key
#: being in force, and the sentence names both because either one missing produces this.
#:
#: **Safe to tell any member only because `GET /api/settings/features` tells anybody**,
#: as `google_books_ready`, which is public deliberately. Narrowing that flag makes this
#: refusal the disclosure, so the two move together: narrowing the flag fails
#: `tests/test_catalogue_access.py::TestTheBackfillRefusalTellsAMemberOnlyWhatAnybodyCanRead`,
#: and that test goes with this refusal.
GOOGLE_BOOKS_IS_NOT_ASKED: Final[str] = (
    "This Library does not ask Google Books, so a Google volume id cannot be "
    "resolved. An administrator can switch Google Books on in Settings and add an "
    "API key."
)


#: Narrowing a request is a library mode feature.
#:
#: **403 rather than a silent full search**, the status the MARCXML export answers a
#: household with: a client sending a narrowing outside library mode is out of step with
#: the server, and asking every catalogue instead would answer a question it did not ask.
NARROWING_NEEDS_LIBRARY_MODE: Final[str] = "Asking only some catalogues is a library mode feature."

#: A narrowed lookup named a catalogue this Library does not ask for an ISBN.
#:
#: **A refusal, never an intersection that drops the name.** The standing list is
#: the institution's policy, and a narrowing can only take sources away from it. Naming a
#: switched off source, or one that cannot answer an ISBN, is a request the policy does
#: not permit, and dropping it quietly would also answer a narrowing to that source alone
#: with every other source asked.
NARROWED_PAST_THE_ISBN_ROSTER: Final[str] = (
    "Only catalogues this Library asks for an ISBN can be chosen. At least one named here "
    "is switched off or cannot look up an ISBN."
)

#: The same refusal for a narrowed title search, with its own roster and its own words.
NARROWED_PAST_THE_TITLE_SEARCH_ROSTER: Final[str] = (
    "Only catalogues this Library asks in a title search can be chosen. At least one named "
    "here is switched off or cannot answer a title search."
)


def _refused(detail: str) -> HTTPException:
    """One of the constants above as the refusal it earns.

    Takes a constant rather than building a sentence, which is what keeps the rule in
    this module's docstring checkable: every `HTTPException` built here takes one of
    those names as its detail.
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def nothing_answers_an_isbn() -> HTTPException:
    """The refusal `metadata.Outcome.NO_SOURCES` earns, for a caller holding a `Lookup`.

    **The lookup path is the one that does not test up front, deliberately.**
    `sources.Plan.lookup_chain`'s emptiness *is* what `NO_SOURCES` means, and that
    docstring is where the fact lives. A door here re-testing it would be the same fact
    in two places, free to disagree, so what this module owns on that path is the
    sentence and not the predicate.
    """
    return _refused(NOTHING_ANSWERS_AN_ISBN)


def _resolved_access(db: Session) -> metadata.Access:
    """Everything one request may ask of the catalogues, resolved once.

    **Here rather than in `settings_store`, so exactly one module in the tree
    constructs a `metadata.Access`.** That is what lets the construction guard hold an
    allowlist of one name instead of two. `settings_store` keeps the three readers this
    calls, because what they answer is what the household configured, which is its
    subject; what this adds is that the three are one value and are read together.

    **The logins are resolved whatever the plan says, and travel no further than a
    source the plan admits.** `metadata._lookup_one` hands a credential to a bespoke
    adapter and `_search_one` to a metered one, and neither is constructed for a source
    the plan left out.

    **The key is resolved once here and handed to all three**, because each opens
    something sealed: the logins, a credentialled source's readiness, and the Google
    Books key since it is sealed too. Each resolving its own cost a lookup three
    resolutions once the Google key was sealed, each a keychain round trip on a
    desktop.
    """
    state = credentials.key_state()
    access = metadata.Access(
        plan=settings_store.catalogue_sources(db, state),
        api_key=settings_store.google_books_api_key(db, state),
        logins=settings_store.catalogue_logins(db, state),
    )
    _warn_about_any_source_asked_with_no_login(access)
    return access


def _narrowed_access(
    db: Session,
    only: frozenset[CatalogueSource],
    roster: Callable[[sources.Plan], tuple[CatalogueSource, ...]],
    refusal: str,
) -> metadata.Access:
    """The access this request may use, narrowed to `only`, or the refusal it earns.

    **Refuses before anything is charged**, so a narrowing the policy does not permit
    spends none of a Member's allowance: the same order `lookup_isbn` keeps for a
    malformed ISBN.

    **`sources.in_force` does the narrowing**, because it is already the one function
    that switches sources off in a plan while keeping its order. What it leaves is a plan
    like any other, so `lookup_together`, `lookup_in_turn` and the search rosters take
    the leading enabled sources of what remains with no second mechanism.

    **`roster` is the path's own**, `lookup_chain` or `searched_harder`. Checking
    against `asked` alone admitted a source that cannot answer this path, and the
    narrowed plan then refused with the 409 telling an administrator to switch a
    catalogue back on, for a library that had switched nothing off.
    """
    if not settings_store.library_mode(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NARROWING_NEEDS_LIBRARY_MODE)
    access = _resolved_access(db)
    if not only or not only <= frozenset(roster(access.plan)):
        raise _refused(refusal)
    return metadata.Access(
        plan=sources.in_force(access.plan, only), api_key=access.api_key, logins=access.logins
    )


def _warn_about_any_source_asked_with_no_login(access: metadata.Access) -> None:
    """Say so when the plan admits a credentialled source no login was resolved for.

    **Here because this is the one place both halves are in hand.** Two predicates
    decide whether such a source is asked, in `settings_store`, and they ask different
    questions of different subjects: `ready_sources` admits one on
    `credentials.is_held`, and `catalogue_logins` resolves one on
    `metadata.carries_a_credential`. A source in the first and not the second is in
    the plan with no entry in the mapping, and every request to it goes out with no
    credential and nothing saying so. `settings_store.catalogue_logins` carries the
    measurement and why this is a warning rather than a refusal.

    **Read off the resolved value, not off either predicate**, so it reports what this
    request will actually do rather than re-deriving whether it should. The source is
    named; the credential never is.
    """
    # The door set is asked rather than restated: `settings_store` owns which
    # catalogues a login is resolved for, and a second spelling here would drift
    # behind it in the miss direction, which is the very failure this warns about.
    carries_a_login = frozenset(settings_store.sources_whose_door_carries_a_login())
    bare = sorted(
        source.value
        for source in access.plan.asked
        if source in carries_a_login and source not in access.logins
    )
    if bare:
        logger.warning(
            "These catalogues are in the plan with no login resolved, so their "
            "requests will go out unauthenticated: %s",
            ", ".join(bare),
        )


@dataclasses.dataclass(frozen=True, slots=True, repr=False)
class Enquiry:
    """What one Member's request may ask the catalogues, and the only way to ask it.

    **Frozen, and the access is private.** The value being resolved once is the whole
    point: a handler reaching outward three times must not be able to ask two different
    rosters or send two different logins between them. The access being unreachable is
    what makes that structural rather than a rule a walk over the router has to check.

    **Built through `for_a_member_request`, which is what charges the rate limiter.**
    That is a rule rather than an impossibility, and the distinction matters: this is a
    dataclass with a public `__init__`, so `Enquiry(_access=_resolved_access(db))` would
    reach every door below with nothing charged. `mypy` permits it and no rule about
    logins or about door calls can see it.
    `tests/test_catalogue_access.py::TestOnlyTheAccessDoorBuildsAnAccess` is what refuses
    it, by name, for every module but this one.
    """

    _access: metadata.Access

    @classmethod
    def for_a_member_request(cls, db: Session, *, member: str) -> Self:
        """Charge this Member's metadata budget, then resolve what they may ask.

        **`member` is a username and never a `User`.** Nothing in this module can reach
        `user.id`, so nothing in it can build a query over books, which is what keeps
        `shelf.py` the only way into a many Book query. The limiter is keyed per member
        so a caller can only ever spend their own budget.

        **Called as a statement in the handler body, never as a `Depends`.** Two
        reasons, and the second is the one that survives the first being fixed. A
        dependency declared beside `CurrentUser` answers an unauthenticated caller with
        this route's 409 instead of a 401, and a route level `dependencies=[...]` entry
        is inserted ahead of every signature parameter so it cannot be ordered after the
        session check at all. That much is avoidable, by taking `CurrentUser` as a sub
        dependency. What is not avoidable is the charge: a dependency runs before the
        handler body, so a route whose own validation refuses locally would spend a
        Member's budget on a request that reaches no catalogue. Constructing it here lets
        each handler put its own refusals first.
        """
        metadata_limiter.check(member)
        return cls(_access=_resolved_access(db))

    @classmethod
    def for_a_narrowed_lookup(cls, db: Session, *, member: str, only: frozenset[CatalogueSource]) -> Self:
        """`for_a_member_request` for one ISBN lookup that asks only `only`.

        A cataloguer's judgement about one book, never a setting: nothing here is
        stored, so the next request asks the standing plan again.
        """
        access = _narrowed_access(db, only, lambda plan: plan.lookup_chain, NARROWED_PAST_THE_ISBN_ROSTER)
        metadata_limiter.check(member)
        return cls(_access=access)

    @classmethod
    def for_a_narrowed_title_search(
        cls, db: Session, *, member: str, only: frozenset[CatalogueSource]
    ) -> Self:
        """`for_a_member_request` for one title search that asks only `only`.

        Checked against `searched_harder`, every search catalogue this Library asks,
        so a slow one may be named; whether it is asked is still `harder`'s decision.
        """
        access = _narrowed_access(
            db, only, lambda plan: plan.searched_harder, NARROWED_PAST_THE_TITLE_SEARCH_ROSTER
        )
        metadata_limiter.check(member)
        return cls(_access=access)

    def __str__(self) -> str:
        return f"<enquiry of {len(self._access.plan.asked)} catalogue(s)>"

    def refuse_if_nothing_is_asked(self) -> None:
        """Refuse when this Library asks nothing at all, before any path is tried.

        **For a caller that reaches outward by more than one route.** Both halves of
        enrichment are optional on their own, so without this a Library with everything
        switched off got a lookup's refusal and then a search's, from one request.
        Asking nothing is one answer rather than two.

        **The predicate is `plan.asked` rather than either roster**, and it is the
        honest one for a caller with fallbacks: it asks whether anything is enabled, not
        whether the first path can answer. `test_sources.py` pins that every seeded
        target answers a lookup or a search, which is what makes this equivalent to
        both rosters being empty rather than merely equal to it today.
        """
        if not self._access.plan.asked:
            raise _refused(NOTHING_IS_SWITCHED_ON)

    async def lookup(self, isbn: str) -> metadata.Lookup:
        """Resolve an ISBN across every catalogue this Library asks.

        **Returns the outcome rather than raising on it.** Three callers read a failed
        `Lookup` and they do not agree about what it means: two answer the Member and
        one falls through to a second and third way of identifying the book. A raising
        door would make that third caller impossible to write without an argument
        turning the raise off, which is the behaviour switch this concept refuses.
        `nothing_answers_an_isbn` is the sentence for the two that do answer.
        """
        return await metadata.lookup(isbn, access=self._access)

    async def title_search(
        self,
        query: str,
        *,
        limit: int,
        prefer_language: str | None,
        harder: bool = False,
    ) -> metadata.Search:
        """Find a book by title and author, or refuse because nothing can.

        Refuses on `searched_harder` rather than `searched`: see
        `NOTHING_ANSWERS_A_TITLE_SEARCH`.
        """
        self._refuse_if_no_title_search()
        return await metadata.title_search(query, limit, prefer_language, access=self._access, harder=harder)

    async def search(self, query: str, *, limit: int) -> list[catalogue.Record]:
        """The rows of a title search alone, for a caller with no use for the roster.

        **The one search door that does not refuse, and the asymmetry is the
        point.** `title_search` and `candidates` serve routes whose entire answer
        is the search, so a Library that can run none has to be told. This serves
        a caller for which the search is the last of several ways to identify a
        book: refusing here would turn "we could not fill this book in" into an
        error, for a Library whose ISBN lookup works perfectly. An empty list is
        the honest answer to a search nobody could run, once somebody has already
        been told that something is askable.

        A caller wanting the refusal asks `refuse_if_nothing_is_asked` up front,
        which is the question that actually fits a caller with fallbacks.
        """
        return await metadata.search(query, limit, access=self._access)

    async def candidates(
        self,
        query: str,
        *,
        isbn: str | None,
        limit: int,
        prefer_language: str | None,
    ) -> list[catalogue.Record]:
        """Other editions of a book that already exists, cluster first then ranked.

        Refuses on the same roster as `title_search` and for the same reason: this runs
        a title search internally, so it is reached by the query and never by an ISBN.
        """
        self._refuse_if_no_title_search()
        return await metadata.candidates(
            query,
            isbn,
            limit,
            prefer_language,
            access=self._access,
        )

    async def volume(self, volume_id: str) -> metadata.Lookup:
        """Resolve a Google volume id, where this Library asks Google Books.

        **Takes the key and the plan apart**, which is `metadata.lookup_volume`'s own
        signature and not a convenience here: its one target keeps its secret in a
        query string, so an access would hand it a keychain it drops without a word,
        which is the shape that makes a caller believe a login went out.

        No refusal of its own. `metadata.lookup_volume` answers `NO_SOURCES` when Google
        is absent from the plan, and the caller that needs to refuse a whole batch on
        that has `GoogleVolumes` instead.
        """
        return await metadata.lookup_volume(volume_id, self._access.api_key, plan=self._access.plan)

    def _refuse_if_no_title_search(self) -> None:
        if not self._access.plan.searched_harder:
            raise _refused(NOTHING_ANSWERS_A_TITLE_SEARCH)


@dataclasses.dataclass(frozen=True, slots=True, repr=False)
class GoogleVolumes:
    """Permission to resolve Google volume ids, and nothing else.

    **One door, no keychain, and both of those are the point.** The only outbound
    request behind this type is `metadata.lookup_volume`, whose single target keeps its
    secret in the query string and sends no login. Resolving a keychain for it would be
    a round trip per request for a credential this path cannot send.

    **Why this is a type and not a flag on `Enquiry`.** A keyless object carrying
    `lookup` or `title_search` would be an object whose methods need a login it never
    resolved, and the caller could not tell. Here the methods that need one do not
    exist, so mypy refuses the call rather than a test reporting it afterwards.

    **Its field set is as load bearing as its method set.** A `logins` field added here,
    even unread, restores the round trip this type exists to avoid and makes the next
    reader believe a login is available. Both sets are pinned.

    **An instance means the answer was yes.** `for_a_batch_backfill` refuses when this
    Library does not ask Google, so no code holding one of these has to re-ask.
    """

    _plan: sources.Plan
    _api_key: str = dataclasses.field(repr=False)

    @classmethod
    def for_a_batch_backfill(cls, db: Session, *, member: str) -> Self:
        """Charge the backfill budget, then refuse unless Google Books is asked.

        **Its own limiter rather than the metadata one**, because a batch spends many
        outbound requests per call where a lookup spends a handful, and sharing the
        counter would let one batch exhaust a Member's scanning budget.

        **Refuses rather than reporting a clean run of nothing.** A batch that examined
        no candidates and returned zero would send somebody hunting through their
        library for the cause, when the cause is a switch and a key. That refusal is a
        second reading of a predicate `metadata.lookup_volume` also applies per request,
        and it earns its place by being about the batch: without it every candidate
        comes back `NO_SOURCES` and the reply is an honest looking zero.
        """
        identifier_backfill_limiter.check(member)
        # One resolution for both readers, as `_resolved_access` does.
        state = credentials.key_state()
        plan = settings_store.catalogue_sources(db, state)
        if CatalogueSource.GOOGLE_BOOKS not in plan.asked:
            raise _refused(GOOGLE_BOOKS_IS_NOT_ASKED)
        return cls(_plan=plan, _api_key=settings_store.google_books_api_key(db, state))

    def __str__(self) -> str:
        return f"<google volume access, {len(self._plan.asked)} catalogue(s) asked>"

    async def volume(self, volume_id: str) -> metadata.Lookup:
        """Resolve one Google volume id."""
        return await metadata.lookup_volume(volume_id, self._api_key, plan=self._plan)
