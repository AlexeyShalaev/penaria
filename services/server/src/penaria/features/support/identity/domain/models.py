"""Users, homes, roles and grants."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from penaria.features.shared.errors import InvalidError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.permissions import (
    GUEST_GRANT_DURATION,
    PRESET_PERMISSIONS,
    Preset,
)

# The locales the interface and the system's own texts ship in.
LOCALES = frozenset({"en", "ru"})
NAME_MAX_LENGTH = 200


class InvalidHomeError(InvalidError):
    code = "invalid_home"


class PrincipalType(StrEnum):
    USER = "user"
    DEVICE = "device"
    LINK = "link"


@dataclass(slots=True)
class User:
    display_name: str
    locale: str
    id: UUID = field(default_factory=new_id)
    # None until the user has an account: the local user of an install from before sign-in.
    username: str | None = None
    email: str | None = None
    install_admin: bool = False
    disabled_at: datetime | None = None


@dataclass(slots=True)
class Home:
    name: str
    timezone: str
    locale: str
    id: UUID = field(default_factory=new_id)
    version: int = 1

    @classmethod
    def create(cls, name: str, timezone: str, locale: str) -> Home:
        name = name.strip()
        if not name or len(name) > NAME_MAX_LENGTH:
            raise InvalidHomeError("a home needs a name of 1 to 200 characters", params={"field": "name"})
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise InvalidHomeError("unknown time zone", params={"field": "timezone"}) from exc
        if locale not in LOCALES:
            raise InvalidHomeError("unsupported locale", params={"field": "locale", "supported": sorted(LOCALES)})
        return cls(name=name, timezone=timezone, locale=locale)


@dataclass(slots=True)
class Role:
    home_id: UUID
    preset: Preset | None
    name: str | None
    all_permissions: bool
    permissions: frozenset[str]
    guest_view: bool = False
    expiry_required: bool = False
    default_duration: timedelta | None = None
    id: UUID = field(default_factory=new_id)

    @property
    def is_owner(self) -> bool:
        return self.preset is Preset.OWNER


def preset_roles(home_id: UUID) -> dict[Preset, Role]:
    """The roles a new home starts with (docs/design/core-model.md, section 11.1)."""
    return {
        preset: Role(
            home_id=home_id,
            preset=preset,
            name=None,
            all_permissions=preset in (Preset.OWNER, Preset.ADMIN),
            permissions=PRESET_PERMISSIONS[preset],
            guest_view=preset is Preset.GUEST,
            expiry_required=preset is Preset.GUEST,
            default_duration=GUEST_GRANT_DURATION if preset is Preset.GUEST else None,
        )
        for preset in Preset
    }


@dataclass(slots=True)
class Grant:
    home_id: UUID
    principal_type: PrincipalType
    principal_id: UUID
    role_id: UUID
    scope_entity_id: UUID | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=new_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
