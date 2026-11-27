"""Rendering as the worker runs it: in a process of its own."""

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from penaria.features.support.documents.domain.files import HEIC, JPEG, PDF, PNG, FileFailure
from penaria.features.support.documents.domain.processing import Rendered, RendererCrashedError, UnrenderableError
from penaria.features.support.documents.infra.sandbox import SandboxRenderer
from tests import images

pytestmark = pytest.mark.unit

MOSCOW_SUMMER = timezone(timedelta(hours=3))


async def render(tmp_path: Path, data: bytes, media_type: str) -> Rendered:
    source = tmp_path / "upload"
    source.write_bytes(data)
    return await SandboxRenderer().render(source, media_type, tmp_path)


def size_of(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def left_and_right(path: Path) -> tuple[str, str]:
    """The colour at the middle of the left and of the right edge."""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        found = []
        for x in (2, rgb.width - 3):
            red, _, blue = rgb.getpixel((x, rgb.height // 2))  # type: ignore[misc]
            found.append("red" if red > blue else "blue")
        return found[0], found[1]


async def test_a_jpeg_is_cleaned_previewed_and_its_facts_read(tmp_path: Path) -> None:
    rendered = await render(tmp_path, images.jpeg(6), JPEG)

    assert rendered.original is not None
    assert images.SECRET not in rendered.original.read_bytes()
    # Turned a quarter, as the camera asked: 48 x 32 is shown as 32 x 48.
    assert (rendered.media_type, rendered.width, rendered.height) == (JPEG, 32, 48)
    assert rendered.taken_at == datetime(2026, 11, 20, 10, 11, 12, tzinfo=MOSCOW_SUMMER)
    assert {size: size_of(path) for size, path in rendered.previews.items()} == {1600: (32, 48), 320: (32, 48)}
    for preview in rendered.previews.values():
        data = preview.read_bytes()
        assert images.SECRET not in data
        assert b"EXIF" not in data


async def test_a_photo_without_an_offset_keeps_its_local_time(tmp_path: Path) -> None:
    rendered = await render(tmp_path, images.jpeg(offset=None), JPEG)

    assert rendered.taken_at == datetime(2026, 11, 20, 10, 11, 12)


async def test_a_png_keeps_its_transparency_and_loses_its_text(tmp_path: Path) -> None:
    rendered = await render(tmp_path, images.png(), PNG)

    assert rendered.original is not None
    assert images.SECRET not in rendered.original.read_bytes()
    with Image.open(rendered.previews[320]) as preview:
        assert preview.mode == "RGBA"


async def test_heic_becomes_a_jpeg_without_metadata_turned_as_it_was_shown(tmp_path: Path) -> None:
    rendered = await render(tmp_path, images.heic(orientation=3), HEIC)

    assert rendered.original is not None
    data = rendered.original.read_bytes()
    assert images.SECRET not in data
    assert b"Exif" not in data
    assert b"xmpmeta" not in data
    with Image.open(io.BytesIO(data)) as image:
        assert (image.format, dict(image.getexif()), image.info["icc_profile"]) == ("JPEG", {}, images.ICC)
    assert (rendered.media_type, rendered.width, rendered.height) == (JPEG, 64, 48)
    # libheif applies what the camera asked while it decodes: a half turn swaps the sides.
    assert left_and_right(rendered.original) == ("blue", "red")
    assert rendered.taken_at == datetime(2026, 11, 20, 10, 11, 12, tzinfo=MOSCOW_SUMMER)


async def test_a_large_picture_gets_previews_of_both_sizes(tmp_path: Path) -> None:
    out = io.BytesIO()
    images.picture(size=(2000, 1000)).save(out, "JPEG")

    rendered = await render(tmp_path, out.getvalue(), JPEG)

    assert {size: size_of(path) for size, path in rendered.previews.items()} == {1600: (1600, 800), 320: (320, 160)}


async def test_the_first_page_of_a_pdf_is_previewed_and_the_pdf_kept(tmp_path: Path) -> None:
    rendered = await render(tmp_path, images.pdf(), PDF)

    assert rendered.original is None
    assert max(size_of(rendered.previews[1600])) == 1600
    assert max(size_of(rendered.previews[320])) == 320


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (images.jpeg()[:200], JPEG),
        (images.png()[:-40], PNG),
        (b"\xff\xd8\xff nothing", JPEG),
        (b"%PDF-1.7 nothing", PDF),
        (images.png(), JPEG),
    ],
    ids=["cut-jpeg", "cut-png", "no-jpeg", "no-pdf", "png-as-jpeg"],
)
async def test_a_damaged_file_cannot_be_rendered(tmp_path: Path, data: bytes, media_type: str) -> None:
    with pytest.raises(UnrenderableError) as raised:
        await render(tmp_path, data, media_type)

    assert raised.value.reason is FileFailure.BROKEN


async def test_an_image_over_a_hundred_megapixels_is_refused_before_it_is_decoded(tmp_path: Path) -> None:
    out = io.BytesIO()
    # One bit per pixel compresses to a few kilobytes: a bomb, as a crafted one would be.
    Image.new("1", (11_000, 9_100)).save(out, "PNG")

    with pytest.raises(UnrenderableError) as raised:
        await render(tmp_path, out.getvalue(), PNG)

    assert raised.value.reason is FileFailure.TOO_MANY_PIXELS


async def test_rendering_that_takes_too_long_is_stopped(tmp_path: Path) -> None:
    source = tmp_path / "upload"
    source.write_bytes(images.jpeg())

    with pytest.raises(RendererCrashedError, match="longer than"):
        await SandboxRenderer(timeout_seconds=0.001).render(source, JPEG, tmp_path)


async def test_the_renderer_gets_none_of_the_servers_environment(tmp_path: Path) -> None:
    # A child that dies is a crash, not an answer: here it is asked to read a file that is not there.
    with pytest.raises(RendererCrashedError, match="code 1"):
        await SandboxRenderer().render(tmp_path / "missing", JPEG, tmp_path)
