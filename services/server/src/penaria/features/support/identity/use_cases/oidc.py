"""Signing in, joining and confirming it is you with the operator's OpenID Connect provider (sign-in.md, 4.4 and 18).

Each way starts a flow here and ends at the one callback: ``CompleteOidc`` does what the flow was for.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import assert_never
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import ConflictError, InvalidError
from penaria.features.shared.journal import Event
from penaria.features.shared.places import PlaceDirectory
from penaria.features.support.identity.domain.accounts import check_locale
from penaria.features.support.identity.domain.mailbox import check_email
from penaria.features.support.identity.domain.members import InvitationNotFoundError
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.oidc import (
    Claims,
    ExternalIdentity,
    ExternalIdentityNotFoundError,
    ExternalSignIn,
    FlowPurpose,
    IdentityLinkedError,
    OidcFlow,
    OidcProvider,
    Problem,
    ProviderError,
    ProviderUnavailableError,
    StartedFlow,
    check_open_flows,
    display_name_of,
    safe_return_to,
    username_candidates,
)
from penaria.features.support.identity.domain.passkeys import LastSignInMethodError
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.secrets import SecretBox
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, hash_token
from penaria.features.support.identity.domain.throttle import account_key, address_key, second_factor_key
from penaria.features.support.identity.domain.totp import PendingSignIn, SecondFactorCodeRequiredError
from penaria.features.support.identity.use_cases.account import load_user
from penaria.features.support.identity.use_cases.attempts import attempt_succeeded, count_attempt
from penaria.features.support.identity.use_cases.invitations import (
    accept_invitation,
    lock_invitation,
    open_invitation,
)
from penaria.features.support.identity.use_cases.members import place_for
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.identity.use_cases.second_factor import (
    SecondFactorProof,
    prove_second_factor,
    totp_enabled,
)
from penaria.features.support.identity.use_cases.sessions import start_session

logger = logging.getLogger(__name__)

HOME_PAGE = "/"
ACCOUNT_PAGE = "/account"
# The provider's clock and the install's may differ a little.
AUTH_TIME_LEEWAY = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class OidcStarted:
    """Where to send the browser, and the binding for its cookie, which the callback checks."""

    url: str
    binding: str


@dataclass(frozen=True, slots=True)
class Done:
    """The flow did what it was for; a sign-in brings a new session's token."""

    return_to: str
    session_token: str | None = None


@dataclass(frozen=True, slots=True)
class SecondStep:
    """The account has an authenticator app: its code comes next, as after a password (sign-in.md, 16)."""

    token: str
    expires_at: datetime
    return_to: str


@dataclass(frozen=True, slots=True)
class Refused:
    problem: Problem


type OidcOutcome = Done | SecondStep | Refused


@dataclass(frozen=True, slots=True)
class SignInMethods:
    has_password: bool
    # Those at the provider set up now; identities of an earlier issuer sign nobody in.
    identities: list[ExternalIdentity]


class _RefusedError(Exception):
    """Every refusal of the callback is raised, so it rolls back whatever the callback wrote, such as an
    account made for an invitation that turns out unusable."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.value)
        self.problem = problem


class _AccountRefusedError(_RefusedError):
    """A refusal that concerns a known account, journalled as a failed sign-in once the rollback is done
    (sign-in.md, 7)."""

    def __init__(self, problem: Problem, user_id: UUID, client: Client) -> None:
        super().__init__(problem)
        self.user_id = user_id
        self.client = client


class StartOidcSignIn:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], external: ExternalSignIn) -> None:
        self._uow = uow
        self._external = external

    async def execute(self, client: Client, *, locale: str, return_to: str | None) -> OidcStarted:
        provider = self._external.configured()
        started = OidcFlow.start(
            FlowPurpose.SIGN_IN,
            return_to=safe_return_to(return_to, HOME_PAGE),
            locale=check_locale(locale),
            address=address_key(client.ip),
            now=datetime.now(UTC),
        )
        return await _begin(self._uow, provider, started)


class StartOidcInvitation:
    """Accept an invitation with an identity at the provider: the linked account, or a new one made from it
    whatever the operator allows, since the invitation lets the person in."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], external: ExternalSignIn) -> None:
        self._uow = uow
        self._external = external

    async def execute(self, token: str, client: Client, *, locale: str) -> OidcStarted:
        provider = self._external.configured()
        await open_invitation(self._uow, token, client)
        started = OidcFlow.start(
            FlowPurpose.INVITATION,
            return_to=HOME_PAGE,
            locale=check_locale(locale),
            address=address_key(client.ip),
            now=datetime.now(UTC),
            invitation_hash=hash_token(token),
        )
        return await _begin(self._uow, provider, started)


