"""The addresses of invitation and guest links, under ``PENARIA_PUBLIC_URL``."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicLinks:
    # The origin people open, without a trailing slash.
    origin: str

    def invitation(self, token: str) -> str:
        return f"{self.origin}/invite/{token}"

    def guest(self, token: str) -> str:
        return f"{self.origin}/guest/{token}"
