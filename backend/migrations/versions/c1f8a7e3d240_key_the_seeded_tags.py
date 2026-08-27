"""Give the seeded tags a stable key, so their names can be shown translated.

Revision ID: c1f8a7e3d240
Revises: b8e2f4c7a913
Create Date: 2026-08-27

The predefined vocabulary is seeded in English, so a German household
cataloguing a German book is offered **Computing** for DDC 004. The names are
now shown in the reader's language, and the row a translation belongs to is
found by `tags.key`.

**Why a key and not the name.** Matching a name at display time is the bug
`95b6a61d6668` exists to fix, moved to a later stage: it breaks the moment
somebody renames a tag, and it would put the seeded word back over theirs. A
boolean saying a row *was* seeded cannot pick a translation, because it does not
say which seeded tag the row is. The key survives a rename in either direction.

**So the backfill below is the whole decision.** A row is keyed only where its
name still matches the English seed name **exactly**. A household that renamed
one does not match, keeps a null key, and is an ordinary invented tag from then
on, shown as typed. That is the answer to "a tag I renamed stays renamed", and
it is why this migration writes no name and creates and deletes no row: the
count of `tags` across this upgrade is unchanged.

The names are written out here rather than imported from `main.PREDEFINED_TAGS`,
which is the rule `e7b3d02a5c94` states for `_KEY_MAX`: a migration describes the
schema and the data as they were on the day it ran. Importing today's list would
make a library upgrading in a year backfill against a vocabulary this revision
never saw, and silently key a row whose English name had been changed since.

**The collision check runs before the first DDL statement**, and that placement
is the trap `e7b3d02a5c94` documents rather than a preference. Alembic's SQLite
dialect sets `transactional_ddl = False`, and pysqlite opens a transaction for
**DML only**, where DML means a write: the `SELECT` that reads the names opens
none, so the `ADD COLUMN` below runs with no transaction around it and is
durable the moment it runs. On a database where the backfill then failed, the
column would be there, the keys would not, and `alembic_version` would still
name the previous revision: a state no rerun can apply twice. Checking first
costs nothing, because nothing has been written.

What the check is for: `uq_tags_key` is created at the end, so two rows taking
the same key would fail **after** the column exists. `tags.name` is unique, and
the match is exact, so no such pair can exist and the check is expected to be
dead. It is here because the alternative to a dead check is a half-applied
database, and because a database this old has been through hands as well as
migrations: the name index is the only thing making the claim true, and it costs
one pass over a hundred rows to stop trusting it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1f8a7e3d240"
down_revision: str | Sequence[str] | None = "b8e2f4c7a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Matches `TagKey` in length. A literal, for the reason in the docstring.
_KEY_MAX = 50

#: The English seed name as it stands today, and the key it identifies. The
#: names carry a hyphen in the age ranges since `95b6a61d6668`, so a database
#: that never ran that revision cannot reach this one and no unhyphenated
#: spelling needs to be listed here.
SEEDED: list[tuple[str, str]] = [
    ("Fiction", "fiction"),
    ("Non-Fiction", "non_fiction"),
    ("Reference", "reference"),
    ("Textbook", "textbook"),
    ("Anthology", "anthology"),
    ("Comics", "comics"),
    ("Manga", "manga"),
    ("Play", "play"),
    ("Essays", "essays"),
    ("Picture Book", "picture_book"),
    ("Adventure", "adventure"),
    ("Classic", "classic"),
    ("Contemporary Fiction", "contemporary_fiction"),
    ("Crime", "crime"),
    ("Detective", "detective"),
    ("Dystopian", "dystopian"),
    ("Epic Fantasy", "epic_fantasy"),
    ("Fairy Tales", "fairy_tales"),
    ("Fantasy", "fantasy"),
    ("Folklore", "folklore"),
    ("Gothic", "gothic"),
    ("Graphic Novel", "graphic_novel"),
    ("Historical Fiction", "historical_fiction"),
    ("Horror", "horror"),
    ("Humour", "humour"),
    ("Literary Fiction", "literary_fiction"),
    ("Magical Realism", "magical_realism"),
    ("Mystery", "mystery"),
    ("Mythology", "mythology"),
    ("Noir", "noir"),
    ("Paranormal", "paranormal"),
    ("Poetry", "poetry"),
    ("Post-Apocalyptic", "post_apocalyptic"),
    ("Romance", "romance"),
    ("Satire", "satire"),
    ("Science Fiction", "science_fiction"),
    ("Short Stories", "short_stories"),
    ("Space Opera", "space_opera"),
    ("Speculative Fiction", "speculative_fiction"),
    ("Spy Fiction", "spy_fiction"),
    ("Steampunk", "steampunk"),
    ("Suspense", "suspense"),
    ("Thriller", "thriller"),
    ("Urban Fantasy", "urban_fantasy"),
    ("War", "war"),
    ("Western", "western"),
    ("Anthropology", "anthropology"),
    ("Archaeology", "archaeology"),
    ("Architecture", "architecture"),
    ("Art", "art"),
    ("Astronomy", "astronomy"),
    ("Autobiography", "autobiography"),
    ("Biography", "biography"),
    ("Biology", "biology"),
    ("Business", "business"),
    ("Chemistry", "chemistry"),
    ("Computing", "computing"),
    ("Cooking", "cooking"),
    ("Design", "design"),
    ("Diaries and Letters", "diaries_and_letters"),
    ("Economics", "economics"),
    ("Education", "education"),
    ("Environment", "environment"),
    ("Ethics", "ethics"),
    ("Feminism", "feminism"),
    ("Film and TV", "film_and_tv"),
    ("Finance", "finance"),
    ("Gardening", "gardening"),
    ("Geography", "geography"),
    ("Health and Fitness", "health_and_fitness"),
    ("History", "history"),
    ("Journalism", "journalism"),
    ("Language", "language"),
    ("Law", "law"),
    ("Linguistics", "linguistics"),
    ("Mathematics", "mathematics"),
    ("Medicine", "medicine"),
    ("Memoir", "memoir"),
    ("Music", "music"),
    ("Nature", "nature"),
    ("Parenting", "parenting"),
    ("Philosophy", "philosophy"),
    ("Photography", "photography"),
    ("Physics", "physics"),
    ("Politics", "politics"),
    ("Popular Science", "popular_science"),
    ("Psychology", "psychology"),
    ("Religion", "religion"),
    ("Science", "science"),
    ("Self-Help", "self_help"),
    ("Sociology", "sociology"),
    ("Sports", "sports"),
    ("Technology", "technology"),
    ("Theatre", "theatre"),
    ("Travel", "travel"),
    ("True Crime", "true_crime"),
    ("Urbanism", "urbanism"),
    ("Wine and Drink", "wine_and_drink"),
    ("Baby and Toddler (0-3)", "baby_and_toddler"),
    ("Children (0-8)", "children"),
    ("Early Reader (5-8)", "early_reader"),
    ("Middle Grade (8-12)", "middle_grade"),
    ("Young Adult (13-18)", "young_adult"),
    ("New Adult (18-25)", "new_adult"),
    ("Adult", "adult"),
]


def upgrade() -> None:
    connection = op.get_bind()

    keys_by_name = dict(SEEDED)
    rows = connection.execute(sa.text("SELECT id, name FROM tags ORDER BY id")).all()
    keyed = [
        {"row_id": row_id, "key": keys_by_name[name]}
        for row_id, name in rows
        if name in keys_by_name
    ]

    # Before any DDL, on purpose: see the module docstring.
    taken: dict[str, int] = {}
    for row in keyed:
        first = taken.setdefault(str(row["key"]), int(row["row_id"]))
        if first != row["row_id"]:
            raise RuntimeError(
                f"tags {first} and {row['row_id']} both claim the key "
                f"{row['key']!r}. Revision c1f8a7e3d240 has been stopped and "
                "nothing was changed. Leave one of them under its seeded name, "
                "rename the other, and upgrade again."
            )

    op.add_column("tags", sa.Column("key", sa.String(length=_KEY_MAX), nullable=True))

    if keyed:
        connection.execute(
            sa.text("UPDATE tags SET key = :key WHERE id = :row_id"), keyed
        )

    # After the backfill, so that a backfill which somehow produced a duplicate
    # fails here rather than shipping one. Multiple NULLs are permitted by a
    # SQLite unique index, which is what lets every invented tag, and every
    # seeded row a household renamed, coexist unkeyed.
    op.create_index("uq_tags_key", "tags", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_tags_key", table_name="tags")

    # Batch mode, which `render_as_batch=True` in `migrations/env.py` turns
    # every ALTER here into. Nothing is lost that this revision did not derive:
    # a re-upgrade recomputes each key from the name it matched.
    with op.batch_alter_table("tags") as batch:
        batch.drop_column("key")
