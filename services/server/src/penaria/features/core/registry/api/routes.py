"""HTTP: the home tree."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Query, status
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.core.registry.domain.kinds import ArchiveReason, Freshness, Kind, Privacy, Status
from penaria.features.core.registry.use_cases.commands import (
    ArchiveEntity,
    CreateEntity,
    MoveEntity,
    RestoreEntity,
    UpdateEntity,
    VerifyEntity,
)
from penaria.features.core.registry.use_cases.queries import EntityHistory, EntityView, GetEntity, ListChildren
from penaria.features.shared.access import Permission
from penaria.features.shared.actor import Actor

router = APIRouter(prefix="/api/v1", tags=["entities"])


class PlaceOut(BaseModel):
    id: UUID
    name: str
    kind: Kind


class EntityOut(BaseModel):
    id: UUID
    home_id: UUID
    kind: Kind
    parent_id: UUID | None
    name: str
    aliases: list[str]
    quantity: Decimal | None
    unit: str | None
    status: Status
    privacy: Privacy
    verified_at: datetime | None
    archived_at: datetime | None
    archive_reason: ArchiveReason | None
    version: int
    freshness: Freshness
    children: int

    @classmethod
    def of(cls, entity: Entity, children: int) -> EntityOut:
        return cls(
            id=entity.id,
            home_id=entity.home_id,
            kind=entity.kind,
            parent_id=entity.parent_id,
            name=entity.name,
            aliases=list(entity.aliases),
            quantity=entity.quantity,
            unit=entity.unit,
            status=entity.status,
            privacy=entity.privacy,
            verified_at=entity.verified_at,
            archived_at=entity.archived_at,
            archive_reason=entity.archive_reason,
            version=entity.version,
            freshness=entity.freshness(datetime.now(UTC)),
            children=children,
        )


class EntityDetailOut(EntityOut):
    path: list[PlaceOut] = Field(description="The places above the entity, from the top of the home down")
    can_edit: bool

    @classmethod
    def of_view(cls, view: EntityView) -> EntityDetailOut:
        return cls(
            **EntityOut.of(view.entity, view.children).model_dump(),
            path=[PlaceOut(id=e.id, name=e.name, kind=e.kind) for e in view.ancestors],
            can_edit=view.access.can(Permission.ENTITIES_EDIT),
        )


class EntityIn(BaseModel):
    kind: Kind
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = None
    privacy: Privacy = Privacy.NORMAL


class EntityPatch(BaseModel):
    version: int = Field(description="The version the change is based on; a newer one answers 409")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = Field(default=None, max_length=20)
    quantity: Decimal | None = Field(default=None, gt=0, description="null clears it")
    unit: str | None = None
    status: Status | None = None
    privacy: Privacy | None = None


class MoveIn(BaseModel):
    parent_id: UUID
    version: int


class ArchiveIn(BaseModel):
    reason: ArchiveReason
    version: int


class VersionIn(BaseModel):
    version: int


class EventOut(BaseModel):
    id: UUID
    type: str
    at: datetime
    actor: dict[str, Any]
    payload: dict[str, Any]


async def _detail(scope: UnitScopeDep, actor: Actor, entity_id: UUID) -> EntityDetailOut:
    return EntityDetailOut.of_view(await (await scope.get(GetEntity)).execute(actor, entity_id))


@router.get("/homes/{home_id}/entities")
async def list_entities(
    home_id: UUID,
    scope: UnitScopeDep,
    parent_id: Annotated[UUID | None, Query(description="Omit for the tops of the home")] = None,
    include_archived: bool = False,
) -> list[EntityOut]:
    children = await (await scope.get(ListChildren)).execute(
        await scope.get(Actor), home_id=home_id, parent_id=parent_id, include_archived=include_archived
    )
    return [EntityOut.of(entity, count) for entity, count in children]


@router.post("/homes/{home_id}/entities", status_code=status.HTTP_201_CREATED)
async def create_entity(home_id: UUID, body: Annotated[EntityIn, Body()], scope: UnitScopeDep) -> EntityDetailOut:
    actor = await scope.get(Actor)
    entity = await (await scope.get(CreateEntity)).execute(
        actor,
        home_id=home_id,
        kind=body.kind,
        parent_id=body.parent_id,
        name=body.name,
        aliases=body.aliases,
        quantity=body.quantity,
        unit=body.unit,
        privacy=body.privacy,
    )
    return await _detail(scope, actor, entity.id)


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: UUID, scope: UnitScopeDep) -> EntityDetailOut:
    return await _detail(scope, await scope.get(Actor), entity_id)


@router.patch("/entities/{entity_id}")
async def update_entity(entity_id: UUID, body: Annotated[EntityPatch, Body()], scope: UnitScopeDep) -> EntityDetailOut:
    actor = await scope.get(Actor)
    await (await scope.get(UpdateEntity)).execute(
        actor,
        entity_id,
        version=body.version,
        name=body.name,
        aliases=body.aliases,
        quantity=body.quantity,
        clear_quantity="quantity" in body.model_fields_set and body.quantity is None,
        unit=body.unit,
        status=body.status,
        privacy=body.privacy,
    )
    return await _detail(scope, actor, entity_id)


@router.post("/entities/{entity_id}:move")
async def move_entity(entity_id: UUID, body: Annotated[MoveIn, Body()], scope: UnitScopeDep) -> EntityDetailOut:
    actor = await scope.get(Actor)
    await (await scope.get(MoveEntity)).execute(actor, entity_id, parent_id=body.parent_id, version=body.version)
    return await _detail(scope, actor, entity_id)


@router.post("/entities/{entity_id}:archive")
async def archive_entity(entity_id: UUID, body: Annotated[ArchiveIn, Body()], scope: UnitScopeDep) -> EntityDetailOut:
    actor = await scope.get(Actor)
    await (await scope.get(ArchiveEntity)).execute(actor, entity_id, reason=body.reason, version=body.version)
    return await _detail(scope, actor, entity_id)


@router.post("/entities/{entity_id}:restore")
async def restore_entity(entity_id: UUID, body: Annotated[VersionIn, Body()], scope: UnitScopeDep) -> EntityDetailOut:
    actor = await scope.get(Actor)
    await (await scope.get(RestoreEntity)).execute(actor, entity_id, version=body.version)
    return await _detail(scope, actor, entity_id)


@router.post("/entities/{entity_id}:verify")
async def verify_entity(entity_id: UUID, scope: UnitScopeDep) -> EntityDetailOut:
    actor = await scope.get(Actor)
    await (await scope.get(VerifyEntity)).execute(actor, entity_id)
    return await _detail(scope, actor, entity_id)


@router.get("/entities/{entity_id}/history")
async def entity_history(
    entity_id: UUID, scope: UnitScopeDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[EventOut]:
    events = await (await scope.get(EntityHistory)).execute(await scope.get(Actor), entity_id, limit=limit)
    return [EventOut(id=e.id, type=e.type, at=e.at, actor=e.actor, payload=e.payload) for e in events]
