"""Settings of the API process, read from the environment only."""

from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode
from servicewright.adapters.fastapi import HttpServerSettings

from penaria.common.database import DatabaseSettings
from penaria.common.files import FilesSettings
from penaria.common.settings import PenariaSettings
from penaria.common.urls import is_loopback, origin_of
from penaria.features.shared.errors import InvalidError
from penaria.features.support.identity.api.cookies import OIDC_CALLBACK_PATH
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.domain.mailbox import DEFAULT_PORTS, MailboxFields, MailSecurity
from penaria.integrations.s3.settings import S3Settings

# Stored secrets are encrypted with keys derived from it; shorter keys are too easy to guess.
SECRET_KEY_MIN_LENGTH = 32


class MailSettings(BaseModel):
    """``PENARIA_MAIL__*``: the install's mailbox, set by the operator. It wins over the interface as a whole:
    with these set, every mail setting comes from here (sign-in.md, 9.1)."""

    host: str
    # The usual port of the security when unset: 587, 465 or 25.
    port: int | None = Field(default=None, ge=1, le=65535)
    security: MailSecurity = MailSecurity.STARTTLS
    username: str | None = None
    password: SecretStr | None = None
    from_address: str
    from_name: str | None = None

    @model_validator(mode="after")
    def _a_mailbox(self) -> Self:
        try:
            self.fields()
        except InvalidError as exc:
            raise ValueError(f"PENARIA_MAIL__{str(exc.params['field']).upper()} is not valid: {exc}") from exc
        return self

    def fields(self) -> MailboxFields:
        return MailboxFields.check(
            host=self.host,
            port=self.port or DEFAULT_PORTS[self.security],
            security=self.security,
            username=self.username,
            from_address=self.from_address,
            from_name=self.from_name,
        )


class OidcSettings(BaseModel):
    """``PENARIA_AUTH__OIDC__*``: the operator's OpenID Connect provider, such as Authentik or Keycloak
    (sign-in.md, 4.4)."""

    # Exactly as the provider names itself in its discovery document, trailing slash and all.
    issuer: str
    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    # Whether an identity nobody linked makes an account; otherwise people join through invitations.
    allow_sign_up: bool = False
    # What the sign-in button calls the provider; its host name when unset.
    name: str | None = Field(default=None, min_length=1, max_length=50)
    scopes: str = "openid profile email"

    @field_validator("issuer")
    @classmethod
    def _an_issuer(cls, issuer: str) -> str:
        parts = urlsplit(issuer)
        # A provider on the machine itself may answer over plain http, as a development one does.
        secure = parts.scheme == "https" or (parts.scheme == "http" and is_loopback(parts.hostname))
        if not secure or parts.query or parts.fragment:
            raise ValueError(
                "an https address without a query, such as https://auth.example.org/application/o/penaria/"
            )
        return issuer

    @field_validator("scopes")
    @classmethod
    def _asks_for_openid(cls, scopes: str) -> str:
        if "openid" not in scopes.split():
            raise ValueError("the scopes must include openid")
        return scopes

    @property
    def display_name(self) -> str:
        return self.name or (urlsplit(self.issuer).hostname or self.issuer)


class AuthSettings(BaseModel):
    oidc: OidcSettings | None = None


class Settings(PenariaSettings):
    server: HttpServerSettings = HttpServerSettings()
    database: DatabaseSettings
    # The address people open, such as https://home.example.org: the web app and the API behind it.
    public_url: AnyHttpUrl
    secret_key: SecretStr = Field(min_length=SECRET_KEY_MIN_LENGTH)
    # Earlier values of PENARIA_SECRET_KEY, separated by commas: what they encrypted still opens.
    retired_secret_keys: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)
    # None: the install's admins connect the mailbox in the interface, if at all.
    mail: MailSettings | None = None
    auth: AuthSettings = AuthSettings()
    # None: the install keeps no files.
    s3: S3Settings | None = None
    files: FilesSettings = FilesSettings()

    @field_validator("public_url")
    @classmethod
    def _public_url_is_an_origin(cls, url: AnyHttpUrl) -> AnyHttpUrl:
        if url.path not in (None, "", "/") or url.query or url.fragment or url.username or url.password:
            raise ValueError("the address of the install's root, such as https://home.example.org")
        return url

    @field_validator("retired_secret_keys", mode="before")
    @classmethod
    def _comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("retired_secret_keys")
    @classmethod
    def _long_enough(cls, keys: list[SecretStr]) -> list[SecretStr]:
        if any(len(key.get_secret_value()) < SECRET_KEY_MIN_LENGTH for key in keys):
            raise ValueError(f"every retired key has at least {SECRET_KEY_MIN_LENGTH} characters, as the key had")
        return keys

    @property
    def public_origin(self) -> str:
        """The ``Origin`` header a browser sends from the install's own pages."""
        return origin_of(str(self.public_url))

    @property
    def passkey_rp_id(self) -> str:
        """The passkeys' relying party: the host name people open, which browsers check passkeys against."""
        return PublicLinks(origin=self.public_origin).host

    @property
    def oidc_redirect_uri(self) -> str:
        """Where the provider sends the browser back: register it with the provider."""
        return self.public_origin + OIDC_CALLBACK_PATH

    @property
    def serves_https(self) -> bool:
        return self.public_url.scheme == "https"
