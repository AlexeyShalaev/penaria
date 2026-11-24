"""``python -m penaria.apps.api``."""

from servicewright import Service, run_sync

from penaria.apps.api.entrypoint import build_http, build_spec
from penaria.apps.api.mail import build_mail_loop
from penaria.apps.api.settings import Settings


def main() -> None:
    settings = Settings()
    run_sync(Service(build_spec(), entrypoints=[build_http(settings), build_mail_loop()]), settings)


if __name__ == "__main__":
    main()
