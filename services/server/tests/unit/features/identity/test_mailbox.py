from typing import Any

import pytest

from penaria.features.support.identity.domain.mailbox import (
    InvalidEmailError,
    InvalidMailboxError,
    MailboxFields,
    MailSecurity,
    check_email,
)

pytestmark = pytest.mark.unit

GOOD: dict[str, Any] = {
    "host": " smtp.example.org ",
    "port": 587,
    "security": MailSecurity.STARTTLS,
    "username": " home@example.org ",
    "from_address": "Home@Example.org",
    "from_name": None,
}


def test_the_fields_are_trimmed_and_the_sender_named_penaria_by_default() -> None:
    assert MailboxFields.check(**GOOD) == MailboxFields(
        host="smtp.example.org",
        port=587,
        security=MailSecurity.STARTTLS,
        username="home@example.org",
        from_address="home@example.org",
        from_name="Penaria",
    )


def test_an_empty_login_means_no_sign_in() -> None:
    assert MailboxFields.check(**{**GOOD, "username": "  "}).username is None


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"host": "smtp.example.org/path"}, "host"),
        ({"host": "user@smtp.example.org"}, "host"),
        ({"host": "  "}, "host"),
        ({"port": 0}, "port"),
        ({"port": 70000}, "port"),
        ({"username": "two words"}, "username"),
        ({"from_name": "x" * 101}, "from_name"),
    ],
)
def test_wrong_fields_are_named(changes: dict[str, Any], field: str) -> None:
    with pytest.raises(InvalidMailboxError) as raised:
        MailboxFields.check(**{**GOOD, **changes})

    assert raised.value.params == {"field": field} | ({"max_length": 100} if field == "from_name" else {})


@pytest.mark.parametrize("address", ["no-at-sign", "a@b", "a b@c.org", "@example.org", ""])
def test_what_is_not_an_address_is_refused(address: str) -> None:
    with pytest.raises(InvalidEmailError):
        check_email(address)


def test_an_address_is_kept_in_lower_case() -> None:
    assert check_email("  Anna@Example.ORG ") == "anna@example.org"
