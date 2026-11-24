import pytest

from penaria.features.shared.access import Permission
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.models import Home, InvalidHomeError, preset_roles
from penaria.features.support.identity.domain.permissions import GUEST_GRANT_DURATION, Preset, with_implied

pytestmark = pytest.mark.unit


def test_implied_permissions_are_added_transitively() -> None:
    assert with_implied({Permission.ROLES_MANAGE}) == {
        Permission.ROLES_MANAGE,
        Permission.MEMBERS_MANAGE,
        Permission.ENTITIES_VIEW,
    }
    assert with_implied({Permission.DEVICES_CONTROL_CRITICAL}) >= {Permission.DEVICES_CONTROL}


def test_a_new_home_gets_the_five_presets() -> None:
    roles = preset_roles(new_id())

    assert set(roles) == set(Preset)
    assert roles[Preset.OWNER].is_owner
    assert roles[Preset.OWNER].all_permissions
    assert roles[Preset.ADMIN].all_permissions
    assert not roles[Preset.ADMIN].is_owner
    assert Permission.CHANGES_APPLY in roles[Preset.FAMILY].permissions
    assert Permission.ENTITIES_VIEW_PRIVATE not in roles[Preset.FAMILY].permissions
    guest = roles[Preset.GUEST]
    assert (guest.guest_view, guest.expiry_required, guest.default_duration) == (True, True, GUEST_GRANT_DURATION)
    assert Permission.ENTITIES_EDIT not in guest.permissions


@pytest.mark.parametrize(
    ("name", "timezone", "locale"),
    [("", "Europe/Moscow", "ru"), ("Home", "Mars/Olympus", "ru"), ("Home", "UTC", "de")],
)
def test_a_home_needs_a_name_a_known_time_zone_and_a_supported_locale(name: str, timezone: str, locale: str) -> None:
    with pytest.raises(InvalidHomeError):
        Home.create(name=name, timezone=timezone, locale=locale)
