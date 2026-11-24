import pytest
from pydantic import ValidationError

from penaria.apps.api.settings import Settings
from penaria.features.support.identity.domain.mailbox import MailboxSource, MailSecurity

pytestmark = pytest.mark.unit


def test_without_mail_variables_mail_is_off() -> None:
    assert Settings().mail.mailbox() is None


def test_a_host_and_a_sender_make_the_operators_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__SECURITY", "tls")
    monkeypatch.setenv("PENARIA_MAIL__USERNAME", "home")
    monkeypatch.setenv("PENARIA_MAIL__PASSWORD", "smtp-secret")
    monkeypatch.setenv("PENARIA_MAIL__FROM_ADDRESS", "home@example.org")

    mailbox = Settings().mail.mailbox()

    assert mailbox is not None
    assert (mailbox.source, mailbox.fields.port, mailbox.fields.security) == (
        MailboxSource.ENVIRONMENT,
        465,
        MailSecurity.TLS,
    )
    assert mailbox.password == "smtp-secret"  # noqa: S105 - the value set above
    assert "smtp-secret" not in repr(mailbox)


def test_a_mail_setting_without_a_host_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__USERNAME", "home")

    with pytest.raises(ValidationError, match="PENARIA_MAIL__HOST is required"):
        Settings()


def test_a_host_without_a_sender_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")

    with pytest.raises(ValidationError, match="PENARIA_MAIL__FROM_ADDRESS is required"):
        Settings()


def test_a_wrong_sender_names_its_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__FROM_ADDRESS", "not an address")

    with pytest.raises(ValidationError, match="PENARIA_MAIL__FROM_ADDRESS is not valid"):
        Settings()


def test_a_misspelt_mail_variable_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOTS", "smtp.example.org")

    with pytest.raises(ValidationError, match="PENARIA_MAIL__HOTS"):
        Settings()


def test_retired_keys_are_separated_by_commas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PENARIA_RETIRED_SECRET_KEYS", "first-retired-key-of-32-characters-x, second-retired-key-of-32-characters"
    )

    keys = [key.get_secret_value() for key in Settings().retired_secret_keys]

    assert keys == ["first-retired-key-of-32-characters-x", "second-retired-key-of-32-characters"]


def test_a_short_retired_key_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_RETIRED_SECRET_KEYS", "short")

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings()
