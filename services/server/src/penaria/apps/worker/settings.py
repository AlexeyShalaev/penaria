"""Settings of the worker process, read from the environment only."""

from typing import Any

from pydantic import SecretStr

from penaria.common.database import DatabaseSettings
from penaria.common.settings import PenariaSettings
from penaria.integrations.s3.settings import S3Settings


class Settings(PenariaSettings):
    database: DatabaseSettings
    # None: the install keeps no files, and the worker has nothing to do.
    s3: S3Settings | None = None
    # One environment serves every process of the image; the worker needs none of these,
    # but must not refuse them as unknown.
    public_url: str | None = None
    secret_key: SecretStr | None = None
    retired_secret_keys: SecretStr | None = None
    mail: dict[str, Any] | None = None
    auth: dict[str, Any] | None = None
    server: dict[str, Any] | None = None
    files: dict[str, Any] | None = None
