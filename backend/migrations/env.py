"""Alembic environment.

Deliberately reads the database URL from the app's own `config` module rather
than from `alembic.ini`, so a migration always runs against the same database
the app would open. Putting a URL in the ini file would be a second source of
truth, and the one people forget to change.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing models registers every table on Base.metadata, which is what
# `--autogenerate` compares the live database against.
import models  # noqa: F401
from config import database_url
from database import Base

config = context.config
config.set_main_option("sqlalchemy.url", database_url())

# fileConfig() REPLACES the process's logging configuration. That is what you
# want from `alembic upgrade` on a terminal, and emphatically not what you want
# when the app runs migrations during startup: it silently tears down the
# handlers the application just installed, and log output stops.
#
# schema.py sets this attribute to say "I am driving you, leave logging alone".
_configure_logging = config.attributes.get("configure_logger", True)
if _configure_logging and config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade --sql`)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table around the change instead of failing.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
