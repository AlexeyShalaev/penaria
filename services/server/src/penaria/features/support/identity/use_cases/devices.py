"""Devices and integrations with a token: making them, listing them, and the requests they make (sign-in.md, 6.3).

A device is revoked through its grant, as a guest link is (``members.RevokeGrant``), and ends with its
giver's ability to give it (``members.disarm_given_by``).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.shared.places import Place, PlaceDirectory
from penaria.features.support.identity.domain.devices import (
    Device,
    GiverAccessEndsError,
    InvalidTokenError,
    is_device_token,
)
from penaria.features.support.identity.domain.members import can_give, check_can_give, grant_payload
from penaria.features.support.identity.domain.models import Role, User
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, DeviceCaller, hash_token
from penaria.features.support.identity.domain.throttle import bearer_token_key, check_not_blocked
from penaria.features.support.identity.use_cases.attempts import count_attempt
from penaria.features.support.identity.use_cases.members import (
    access_in,
    check_place,
    lasting_access_in,
    place_of,
    require_manager,
    require_member,
    role_in,
)


@dataclass(frozen=True, slots=True)
class DeviceView:
    device: Device
    role: Role
    scope: Place | None
    granted_by: User | None


class CreateDevice:
    """A device with a role over a place, and its token, shown only now.

    The token outlives the session that makes it, so making one needs a recent sign-in: a stolen
    session cookie must not turn into access that signing out everywhere does not end.
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(
        self, current: CurrentSession, home_id: UUID, *, name: str, role_id: UUID, scope_entity_id: UUID | None
    ) -> tuple[DeviceView, str]:
        now = datetime.now(UTC)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            role = role_in(await tx.roles.get_many({role_id}), role_id, home_id)
            creator = await tx.users.get(current.user_id)
        current.require_recent_sign_in(now)
        found = await self._places.find(set() if scope_entity_id is None else {scope_entity_id})
        scope = check_place(found, scope_entity_id, home_id)
        device, token = Device.create(
            home_id=home_id,
            role=role,
            name=name,
            scope_entity_id=scope_entity_id,
            granted_by=current.user_id,
            now=now,
        )
        async with self._uow.transaction() as tx:
            # Under the lock that taking the creator's access back takes, so their devices end with it.
            await tx.homes.lock(home_id)
            check_can_give(await access_in(tx, actor, home_id, scope, now), role)
            # Access that ends would otherwise leave behind a token that does not.
            if not can_give(await lasting_access_in(tx, actor, home_id, scope, now), role):
                raise GiverAccessEndsError(
                    "your access to this home ends, and a device's never does: ask someone whose access does not end"
                )
            await tx.grants.add(device.grant)
            await tx.tokens.add(device.token)
            await tx.journal.append(
                [
                    Event(
                        "device.created",
                        home_id,
                        actor,
                        {**grant_payload(device.grant, role), "device_id": str(device.id), "name": device.token.name},
                    )
                ]
            )
        return DeviceView(device=device, role=role, scope=scope, granted_by=creator), token


class ListDevices:
    """The home's devices whose tokens work; for those who manage its people."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID) -> list[DeviceView]:
        now = datetime.now(UTC)
        async with self._uow.query() as tx:
            await require_manager(tx, Actor.user(current.user_id), home_id, now)
            devices = await tx.tokens.devices_in(home_id, now)
            roles = await tx.roles.get_many({device.grant.role_id for device in devices})
            users = await tx.users.get_many({d.grant.granted_by for d in devices if d.grant.granted_by})
        places = await self._places.find({d.grant.scope_entity_id for d in devices if d.grant.scope_entity_id})
        return [
            DeviceView(
                device=device,
                role=roles[device.grant.role_id],
                scope=place_of(places, device.grant.scope_entity_id),
                granted_by=users.get(device.grant.granted_by) if device.grant.granted_by else None,
            )
            for device in devices
        ]


class AuthenticateDevice:
    """The device behind a request's bearer token, while its token and grant still work.

    Tokens that do not exist count against the address, as guessed links do (sign-in.md, 7); a known
    token that was revoked is no guess and does not count, so a forgotten device that keeps calling
    does not make the other devices of its household wait.

    Unlike ``attempts.find_by_secret``, an attempt is counted only once it missed, not before the look-up:
    a device calls every few seconds, and counting first would write on each of its requests. So a burst
    of parallel guesses passes the check until the first of them is counted; with 256-bit tokens, those
    few guesses are no risk.
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, token: str, client: Client) -> DeviceCaller:
        now = datetime.now(UTC)
        key = bearer_token_key(client.ip)
        keys = [] if key is None else [key]
        async with self._uow.transaction() as tx:
            check_not_blocked(await tx.failures.get(keys), now)
            device = await tx.tokens.device_by_token_hash(hash_token(token)) if is_device_token(token) else None
            if device is not None:
                return await _use(tx, device, client, now)
        async with self._uow.transaction() as tx:
            await count_attempt(tx, keys, now)
        raise InvalidTokenError


async def _use(tx: IdentityTransaction, device: Device, client: Client, now: datetime) -> DeviceCaller:
    if not device.is_active(now):
        raise InvalidTokenError
    if device.needs_journal(client.ip, now):
        payload = {"device_id": str(device.id), "ip": client.ip}
        await tx.journal.append([Event("device.used", device.grant.home_id, Actor.device(device.id), payload)])
    if device.needs_touch(now):
        await tx.tokens.used(device.token.id, now, ip=client.ip)
    return DeviceCaller(device_id=device.id)
