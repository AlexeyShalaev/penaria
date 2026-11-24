"""Confirming it is still the session's person, with their password or a passkey, before a sensitive command.

A confirmation makes the session's sign-in recent again (sign-in.md, 5), as signing in anew would,
without ending the session.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.passkeys import (
    Ceremony,
    Challenge,
    CredentialJson,
    CredentialRejected,
    Passkey,
    PasskeyNotFoundError,
    PasskeyOptions,
    PasskeyRejectedError,
    RelyingParty,
)
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.account import check_current_password
from penaria.features.support.identity.use_cases.challenges import issue_challenge


class ReauthenticateWithPassword:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def execute(self, current: CurrentSession, password: str) -> None:
        checked = await check_current_password(self._uow, self._hasher, current, password)
        async with self._uow.transaction() as tx:
            await checked.still_current(tx)
            await _confirmed(tx, current, datetime.now(UTC))


class StartPasskeyReauthentication:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], relying_party: RelyingParty) -> None:
        self._uow = uow
        self._relying_party = relying_party

    async def execute(self, current: CurrentSession) -> PasskeyOptions:
        """The options for ``navigator.credentials.get`` that offer the account's passkeys."""
        now = datetime.now(UTC)
        challenge = Challenge.for_session(Ceremony.REAUTHENTICATION, current.id, now)
        async with self._uow.transaction() as tx:
            passkeys = await tx.passkeys.for_user(current.user_id)
            if not passkeys:
                raise PasskeyNotFoundError("the account has no passkey to confirm it is you with")
            await issue_challenge(tx, challenge, now)
        return PasskeyOptions(challenge.id, self._relying_party.authentication_options(challenge, passkeys))


class ReauthenticateWithPasskey:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], relying_party: RelyingParty) -> None:
        self._uow = uow
        self._relying_party = relying_party

    async def execute(self, current: CurrentSession, *, challenge_id: UUID, credential: CredentialJson) -> None:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            challenge = await tx.challenges.take(challenge_id, Ceremony.REAUTHENTICATION, current.id, now)
        if challenge is None:
            raise PasskeyRejectedError("confirming took too long or was already done; start again")
        passkey = await self._own_passkey(current, credential)
        try:
            sign_count = self._relying_party.verify_authentication(credential, challenge, passkey)
        except CredentialRejected as exc:
            raise PasskeyRejectedError("this passkey does not confirm it is you") from exc
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            if not await tx.passkeys.record_use(passkey.id, passkey.sign_count, sign_count, now):
                raise PasskeyRejectedError("this passkey does not confirm it is you")
            await _confirmed(tx, current, now, passkey_id=passkey.id)

    async def _own_passkey(self, current: CurrentSession, credential: CredentialJson) -> Passkey:
        try:
            credential_id = self._relying_party.read_assertion(credential).credential_id
        except CredentialRejected as exc:
            raise PasskeyRejectedError("this passkey does not confirm it is you") from exc
        async with self._uow.query() as tx:
            found = await tx.passkeys.by_credential_id(credential_id)
        if found is None or found[0].user_id != current.user_id:
            raise PasskeyRejectedError("this passkey is not one of the account's")
        return found[0]


async def _confirmed(
    tx: IdentityTransaction, current: CurrentSession, now: datetime, *, passkey_id: UUID | None = None
) -> None:
    """Make the session's sign-in recent; ``passkey_id`` names the passkey used, without it the password was."""
    await tx.sessions.reauthenticate(current.id, now)
    payload = {"user_id": str(current.user_id), "session_id": str(current.id)}
    if passkey_id is not None:
        payload["passkey_id"] = str(passkey_id)
    await tx.journal.append([Event("account.reauthenticated", None, Actor.user(current.user_id), payload)])
