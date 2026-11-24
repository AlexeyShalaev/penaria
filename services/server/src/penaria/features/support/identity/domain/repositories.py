"""What the identity use cases need from storage."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from penaria.features.shared.journal import Journal
from penaria.features.support.identity.domain.devices import Device
from penaria.features.support.identity.domain.mail import Attempt, LoggedMail, Mail
from penaria.features.support.identity.domain.mailbox import StoredMailbox
from penaria.features.support.identity.domain.members import GuestLink, Invitation, Token
from penaria.features.support.identity.domain.models import Grant, Home, PrincipalType, Role, User
from penaria.features.support.identity.domain.passkeys import Ceremony, Challenge, Passkey
from penaria.features.support.identity.domain.recovery import AccountLink, LinkPurpose
from penaria.features.support.identity.domain.sessions import Session
from penaria.features.support.identity.domain.throttle import Failures
from penaria.features.support.identity.domain.totp import PendingSignIn, Totp


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def save(self, user: User) -> None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def get_for_update(self, user_id: UUID) -> User | None:
        """The user, locked until the transaction ends."""
        ...

    async def get_many(self, user_ids: Collection[UUID]) -> dict[UUID, User]:
        """The users with these ids, by id."""
        ...

    async def by_username(self, username: str) -> User | None:
        """The user with this (normalized) username."""
        ...

    async def by_email(self, email: str) -> User | None:
        """The user whose confirmed email this (normalized) address is."""
        ...

    async def first(self) -> User | None:
        """The earliest user, if there is any."""
        ...

    async def any_account(self) -> bool:
        """Whether any user has an account, that is, whether the install is set up."""
        ...


class PasswordRepository(Protocol):
    async def get(self, user_id: UUID) -> str | None:
        """The user's password hash, if they have a password."""
        ...

    async def set(self, user_id: UUID, password_hash: str, now: datetime) -> None: ...


class SessionRepository(Protocol):
    async def add(self, session: Session) -> None: ...

    async def by_token_hash(self, token_hash: bytes) -> tuple[Session, User | None, Grant | None] | None:
        """The session with this token, whatever its state, with its user, or its grant for a guest's."""
        ...

    async def active_for(self, user_id: UUID, now: datetime) -> list[Session]:
        """The user's sessions that have not ended (``Session.is_active``), the most recently seen first."""
        ...

    async def touch(self, session_id: UUID, now: datetime) -> None: ...

    async def revoke(self, user_id: UUID, session_id: UUID, now: datetime) -> bool:
        """End one session of the user's; whether there was such a session still open."""
        ...

    async def revoke_all_but(self, user_id: UUID, keep: UUID, now: datetime) -> list[UUID]:
        """End every active session of the user's except ``keep``; the ids of those ended."""
        ...

    async def revoke_all(self, user_id: UUID, now: datetime) -> list[UUID]:
        """End every active session of the user's; the ids of those ended."""
        ...

    async def reauthenticate(self, session_id: UUID, now: datetime) -> None:
        """Its person has just proved who they are again."""
        ...

    async def revoke_for_grant(self, grant_id: UUID, now: datetime) -> list[UUID]:
        """End every open guest session made from the grant; the ids of those ended."""
        ...

    async def trim_for_grant(self, grant_id: UUID, keep: int, now: datetime) -> None:
        """End the grant's open guest sessions but the ``keep`` most recently started."""
        ...


class PasskeyRepository(Protocol):
    async def add(self, passkey: Passkey) -> None: ...

    async def for_user(self, user_id: UUID) -> list[Passkey]:
        """The user's passkeys, the oldest first."""
        ...

    async def get(self, user_id: UUID, passkey_id: UUID) -> Passkey | None:
        """One of the user's passkeys."""
        ...

    async def by_credential_id(self, credential_id: bytes) -> tuple[Passkey, User] | None:
        """The passkey of this credential, of any account, and its user."""
        ...

    async def rename(self, passkey_id: UUID, name: str) -> None: ...

    async def record_use(self, passkey_id: UUID, seen_sign_count: int, sign_count: int, now: datetime) -> bool:
        """Keep the passkey's new signature count and last use; refused (``False``) when the passkey is gone
        or another use changed its count since it was read as ``seen_sign_count``."""
        ...

    async def remove(self, user_id: UUID, passkey_id: UUID) -> None: ...


class ChallengeRepository(Protocol):
    async def add(self, challenge: Challenge) -> None: ...

    async def take(
        self, challenge_id: UUID, ceremony: Ceremony, session_id: UUID | None, now: datetime
    ) -> Challenge | None:
        """Remove and return the challenge, if it is of this ceremony and session and has not expired."""
        ...

    async def open_sign_ins(self, address: str, now: datetime) -> list[datetime]:
        """When the sign-in challenges this address holds, unused and unexpired, expire."""
        ...

    async def forget_expired(self, now: datetime) -> None: ...


