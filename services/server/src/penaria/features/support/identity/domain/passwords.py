"""What the use cases need from password hashing."""

from typing import Protocol


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...

    async def verify(self, password_hash: str | None, password: str) -> bool:
        """Whether ``password`` matches; ``None`` (no such account) spends the same time and answers no."""
        ...

    def needs_rehash(self, password_hash: str) -> bool:
        """Whether the hash was made with other parameters than today's."""
        ...
