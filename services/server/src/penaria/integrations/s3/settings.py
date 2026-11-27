"""The ``s3`` section of the settings: ``PENARIA_S3__ENDPOINT``, ``..._BUCKET`` and so on."""

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr


class S3Settings(BaseModel):
    # None: AWS S3 in the region.
    endpoint: AnyHttpUrl | None = None
    bucket: str = Field(min_length=3, max_length=63)
    access_key_id: str = Field(min_length=1)
    secret_access_key: SecretStr = Field(min_length=1)
    region: str = Field(default="us-east-1", min_length=1)
    # The bucket in the path (``endpoint/bucket/key``), as self-hosted storages expect; with ``false``,
    # in the host name (``bucket.endpoint/key``).
    path_style: bool = True
