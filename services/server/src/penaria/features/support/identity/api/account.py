"""HTTP: setting up the install, signing in and out, and the signed-in person's account."""

import ipaddress
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Request, Response, status
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.identity.api.cookies import SessionCookie
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, Session
from penaria.features.support.identity.use_cases.account import (
    ChangePassword,
    GetAccount,
    ListSessions,
    RevokeOtherSessions,
    RevokeSession,
    UpdateAccount,
)
from penaria.features.support.identity.use_cases.sessions import SignIn, SignOut
from penaria.features.support.identity.use_cases.setup import CompleteSetup, NeedsSetup

# What a session keeps of the browser's description of itself.
USER_AGENT_MAX_LENGTH = 512
# Bounds on what a request may carry, so nothing absurd reaches the slow password hash; the domain
# rules (accounts.py) are stricter and answer with a reason the interface can show.
NAME_INPUT_MAX_LENGTH = 200
PASSWORD_INPUT_MAX_LENGTH = 1024

sign_in_router = APIRouter(prefix="/api/v1", tags=["sign-in"])
router = APIRouter(prefix="/api/v1", tags=["account"], dependencies=[SIGNED_IN])


class AccountOut(BaseModel):
    id: UUID
    username: str
    display_name: str
    email: str | None
    locale: str
    install_admin: bool

    @classmethod
    def of(cls, user: User) -> AccountOut:
        if user.username is None:
            raise RuntimeError(f"the user ({user.id}) has no account")
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            locale=user.locale,
            install_admin=user.install_admin,
        )


class SetupStatusOut(BaseModel):
    needed: bool = Field(description="Whether no account can sign in yet, so the setup screen is shown")


class SetupIn(BaseModel):
    token: str = Field(min_length=1, max_length=200, description="The setup token from the server's log")
    username: str = Field(min_length=1, max_length=NAME_INPUT_MAX_LENGTH)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=PASSWORD_INPUT_MAX_LENGTH)
    locale: str = Field(examples=["en"])


class SignInIn(BaseModel):
    username: str = Field(min_length=1, max_length=NAME_INPUT_MAX_LENGTH)
    password: str = Field(min_length=1, max_length=PASSWORD_INPUT_MAX_LENGTH)


class AccountPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    locale: str | None = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_INPUT_MAX_LENGTH)
    new_password: str = Field(min_length=1, max_length=PASSWORD_INPUT_MAX_LENGTH)


class SessionOut(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    user_agent: str | None
    ip: str | None
    current: bool = Field(description="Whether this is the session of the request")

    @classmethod
    def of(cls, session: Session, current: CurrentSession) -> SessionOut:
        return cls(
            id=session.id,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            user_agent=session.client.user_agent,
            ip=session.client.ip,
            current=session.id == current.id,
        )


class RevokedOut(BaseModel):
    revoked: int


@sign_in_router.get("/setup")
async def setup_status(scope: UnitScopeDep) -> SetupStatusOut:
    return SetupStatusOut(needed=await (await scope.get(NeedsSetup)).execute())


@sign_in_router.post("/setup")
async def complete_setup(
    body: Annotated[SetupIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> AccountOut:
    user, token = await (await scope.get(CompleteSetup)).execute(
        token=body.token,
        username=body.username,
        display_name=body.display_name,
        password=body.password,
        locale=body.locale,
        client=_client(request),
    )
    (await scope.get(SessionCookie)).set(response, token)
    return AccountOut.of(user)


@sign_in_router.post("/sign-in")
async def sign_in(
    body: Annotated[SignInIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> AccountOut:
    user, token = await (await scope.get(SignIn)).execute(
        username=body.username, password=body.password, client=_client(request)
    )
    (await scope.get(SessionCookie)).set(response, token)
    return AccountOut.of(user)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(response: Response, scope: UnitScopeDep) -> None:
    await (await scope.get(SignOut)).execute(await scope.get(CurrentSession))
    (await scope.get(SessionCookie)).clear(response)


@router.get("/me")
async def me(scope: UnitScopeDep) -> AccountOut:
    return AccountOut.of(await (await scope.get(GetAccount)).execute(await scope.get(CurrentSession)))


@router.patch("/me")
async def update_me(body: Annotated[AccountPatch, Body()], scope: UnitScopeDep) -> AccountOut:
    user = await (await scope.get(UpdateAccount)).execute(
        await scope.get(CurrentSession), display_name=body.display_name, locale=body.locale
    )
    return AccountOut.of(user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: Annotated[PasswordChangeIn, Body()], scope: UnitScopeDep) -> None:
    await (await scope.get(ChangePassword)).execute(
        await scope.get(CurrentSession), current_password=body.current_password, new_password=body.new_password
    )


@router.get("/me/sessions")
async def list_sessions(scope: UnitScopeDep) -> list[SessionOut]:
    current = await scope.get(CurrentSession)
    sessions = await (await scope.get(ListSessions)).execute(current)
    return [SessionOut.of(session, current) for session in sessions]


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: UUID, response: Response, scope: UnitScopeDep) -> None:
    current = await scope.get(CurrentSession)
    await (await scope.get(RevokeSession)).execute(current, session_id)
    if session_id == current.id:
        (await scope.get(SessionCookie)).clear(response)


@router.post("/me/sessions:revoke-others")
async def revoke_other_sessions(scope: UnitScopeDep) -> RevokedOut:
    return RevokedOut(revoked=await (await scope.get(RevokeOtherSessions)).execute(await scope.get(CurrentSession)))


def _client(request: Request) -> Client:
    user_agent = request.headers.get("user-agent")
    return Client(
        user_agent=None if user_agent is None else user_agent[:USER_AGENT_MAX_LENGTH],
        ip=_ip(request),
    )


def _ip(request: Request) -> str | None:
    # A server on a Unix socket, or a test client, names its peer with something else than an address.
    if request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None
