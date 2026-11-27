"""``python -m penaria.features.support.documents.infra.render <source> <media type> <directory>``

Clean and preview one file into the directory, and write what came of it there as ``result.json``. Run
only by ``sandbox.py``, in a process of its own: Pillow, libheif and PDFium parse what strangers made.
"""

import io
import json
import resource
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pillow_heif
import pypdfium2
from PIL import Image, ImageOps

from penaria.features.support.documents.domain.files import (
    HEIC,
    JPEG,
    PDF,
    PNG,
    WEBP,
    FileFailure,
    stored_type,
)
from penaria.features.support.documents.domain.metadata import (
    ORIENTATIONS,
    UPRIGHT,
    DamagedImageError,
    UnknownVariantError,
    strip,
)
from penaria.features.support.documents.domain.processing import MAX_PIXELS, UnrenderableError
from penaria.features.support.documents.domain.storage import LARGE_PREVIEW, PREVIEW_SIZES
from penaria.features.support.documents.infra.sandbox import ORIGINAL_NAME, RESULT_NAME, preview_name

# Enough for an image of the largest size decoded, with room to spare; a file that takes more is a bomb.
MEMORY_LIMIT_BYTES = 2 * 1024**3
CPU_LIMIT_SECONDS = 100
# What Pillow calls the format of each type it is asked to read.
FORMATS = {JPEG: ("JPEG", "MPO"), PNG: ("PNG",), WEBP: ("WEBP",), HEIC: ("HEIF",)}
JPEG_QUALITY_OF_HEIC = 92
PREVIEW_QUALITY = 80
ORIENTATION_TAG = 0x0112
EXIF_IFD = 0x8769
DATE_TIME_ORIGINAL = 0x9003
OFFSET_TIME_ORIGINAL = 0x9011
# The orientations that swap width and height.
SIDEWAYS = frozenset({5, 6, 7, 8})
# What Pillow raises on a damaged or nonsensical TIFF structure, which EXIF is.
UNREADABLE_EXIF = (SyntaxError, ValueError, TypeError, KeyError, OSError, struct.error)


def main() -> None:
    _limit_resources()
    source, media_type, directory = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    try:
        result = render_pdf(source, directory) if media_type == PDF else render_image(source, media_type, directory)
    except UnrenderableError as exc:
        result = {"failure": exc.reason.value, "detail": str(exc)}
    # A file rather than the output, where the libraries may write what they please.
    (directory / RESULT_NAME).write_text(json.dumps(result), encoding="utf-8")


def render_image(source: Path, media_type: str, directory: Path) -> dict[str, Any]:
    data = source.read_bytes()
    clean, facts = _heic_to_jpeg(data) if media_type == HEIC else _cleaned(data, media_type)
    (directory / ORIGINAL_NAME).write_bytes(clean)
    # The previews come from the clean copy, which is also proof that it still reads as the picture.
    with _decoded(clean, stored_type(media_type)) as image:
        # In place: a copy of the largest picture would take hundreds of megabytes more.
        ImageOps.exif_transpose(image, in_place=True)
        _write_previews(image, directory)
    return {**facts, "original": True, "previews": True}


def render_pdf(source: Path, directory: Path) -> dict[str, Any]:
    try:
        document = pypdfium2.PdfDocument(source)
        page = document[0]
        width, height = page.get_size()
        # Drawn at the size of the large preview, whatever size the page claims to be.
        picture = page.render(scale=LARGE_PREVIEW / max(width, height, 1)).to_pil()
    except (pypdfium2.PdfiumError, IndexError) as exc:
        raise UnrenderableError(FileFailure.BROKEN, f"the PDF cannot be drawn: {exc}") from exc
    _write_previews(picture, directory)
    return {"original": False, "width": None, "height": None, "taken_at": None, "previews": True}


def _cleaned(data: bytes, media_type: str) -> tuple[bytes, dict[str, Any]]:
    """The image without metadata, and the facts of it that are kept in the database."""
    with _decoded(data, media_type) as image:
        exif = Image.Exif()
        orientation, taken_at = _from_exif(exif, image.info.get("exif", b""))
        facts = _facts(image.width, image.height, orientation, taken_at)
    try:
        return strip(data, media_type, orientation), facts
    except UnknownVariantError as exc:
        raise UnrenderableError(FileFailure.UNSUPPORTED, str(exc)) from exc
    except DamagedImageError as exc:
        raise UnrenderableError(FileFailure.BROKEN, str(exc)) from exc


