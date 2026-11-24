from datetime import UTC, datetime, timedelta

import pytest

from penaria.features.shared.access import Access, Permission
from penaria.features.shared.errors import ForbiddenError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.members import (
    EscalationError,
    GuestLink,
    InvalidGrantError,
    Invitation,
    InvitationExpiredError,
    InvitationRevokedError,
    InvitationState,
    InvitationUsedError,
    check_can_give,
    grant_expiry,
)
from penaria.features.support.identity.domain.models import PrincipalType, Role
from penaria.features.support.identity.domain.permissions import Preset, with_implied
from penaria.features.support.identity.domain.sessions import hash_token

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
HOME = new_id()
OWNER = Access(permissions=frozenset(), owner=True, all_permissions=True)
ADMIN = Access(permissions=frozenset(), all_permissions=True)
FAMILY = Access(permissions=with_implied({Permission.ENTITIES_EDIT, Permission.TASKS_COMPLETE}))
MANAGER = Access(permissions=with_implied({Permission.MEMBERS_MANAGE, Permission.ENTITIES_EDIT}))


def role(preset: Preset | None = None, *permissions: str, **fields: object) -> Role:
    return Role(
        home_id=HOME,
        preset=preset,
        name=None if preset else "Custom",
        all_permissions=preset in (Preset.OWNER, Preset.ADMIN),
        permissions=with_implied(permissions),
        **fields,  # type: ignore[arg-type]
    )


GUEST = role(
    Preset.GUEST, Permission.ENTITIES_VIEW, guest_view=True, expiry_required=True, default_duration=timedelta(days=3)
)


@pytest.mark.parametrize(
    ("access", "given"),
    [
        (OWNER, role(Preset.OWNER)),
        (OWNER, role(Preset.ADMIN)),
        (ADMIN, role(Preset.ADMIN)),
        (ADMIN, GUEST),
        (MANAGER, role(None, Permission.ENTITIES_EDIT)),
        (MANAGER, role(None, Permission.MEMBERS_MANAGE)),
    ],
)
def test_a_role_within_your_own_access_can_be_given(access: Access, given: Role) -> None:
    check_can_give(access, given)


@pytest.mark.parametrize(
    ("access", "given"),
    [
        (ADMIN, role(Preset.OWNER)),
        (MANAGER, role(Preset.ADMIN)),
        (MANAGER, role(None, Permission.CHANGES_APPLY)),
        (Access(permissions=with_implied({Permission.MEMBERS_MANAGE}), guest_view=True), role(None)),
    ],
)
def test_a_role_beyond_your_own_access_is_escalation(access: Access, given: Role) -> None:
    with pytest.raises(EscalationError):
        check_can_give(access, given)


def test_without_members_manage_nothing_can_be_given() -> None:
    with pytest.raises(ForbiddenError) as raised:
        check_can_give(FAMILY, GUEST)

    assert raised.value.code == "permission_denied"


def test_a_grant_of_a_role_that_requires_an_end_gets_its_default() -> None:
    assert grant_expiry(GUEST, None, NOW, field="expires_at") == NOW + timedelta(days=3)
    assert grant_expiry(role(Preset.FAMILY), None, NOW, field="expires_at") is None


def test_an_owner_grant_never_ends() -> None:
    with pytest.raises(InvalidGrantError):
        grant_expiry(role(Preset.OWNER), NOW + timedelta(days=1), NOW, field="grant_expires_at")


def test_an_end_in_the_past_is_refused() -> None:
    with pytest.raises(InvalidGrantError) as raised:
        grant_expiry(role(Preset.FAMILY), NOW, NOW, field="grant_expires_at")

    assert raised.value.params == {"field": "grant_expires_at"}


def invitation(given: Role, **fields: object) -> tuple[Invitation, str]:
    arguments: dict[str, object] = {
        "scope_entity_id": None,
        "expires_at": None,
        "grant_expires_at": None,
        "leave_when_accepted": False,
        **fields,
    }
    return Invitation.create(home_id=HOME, role=given, created_by=new_id(), now=NOW, **arguments)  # type: ignore[arg-type]


def test_an_invitation_keeps_only_its_tokens_hash() -> None:
    made, token = invitation(role(Preset.FAMILY))

    assert made.token_hash == hash_token(token)
    assert token not in repr(made)
    assert (made.expires_at, made.state(NOW)) == (NOW + timedelta(days=7), InvitationState.PENDING)


def test_an_invitation_ends_with_the_access_it_gives() -> None:
    made, _ = invitation(GUEST)

    assert made.expires_at == made.grant_expires_at == NOW + timedelta(days=3)


def test_an_owner_invitation_covers_the_whole_home() -> None:
    with pytest.raises(InvalidGrantError):
        invitation(role(Preset.OWNER), scope_entity_id=new_id())


def test_an_invitation_says_why_it_cannot_be_accepted() -> None:
    used, _ = invitation(role(Preset.FAMILY))
    used.accepted_at, used.accepted_by = NOW, new_id()
    revoked, _ = invitation(role(Preset.FAMILY))
    revoked.revoked_at = NOW
    expired, _ = invitation(role(Preset.FAMILY), expires_at=NOW + timedelta(hours=1))

    with pytest.raises(InvitationUsedError):
        used.check_open(NOW)
    with pytest.raises(InvitationRevokedError):
        revoked.check_open(NOW)
    with pytest.raises(InvitationExpiredError):
        expired.check_open(NOW + timedelta(hours=1))


def test_the_grant_of_an_invitation_names_who_gave_it() -> None:
    made, _ = invitation(role(Preset.FAMILY))
    user_id = new_id()

    grant = made.grant_for(user_id)

    assert (grant.principal_type, grant.principal_id, grant.granted_by) == (
        PrincipalType.USER,
        user_id,
        made.created_by,
    )


def test_a_guest_link_is_a_link_principal_with_a_grant_that_ends() -> None:
    link, token = GuestLink.create(
        home_id=HOME, role=GUEST, name=" Weekend ", scope_entity_id=None, expires_at=None, granted_by=new_id(), now=NOW
    )

    assert link.grant.principal_type is PrincipalType.LINK
    assert link.grant.principal_id == link.token.principal_id == link.id
    assert link.grant.expires_at == NOW + timedelta(days=3)
    assert link.token.name == "Weekend"
    assert link.token.token_hash == hash_token(token)


def test_a_guest_link_needs_a_role_with_guest_view() -> None:
    with pytest.raises(InvalidGrantError):
        GuestLink.create(
            home_id=HOME,
            role=role(Preset.FAMILY),
            name="Kids",
            scope_entity_id=None,
            expires_at=None,
            granted_by=new_id(),
            now=NOW,
        )