class StartOidcLink:
    """Link the signed-in account to an identity at the provider: a new way to sign in, so it needs a
    recent sign-in (sign-in.md, 5)."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], external: ExternalSignIn) -> None:
        self._uow = uow
        self._external = external

    async def execute(self, current: CurrentSession, client: Client, *, return_to: str | None) -> OidcStarted:
        provider = self._external.configured()
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        async with self._uow.query() as tx:
            user = await load_user(tx, current)
            linked = await usable_identities(tx, self._external, current.user_id)
        if linked:
            raise IdentityLinkedError("the account is linked to an identity at the provider already: unlink it first")
        started = OidcFlow.start(
            FlowPurpose.LINK,
            return_to=safe_return_to(return_to, ACCOUNT_PAGE),
            locale=user.locale,
            address=address_key(client.ip),
            now=now,
            user_id=current.user_id,
            session_id=current.id,
        )
        return await _begin(self._uow, provider, started)


class StartOidcReauthentication:
    """Confirm it is you by signing in at the provider again, with a code of the authenticator app too while
    it is on, checked here before the browser leaves: the provider alone never confirms what needed both."""

    def __init__(
        self,
        uow: AsyncUnitOfWork[IdentityTransaction],
        external: ExternalSignIn,
        box: SecretBox,
        postman: Postman,
    ) -> None:
        self._uow = uow
        self._external = external
        self._box = box
        self._postman = postman

    async def execute(
        self, current: CurrentSession, client: Client, *, proof: SecondFactorProof | None, return_to: str | None
    ) -> OidcStarted:
        provider = self._external.configured()
        async with self._uow.query() as tx:
            user = await load_user(tx, current)
            linked = await usable_identities(tx, self._external, current.user_id)
            asks_code = await totp_enabled(tx, current.user_id) is not None
        if not linked:
            raise ExternalIdentityNotFoundError("the account has no identity at the provider to confirm it is you with")
        if asks_code and proof is None:
            raise SecondFactorCodeRequiredError("enter a code of your authenticator app, or a recovery code, too")
        started = OidcFlow.start(
            FlowPurpose.REAUTHENTICATE,
            return_to=safe_return_to(return_to, ACCOUNT_PAGE),
            locale=user.locale,
            address=address_key(client.ip),
            now=datetime.now(UTC),
            user_id=current.user_id,
            session_id=current.id,
        )
        # The flow is set up first, so a code is spent only on a confirmation that can go on; its state leaves
        # here only once the code checks out.
        flow = await _begin(self._uow, provider, started)
        if asks_code and proof is not None:
            await self._prove(current, proof)
        return flow

    async def _prove(self, current: CurrentSession, proof: SecondFactorProof) -> None:
        codes = second_factor_key(current.user_id)
        async with self._uow.transaction() as tx:
            await count_attempt(tx, [codes], datetime.now(UTC))
        # Committed before the code is checked, so a wrong one stays counted.
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            user = await tx.users.get_for_update(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            totp = await totp_enabled(tx, user.id)
            if totp is not None:
                await prove_second_factor(tx, self._box, self._postman, user, totp, proof, now)
            await attempt_succeeded(tx, codes)


class CompleteOidc:
    """The provider's callback: check the flow and the ID token, then do what the flow was for."""

    def __init__(
        self,
        uow: AsyncUnitOfWork[IdentityTransaction],
        external: ExternalSignIn,
        places: PlaceDirectory,
    ) -> None:
        self._uow = uow
        self._external = external
        self._places = places

    async def execute(
        self, *, state: str | None, code: str | None, error: str | None, binding: str | None, client: Client
    ) -> OidcOutcome:
        provider = self._external.configured()
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            flow = None if not state else await tx.oidc_flows.take(hash_token(state), now)
        if flow is None or not flow.started_in(binding):
            return Refused(Problem.EXPIRED)
        if error is not None or not code:
            logger.info("The provider ended a sign-in without a code: %s", error)
            return Refused(Problem.FAILED)
        try:
            claims = await provider.claims(code=code, code_verifier=flow.code_verifier, nonce=flow.nonce)
        except ProviderError as exc:
            logger.warning("A sign-in with the provider failed: %s", exc)
            return Refused(Problem.FAILED)
        try:
            return await self._complete(provider, flow, claims, client)
        except _AccountRefusedError as refusal:
            await self._journal_failure(refusal)
            return Refused(refusal.problem)
        except _RefusedError as refusal:
            return Refused(refusal.problem)

    async def _journal_failure(self, refusal: _AccountRefusedError) -> None:
        payload = {"user_id": str(refusal.user_id), "ip": refusal.client.ip, "reason": refusal.problem.value}
        async with self._uow.transaction() as tx:
            await tx.journal.append([Event("account.sign_in_failed", None, Actor.system(), payload)])

    async def _complete(self, provider: OidcProvider, flow: OidcFlow, claims: Claims, client: Client) -> OidcOutcome:
        match flow.purpose:
            case FlowPurpose.SIGN_IN:
                return await self._sign_in(provider, flow, claims, client)
            case FlowPurpose.INVITATION:
                return await self._accept(provider, flow, claims, client)
            case FlowPurpose.LINK:
                return await self._link(provider, flow, claims)
            case FlowPurpose.REAUTHENTICATE:
                return await self._reauthenticate(provider, flow, claims, client)
            case _:
                assert_never(flow.purpose)

    async def _sign_in(self, provider: OidcProvider, flow: OidcFlow, claims: Claims, client: Client) -> OidcOutcome:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await _lock_identity(tx, provider.issuer, claims.subject)
            found = await tx.external_identities.by_subject(provider.issuer, claims.subject)
            if found is not None:
                identity, user = found
            elif self._external.allow_sign_up:
                identity, user = await _new_account(tx, provider.issuer, claims, flow.locale, now)
            else:
                raise _RefusedError(Problem.INVITATION_REQUIRED)
            return await _open(tx, user, identity, client, now, flow.return_to)

    async def _accept(self, provider: OidcProvider, flow: OidcFlow, claims: Claims, client: Client) -> OidcOutcome:
        if flow.invitation_hash is None:
            raise RuntimeError(f"the invitation flow ({flow.id}) names no invitation")
        async with self._uow.query() as tx:
            invitation = await tx.invitations.by_token_hash(flow.invitation_hash)
        if invitation is None:
            raise _RefusedError(Problem.INVITATION_UNUSABLE)
        scope = await place_for(self._places, invitation.scope_entity_id)
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await _lock_identity(tx, provider.issuer, claims.subject)
            found = await tx.external_identities.by_subject(provider.issuer, claims.subject)
            if found is None:
                identity, user = await _new_account(
                    tx, provider.issuer, claims, flow.locale, now, invitation_id=invitation.id
                )
            else:
                identity, user = found
                # Accepting is a change to the account: an account with an authenticator app makes it only once
                # its code is in, as it would accept signed in (sign-in.md, 18).
                if await totp_enabled(tx, user.id) is not None:
                    raise _RefusedError(Problem.SIGN_IN_FIRST)
            try:
                invitation, _ = await lock_invitation(tx, flow.invitation_hash, scope, now)
                if invitation.created_by == user.id:
                    raise _RefusedError(Problem.INVITATION_UNUSABLE)
                await accept_invitation(tx, self._places, invitation, user.id, now)
            except (ConflictError, InvalidError, InvitationNotFoundError) as exc:
                logger.info("An invitation accepted through the provider was refused: %s", exc)
                raise _RefusedError(Problem.INVITATION_UNUSABLE) from exc
            return await _open(tx, user, identity, client, now, flow.return_to)

    async def _link(self, provider: OidcProvider, flow: OidcFlow, claims: Claims) -> OidcOutcome:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            user_id = await _session_still_open(tx, flow, now)
            await _lock_identity(tx, provider.issuer, claims.subject)
            found = await tx.external_identities.by_subject(provider.issuer, claims.subject)
            if found is not None:
                if found[1].id != user_id:
                    raise _RefusedError(Problem.IDENTITY_TAKEN)
                return Done(flow.return_to)
            if await usable_identities(tx, self._external, user_id):
                raise _RefusedError(Problem.ALREADY_LINKED)
            identity = ExternalIdentity(
                issuer=provider.issuer, subject=claims.subject, user_id=user_id, created_at=now, email=claims.email
            )
            await tx.external_identities.add(identity)
            payload = {"user_id": str(user_id), "external_identity_id": str(identity.id), "issuer": provider.issuer}
            await tx.journal.append([Event("account.external_identity_linked", None, Actor.user(user_id), payload)])
        return Done(flow.return_to)

    async def _reauthenticate(
        self, provider: OidcProvider, flow: OidcFlow, claims: Claims, client: Client
    ) -> OidcOutcome:
        now = datetime.now(UTC)
        # The provider was asked to check the person again; a sign-in older than the flow means it did not.
        if (
            claims.auth_time is None
            or datetime.fromtimestamp(claims.auth_time, UTC) < flow.created_at - AUTH_TIME_LEEWAY
        ):
            logger.warning(
                "The provider confirmed a person without signing them in again (auth_time %s)", claims.auth_time
            )
            raise _RefusedError(Problem.FAILED)
        async with self._uow.transaction() as tx:
            user_id = await _session_still_open(tx, flow, now)
            found = await tx.external_identities.by_subject(provider.issuer, claims.subject)
            if found is None or found[1].id != user_id:
                raise _AccountRefusedError(Problem.WRONG_ACCOUNT, user_id, client)
            if flow.session_id is None:
                raise RuntimeError(f"the confirmation flow ({flow.id}) names no session")
            await tx.sessions.reauthenticate(flow.session_id, now)
            payload = {
                "user_id": str(user_id),
                "session_id": str(flow.session_id),
                "external_identity_id": str(found[0].id),
            }
            await tx.journal.append([Event("account.reauthenticated", None, Actor.user(user_id), payload)])
        return Done(flow.return_to)


