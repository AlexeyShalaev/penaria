"""Settings of the API process, read from the environment only."""

from typing import Annotated, Self

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode
from servicewright.adapters.fastapi import HttpServerSettings

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings
from penaria.common.urls import origin_of
from penaria.features.shared.errors import InvalidError
from penaria.features.support.identity.domain.mailbox import (
    DEFAULT_PORTS,
    Mailbox,
    MailboxFields,
    MailboxSource,
    MailSecurity,
)

# Stored secrets are encrypted with keys derived from it; shorter keys are too easy to guess.
SECRET_KEY_MIN_LENGTH = 32


class MailSettings(BaseModel):
    """``PENARIA_MAIL__*``: the install's mailbox, set by the operator. It wins over the interface as a whole:
    with ``PENARIA_MAIL__HOST`` set, every mail setting comes from here (sign-in.md, 9.1)."""

    host: str | None = None
    # The usual port of the security when unset: 587, 465 or 25.
    port: int | None = Field(default=None, ge=1, le=65535)
    security: MailSecurity = MailSecurity.STARTTLS
    username: str | None = None
    password: SecretStr | None = None
    from_address: str | None = None
    from_name: str | None = None

    @model_validator(mode="after")
    def _whole(self) -> Self:
        if self.host is None:
            if self.model_fields_set:
                raise ValueError("PENARIA_MAIL__HOST is required once any PENARIA_MAIL__* variable is set")
            return self
        if self.from_address is None:
            raise ValueError("PENARIA_MAIL__FROM_ADDRESS is required with PENARIA_MAIL__HOST")
        try:
            self.fields()
        except InvalidError as exc:
            field = str(exc.params.get("field", "host")).upper()
            raise ValueError(f"PENARIA_MAIL__{field} is not valid: {exc}") from exc
        return self

    def fields(self) -> MailboxFields:
        if self.host is None or self.from_address is None:
            raise RuntimeError("no mailbox is set in the environment")
        return MailboxFields.check(
            host=self.host,
            port=self.port or DEFAULT_PORTS[self.security],
            security=self.security,
            username=self.username,
            from_address=self.from_address,
            from_name=self.from_name,
        )

    def mailbox(self) -> Mailbox | None:
        """The operator's mailbox, or None when the environment sets none."""
        if self.host is None:
            return None
        password = None if self.password is None else self.password.get_secret_value()
        return Mailbox(fields=self.fields(), password=password, source=MailboxSource.ENVIRONMENT)


class Settings(PenariaSettings):
    server: HttpServerSettings = HttpServerSettings()
    database: DatabaseSettings
    # The address people open, such as https://home.example.org: the web app and the API behind it.
    public_url: AnyHttpUrl
    secret_key: SecretStr = Field(min_length=SECRET_KEY_MIN_LENGTH)
    # Earlier values of PENARIA_SECRET_KEY, separated by commas: what they encrypted still opens.
    retired_secret_keys: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)
    mail: MailSettings = MailSettings()

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
        if self.public_url.host is None:
            raise RuntimeError("PENARIA_PUBLIC_URL has no host")
        return self.public_url.host

    @property
    def serves_https(self) -> bool:
        return self.public_url.scheme == "https"
