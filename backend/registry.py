"""The curated catalogue registry this build ships, what picking an entry writes,
and the picks a lookup plan asks at its tail.

## Vendored, never fetched

**The registry is a committed snapshot, refreshed by a commit and never at
runtime** (owner, ticket 148). So the hosts this build can reach are still a
list it ships: `fetch.py`'s argument for having no host allowlist, that an
attacker cannot choose the host, becomes "the host comes from a list in the
build" rather than "the host is a module constant", which is a weaker statement
of the same kind. Nothing here opens a connection, so there is no third party
to stay up and no outbound call to make the feature work. A new reachable host
is a diff somebody reads.

## Curated, with evidence per row

The candidates come from the directories whose job this is, `LISTED_BY`, and
**an entry ships only once somebody probed it answering**: each carries the
date, the ISBN asked and the disposition, `Evidence`, and an entry whose
evidence is not `ANSWERED` is refused at import. The probe is `metadata.probe`,
the same call the admin's test action makes, so a reviewer re-runs a row by
asking it again and a curation record and a test result are one shape.

**An ISBN asked is one taken from that catalogue's own record**, because zero
hits is also what a catalogue that indexes the ISBN in a form nobody sends
answers, and the two cannot be told apart from outside.

## Aged, without fetching

`TAKEN_ON` records when the snapshot was curated and `RECHECK_AFTER` how long
its evidence is trusted. `aged` compares the two with a date the caller hands
in, so the build can tell it has aged and say so on the settings screen, and
nothing goes to the network to find out. Re-checking is a release task: probe
every row again, drop what no longer answers, and move `TAKEN_ON`.

## What a pick writes, and what it does not

`pick` adds the entry's `RegisteredCatalogue` name to one settings row,
`SettingKey.PICKED_CATALOGUES`, the way `sources.Plan` is stored. **A name and
never an address**: wherever a picked entry is reached, its `targets.Target`
is the snapshot's, `ENTRIES[...]`, so no table holds a picked host and nothing
reads one back. That keeps the roster table, `catalogue_targets`, what
`tests/test_credentials.py` needs it to be, a copy of `targets.SEEDED` that
nothing reads, until ticket 130 makes a row the source of an address. A
restore or a hand edit can only name a member or be ignored: `picked` keeps
the names this snapshot holds and drops the rest.

**The reader is this project's**, a member of the closed `decoders.Reader` set
named in this file, and never a value a directory supplied. The identity check
travels with it: `requires_isbn_claim` stays true on every entry, which
`targets.Target` refuses to waive anywhere but the DNB.

**A pick is asked on a scan, at the tail of the chain and lookup only.**
`with_picks` hands the picked entries' targets to `sources.Plan.picked`, which
`metadata.lookup` asks one at a time after the chain missed, in this
file's order. Unpicked, or dropped from a later snapshot, an entry is not in
the plan, so it is not asked. A pick is never in the tier asked on every
lookup, never in a title search, and never in a narrowed lookup: nothing
measured where an entry would earn more, which is the rule `docs/decisions.md`
sets for a new catalogue.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from types import MappingProxyType
from typing import Final, Literal

from sqlalchemy.orm import Session

import isbn
import settings_store
import sources
import targets
from decoders import Reader
from enums import CatalogueSource, Disposition, RegisteredCatalogue, SettingKey, Transport

#: The directories the entries were curated from.
#:
#: **Named rather than copied.** IRSpy states it "is made available for
#: evaluation purposes only", so no record of it is vendored here: what an entry
#: carries is an address this project probed and the evidence of that probe,
#: which are facts about a host and this project's own measurement. The Library
#: of Congress page the ticket names, `loc.gov/z3950`, no longer lists targets:
#: its gateway was discontinued, and it names three web catalogues instead.
LISTED_BY: Final = ("https://irspy.indexdata.com/",)

#: When the snapshot was curated: the date of its newest probe.
TAKEN_ON: Final = date(2026, 11, 22)

#: How long a probe is trusted before the snapshot counts as aged.
#:
#: **Half a year, about two release cycles**, so a release cut while the
#: snapshot is fresh carries a probe from inside its own cycle or the one before.
#: Published lists rot fast: of Tellico's thirteen shipped Z39.50 servers, nine
#: had rotted, which `docs/decisions.md` records.
RECHECK_AFTER: Final = timedelta(days=183)


def aged(today: date) -> bool:
    """Whether the snapshot's evidence is older than `RECHECK_AFTER` on `today`."""
    return today - TAKEN_ON > RECHECK_AFTER


