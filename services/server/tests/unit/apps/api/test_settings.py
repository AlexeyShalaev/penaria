import pytest
from pydantic import ValidationError

from penaria.apps.api.settings import Settings
from penaria.features.support.identity.domain.mailbox import MailboxFields, MailSecurity

pytestmark = pytest.mark.unit

PASSWORD = "smtp-secret-of-the-test"  # noqa: S105 - a value of the tests


def test_without_mail_variables_the_interface_sets_the_mailbox() -> None:
    assert Settings().mail is None


def test_a_host_and_a_sender_make_the_operators_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__SECURITY", "tls")
    monkeypatch.setenv("PENARIA_MAIL__USERNAME", "home")
    monkeypatch.setenv("PENARIA_MAIL__PASSWORD", PASSWORD)
    monkeypatch.setenv("PENARIA_MAIL__FROM_ADDRESS", "home@example.org")

    mail = Settings().mail

    assert mail is not None
    assert mail.fields() == MailboxFields(
        host="smtp.example.org",
        port=465,
        security=MailSecurity.TLS,
        username="home",
        from_address="home@example.org",
        from_name="Penaria",
    )
    assert mail.password is not None
    assert mail.password.get_secret_value() == PASSWORD


@pytest.mark.parametrize(
    ("variables", "missing"),
    [
        ({"PENARIA_MAIL__USERNAME": "home"}, "mail.host"),
        ({"PENARIA_MAIL__HOST": "smtp.example.org"}, "mail.from_address"),
    ],
)
def test_half_a_mailbox_in_the_environment_stops_the_process(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], missing: str
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=missing):
        Settings()


def test_a_wrong_sender_names_its_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__FROM_ADDRESS", "not an address")

    with pytest.raises(ValidationError, match="PENARIA_MAIL__FROM_ADDRESS is not valid"):
        Settings()


def test_an_error_in_the_mail_settings_never_shows_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__PASSWORD", PASSWORD)

    with pytest.raises(ValidationError) as raised:
        Settings()

    assert PASSWORD not in str(raised.value)


def test_a_misspelt_mail_variable_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__FROM_ADDRESS", "home@example.org")
    monkeypatch.setenv("PENARIA_MAIL__USERNAMME", "home")

    with pytest.raises(ValidationError, match="PENARIA_MAIL__USERNAMME"):
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


def provider_variables(monkeypatch: pytest.MonkeyPatch, issuer: str) -> None:
    monkeypatch.setenv("PENARIA_AUTH__OIDC__ISSUER", issuer)
    monkeypatch.setenv("PENARIA_AUTH__OIDC__CLIENT_ID", "penaria")
    monkeypatch.setenv("PENARIA_AUTH__OIDC__CLIENT_SECRET", PASSWORD)


def test_without_provider_variables_there_is_no_provider() -> None:
    assert Settings().auth.oidc is None


def test_a_provider_from_the_environment_keeps_its_issuer_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_variables(monkeypatch, "https://auth.example.org/application/o/penaria/")

    oidc = Settings().auth.oidc

    assert oidc is not None
    assert (oidc.issuer, oidc.allow_sign_up, oidc.scopes, oidc.display_name) == (
        "https://auth.example.org/application/o/penaria/",
        False,
        "openid profile email",
        "auth.example.org",
    )
    assert Settings().oidc_redirect_uri == "http://localhost:5173/api/v1/auth/oidc/callback"


@pytest.mark.parametrize(
    "issuer", ["http://auth.example.org", "https://auth.example.org/?tenant=1", "auth.example.org"]
)
def test_a_provider_must_be_https_unless_it_is_on_the_machine(monkeypatch: pytest.MonkeyPatch, issuer: str) -> None:
    provider_variables(monkeypatch, issuer)

    with pytest.raises(ValidationError, match=r"auth\.oidc\.issuer"):
        Settings()


def test_a_provider_on_the_machine_may_use_http(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_variables(monkeypatch, "http://localhost:5556/dex")

    assert Settings().auth.oidc is not None


def test_scopes_without_openid_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_variables(monkeypatch, "https://auth.example.org")
    monkeypatch.setenv("PENARIA_AUTH__OIDC__SCOPES", "profile email")

    with pytest.raises(ValidationError, match="openid"):
        Settings()
