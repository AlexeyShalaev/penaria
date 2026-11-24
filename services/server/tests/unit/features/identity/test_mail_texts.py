from datetime import timedelta

import pytest

from penaria.features.support.identity.domain.mail import MailKind
from penaria.features.support.identity.domain.mail_texts import Link, compose, duration, plural_category, role_name
from penaria.features.support.identity.domain.permissions import Preset

pytestmark = pytest.mark.unit

SERVER = "https://home.example.org"
LINK = Link("https://home.example.org/reset-password/abc", timedelta(minutes=30))
VALUES = {
    MailKind.TEST: {},
    MailKind.EMAIL_VERIFICATION: {"name": "Anna", "email": "anna@example.org"},
    MailKind.PASSWORD_RESET: {"name": "Anna", "username": "anna"},
    MailKind.INVITATION: {"inviter": "Oleg", "home": "Dacha", "role": "family member"},
    MailKind.PASSWORD_CHANGED: {"name": "Anna", "username": "anna"},
    MailKind.PASSKEY_ADDED: {"name": "Anna", "username": "anna", "passkey": "Phone"},
}
LINKED = {MailKind.EMAIL_VERIFICATION, MailKind.PASSWORD_RESET, MailKind.INVITATION}


@pytest.mark.parametrize("locale", ["en", "ru"])
@pytest.mark.parametrize("kind", list(MailKind))
def test_every_mail_has_its_words_in_both_languages(kind: MailKind, locale: str) -> None:
    link = LINK if kind in LINKED else None

    content = compose(kind, locale, VALUES[kind], server=SERVER, link=link)

    assert content.subject
    assert "{" not in content.subject + content.text + content.html
    assert SERVER in content.text
    assert f'<html lang="{locale}">' in content.html
    assert (LINK.url in content.text) is (link is not None)
    assert (f'href="{LINK.url}"' in content.html) is (link is not None)


def test_a_reset_mail_in_english() -> None:
    content = compose(MailKind.PASSWORD_RESET, "en", VALUES[MailKind.PASSWORD_RESET], server=SERVER, link=LINK)

    assert content.subject == "Reset your Penaria password"
    assert content.text == (
        "Reset your password\n\n"
        "Anna, someone asked to reset the password of the account anna. Open the link to choose a new password.\n\n"
        "Choose a new password:\nhttps://home.example.org/reset-password/abc\n\n"
        "The link works for 30 minutes, once.\n\n"
        "If it was not you, ignore this email: your password stays as it is.\n\n"
        "A new password signs you out on every device. Your passkeys keep working.\n\n"
        "--\nPenaria at https://home.example.org sent this message automatically. Replies to it are not read.\n"
    )


def test_a_reset_mail_in_russian() -> None:
    content = compose(MailKind.PASSWORD_RESET, "ru", VALUES[MailKind.PASSWORD_RESET], server=SERVER, link=LINK)

    assert content.subject == "Сброс пароля в Penaria"  # noqa: RUF001 - Russian next to the product's name
    assert "Ссылка действует 30 минут и срабатывает один раз." in content.text


def test_values_are_escaped_in_the_html_and_kept_in_the_text() -> None:
    values = {"inviter": "<b>Oleg</b>", "home": "Tom & Jerry", "role": "guest"}

    content = compose(MailKind.INVITATION, "en", values, server=SERVER, link=LINK)

    assert "&lt;b&gt;Oleg&lt;/b&gt;" in content.html
    assert "Tom &amp; Jerry" in content.html
    assert "<b>Oleg</b>" not in content.html
    assert "<b>Oleg</b> invites you to the home Tom & Jerry" in content.text


def test_a_line_break_in_a_value_does_not_reach_the_subject() -> None:
    values = {"inviter": "Oleg\r\nBcc: x@y.z", "home": "Dacha", "role": "guest"}

    content = compose(MailKind.INVITATION, "en", values, server=SERVER, link=LINK)

    assert "\n" not in content.subject
    assert "\r" not in content.subject


@pytest.mark.parametrize(
    ("span", "locale", "words"),
    [
        (timedelta(minutes=1), "en", "1 minute"),
        (timedelta(minutes=30), "en", "30 minutes"),
        (timedelta(hours=24), "en", "24 hours"),
        (timedelta(days=7), "en", "7 days"),
        (timedelta(days=1), "en", "24 hours"),
        (timedelta(minutes=1), "ru", "1 минуту"),
        (timedelta(minutes=30), "ru", "30 минут"),
        (timedelta(minutes=22), "ru", "22 минуты"),
        (timedelta(hours=24), "ru", "24 часа"),
        (timedelta(hours=21), "ru", "21 час"),
        (timedelta(days=11), "ru", "11 дней"),
        (timedelta(days=21), "ru", "21 день"),
        (timedelta(days=3), "ru", "3 дня"),
    ],
)
def test_durations_are_told_in_words(span: timedelta, locale: str, words: str) -> None:
    assert duration(span, locale) == words


@pytest.mark.parametrize(
    ("n", "category"), [(1, "one"), (2, "few"), (5, "many"), (11, "many"), (12, "many"), (101, "one")]
)
def test_russian_plurals(n: int, category: str) -> None:
    assert plural_category(n, "ru") == category


def test_preset_roles_are_named_in_the_mails_language() -> None:
    assert (role_name(Preset.FAMILY, "en"), role_name(Preset.FAMILY, "ru")) == ("family member", "член семьи")
