"""Counting attempts that check a secret, so guessing is slowed down (sign-in.md, 7).

An attempt is counted as failed before the secret is checked, in a short transaction of its own,
so parallel guesses cannot all pass the check while the slow password hash runs, and no
transaction stays open during it. A successful attempt takes its count back.
"""

from collections.abc import Sequence
from datetime import datetime

from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.throttle import FAILURES_EXPIRE_AFTER, check_not_blocked


async def count_attempt(tx: IdentityTransaction, keys: Sequence[str], now: datetime) -> None:
    """Refuse the attempt while any of its keys must wait; otherwise count it as failed under each key."""
    await tx.failures.lock(keys)
    check_not_blocked(await tx.failures.get(keys), now)
    forget_before = now - FAILURES_EXPIRE_AFTER
    # Counters nobody failed under for long go, so typed usernames do not pile up.
    await tx.failures.forget_older_than(forget_before)
    await tx.failures.record(keys, now, forget_before=forget_before)


async def attempt_succeeded(tx: IdentityTransaction, account: str, others: Sequence[str] = ()) -> None:
    """The account's failures are forgiven; under the other keys, such as the address, only this attempt."""
    await tx.failures.clear(account)
    await tx.failures.uncount(others)
