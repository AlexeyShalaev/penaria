import pytest

from penaria.features.support.identity.domain.accounts import (
    InvalidAccountError,
    PasswordProblem,
    WeakPasswordError,
    check_display_name,
    check_locale,
    check_password,
    check_username,
)

pytestmark = pytest.mark.unit


def test_a_password_of_twelve_characters_is_enough() -> None:
    check_password("tulip garden")


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("eleven char", PasswordProblem.TOO_SHORT),
        ("x" * 257, PasswordProblem.TOO_LONG),
        ("password1234", PasswordProblem.COMMON),
        ("QwertyUiopAS", PasswordProblem.COMMON),
        ("1q2w3e4r5t6y", PasswordProblem.COMMON),
    ],
)
def test_a_weak_password_is_refused_with_its_reason(password: str, problem: PasswordProblem) -> None:
    with pytest.raises(WeakPasswordError) as raised:
        check_password(password)

    assert raised.value.params["reason"] == problem


def test_a_username_is_stored_in_lower_case() -> None:
    assert check_username("  Alice.Smith ") == "alice.smith"


def test_a_username_may_be_in_any_script() -> None:
    assert check_username("Мария_1") == "мария_1"


@pytest.mark.parametrize("username", ["ab", "a" * 33, "alice smith", "alice@home"])
def test_a_username_that_is_too_short_long_or_has_odd_characters_is_refused(username: str) -> None:
    with pytest.raises(InvalidAccountError) as raised:
        check_username(username)

    assert raised.value.params == {"field": "username"}


def test_a_display_name_is_trimmed_and_must_not_be_blank() -> None:
    assert check_display_name("  Alice ") == "Alice"
    with pytest.raises(InvalidAccountError):
        check_display_name("   ")


def test_only_the_shipped_locales_are_accepted() -> None:
    assert check_locale("ru") == "ru"
    with pytest.raises(InvalidAccountError):
        check_locale("de")
