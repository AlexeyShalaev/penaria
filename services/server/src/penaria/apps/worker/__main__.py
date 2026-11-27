"""``python -m penaria.apps.worker``."""

from servicewright import Service, run_sync

from penaria.apps.worker.entrypoint import build_daemon, build_spec
from penaria.apps.worker.settings import Settings
from penaria.features.support.documents.infra.sandbox import forbid_reading_this_process


def main() -> None:
    # Before anything: the renderers of strangers' files run as the same user.
    forbid_reading_this_process()
    settings = Settings()
    run_sync(Service(build_spec(), entrypoints=[build_daemon(settings)]), settings)


if __name__ == "__main__":
    main()
