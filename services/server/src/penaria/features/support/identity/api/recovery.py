"""HTTP: getting back into an account and confirming its email, without a session (sign-in.md, 8).

Tokens travel in request bodies, never in the API's paths, so they stay out of access logs.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Request, status
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.support.identity.api.account import PASSWORD_INPUT_MAX_LENGTH, client_of
from penaria.features.support.identity.api.people import TOKEN_INPUT_MAX_LENGTH, TokenIn
from penaria.features.support.identity.domain.mailbox import EMAIL_MAX_LENGTH
from penaria.features.support.identity.domain.passkeys import Passkey
from penaria.features.support.identity.use_cases.email import ConfirmEmail
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.identity.use_cases.recovery import (
    PreviewPasswordReset,
    RequestPasswordReset,
    ResetPassword,
)

router = APIRouter(prefix="/api/v1", tags=["recovery"])


class MailStatusOut(BaseModel):
    enabled: bool = Field(description="Whether the install sends email; without it, links are passed on by hand")


class ResetRequestIn(BaseModel):
    login: str = Field(min_length=1, max_length=EMAIL_MAX_LENGTH, description="A username or a confirmed email")


class ResetPasskeyOut(BaseModel):
    name: str
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def of(cls, passkey: Passkey) -> ResetPasskeyOut:
        return cls(name=passkey.name, created_at=passkey.created_at, last_used_at=passkey.last_used_at)


class ResetPreviewOut(BaseModel):
    username: str
    display_name: str
    passkeys: list[ResetPasskeyOut] = Field(description="They keep working after the reset")


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=1, max_length=TOKEN_INPUT_MAX_LENGTH)
    new_password: str = Field(min_length=1, max_length=PASSWORD_INPUT_MAX_LENGTH)


class ConfirmedEmailOut(BaseModel):
    email: str


@router.get("/mail")
async def mail_status(scope: UnitScopeDep) -> MailStatusOut:
    return MailStatusOut(enabled=await (await scope.get(Postman)).on())


@router.post("/password-reset:request", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    body: Annotated[ResetRequestIn, Body()], request: Request, scope: UnitScopeDep
) -> None:
    """Mail a reset link to the account's confirmed email; the answer is the same for any login."""
    await (await scope.get(RequestPasswordReset)).execute(body.login, client_of(request))


@router.post("/password-reset:preview")
async def preview_password_reset(
    body: Annotated[TokenIn, Body()], request: Request, scope: UnitScopeDep
) -> ResetPreviewOut:
    """Whose password a reset link sets, and the passkeys it leaves; it changes nothing."""
    preview = await (await scope.get(PreviewPasswordReset)).execute(body.token, client_of(request))
    if preview.user.username is None:
        raise RuntimeError(f"the user ({preview.user.id}) of a reset link has no account")
    return ResetPreviewOut(
        username=preview.user.username,
        display_name=preview.user.display_name,
        passkeys=[ResetPasskeyOut.of(passkey) for passkey in preview.passkeys],
    )


@router.post("/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: Annotated[PasswordResetIn, Body()], request: Request, scope: UnitScopeDep) -> None:
    """Set a new password with a reset link; every session of the account ends, its passkeys stay."""
    await (await scope.get(ResetPassword)).execute(body.token, body.new_password, client_of(request))


@router.post("/email-verifications:confirm")
async def confirm_email(body: Annotated[TokenIn, Body()], request: Request, scope: UnitScopeDep) -> ConfirmedEmailOut:
    """Make the address a confirmation link was sent to the account's email."""
    user = await (await scope.get(ConfirmEmail)).execute(body.token, client_of(request))
    if user.email is None:
        raise RuntimeError(f"the user ({user.id}) has no email right after confirming one")
    return ConfirmedEmailOut(email=user.email)
