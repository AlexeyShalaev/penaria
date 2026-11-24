"""Slowing down password guessing: per account and per address, failures earn a growing wait (sign-in.md, 7)."""

import hashlib
import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta

from penaria.features.shared.errors import TooManyRequestsError

FREE_FAILURES = 5
FIRST_DELAY = timedelta(seconds=30)
MAX_DELAY = timedelta(minutes=15)
# A counter whose last failure is this old starts again from zero.
FAILURES_EXPIRE_AFTER = timedelta(hours=1)
IPV6 = 6
IPV6_PREFIX = 64


class TooManyAttemptsError(TooManyRequestsError):
    code = "too_many_attempts"


@dataclass(frozen=True, slots=True)
class Failures:
    count: int
    last_at: datetime

    def blocked_until(self) -> datetime | None:
        delay = delay_after(self.count)
        return None if delay is None else self.last_at + delay


def delay_after(failures: int) -> timedelta | None:
    """How long to wait after ``failures`` failures in a row: none for the first few, then doubling up to a cap."""
    if failures < FREE_FAILURES:
        return None
    delay = FIRST_DELAY
    for _ in range(failures - FREE_FAILURES):
        if delay >= MAX_DELAY:
            break
        delay *= 2
    return min(delay, MAX_DELAY)


def check_not_blocked(failures: list[Failures], now: datetime) -> None:
    """Refuse the attempt while any of its counters still makes it wait."""
    until = max((u for f in failures if (u := f.blocked_until()) is not None), default=None)
    if until is not None and until > now:
        wait = until - now
        raise TooManyAttemptsError(
            "too many failed attempts; wait and try again",
            params={"retry_after_seconds": int(wait.total_seconds()) + 1},
        )


def account_key(username: str) -> str:
    """The counter of a username, known or not; hashed so the table holds no usernames people typed."""
    return "account:" + hashlib.sha256(username.encode()).hexdigest()


def address_key(ip: str | None) -> str | None:
    """The counter of an address; IPv6 by its /64, the block a single household or attacker holds."""
    if ip is None:
        return None
    address = ipaddress.ip_address(ip)
    if address.version == IPV6:
        return f"ip:{ipaddress.ip_network(f'{address}/{IPV6_PREFIX}', strict=False)}"
    return f"ip:{address}"
