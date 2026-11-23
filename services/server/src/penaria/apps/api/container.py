"""The DI container of the API process."""

from dishka import make_async_container
from servicewright.adapters.dishka import DishkaContainer

from penaria.apps.api.settings import Settings


def build_container(settings: Settings) -> DishkaContainer:
    return DishkaContainer(make_async_container())
