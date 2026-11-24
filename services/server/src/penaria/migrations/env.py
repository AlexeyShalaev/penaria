"""Alembic environment: runs on a connection handed in through ``config.attributes``.

``python -m penaria.apps.migrate`` and the migration tests open the connection; a bare
``alembic`` command has none and stops with a hint.
"""

from alembic import context
from sqlalchemy import Connection, text

from penaria.migrations.models import metadata

# Any constant works; it only has to be the same in every process that migrates.
MIGRATION_LOCK_KEY = 0x50454E41  # "PENA"


def run_migrations_online() -> None:
    connection: Connection | None = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("run migrations through `python -m penaria.apps.migrate`, not the alembic command")
    target_schema: str | None = context.config.attributes.get("target_schema")
    if target_schema:
        # The migration tests run every test in a schema of their own; extensions stay in public.
        quoted = connection.dialect.identifier_preparer.quote_schema(target_schema)
        connection.execute(text(f"SET search_path TO {quoted}, public"))
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema=target_schema,
        compare_type=True,
    )
    with context.begin_transaction():
        # Two replicas starting at once must not migrate concurrently.
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("offline (SQL script) migrations are not supported")
run_migrations_online()
