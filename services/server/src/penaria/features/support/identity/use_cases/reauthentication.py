"""Confirming it is still the session's person, with their password (and second factor) or a passkey, before a
sensitive command.

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
from penaria.features.support.identity.domain.secrets import SecretBox
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.domain.throttle import second_factor_key
from penaria.features.support.identity.domain.totp import SecondFactorCodeRequiredError
from penaria.features.support.identity.use_cases.account import check_current_password
from penaria.features.support.identity.use_cases.attempts import attempt_succeeded, count_attempt
from penaria.features.support.identity.use_cases.challenges import issue_challenge
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.identity.use_cases.second_factor import (
    SecondFactorMethod,
    SecondFactorProof,
    prove_second_factor,
    totp_enabled,
)


class ReauthenticateWithPassword:
    """With the password, and a code of the authenticator app or a recovery code when the account has the app:
    the password alone never makes a sign-in recent that needed both to start (sign-in.md, 4.3)."""

    def __init__(
        self, uow: AsyncUnitOfWork[IdentityTransaction], hasher: PasswordHasher, box: SecretBox, postman: Postman
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._box = box
        self._postman = postman

    async def execute(self, current: CurrentSession, password: str, proof: SecondFactorProof | None) -> None:
        """``proof`` is needed, and only used, while the account's authenticator app is on."""
        async with self._uow.query() as tx:
            asks_code = await totp_enabled(tx, current.user_id) is not None
        if asks_code and proof is None:
            raise SecondFactorCodeRequiredError("enter a code of your authenticator app, or a recovery code, too")
        checked = await check_current_password(self._uow, self._hasher, current, password)
        if not asks_code or proof is None:
            async with self._uow.transaction() as tx:
                await checked.still_current(tx)
                await _confirmed(tx, current, datetime.now(UTC))
            return
        # The password was right: it is forgiven even if the code that follows is wrong, which counts apart.
        async with self._uow.transaction() as tx:
            await tx.users.get_for_update(current.user_id)
            await checked.still_current(tx)
        codes = second_factor_key(current.user_id)
        async with self._uow.transaction() as tx:
            await count_attempt(tx, [codes], datetime.now(UTC))
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            user = await tx.users.get_for_update(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            totp = await totp_enabled(tx, user.id)
            # Turned off since it was looked at: the password is all the account asks for now.
            method = (
                None
                if totp is None
                else await prove_second_factor(tx, self._box, self._postman, user, totp, proof, now)
            )
            await attempt_succeeded(tx, codes)
            await _confirmed(tx, current, now, second_factor=method)


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
    tx: IdentityTransaction,
    current: CurrentSession,
    now: datetime,
    *,
    passkey_id: UUID | None = None,
    second_factor: SecondFactorMethod | None = None,
) -> None:
    """Make the session's sign-in recent; ``passkey_id`` names the passkey used, without it the password was,
    with ``second_factor`` when the account asked for one."""
    await tx.sessions.reauthenticate(current.id, now)
    payload = {"user_id": str(current.user_id), "session_id": str(current.id)}
    if passkey_id is not None:
        payload["passkey_id"] = str(passkey_id)
    if second_factor is not None:
        payload["second_factor"] = second_factor.value
    await tx.journal.append([Event("account.reauthenticated", None, Actor.user(current.user_id), payload)])
