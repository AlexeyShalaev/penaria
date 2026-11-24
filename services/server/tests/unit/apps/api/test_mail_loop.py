import asyncio
from typing import Any

import pytest

from penaria.apps.api import mail
from penaria.features.support.identity.use_cases.postman import Postman

pytestmark = pytest.mark.unit


class FlakyPostman:
    """Fails its first pass, as when the database restarts, then finds nothing due."""

    def __init__(self, stop: asyncio.Event) -> None:
        self.passes = 0
        self.sweeps = 0
        self._stop = stop

    async def deliver_due(self) -> bool:
        self.passes += 1
        if self.passes == 1:
            raise ConnectionError("the database is restarting")
        if self.passes == 3:
            self._stop.set()
        return False

    async def sweep(self) -> None:
        self.sweeps += 1


class Scope:
    def __init__(self, postman: FlakyPostman) -> None:
        self._postman = postman

    async def get(self, kind: Any) -> Any:
        assert kind is Postman
        return self._postman


async def test_the_mail_loop_outlives_a_failed_pass_and_ends_when_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "POLL_SECONDS", 0)
    stop = asyncio.Event()
    postman = FlakyPostman(stop)

    await asyncio.wait_for(mail.deliver_mail(Scope(postman), stop), timeout=5)

    assert (postman.passes, postman.sweeps) == (3, 1)
