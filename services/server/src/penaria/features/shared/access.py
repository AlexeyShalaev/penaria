"""Permissions, and the port through which a feature asks what an actor may do."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from penaria.features.shared.actor import Actor


class Permission(StrEnum):
    ENTITIES_VIEW = "entities.view"
    ENTITIES_VIEW_PRIVATE = "entities.view_private"
    ENTITIES_EDIT = "entities.edit"
    CHANGES_APPLY = "changes.apply"
    DEVICES_CONTROL = "devices.control"
    DEVICES_CONTROL_CRITICAL = "devices.control_critical"
    TASKS_VIEW = "tasks.view"
    TASKS_COMPLETE = "tasks.complete"
    TASKS_MANAGE = "tasks.manage"
    MEMBERS_MANAGE = "members.manage"
    ROLES_MANAGE = "roles.manage"
    MODULES_MANAGE = "modules.manage"
    HOME_MANAGE = "home.manage"


@dataclass(frozen=True, slots=True)
class Access:
    """What an actor may do at one place of a home's tree."""

    permissions: frozenset[str]
    # The owner's rights: owners and deleting the home.
    owner: bool = False
    # Every permission, those that modules add later included.
    all_permissions: bool = False
    # Every grant that applies here sees only guest-visible entities.
    guest_view: bool = False

    def can(self, permission: str) -> bool:
        return self.all_permissions or permission in self.permissions

    @property
    def any(self) -> bool:
        """Whether any grant covers the place at all."""
        return self.all_permissions or bool(self.permissions)


class AccessPolicy(Protocol):
    async def access(self, actor: Actor, home_id: UUID, path: Sequence[UUID]) -> Access:
        """What ``actor`` may do at ``path`` (the ids from the root down); ``()`` is the whole home."""
        ...
