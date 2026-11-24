"""``python -m penaria.apps.cli users reset <username>``: the operator's tools.

``users reset`` prints a one-time link that sets a new password for the account, valid for 24 hours:
for the owner who is locked out and has no one to make a link for them (sign-in.md, 8). Access to the
server is access to the house.
"""

import argparse
import asyncio
import sys

from servicewright import ServiceError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.apps.cli.settings import Settings
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.use_cases.recovery import CreateOperatorResetLink
from penaria.integrations.postgres.transaction import PenariaTransaction


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m penaria.apps.cli", description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)
    users = groups.add_parser("users", help="accounts")
    commands = users.add_subparsers(dest="command", required=True)
    reset = commands.add_parser("reset", help="print a one-time link that sets a new password for the account")
    reset.add_argument("username")
    return parser.parse_args(argv)


async def reset_password(settings: Settings, username: str) -> str:
    """The reset link of the account, and what to do with it, to print."""
    engine = create_async_engine(settings.database.to_dsn(), poolclass=NullPool)
    try:
        uow = AsyncSQLAlchemyUnitOfWork(
            async_sessionmaker(engine, expire_on_commit=False), transaction_factory=PenariaTransaction
        )
        link = await CreateOperatorResetLink(uow, PublicLinks(origin=settings.public_origin)).execute(username)
    finally:
        await engine.dispose()
    return (
        f"Open this link to set a new password for {link.user.username}; it works once, "
        f"until {link.expires_at:%Y-%m-%d %H:%M} UTC:\n{link.url}\n"
        "Every session of the account ends; its passkeys keep working."
    )


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    try:
        # The only command so far: users reset.
        message = asyncio.run(reset_password(Settings(), args.username))
    except ServiceError as exc:
        sys.exit(f"error: {exc}")
    print(message)  # noqa: T201 - the link is the command's output


if __name__ == "__main__":
    main()
