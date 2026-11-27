"""Removing the metadata of JPEG, PNG and WebP images without recompressing them.

Each format is rewritten part by part from a list of what is kept: the parts that make the picture,
its colours (the ICC profile among them) and its animation. Everything else goes, whatever it is:
EXIF with the location and the thumbnail, XMP, IPTC, comments, text, further images and anything
after the end of the picture. The orientation is the one fact of EXIF that changes how the picture
is shown, so it is written back alone. A file that does not read as its format is refused: nothing
is guessed.
"""

import struct
import zlib

from penaria.features.support.documents.domain.content import PNG_SIGNATURE
from penaria.features.support.documents.domain.files import JPEG, PNG, WEBP

# EXIF's orientations: 1 is upright and says nothing.
UPRIGHT = 1
ORIENTATIONS = range(1, 9)


class NotCleanableError(Exception):
    """The file cannot be rewritten without what it carries: it is damaged or an unknown variant."""


class DamagedImageError(NotCleanableError):
    pass


class UnknownVariantError(NotCleanableError):
    pass


def strip(data: bytes, media_type: str, orientation: int) -> bytes:
    """``data`` without metadata; ``orientation`` is its EXIF orientation, kept."""
    if orientation not in ORIENTATIONS:
        raise ValueError(f"An EXIF orientation is 1 to 8, not {orientation}.")
    if media_type == JPEG:
        return _strip_jpeg(data, orientation)
    if media_type == PNG:
        return _strip_png(data, orientation)
    if media_type == WEBP:
        return _strip_webp(data, orientation)
    raise ValueError(f"Cannot strip metadata from {media_type}.")


def orientation_tiff(orientation: int) -> bytes:
    """A TIFF structure, as EXIF is, that holds the orientation and nothing else."""
    # Big endian; the first IFD at offset 8 with one entry: Orientation, SHORT, one value.
    return struct.pack(">2sHIHHHIH2xI", b"MM", 42, 8, 1, 0x0112, 3, 1, orientation, 0)


# JPEG: markers (ITU T.81), each but a few followed by a length that counts itself.

SOI, EOI, SOS = 0xD8, 0xD9, 0xDA
APP0, APP1, APP2, APP14 = 0xE0, 0xE1, 0xE2, 0xEE
COMMENT = 0xFE
# Without a length: the restart markers and TEM.
STANDALONE = frozenset({0x01, *range(0xD0, 0xD8)})
# Frames, tables and the scan: SOF0-15, DHT, DAC (0xC0-0xCF but the reserved 0xC8), SOS, DQT, DNL, DRI, DHP, EXP.
STRUCTURAL = frozenset({*range(0xC0, 0xD0), SOS, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF}) - {0xC8}
APPLICATION = frozenset(range(0xE0, 0xF0))


def _strip_jpeg(data: bytes, orientation: int) -> bytes:
    if data[:2] != b"\xff\xd8":
        raise DamagedImageError("not a JPEG")
    out = bytearray(b"\xff\xd8")
    # Written back right after the start, or after JFIF's header, which must be first.
    exif = b"" if orientation == UPRIGHT else _jpeg_segment(APP1, b"Exif\0\0" + orientation_tiff(orientation))
    position = 2
    while True:
        marker, position = _jpeg_marker(data, position)
        if exif and marker != APP0:
            out += exif
            exif = b""
        if marker == EOI:
            # Whatever follows the picture, such as the further images and videos of phones, is left behind.
            out += b"\xff\xd9"
            return bytes(out)
        if marker in STANDALONE:
            out += bytes((0xFF, marker))
            continue
        payload, position = _jpeg_payload(data, position)
        out += _kept_jpeg_segment(marker, payload)
        if marker == SOS:
            end = _end_of_scan(data, position)
            out += data[position:end]
            position = end


def _jpeg_marker(data: bytes, position: int) -> tuple[int, int]:
    if data[position : position + 1] != b"\xff":
        raise DamagedImageError("no marker where one is expected")
    # Any number of 0xFF may fill the space before a marker.
    while data[position : position + 1] == b"\xff":
        position += 1
    if position >= len(data):
        raise DamagedImageError("the picture has no end")
    marker = data[position]
    if marker in (0x00, SOI):
        raise DamagedImageError("a marker out of place")
    return marker, position + 1


def _jpeg_payload(data: bytes, position: int) -> tuple[bytes, int]:
    length = int.from_bytes(data[position : position + 2])
    end = position + length
    if length < 2 or end > len(data):
        raise DamagedImageError("a segment longer than the file")
    return data[position + 2 : end], end


def _jpeg_segment(marker: int, payload: bytes) -> bytes:
    return struct.pack(">BBH", 0xFF, marker, len(payload) + 2) + payload


