"""The ``files`` section of the settings: ``PENARIA_FILES__MAX_SIZE``."""

from pydantic import BaseModel, Field

DEFAULT_MAX_SIZE = 50 * 1024 * 1024


class FilesSettings(BaseModel):
    # The largest file, in bytes. The web image's PENARIA_FILES__MAX_SIZE must be the same.
    max_size: int = Field(default=DEFAULT_MAX_SIZE, gt=0)
