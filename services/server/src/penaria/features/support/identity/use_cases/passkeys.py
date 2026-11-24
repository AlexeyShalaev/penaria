"""The signed-in person's passkeys: adding, naming and removing them."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.passkeys import (
    Ceremony,
    Challenge,
    CredentialJson,
    CredentialRejected,
    LastSignInMethodError,
    Passkey,
    PasskeyAlreadyRegisteredError,
    PasskeyNotFoundError,
    PasskeyRejectedError,
    RelyingParty,
    check_passkey_name,
)
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import CurrentSession


class ListPasskeys:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession) -> list[Passkey]:
        """The account's passkeys, the oldest first."""
        async with self._uow.query() as tx:
            return await tx.passkeys.for_user(current.user_id)


class StartPasskeyRegistration:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], relying_party: RelyingParty) -> None:
        self._uow = uow
        self._relying_party = relying_party

    async def execute(self, current: CurrentSession) -> tuple[Challenge, dict[str, Any]]:
        """A challenge, and the options for ``navigator.credentials.create`` that carry it."""
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        challenge = Challenge.issue(Ceremony.REGISTRATION, current.id, now)
        async with self._uow.transaction() as tx:
            user = await tx.users.get(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            existing = await tx.passkeys.for_user(user.id)
            await issue_challenge(tx, challenge, now)
        # The authenticators that already hold one of the account's passkeys decline to make another.
        return challenge, self._relying_party.registration_options(user, challenge, existing)


class AddPasskey:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], relying_party: RelyingParty) -> None:
        self._uow = uow
        self._relying_party = relying_party

    async def execute(
        self, current: CurrentSession, *, challenge_id: UUID, credential: CredentialJson, name: str
    ) -> Passkey:
        """Keep the credential the browser made for the challenge, under the name the person gave it."""
        name = check_passkey_name(name)
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        async with self._uow.transaction() as tx:
            challenge = await tx.challenges.take(challenge_id, Ceremony.REGISTRATION, current.id, now)
        if challenge is None:
            raise PasskeyRejectedError("adding the passkey took too long or was already done; start again")
        try:
            new = self._relying_party.verify_registration(credential, challenge)
        except CredentialRejected as exc:
            raise PasskeyRejectedError("the browser's answer does not check out; start again") from exc
        passkey = Passkey(
            user_id=current.user_id,
            credential_id=new.credential_id,
            public_key=new.public_key,
            sign_count=new.sign_count,
            name=name,
            transports=new.transports,
            created_at=now,
        )
        async with self._uow.transaction() as tx:
            if await tx.passkeys.by_credential_id(new.credential_id) is not None:
                raise PasskeyAlreadyRegisteredError("this passkey is already added")
            await tx.passkeys.add(passkey)
            await tx.journal.append(
                [_event("account.passkey_added", current, passkey_id=str(passkey.id), name=passkey.name)]
            )
        return passkey


class RenamePasskey:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession, passkey_id: UUID, name: str) -> Passkey:
        name = check_passkey_name(name)
        async with self._uow.transaction() as tx:
            passkey = await tx.passkeys.get(current.user_id, passkey_id)
            if passkey is None:
                raise PasskeyNotFoundError(params={"passkey_id": str(passkey_id)})
            if name != passkey.name:
                passkey.name = name
                await tx.passkeys.rename(passkey.id, name)
                await tx.journal.append(
                    [_event("account.passkey_renamed", current, passkey_id=str(passkey.id), name=name)]
                )
        return passkey


class RemovePasskey:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession, passkey_id: UUID) -> None:
        """Forget a passkey; the account keeps at least one way to sign in."""
        current.require_recent_sign_in(datetime.now(UTC))
        async with self._uow.transaction() as tx:
            # Two removals at once would each see the other passkey still there.
            await tx.users.get_for_update(current.user_id)
            passkeys = await tx.passkeys.for_user(current.user_id)
            if all(passkey.id != passkey_id for passkey in passkeys):
                raise PasskeyNotFoundError(params={"passkey_id": str(passkey_id)})
            if len(passkeys) == 1 and await tx.passwords.get(current.user_id) is None:
                raise LastSignInMethodError("this passkey is the account's only way to sign in")
            await tx.passkeys.remove(current.user_id, passkey_id)
            await tx.journal.append([_event("account.passkey_removed", current, passkey_id=str(passkey_id))])


async def issue_challenge(tx: IdentityTransaction, challenge: Challenge, now: datetime) -> None:
    """Keep a new challenge; the expired ones go, so ceremonies people abandon do not pile up."""
    await tx.challenges.forget_expired(now)
    await tx.challenges.add(challenge)


def _event(event_type: str, current: CurrentSession, **payload: str) -> Event:
    return Event(event_type, None, Actor.user(current.user_id), {"user_id": str(current.user_id), **payload})
