"""What a file is, told from its first bytes: never from its name or what the browser claims."""

from penaria.features.support.documents.domain.files import HEIC, JPEG, PDF, PNG, WEBP

# Enough for every signature, a HEIF's list of brands included.
SNIFF_BYTES = 256
UNKNOWN = "application/octet-stream"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
HEIC_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"})
AVIF_BRANDS = frozenset({b"avif", b"avis"})


def sniff(head: bytes) -> str:
    """The media type of a file that starts with ``head``: one that Penaria previews, or ``UNKNOWN``."""
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(PNG_SIGNATURE):
        return PNG
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return WEBP
    if head.startswith(b"%PDF-"):
        return PDF
    if head[4:8] == b"ftyp":
        return _heif(head)
    return UNKNOWN


def _heif(head: bytes) -> str:
    """A HEIF file lists its brands: the major one, a version, then the compatible ones."""
    box = head[: int.from_bytes(head[:4])]
    brands = {box[8:12], *(box[start : start + 4] for start in range(16, len(box), 4))}
    if brands & AVIF_BRANDS:
        # Browsers show it, but its metadata is not removed here, so it is a file like any other.
        return UNKNOWN
    return HEIC if brands & HEIC_BRANDS else UNKNOWN
