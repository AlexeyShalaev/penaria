"""``python -m penaria.apps.worker``."""

from servicewright import Service, run_sync

from penaria.apps.worker.entrypoint import build_daemon, build_spec
from penaria.apps.worker.settings import Settings


def main() -> None:
    settings = Settings()
    run_sync(Service(build_spec(), entrypoints=[build_daemon(settings)]), settings)


if __name__ == "__main__":
    main()
