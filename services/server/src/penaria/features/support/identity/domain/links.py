"""The addresses of the links Penaria hands out, under ``PENARIA_PUBLIC_URL``: the web app's pages that open them."""

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class PublicLinks:
    # The origin people open, without a trailing slash.
    origin: str

    @property
    def host(self) -> str:
        """The host name people open, as passkeys and authenticator apps name the install."""
        host = urlsplit(self.origin).hostname
        if host is None:
            raise RuntimeError(f"the public origin ({self.origin}) names no host")
        return host

    def invitation(self, token: str) -> str:
        return f"{self.origin}/invite/{token}"

    def guest(self, token: str) -> str:
        return f"{self.origin}/guest/{token}"

    def password_reset(self, token: str) -> str:
        return f"{self.origin}/reset-password/{token}"

    def email_verification(self, token: str) -> str:
        return f"{self.origin}/verify-email/{token}"
