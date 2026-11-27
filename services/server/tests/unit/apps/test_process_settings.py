"""One environment serves every process of the image: each accepts the others' variables."""

import pytest
from pydantic import ValidationError

from penaria.apps.api.settings import Settings as ApiSettings
from penaria.apps.cli.settings import Settings as CliSettings
from penaria.apps.migrate.settings import Settings as MigrateSettings
from penaria.apps.worker.settings import Settings as WorkerSettings

pytestmark = pytest.mark.unit

PROCESSES = [ApiSettings, CliSettings, MigrateSettings, WorkerSettings]
SECRET = "storage-secret-of-the-test"  # noqa: S105 - a value of the tests


def storage_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_S3__ENDPOINT", "http://s3:9000")
    monkeypatch.setenv("PENARIA_S3__BUCKET", "penaria")
    monkeypatch.setenv("PENARIA_S3__ACCESS_KEY_ID", "penaria")
    monkeypatch.setenv("PENARIA_S3__SECRET_ACCESS_KEY", SECRET)
    monkeypatch.setenv("PENARIA_FILES__MAX_SIZE", "1048576")


@pytest.mark.parametrize("settings", PROCESSES)
def test_every_process_accepts_the_storage_and_file_variables(
    monkeypatch: pytest.MonkeyPatch, settings: type[ApiSettings]
) -> None:
    storage_variables(monkeypatch)
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__FROM_ADDRESS", "home@example.org")
    monkeypatch.setenv("PENARIA_SERVER__UVICORN__FORWARDED_ALLOW_IPS", "10.0.0.1")
    monkeypatch.setenv("PENARIA_AUTH__OIDC__ISSUER", "https://auth.example.org")
    monkeypatch.setenv("PENARIA_AUTH__OIDC__CLIENT_ID", "penaria")
    monkeypatch.setenv("PENARIA_AUTH__OIDC__CLIENT_SECRET", "a-provider-secret")

    assert settings().database.connection.database == "unit"


@pytest.mark.parametrize("settings", PROCESSES)
def test_a_misspelt_storage_variable_stops_the_process_that_reads_it(
    monkeypatch: pytest.MonkeyPatch, settings: type[ApiSettings]
) -> None:
    storage_variables(monkeypatch)
    monkeypatch.setenv("PENARIA_S4__BUCKET", "penaria")

    with pytest.raises(ValidationError, match="PENARIA_S4__BUCKET"):
        settings()


def test_without_storage_variables_there_is_no_storage() -> None:
    assert (ApiSettings().s3, WorkerSettings().s3, MigrateSettings().s3) == (None, None, None)
    assert ApiSettings().files.max_size == 52428800


def test_the_storage_of_the_environment_takes_paths_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    storage_variables(monkeypatch)

    s3 = ApiSettings().s3

    assert s3 is not None
    assert (str(s3.endpoint), s3.bucket, s3.region, s3.path_style) == ("http://s3:9000/", "penaria", "us-east-1", True)
    assert s3.secret_access_key.get_secret_value() == SECRET
    assert ApiSettings().files.max_size == 1048576


@pytest.mark.parametrize("settings", [ApiSettings, WorkerSettings, MigrateSettings])
def test_half_a_storage_stops_the_process_without_showing_the_secret(
    monkeypatch: pytest.MonkeyPatch, settings: type[ApiSettings]
) -> None:
    monkeypatch.setenv("PENARIA_S3__SECRET_ACCESS_KEY", SECRET)

    with pytest.raises(ValidationError, match=r"s3\.bucket") as raised:
        settings()

    assert SECRET not in str(raised.value)