class TotpRepository(Protocol):
    async def get(self, user_id: UUID) -> Totp | None:
        """The account's authenticator app, turned on or waiting for its first code."""
        ...

    async def save(self, totp: Totp) -> None:
        """Keep the account's authenticator app, replacing what the account had."""
        ...

    async def remove(self, user_id: UUID) -> bool:
        """Forget the account's authenticator app and its recovery codes; whether there was one."""
        ...


class PendingSignInRepository(Protocol):
    async def add(self, pending: PendingSignIn) -> None: ...

    async def get(self, token_hash: bytes, now: datetime) -> PendingSignIn | None:
        """The pending sign-in of this token, if it has not expired."""
        ...

    async def take(self, pending_id: UUID, now: datetime) -> bool:
        """Remove the pending sign-in, so it opens one session at most; whether it was still there and unexpired."""
        ...

    async def forget_expired(self, now: datetime) -> None: ...

    async def forget_for(self, user_id: UUID) -> None:
        """Drop the account's pending sign-ins: what its old password started opens no session."""
        ...


class SetupTokenRepository(Protocol):
    async def lock(self) -> None:
        """Hold the setup until the transaction ends, so issuing and completing it never interleave."""
        ...

    async def replace(self, token_hash: bytes, now: datetime) -> None:
        """Keep this token and forget any earlier one."""
        ...

    async def current(self) -> bytes | None: ...

    async def clear(self) -> None: ...


class FailureRepository(Protocol):
    """Counters of failed attempts (to sign in, set up, confirm a password), by key."""

    async def lock(self, keys: Sequence[str]) -> None:
        """Hold the keys until the transaction ends; another transaction locking any of them waits."""
        ...

    async def get(self, keys: Sequence[str]) -> list[Failures]: ...

    async def record(self, keys: Sequence[str], now: datetime, forget_before: datetime) -> None:
        """Count a failure under each key; a count whose last failure is older than ``forget_before`` restarts."""
        ...

    async def uncount(self, keys: Sequence[str]) -> None:
        """Take back one failure counted under each key."""
        ...

    async def clear(self, key: str) -> None: ...

    async def forget_older_than(self, cutoff: datetime) -> None:
        """Drop the counters whose last failure is older than ``cutoff``."""
        ...


class HomeRepository(Protocol):
    async def add(self, home: Home) -> None: ...

    async def get(self, home_id: UUID) -> Home | None: ...

    async def lock(self, home_id: UUID) -> Home | None:
        """The home, locked until the transaction ends: changes to its people take turns."""
        ...

    async def with_grants_for(self, principal_type: PrincipalType, principal_id: UUID, now: datetime) -> list[Home]:
        """The homes where the principal holds an active grant, by name."""
        ...


class RoleRepository(Protocol):
    async def add_all(self, roles: Sequence[Role]) -> None: ...

    async def for_home(self, home_id: UUID) -> list[Role]:
        """The home's roles, the presets first in their order, then the others by name."""
        ...

    async def get_many(self, role_ids: Collection[UUID]) -> dict[UUID, Role]: ...


class GrantRepository(Protocol):
    async def add(self, grant: Grant) -> None: ...

    async def get(self, home_id: UUID, grant_id: UUID) -> Grant | None: ...

    async def save(self, grant: Grant) -> None:
        """Write a grant's role, scope and end."""
        ...

    async def revoke(self, grant_ids: Collection[UUID], now: datetime) -> None: ...

    async def active_in(self, home_id: UUID, principal_type: PrincipalType, now: datetime) -> list[Grant]:
        """The home's active grants of principals of this type, the oldest first."""
        ...

    async def active_of(
        self, home_id: UUID, principal_type: PrincipalType, principal_id: UUID, now: datetime
    ) -> list[Grant]:
        """The principal's active grants in the home, the oldest first."""
        ...

    async def for_principal(self, principal_type: PrincipalType, principal_id: UUID) -> list[Grant]:
        """Every grant of the principal, active or not, in any home."""
        ...

    async def owns_a_home(self, user_id: UUID) -> bool:
        """Whether the user holds an active owner grant in any home (owner grants never expire)."""
        ...

    async def owners(self, home_id: UUID) -> list[Grant]:
        """The home's active owner grants (they never expire)."""
        ...

    async def applicable(
        self,
        principal_type: PrincipalType,
        principal_id: UUID,
        home_id: UUID,
        path: Sequence[UUID],
        now: datetime,
    ) -> list[Role]:
        """The roles of the principal's active grants whose scope is the whole home or an id in ``path``."""
        ...

    async def lasting(
        self,
        principal_type: PrincipalType,
        principal_id: UUID,
        home_id: UUID,
        path: Sequence[UUID],
        now: datetime,
    ) -> list[Role]:
        """The roles of those of the ``applicable`` grants that have no end."""
        ...


