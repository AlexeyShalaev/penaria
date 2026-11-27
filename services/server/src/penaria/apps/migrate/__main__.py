"""``python -m penaria.apps.migrate [upgrade|downgrade|current|revision|check]``.

Every install runs ``upgrade`` before a new version of the other processes starts: the
all-in-one Compose file as a one-off service, Kubernetes as a pre-upgrade hook. With storage
set up, ``upgrade`` also creates its bucket when there is none.
"""

import argparse
import asyncio
import logging
from collections.abc import Callable
from functools import partial

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from penaria.apps.migrate.settings import Settings
from penaria.integrations.s3.settings import S3Settings
from penaria.integrations.s3.storage import open_s3
from penaria.migrations.runner import build_config, run_with_connection

logger = logging.getLogger(__name__)


def parse_command(argv: list[str] | None = None) -> Callable[[Config], object]:
    parser = argparse.ArgumentParser(prog="python -m penaria.apps.migrate", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    upgrade = commands.add_parser("upgrade", help="apply migrations up to a revision (head by default)")
    upgrade.add_argument("revision", nargs="?", default="head")
    downgrade = commands.add_parser("downgrade", help="roll back to a revision, such as -1")
    downgrade.add_argument("revision")
    commands.add_parser("current", help="print the revision the database is at")
    revision = commands.add_parser("revision", help="write a new migration from the difference with the models")
    revision.add_argument("-m", "--message", required=True)
    revision.add_argument("--empty", action="store_true", help="an empty migration instead of autogenerate")
    commands.add_parser("check", help="fail if the models differ from the migrations")
    args = parser.parse_args(argv)

    match args.command:
        case "upgrade":
            return partial(command.upgrade, revision=args.revision)
        case "downgrade":
            return partial(command.downgrade, revision=args.revision)
        case "current":
            return command.current
        case "revision":
            return partial(command.revision, message=args.message, autogenerate=not args.empty)
        case "check":
            return command.check
        case _:
            raise AssertionError(args.command)


async def run(settings: Settings, alembic_command: Callable[[Config], object]) -> None:
    engine = create_async_engine(settings.database.to_dsn(), poolclass=NullPool)
    try:
        await run_with_connection(engine, build_config(), alembic_command)
    finally:
        await engine.dispose()


async def ensure_bucket(settings: S3Settings) -> None:
    async with open_s3(settings) as storage:
        if await storage.ensure_bucket():
            logger.info("Created the bucket %s", settings.bucket)


def main() -> None:
    alembic_command = parse_command()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    asyncio.run(run(settings, alembic_command))
    if settings.s3 is not None and _upgrades(alembic_command):
        asyncio.run(ensure_bucket(settings.s3))


def _upgrades(alembic_command: Callable[[Config], object]) -> bool:
    return isinstance(alembic_command, partial) and alembic_command.func is command.upgrade


if __name__ == "__main__":
    main()
