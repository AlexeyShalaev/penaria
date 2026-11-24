"""Settings of the API process, read from the environment only."""

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from servicewright.adapters.fastapi import HttpServerSettings

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings
from penaria.common.urls import origin_of

# Later steps of sign-in derive encryption keys from it; shorter keys are too easy to guess.
SECRET_KEY_MIN_LENGTH = 32


class Settings(PenariaSettings):
    server: HttpServerSettings = HttpServerSettings()
    database: DatabaseSettings
    # The address people open, such as https://home.example.org: the web app and the API behind it.
    public_url: AnyHttpUrl
    secret_key: SecretStr = Field(min_length=SECRET_KEY_MIN_LENGTH)

    @field_validator("public_url")
    @classmethod
    def _public_url_is_an_origin(cls, url: AnyHttpUrl) -> AnyHttpUrl:
        if url.path not in (None, "", "/") or url.query or url.fragment or url.username or url.password:
            raise ValueError("the address of the install's root, such as https://home.example.org")
        return url

    @property
    def public_origin(self) -> str:
        """The ``Origin`` header a browser sends from the install's own pages."""
        return origin_of(str(self.public_url))

    @property
    def serves_https(self) -> bool:
        return self.public_url.scheme == "https"
