"""Browser sessions: a random token in a cookie, of which the server keeps only a hash (sign-in.md, 5)."""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from penaria.features.shared.ids import new_id

IDLE_TIMEOUT = timedelta(days=30)
ABSOLUTE_LIFETIME = timedelta(days=180)
# Seeing a session again within this time does not write; the idle timeout is far longer.
LAST_SEEN_PRECISION = timedelta(minutes=5)
TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class Client:
    """Where a request comes from, as the session list shows it."""

    user_agent: str | None
    ip: str | None


@dataclass(slots=True)
class Session:
    user_id: UUID
    token_hash: bytes
    created_at: datetime
    last_seen_at: datetime
    authenticated_at: datetime
    client: Client
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=new_id)

    @classmethod
    def start(cls, user_id: UUID, client: Client, now: datetime) -> tuple[Session, str]:
        """A new session and the token for its cookie; only the token's hash is kept."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        session = cls(
            user_id=user_id,
            token_hash=hash_token(token),
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


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
