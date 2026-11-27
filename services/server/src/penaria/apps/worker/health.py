"""``python -m penaria.apps.worker.health``: exit 0 if the worker made a pass lately, for a container's
health check; the worker answers no requests."""

import sys
import tempfile
import time
from pathlib import Path

# Written by the loop after every pass that worked. Kept here, so that this check, run every few
# seconds, imports nothing of the worker.
HEARTBEAT = Path(tempfile.gettempdir()) / "penaria-worker.alive"
# Longer than processing the largest file takes.
STALE_SECONDS = 300


def is_alive(heartbeat: Path, now: float) -> bool:
    try:
        beaten_at = heartbeat.stat().st_mtime
    except FileNotFoundError:
        return False
    return now - beaten_at < STALE_SECONDS


def main() -> None:
    sys.exit(0 if is_alive(HEARTBEAT, time.time()) else 1)


if __name__ == "__main__":
    main()
