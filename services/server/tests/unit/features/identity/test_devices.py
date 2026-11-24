import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from penaria.features.shared.access import Permission
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.devices import Device, is_device_token
from penaria.features.support.identity.domain.members import InvalidGrantError
from penaria.features.support.identity.domain.models import PrincipalType, Role
from penaria.features.support.identity.domain.permissions import Preset, with_implied
from penaria.features.support.identity.domain.sessions import hash_token

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
HOME = new_id()
CREATOR = new_id()
FAMILY = Role(
    home_id=HOME,
    preset=Preset.FAMILY,
    name=None,
    all_permissions=False,
    permissions=with_implied({Permission.ENTITIES_EDIT}),
)
ADDRESS = "192.0.2.10"


def made(role: Role = FAMILY, name: str = "Hallway mirror") -> tuple[Device, str]:
    return Device.create(home_id=HOME, role=role, name=name, scope_entity_id=None, granted_by=CREATOR, now=NOW)


def used(device: Device, at: datetime, ip: str | None = ADDRESS) -> Device:
    return replace(device, token=replace(device.token, last_used_at=at, last_used_ip=ip))


def test_a_device_is_a_device_principal_whose_grant_and_token_share_its_id() -> None:
    device, _ = made()

    assert (device.grant.principal_type, device.token.principal_type) == (PrincipalType.DEVICE, PrincipalType.DEVICE)
    assert device.grant.principal_id == device.token.principal_id == device.id
    assert (device.grant.expires_at, device.grant.granted_by, device.token.name) == (None, CREATOR, "Hallway mirror")


def test_the_token_has_a_prefix_scanners_know_and_only_its_hash_is_kept() -> None:
    device, token = made()

    assert re.fullmatch(r"pnr_[0-9A-Za-z]{43}", token)
    assert device.token.token_hash == hash_token(token)


def test_every_token_is_new() -> None:
    assert made()[1] != made()[1]


@pytest.mark.parametrize(
    "value",
    ["pnr_", "pnr_" + "a" * 42, "pnr_" + "a" * 44, "pnr_" + "a" * 42 + "-", "PNR_" + "a" * 43, "a" * 47],
)
def test_what_does_not_have_a_tokens_form_is_not_one(value: str) -> None:
    assert not is_device_token(value)


def test_a_device_cannot_be_an_owner() -> None:
    owner = replace(FAMILY, preset=Preset.OWNER, all_permissions=True)

    with pytest.raises(InvalidGrantError) as raised:
        made(owner)

    assert raised.value.params == {"field": "role_id", "reason": "device_role"}


def test_a_role_whose_access_must_end_is_refused_since_a_devices_never_does() -> None:
    guest = replace(FAMILY, preset=Preset.GUEST, expiry_required=True, default_duration=timedelta(days=3))

    with pytest.raises(InvalidGrantError) as raised:
        made(guest)

    assert raised.value.params == {"field": "role_id", "reason": "device_role"}


def test_a_device_needs_a_name() -> None:
    with pytest.raises(InvalidGrantError) as raised:
        made(name="  ")

    assert raised.value.params == {"field": "name", "max_length": 100}


def test_a_revoked_token_or_grant_ends_the_device() -> None:
    device, _ = made()

    assert device.is_active(NOW)
    assert not replace(device, token=replace(device.token, revoked_at=NOW)).is_active(NOW)
    assert not replace(device, grant=replace(device.grant, revoked_at=NOW)).is_active(NOW)


def test_the_first_use_is_recorded_and_journalled() -> None:
    device, _ = made()

    assert (device.needs_touch(NOW), device.needs_journal(ADDRESS, NOW)) == (True, True)


def test_uses_minutes_apart_from_the_same_place_are_neither_recorded_nor_journalled() -> None:
    device = used(made()[0], NOW)

    later = NOW + timedelta(minutes=4)
    assert (device.needs_touch(later), device.needs_journal(ADDRESS, later)) == (False, False)


def test_a_use_after_five_minutes_is_recorded_but_not_journalled() -> None:
    device = used(made()[0], NOW)

    later = NOW + timedelta(minutes=5)
    assert (device.needs_touch(later), device.needs_journal(ADDRESS, later)) == (True, False)


def test_a_use_after_a_quiet_day_is_journalled() -> None:
    device = used(made()[0], NOW)

    assert device.needs_journal(ADDRESS, NOW + timedelta(days=1))


def test_a_use_from_another_address_is_journalled_when_it_is_recorded() -> None:
    device = used(made()[0], NOW)

    later = NOW + timedelta(minutes=5)
    assert (device.needs_touch(later), device.needs_journal("198.51.100.7", later)) == (True, True)


def test_an_address_that_alternates_between_records_is_not_journalled_on_each_request() -> None:
    device = used(made()[0], NOW)

    assert not device.needs_journal("198.51.100.7", NOW + timedelta(seconds=5))


def test_another_address_in_the_same_ipv6_block_is_the_same_place() -> None:
    device = used(made()[0], NOW, ip="2001:db8::1")

    assert not device.needs_journal("2001:db8::abcd", NOW + timedelta(minutes=5))
