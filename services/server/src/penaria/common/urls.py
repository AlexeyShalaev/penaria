"""URLs."""

from urllib.parse import urlsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_of(url: str) -> str:
    """The origin of a URL as browsers write it in ``Origin``: lower case, without the default port."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    port = "" if parts.port in (None, DEFAULT_PORTS.get(scheme)) else f":{parts.port}"
    return f"{scheme}://{host}{port}"
