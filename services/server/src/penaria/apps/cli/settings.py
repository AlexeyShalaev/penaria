"""Settings of the command line, read from the environment only."""

from typing import Any

from pydantic import AnyHttpUrl, SecretStr

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings
from penaria.common.urls import origin_of


class Settings(PenariaSettings):
    database: DatabaseSettings
    # The links it prints open the web app there.
    public_url: AnyHttpUrl
    # One environment serves every process of the image; the command line needs none of these,
    # but must not refuse them as unknown.
    secret_key: SecretStr | None = None
    retired_secret_keys: SecretStr | None = None
    mail: dict[str, Any] | None = None

    @property
    def public_origin(self) -> str:
        return origin_of(str(self.public_url))
