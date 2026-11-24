"""Settings of the API process, read from the environment only."""

from servicewright.adapters.fastapi import HttpServerSettings

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings


class Settings(PenariaSettings):
    server: HttpServerSettings = HttpServerSettings()
    database: DatabaseSettings
