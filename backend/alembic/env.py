from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from novel_system.db.base import Base
from novel_system.db import models  # noqa: F401
from novel_system.settings import get_settings

config = context.config

if config.config_file_name is not None:
    # Alembic is also invoked in-process by maintenance tools and tests.  The
    # logging module's default would disable every already-imported application
    # logger that is absent from alembic.ini, silently removing later audit
    # events from the host process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if str(config.get_main_option("sqlalchemy.url")).startswith("sqlite"):
        # SQLite table-rebuild migrations need FK enforcement disabled on their
        # dedicated connection. Runtime application connections use the opposite
        # fail-closed default in db/session.py. Post-migration preflight performs a
        # full PRAGMA foreign_key_check before the database is considered ready.
        @event.listens_for(connectable, "connect")
        def configure_sqlite_migration_connection(
            dbapi_connection,
            _connection_record,
        ) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=OFF")
                cursor.execute("PRAGMA foreign_keys")
                row = cursor.fetchone()
                if row is None or int(row[0]) != 0:
                    raise RuntimeError("sqlite_migration_foreign_keys_not_disabled")
            finally:
                cursor.close()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
