"""HTTP: a home's devices and integrations, and the bearer token their requests carry (sign-in.md, 6.3)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Request, status
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.identity.api.people import PersonOut, PlaceRefOut, RoleOut
from penaria.features.support.identity.domain.devices import TOKEN_PREFIX
from penaria.features.support.identity.domain.members import TOKEN_NAME_MAX_LENGTH
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.devices import CreateDevice, DeviceView, ListDevices

router = APIRouter(prefix="/api/v1", tags=["devices"], dependencies=[SIGNED_IN])


def device_token_of(request: Request) -> str | None:
    """The device token the request carries as ``Authorization: Bearer pnr_…``, if any.

    Such a request is judged by the token alone, never by a cookie. Any other ``Authorization``
    header, such as the basic auth of a reverse proxy in front of the install, is not Penaria's:
    the request is then judged by its cookie, as if the header were not there.
    """
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, credentials = header.partition(" ")
    credentials = credentials.strip()
    if scheme.lower() != "bearer" or not credentials.startswith(TOKEN_PREFIX):
        return None
    return credentials


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=TOKEN_NAME_MAX_LENGTH, examples=["Hallway mirror"])
    role_id: UUID = Field(description="Any role but the owner's and those whose access must end")
    scope_entity_id: UUID | None = Field(default=None, description="Omit for the whole home")


class DeviceOut(BaseModel):
    id: UUID
    grant_id: UUID = Field(description="Revoke it to end the device's access at once")
    name: str
    role: RoleOut
    scope: PlaceRefOut | None
    created_at: datetime
    last_used_at: datetime | None
    last_used_ip: str | None = Field(description="The address it was last used from")
    granted_by: PersonOut | None

    @classmethod
    def of(cls, view: DeviceView) -> DeviceOut:
        grant, token = view.device.grant, view.device.token
        return cls(
            id=view.device.id,
            grant_id=grant.id,
            name=token.name,
            role=RoleOut.of(view.role),
            scope=PlaceRefOut.of(view.scope),
            created_at=grant.created_at,
            last_used_at=token.last_used_at,
            last_used_ip=token.last_used_ip,
            granted_by=None if view.granted_by is None else PersonOut.of(view.granted_by),
        )


class CreatedDeviceOut(BaseModel):
    device: DeviceOut
    token: str = Field(description="Send it as `Authorization: Bearer <token>`; shown only now")


@router.get("/homes/{home_id}/devices")
async def list_devices(home_id: UUID, scope: UnitScopeDep) -> list[DeviceOut]:
    views = await (await scope.get(ListDevices)).execute(await scope.get(CurrentSession), home_id)
    return [DeviceOut.of(view) for view in views]


@router.post("/homes/{home_id}/devices", status_code=status.HTTP_201_CREATED)
async def create_device(home_id: UUID, body: Annotated[DeviceIn, Body()], scope: UnitScopeDep) -> CreatedDeviceOut:
    """A device or an integration with its token, shown only now; needs a recent sign-in.
    Revoking its grant (``DELETE /homes/{id}/grants/{grant_id}``) ends its access at once."""
    view, token = await (await scope.get(CreateDevice)).execute(
        await scope.get(CurrentSession),
        home_id,
        name=body.name,
        role_id=body.role_id,
        scope_entity_id=body.scope_entity_id,
    )
    return CreatedDeviceOut(device=DeviceOut.of(view), token=token)
