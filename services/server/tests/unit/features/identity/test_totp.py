import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from penaria.features.support.identity.domain.totp import (
    ENROLMENT_TIMEOUT,
    RECOVERY_CODE_COUNT,
    PendingSignIn,
    Totp,
    WrongCodeError,
    code_at,
    hash_recovery_code,
    matching_step,
    new_recovery_codes,
    new_secret_key,
    provisioning_uri,
    second_factor_required,
    step_at,
)

pytestmark = pytest.mark.unit

# RFC 6238, appendix B: the SHA-1 seed and the last six digits of its eight-digit codes.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()
NOW = datetime(2026, 11, 24, 12, 0, 15, tzinfo=UTC)
STEP = timedelta(seconds=30)
# What the store keeps: the secret sealed; these tests never open it.
SEALED = "pnr1:key:sealed"


@pytest.mark.parametrize(
    ("unix_time", "code"),
    [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_codes_follow_rfc_6238(unix_time: int, code: str) -> None:
    assert code_at(RFC_SECRET, step_at(datetime.fromtimestamp(unix_time, UTC))) == code


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_a_code_of_the_step_before_now_or_after_is_accepted(offset: int) -> None:
    step = step_at(NOW) + offset

    assert matching_step(RFC_SECRET, code_at(RFC_SECRET, step), NOW, after=None) == step


@pytest.mark.parametrize("offset", [-2, 2])
def test_a_code_two_steps_away_is_refused(offset: int) -> None:
    code = code_at(RFC_SECRET, step_at(NOW) + offset)

    assert matching_step(RFC_SECRET, code, NOW, after=None) is None


def test_a_code_typed_with_spaces_is_accepted() -> None:
    code = code_at(RFC_SECRET, step_at(NOW))

    assert matching_step(RFC_SECRET, f" {code[:3]} {code[3:]} ", NOW, after=None) == step_at(NOW)


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "abcdef", "١٢٣٤٥٦"])
def test_what_is_not_six_digits_is_refused(typed: str) -> None:
    assert matching_step(RFC_SECRET, typed, NOW, after=None) is None


@pytest.mark.parametrize("offset", [0, -1])
def test_a_used_code_and_every_earlier_one_are_refused(offset: int) -> None:
    totp = enabled_totp()
    totp.use_code(RFC_SECRET, code_at(RFC_SECRET, step_at(NOW)), NOW)

    with pytest.raises(WrongCodeError):
        totp.use_code(RFC_SECRET, code_at(RFC_SECRET, step_at(NOW) + offset), NOW)

    assert totp.last_used_step == step_at(NOW)


def test_the_next_code_works_after_one_was_used() -> None:
    totp = enabled_totp()
    totp.use_code(RFC_SECRET, code_at(RFC_SECRET, step_at(NOW)), NOW)

    totp.use_code(RFC_SECRET, code_at(RFC_SECRET, step_at(NOW + STEP)), NOW + STEP)

    assert totp.last_used_step == step_at(NOW) + 1


def test_a_recovery_code_works_once_however_it_is_typed() -> None:
    codes = new_recovery_codes()
    totp = enabled_totp(recovery_codes=[hash_recovery_code(code) for code in codes])

    totp.use_recovery_code(f"  {codes[3].upper().replace('-', ' ')} ")

    assert len(totp.recovery_codes) == RECOVERY_CODE_COUNT - 1
    with pytest.raises(WrongCodeError):
        totp.use_recovery_code(codes[3])


def test_a_wrong_recovery_code_crosses_nothing_off() -> None:
    codes = new_recovery_codes()
    totp = enabled_totp(recovery_codes=[hash_recovery_code(code) for code in codes])

    with pytest.raises(WrongCodeError):
        totp.use_recovery_code("0000-0000-0000-0000")

    assert len(totp.recovery_codes) == RECOVERY_CODE_COUNT


def test_letters_that_look_like_digits_are_read_as_them() -> None:
    assert hash_recovery_code("o1l1-i0O0") == hash_recovery_code("0111-1000")


def test_recovery_codes_are_ten_different_codes_of_four_groups() -> None:
    codes = new_recovery_codes()

    assert len(set(codes)) == RECOVERY_CODE_COUNT
    assert set("".join(codes)) <= set("0123456789abcdefghjkmnpqrstvwxyz-")
    assert all([len(group) for group in code.split("-")] == [4, 4, 4, 4] for code in codes)


def test_only_a_hash_of_a_recovery_code_is_kept() -> None:
    code = new_recovery_codes()[0]

    assert code.replace("-", "") not in hash_recovery_code(code)
    assert len(hash_recovery_code(code)) == 64


def test_a_new_secret_is_160_bits_of_base32() -> None:
    secret = new_secret_key()

    assert len(base64.b32decode(secret + "=" * (-len(secret) % 8))) == 20


def test_the_provisioning_uri_names_penaria_and_the_account_at_the_host() -> None:
    uri = urlsplit(provisioning_uri("JBSWY3DPEHPK3PXP", "anna", "home.example.org"))

    assert (uri.scheme, uri.netloc, uri.path) == ("otpauth", "totp", "/Penaria:anna@home.example.org")
    assert parse_qs(uri.query) == {
        "secret": ["JBSWY3DPEHPK3PXP"],
        "issuer": ["Penaria"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }


def test_an_enrolment_waits_for_its_code_ten_minutes() -> None:
    totp = Totp(user_id=uuid4(), sealed_secret=SEALED, created_at=NOW)

    assert totp.enrolment_open(NOW + ENROLMENT_TIMEOUT - timedelta(seconds=1))
    assert not totp.enrolment_open(NOW + ENROLMENT_TIMEOUT)


def test_a_pending_sign_in_lasts_five_minutes_and_keeps_only_a_hash() -> None:
    pending, token = PendingSignIn.start(uuid4(), "ip:192.0.2.1", NOW)

    assert pending.expires_at == NOW + timedelta(minutes=5)
    assert pending.token_hash == hashlib.sha256(token.encode()).digest()


@pytest.mark.parametrize(
    ("signs_in_without_passkey", "install_admin", "owns_a_home", "required"),
    [
        (True, False, True, True),
        (True, True, False, True),
        (True, False, False, False),
        (False, True, True, False),
    ],
)
def test_owners_and_install_admins_with_a_password_or_a_provider_must_keep_a_second_factor(
    signs_in_without_passkey: bool, install_admin: bool, owns_a_home: bool, required: bool
) -> None:
    assert (
        second_factor_required(
            signs_in_without_passkey=signs_in_without_passkey, install_admin=install_admin, owns_a_home=owns_a_home
        )
        is required
    )


def enabled_totp(recovery_codes: list[str] | None = None) -> Totp:
    return Totp(
        user_id=uuid4(),
        sealed_secret=SEALED,
        created_at=NOW - timedelta(days=1),
        confirmed_at=NOW - timedelta(days=1),
        recovery_codes=recovery_codes or [],
    )
