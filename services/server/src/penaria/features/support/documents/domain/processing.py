"""What turns an upload into a clean file with previews (docs/design/documents.md, 5)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from penaria.features.support.documents.domain.files import FileFailure

MAX_PIXELS = 100_000_000
# A file is taken for this long: longer than rendering and the transfers of its largest size take.
LEASE = timedelta(minutes=10)
# A file whose processing crashed this many times, or took the worker down with it, is given up.
MAX_ATTEMPTS = 3
# A file that failed for now, on the storage or in a crash, waits this long for its next try.
RETRY_DELAY = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class Rendered:
    """What rendering a file produced, as files in the directory it was given."""

    # The cleaned original; None keeps the upload byte for byte.
    original: Path | None = None
    media_type: str | None = None
    width: int | None = None
    height: int | None = None
    # When the photo was taken, as the camera wrote it: aware only if the camera noted its offset.
    taken_at: datetime | None = None
    # The path of each preview, by its longest side.
    previews: dict[int, Path] = field(default_factory=dict)


class UnrenderableError(Exception):
    """The file cannot be rendered, however often it is tried."""

    def __init__(self, reason: FileFailure, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


class RendererCrashedError(Exception):
    """Rendering crashed or ran out of time or memory; another try may succeed."""


class Renderer(Protocol):
    async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
        """Clean and preview an image, or preview a PDF, writing the results into ``into``."""
        ...
