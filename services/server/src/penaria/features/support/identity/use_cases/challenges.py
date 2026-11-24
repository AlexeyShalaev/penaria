"""Giving out the challenges of passkey ceremonies."""

from datetime import datetime

from penaria.features.support.identity.domain.passkeys import Challenge
from penaria.features.support.identity.domain.repositories import IdentityTransaction


async def issue_challenge(tx: IdentityTransaction, challenge: Challenge, now: datetime) -> None:
    """Keep a new challenge; the expired ones go, so ceremonies people abandon do not pile up."""
    await tx.challenges.forget_expired(now)
    await tx.challenges.add(challenge)
