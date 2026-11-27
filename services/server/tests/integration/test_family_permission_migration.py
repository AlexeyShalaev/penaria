"""The data migration that gives the family role of the homes there are "See receipts and warranties"."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from penaria.migrations.runner import build_config, run_with_connection

pytestmark = pytest.mark.integration

# The revision before the data migration.
BEFORE = "465614bbd3ff"
HOME = "01900000-0000-7000-8000-0000000000aa"


async def test_existing_family_roles_get_the_permission_once(migrated_database: None, test_database_url: str) -> None:
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        await run_with_connection(engine, build_config(), lambda config: command.downgrade(config, BEFORE))
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO identity_homes (id, name, timezone, locale) VALUES (:id, 'Flat', 'UTC', 'en')"),
                {"id": HOME},
            )
            await connection.execute(
                text(
                    "INSERT INTO identity_roles (id, home_id, preset, permissions) VALUES"
                    " (gen_random_uuid(), :home, 'family', ARRAY['entities.view', 'entities.edit']),"
                    " (gen_random_uuid(), :home, 'contractor', ARRAY['entities.view'])"
                ),
                {"home": HOME},
            )
        await run_with_connection(engine, build_config(), lambda config: command.upgrade(config, "head"))
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT preset, permissions FROM identity_roles WHERE home_id = :home ORDER BY preset"),
                {"home": HOME},
            )
            found = [(preset, permissions) for preset, permissions in rows]
    finally:
        await engine.dispose()

    assert found == [
        ("contractor", ["entities.view"]),
        ("family", ["entities.view", "entities.edit", "documents.view_financial"]),
    ]
