"""People in a home: who may give whom which access, invitations and guest links (sign-in.md, 6.1 and 6.2)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from penaria.features.shared.access import Access, Permission, PermissionDeniedError
from penaria.features.shared.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.models import Grant, PrincipalType, Role
from penaria.features.support.identity.domain.permissions import GUEST_GRANT_DURATION
from penaria.features.support.identity.domain.sessions import new_secret

INVITATION_DAYS = 7
INVITATION_MAX_DAYS = 30
# A guest link is for a visit; one meant to outlast a season is a family member's access instead.
LINK_MAX_LIFETIME = timedelta(days=90)
# The name of a guest link or a device, which only those who manage the home's people see.
TOKEN_NAME_MAX_LENGTH = 100


class EscalationError(ForbiddenError):
    """The role would give more than the person giving it holds over that place."""

    code = "escalation"


class InvalidGrantError(InvalidError):
    code = "invalid_grant"


class RoleNotFoundError(NotFoundError):
    code = "role_not_found"


class GrantNotFoundError(NotFoundError):
    code = "grant_not_found"


class LastOwnerError(ConflictError):
    """A home always has at least one owner (core-model.md, 3)."""

    code = "last_owner"


class OwnGrantError(ForbiddenError):
    """Nobody changes their own access: a time-limited admin must not lift their own end."""

    code = "own_grant"


class OwnerGrantError(ConflictError):
    """An owner's access is never changed: owners are made by invitation and leave by revocation."""

    code = "owner_grant"


class InvitationNotFoundError(NotFoundError):
    code = "invitation_not_found"


class InvitationExpiredError(ConflictError):
    code = "invitation_expired"


class InvitationUsedError(ConflictError):
    code = "invitation_used"


class InvitationRevokedError(ConflictError):
    code = "invitation_revoked"


class OwnInvitationError(ConflictError):
    code = "own_invitation"


class AlreadyGrantedError(ConflictError):
    """The account already holds this role over this place in the home; the invitation stays unused."""

    code = "already_granted"


class InviterLostAccessError(ConflictError):
    """The person who invited may no longer give this access, so the invitation gives nothing."""

    code = "inviter_lost_access"


class GuestLinkNotFoundError(NotFoundError):
    code = "guest_link_not_found"


class GuestLinkEndedError(ConflictError):
    """The guest link expired or was revoked."""

    code = "guest_link_ended"


class RevokeReason(StrEnum):
    REVOKED = "revoked"
    LEFT = "left"
    TRANSFERRED = "transferred"
    # A guest link whose maker can no longer give it, having lost or changed their own access.
    GIVER_LOST_ACCESS = "giver_lost_access"


def check_can_give(access: Access, role: Role) -> None:
    """Refuse giving ``role`` by someone with ``access`` over the place: no escalation (core-model.md, 11.1).

    The same rule decides who may change or take back a grant: only someone who could have given it.
    """
    refusal = _refusal(access, role)
    if refusal is not None:
        raise refusal


def can_give(access: Access, role: Role) -> bool:
    return _refusal(access, role) is None


def _refusal(access: Access, role: Role) -> ForbiddenError | None:
    if not access.can(Permission.MEMBERS_MANAGE):
        return PermissionDeniedError(Permission.MEMBERS_MANAGE)
    if role.is_owner and not access.owner:
        return EscalationError("only an owner can make or remove owners")
    if role.all_permissions and not access.all_permissions:
        return EscalationError("this role holds every permission, and you do not")
    missing = set() if access.all_permissions else role.permissions - access.permissions
    if missing:
        return EscalationError("this role holds permissions you do not", params={"permissions": sorted(missing)})
    if access.guest_view and not role.guest_view:
        return EscalationError("this role sees more than guest-visible things, and you do not")
    return None


def grant_payload(grant: Grant, role: Role) -> dict[str, Any]:
    """A grant as the journal records it."""
    return {
        "grant_id": str(grant.id),
        "principal_type": grant.principal_type.value,
        "principal_id": str(grant.principal_id),
        "role_id": str(role.id),
        "role": role.preset.value if role.preset else role.name,
        "scope_entity_id": None if grant.scope_entity_id is None else str(grant.scope_entity_id),
        "expires_at": None if grant.expires_at is None else grant.expires_at.isoformat(),
    }


def check_scope(role: Role, scope_entity_id: UUID | None) -> None:
    if role.is_owner and scope_entity_id is not None:
        raise InvalidGrantError("an owner's access covers the whole home", params={"field": "scope_entity_id"})


def grant_expiry(role: Role, requested: datetime | None, now: datetime, *, field: str) -> datetime | None:
    """When a new grant of ``role`` ends: as requested, or the role's default when it requires an end.

    ``field`` names the input that requested it, for the error.
    """
    if role.is_owner:
        if requested is not None:
            raise InvalidGrantError("an owner's access never ends", params={"field": field})
        return None
    if requested is None:
        return now + _default_duration(role) if role.expiry_required else None
    return _future(requested, now, field)


def changed_expiry(role: Role, requested: datetime | None, now: datetime) -> datetime | None:
    """A grant's new end when someone sets it: ``None`` clears it, unless the role requires one."""
    if requested is None:
        if role.expiry_required:
            raise InvalidGrantError("this role's access must end", params={"field": "expires_at"})
        return None
    return _future(requested, now, "expires_at")


