"""Who performs a command."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

# The install itself has one identity: it is the actor of what it observes, such as a failed sign-in.
SYSTEM_ID = UUID(int=0)


class ActorKind(StrEnum):
    USER = "user"
    DEVICE = "device"
    LINK = "link"
    MODULE = "module"
    HUB = "hub"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Actor:
    kind: ActorKind
    id: UUID
    on_behalf_of: UUID | None = None

    @classmethod
    def user(cls, user_id: UUID) -> Actor:
        return cls(ActorKind.USER, user_id)

    @classmethod
    def device(cls, device_id: UUID) -> Actor:
        """A device or an integration with a token: the device is the principal."""
        return cls(ActorKind.DEVICE, device_id)

    @classmethod
    def link(cls, link_id: UUID) -> Actor:
        """A guest who opened a guest link: the link is the principal."""
        return cls(ActorKind.LINK, link_id)

    @classmethod
    def system(cls) -> Actor:
        return cls(ActorKind.SYSTEM, SYSTEM_ID)

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind.value, "id": str(self.id)}
        if self.on_behalf_of is not None:
            data["on_behalf_of"] = str(self.on_behalf_of)
        return data
