import asyncio
import os
from pathlib import Path

import pytest

from penaria.apps.worker import loop
from penaria.apps.worker.health import STALE_SECONDS, is_alive

pytestmark = pytest.mark.unit


class Queue:
    """Two files wait; the first pass fails as with a database that restarts."""

    def __init__(self, stop: asyncio.Event) -> None:
        self._stop = stop
        self.results: list[bool | Exception] = [ConnectionError("the database restarts"), True, True, False]

    async def execute(self) -> bool:
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        if not result:
            self._stop.set()
        return result


class Sweeper:
    def __init__(self) -> None:
        self.runs = 0

    async def execute(self) -> None:
        self.runs += 1


async def test_the_loop_survives_a_failed_pass_and_beats_after_a_good_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "POLL_SECONDS", 0)
    stop = asyncio.Event()
    queue, sweeper = Queue(stop), Sweeper()

    await loop.process_files(queue, sweeper, stop, tmp_path / "alive")  # type: ignore[arg-type]

    assert queue.results == []
    assert sweeper.runs == 1
    assert (tmp_path / "alive").exists()


async def test_a_worker_whose_passes_all_fail_does_not_beat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop, "POLL_SECONDS", 0)
    stop = asyncio.Event()

    class Away:
        async def execute(self) -> bool:
            stop.set()
            raise ConnectionError("the database is away")

    await loop.process_files(Away(), Sweeper(), stop, tmp_path / "alive")  # type: ignore[arg-type]

    assert not (tmp_path / "alive").exists()


async def test_without_storage_the_worker_idles_until_it_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "POLL_SECONDS", 0.001)
    stop = asyncio.Event()
    running = asyncio.create_task(loop.idle(stop, tmp_path / "alive"))
    await asyncio.sleep(0.01)
    assert not running.done()

    stop.set()
    await running

    assert (tmp_path / "alive").exists()


def test_the_worker_is_alive_while_its_heartbeat_is_fresh(tmp_path: Path) -> None:
    heartbeat = tmp_path / "alive"
    assert is_alive(heartbeat, now=1000.0) is False
    heartbeat.touch()
    os.utime(heartbeat, (1000.0, 1000.0))

    assert is_alive(heartbeat, now=1000.0 + STALE_SECONDS - 1) is True
    assert is_alive(heartbeat, now=1000.0 + STALE_SECONDS) is False
