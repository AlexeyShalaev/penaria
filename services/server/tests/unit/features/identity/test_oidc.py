from datetime import UTC, datetime, timedelta

import pytest

from penaria.features.support.identity.domain.oidc import (
    Claims,
    FlowPurpose,
    OidcFlow,
    check_open_flows,
    display_name_of,
    safe_return_to,
    username_candidates,
)
from penaria.features.support.identity.domain.sessions import hash_token
from penaria.features.support.identity.domain.throttle import TooManyAttemptsError

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)


def started() -> tuple[OidcFlow, str, str]:
    flow = OidcFlow.start(FlowPurpose.SIGN_IN, return_to="/", locale="en", address="ip:192.0.2.1", now=NOW)
    return flow.flow, flow.state, flow.binding


def test_a_flow_keeps_only_hashes_of_its_state_and_browser_binding_and_lasts_ten_minutes() -> None:
    flow, state, binding = started()

    assert (flow.state_hash, flow.browser_hash) == (hash_token(state), hash_token(binding))
    assert flow.expires_at == NOW + timedelta(minutes=10)
    assert len({state, binding, flow.nonce, flow.code_verifier}) == 4


def test_a_flow_belongs_to_the_browser_that_started_it() -> None:
    flow, _, binding = started()
    _, _, other = started()

    assert (flow.started_in(binding), flow.started_in(other), flow.started_in(None)) == (True, False, False)


def test_an_address_holds_ten_open_flows_at_most() -> None:
    check_open_flows(9)
    with pytest.raises(TooManyAttemptsError):
        check_open_flows(10)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/homes/1/people", "/homes/1/people"),
        ("//evil.example/x", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
        (None, "/"),
    ],
)
def test_coming_back_goes_only_to_a_page_of_the_install(path: str | None, expected: str) -> None:
    assert safe_return_to(path, "/") == expected


@pytest.mark.parametrize(
    ("claims", "username"),
    [
        (Claims(subject="1", preferred_username="Anna"), "anna"),
        (Claims(subject="1", preferred_username="Anna Petrova"), "anna.petrova"),
        (Claims(subject="1", email="kim.lee@example.org"), "kim.lee"),
        (Claims(subject="1", name="Мария"), "мария"),
        (Claims(subject="1", preferred_username="a!", email="bo@x.org", name="Zed Zed"), "zed.zed"),
        (Claims(subject="1"), "user"),
        (Claims(subject="1", preferred_username="x" * 40), "x" * 32),
    ],
)
def test_a_username_is_made_from_the_claims(claims: Claims, username: str) -> None:
    assert username_candidates(claims)[0] == username


def test_a_taken_username_is_tried_with_numbers() -> None:
    candidates = username_candidates(Claims(subject="1", preferred_username="y" * 32))

    assert candidates[1:3] == ["y" * 30 + "-2", "y" * 30 + "-3"]
    assert len(candidates) == 99
    assert all(len(candidate) <= 32 for candidate in candidates)


@pytest.mark.parametrize(
    ("claims", "name"),
    [
        (Claims(subject="1", name=" Anna Petrova ", preferred_username="anna"), "Anna Petrova"),
        (Claims(subject="1", preferred_username="anna"), "anna"),
        (Claims(subject="1"), "user"),
    ],
)
def test_a_display_name_is_the_name_the_provider_has(claims: Claims, name: str) -> None:
    assert display_name_of(claims, "user") == name
