"""The classification schemes a library's headings may quote, as rows.

**Classification schemes are rows and authority schemes stay code**, which is
the owner's split: UDC exists whether or not this app knows it, while an
authority scheme needs a reader, so a row naming one would lie
(`enums.AuthorityScheme`). `models.ClassificationSchemeRow` lists what a row
costs that an enum did not, and where each answer lives.

**Four rows are built in, and code reads them.** `BUILT_IN` seeds them; this
module refuses to rename, refile or delete one, and `backup.restore` puts them
back as seeded. The rest are a library's own, and their rule is fixed at
definition because every stored key was computed under it (`filing.py`).

**Deleting a scheme that books still quote is refused, naming how many**
(owner, 2026-11-19). The foreign key refuses it; this module counts.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import filing
from enums import ClassificationScheme, FilingRuleName
from models import CLASSIFICATION_SCHEME_NAME_MAX, ClassificationSchemeRow, forget_filing_rules


@dataclass(frozen=True, slots=True)
class BuiltIn:
    """What a built in scheme's row is seeded with, and locked to."""

    name: str
    filing: FilingRuleName


#: The rows code names, in `ClassificationScheme`'s order.
#:
#: **The seed, and the lock.** Migration `8cfb39d1d900` wrote these rows from a
#: frozen copy, `tests/test_schema.py` holds the two equal, and nothing here
#: lets a built in row move away from them, so code reading one of these
#: schemes reads what the row says.
BUILT_IN: Final[Mapping[ClassificationScheme, BuiltIn]] = {
    ClassificationScheme.DDC: BuiltIn("Dewey Decimal Classification", FilingRuleName.DEWEY),
    ClassificationScheme.LCC: BuiltIn("Library of Congress Classification", FilingRuleName.LCC),
    ClassificationScheme.GND: BuiltIn("GND", FilingRuleName.GENERIC),
    ClassificationScheme.LCSH: BuiltIn("Library of Congress Subject Headings", FilingRuleName.GENERIC),
}

#: The built in schemes a shelf may be ordered by, derived from their rules.
#:
#: Only built in ones, because `BookSort` is the API's closed vocabulary and
#: names no scheme a library added. `shelf._SHELF_SORTS` pairs each with the
#: `BookSort` value that asks for it, and `tests/test_shelf.py` pins that the
#: two cover each other.
SHELF_SCHEMES: Final[tuple[ClassificationScheme, ...]] = tuple(
    scheme for scheme, seed in BUILT_IN.items() if filing.FILING_RULES[seed.filing].orders_a_shelf
)


class Refused(Exception):
    """A change to the schemes that is not allowed, worded for the member."""


class StillQuoted(Refused):
    """A delete refused because headings quote the scheme.

    `count` is how many books the caller may see quote it, 0 where only books
    hidden from them do; `remove` says why it counts only those. Carried apart
    from the sentence so a client can word it in the reader's language.
    """

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(_still_quoted_sentence(count))


def is_built_in(code: str) -> bool:
    """Whether code names this scheme, which locks its row."""
    return code in BUILT_IN


def seed_rows() -> list[dict[str, str]]:
    """The built in rows, as a Core insert takes them."""
    return [
        {"code": scheme.value, "name": seed.name, "filing": seed.filing.value}
        for scheme, seed in BUILT_IN.items()
    ]


def listing(db: Session) -> list[ClassificationSchemeRow]:
    """Every scheme: the built in four in their order, then the library's own by name."""
    rows = db.scalars(select(ClassificationSchemeRow)).all()
    order = {scheme.value: index for index, scheme in enumerate(BUILT_IN)}
    return sorted(rows, key=lambda row: (order.get(row.code, len(order)), row.name.casefold(), row.code))


def define(db: Session, code: str, name: str, rule: FilingRuleName) -> ClassificationSchemeRow:
    """Add a scheme. Its code and its filing rule are fixed from here on.

    **A code already taken is refused rather than handed back**, unlike
    `custom_fields.define`: the existing row may file under another rule, and
    returning it would tell the member their rule was taken when it was not.
    """
    if db.get(ClassificationSchemeRow, code) is not None:
        raise Refused(f"A scheme with the code {code!r} already exists.")
    row = ClassificationSchemeRow(code=code, name=name, filing=rule)
    db.add(row)
    db.flush()
    forget_filing_rules(db)
    return row


