"""Counting attempts that check a secret, so guessing is slowed down (sign-in.md, 7).

An attempt is counted as failed before the secret is checked, in a short transaction of its own,
so parallel guesses cannot all pass the check while the slow password hash runs, and no
transaction stays open during it. A successful attempt takes its count back.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from servicewright import ServiceError
from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client
from penaria.features.support.identity.domain.throttle import (
    FAILURES_EXPIRE_AFTER,
    check_not_blocked,
    secret_link_key,
)


async def count_attempt(tx: IdentityTransaction, keys: Sequence[str], now: datetime) -> None:
    """Refuse the attempt while any of its keys must wait; otherwise count it as failed under each key."""
    await tx.failures.lock(keys)
    check_not_blocked(await tx.failures.get(keys), now)
    forget_before = now - FAILURES_EXPIRE_AFTER
    # Counters nobody failed under for long go, so typed usernames do not pile up.
    await tx.failures.forget_older_than(forget_before)
    await tx.failures.record(keys, now, forget_before=forget_before)


async def attempt_succeeded(tx: IdentityTransaction, account: str, others: Sequence[str] = ()) -> None:
    """The account's failures are forgiven; under the other keys, such as the address, only this attempt.

    It locks the account's key until the transaction ends, so the success and the change it makes
    (a session, a new password) wait for any other attempt on the account that is finishing.
    """
    await tx.failures.lock([account])
    await tx.failures.clear(account)
    await tx.failures.uncount(others)


async def find_by_secret[T](
    uow: AsyncUnitOfWork[IdentityTransaction],
    client: Client,
    find: Callable[[IdentityTransaction], Awaitable[T | None]],
    missing: ServiceError,
) -> T:
    """What a secret link's token stands for (an invitation, a guest link), or ``missing`` raised.

    Tokens are guessed like passwords, so every look-up counts against the address first, under a
    key apart from sign-ins (sign-in.md, 14); a token found takes its count back at once.
    """
    key = secret_link_key(client.ip)
    keys = [] if key is None else [key]
    async with uow.transaction() as tx:
        await count_attempt(tx, keys, datetime.now(UTC))
    async with uow.query() as tx:
        found = await find(tx)
    if found is None:
        raise missing
    async with uow.transaction() as tx:
        await tx.failures.uncount(keys)
    return found
