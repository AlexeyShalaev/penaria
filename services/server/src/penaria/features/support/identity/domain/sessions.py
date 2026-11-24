"""Browser sessions: a random token in a cookie, of which the server keeps only a hash (sign-in.md, 5).

A session belongs to an account, or to a guest link's grant: a guest needs no account (sign-in.md, 6.2).
A device has no session: each of its requests carries its token (sign-in.md, 6.3).
"""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import assert_never
from uuid import UUID

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import ForbiddenError, UnauthenticatedError
from penaria.features.shared.ids import new_id

IDLE_TIMEOUT = timedelta(days=30)
ABSOLUTE_LIFETIME = timedelta(days=180)
# Seeing a session again within this time does not write; the idle timeout is far longer.
LAST_SEEN_PRECISION = timedelta(minutes=5)
TOKEN_BYTES = 32
# Sensitive commands, such as adding a sign-in method, need the password or a passkey this recently.
RECENT_SIGN_IN = timedelta(minutes=10)


class RecentSignInRequiredError(ForbiddenError):
    code = "recent_sign_in_required"


@dataclass(frozen=True, slots=True)
class Client:
    """Where a request comes from, as the session list shows it."""

    user_agent: str | None
    ip: str | None


@dataclass(slots=True)
class Session:
    # Exactly one of the two: the account's, or a guest link's grant.
    user_id: UUID | None
    token_hash: bytes
    created_at: datetime
    last_seen_at: datetime
    authenticated_at: datetime
    client: Client
    grant_id: UUID | None = None
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=new_id)

    @classmethod
    def start(cls, user_id: UUID, client: Client, now: datetime) -> tuple[Session, str]:
        """A new session of an account and the token for its cookie; only the token's hash is kept."""
        token, token_hash = new_secret()
        session = cls(
            user_id=user_id,
            token_hash=token_hash,
            created_at=now,
            last_seen_at=now,
            authenticated_at=now,
            client=client,
        )
        return session, token

    @classmethod
    def start_guest(cls, grant_id: UUID, client: Client, now: datetime) -> tuple[Session, str]:
        """A new session of a guest link's grant and the token for its cookie."""
        token, token_hash = new_secret()
        session = cls(
            user_id=None,
            grant_id=grant_id,
            token_hash=token_hash,
            created_at=now,
            last_seen_at=now,
            authenticated_at=now,
            client=client,
        )
        return session, token

    def is_active(self, now: datetime) -> bool:
        return (
            self.revoked_at is None
            and now < self.last_seen_at + IDLE_TIMEOUT
            and now < self.created_at + ABSOLUTE_LIFETIME
        )

    def needs_touch(self, now: datetime) -> bool:
        return now - self.last_seen_at >= LAST_SEEN_PRECISION


@dataclass(frozen=True, slots=True)
class CurrentSession:
    """The session a request was made in, and its account."""

    id: UUID
    user_id: UUID
    # When its person last proved who they are in it: signing in, or confirming it is them again.
    authenticated_at: datetime

    def require_recent_sign_in(self, now: datetime) -> None:
        """Refuse a sensitive command in a session whose person has not proved who they are recently."""
        if now - self.authenticated_at > RECENT_SIGN_IN:
            raise RecentSignInRequiredError("confirm it is you first: sign in again with your password or a passkey")


@dataclass(frozen=True, slots=True)
class GuestSession:
    """A session opened with a guest link: it acts as the link, within the link's grant."""

    grant_id: UUID
    link_id: UUID
    home_id: UUID


@dataclass(frozen=True, slots=True)
class DeviceCaller:
    """A request made with a device's token: it acts as the device, within the device's grant."""

    device_id: UUID


@dataclass(frozen=True, slots=True)
class RequestSession:
    """Who is behind a request: an account's session, a guest's, or a device's token."""

    session: CurrentSession | GuestSession | DeviceCaller

    def account(self) -> CurrentSession:
        """The account's session; a guest's or a device's answers as none, since neither opens an account."""
        match self.session:
            case CurrentSession():
                return self.session
            case GuestSession():
                raise UnauthenticatedError("a guest link opens no account: sign in")
            case DeviceCaller():
                raise UnauthenticatedError("a device's token opens no account: sign in")
            case _:
                assert_never(self.session)

    def guest(self) -> GuestSession:
        if not isinstance(self.session, GuestSession):
            raise UnauthenticatedError("this is not a guest's session: open the guest link")
        return self.session

    def actor(self) -> Actor:
        match self.session:
            case CurrentSession():
                return Actor.user(self.session.user_id)
            case GuestSession():
                return Actor.link(self.session.link_id)
            case DeviceCaller():
                return Actor.device(self.session.device_id)
            case _:
                assert_never(self.session)


def new_secret() -> tuple[str, bytes]:
    """A random token to hand out, for a cookie or a link, and the hash to keep of it."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
