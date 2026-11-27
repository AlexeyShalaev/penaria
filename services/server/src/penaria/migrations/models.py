"""The metadata migrations compare against: importing this module registers every ORM model."""

from sqlalchemy import MetaData

from penaria.common.database import Base

# Every package with ORM models is imported here, so autogenerate and the migration tests see
# the whole schema.
from penaria.features.core.registry.infra import orm as registry_orm  # noqa: F401
from penaria.features.support.documents.infra import orm as documents_orm  # noqa: F401
from penaria.features.support.identity.infra import orm as identity_orm  # noqa: F401
from penaria.features.support.platform.infra import orm as platform_orm  # noqa: F401

metadata: MetaData = Base.metadata