class ListSignInMethods:
    """Whether the account has a password, and its identity at the provider, for the account page."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], external: ExternalSignIn) -> None:
        self._uow = uow
        self._external = external

    async def execute(self, current: CurrentSession) -> SignInMethods:
        async with self._uow.query() as tx:
            has_password = await tx.passwords.get(current.user_id) is not None
            identities = await usable_identities(tx, self._external, current.user_id)
        return SignInMethods(has_password=has_password, identities=identities)


class UnlinkExternalIdentity:
    """Unlink an identity at the provider; the account keeps at least one way to sign in."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], external: ExternalSignIn) -> None:
        self._uow = uow
        self._external = external

    async def execute(self, current: CurrentSession, identity_id: UUID) -> None:
        current.require_recent_sign_in(datetime.now(UTC))
        async with self._uow.transaction() as tx:
            # Two removals at once would each see the other way to sign in still there.
            await tx.users.get_for_update(current.user_id)
            identities = await tx.external_identities.for_user(current.user_id)
            if all(identity.id != identity_id for identity in identities):
                raise ExternalIdentityNotFoundError(params={"external_identity_id": str(identity_id)})
            usable = [i for i in await usable_identities(tx, self._external, current.user_id) if i.id != identity_id]
            others = (
                bool(usable)
                or await tx.passwords.get(current.user_id) is not None
                or bool(await tx.passkeys.for_user(current.user_id))
            )
            if not others:
                raise LastSignInMethodError("this identity is the account's only way to sign in")
            await tx.external_identities.remove(current.user_id, identity_id)
            payload = {"user_id": str(current.user_id), "external_identity_id": str(identity_id)}
            await tx.journal.append(
                [Event("account.external_identity_unlinked", None, Actor.user(current.user_id), payload)]
            )


