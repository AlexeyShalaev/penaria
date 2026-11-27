"""Rendering in a process of its own, one per file, so that a crafted file can crash or hang only that.

The child gets none of the worker's environment, a limit of memory and processor time, and a deadline
past which it is killed. The worker is made non-dumpable, so the child cannot read its environment or
memory through /proc either, and takes from the child only facts and files of fixed names. It is a
process, not a boundary of users or networks: code that took over a decoder would still run as the
worker's user.
"""

import asyncio
import ctypes
import json
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from penaria.features.support.documents.domain.files import HEIC, JPEG, FileFailure
from penaria.features.support.documents.domain.processing import (
    Rendered,
    RendererCrashedError,
    UnrenderableError,
)
from penaria.features.support.documents.domain.storage import PREVIEW_SIZES

TIMEOUT_SECONDS = 120
CHILD_MODULE = "penaria.features.support.documents.infra.render"
# What the child writes into its directory.
RESULT_NAME = "result.json"
ORIGINAL_NAME = "original"
STDERR_SHOWN = 2000
# prctl(2)
PR_SET_DUMPABLE = 4


def preview_name(size: int) -> str:
    return f"preview-{size}.webp"


def forbid_reading_this_process() -> None:
    """Make the process non-dumpable, so that another process of the same user, a renderer among them,
    cannot read its environment or memory. Only Linux, where Penaria is run, has this."""
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE) failed")


class SandboxRenderer:
    def __init__(self, timeout_seconds: float = TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            CHILD_MODULE,
            str(source),
            media_type,
            str(into),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env={},
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                _, errors = await process.communicate()
        except TimeoutError as exc:
            raise RendererCrashedError(f"rendering took longer than {self._timeout_seconds} s") from exc
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0:
            raise RendererCrashedError(
                f"the renderer ended with {_ending(process.returncode)}: "
                f"{errors.decode(errors='replace')[-STDERR_SHOWN:]}"
            )
        return _outcome(media_type, into)


def _ending(returncode: int | None) -> str:
    if returncode is not None and returncode < 0:
        return f"signal {signal.Signals(-returncode).name}"
    return f"code {returncode}"


def _outcome(media_type: str, into: Path) -> Rendered:
    """What the child says, as far as it is believed: which of the fixed files exist, and the facts of
    the picture. The type the original is stored as follows from the upload's."""
    result: dict[str, Any] = json.loads(_produced(into / RESULT_NAME).read_text(encoding="utf-8"))
    if "failure" in result:
        raise UnrenderableError(FileFailure(result["failure"]), str(result["detail"]))
    return Rendered(
        original=_produced(into / ORIGINAL_NAME) if result["original"] else None,
        media_type=JPEG if media_type == HEIC else media_type,
        width=None if result["width"] is None else int(result["width"]),
        height=None if result["height"] is None else int(result["height"]),
        taken_at=None if result["taken_at"] is None else datetime.fromisoformat(result["taken_at"]),
        previews={size: _produced(into / preview_name(size)) for size in PREVIEW_SIZES if result["previews"]},
    )


def _produced(path: Path) -> Path:
    """A file the child made: a link could name anything the worker reads, and have it stored."""
    if path.is_symlink() or not path.is_file():
        raise RendererCrashedError(f"the renderer's {path.name} is not a file of its own")
    return path
