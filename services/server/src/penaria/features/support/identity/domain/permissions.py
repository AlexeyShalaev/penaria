"""The permission catalogue's implications and the roles every new home starts with."""

from collections.abc import Iterable
from datetime import timedelta
from enum import StrEnum

from penaria.features.shared.access import Permission

# Ticking a permission ticks what it implies (docs/design/core-model.md, section 11.1).
IMPLIES: dict[str, frozenset[str]] = {
    Permission.ENTITIES_VIEW_PRIVATE: frozenset({Permission.ENTITIES_VIEW}),
    Permission.ENTITIES_EDIT: frozenset({Permission.ENTITIES_VIEW}),
    Permission.CHANGES_APPLY: frozenset({Permission.ENTITIES_EDIT}),
    Permission.DEVICES_CONTROL: frozenset({Permission.ENTITIES_VIEW}),
    Permission.DEVICES_CONTROL_CRITICAL: frozenset({Permission.DEVICES_CONTROL}),
    Permission.TASKS_VIEW: frozenset({Permission.ENTITIES_VIEW}),
    Permission.TASKS_COMPLETE: frozenset({Permission.TASKS_VIEW}),
    Permission.TASKS_MANAGE: frozenset({Permission.TASKS_COMPLETE}),
    Permission.MEMBERS_MANAGE: frozenset({Permission.ENTITIES_VIEW}),
    Permission.ROLES_MANAGE: frozenset({Permission.MEMBERS_MANAGE}),
    Permission.MODULES_MANAGE: frozenset({Permission.ENTITIES_VIEW}),
    Permission.HOME_MANAGE: frozenset({Permission.ENTITIES_VIEW}),
}


def with_implied(permissions: Iterable[str]) -> frozenset[str]:
    """The permissions together with everything they imply, transitively."""
    result: set[str] = set()
    pending = list(permissions)
    while pending:
        permission = pending.pop()
        if permission not in result:
            result.add(permission)
            pending.extend(IMPLIES.get(permission, ()))
    return frozenset(result)


class Preset(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    FAMILY = "family"
    GUEST = "guest"
    CONTRACTOR = "contractor"


GUEST_GRANT_DURATION = timedelta(days=3)

PRESET_PERMISSIONS: dict[Preset, frozenset[str]] = {
    Preset.OWNER: frozenset(),  # all permissions
    Preset.ADMIN: frozenset(),  # all permissions
    Preset.FAMILY: with_implied(
        {Permission.ENTITIES_EDIT, Permission.CHANGES_APPLY, Permission.DEVICES_CONTROL, Permission.TASKS_COMPLETE}
    ),
    Preset.GUEST: with_implied({Permission.ENTITIES_VIEW, Permission.DEVICES_CONTROL}),
    Preset.CONTRACTOR: with_implied({Permission.TASKS_COMPLETE}),
}
