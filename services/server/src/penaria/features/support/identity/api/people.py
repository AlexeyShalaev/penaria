"""HTTP: a home's people, invitations and guest links (sign-in.md, 6.1 and 6.2).

Secret tokens travel in request bodies, never in the API's paths, so they stay out of access logs.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Request, Response, status
from pydantic import AwareDatetime, BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.http import SIGNED_IN
from penaria.features.shared.places import Place
from penaria.features.support.identity.api.account import (
    NAME_INPUT_MAX_LENGTH,
    PASSWORD_INPUT_MAX_LENGTH,
    AccountOut,
    client_of,
)
from penaria.features.support.identity.api.cookies import SESSION_COOKIE, SessionCookie
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.domain.mailbox import EMAIL_MAX_LENGTH
from penaria.features.support.identity.domain.members import (
    INVITATION_DAYS,
    INVITATION_MAX_DAYS,
    LINK_NAME_MAX_LENGTH,
)
from penaria.features.support.identity.domain.models import Home, Role, User
from penaria.features.support.identity.domain.permissions import Preset
from penaria.features.support.identity.domain.sessions import CurrentSession, GuestSession
from penaria.features.support.identity.use_cases.guest_links import (
    CreateGuestLink,
    GetGuestView,
    GuestLinkView,
    GuestView,
    ListGuestLinks,
    OpenGuestLink,
)
from penaria.features.support.identity.use_cases.invitations import (
    AcceptInvitation,
    AcceptInvitationWithNewAccount,
    CreateInvitation,
    InvitationView,
    ListInvitations,
    PreviewInvitation,
    RevokeInvitation,
)
from penaria.features.support.identity.use_cases.members import (
    ChangeGrant,
    GrantChanges,
    GrantView,
    LeaveHome,
    ListMembers,
    ListRoles,
    RevokeGrant,
)
from penaria.features.support.identity.use_cases.recovery import CreateResetLink

# Tokens are 43 characters of base64url; room for whatever a person pastes around one.
TOKEN_INPUT_MAX_LENGTH = 200

router = APIRouter(prefix="/api/v1", tags=["people"], dependencies=[SIGNED_IN])
public_router = APIRouter(prefix="/api/v1", tags=["invitations"])
guest_router = APIRouter(prefix="/api/v1", tags=["guests"], dependencies=[SIGNED_IN])


class RoleOut(BaseModel):
    id: UUID
    preset: Preset | None = Field(description="The preset it started as; its name is then translated")
    name: str | None = Field(description="The name someone gave it; a preset's is null until renamed")
    all_permissions: bool
    permissions: list[str]
    guest_view: bool = Field(description="Sees only guest-visible things and the places on the way to them")
    expiry_required: bool = Field(description="Every grant of it must end")
    default_duration_seconds: int | None = Field(description="How long its grants last unless the giver says")

    @classmethod
    def of(cls, role: Role) -> RoleOut:
        return cls(
            id=role.id,
            preset=role.preset,
            name=role.name,
            all_permissions=role.all_permissions,
            permissions=sorted(role.permissions),
            guest_view=role.guest_view,
            expiry_required=role.expiry_required,
            default_duration_seconds=None
            if role.default_duration is None
            else int(role.default_duration.total_seconds()),
        )


class PlaceRefOut(BaseModel):
    id: UUID
    names: list[str] = Field(description="The names from the top of the home down to the place itself")

    @classmethod
    def of(cls, place: Place | None) -> PlaceRefOut | None:
        return None if place is None else cls(id=place.id, names=list(place.names))


class PersonOut(BaseModel):
    id: UUID
    username: str | None
    display_name: str

    @classmethod
    def of(cls, user: User) -> PersonOut:
        return cls(id=user.id, username=user.username, display_name=user.display_name)


class HomeRefOut(BaseModel):
    id: UUID
    name: str

    @classmethod
    def of(cls, home: Home) -> HomeRefOut:
        return cls(id=home.id, name=home.name)


class GrantOut(BaseModel):
    id: UUID
    role: RoleOut
    scope: PlaceRefOut | None = Field(description="null for the whole home")
    expires_at: datetime | None
    created_at: datetime
    granted_by: PersonOut | None

    @classmethod
    def of(cls, view: GrantView) -> GrantOut:
        return cls(
            id=view.grant.id,
            role=RoleOut.of(view.role),
            scope=PlaceRefOut.of(view.scope),
            expires_at=view.grant.expires_at,
            created_at=view.grant.created_at,
            granted_by=None if view.granted_by is None else PersonOut.of(view.granted_by),
        )


class MemberOut(BaseModel):
    person: PersonOut
    you: bool
    grants: list[GrantOut]


class GrantPatch(BaseModel):
    role_id: UUID | None = None
    scope_entity_id: UUID | None = Field(default=None, description="null for the whole home")
    expires_at: AwareDatetime | None = Field(default=None, description="null for no end")


class InvitationIn(BaseModel):
    role_id: UUID
    email: str | None = Field(
        default=None, max_length=EMAIL_MAX_LENGTH, description="Mail the link there too; needs outgoing email"
    )
    scope_entity_id: UUID | None = Field(default=None, description="Omit for the whole home")
    valid_days: int = Field(
        default=INVITATION_DAYS, ge=1, le=INVITATION_MAX_DAYS, description="For how many days the link works"
    )
    grant_expires_at: AwareDatetime | None = Field(
        default=None, description="When the access ends; the role's default when it requires an end"
    )
    leave_when_accepted: bool = Field(default=False, description="Transfer ownership: an owner invitation only")


class InvitationOut(BaseModel):
    id: UUID
    role: RoleOut
    scope: PlaceRefOut | None
    expires_at: datetime
    grant_expires_at: datetime | None
    leave_when_accepted: bool
    created_at: datetime
    created_by: PersonOut

    @classmethod
    def of(cls, view: InvitationView) -> InvitationOut:
        invitation = view.invitation
        return cls(
            id=invitation.id,
            role=RoleOut.of(view.role),
            scope=PlaceRefOut.of(view.scope),
            expires_at=invitation.expires_at,
            grant_expires_at=invitation.grant_expires_at,
            leave_when_accepted=invitation.leave_when_accepted,
            created_at=invitation.created_at,
            created_by=PersonOut.of(view.created_by),
        )


class CreatedInvitationOut(BaseModel):
    invitation: InvitationOut
    url: str = Field(description="The link to pass on; shown only now")
    emailed_to: str | None = Field(description="Where the link was mailed, when it was")


class ResetLinkOut(BaseModel):
    url: str = Field(description="The reset link to pass on by hand; shown only now")
    expires_at: datetime


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=TOKEN_INPUT_MAX_LENGTH)


class InvitationPreviewOut(BaseModel):
    home: HomeRefOut
    inviter: str = Field(description="The display name of whoever invited")
    role: RoleOut
    scope: PlaceRefOut | None
    expires_at: datetime
    grant_expires_at: datetime | None
    leave_when_accepted: bool


class NewAccountIn(TokenIn):
    username: str = Field(min_length=1, max_length=NAME_INPUT_MAX_LENGTH)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=PASSWORD_INPUT_MAX_LENGTH)
    locale: str = Field(examples=["en"])


class NewAccountOut(BaseModel):
    account: AccountOut
    home: HomeRefOut


class GuestLinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=LINK_NAME_MAX_LENGTH, examples=["Weekend guests"])
    role_id: UUID = Field(description="A role with guest view, such as the guest preset")
    scope_entity_id: UUID | None = Field(default=None, description="Omit for the whole home")
    expires_at: AwareDatetime | None = Field(default=None, description="The role's default when omitted")


class GuestLinkOut(BaseModel):
    id: UUID
    grant_id: UUID = Field(description="Revoke it to end the link and every guest's visit")
    name: str
    role: RoleOut
    scope: PlaceRefOut | None
    expires_at: datetime
    created_at: datetime
    last_used_at: datetime | None
    granted_by: PersonOut | None

    @classmethod
    def of(cls, view: GuestLinkView) -> GuestLinkOut:
        grant = view.link.grant
        if grant.expires_at is None:
            raise RuntimeError(f"the guest link's grant ({grant.id}) has no end")
        return cls(
            id=view.link.id,
            grant_id=grant.id,
            name=view.link.token.name,
            role=RoleOut.of(view.role),
            scope=PlaceRefOut.of(view.scope),
            expires_at=grant.expires_at,
            created_at=grant.created_at,
            last_used_at=view.link.token.last_used_at,
            granted_by=None if view.granted_by is None else PersonOut.of(view.granted_by),
        )


class CreatedGuestLinkOut(BaseModel):
    link: GuestLinkOut
    url: str = Field(description="The link to pass on or print as a QR code; shown only now")


class GuestOut(BaseModel):
    home: HomeRefOut
    name: str = Field(description="The guest link's name")
    expires_at: datetime
    scope: PlaceRefOut | None = Field(description="Where the visit's things start; null for the whole home")

    @classmethod
    def of(cls, view: GuestView) -> GuestOut:
        return cls(
            home=HomeRefOut.of(view.home),
            name=view.name,
            expires_at=view.expires_at,
            scope=PlaceRefOut.of(view.scope),
        )


# A home's people


@router.get("/homes/{home_id}/roles")
async def list_roles(home_id: UUID, scope: UnitScopeDep) -> list[RoleOut]:
    roles = await (await scope.get(ListRoles)).execute(await scope.get(CurrentSession), home_id)
    return [RoleOut.of(role) for role in roles]


@router.get("/homes/{home_id}/members")
async def list_members(home_id: UUID, scope: UnitScopeDep) -> list[MemberOut]:
    current = await scope.get(CurrentSession)
    members = await (await scope.get(ListMembers)).execute(current, home_id)
    return [
        MemberOut(
            person=PersonOut.of(member.user),
            you=member.user.id == current.user_id,
            grants=[GrantOut.of(view) for view in member.grants],
        )
        for member in members
    ]


@router.patch("/homes/{home_id}/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def change_grant(home_id: UUID, grant_id: UUID, body: Annotated[GrantPatch, Body()], scope: UnitScopeDep) -> None:
    """Change a member's role, place or end of access; needs a recent sign-in."""
    given = body.model_fields_set
    changes = GrantChanges(
        role_id=body.role_id,
        change_scope="scope_entity_id" in given,
        scope_entity_id=body.scope_entity_id,
        change_expiry="expires_at" in given,
        expires_at=body.expires_at,
    )
    await (await scope.get(ChangeGrant)).execute(await scope.get(CurrentSession), home_id, grant_id, changes)


