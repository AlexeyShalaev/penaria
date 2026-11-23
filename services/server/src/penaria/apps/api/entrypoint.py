"""The service spec and the HTTP entrypoint of the API process."""

from servicewright import AppSpec
from servicewright.adapters.dishka import DishkaContainer
from servicewright.adapters.fastapi import FastApiEntrypoint

from penaria import __version__
from penaria.apps.api.container import build_container
from penaria.apps.api.settings import Settings

SERVICE_NAME = "penaria-api"


def build_spec() -> AppSpec[Settings, DishkaContainer]:
    return AppSpec(service_name=SERVICE_NAME, create_container=build_container)


def build_http(settings: Settings) -> FastApiEntrypoint:
    return FastApiEntrypoint(config=settings.server.to_config(version=__version__))