class InvitationRepository(Protocol):
    async def add(self, invitation: Invitation) -> None: ...

    async def by_token_hash(self, token_hash: bytes, *, for_update: bool = False) -> Invitation | None: ...

    async def get(self, home_id: UUID, invitation_id: UUID, *, for_update: bool = False) -> Invitation | None: ...

    async def pending_in(self, home_id: UUID, now: datetime) -> list[Invitation]:
        """The home's invitations that can still be accepted, the newest first."""
        ...

    async def save(self, invitation: Invitation) -> None:
        """Write whether and by whom it was accepted, or when it was revoked."""
        ...


class TokenRepository(Protocol):
    async def add(self, token: Token) -> None: ...

    async def by_token_hash(self, token_hash: bytes) -> Token | None: ...

    async def for_principal(self, principal_type: PrincipalType, principal_id: UUID) -> Token | None:
        """The principal's token; a guest link has exactly one."""
        ...

    async def used(self, token_id: UUID, now: datetime, *, ip: str | None) -> None:
        """Keep when the token was last used, and from which address when ``ip`` is given."""
        ...

    async def revoke_for(self, principal_type: PrincipalType, principal_id: UUID, now: datetime) -> None: ...

    async def links_in(self, home_id: UUID, now: datetime) -> list[GuestLink]:
        """The home's guest links that still open, the newest first."""
        ...

    async def devices_in(self, home_id: UUID, now: datetime) -> list[Device]:
        """The home's devices whose tokens still work, the newest first."""
        ...

    async def device_by_token_hash(self, token_hash: bytes) -> Device | None:
        """The device whose token this is, whatever the state of its token and grant."""
        ...


class InstallSettingsRepository(Protocol):
    async def mailbox(self, *, for_update: bool = False) -> StoredMailbox | None:
        """The mailbox an admin saved, if any; ``for_update`` holds it until the transaction ends."""
        ...

    async def save_mailbox(self, mailbox: StoredMailbox, by: UUID, now: datetime) -> None: ...

    async def remove_mailbox(self) -> bool:
        """Forget the saved mailbox; whether there was one."""
        ...


class MailRepository(Protocol):
    async def add(self, mail: Mail) -> None: ...

    async def get(self, mail_id: UUID, *, for_update: bool = False) -> Mail | None: ...

    async def claim_due(self, now: datetime, lease_until: datetime, limit: int) -> list[Mail]:
        """Take queued mails whose attempt is due, the most overdue first, and put their next attempt at
        ``lease_until``, so no other sender takes them meanwhile; mails another transaction holds are skipped."""
        ...

    async def save(self, mail: Mail) -> None:
        """Write the mail's state, attempts, next attempt and content."""
        ...

    async def add_attempt(self, attempt: Attempt) -> None: ...

    async def page(self, before: UUID | None, limit: int) -> list[LoggedMail]:
        """The newest mails older than ``before`` (all of them without it), with their attempts."""
        ...

    async def forget_content(self, now: datetime) -> None:
        """Clear the content of the mails that can no longer be sent and are not queued."""
        ...

    async def delete_created_before(self, cutoff: datetime) -> None: ...


class AccountLinkRepository(Protocol):
    async def add(self, link: AccountLink) -> None: ...

    async def by_token_hash(
        self, token_hash: bytes, purpose: LinkPurpose, *, for_update: bool = False
    ) -> AccountLink | None: ...

    async def use(self, link_id: UUID, now: datetime) -> None: ...

    async def forget_unused(self, user_id: UUID, purpose: LinkPurpose) -> None:
        """Drop the user's links of this purpose that were not used: a new one replaces them."""
        ...

    async def forget_expired(self, now: datetime) -> None: ...


class IdentityTransaction(Protocol):
    @property
    def users(self) -> UserRepository: ...

    @property
    def passwords(self) -> PasswordRepository: ...

    @property
    def sessions(self) -> SessionRepository: ...

    @property
    def passkeys(self) -> PasskeyRepository: ...

    @property
    def challenges(self) -> ChallengeRepository: ...

    @property
    def totp(self) -> TotpRepository: ...

    @property
    def pending_sign_ins(self) -> PendingSignInRepository: ...

    @property
    def setup_tokens(self) -> SetupTokenRepository: ...

    @property
    def failures(self) -> FailureRepository: ...

    @property
    def homes(self) -> HomeRepository: ...

    @property
    def roles(self) -> RoleRepository: ...

    @property
    def grants(self) -> GrantRepository: ...

    @property
    def invitations(self) -> InvitationRepository: ...

    @property
    def tokens(self) -> TokenRepository: ...

    @property
    def install_settings(self) -> InstallSettingsRepository: ...

    @property
    def mail(self) -> MailRepository: ...

    @property
    def account_links(self) -> AccountLinkRepository: ...

    @property
    def journal(self) -> Journal: ...
