"""Bringing the database up to date at startup.

Schema changes used to be hand-written `ALTER TABLE`s in `migrate_schema()`,
with a note in the docs saying to adopt Alembic before adding a third. This is
that adoption.

The tricky part is not new installations, it is the ones already running. Three
cases have to work:

1. **Empty database.** Every revision runs; the baseline creates the tables.
2. **Created before Alembic existed.** Tables are there but there is no
   `alembic_version`. Running the baseline would try to create tables that
   already exist, and stamping blindly would assume a shape the database may
   not have. So the two legacy fixups are applied first (they are idempotent),
   which brings any older database to exactly the baseline shape, and only then
   is it stamped and upgraded.
3. **Already managed by Alembic.** Straight upgrade to head.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from database import engine

logger = logging.getLogger("endpaper.schema")

_BACKEND_DIR = Path(__file__).resolve().parent
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

# The first revision. A pre-Alembic database is stamped here, because the
# legacy fixups below leave it in exactly this shape.
BASELINE_REVISION = "6ac5f778dadb"

# Tables that existed before Alembic. Their presence is how a pre-Alembic
# database is recognised.
_LEGACY_TABLES = {"books", "users", "tags", "loans", "notes", "user_books"}


def _alembic_config() -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    # Alembic's env.py calls fileConfig(), which REPLACES the process-wide
    # logging configuration. Harmless from the CLI, destructive at startup: it
    # would tear down the handlers the app just installed and log output would
    # stop. env.py honours this flag.
    config.attributes["configure_logger"] = False
    return config


def _current_revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def apply_legacy_fixups() -> None:
    """The two hand-written steps that predate Alembic.

    Kept, rather than folded into a revision, because they have to run against
    databases that Alembic has never seen. Both are idempotent, so running them
    on an already-correct database does nothing.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "books" in tables:
        columns = {column["name"] for column in inspector.get_columns("books")}
        if "is_private" not in columns:
            logger.info("legacy fixup: adding books.is_private")
            with engine.connect() as connection:
                connection.execute(
                    text("ALTER TABLE books ADD COLUMN is_private BOOLEAN NOT NULL DEFAULT 0")
                )
                connection.commit()

    if "user_books" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("user_books")}
        if "uq_user_books_user_book" not in indexes:
            logger.info("legacy fixup: de-duplicating and indexing user_books")
            with engine.connect() as connection:
                # Nothing prevented duplicate (user, book) rows before, and the
                # unique index would fail if any remain. Keep the most recent,
                # which is the status the member last chose.
                connection.execute(
                    text(
                        "DELETE FROM user_books WHERE id NOT IN "
                        "(SELECT MAX(id) FROM user_books GROUP BY user_id, book_id)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX uq_user_books_user_book "
                        "ON user_books (user_id, book_id)"
                    )
                )
                connection.commit()


def upgrade_to(revision: str) -> None:
    """Apply migrations up to `revision`. Safe to call on every boot.

    `revision` is normally "head". Naming an explicit one is useful in tests
    that need to reconstruct a historical schema.
    """
    config = _alembic_config()

    if _current_revision() is None:
        existing = set(inspect(engine).get_table_names())
        if _LEGACY_TABLES & existing:
            # Case 2: a database from before Alembic. Bring it to the baseline
            # shape, then tell Alembic that is where it stands.
            logger.info("Adopting an existing pre-Alembic database")
            apply_legacy_fixups()
            command.stamp(config, BASELINE_REVISION)

    command.upgrade(config, revision)
    logger.info("Database schema at %s", _current_revision())


def upgrade_to_head() -> None:
    upgrade_to("head")
