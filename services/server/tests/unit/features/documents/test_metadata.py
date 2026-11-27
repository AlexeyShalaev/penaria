import io

import pytest
from PIL import Image

from penaria.features.support.documents.domain.files import JPEG, PNG, WEBP
from penaria.features.support.documents.domain.metadata import (
    DamagedImageError,
    UnknownVariantError,
    strip,
)
from tests import images

pytestmark = pytest.mark.unit

ORIENTATION = images.ORIENTATION_TAG


def frames(data: bytes) -> list[bytes]:
    """The pixels of every frame, as stored: no orientation applied."""
    with Image.open(io.BytesIO(data)) as image:
        found = []
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            found.append(image.convert("RGBA").tobytes())
        return found


def facts(data: bytes) -> tuple[dict[int, object], object, bytes | None]:
    """The EXIF tags, the XMP and the colour profile a reader finds."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        exif = Image.Exif()
        exif.load(image.info.get("exif", b""))
        return dict(exif), image.info.get("xmp"), image.info.get("icc_profile")


@pytest.mark.parametrize(
    ("original", "media_type"),
    [
        (images.jpeg(), JPEG),
        (images.progressive_jpeg(), JPEG),
        (images.png(), PNG),
        (images.webp(), WEBP),
        (images.webp(frames=3), WEBP),
    ],
    ids=["jpeg", "progressive-jpeg", "png", "webp", "animated-webp"],
)
def test_nothing_but_the_picture_and_its_colours_survives(original: bytes, media_type: str) -> None:
    assert images.SECRET in original

    clean = strip(original, media_type, 1)

    assert images.SECRET not in clean
    assert b"Exif" not in clean
    assert b"EXIF" not in clean
    assert b"xmpmeta" not in clean
    tags, xmp, _ = facts(clean)
    assert (tags, xmp) == ({}, None)
    # Without recompression: the pixels are the very same.
    assert frames(clean) == frames(original)


@pytest.mark.parametrize(
    ("original", "media_type"),
    [(images.jpeg(6), JPEG), (images.png(6), PNG), (images.webp(6), WEBP)],
    ids=["jpeg", "png", "webp"],
)
def test_the_orientation_is_all_of_exif_that_stays(original: bytes, media_type: str) -> None:
    clean = strip(original, media_type, 6)

    tags, _, profile = facts(clean)
    assert tags == {ORIENTATION: 6}
    assert images.SECRET not in clean
    assert profile == images.ICC


@pytest.mark.parametrize(
    ("original", "media_type"),
    [(images.jpeg(), JPEG), (images.png(), PNG), (images.webp(), WEBP)],
    ids=["jpeg", "png", "webp"],
)
def test_the_colour_profile_stays(original: bytes, media_type: str) -> None:
    assert facts(strip(original, media_type, 1))[2] == images.ICC


def test_a_jpeg_ends_where_its_picture_ends() -> None:
    clean = strip(images.jpeg(), JPEG, 1)

    assert clean.endswith(b"\xff\xd9")
    # Neither the further picture nor the trailer after it.
    assert clean.count(b"\xff\xd8\xff") == 1


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (images.jpeg()[:200], JPEG),
        (b"\xff\xd8\xff\xe0\x00\x01", JPEG),
        (images.png()[:100], PNG),
        (images.webp()[:40], WEBP),
        (b"not an image", WEBP),
    ],
    ids=["cut-jpeg", "short-segment", "cut-png", "cut-webp", "text"],
)
def test_a_damaged_image_is_refused(data: bytes, media_type: str) -> None:
    with pytest.raises(DamagedImageError):
        strip(data, media_type, 1)


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b"\xff\xd8\xff\xf7\x00\x02\xff\xd9", JPEG),
        (images.png()[:33] + b"\x00\x00\x00\x00CgBI\x00\x00\x00\x00" + images.png()[33:], PNG),
    ],
    ids=["jpeg-ls", "unknown-critical-chunk"],
)
def test_an_unknown_variant_is_refused_rather_than_guessed(data: bytes, media_type: str) -> None:
    with pytest.raises(UnknownVariantError):
        strip(data, media_type, 1)
