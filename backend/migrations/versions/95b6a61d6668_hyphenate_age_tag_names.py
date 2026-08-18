"""Hyphenate the age tag names.

The three age tags shipped with an en dash in their range. House style allows no
dash as punctuation anywhere, so `PREDEFINED_TAGS` now spells them with a plain
hyphen.

The rename has to happen in the database too, and *before* `seed_tags()` runs.
Seeding matches on name, so an unrenamed row would leave the old tag in place and
insert a second one beside it, and every book already tagged with the old name
would keep pointing at the orphan. `ensure_schema()` runs migrations before
seeding, which is what makes that ordering hold.

Data-only: no schema change.

Revision ID: 95b6a61d6668
Revises: a7feb2db74ac
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "95b6a61d6668"
down_revision: str | Sequence[str] | None = "a7feb2db74ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Escaped, so this file contains no literal en dash of its own.
_EN_DASH = "\u2013"

RENAMES: list[tuple[str, str]] = [
    (f"Children (0{_EN_DASH}8)", "Children (0-8)"),
    (f"Middle Grade (8{_EN_DASH}12)", "Middle Grade (8-12)"),
    (f"Young Adult (13{_EN_DASH}18)", "Young Adult (13-18)"),
]

# UPDATE, not delete-and-insert: the tag id is referenced by book_tags, so
# replacing the row would drop every existing assignment.
_RENAME = sa.text("UPDATE tags SET name = :new WHERE name = :old")


def _apply(pairs: list[tuple[str, str]]) -> None:
    connection = op.get_bind()
    for old, new in pairs:
        connection.execute(_RENAME, {"old": old, "new": new})


def upgrade() -> None:
    _apply(RENAMES)


def downgrade() -> None:
    _apply([(new, old) for old, new in RENAMES])
