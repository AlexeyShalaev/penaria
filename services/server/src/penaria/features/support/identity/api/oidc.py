"""HTTP: signing in with the operator's OpenID Connect provider, and the account's linked identities (sign-in.md, 18).

Each way to start answers with the provider's address for the browser to open, and a cookie that binds the
flow to the browser; the provider sends the browser back to the callback, which redirects to a page.
"""

from datetime import datetime
from typing import Annotated, assert_never
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Body, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.identity.api.account import SecondFactorFields, client_of
from penaria.features.support.identity.api.cookies import OIDC_CALLBACK_PATH, OIDC_COOKIE, SessionCookie
from penaria.features.support.identity.api.people import TokenIn
from penaria.features.support.identity.domain.oidc import ExternalIdentity, ExternalSignIn
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.oidc import (
    CompleteOidc,
    Done,
    ListSignInMethods,
    OidcStarted,
    Refused,
    SecondStep,
    StartOidcInvitation,
    StartOidcLink,
    StartOidcReauthentication,
    StartOidcSignIn,
    UnlinkExternalIdentity,
)

# A page of the install to come back to, such as /homes/<id>/people.
RETURN_TO_MAX_LENGTH = 500
# The web page that says why a sign-in with the provider did not go through.
PROBLEM_PAGE = "/sign-in/external"
SIGN_IN_PAGE = "/sign-in"
# What the provider passes back is short; anything longer is not its answer.
CALLBACK_PARAM_MAX_LENGTH = 2048

API_PREFIX = "/api/v1"
public_router = APIRouter(prefix=API_PREFIX, tags=["sign-in"])
router = APIRouter(prefix=API_PREFIX, tags=["account"], dependencies=[SIGNED_IN])


class OidcConfigOut(BaseModel):
    name: str = Field(description="What the sign-in button calls the provider, such as Authentik")


class AuthConfigOut(BaseModel):
    oidc: OidcConfigOut | None = Field(description="The operator's provider; null when there is none")


class OidcSignInIn(BaseModel):
    locale: str = Field(examples=["en"], description="The language of an account the sign-in may make")
    return_to: str | None = Field(default=None, max_length=RETURN_TO_MAX_LENGTH, description="A page to come back to")


class OidcInvitationIn(TokenIn):
    locale: str = Field(examples=["en"], description="The language of an account the invitation may make")


class OidcLinkIn(BaseModel):
    return_to: str | None = Field(default=None, max_length=RETURN_TO_MAX_LENGTH)


class OidcReauthenticationIn(SecondFactorFields):
    """A code or a recovery code too while the account's authenticator app is on."""

    return_to: str | None = Field(default=None, max_length=RETURN_TO_MAX_LENGTH)


class OidcStartOut(BaseModel):
    url: str = Field(description="Open it in the browser: the provider signs the person in and sends them back")


class ExternalIdentityOut(BaseModel):
    id: UUID
    email: str | None = Field(description="What the provider said when it was linked")
    created_at: datetime

    @classmethod
    def of(cls, identity: ExternalIdentity) -> ExternalIdentityOut:
        return cls(id=identity.id, email=identity.email, created_at=identity.created_at)


class SignInMethodsOut(BaseModel):
    password: bool = Field(description="Whether the account has a password")
    external_identities: list[ExternalIdentityOut] = Field(description="Its identities at the operator's provider")


@public_router.get("/auth/config")
async def auth_config(scope: UnitScopeDep) -> AuthConfigOut:
    """How people may sign in here beyond passwords and passkeys."""
    external = await scope.get(ExternalSignIn)
    return AuthConfigOut(oidc=None if external.provider is None else OidcConfigOut(name=external.name))


