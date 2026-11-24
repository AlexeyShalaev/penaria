"""The addresses of the links Penaria hands out, under ``PENARIA_PUBLIC_URL``: the web app's pages that open them."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicLinks:
    # The origin people open, without a trailing slash.
    origin: str

    def invitation(self, token: str) -> str:
        return f"{self.origin}/invite/{token}"

    def guest(self, token: str) -> str:
        return f"{self.origin}/guest/{token}"

    def password_reset(self, token: str) -> str:
        return f"{self.origin}/reset-password/{token}"

    def email_verification(self, token: str) -> str:
        return f"{self.origin}/verify-email/{token}"
