"""The base of every process's settings: environment variables named ``PENARIA_*``.

A section is reached with ``__``: ``PENARIA_SERVER__PORT=8080`` sets ``server.port``. A variable
with the prefix that names no setting stops the process, so a misspelt setting is never ignored.
"""

import os
import types
from collections.abc import Mapping
from typing import Any, Self, Union, get_args, get_origin

from pydantic import BaseModel, model_validator
from pydantic_settings import SettingsConfigDict
from servicewright.adapters.settings import BaseServiceSettings

ENV_PREFIX = "PENARIA_"
NESTED_DELIMITER = "__"


class PenariaSettings(BaseServiceSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_nested_delimiter=NESTED_DELIMITER)

    @model_validator(mode="after")
    def _reject_unknown_variables(self) -> Self:
        unknown = unknown_variables(type(self), os.environ)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unknown environment variables: {names}; check them for typos")
        return self


def unknown_variables(model: type[BaseModel], environ: Mapping[str, str]) -> list[str]:
    """Return the ``PENARIA_*`` variables in ``environ`` that name no field of ``model``."""
    return [
        name
        for name in environ
        if name.upper().startswith(ENV_PREFIX)
        and not _names_a_field(model, name[len(ENV_PREFIX) :].lower().split(NESTED_DELIMITER))
    ]


def _names_a_field(model: type[BaseModel], path: list[str]) -> bool:
    field = model.model_fields.get(path[0])
    if field is None:
        return False
    rest = path[1:]
    if not rest:
        return True
    section = _section_model(field.annotation)
    # A field that is not a section (a mapping, say) takes whatever is below it.
    return section is None or _names_a_field(section, rest)


def _section_model(annotation: Any) -> type[BaseModel] | None:
    candidates = get_args(annotation) if get_origin(annotation) in (Union, types.UnionType) else (annotation,)
    models = [c for c in candidates if isinstance(c, type) and issubclass(c, BaseModel)]
    return models[0] if len(models) == 1 else None