@public_router.post("/auth/oidc:sign-in")
async def start_oidc_sign_in(
    body: Annotated[OidcSignInIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> OidcStartOut:
    started = await (await scope.get(StartOidcSignIn)).execute(
        client_of(request), locale=body.locale, return_to=body.return_to
    )
    return await _started(scope, response, started)


@public_router.post("/auth/oidc:accept-invitation")
async def start_oidc_invitation(
    body: Annotated[OidcInvitationIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> OidcStartOut:
    """Accept an invitation with an identity at the provider: its account, or a new one made from it."""
    started = await (await scope.get(StartOidcInvitation)).execute(body.token, client_of(request), locale=body.locale)
    return await _started(scope, response, started)


@public_router.get(
    OIDC_CALLBACK_PATH.removeprefix(API_PREFIX), response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER
)
async def oidc_callback(
    request: Request,
    scope: UnitScopeDep,
    state: Annotated[str | None, Query(max_length=CALLBACK_PARAM_MAX_LENGTH)] = None,
    code: Annotated[str | None, Query(max_length=CALLBACK_PARAM_MAX_LENGTH)] = None,
    error: Annotated[str | None, Query(max_length=CALLBACK_PARAM_MAX_LENGTH)] = None,
) -> RedirectResponse:
    """Where the provider sends the browser back (`PENARIA_PUBLIC_URL` + this path): it redirects to a page."""
    outcome = await (await scope.get(CompleteOidc)).execute(
        state=state, code=code, error=error, binding=request.cookies.get(OIDC_COOKIE), client=client_of(request)
    )
    cookies = await scope.get(SessionCookie)
    match outcome:
        case Done(return_to=return_to, session_token=session_token):
            response = RedirectResponse(return_to, status_code=status.HTTP_303_SEE_OTHER)
            if session_token is not None:
                cookies.set(response, session_token)
        case SecondStep(token=token, expires_at=expires_at, return_to=return_to):
            # In the fragment, which browsers never send to a server or write to its logs.
            fragment = urlencode({"second-factor": token, "until": expires_at.isoformat()})
            page = f"{SIGN_IN_PAGE}?{urlencode({'next': return_to})}#{fragment}"
            response = RedirectResponse(page, status_code=status.HTTP_303_SEE_OTHER)
        case Refused(problem=problem):
            page = f"{PROBLEM_PAGE}?{urlencode({'problem': problem.value})}"
            response = RedirectResponse(page, status_code=status.HTTP_303_SEE_OTHER)
        case _:
            assert_never(outcome)
    cookies.unbind_oidc(response)
    return response


@router.get("/me/sign-in-methods")
async def sign_in_methods(scope: UnitScopeDep) -> SignInMethodsOut:
    methods = await (await scope.get(ListSignInMethods)).execute(await scope.get(CurrentSession))
    return SignInMethodsOut(
        password=methods.has_password,
        external_identities=[ExternalIdentityOut.of(identity) for identity in methods.identities],
    )


@router.post("/me/external-identities:link")
async def start_oidc_link(
    body: Annotated[OidcLinkIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> OidcStartOut:
    """Link the account to an identity at the provider; needs a recent sign-in."""
    started = await (await scope.get(StartOidcLink)).execute(
        await scope.get(CurrentSession), client_of(request), return_to=body.return_to
    )
    return await _started(scope, response, started)


@router.delete("/me/external-identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_external_identity(identity_id: UUID, scope: UnitScopeDep) -> None:
    """Unlink an identity; needs a recent sign-in, and the account keeps another way to sign in."""
    await (await scope.get(UnlinkExternalIdentity)).execute(await scope.get(CurrentSession), identity_id)


@router.post("/me/reauthenticate/oidc")
async def start_oidc_reauthentication(
    body: Annotated[OidcReauthenticationIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> OidcStartOut:
    """Confirm it is you by signing in at the provider again (``second_factor_code_required`` without a code while
    the authenticator app is on)."""
    started = await (await scope.get(StartOidcReauthentication)).execute(
        await scope.get(CurrentSession), client_of(request), proof=body.proof(), return_to=body.return_to
    )
    return await _started(scope, response, started)


async def _started(scope: UnitScopeDep, response: Response, started: OidcStarted) -> OidcStartOut:
    (await scope.get(SessionCookie)).bind_oidc(response, started.binding)
    return OidcStartOut(url=started.url)
