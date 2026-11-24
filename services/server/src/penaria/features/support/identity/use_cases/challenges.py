"""Giving out the challenges of passkey ceremonies."""

from datetime import datetime

from penaria.features.support.identity.domain.passkeys import Challenge, check_open_sign_ins
from penaria.features.support.identity.domain.repositories import IdentityTransaction


async def issue_challenge(tx: IdentityTransaction, challenge: Challenge, now: datetime) -> None:
    """Keep a new challenge; the expired ones go, so ceremonies people abandon do not pile up.

    A sign-in needs no account, so an address that already holds too many open ones is refused.
    """
    if challenge.address is not None:
        check_open_sign_ins(await tx.challenges.open_sign_ins(challenge.address, now), now)
    await tx.challenges.forget_expired(now)
    await tx.challenges.add(challenge)
