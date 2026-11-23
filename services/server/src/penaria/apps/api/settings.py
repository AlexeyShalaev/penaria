"""Settings of the API process, read from the environment only."""

from servicewright.adapters.fastapi import HttpServerSettings
from servicewright.adapters.settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    server: HttpServerSettings = HttpServerSettings()
