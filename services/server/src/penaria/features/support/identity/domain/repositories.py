"""What the identity use cases need from storage."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from penaria.features.shared.journal import Journal
from penaria.features.support.identity.domain.models import Grant, Home, PrincipalType, Role, User
from penaria.features.support.identity.domain.passkeys import Ceremony, Challenge, Passkey
from penaria.features.support.identity.domain.sessions import Session
from penaria.features.support.identity.domain.throttle import Failures


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def save(self, user: User) -> None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def get_for_update(self, user_id: UUID) -> User | None:
        """The user, locked until the transaction ends."""
        ...

    async def by_username(self, username: str) -> User | None:
        """The user with this (normalized) username."""
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

    async def by_token_hash(self, token_hash: bytes) -> tuple[Session, User] | None:
        """The session with this token and its user, whatever their state."""
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

    async def reauthenticate(self, session_id: UUID, now: datetime) -> None:
        """Its person has just proved who they are again."""
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

    async def with_grants_for(self, principal_type: PrincipalType, principal_id: UUID, now: datetime) -> list[Home]:
        """The homes where the principal holds an active grant, by name."""
        ...


class RoleRepository(Protocol):
    async def add_all(self, roles: Sequence[Role]) -> None: ...


class GrantRepository(Protocol):
    async def add(self, grant: Grant) -> None: ...

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
    def journal(self) -> Journal: ...