async def signs_in_without_passkeys(tx: IdentityTransaction, external: ExternalSignIn, user_id: UUID) -> bool:
    """Whether the account can sign in some other way than its passkeys: a password, or the provider."""
    return await tx.passwords.get(user_id) is not None or bool(await usable_identities(tx, external, user_id))


async def usable_identities(tx: IdentityTransaction, external: ExternalSignIn, user_id: UUID) -> list[ExternalIdentity]:
    """The account's identities at the provider set up now: one of an earlier issuer, or with no provider at all,
    signs nobody in, so it is no way to sign in."""
    return [
        identity for identity in await tx.external_identities.for_user(user_id) if identity.issuer == external.issuer
    ]


async def _begin(
    uow: AsyncUnitOfWork[IdentityTransaction], provider: OidcProvider, started: StartedFlow
) -> OidcStarted:
    flow = started.flow
    now = datetime.now(UTC)
    async with uow.transaction() as tx:
        await tx.oidc_flows.forget_expired(now)
        # A request with no address (through a Unix socket) has nothing to count it by.
        if flow.address is not None:
            check_open_flows(await tx.oidc_flows.open_for(flow.address, now))
        await tx.oidc_flows.add(flow)
    try:
        url = await provider.authorization_url(
            state=started.state,
            nonce=flow.nonce,
            code_verifier=flow.code_verifier,
            reauthenticate=flow.purpose is FlowPurpose.REAUTHENTICATE,
        )
    except ProviderError as exc:
        logger.error("The provider cannot start a sign-in: %s", exc)  # noqa: TRY400 - the cause is in the message
        raise ProviderUnavailableError("the sign-in provider cannot be reached; try again later") from exc
    return OidcStarted(url=url, binding=started.binding)


