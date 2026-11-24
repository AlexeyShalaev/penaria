"""The metadata migrations compare against: importing this module registers every ORM model."""

from sqlalchemy import MetaData

from penaria.common.database import Base

# Every package with ORM models is imported here as it lands, so autogenerate and the
# migration tests see the whole schema.

metadata: MetaData = Base.metadata
