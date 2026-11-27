"""The worker's loop: it processes the files that wait, empties the trash and tells that it is alive."""

import asyncio
import contextlib
import logging
import math
import time
from pathlib import Path

from penaria.apps.worker.health import HEARTBEAT
from penaria.features.support.documents.use_cases.processing import ProcessNextFile
from penaria.features.support.documents.use_cases.sweep import SweepFiles

# A photo is ready within a couple of seconds of its upload; one indexed query per pass.
POLL_SECONDS = 2
# The trash is emptied and abandoned uploads forgotten within the hour.
SWEEP_SECONDS = 3600

logger = logging.getLogger(__name__)


async def process_files(
    processor: ProcessNextFile, sweeper: SweepFiles, stop: asyncio.Event, heartbeat: Path = HEARTBEAT
) -> None:
    swept_at = -math.inf
    while not stop.is_set():
        try:
            while not stop.is_set() and await processor.execute():
                heartbeat.touch()
            if time.monotonic() - swept_at >= SWEEP_SECONDS:
                await sweeper.execute()
                swept_at = time.monotonic()
            heartbeat.touch()
        except Exception:
            # The database or the storage may be restarting; the files wait for the next pass.
            logger.exception("The worker's pass failed; it tries again in %d seconds", POLL_SECONDS)
        await _pause(stop, POLL_SECONDS)


async def idle(stop: asyncio.Event, heartbeat: Path = HEARTBEAT) -> None:
    """Without storage there is nothing to do; exiting would only have the process restarted."""
    logger.warning("PENARIA_S3__* is not set, so Penaria keeps no files: the worker has nothing to do")
    while not stop.is_set():
        heartbeat.touch()
        await _pause(stop, POLL_SECONDS)


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)
