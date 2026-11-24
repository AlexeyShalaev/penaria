"""The session cookie (sign-in.md, 5), and the one that binds a sign-in with the provider to its browser (18)."""

from dataclasses import dataclass

from fastapi import Response

from penaria.features.support.identity.domain.oidc import FLOW_LIFETIME
from penaria.features.support.identity.domain.sessions import ABSOLUTE_LIFETIME

SESSION_COOKIE = "penaria_session"
# Binds a sign-in with the provider to the browser that started it; sent only to the callback.
OIDC_COOKIE = "penaria_oidc"
OIDC_COOKIE_PATH = "/api/v1/auth/oidc"


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

    def bind_oidc(self, response: Response, binding: str) -> None:
        # Lax: the provider sends the browser back with a top-level GET, which carries it.
        response.set_cookie(
            OIDC_COOKIE,
            binding,
            max_age=int(FLOW_LIFETIME.total_seconds()),
            path=OIDC_COOKIE_PATH,
            secure=self.secure,
            httponly=True,
            samesite="lax",
        )

    def unbind_oidc(self, response: Response) -> None:
        response.delete_cookie(OIDC_COOKIE, path=OIDC_COOKIE_PATH, secure=self.secure, httponly=True, samesite="lax")