@router.delete("/homes/{home_id}/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_grant(home_id: UUID, grant_id: UUID, scope: UnitScopeDep) -> None:
    """Take back a member's access, or end a guest link with every visit made with it."""
    await (await scope.get(RevokeGrant)).execute(await scope.get(CurrentSession), home_id, grant_id)


@router.post("/homes/{home_id}:leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_home(home_id: UUID, scope: UnitScopeDep) -> None:
    """Give up your own access to the home; the last owner cannot."""
    await (await scope.get(LeaveHome)).execute(await scope.get(CurrentSession), home_id)


@router.post("/homes/{home_id}/members/{user_id}:reset-link", status_code=status.HTTP_201_CREATED)
async def create_reset_link(home_id: UUID, user_id: UUID, scope: UnitScopeDep) -> ResetLinkOut:
    """A password reset link for a member, to pass on by hand; it works for 24 hours. Needs a recent sign-in."""
    link = await (await scope.get(CreateResetLink)).execute(await scope.get(CurrentSession), home_id, user_id)
    return ResetLinkOut(url=link.url, expires_at=link.expires_at)


# Invitations


@router.get("/homes/{home_id}/invitations")
async def list_invitations(home_id: UUID, scope: UnitScopeDep) -> list[InvitationOut]:
    views = await (await scope.get(ListInvitations)).execute(await scope.get(CurrentSession), home_id)
    return [InvitationOut.of(view) for view in views]


@router.post("/homes/{home_id}/invitations", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    home_id: UUID, body: Annotated[InvitationIn, Body()], scope: UnitScopeDep
) -> CreatedInvitationOut:
    view, token = await (await scope.get(CreateInvitation)).execute(
        await scope.get(CurrentSession),
        home_id,
        role_id=body.role_id,
        scope_entity_id=body.scope_entity_id,
        valid_days=body.valid_days,
        grant_expires_at=body.grant_expires_at,
        leave_when_accepted=body.leave_when_accepted,
        email=body.email or None,
    )
    return CreatedInvitationOut(
        invitation=InvitationOut.of(view),
        url=(await scope.get(PublicLinks)).invitation(token),
        emailed_to=view.emailed_to,
    )


@router.delete("/homes/{home_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(home_id: UUID, invitation_id: UUID, scope: UnitScopeDep) -> None:
    await (await scope.get(RevokeInvitation)).execute(await scope.get(CurrentSession), home_id, invitation_id)


@public_router.post("/invitations:preview")
async def preview_invitation(
    body: Annotated[TokenIn, Body()], request: Request, scope: UnitScopeDep
) -> InvitationPreviewOut:
    """What an invitation's link offers, for its landing page; it changes nothing."""
    preview = await (await scope.get(PreviewInvitation)).execute(body.token, client_of(request))
    return InvitationPreviewOut(
        home=HomeRefOut.of(preview.home),
        inviter=preview.inviter.display_name,
        role=RoleOut.of(preview.role),
        scope=PlaceRefOut.of(preview.scope),
        expires_at=preview.invitation.expires_at,
        grant_expires_at=preview.invitation.grant_expires_at,
        leave_when_accepted=preview.invitation.leave_when_accepted,
    )


@router.post("/invitations:accept")
async def accept_invitation(body: Annotated[TokenIn, Body()], request: Request, scope: UnitScopeDep) -> HomeRefOut:
    """Accept an invitation with the signed-in account."""
    home = await (await scope.get(AcceptInvitation)).execute(
        await scope.get(CurrentSession), body.token, client_of(request)
    )
    return HomeRefOut.of(home)


@public_router.post("/invitations:accept-new-account")
async def accept_invitation_with_new_account(
    body: Annotated[NewAccountIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> NewAccountOut:
    """Make an account through an invitation and accept it; the new account is signed in."""
    user, home, token = await (await scope.get(AcceptInvitationWithNewAccount)).execute(
        body.token,
        username=body.username,
        display_name=body.display_name,
        password=body.password,
        locale=body.locale,
        client=client_of(request),
    )
    (await scope.get(SessionCookie)).set(response, token)
    return NewAccountOut(account=AccountOut.of(user), home=HomeRefOut.of(home))


# Guest links


@router.get("/homes/{home_id}/guest-links")
async def list_guest_links(home_id: UUID, scope: UnitScopeDep) -> list[GuestLinkOut]:
    views = await (await scope.get(ListGuestLinks)).execute(await scope.get(CurrentSession), home_id)
    return [GuestLinkOut.of(view) for view in views]


@router.post("/homes/{home_id}/guest-links", status_code=status.HTTP_201_CREATED)
async def create_guest_link(
    home_id: UUID, body: Annotated[GuestLinkIn, Body()], scope: UnitScopeDep
) -> CreatedGuestLinkOut:
    view, token = await (await scope.get(CreateGuestLink)).execute(
        await scope.get(CurrentSession),
        home_id,
        name=body.name,
        role_id=body.role_id,
        scope_entity_id=body.scope_entity_id,
        expires_at=body.expires_at,
    )
    return CreatedGuestLinkOut(link=GuestLinkOut.of(view), url=(await scope.get(PublicLinks)).guest(token))


@public_router.post("/guest-sessions")
async def open_guest_link(
    body: Annotated[TokenIn, Body()], request: Request, response: Response, scope: UnitScopeDep
) -> GuestOut:
    """Exchange a guest link's token for a guest session's cookie."""
    view, token = await (await scope.get(OpenGuestLink)).execute(
        body.token, client_of(request), request.cookies.get(SESSION_COOKIE)
    )
    (await scope.get(SessionCookie)).set(response, token)
    return GuestOut.of(view)


@guest_router.get("/guest")
async def guest(scope: UnitScopeDep) -> GuestOut:
    """The visit of the request's guest session."""
    return GuestOut.of(await (await scope.get(GetGuestView)).execute(await scope.get(GuestSession)))
