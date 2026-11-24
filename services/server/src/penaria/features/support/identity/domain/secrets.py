"""Secrets kept in the database encrypted with ``PENARIA_SECRET_KEY`` (sign-in.md, 9 and 15)."""

from typing import Protocol


class SecretUnreadableError(Exception):
    """A stored secret does not open: its key is gone, or it was moved from the record it was sealed for."""


class SecretBox(Protocol):
    def seal(self, plaintext: str, *, bound_to: str) -> str:
        """The secret encrypted for storage, opened only with the same ``bound_to``: the record it belongs to,
        such as ``mail/<id>/content``, so a ciphertext copied into another record does not open."""
        ...

    def open(self, sealed: str, *, bound_to: str) -> str:
        """The secret ``seal`` made; ``SecretUnreadableError`` when it does not open."""
        ...
