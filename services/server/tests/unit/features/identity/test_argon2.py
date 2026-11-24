import pytest
from argon2 import PasswordHasher

from penaria.features.support.identity.infra.argon2 import Argon2PasswordHasher

pytestmark = pytest.mark.unit


async def test_a_password_matches_its_hash_only() -> None:
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash("tulip garden")

    assert password_hash.startswith("$argon2id$")
    assert await hasher.verify(password_hash, "tulip garden")
    assert not await hasher.verify(password_hash, "tulip gardens")


async def test_no_account_never_matches() -> None:
    assert not await Argon2PasswordHasher().verify(None, "tulip garden")


async def test_a_hash_made_with_other_parameters_is_redone() -> None:
    hasher = Argon2PasswordHasher()
    old = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("tulip garden")

    assert hasher.needs_rehash(old)
    assert not hasher.needs_rehash(await hasher.hash("tulip garden"))
    assert await hasher.verify(old, "tulip garden")


async def test_a_corrupt_hash_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="not a valid Argon2 hash"):
        await Argon2PasswordHasher().verify("not-a-hash", "tulip garden")
