"""The entity aggregate: one node of the home tree and the rules every change to it follows."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from penaria.features.core.registry.domain.kinds import (
    ALLOWED_PARENTS,
    FRESH_FOR,
    MAX_DEPTH,
    ArchiveReason,
    Freshness,
    Kind,
    Privacy,
    Status,
)
from penaria.features.shared.errors import ConflictError, InvalidError, StaleVersionError
from penaria.features.shared.ids import new_id

NAME_MAX_LENGTH = 200
ALIASES_MAX = 20


class InvalidEntityError(InvalidError):
    code = "invalid_entity"


class MisplacedEntityError(InvalidError):
    """The kind may not sit under that parent, or the move would create a cycle or a too deep tree."""

    code = "misplaced_entity"


class ArchivedEntityError(ConflictError):
    code = "entity_archived"


@dataclass(slots=True)
class Entity:
    home_id: UUID
    kind: Kind
    parent_id: UUID | None
    path: tuple[UUID, ...]
    name: str
    aliases: tuple[str, ...] = ()
    quantity: Decimal | None = None
    unit: str | None = None
    status: Status = Status.PRESENT
    privacy: Privacy = Privacy.NORMAL
    verified_at: datetime | None = None
    verified_by: UUID | None = None
    archived_at: datetime | None = None
    archive_reason: ArchiveReason | None = None
    version: int = 1
    id: UUID = field(default_factory=new_id)

    @classmethod
    def create(
        cls,
        *,
        home_id: UUID,
        kind: Kind,
        parent: Entity | None,
        name: str,
        aliases: tuple[str, ...] = (),
        quantity: Decimal | None = None,
        unit: str | None = None,
        privacy: Privacy = Privacy.NORMAL,
    ) -> Entity:
        check_placement(kind, parent, home_id)
        entity_id = new_id()
        return cls(
            id=entity_id,
            home_id=home_id,
            kind=kind,
            parent_id=parent.id if parent else None,
            path=(*(parent.path if parent else ()), entity_id),
            name=clean_name(name),
            aliases=clean_aliases(aliases),
            quantity=check_quantity(quantity),
            unit=unit.strip() or None if unit else None,
            privacy=privacy,
        )

    @property
    def archived(self) -> bool:
        return self.archived_at is not None

    @property
    def depth(self) -> int:
        return len(self.path)

    def expect_version(self, version: int | None) -> None:
        if version is not None and version != self.version:
            raise StaleVersionError(params={"entity_id": str(self.id), "version": self.version})

    def update(
        self,
        *,
        name: str | None = None,
        aliases: tuple[str, ...] | None = None,
        quantity: Decimal | None = None,
        unit: str | None = None,
        status: Status | None = None,
        privacy: Privacy | None = None,
        clear_quantity: bool = False,
    ) -> dict[str, object]:
        """Change the given fields; return what changed, as the journal records it."""
        self._ensure_live()
        changes: dict[str, object] = {}
        if name is not None and (cleaned := clean_name(name)) != self.name:
            changes["name"] = {"from": self.name, "to": cleaned}
            self.name = cleaned
        if aliases is not None and (cleaned_aliases := clean_aliases(aliases)) != self.aliases:
            changes["aliases"] = {"from": list(self.aliases), "to": list(cleaned_aliases)}
            self.aliases = cleaned_aliases
        if clear_quantity or quantity is not None:
            new_quantity = None if clear_quantity else check_quantity(quantity)
            if new_quantity != self.quantity:
                changes["quantity"] = {"from": _num(self.quantity), "to": _num(new_quantity)}
                self.quantity = new_quantity
        if unit is not None and (unit.strip() or None) != self.unit:
            changes["unit"] = {"from": self.unit, "to": unit.strip() or None}
            self.unit = unit.strip() or None
        if status is not None and status != self.status:
            changes["status"] = {"from": self.status.value, "to": status.value}
            self.status = status
        if privacy is not None and privacy != self.privacy:
            changes["privacy"] = {"from": self.privacy.value, "to": privacy.value}
            self.privacy = privacy
        if changes:
            self.version += 1
        return changes

    def move_to(self, parent: Entity, *, subtree_height: int, by: UUID, now: datetime) -> tuple[UUID, ...]:
        """Move under ``parent``; ``subtree_height`` counts the levels below this entity. Returns the old path."""
        self._ensure_live()
        if parent.archived:
            raise ArchivedEntityError(params={"entity_id": str(parent.id)})
        if self.id in parent.path:
            raise MisplacedEntityError("an entity cannot move into its own subtree")
        check_placement(self.kind, parent, self.home_id)
        new_path = (*parent.path, self.id)
        if len(new_path) + subtree_height > MAX_DEPTH:
            raise MisplacedEntityError(f"the tree is at most {MAX_DEPTH} levels deep")
        old_path = self.path
        self.parent_id = parent.id
        self.path = new_path
        # Whoever moves a thing has seen it (section 8).
        self.verified_at = now
        self.verified_by = by
        self.version += 1
        return old_path

    def archive(self, reason: ArchiveReason, now: datetime) -> None:
        self._ensure_live()
        self.archived_at = now
        self.archive_reason = reason
        self.version += 1

    def restore(self) -> None:
        if not self.archived:
            raise ConflictError("the entity is not archived", code="entity_not_archived")
        self.archived_at = None
        self.archive_reason = None
        self.version += 1

    def verify(self, by: UUID, now: datetime) -> None:
        self._ensure_live()
        self.verified_at = now
        self.verified_by = by
        if self.status is Status.MISSING:
            self.status = Status.PRESENT
        self.version += 1

    def freshness(self, now: datetime) -> Freshness:
        return freshness(self.kind, self.status, self.verified_at, now)

    def _ensure_live(self) -> None:
        if self.archived:
            raise ArchivedEntityError(params={"entity_id": str(self.id)})


def check_placement(kind: Kind, parent: Entity | None, home_id: UUID) -> None:
    if parent is not None and parent.home_id != home_id:
        raise MisplacedEntityError("the parent belongs to another home")
    if parent is not None and parent.archived:
        raise ArchivedEntityError(params={"entity_id": str(parent.id)})
    parent_kind = parent.kind if parent else None
    if parent_kind not in ALLOWED_PARENTS[kind]:
        where = "at the top of the home" if parent_kind is None else f"in a {parent_kind.value}"
        raise MisplacedEntityError(
            f"kind {kind.value} cannot sit {where}",
            params={"kind": kind.value, "parent_kind": parent_kind.value if parent_kind else None},
        )
    if parent is not None and parent.depth + 1 > MAX_DEPTH:
        raise MisplacedEntityError(f"the tree is at most {MAX_DEPTH} levels deep")


def freshness(kind: Kind, status: Status, verified_at: datetime | None, now: datetime) -> Freshness:
    fresh_for = FRESH_FOR[kind]
    if status is Status.MISSING:
        return Freshness.DOUBTFUL
    if fresh_for is None:
        return Freshness.FRESH
    if verified_at is None:
        return Freshness.DOUBTFUL
    return Freshness.FRESH if now - verified_at <= fresh_for else Freshness.STALE


def clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > NAME_MAX_LENGTH:
        raise InvalidEntityError(f"a name has 1 to {NAME_MAX_LENGTH} characters", params={"field": "name"})
    return cleaned


def clean_aliases(aliases: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = tuple(dict.fromkeys(a for a in (" ".join(alias.split()) for alias in aliases) if a))
    if len(cleaned) > ALIASES_MAX or any(len(a) > NAME_MAX_LENGTH for a in cleaned):
        raise InvalidEntityError(f"at most {ALIASES_MAX} aliases of up to {NAME_MAX_LENGTH} characters")
    return cleaned


def check_quantity(quantity: Decimal | None) -> Decimal | None:
    if quantity is not None and (not quantity.is_finite() or quantity <= 0):
        raise InvalidEntityError("a quantity is a positive number", params={"field": "quantity"})
    return quantity


def _num(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
