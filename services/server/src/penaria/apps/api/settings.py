"""Settings of the API process, read from the environment only."""

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from servicewright.adapters.fastapi import HttpServerSettings

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings

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
        url = self.public_url
        default_port = {"http": 80, "https": 443}[url.scheme]
        port = "" if url.port in (None, default_port) else f":{url.port}"
        return f"{url.scheme}://{url.host}{port}"
