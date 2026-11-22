"""Classification schemes become rows

Revision ID: 8cfb39d1d900
Revises: 205abd150aeb
Create Date: 2026-11-20

`classification_schemes` holds one row per scheme a heading may quote, and
`classifications.scheme` becomes a foreign key into it. `models.
ClassificationSchemeRow` says what the change buys and what it costs.

**The code is the primary key, and it is the value the column already holds**,
so the foreign key lands on the existing column and no heading is rewritten.

**A row for every scheme already stored, not only the four seeded ones.**
`classifications.scheme` carried no constraint before this, and
`backup.restore` inserts through Core, so a database may hold a heading under
`udc`. Refusing the upgrade over it would strand that library on the old
version, and dropping the heading would lose a catalogue's assertion. So each
such code gets a row named after itself, filed as text, which is the column's
default: what a library would have typed for it.

**Frozen rather than imported.** The four seeded rows are written out here, and
`tests/test_schema.py` holds them to `classification_schemes.BUILT_IN`, so a
later edit to that table cannot rewrite what this revision did.

No refusal check runs here, so nothing has to precede the DDL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8cfb39d1d900"
down_revision: str | Sequence[str] | None = "205abd150aeb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMES = sa.table(
    "classification_schemes",
    sa.column("code", sa.String()),
    sa.column("name", sa.String()),
    sa.column("filing", sa.String()),
)

#: The four rows code names, as `classification_schemes.BUILT_IN` held them.
_SEEDED: tuple[tuple[str, str, str], ...] = (
    ("ddc", "Dewey Decimal Classification", "dewey"),
    ("lcc", "Library of Congress Classification", "lcc"),
    ("gnd", "GND", "generic"),
    ("lcsh", "Library of Congress Subject Headings", "generic"),
)


def upgrade() -> None:
    op.create_table(
        "classification_schemes",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("filing", sa.String(length=20), server_default="generic", nullable=False),
        sa.CheckConstraint("filing IN ('generic', 'dewey', 'lcc')", name="ck_classification_schemes_filing"),
        sa.PrimaryKeyConstraint("code"),
    )
    seeded = {code for code, _name, _filing in _SEEDED}
    stored = op.get_bind().execute(sa.text("SELECT DISTINCT scheme FROM classifications")).scalars().all()
    rows = [{"code": code, "name": name, "filing": filing} for code, name, filing in _SEEDED]
    rows += [{"code": code, "name": code, "filing": "generic"} for code in sorted(set(stored) - seeded)]
    op.bulk_insert(_SCHEMES, rows)
    with op.batch_alter_table("classifications") as batch:
        batch.create_foreign_key(
            "fk_classifications_scheme",
            "classification_schemes",
            ["scheme"],
            ["code"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("classifications") as batch:
        batch.drop_constraint("fk_classifications_scheme", type_="foreignkey")
    op.drop_table("classification_schemes")
