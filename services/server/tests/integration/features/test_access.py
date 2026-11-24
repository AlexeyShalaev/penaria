"""Access through grants: strangers see nothing, guests see only what is meant for them."""

import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.features.core.registry.domain.kinds import Kind, Privacy
from penaria.features.core.registry.use_cases.access import EntityNotFoundError
from penaria.features.core.registry.use_cases.commands import CreateEntity
from penaria.features.core.registry.use_cases.queries import GetEntity, ListChildren
from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import ForbiddenError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.models import Grant, PrincipalType
from penaria.features.support.identity.domain.permissions import Preset
from penaria.features.support.identity.infra.orm import RoleDB
from penaria.features.support.identity.use_cases.homes import CreateHome
from penaria.integrations.postgres.transaction import PenariaTransaction

pytestmark = pytest.mark.integration


async def test_grants_decide_what_others_see(container: DishkaContainer) -> None:
    owner, stranger, guest = Actor.user(new_id()), Actor.user(new_id()), Actor.user(new_id())
    async with container.app_scope() as scope:
        create = await scope.get(CreateEntity)
        home = await (await scope.get(CreateHome)).execute(owner, name="Flat", timezone="UTC", locale="en")
        flat = await create.execute(owner, home_id=home.id, kind=Kind.PROPERTY, parent_id=None, name="Flat")
        bathroom = await create.execute(owner, home_id=home.id, kind=Kind.SPACE, parent_id=flat.id, name="Bathroom")
        towels = await create.execute(
            owner,
            home_id=home.id,
            kind=Kind.ITEM,
            parent_id=bathroom.id,
            name="Towels",
            privacy=Privacy.GUEST_VISIBLE,
        )
        safe = await create.execute(
            owner, home_id=home.id, kind=Kind.CONTAINER, parent_id=bathroom.id, name="Safe", privacy=Privacy.PRIVATE
        )
        await create.execute(owner, home_id=home.id, kind=Kind.ITEM, parent_id=bathroom.id, name="Hair dryer")

        uow = await scope.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])
        async with uow.transaction() as tx:
            guest_role = await tx.session.scalar(
                RoleDB.__table__.select().where(RoleDB.home_id == home.id, RoleDB.preset == Preset.GUEST.value)
            )
            assert guest_role is not None
            await tx.grants.add(
                Grant(
                    home_id=home.id,
                    principal_type=PrincipalType.USER,
                    principal_id=guest.id,
                    role_id=guest_role,
                    scope_entity_id=flat.id,
                )
            )

        get, children = await scope.get(GetEntity), await scope.get(ListChildren)

        with pytest.raises(EntityNotFoundError):
            await get.execute(stranger, towels.id)
        with pytest.raises(ForbiddenError):
            await create.execute(stranger, home_id=home.id, kind=Kind.PROPERTY, parent_id=None, name="Mine")

        assert (await get.execute(guest, towels.id)).entity.name == "Towels"
        # The bathroom is on the way to the towels; the hair dryer is not for guests.
        assert (await get.execute(guest, bathroom.id)).entity.name == "Bathroom"
        with pytest.raises(EntityNotFoundError):
            await get.execute(guest, safe.id)
        listed = await children.execute(guest, home_id=home.id, parent_id=bathroom.id)
        assert [entity.name for entity, _ in listed] == ["Towels"]
        with pytest.raises(ForbiddenError):
            await create.execute(guest, home_id=home.id, kind=Kind.ITEM, parent_id=bathroom.id, name="Soap")

        owner_view = await children.execute(owner, home_id=home.id, parent_id=bathroom.id)
        assert [entity.name for entity, _ in owner_view] == ["Hair dryer", "Safe", "Towels"]
