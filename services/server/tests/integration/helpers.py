"""What the integration tests of the HTTP API share."""

import re
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import FastAPI
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.integrations.postgres.transaction import PenariaTransaction
from tests.authenticator import Authenticator

NewClient = Callable[..., httpx.AsyncClient]
WRONG = "not the password"
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


async def uow_of(container: DishkaContainer) -> AsyncSQLAlchemyUnitOfWork[PenariaTransaction]:
    return await container.container.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])


def from_address(new_client: NewClient, app: FastAPI, ip: str) -> httpx.AsyncClient:
    return new_client(transport=httpx.ASGITransport(app=app, client=(ip, 1)))


def shape(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with its ids replaced by "uuid", so it compares whole."""
    return {
        key: "uuid" if isinstance(value, str) and UUID_PATTERN.match(value) else value for key, value in payload.items()
    }


async def add_passkey(client: httpx.AsyncClient, device: Authenticator, name: str = "Phone") -> httpx.Response:
    started = await client.post("/me/passkeys/options")
    assert started.status_code == 200, started.text
    ceremony = started.json()
    credential = device.create(ceremony["options"])
    return await client.post(
        "/me/passkeys", json={"challenge_id": ceremony["challenge_id"], "credential": credential, "name": name}
    )
