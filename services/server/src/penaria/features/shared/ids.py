"""Identifiers: UUIDv7, so ids sort by creation time."""

import uuid


def new_id() -> uuid.UUID:
    return uuid.uuid7()