def _kept_jpeg_segment(marker: int, payload: bytes) -> bytes:
    if marker in STRUCTURAL:
        return _jpeg_segment(marker, payload)
    if marker == APP0 and payload.startswith(b"JFIF\0") and len(payload) >= 14:
        # Without the thumbnail that may follow the densities.
        return _jpeg_segment(marker, payload[:12] + b"\0\0")
    if marker == APP2 and payload.startswith(b"ICC_PROFILE\0"):
        return _jpeg_segment(marker, payload)
    if marker == APP14 and payload.startswith(b"Adobe") and len(payload) >= 12:
        # Says how the colours are coded: without it the picture would look different.
        return _jpeg_segment(marker, payload[:12])
    if marker in APPLICATION or marker == COMMENT:
        return b""
    raise UnknownVariantError(f"unknown JPEG marker 0x{marker:02X}")


def _end_of_scan(data: bytes, position: int) -> int:
    """Where the compressed data of a scan ends: at the next marker that is not part of it."""
    while True:
        found = data.find(b"\xff", position)
        if found < 0 or found + 1 >= len(data):
            raise DamagedImageError("the picture has no end")
        following = data[found + 1]
        if following == 0x00 or 0xD0 <= following <= 0xD7:
            position = found + 2
        elif following == 0xFF:
            position = found + 1
        else:
            return found


# PNG: chunks of length, type, data and a checksum.

PNG_KEPT = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        # Transparency, colour and size of a pixel.
        b"tRNS",
        b"cHRM",
        b"gAMA",
        b"iCCP",
        b"sBIT",
        b"sRGB",
        b"cICP",
        b"mDCV",
        b"cLLI",
        b"bKGD",
        b"pHYs",
        # Animation.
        b"acTL",
        b"fcTL",
        b"fdAT",
    }
)


def _strip_png(data: bytes, orientation: int) -> bytes:
    if not data.startswith(PNG_SIGNATURE):
        raise DamagedImageError("not a PNG")
    out = bytearray(PNG_SIGNATURE)
    position = len(PNG_SIGNATURE)
    while True:
        header = data[position : position + 8]
        if len(header) < 8:
            raise DamagedImageError("the picture has no end")
        length, kind = struct.unpack(">I4s", header)
        end = position + 12 + length
        if end > len(data):
            raise DamagedImageError("a chunk longer than the file")
        if kind in PNG_KEPT:
            out += data[position:end]
        elif not kind[0] & 0x20:
            # A chunk whose type starts with a capital is needed to show the picture.
            raise UnknownVariantError("unknown critical PNG chunk")
        if kind == b"IHDR" and orientation != UPRIGHT:
            out += _png_chunk(b"eXIf", orientation_tiff(orientation))
        if kind == b"IEND":
            return bytes(out)
        position = end


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


# WebP: a RIFF container of chunks, each padded to an even length.

WEBP_KEPT = frozenset({b"VP8X", b"ICCP", b"ANIM", b"ANMF", b"ALPH", b"VP8 ", b"VP8L"})
FRAME_KEPT = frozenset({b"ALPH", b"VP8 ", b"VP8L"})
FRAME_HEADER = 16
# The flags of VP8X that say which chunks follow.
EXIF_FLAG, XMP_FLAG = 0x08, 0x04


def _strip_webp(data: bytes, orientation: int) -> bytes:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise DamagedImageError("not a WebP")
    end = 8 + int.from_bytes(data[4:8], "little")
    if end > len(data):
        raise DamagedImageError("the file is shorter than it says")
    chunks = [(kind, payload) for kind, payload in _riff_chunks(data[12:end]) if kind in WEBP_KEPT]
    # Only the extended format, with VP8X first, has EXIF at all.
    extended = bool(chunks) and chunks[0][0] == b"VP8X"
    turned = extended and orientation != UPRIGHT
    body = bytearray()
    for kind, payload in chunks:
        body += _riff_chunk(kind, _webp_payload(kind, payload, turned))
    if turned:
        body += _riff_chunk(b"EXIF", orientation_tiff(orientation))
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + bytes(body)


def _webp_payload(kind: bytes, payload: bytes, turned: bool) -> bytes:
    """A kept chunk's content: VP8X says only what is still there, and a frame holds only its picture."""
    if kind == b"VP8X":
        if len(payload) != 10:
            raise DamagedImageError("a VP8X chunk of a wrong length")
        flags = (payload[0] & ~(EXIF_FLAG | XMP_FLAG)) | (EXIF_FLAG if turned else 0)
        return bytes((flags,)) + payload[1:]
    if kind == b"ANMF":
        frame = _riff_chunks(payload[FRAME_HEADER:])
        return payload[:FRAME_HEADER] + b"".join(
            _riff_chunk(inner, content) for inner, content in frame if inner in FRAME_KEPT
        )
    return payload


def _riff_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    chunks = []
    position = 0
    while position < len(data):
        if position + 8 > len(data):
            raise DamagedImageError("a chunk without its header")
        kind = data[position : position + 4]
        length = int.from_bytes(data[position + 4 : position + 8], "little")
        end = position + 8 + length
        if end > len(data):
            raise DamagedImageError("a chunk longer than the file")
        chunks.append((kind, data[position + 8 : end]))
        position = end + (length & 1)
    return chunks


def _riff_chunk(kind: bytes, payload: bytes) -> bytes:
    return kind + len(payload).to_bytes(4, "little") + payload + b"\0" * (len(payload) & 1)