def _heic_to_jpeg(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """HEIC cannot be cleaned in place and browsers cannot show it. libheif applies the orientation as
    it decodes, and nothing but the pixels and the colour profile goes into the JPEG."""
    pillow_heif.register_heif_opener()
    with _decoded(data, HEIC) as image:
        # libheif has turned the picture already, whatever EXIF says.
        _, taken_at = _from_exif(Image.Exif(), image.info.get("exif", b""))
        facts = _facts(image.width, image.height, UPRIGHT, taken_at)
        profile = image.info.get("icc_profile")
        picture = _opaque(image)
        buffer = io.BytesIO()
        picture.info = {}
        picture.save(buffer, "JPEG", quality=JPEG_QUALITY_OF_HEIC, icc_profile=profile, exif=b"")
    return strip(buffer.getvalue(), JPEG, UPRIGHT), facts


def _decoded(data: bytes, media_type: str) -> Image.Image:
    """The image, fully decoded, within the limit of pixels."""
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in FORMATS[media_type]:
            raise UnrenderableError(FileFailure.BROKEN, f"the content is {image.format}, not {media_type}")
        # Checked before a pixel is decoded.
        if image.width * image.height > MAX_PIXELS:
            raise UnrenderableError(FileFailure.TOO_MANY_PIXELS, f"{image.width} x {image.height} pixels")
        image.load()
    except Image.DecompressionBombError as exc:
        raise UnrenderableError(FileFailure.TOO_MANY_PIXELS, str(exc)) from exc
    # What the decoders raise on damaged files; Pillow's UnidentifiedImageError is an OSError.
    except (OSError, SyntaxError, ValueError, EOFError) as exc:
        raise UnrenderableError(FileFailure.BROKEN, f"the image cannot be read: {exc}") from exc
    return image


def _from_exif(exif: Image.Exif, raw: bytes) -> tuple[int, str | None]:
    """The orientation and when the photo was taken. EXIF that cannot be read is no EXIF: it goes with the
    rest of the metadata, and no viewer could have followed it either."""
    try:
        exif.load(raw)
        orientation = exif.get(ORIENTATION_TAG, UPRIGHT)
        taken_at = _taken_at(exif)
    except UNREADABLE_EXIF:
        return UPRIGHT, None
    return (orientation if orientation in ORIENTATIONS else UPRIGHT), taken_at


def _facts(width: int, height: int, orientation: int, taken_at: str | None) -> dict[str, Any]:
    if orientation in SIDEWAYS:
        width, height = height, width
    return {"width": width, "height": height, "taken_at": taken_at}


def _taken_at(exif: Image.Exif) -> str | None:
    """When the photo was taken, as ISO 8601, with the offset if the camera wrote one.

    Cameras write all sorts of things here, zeros among them: what is not a date is left out.
    """
    details = exif.get_ifd(EXIF_IFD)
    written = details.get(DATE_TIME_ORIGINAL)
    if not isinstance(written, str):
        return None
    try:
        taken = datetime.strptime(written.strip("\0 "), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    offset = details.get(OFFSET_TIME_ORIGINAL)
    if isinstance(offset, str):
        try:
            return datetime.fromisoformat(taken.isoformat() + offset.strip("\0 ")).isoformat()
        except ValueError:
            return taken.isoformat()
    return taken.isoformat()


def _write_previews(picture: Image.Image, directory: Path) -> None:
    """A WebP of each size, never larger than the picture; no metadata goes into them.

    Shrinks ``picture`` itself, the larger size first.
    """
    profile = picture.info.get("icc_profile") if picture.mode in ("RGB", "RGBA") else None
    if picture.mode not in ("RGB", "RGBA"):
        picture = picture.convert("RGBA" if picture.has_transparency_data else "RGB")
    for size in sorted(PREVIEW_SIZES, reverse=True):
        picture.thumbnail((size, size), Image.Resampling.LANCZOS)
        picture.info = {}
        picture.save(
            directory / preview_name(size), "WEBP", quality=PREVIEW_QUALITY, icc_profile=profile, exif=b"", xmp=b""
        )


def _opaque(image: Image.Image) -> Image.Image:
    """The picture in RGB, transparent parts white: JPEG has no transparency."""
    if not image.has_transparency_data:
        return image.convert("RGB")
    background = Image.new("RGBA", image.size, "white")
    return Image.alpha_composite(background, image.convert("RGBA")).convert("RGB")


def _limit_resources() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS))
    # macOS, where only developers run this, does not enforce a limit of memory and refuses to set it.
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_DATA, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    # Pillow refuses to decode what is far over the limit by itself, before the check in _decoded.
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS


if __name__ == "__main__":
    main()
