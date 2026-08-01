"""Alembic environment: resolves the database URL from AppConfig at runtime.

Rather than hand-editing ``alembic.ini`` on every machine, the actual
SQLite path always comes from :func:`app.config.get_config` (which in
turn respects ``HOS_DATA_DIR``), so migrations run against the same
database the application itself would open.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the repository root importable so `import app...` works when
# Alembic is invoked as `alembic <command>` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.core.models  # noqa: F401  registers every model on Base.metadata
from app.config import get_config
from app.core.db.base import Base
from app.core.db.engine import register_sqlite_pragma

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

app_config = get_config()
app_config.ensure_runtime_dirs()
config.set_main_option("sqlalchemy.url", f"sqlite:///{app_config.db_path}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without a live DB connection (``alembic ... --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection.

    ``render_as_batch=True`` is required for SQLite: it can't ALTER
    TABLE most column changes in place, so Alembic instead recreates
    the table under the hood when a migration needs that.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    register_sqlite_pragma(connectable)

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
