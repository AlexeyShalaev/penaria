"""Settings of the migrate process, read from the environment only."""

from pydantic import SecretStr

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings


class Settings(PenariaSettings):
    database: DatabaseSettings
    # One environment serves every process of the image; migrate needs neither of the api's own
    # settings, but must not refuse them as unknown.
    public_url: str | None = None
    secret_key: SecretStr | None = None
