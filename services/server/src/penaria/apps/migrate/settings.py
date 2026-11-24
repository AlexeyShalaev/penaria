"""Settings of the migrate process, read from the environment only."""

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings


class Settings(PenariaSettings):
    database: DatabaseSettings
