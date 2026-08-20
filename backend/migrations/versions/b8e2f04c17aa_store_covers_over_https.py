"""Store covers a browser will load.

Revision ID: b8e2f04c17aa
Revises: d5c31b7a09fe

Google Books returns `imageLinks.thumbnail` over plain http. An http image on
an https page is mixed content: the browser blocks it whatever the CSP says, so
the book carries a cover that is correct in the database and invisible in the
app, with nothing anywhere saying why.

New writes are upgraded on the column itself (`Book._store_covers_over_https`),
but that fires on a write and these rows are not going to be written again. Any
deployment that enriched a book from Google before today is holding one, and it
would stay broken for good.

A locally uploaded cover is a relative `/covers/1.jpg` and is left alone.

**The second statement follows the same argument to its end.** A row nobody
writes again stays as it is forever, which is the whole reason the first
statement exists, and that applies identically to a legacy `data:`,
`javascript:` or `//host` value: `covers.is_renderable` refuses those on every
new write, but nothing rewrites an old row to find out. Leaving them would mean
the http case earned a data step and the case with an actual security argument
did not. `data:` in particular is still listed in `img-src`, so such a row does
not merely fail to load, it renders whatever it carries.

Nulled rather than repaired, because there is nothing to repair them to. A book
loses a cover it never successfully showed, and the next metadata refresh
offers a real one.

The match is kept identical to `covers.is_renderable`: the scheme
case-insensitively, the local prefix exactly, and no `..` in a local path.

The downgrade is deliberately empty: nothing here records which rows arrived as
http or what was dropped, and putting a scheme back that the browser refuses to
load would be a migration whose whole effect is to break covers.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e2f04c17aa"
down_revision: str | None = "d5c31b7a09fe"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Upgrade first, then judge the result: the other order would discard every
    # http cover instead of fixing it. Same order as `covers.storable`.
    op.execute(
        sa.text(
            """
            UPDATE books
               SET cover_url = 'https://' || substr(cover_url, 8)
             WHERE lower(substr(cover_url, 1, 7)) = 'http://'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE books
               SET cover_url = NULL
             WHERE cover_url IS NOT NULL
               AND lower(substr(cover_url, 1, 8)) <> 'https://'
               AND NOT (
                     substr(cover_url, 1, 8) = '/covers/'
                 AND instr(cover_url, '..') = 0
               )
            """
        )
    )


def downgrade() -> None:
    """Nothing to undo. See the module docstring."""
