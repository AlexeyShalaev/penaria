"""Generated images that carry the metadata a phone or an editor writes, each piece marked with a word of
its own, so a test can tell whether any of it survives. Nothing here is a real photo."""

import io
import struct
import zlib

import pillow_heif
from PIL import Image, ImageCms, PngImagePlugin

# Every marker starts with it; none may be found in a cleaned file.
SECRET = b"SECRET"
# What the camera writes as the owner, the serial number and the place.
OWNER_TAG, SERIAL_TAG = 0x013B, 0xA431
MAKE_TAG, ORIENTATION_TAG, EXIF_IFD, GPS_IFD = 0x010F, 0x0112, 0x8769, 0x8825
LATITUDE = (55.0, 45.0, 7.0)

XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description rdf:about="" xmlns:exif="http://ns.adobe.com/exif/1.0/" exif:GPSLatitude="SECRET-XMP"/>'
    b"</rdf:RDF></x:xmpmeta>"
)
ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
# The width and the height of every generated picture.
SIZE = (48, 32)


def picture(mode: str = "RGB", size: tuple[int, int] = SIZE) -> Image.Image:
    """Two halves, red on the left, so a turn of the picture can be seen."""
    image = Image.new("RGB", size, (20, 40, 200))
    image.paste((220, 30, 20), (0, 0, size[0] // 2, size[1]))
    return image.convert(mode)


def exif(orientation: int | None = None, *, offset: str | None = "+03:00") -> bytes:
    """EXIF as a phone writes it: the place, the owner, the serial number and when the photo was taken."""
    data = Image.Exif()
    data[MAKE_TAG] = "SECRET-MAKE"
    data[OWNER_TAG] = "SECRET-OWNER"
    if orientation is not None:
        data[ORIENTATION_TAG] = orientation
    gps = data.get_ifd(GPS_IFD)
    gps[1] = "N"
    gps[2] = LATITUDE
    gps[27] = b"SECRET-GPS"
    details = data.get_ifd(EXIF_IFD)
    details[0x9003] = "2026:11:20 10:11:12"
    if offset is not None:
        details[0x9011] = offset
    details[SERIAL_TAG] = "SECRET-SERIAL"
    return data.tobytes()


def jpeg(orientation: int | None = None, *, offset: str | None = "+03:00") -> bytes:
    """A JPEG with everything a phone and an editor put in one, further pictures after its end included."""
    out = io.BytesIO()
    picture().save(
        out, "JPEG", quality=90, exif=exif(orientation, offset=offset), icc_profile=ICC, comment=b"SECRET-COMMENT"
    )
    data = out.getvalue()
    extra = b"".join(
        (
            _segment(0xE0, b"JFXX\0\x10SECRET-THUMBNAIL"),
            _segment(0xE1, b"http://ns.adobe.com/xap/1.0/\0" + XMP),
            _segment(0xE2, b"MPF\0SECRET-MPF"),
            _segment(0xED, b"Photoshop 3.0\x008BIM\x04\x04SECRET-IPTC"),
            _segment(0xEB, b"JUMBF SECRET-C2PA"),
            _segment(0xFE, b"SECRET-SECOND-COMMENT"),
        )
    )
    # After the first segment, which JFIF keeps for itself.
    first_end = 4 + int.from_bytes(data[4:6])
    second = io.BytesIO()
    picture().save(second, "JPEG", exif=exif())
    return data[:first_end] + extra + data[first_end:] + second.getvalue() + b"SECRET-VIDEO-TRAILER"


def progressive_jpeg() -> bytes:
    out = io.BytesIO()
    picture(size=(160, 120)).save(out, "JPEG", progressive=True, exif=exif(), comment=b"SECRET-COMMENT")
    return out.getvalue() + b"SECRET-TRAILER"


def restart_jpeg() -> bytes:
    """As cameras write them, with restart markers inside the compressed data."""
    out = io.BytesIO()
    picture(size=(160, 120)).save(out, "JPEG", restart_marker_blocks=1, exif=exif())
    return out.getvalue() + b"SECRET-TRAILER"


def cmyk_jpeg() -> bytes:
    """With Adobe's marker, which says how its four colours are coded."""
    out = io.BytesIO()
    picture("CMYK").save(out, "JPEG", exif=exif())
    return out.getvalue() + b"SECRET-TRAILER"


def png(orientation: int | None = None) -> bytes:
    text = PngImagePlugin.PngInfo()
    text.add_text("Comment", "SECRET-TEXT")
    text.add_text("Author", "SECRET-ZTXT", zip=True)
    text.add_itxt("XML:com.adobe.xmp", XMP.decode())
    see_through = picture("RGBA")
    see_through.putpixel((0, 0), (0, 0, 0, 0))
    out = io.BytesIO()
    see_through.save(out, "PNG", pnginfo=text, exif=exif(orientation), icc_profile=ICC)
    data = out.getvalue()
    # A time, a private chunk and one after the header that a camera app may add.
    added = _chunk(b"tIME", struct.pack(">HBBBBB", 2026, 11, 20, 10, 11, 12)) + _chunk(b"prVt", b"SECRET-PRIVATE")
    header_end = 8 + 12 + 13
    return data[:header_end] + added + data[header_end:] + b"SECRET-TRAILER"


def webp(orientation: int | None = None, *, frames: int = 1) -> bytes:
    out = io.BytesIO()
    others = [picture().transpose(Image.Transpose.FLIP_LEFT_RIGHT) for _ in range(frames - 1)]
    picture().save(
        out,
        "WEBP",
        lossless=True,
        exif=exif(orientation),
        xmp=XMP,
        icc_profile=ICC,
        save_all=frames > 1,
        append_images=others,
    )
    data = bytearray(out.getvalue())
    data += b"JUNK" + (14).to_bytes(4, "little") + b"SECRET-UNKNOWN"
    data[4:8] = (len(data) - 8).to_bytes(4, "little")
    return bytes(data) + b"SECRET-TRAILER"


def heic(orientation: int | None = None) -> bytes:
    pillow_heif.register_heif_opener()
    out = io.BytesIO()
    picture(size=(64, 48)).save(out, "HEIF", quality=90, exif=exif(orientation), xmp=XMP, icc_profile=ICC)
    return out.getvalue()


def pdf() -> bytes:
    out = io.BytesIO()
    picture(size=(300, 420)).save(out, "PDF")
    return out.getvalue()


def _segment(marker: int, payload: bytes) -> bytes:
    return struct.pack(">BBH", 0xFF, marker, len(payload) + 2) + payload


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
