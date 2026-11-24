"""HTTP: signing in with a passkey, the signed-in person's passkeys, and confirming it is them with one.

A ceremony takes two requests: the first gives out a challenge with the options for
``navigator.credentials``, the second brings back the browser's answer with the challenge's id.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.identity.api.account import AccountOut, client_of
from penaria.features.support.identity.api.cookies import SessionCookie
from penaria.features.support.identity.domain.passkeys import NAME_MAX_LENGTH, Passkey, PasskeyOptions
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.passkeys import (
    AddPasskey,
    ListPasskeys,
    RemovePasskey,
    RenamePasskey,
    StartPasskeyRegistration,
)
from penaria.features.support.identity.use_cases.reauthentication import (
    ReauthenticateWithPasskey,
    StartPasskeyReauthentication,
)
from penaria.features.support.identity.use_cases.sessions import SignInWithPasskey, StartPasskeySignIn

# Bounds on what a browser's answer may carry: base64url of a few kilobytes at most, even with
# an attestation certificate chain.
ENCODED_MAX_LENGTH = 16_384
# WebAuthn names six transports, the longest ten letters ("smart-card"); room for a few more.
TRANSPORTS_MAX = 10
TRANSPORT_MAX_LENGTH = 32

sign_in_router = APIRouter(prefix="/api/v1", tags=["sign-in"])
router = APIRouter(prefix="/api/v1", tags=["passkeys"], dependencies=[SIGNED_IN])

Encoded = Annotated[str, Field(min_length=1, max_length=ENCODED_MAX_LENGTH, description="base64url")]


class _WebAuthnJson(BaseModel):
    # The browser's names, as PublicKeyCredential.toJSON() writes them.
    model_config = ConfigDict(serialize_by_alias=True)


class AttestationResponseIn(_WebAuthnJson):
    client_data_json: Encoded = Field(alias="clientDataJSON")
    attestation_object: Encoded = Field(alias="attestationObject")
    transports: list[Annotated[str, Field(max_length=TRANSPORT_MAX_LENGTH)]] = Field(
        default=[], max_length=TRANSPORTS_MAX
    )


class AssertionResponseIn(_WebAuthnJson):
    client_data_json: Encoded = Field(alias="clientDataJSON")
    authenticator_data: Encoded = Field(alias="authenticatorData")
    signature: Encoded
    user_handle: Encoded | None = Field(default=None, alias="userHandle")


class RegistrationCredentialIn(_WebAuthnJson):
    """A new credential, as ``navigator.credentials.create`` gives it, in JSON."""

    id: Encoded
    raw_id: Encoded = Field(alias="rawId")
    type: Literal["public-key"]
    response: AttestationResponseIn


class AuthenticationCredentialIn(_WebAuthnJson):
    """An answer to a challenge, as ``navigator.credentials.get`` gives it, in JSON."""

    id: Encoded
    raw_id: Encoded = Field(alias="rawId")
    type: Literal["public-key"]
    response: AssertionResponseIn


class PasskeyOptionsOut(BaseModel):
    challenge_id: UUID = Field(description="Send it back with the browser's answer")
    options: dict[str, Any] = Field(
        description="PublicKeyCredentialCreationOptionsJSON or PublicKeyCredentialRequestOptionsJSON (WebAuthn)"
    )

    @classmethod
    def of(cls, ceremony: PasskeyOptions) -> PasskeyOptionsOut:
        return cls(challenge_id=ceremony.challenge_id, options=ceremony.options)


class PasskeySignInIn(BaseModel):
    challenge_id: UUID
    credential: AuthenticationCredentialIn


class PasskeyIn(BaseModel):
    challenge_id: UUID
    credential: RegistrationCredentialIn
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH, description="How the person tells it apart")


class PasskeyPatch(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class PasskeyReauthenticationIn(BaseModel):
    challenge_id: UUID
    credential: AuthenticationCredentialIn


class PasskeyOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def of(cls, passkey: Passkey) -> PasskeyOut:
        return cls(id=passkey.id, name=passkey.name, created_at=passkey.created_at, last_used_at=passkey.last_used_at)


@sign_in_router.post("/sign-in/passkey/options")
async def passkey_sign_in_options(request: Request, scope: UnitScopeDep) -> PasskeyOptionsOut:
    """An address may hold 10 sign-ins that are neither finished nor expired (``too_many_attempts``)."""
    return PasskeyOptionsOut.of(await (await scope.get(StartPasskeySignIn)).execute(client_of(request)))


@sign_in_router.post("/sign-in/passkey")
async def sign_in_with_passkey(
    body: Annotated[PasskeySignInIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> AccountOut:
    user, token = await (await scope.get(SignInWithPasskey)).execute(
        challenge_id=body.challenge_id, credential=body.credential.model_dump(), client=client_of(request)
    )
    (await scope.get(SessionCookie)).set(response, token)
    return AccountOut.of(user)


@router.get("/me/passkeys")
async def list_passkeys(scope: UnitScopeDep) -> list[PasskeyOut]:
    passkeys = await (await scope.get(ListPasskeys)).execute(await scope.get(CurrentSession))
    return [PasskeyOut.of(passkey) for passkey in passkeys]


@router.post("/me/passkeys/options")
async def passkey_registration_options(scope: UnitScopeDep) -> PasskeyOptionsOut:
    """Needs a recent sign-in (``recent_sign_in_required``)."""
    return PasskeyOptionsOut.of(
        await (await scope.get(StartPasskeyRegistration)).execute(await scope.get(CurrentSession))
    )


@router.post("/me/passkeys", status_code=status.HTTP_201_CREATED)
async def add_passkey(body: Annotated[PasskeyIn, Body()], scope: UnitScopeDep) -> PasskeyOut:
    """Needs a recent sign-in (``recent_sign_in_required``)."""
    passkey = await (await scope.get(AddPasskey)).execute(
        await scope.get(CurrentSession),
        challenge_id=body.challenge_id,
        credential=body.credential.model_dump(),
        name=body.name,
    )
    return PasskeyOut.of(passkey)


@router.patch("/me/passkeys/{passkey_id}")
async def rename_passkey(passkey_id: UUID, body: Annotated[PasskeyPatch, Body()], scope: UnitScopeDep) -> PasskeyOut:
    passkey = await (await scope.get(RenamePasskey)).execute(await scope.get(CurrentSession), passkey_id, body.name)
    return PasskeyOut.of(passkey)


@router.delete("/me/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_passkey(passkey_id: UUID, scope: UnitScopeDep) -> None:
    """Needs a recent sign-in (``recent_sign_in_required``)."""
    await (await scope.get(RemovePasskey)).execute(await scope.get(CurrentSession), passkey_id)


@router.post("/me/reauthenticate/passkey/options")
async def passkey_reauthentication_options(scope: UnitScopeDep) -> PasskeyOptionsOut:
    return PasskeyOptionsOut.of(
        await (await scope.get(StartPasskeyReauthentication)).execute(await scope.get(CurrentSession))
    )


@router.post("/me/reauthenticate/passkey", status_code=status.HTTP_204_NO_CONTENT)
async def reauthenticate_with_passkey(body: Annotated[PasskeyReauthenticationIn, Body()], scope: UnitScopeDep) -> None:
    await (await scope.get(ReauthenticateWithPasskey)).execute(
        await scope.get(CurrentSession), challenge_id=body.challenge_id, credential=body.credential.model_dump()
    )
