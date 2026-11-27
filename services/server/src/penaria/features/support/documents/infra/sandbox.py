"""Rendering in a process of its own, one per file, so that a crafted file can crash or hang only that.

The child gets none of the server's environment, so no secrets, and a limit of memory and processor
time; the parent gives it a deadline and kills it past it.
"""

import asyncio
import json
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from penaria.features.support.documents.domain.files import FileFailure
from penaria.features.support.documents.domain.processing import (
    Rendered,
    Renderer,
    RendererCrashedError,
    UnrenderableError,
)

TIMEOUT_SECONDS = 120
CHILD_MODULE = "penaria.features.support.documents.infra.render"
RESULT_FILE = "result.json"
STDERR_SHOWN = 2000


class SandboxRenderer(Renderer):
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
        return _outcome(json.loads((into / RESULT_FILE).read_text(encoding="utf-8")), into)


def _ending(returncode: int | None) -> str:
    if returncode is not None and returncode < 0:
        return f"signal {signal.Signals(-returncode).name}"
    return f"code {returncode}"


def _outcome(result: dict[str, Any], into: Path) -> Rendered:
    if "failure" in result:
        raise UnrenderableError(FileFailure(result["failure"]), result["detail"])
    return Rendered(
        original=None if result["original"] is None else into / result["original"],
        media_type=result["media_type"],
        width=result["width"],
        height=result["height"],
        taken_at=None if result["taken_at"] is None else datetime.fromisoformat(result["taken_at"]),
        previews={int(size): into / name for size, name in result["previews"].items()},
    )
