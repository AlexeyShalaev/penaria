from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from webauthn.helpers import bytes_to_base64url

from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.passkeys import (
    Ceremony,
    Challenge,
    CredentialRejected,
    InvalidPasskeyNameError,
    Passkey,
    check_passkey_name,
)
from penaria.features.support.identity.infra.webauthn import WebAuthnRelyingParty
from tests.authenticator import Authenticator

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ORIGIN = "https://home.example.org"
RP = WebAuthnRelyingParty(rp_id="home.example.org", origin=ORIGIN)
OWNER = User(display_name="Alex", locale="en", username="alex")


def registration() -> Challenge:
    return Challenge.issue(Ceremony.REGISTRATION, new_id(), NOW)


def sign_in() -> Challenge:
    return Challenge.issue(Ceremony.SIGN_IN, None, NOW)


def registered(device: Authenticator) -> Passkey:
    challenge = registration()
    new = RP.verify_registration(device.create(RP.registration_options(OWNER, challenge, [])), challenge)
    return Passkey(
        user_id=OWNER.id,
        credential_id=new.credential_id,
        public_key=new.public_key,
        sign_count=new.sign_count,
        name="Phone",
        created_at=NOW,
        transports=new.transports,
    )


def answer(device: Authenticator, passkey: Passkey, challenge: Challenge) -> dict[str, Any]:
    return device.get(RP.authentication_options(challenge, [passkey]))


# The domain


def test_a_challenge_expires_after_five_minutes() -> None:
    challenge = sign_in()

    assert challenge.expires_at == NOW + timedelta(minutes=5)
    assert len(challenge.value) == 32
    assert challenge.value != sign_in().value


@pytest.mark.parametrize(
    ("ceremony", "has_session"),
    [(Ceremony.SIGN_IN, True), (Ceremony.REGISTRATION, False), (Ceremony.REAUTHENTICATION, False)],
)
def test_only_a_sign_in_belongs_to_no_session(ceremony: Ceremony, has_session: bool) -> None:
    with pytest.raises(ValueError, match="belongs to a session"):
        Challenge.issue(ceremony, new_id() if has_session else None, NOW)


def test_a_passkey_name_is_trimmed() -> None:
    assert check_passkey_name("  Safari on iPhone ") == "Safari on iPhone"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_a_passkey_name_has_one_to_a_hundred_characters(name: str) -> None:
    with pytest.raises(InvalidPasskeyNameError):
        check_passkey_name(name)


# The options


def test_registration_asks_for_a_discoverable_credential_and_a_verified_person() -> None:
    challenge = registration()

    options = RP.registration_options(OWNER, challenge, [])

    assert options["rp"] == {"id": "home.example.org", "name": "Penaria"}
    assert options["user"] == {"id": bytes_to_base64url(OWNER.id.bytes), "name": "alex", "displayName": "Alex"}
    assert options["challenge"] == bytes_to_base64url(challenge.value)
    assert options["authenticatorSelection"] == {
        "residentKey": "required",
        "requireResidentKey": True,
        "userVerification": "required",
    }
    assert options["attestation"] == "none"
    assert options["timeout"] == 300_000
    assert options["excludeCredentials"] == []


def test_registration_excludes_the_account_s_passkeys() -> None:
    passkey = registered(Authenticator(ORIGIN))

    options = RP.registration_options(OWNER, registration(), [passkey])

    assert options["excludeCredentials"] == [
        {"id": bytes_to_base64url(passkey.credential_id), "type": "public-key", "transports": ["hybrid", "internal"]}
    ]


def test_sign_in_lets_the_person_pick_any_passkey() -> None:
    challenge = sign_in()

    options = RP.authentication_options(challenge, [])

    assert options == {
        "rpId": "home.example.org",
        "challenge": bytes_to_base64url(challenge.value),
        "timeout": 300_000,
        "allowCredentials": [],
        "userVerification": "required",
    }


# Checking what the browser answers


def test_a_new_credential_is_checked_and_kept() -> None:
    device = Authenticator(ORIGIN)

    passkey = registered(device)

    assert passkey.credential_id == device.credential_id
    assert passkey.sign_count == 0
    assert passkey.transports == ["hybrid", "internal"]


@pytest.mark.parametrize(
    "device",
    [
        Authenticator("https://evil.example"),
        Authenticator("http://home.example.org"),
        Authenticator(ORIGIN, verifies_user=False),
    ],
    ids=["another site", "plain http", "no user verification"],
)
def test_a_credential_made_elsewhere_or_without_verifying_the_person_is_rejected(device: Authenticator) -> None:
    challenge = registration()
    credential = device.create(RP.registration_options(OWNER, challenge, []))

    with pytest.raises(CredentialRejected):
        RP.verify_registration(credential, challenge)


def test_a_credential_made_for_another_challenge_is_rejected() -> None:
    credential = Authenticator(ORIGIN).create(RP.registration_options(OWNER, registration(), []))

    with pytest.raises(CredentialRejected):
        RP.verify_registration(credential, registration())


def test_an_answer_is_checked_against_the_passkey_s_key() -> None:
    device = Authenticator(ORIGIN, counting=True)
    passkey = registered(device)
    challenge = sign_in()

    assert RP.verify_authentication(answer(device, passkey, challenge), challenge, passkey) == 1


def test_an_answer_from_another_key_is_rejected() -> None:
    device = Authenticator(ORIGIN)
    passkey = registered(device)
    challenge = sign_in()

    with pytest.raises(CredentialRejected):
        RP.verify_authentication(answer(device.impostor(), passkey, challenge), challenge, passkey)


def test_an_answer_to_another_challenge_is_rejected() -> None:
    device = Authenticator(ORIGIN)
    passkey = registered(device)

    with pytest.raises(CredentialRejected):
        RP.verify_authentication(answer(device, passkey, sign_in()), sign_in(), passkey)


def test_a_cloned_authenticator_is_caught_by_its_count() -> None:
    device = Authenticator(ORIGIN, counting=True)
    passkey = registered(device)
    clone = device.clone()
    first = sign_in()
    passkey.sign_count = RP.verify_authentication(answer(device, passkey, first), first, passkey)
    second = sign_in()

    with pytest.raises(CredentialRejected, match="sign count"):
        RP.verify_authentication(answer(clone, passkey, second), second, passkey)


def test_a_synced_passkey_that_always_counts_zero_keeps_working() -> None:
    device = Authenticator(ORIGIN)
    passkey = registered(device)
    challenges = [sign_in(), sign_in()]

    counts = [RP.verify_authentication(answer(device, passkey, c), c, passkey) for c in challenges]

    assert counts == [0, 0]


def test_an_assertion_names_its_credential_and_account() -> None:
    device = Authenticator(ORIGIN)
    passkey = registered(device)

    assertion = RP.read_assertion(answer(device, passkey, sign_in()))

    assert assertion.credential_id == passkey.credential_id
    assert assertion.user_handle == OWNER.id.bytes


def test_an_unreadable_assertion_is_rejected() -> None:
    with pytest.raises(CredentialRejected):
        RP.read_assertion({"id": "x", "rawId": "x", "type": "public-key", "response": {}})
