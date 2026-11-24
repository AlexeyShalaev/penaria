"""Devices and integrations: a ``device`` principal with a grant, and its bearer token (sign-in.md, 6.3).

A smart mirror or a backup script holds a token, ``pnr_`` and 43 letters and digits; only its hash is kept.
The token never expires on its own; revoking the device's grant revokes it.
"""

import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from penaria.features.shared.errors import UnauthenticatedError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.members import InvalidGrantError, Token, check_scope, check_token_name
from penaria.features.support.identity.domain.models import Grant, PrincipalType, Role
from penaria.features.support.identity.domain.sessions import LAST_SEEN_PRECISION, hash_token
from penaria.features.support.identity.domain.throttle import address_key

# The prefix lets secret scanners recognise a leaked token; 43 characters of 62 carry 256 bits, as every
# other secret of the install does.
TOKEN_PREFIX = "pnr_"  # noqa: S105 - the public prefix of every device token, not a secret
TOKEN_ALPHABET = string.ascii_letters + string.digits
TOKEN_LENGTH = 43
TOKEN_PATTERN = re.compile(rf"{TOKEN_PREFIX}[0-9A-Za-z]{{{TOKEN_LENGTH}}}")
# A device's use is journalled when it is the first, comes after this long without use, or comes from
# another address; the uses in between only move its "last used".
USE_JOURNALLED_AFTER = timedelta(days=1)


class InvalidTokenError(UnauthenticatedError):
    """The bearer token is unknown, malformed or revoked; the same answer for each."""

    code = "invalid_token"


def is_device_token(value: str) -> bool:
    """Whether the value has a device token's form; anything else is not one of ours."""
    return TOKEN_PATTERN.fullmatch(value) is not None


def check_device_role(role: Role) -> None:
    """Refuse a role a device cannot hold: an owner's, or one whose access must end, since a device's never does."""
    if role.is_owner:
        raise InvalidGrantError("a device cannot be an owner", params={"field": "role_id", "reason": "device_role"})
    if role.expiry_required:
        raise InvalidGrantError(
            "this role's access must end, and a device's never does",
            params={"field": "role_id", "reason": "device_role"},
        )


@dataclass(frozen=True, slots=True)
class Device:
    """A device or an integration: the grant of a ``device`` principal and the token it uses."""

    grant: Grant
    token: Token

    @property
    def id(self) -> UUID:
        return self.grant.principal_id

    @classmethod
    def create(
        cls,
        *,
        home_id: UUID,
        role: Role,
        name: str,
        scope_entity_id: UUID | None,
        granted_by: UUID,
        now: datetime,
    ) -> tuple[Device, str]:
        """A new device and its token, shown only now."""
        check_device_role(role)
        check_scope(role, scope_entity_id)
        device_id = new_id()
        grant = Grant(
            home_id=home_id,
            principal_type=PrincipalType.DEVICE,
            principal_id=device_id,
            role_id=role.id,
            scope_entity_id=scope_entity_id,
            granted_by=granted_by,
            created_at=now,
        )
        secret = TOKEN_PREFIX + "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
        token = Token(
            principal_type=PrincipalType.DEVICE,
            principal_id=device_id,
            name=check_token_name(name),
            token_hash=hash_token(secret),
            created_at=now,
        )
        return cls(grant=grant, token=token), secret

    def is_active(self, now: datetime) -> bool:
        return self.token.revoked_at is None and self.grant.is_active(now)

    def use_to_record(self, ip: str | None, now: datetime) -> bool:
        """Whether this use moves the device's "last used": now and then, or at once from another address."""
        last = self.token.last_used_at
        return last is None or now - last >= LAST_SEEN_PRECISION or self._moved(ip)

    def use_to_journal(self, ip: str | None, now: datetime) -> bool:
        """Whether this use goes to the journal: the first, the first after a quiet day, or from another address."""
        last = self.token.last_used_at
        return last is None or now - last >= USE_JOURNALLED_AFTER or self._moved(ip)

    def _moved(self, ip: str | None) -> bool:
        # Compared as counter keys, so a phone's changing IPv6 address within its /64 is the same place.
        return address_key(ip) != address_key(self.token.last_used_ip)