@dataclass(frozen=True)
class Evidence:
    """One probe of one catalogue: when, what was asked, and how it answered.

    **The shape the test action returns too**, so a shipped row's record and an
    admin's result are one thing rather than two.
    """

    probed_on: date
    #: Normalised ISBN-13, taken from the catalogue's own record.
    isbn: str
    disposition: Disposition


@dataclass(frozen=True)
class Entry:
    """One catalogue the registry ships."""

    #: The institution's own English name for itself.
    name: str
    #: ISO 3166-1 alpha-2.
    country: str
    #: A national library's catalogue, or a union catalogue of several libraries.
    kind: Literal["national", "union"]
    target: targets.Target
    evidence: Evidence


def _alma(source: RegisteredCatalogue, base_url: str) -> targets.Target:
    """One entry's target: every entry is Alma's SRU server, so one profile.

    The Royal Danish Library's row in `targets.SEEDED` is the same shape, and
    its comments say why each value is what it is.

    **No remit**, `serves_groups` empty: the bar for a non empty one is zero
    misses on the committed sample, and nobody has asked these catalogues that
    question. Too wide costs a round trip; too narrow loses a book silently.

    **Lookup only**, the rule `docs/decisions.md` sets for a new catalogue: a
    search slot waits for somebody to measure what a search there finds.
    """
    return targets.Target(
        source=source,
        # No place in `sources.DEFAULT_ORDER`, so after every seeded row, in this
        # file's order. Nothing reads it at runtime, as on the seeded rows: the
        # order a pick is asked in is `with_picks`'.
        rank=len(targets.SEEDED) + list(RegisteredCatalogue).index(source),
        transport=Transport.SRU,
        timeout_seconds=3.0,
        base_url=base_url,
        reader=Reader.MARC_GND,
        answers_lookup=True,
        answers_search=False,
        metered=False,
        needs_key=False,
        serves_groups=frozenset(),
        sru_version="1.2",
        query_parameter="query",
        query_language=targets.QueryLanguage.CQL,
        record_schema="marcxml",
        isbn_index="alma.isbn",
        lookup_records=5,
        refuses_component_parts=True,
    )


# Each row's evidence is one call of `metadata.probe`, asking an ISBN taken from
# that catalogue's own record, so the admin's test action re-runs it. The
# National Library of Wales, 44WHELF_NLW, was a candidate and is not here: on
# 2026-11-22 no Alma host gave a record of it to probe with.
ENTRIES: Final[Mapping[RegisteredCatalogue, Entry]] = MappingProxyType(
    {
        RegisteredCatalogue.NLS: Entry(
            name="National Library of Scotland",
            country="GB",
            kind="national",
            target=_alma(RegisteredCatalogue.NLS, "https://nls.alma.exlibrisgroup.com/view/sru/44NLS_INST"),
            evidence=Evidence(date(2026, 11, 22), "9781426224393", Disposition.ANSWERED),
        ),
        RegisteredCatalogue.NLI: Entry(
            name="National Library of Israel",
            country="IL",
            kind="national",
            target=_alma(RegisteredCatalogue.NLI, "https://nli.alma.exlibrisgroup.com/view/sru/972NNL_INST"),
            evidence=Evidence(date(2026, 11, 22), "9780971339088", Disposition.ANSWERED),
        ),
        RegisteredCatalogue.CSIC: Entry(
            name="CSIC Library Network",
            country="ES",
            kind="union",
            target=_alma(
                RegisteredCatalogue.CSIC, "https://eu00.alma.exlibrisgroup.com/view/sru/34CSIC_INST"
            ),
            evidence=Evidence(date(2026, 11, 22), "9786612490477", Disposition.ANSWERED),
        ),
    }
)


