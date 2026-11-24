import pytest
from alembic.config import Config
from alembic_gauntlet import MigrationTestBase
from sqlalchemy import MetaData

from penaria.migrations.models import metadata
from penaria.migrations.runner import build_config

pytestmark = pytest.mark.integration


class TestMigrations(MigrationTestBase):
    """Every migration upgrades, downgrades and upgrades again; the last one matches the models."""

    @pytest.fixture
    def migration_db_url(self, test_database_url: str) -> str:
        return test_database_url

    @pytest.fixture
    def alembic_config(self) -> Config:
        return build_config()

    @pytest.fixture
    def orm_metadata(self) -> MetaData:
        return metadata
