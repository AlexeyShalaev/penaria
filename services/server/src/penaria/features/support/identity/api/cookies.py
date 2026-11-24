"""The session cookie (sign-in.md, 5)."""

from dataclasses import dataclass

from fastapi import Response

from penaria.features.support.identity.domain.sessions import ABSOLUTE_LIFETIME

SESSION_COOKIE = "penaria_session"


@dataclass(frozen=True, slots=True)
class SessionCookie:
    # Browsers drop a Secure cookie set over plain HTTP, so it follows the scheme people open.
    secure: bool

    def set(self, response: Response, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=int(ABSOLUTE_LIFETIME.total_seconds()),
            path="/",
            secure=self.secure,
            httponly=True,
            samesite="lax",
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=self.secure, httponly=True, samesite="lax")