def _refusals() -> list[str]:
    """Every way the snapshot above breaks the rules this module's docstring states."""
    found: list[str] = []
    if set(ENTRIES) != set(RegisteredCatalogue):
        found.append(f"members and entries differ: {set(RegisteredCatalogue) ^ set(ENTRIES)}")
    clashes = {member.value for member in RegisteredCatalogue} & {member.value for member in CatalogueSource}
    if clashes:
        # The test route coerces a path to `CatalogueSource` first, so a shared
        # value would make the entry unreachable by name, and the credentials
        # store and `sources.Plan` key on the same string.
        found.append(f"spelled like a seeded source: {sorted(clashes)}")
    newest = max((entry.evidence.probed_on for entry in ENTRIES.values()), default=None)
    if newest != TAKEN_ON:
        # `aged` counts from `TAKEN_ON`, so a date later than every probe would
        # let the snapshot read fresh past `RECHECK_AFTER`.
        found.append(f"TAKEN_ON is {TAKEN_ON}, the newest probe {newest}")
    for key, entry in ENTRIES.items():
        found.extend(f"{key}: {problem}" for problem in _entry_refusals(key, entry))
    return found


def _entry_refusals(key: RegisteredCatalogue, entry: Entry) -> list[str]:
    """What is wrong with one entry, against the rules a shipped row must meet."""
    target, evidence = entry.target, entry.evidence
    checks = {
        "keyed under another member": target.source is not key,
        "not probed answering": evidence.disposition is not Disposition.ANSWERED,
        "evidence names no normalised ISBN-13": isbn.parse(evidence.isbn) != evidence.isbn,
        # A web API's adapter is code, and a login is ticket 131's to store.
        "bespoke, metered or credentialled": (
            target.transport is Transport.BESPOKE or target.metered or target.needs_key
        ),
        "answers no lookup, so nothing can test it": not target.answers_lookup,
        "waives the ISBN identity check": not target.requires_isbn_claim,
    }
    return [problem for problem, broken in checks.items() if broken]


if _broken := _refusals():
    raise RuntimeError(f"registry snapshot refused: {_broken}")


def picked(db: Session) -> frozenset[RegisteredCatalogue]:
    """The entries this library has picked.

    **Only names this snapshot holds.** A name a later snapshot dropped, or one
    a restore or a hand edit wrote, is ignored rather than raised on, so the
    settings screen cannot be broken by its own row; a later snapshot restoring
    the entry restores the pick.
    """
    stored = settings_store.get_json(db, SettingKey.PICKED_CATALOGUES).get("picked")
    names = stored if isinstance(stored, list) else []
    return frozenset(member for member in RegisteredCatalogue if member.value in names)


def _store(db: Session, chosen: frozenset[RegisteredCatalogue]) -> None:
    # Sorted, so an unchanged pick writes an unchanged row: `set_json`'s reason.
    names = sorted(member.value for member in chosen)
    settings_store.set_json(db, SettingKey.PICKED_CATALOGUES, {"picked": names})


def pick(db: Session, which: RegisteredCatalogue) -> None:
    """Record the entry as picked. Picking twice is one pick."""
    _store(db, picked(db) | {which})


def drop(db: Session, which: RegisteredCatalogue) -> None:
    """Forget a pick. Dropping one never picked does nothing."""
    _store(db, picked(db) - {which})


def with_picks(db: Session, plan: sources.Plan) -> sources.Plan:
    """`plan` with this library's picks at its tail, in `RegisteredCatalogue` order.

    **The one way a pick reaches a scan**, and `catalogue_access` its one
    caller, so a pick is asked under the same resolved `Access` as every other
    catalogue and nothing else assembles a plan holding one. What replaces
    `plan.picked` is read fresh, so dropping an entry stops it being asked on
    the next request.
    """
    chosen = picked(db)
    asked = tuple(ENTRIES[member].target for member in RegisteredCatalogue if member in chosen)
    return replace(plan, picked=asked)
