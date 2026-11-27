"""How a stored file is answered (docs/design/documents.md, 7): checked on every request, shown in the
browser only when it is an image or a PDF, and never as something that can run script."""

from typing import Literal
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from penaria.features.support.documents.domain.content import UNKNOWN
from penaria.features.support.documents.domain.files import PDF, STORED_IMAGES
from penaria.features.support.documents.domain.storage import ByteRange
from penaria.features.support.documents.use_cases.queries import Content

# Nothing runs and nothing is loaded; a download or an image is also sandboxed.
CSP = "default-src 'none'; frame-ancestors 'self'; sandbox"
IMAGE_CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox"
# The viewer's own embed and styles, and no `sandbox`: some Chromium versions refuse to open their PDF
# viewer in a sandboxed document, and `default-src 'none'` forbids script already.
PDF_CSP = "default-src 'none'; object-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"
# What is answered as these is never compressed: it would break ranges and ETags, and mostly is already.
UNCOMPRESSED_TYPES = (PDF, UNKNOWN)


async def serve(request: Request, content: Content, filename: str) -> Response:
    """The content, a part of it, or "not modified"; ``filename`` is what a download is saved as."""
    headers = _headers(content, filename)
    if _matches(request.headers.get("if-none-match"), content.etag):
        return Response(status_code=304, headers=headers)
    byte_range = None
    # Previews are small: only the original is served in parts.
    if content.preview is None:
        headers["Accept-Ranges"] = "bytes"
        if request.headers.get("if-range") in (None, content.etag):
            wanted = parse_range(request.headers.get("range"), content.file.size)
            if wanted == "unsatisfiable":
                return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{content.file.size}"})
            byte_range = wanted
    stored = await content.open(byte_range)
    headers["Content-Length"] = str(stored.length)
    if byte_range is not None:
        headers["Content-Range"] = f"bytes {byte_range.first}-{byte_range.last}/{content.file.size}"
    return StreamingResponse(
        stored.chunks(),
        status_code=200 if byte_range is None else 206,
        media_type=_served_type(content.media_type),
        headers=headers,
    )


def parse_range(header: str | None, size: int) -> ByteRange | Literal["unsatisfiable"] | None:
    """The one range asked for; None to answer the whole file (no header, or one that is not a single
    range of bytes, which a server may ignore), "unsatisfiable" for one that lies past the end."""
    if header is None:
        return None
    unit, _, spec = header.partition("=")
    first, dash, last = spec.strip().partition("-")
    if unit.strip() != "bytes" or not dash or "," in spec:
        return None
    if not first:
        # The last `last` bytes.
        if not _is_number(last):
            return None
        length = int(last)
        return "unsatisfiable" if length == 0 or size == 0 else ByteRange(max(size - length, 0), size - 1)
    if not _is_number(first) or (last and not _is_number(last)):
        return None
    start = int(first)
    end = int(last) if last else size - 1
    if last and end < start:
        return None
    return "unsatisfiable" if start >= size else ByteRange(start, min(end, size - 1))


def _is_number(text: str) -> bool:
    return text.isascii() and text.isdigit()


def _shown(media_type: str) -> bool:
    """Whether the browser shows it; everything else it only downloads."""
    return media_type in STORED_IMAGES or media_type == PDF


def _headers(content: Content, filename: str) -> dict[str, str]:
    shown = _shown(content.media_type)
    if content.media_type == PDF:
        policy = PDF_CSP
    elif shown:
        policy = IMAGE_CSP
    else:
        policy = CSP
    return {
        "Content-Disposition": disposition("inline" if shown else "attachment", filename),
        "Content-Security-Policy": policy,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Resource-Policy": "same-origin",
        # Kept by the browser only, and asked about again each time: access is checked on every request.
        "Cache-Control": "private, no-cache",
        "ETag": content.etag,
        "Vary": "Cookie, Authorization",
    }


def _served_type(media_type: str) -> str:
    # What is not shown is only ever downloaded, whatever it is.
    return media_type if _shown(media_type) else UNKNOWN


def disposition(kind: str, filename: str) -> str:
    """``Content-Disposition`` with the name in ASCII for old clients and in full as RFC 6266 writes it."""
    fallback = "".join(char if 32 <= ord(char) < 127 and char not in '"\\' else "_" for char in filename)
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _matches(if_none_match: str | None, etag: str) -> bool:
    if if_none_match is None:
        return False
    known = {value.strip().removeprefix("W/") for value in if_none_match.split(",")}
    return "*" in known or etag in known
