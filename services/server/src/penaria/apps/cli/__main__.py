"""``python -m penaria.apps.cli users reset <username>``: the operator's tools.

``users reset`` prints a one-time link that sets a new password for the account, valid for 24 hours:
for the owner who is locked out and has no one to make a link for them (sign-in.md, 8). With
``--disable-second-factor`` it also turns the account's authenticator app off, for a person who lost
it and its recovery codes. Access to the server is access to the house.
"""

import argparse
import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator

from pydantic import ValidationError
from servicewright import ServiceError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.apps.cli.settings import Settings
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.use_cases.recovery import CreateOperatorResetLink
from penaria.features.support.identity.use_cases.totp import TurnOffTotpByOperator
from penaria.integrations.postgres.transaction import PenariaTransaction


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m penaria.apps.cli", description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)
    users = groups.add_parser("users", help="accounts")
    commands = users.add_subparsers(dest="command", required=True)
    reset = commands.add_parser("reset", help="print a one-time link that sets a new password for the account")
    reset.add_argument("username")
    reset.add_argument(
        "--disable-second-factor",
        action="store_true",
        help="also turn off the account's authenticator app, for a person who lost it and its recovery codes",
    )
    return parser.parse_args(argv)


async def reset(settings: Settings, args: argparse.Namespace) -> str:
    """What ``users reset`` prints."""
    message = await reset_password(settings, args.username)
    if args.disable_second_factor:
        message += await disable_second_factor(settings, args.username)
    return message


async def reset_password(settings: Settings, username: str) -> str:
    """The reset link of the account, and what to do with it, to print."""
    async with _unit_of_work(settings) as uow:
        link = await CreateOperatorResetLink(uow, PublicLinks(origin=settings.public_origin)).execute(username)
    return (
        f"Open this link to set a new password for {link.user.username}; it works once, "
        f"until {link.expires_at:%Y-%m-%d %H:%M} UTC:\n{link.url}\n"
        "Every session of the account ends; its passkeys keep working."
    )


async def disable_second_factor(settings: Settings, username: str) -> str:
    """Turn the account's authenticator app off; what to print about it."""
    async with _unit_of_work(settings) as uow:
        turned_off = await TurnOffTotpByOperator(uow).execute(username)
    if not turned_off:
        return "\nThe account had no authenticator app to turn off.\n"
    return (
        "\nIts authenticator app is turned off, and its recovery codes no longer work: signing in with the new "
        "password asks for no code. An owner or an install admin is asked to add a second factor again.\n"
    )


@contextlib.asynccontextmanager
async def _unit_of_work(settings: Settings) -> AsyncIterator[AsyncSQLAlchemyUnitOfWork[PenariaTransaction]]:
    engine = create_async_engine(settings.database.to_dsn(), poolclass=NullPool)
    try:
        yield AsyncSQLAlchemyUnitOfWork(
            async_sessionmaker(engine, expire_on_commit=False), transaction_factory=PenariaTransaction
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.exit(f"error: the PENARIA_* environment is not valid:\n{exc}")
    try:
        # The only command so far: users reset.
        message = asyncio.run(reset(settings, args))
    except ServiceError as exc:
        sys.exit(f"error: {exc}")
    print(message)  # noqa: T201 - the link is the command's output


if __name__ == "__main__":
    main()