def link_expiry(role: Role, requested: datetime | None, now: datetime) -> datetime:
    """A guest link always ends, within 90 days: as requested, or after the role's default.

    A role with guest view need not require an end of the accounts that hold it, yet a link it is
    given through always ends: three days, as the guest preset's, when the role names no default.
    """
    if not role.guest_view:
        raise InvalidGrantError("a guest link gives a role with guest view", params={"field": "role_id"})
    if requested is None:
        return now + (role.default_duration or GUEST_GRANT_DURATION)
    if requested > now + LINK_MAX_LIFETIME:
        raise InvalidGrantError(
            "a guest link works for 90 days at most",
            params={"field": "expires_at", "max_days": LINK_MAX_LIFETIME.days},
        )
    return _future(requested, now, "expires_at")


def check_token_name(name: str) -> str:
    """The name of a guest link or a device."""
    name = name.strip()
    if not name or len(name) > TOKEN_NAME_MAX_LENGTH:
        raise InvalidGrantError(
            f"a name has 1 to {TOKEN_NAME_MAX_LENGTH} characters",
            params={"field": "name", "max_length": TOKEN_NAME_MAX_LENGTH},
        )
    return name


class InvitationState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass(slots=True)
class Invitation:
    home_id: UUID
    token_hash: bytes
    role_id: UUID
    created_by: UUID
    created_at: datetime
    expires_at: datetime
    scope_entity_id: UUID | None = None
    # When the grant it gives ends; None for a grant without end.
    grant_expires_at: datetime | None = None
    # Ownership transfer: the inviter's owner grant is revoked when the invitation is accepted.
    leave_when_accepted: bool = False
    accepted_at: datetime | None = None
    accepted_by: UUID | None = None
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=new_id)

    @classmethod
    def create(
        cls,
        *,
        home_id: UUID,
        role: Role,
        created_by: UUID,
        scope_entity_id: UUID | None,
        valid_days: int,
        grant_expires_at: datetime | None,
        leave_when_accepted: bool,
        now: datetime,
    ) -> tuple[Invitation, str]:
        """A new invitation and the secret token of its link; only the token's hash is kept."""
        check_scope(role, scope_entity_id)
        if leave_when_accepted and not role.is_owner:
            raise InvalidGrantError(
                "only an owner invitation can transfer ownership", params={"field": "leave_when_accepted"}
            )
        grant_ends = grant_expiry(role, grant_expires_at, now, field="grant_expires_at")
        # Days rather than a moment, so a browser whose clock runs ahead is not refused the longest choice.
        if not 1 <= valid_days <= INVITATION_MAX_DAYS:
            raise InvalidGrantError(
                "an invitation is valid for 1 to 30 days",
                params={"field": "valid_days", "max_days": INVITATION_MAX_DAYS},
            )
        ends = now + timedelta(days=valid_days)
        # An invitation never outlives the access it gives.
        if grant_ends is not None:
            ends = min(ends, grant_ends)
        token, token_hash = new_secret()
        invitation = cls(
            home_id=home_id,
            token_hash=token_hash,
            role_id=role.id,
            created_by=created_by,
            created_at=now,
            expires_at=ends,
            scope_entity_id=scope_entity_id,
            grant_expires_at=grant_ends,
            leave_when_accepted=leave_when_accepted,
        )
        return invitation, token

    def state(self, now: datetime) -> InvitationState:
        if self.accepted_at is not None:
            return InvitationState.ACCEPTED
        if self.revoked_at is not None:
            return InvitationState.REVOKED
        if now >= self.expires_at:
            return InvitationState.EXPIRED
        return InvitationState.PENDING

    def check_open(self, now: datetime) -> None:
        """Refuse an invitation that can no longer be accepted, saying why."""
        match self.state(now):
            case InvitationState.ACCEPTED:
                raise InvitationUsedError("this invitation has already been used")
            case InvitationState.REVOKED:
                raise InvitationRevokedError("this invitation was revoked")
            case InvitationState.EXPIRED:
                raise InvitationExpiredError("this invitation has expired")
            case InvitationState.PENDING:
                return

    def grant_for(self, user_id: UUID) -> Grant:
        return Grant(
            home_id=self.home_id,
            principal_type=PrincipalType.USER,
            principal_id=user_id,
            role_id=self.role_id,
            scope_entity_id=self.scope_entity_id,
            expires_at=self.grant_expires_at,
            granted_by=self.created_by,
        )


@dataclass(slots=True)
class Token:
    """A secret that stands for a principal, a guest link or a device; only its hash is kept (sign-in.md, 10)."""

    principal_type: PrincipalType
    principal_id: UUID
    name: str
    token_hash: bytes
    created_at: datetime
    last_used_at: datetime | None = None
    # The address it was last used from.
    last_used_ip: str | None = None
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=new_id)


@dataclass(frozen=True, slots=True)
class GuestLink:
    """A guest link: the grant of a ``link`` principal and the token that opens it."""

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
        expires_at: datetime | None,
        granted_by: UUID,
        now: datetime,
    ) -> tuple[GuestLink, str]:
        """A new guest link and the secret token of its address."""
        link_id = new_id()
        grant = Grant(
            home_id=home_id,
            principal_type=PrincipalType.LINK,
            principal_id=link_id,
            role_id=role.id,
            scope_entity_id=scope_entity_id,
            expires_at=link_expiry(role, expires_at, now),
            granted_by=granted_by,
            created_at=now,
        )
        secret, token_hash = new_secret()
        token = Token(
            principal_type=PrincipalType.LINK,
            principal_id=link_id,
            name=check_token_name(name),
            token_hash=token_hash,
            created_at=now,
        )
        return cls(grant=grant, token=token), secret


def _default_duration(role: Role) -> timedelta:
    if role.default_duration is None:
        raise RuntimeError(f"the role ({role.id}) requires an end but has no default duration")
    return role.default_duration


def _future(moment: datetime, now: datetime, field: str) -> datetime:
    if moment <= now:
        raise InvalidGrantError("the end must be in the future", params={"field": field})
    return moment
