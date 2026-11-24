"""Refusing cross-site requests that change something (sign-in.md, 5: CSRF).

Browsers send ``Origin`` with every cross-site ``POST``, ``PUT``, ``PATCH`` and ``DELETE``, and the
session cookie is ``SameSite=Lax``. So a request that changes something is refused when its
``Origin`` (or, without one, its ``Referer``) names another site than ``PENARIA_PUBLIC_URL``. A
request with neither header comes from a client that is not a browser, such as a script, which a
forged page cannot make carry the cookie; it passes. So does a request with a device's bearer token
(sign-in.md, 6.3): it is judged by the token, never by a cookie, and browsers never add the header by
themselves, so a page of another site can send it only with a token it already holds.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request
from servicewright import ErrorKind, ServiceError

from penaria.common.urls import origin_of
from penaria.features.support.identity.api.devices import device_token_of

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CrossOriginRequestError(ServiceError):
    kind = ErrorKind.FORBIDDEN
    code = "cross_origin_request"


def origin_check(public_origin: str) -> Callable[[Request], Awaitable[None]]:
    """A dependency for every route: refuse a change that a page of another site asks for."""

    async def check_origin(request: Request) -> None:
        if request.method in SAFE_METHODS or device_token_of(request) is not None:
            return
        origin = request.headers.get("origin")
        if origin is None and (referer := request.headers.get("referer")) is not None:
            try:
                origin = origin_of(referer)
            except ValueError:
                # A malformed Referer, such as one with a port out of range, names no site we know.
                origin = "null"
        if origin is not None and origin != public_origin:
            raise CrossOriginRequestError("the request comes from another site than PENARIA_PUBLIC_URL")

    return check_origin
