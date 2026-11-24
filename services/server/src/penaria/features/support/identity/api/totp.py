"""HTTP: the signed-in person's second factor: an authenticator app and its recovery codes (sign-in.md, 4.3)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, status
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.identity.api.account import CODE_INPUT_MAX_LENGTH
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.totp import (
    ConfirmTotp,
    GetSecondFactor,
    RegenerateRecoveryCodes,
    StartTotpEnrolment,
    TurnOffTotp,
)

router = APIRouter(prefix="/api/v1", tags=["second factor"], dependencies=[SIGNED_IN])


class SecondFactorOut(BaseModel):
    totp_enabled: bool = Field(description="Whether signing in with the password asks for a code of the app")
    totp_enabled_at: datetime | None
    recovery_codes_left: int | None = Field(description="Unused recovery codes; none while the app is off")
    required: bool = Field(
        description="The account is an owner or an install admin with a password: it must keep a second factor, "
        "an authenticator app or a passkey"
    )
    missing: bool = Field(
        description="Required, and the account has neither: owner-level commands answer 403 second_factor_required "
        "until it adds one"
    )


class TotpEnrolmentOut(BaseModel):
    secret: str = Field(description="The secret in base32, to type into the app by hand")
    uri: str = Field(description="The otpauth:// address, for a QR code")
    expires_at: datetime = Field(description="Confirm with a code before this, or start again")


class TotpCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=CODE_INPUT_MAX_LENGTH, description="A code the app shows")


class RecoveryCodesOut(BaseModel):
    codes: list[str] = Field(description="Ten single-use codes, shown only now; each replaces a code of the app once")


@router.get("/me/second-factor")
async def second_factor(scope: UnitScopeDep) -> SecondFactorOut:
    status_ = await (await scope.get(GetSecondFactor)).execute(await scope.get(CurrentSession))
    return SecondFactorOut(
        totp_enabled=status_.totp_enabled_at is not None,
        totp_enabled_at=status_.totp_enabled_at,
        recovery_codes_left=status_.recovery_codes_left,
        required=status_.required,
        missing=status_.missing,
    )


@router.post("/me/totp")
async def start_totp(scope: UnitScopeDep) -> TotpEnrolmentOut:
    """Start setting up an authenticator app: a new secret, on once a code confirms it. Needs a recent sign-in."""
    enrolment = await (await scope.get(StartTotpEnrolment)).execute(await scope.get(CurrentSession))
    return TotpEnrolmentOut(secret=enrolment.secret, uri=enrolment.uri, expires_at=enrolment.expires_at)


@router.post("/me/totp:confirm")
async def confirm_totp(body: Annotated[TotpCodeIn, Body()], scope: UnitScopeDep) -> RecoveryCodesOut:
    """Turn the app on with its first code; the recovery codes come only in this answer."""
    codes = await (await scope.get(ConfirmTotp)).execute(await scope.get(CurrentSession), body.code)
    return RecoveryCodesOut(codes=codes)


@router.post("/me/totp/recovery-codes")
async def regenerate_recovery_codes(scope: UnitScopeDep) -> RecoveryCodesOut:
    """Ten new recovery codes; the earlier ones stop working. Needs a recent sign-in."""
    return RecoveryCodesOut(
        codes=await (await scope.get(RegenerateRecoveryCodes)).execute(await scope.get(CurrentSession))
    )


@router.delete("/me/totp", status_code=status.HTTP_204_NO_CONTENT)
async def turn_off_totp(scope: UnitScopeDep) -> None:
    """Turn the app off, with its recovery codes. Needs a recent sign-in; an owner or an install admin keeps it
    unless they have a passkey (``409 last_second_factor``)."""
    await (await scope.get(TurnOffTotp)).execute(await scope.get(CurrentSession))
