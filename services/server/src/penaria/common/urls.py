"""URLs."""

from urllib.parse import urlsplit

DEFAULT_PORTS = {"http": 80, "https": 443}
# Names of the machine itself, where plain http stays on the machine.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def origin_of(url: str) -> str:
    """The origin of a URL as browsers write it in ``Origin``: lower case, without the default port."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    port = "" if parts.port in (None, DEFAULT_PORTS.get(scheme)) else f":{parts.port}"
    return f"{scheme}://{host}{port}"


def is_loopback(host: str | None) -> bool:
    """Whether the host name is the machine itself; an IPv6 address may come in brackets, as URLs write it."""
    return host is not None and host.strip("[]").lower() in LOOPBACK_HOSTS
