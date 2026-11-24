"""The eight kinds of entity, where each may sit, and the other closed vocabularies."""

from datetime import timedelta
from enum import StrEnum


class Kind(StrEnum):
    PROPERTY = "property"
    BUILDING = "building"
    FLOOR = "floor"
    SPACE = "space"
    CONTAINER = "container"
    ITEM = "item"
    DEVICE = "device"
    SYSTEM = "system"


# The tree is physical (docs/design/core-model.md, section 4.1); None is the root of the home.
ALLOWED_PARENTS: dict[Kind, frozenset[Kind | None]] = {
    Kind.PROPERTY: frozenset({None}),
    Kind.BUILDING: frozenset({Kind.PROPERTY}),
    Kind.FLOOR: frozenset({Kind.BUILDING}),
    Kind.SPACE: frozenset({Kind.PROPERTY, Kind.BUILDING, Kind.FLOOR, Kind.SPACE}),
    Kind.CONTAINER: frozenset({Kind.SPACE, Kind.CONTAINER, Kind.ITEM}),
    Kind.ITEM: frozenset({Kind.SPACE, Kind.CONTAINER, Kind.ITEM}),
    Kind.DEVICE: frozenset({Kind.SPACE, Kind.CONTAINER, Kind.ITEM}),
    Kind.SYSTEM: frozenset({Kind.PROPERTY, Kind.BUILDING, Kind.SYSTEM}),
}

MAX_DEPTH = 32


class Status(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    LENT = "lent"
    IN_REPAIR = "in_repair"


class Privacy(StrEnum):
    NORMAL = "normal"
    GUEST_VISIBLE = "guest_visible"
    PRIVATE = "private"


class ArchiveReason(StrEnum):
    DISCARDED = "discarded"
    SOLD = "sold"
    GIVEN_AWAY = "given_away"
    USED_UP = "used_up"
    MERGED = "merged"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    DOUBTFUL = "doubtful"


# How long a verified place stays fresh; None never goes stale (section 8).
FRESH_FOR: dict[Kind, timedelta | None] = {
    Kind.ITEM: timedelta(days=90),
    Kind.DEVICE: timedelta(days=180),
    Kind.CONTAINER: timedelta(days=365),
    Kind.SPACE: timedelta(days=365),
    Kind.PROPERTY: None,
    Kind.BUILDING: None,
    Kind.FLOOR: None,
    Kind.SYSTEM: None,
}