async def _session_still_open(tx: IdentityTransaction, flow: OidcFlow, now: datetime) -> UUID:
    """The account of a link or a confirmation, locked, while the session that started it is open and the account
    enabled: signing out everywhere or changing the password ends what the old session started."""
    if flow.user_id is None or flow.session_id is None:
        raise RuntimeError(f"the flow ({flow.id}) of a signed-in person names no account or session")
    user = await tx.users.get_for_update(flow.user_id)
    open_sessions = await tx.sessions.active_for(flow.user_id, now)
    if user is None or user.disabled_at is not None or all(s.id != flow.session_id for s in open_sessions):
        raise _RefusedError(Problem.EXPIRED)
    return user.id


async def _lock_identity(tx: IdentityTransaction, issuer: str, subject: str) -> None:
    """Two callbacks of one new identity at once (two browsers signing up, two accounts linking it) take turns."""
    await tx.failures.lock(["identity:" + hashlib.sha256(f"{issuer}\n{subject}".encode()).hexdigest()])


async def _open(
    tx: IdentityTransaction,
    user: User,
    identity: ExternalIdentity,
    client: Client,
    now: datetime,
    return_to: str,
) -> OidcOutcome:
    """A session for the account, or the code of its authenticator app first."""
    if user.disabled_at is not None:
        raise _AccountRefusedError(Problem.ACCOUNT_DISABLED, user.id, client)
    if await totp_enabled(tx, user.id) is not None:
        await tx.pending_sign_ins.forget_expired(now)
        pending, token = PendingSignIn.start(user.id, address_key(client.ip), now)
        await tx.pending_sign_ins.add(pending)
        return SecondStep(token=token, expires_at=pending.expires_at, return_to=return_to)
    session_token = await start_session(tx, user, client, now, external_identity_id=identity.id)
    return Done(return_to=return_to, session_token=session_token)


async def _new_account(
    tx: IdentityTransaction,
    issuer: str,
    claims: Claims,
    locale: str,
    now: datetime,
    *,
    invitation_id: UUID | None = None,
) -> tuple[ExternalIdentity, User]:
    """An account made from the provider's claims, with no password: the provider signs its person in."""
    username = await _free_username(tx, claims)
    user = User(
        display_name=display_name_of(claims, username),
        locale=locale,
        username=username,
        email=await _verified_free_email(tx, claims),
    )
    await tx.users.add(user)
    identity = ExternalIdentity(
        issuer=issuer, subject=claims.subject, user_id=user.id, created_at=now, email=claims.email
    )
    await tx.external_identities.add(identity)
    payload = {"user_id": str(user.id), "external_identity_id": str(identity.id), "issuer": issuer}
    if invitation_id is not None:
        payload["invitation_id"] = str(invitation_id)
    await tx.journal.append([Event("account.created", None, Actor.user(user.id), payload)])
    return identity, user


async def _free_username(tx: IdentityTransaction, claims: Claims) -> str:
    candidates = username_candidates(claims)
    for candidate in candidates:
        # Two accounts made at once with the same name take turns here, as through invitations.
        await tx.failures.lock([account_key(candidate)])
        if await tx.users.by_username(candidate) is None:
            return candidate
    logger.warning("No free username is left for a new account from the provider (%s-…)", candidates[0])
    raise _RefusedError(Problem.FAILED)


async def _verified_free_email(tx: IdentityTransaction, claims: Claims) -> str | None:
    """The provider's email, when it says it checked it and no other account has it; it is the account's
    confirmed address then, since the provider confirmed it (sign-in.md, 15)."""
    if not claims.email_verified or claims.email is None:
        return None
    try:
        email = check_email(claims.email)
    except InvalidError:
        logger.info("The provider's email of a new account is not an address Penaria takes; the account has none")
        return None
    return None if await tx.users.by_email(email) is not None else email
