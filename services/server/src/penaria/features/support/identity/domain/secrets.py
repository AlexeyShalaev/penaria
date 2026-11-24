"""Secrets kept in the database encrypted with ``PENARIA_SECRET_KEY`` (sign-in.md, 9 and 15)."""

from typing import Protocol


class SecretUnreadableError(Exception):
    """A stored secret does not open: its key is gone, or it was moved from the record it was sealed for."""


class SecretBox(Protocol):
    def seal(self, plaintext: str, *, bound_to: str) -> str:
        """The secret encrypted for storage, opened only with the same ``bound_to``."""
        ...

    def open(self, sealed: str, *, bound_to: str) -> str:
        """The secret ``seal`` made; ``SecretUnreadableError`` when it does not open."""
        ...


def bound_to(table: str, column: str, key: object) -> str:
    """What ties a sealed secret to its cell: moved to another row, column or table, it does not open."""
    return f"{table}/{column}/{key}"