def rename(db: Session, row: ClassificationSchemeRow, name: str) -> ClassificationSchemeRow:
    """Give a library's own scheme a new name. Its code and rule stay."""
    _refuse_a_built_in(row)
    row.name = name
    return row


def remove(db: Session, row: ClassificationSchemeRow, viewer_id: int) -> None:
    """Delete a scheme no heading quotes, or refuse naming how many books do.

    **The foreign key decides, and this only counts**, so a heading written
    between a count and the delete cannot slip past: the delete runs in a
    savepoint and `fk_classifications_scheme` refuses it there.

    **The count is of the books the caller may see, in the shelf and in the
    trash**, through `shelf.Shelf` like every count of books, and the refusal
    says so: "N books you can see" (owner, 2026-11-20). A heading on another
    member's private book still blocks the delete, and where only such books
    quote the scheme the refusal gives no number: refusing at all already
    tells the caller that some book quotes it, and a count would say how many
    of somebody else's private books do.
    """
    _refuse_a_built_in(row)
    code = row.code
    try:
        with db.begin_nested():
            db.delete(row)
            db.flush()
    except IntegrityError:
        raise StillQuoted(_visible_quoting(db, code, viewer_id)) from None
    forget_filing_rules(db)


def _visible_quoting(db: Session, code: str, viewer_id: int) -> int:
    """How many books the caller may see, shelved or trashed, quote `code`.

    `shelf` is imported here because it imports this module for
    `SHELF_SCHEMES`, so a module level import would be a cycle.
    """
    from shelf import Shelf

    return (
        Shelf.seen_by(db, viewer_id).classified_under(code).count()
        + Shelf.trashed_by(db, viewer_id).classified_under(code).count()
    )


def _still_quoted_sentence(count: int) -> str:
    """The refusal in English, worded as the count it is: the books the caller can see."""
    if count == 0:
        return "Books you cannot see still use this scheme, so it cannot be deleted."
    books = "book you can see still uses" if count == 1 else "books you can see still use"
    return f"{count} {books} this scheme, so it cannot be deleted."


def _refuse_a_built_in(row: ClassificationSchemeRow) -> None:
    """Refuse a change to a row code reads; see `BUILT_IN`."""
    if is_built_in(row.code):
        raise Refused("This scheme is built in, so it cannot be renamed or deleted.")


def restorable(schemes: Iterable[dict[str, Any]], headings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The scheme rows a restore inserts: the archive's, completed.

    **The built in rows as seeded, whatever the archive says**, since code
    reads them, and an archive taken before this table existed carries none.

    **A row for every code a restored heading quotes and no scheme row
    names**, named after its code and filed as text, the rule migration
    `8cfb39d1d900` applied to a database being upgraded. Without it the
    foreign key refuses the whole restore over one heading, which is the
    failed restore a scheme the app could not name used to cost a listing.
    """
    rows: dict[str, dict[str, Any]] = {
        row["code"]: {**row, "name": _known_name(row), "filing": _known_rule(row.get("filing"))}
        for row in schemes
        if isinstance(row.get("code"), str)
    }
    for seeded in seed_rows():
        rows[seeded["code"]] = seeded
    for heading in headings:
        code = heading.get("scheme")
        if isinstance(code, str) and code not in rows:
            rows[code] = {"code": code, "name": code, "filing": FilingRuleName.GENERIC.value}
    return list(rows.values())


def _known_name(row: dict[str, Any]) -> str:
    """A restored `name`, or the code where it is missing, blank or not text,
    clipped to the column.

    Degraded rather than refused, as `_known_rule` is: a hand edited archive
    would otherwise fail the whole restore on NOT NULL, or on PostgreSQL's
    `String(80)`, as an error the route does not turn into a 400.
    """
    name = row.get("name")
    text = name.strip() if isinstance(name, str) else ""
    return (text or row["code"])[:CLASSIFICATION_SCHEME_NAME_MAX]


def _known_rule(value: object) -> str:
    """A restored `filing` value, or the generic rule where it names none.

    Degraded rather than refused, the way `filing.rule_named` reads one: an
    archive edited by hand should not fail a whole restore on
    `ck_classification_schemes_filing`.
    """
    return filing.rule_named(value).name
