"""Builds the Alembic configuration and runs Alembic commands on a connection of ours."""

from collections.abc import Callable

from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

# Revision files sort by creation time: 2026_11_24_1530-<rev>_<slug>.py
FILE_TEMPLATE = "%%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s"


def build_config() -> Config:
    """The Alembic configuration, without an ``alembic.ini``: the image ships none."""
    config = Config()
    config.set_main_option("script_location", "penaria:migrations")
    config.set_main_option("file_template", FILE_TEMPLATE)
    return config


async def run_with_connection(engine: AsyncEngine, config: Config, command: Callable[[Config], object]) -> None:
    """Run an Alembic ``command`` in one transaction of ``engine``, committed when it returns."""

    def run(connection: Connection) -> None:
        config.attributes["connection"] = connection
        try:
            command(config)
        finally:
            config.attributes.pop("connection", None)

    async with engine.begin() as connection:
        await connection.run_sync(run)
