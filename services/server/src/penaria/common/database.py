"""PostgreSQL plumbing every process shares: the connection settings and the ORM base."""

import datetime
import uuid
from typing import ClassVar

from pydantic_settings import SettingsConfigDict
from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy_foundation_kit import DB_NAMING_CONVENTION
from sqlalchemy_foundation_kit.contrib.settings import BasePostgresConfig

from penaria.common.settings import ENV_PREFIX, NESTED_DELIMITER


class DatabaseSettings(BasePostgresConfig):
    """The ``database`` section: ``PENARIA_DATABASE__CONNECTION__HOST``, ``..._PASSWORD`` and so on.

    The kit's model is a ``BaseSettings`` that also reads the environment by itself when built;
    the same prefix keeps that reading identical to the process settings' own.
    """

    model_config = SettingsConfigDict(
        env_prefix=f"{ENV_PREFIX}DATABASE{NESTED_DELIMITER}", env_nested_delimiter=NESTED_DELIMITER
    )

    application_name: str = "penaria"


class Base(DeclarativeBase):
    """The base of every ORM model; the naming convention gives every constraint a stable name."""

    metadata = MetaData(naming_convention=DB_NAMING_CONVENTION)
    type_annotation_map: ClassVar = {
        uuid.UUID: UUID(as_uuid=True),
        datetime.datetime: TIMESTAMP(timezone=True),
    }
