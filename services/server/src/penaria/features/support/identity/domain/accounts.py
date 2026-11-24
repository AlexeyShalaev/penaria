"""The rules for what an account is made of: its username, display name, language and password."""

import re
import unicodedata
from enum import StrEnum
from functools import cache
from importlib.resources import files

from penaria.features.shared.errors import InvalidError
from penaria.features.support.identity.domain.models import LOCALES, NAME_MAX_LENGTH

# Letters and digits of any script, dot, underscore and hyphen: something a person can type on a phone.
USERNAME_PATTERN = re.compile(r"[\w.-]{3,32}")
# NIST SP 800-63B: at least 12 for a password that is the only factor; no composition rules.
PASSWORD_MIN_LENGTH = 12
# Long passphrases are welcome; the cap only keeps the hashing input bounded.
PASSWORD_MAX_LENGTH = 256


class InvalidAccountError(InvalidError):
    code = "invalid_account"


class WeakPasswordError(InvalidError):
    code = "weak_password"


class PasswordProblem(StrEnum):
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    COMMON = "common"


def normalize_username(username: str) -> str:
    """The username as stored and compared: usernames are case-insensitive, so they are kept in lower case."""
    return unicodedata.normalize("NFKC", username).strip().lower()


def check_username(username: str) -> str:
    """The normalized username, or an error when it cannot be one."""
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidAccountError(
            "a username is 3 to 32 letters, digits, dots, underscores or hyphens", params={"field": "username"}
        )
    return normalized


def check_display_name(display_name: str) -> str:
    name = display_name.strip()
    if not name or len(name) > NAME_MAX_LENGTH:
        raise InvalidAccountError("a display name has 1 to 200 characters", params={"field": "display_name"})
    return name


def check_locale(locale: str) -> str:
    if locale not in LOCALES:
        raise InvalidAccountError("unsupported locale", params={"field": "locale", "supported": sorted(LOCALES)})
    return locale


def check_password(password: str) -> None:
    """Refuse a password that is too short, too long or among the most common ones."""
    if len(password) < PASSWORD_MIN_LENGTH:
        _refuse(PasswordProblem.TOO_SHORT)
    if len(password) > PASSWORD_MAX_LENGTH:
        _refuse(PasswordProblem.TOO_LONG)
    if password.lower() in common_passwords():
        _refuse(PasswordProblem.COMMON)


@cache
def common_passwords() -> frozenset[str]:
    """The built-in list of passwords too common to allow, in lower case."""
    text = files(__package__).joinpath("common_passwords.txt").read_text(encoding="utf-8")
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip() and not line.startswith("#"))


def _refuse(problem: PasswordProblem) -> None:
    raise WeakPasswordError(
        f"the password is {problem.value.replace('_', ' ')}",
        params={"reason": problem, "min_length": PASSWORD_MIN_LENGTH, "max_length": PASSWORD_MAX_LENGTH},
    )
