"""HTTP: the actor's homes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, status
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.access import Access
from penaria.features.shared.actor import Actor
from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.identity.domain.models import Home
from penaria.features.support.identity.use_cases.homes import CreateHome, GetHome, ListHomes

router = APIRouter(prefix="/api/v1", tags=["homes"], dependencies=[SIGNED_IN])


class AccessOut(BaseModel):
    owner: bool
    all_permissions: bool
    permissions: list[str]

    @classmethod
    def of(cls, access: Access) -> AccessOut:
        return cls(owner=access.owner, all_permissions=access.all_permissions, permissions=sorted(access.permissions))


class HomeOut(BaseModel):
    id: UUID
    name: str
    timezone: str
    locale: str
    version: int
    access: AccessOut | None = None

    @classmethod
    def of(cls, home: Home, access: Access | None = None) -> HomeOut:
        return cls(
            id=home.id,
            name=home.name,
            timezone=home.timezone,
            locale=home.locale,
            version=home.version,
            access=AccessOut.of(access) if access else None,
        )


class HomeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(examples=["Europe/Moscow"])
    locale: str = Field(examples=["ru"])


@router.get("/homes")
async def list_homes(scope: UnitScopeDep) -> list[HomeOut]:
    homes = await (await scope.get(ListHomes)).execute(await scope.get(Actor))
    return [HomeOut.of(home) for home in homes]


@router.post("/homes", status_code=status.HTTP_201_CREATED)
async def create_home(body: Annotated[HomeIn, Body()], scope: UnitScopeDep) -> HomeOut:
    actor = await scope.get(Actor)
    home = await (await scope.get(CreateHome)).execute(
        actor, name=body.name, timezone=body.timezone, locale=body.locale
    )
    _, access = await (await scope.get(GetHome)).execute(actor, home.id)
    return HomeOut.of(home, access)


@router.get("/homes/{home_id}")
async def get_home(home_id: UUID, scope: UnitScopeDep) -> HomeOut:
    home, access = await (await scope.get(GetHome)).execute(await scope.get(Actor), home_id)
    return HomeOut.of(home, access)
