"""Argon2id password hashes (argon2-cffi), computed off the event loop."""

import asyncio
import os
import secrets
from collections.abc import Callable

import argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class Argon2PasswordHasher:
    """The library's defaults, RFC 9106's low-memory profile; a hash made with older ones is redone on sign-in.

    Each hash takes 64 MiB and ``parallelism`` cores, so only as many run at once as the cores allow;
    the rest wait, and a burst of attempts cannot exhaust the machine's memory.
    """

    def __init__(self) -> None:
        self._hasher = argon2.PasswordHasher()
        self._running = asyncio.Semaphore(max(1, (os.cpu_count() or 1) // self._hasher.parallelism))
        self._dummy_hash: str | None = None

    async def hash(self, password: str) -> str:
        return await self._run(self._hasher.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        if password_hash is None:
            # An unknown account costs as much as a known one, so the time does not tell them apart.
            await self._run(self._verify, await self._dummy(), password)
            return False
        return await self._run(self._verify, password_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)

    def _verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except (VerificationError, InvalidHashError) as exc:
            raise RuntimeError("a stored password hash is not a valid Argon2 hash") from exc

    async def _run[T](self, work: Callable[..., T], *args: str) -> T:
        async with self._running:
            return await asyncio.to_thread(work, *args)

    async def _dummy(self) -> str:
        if self._dummy_hash is None:
            self._dummy_hash = await self.hash(secrets.token_urlsafe(16))
        return self._dummy_hash
