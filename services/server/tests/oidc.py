"""An OpenID Connect provider in the test's event loop: discovery, keys and a token endpoint (FastAPI on uvicorn).

``authorize`` plays the person signing in at the provider: it reads the authorization request Penaria made
and returns what the provider sends the browser back with. The token endpoint checks the client, the code
and its PKCE verifier, and issues an ID token signed with the provider's current key.
"""

import asyncio
import base64
import hashlib
import secrets
import socket
import time
from dataclasses import dataclass, field
from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from joserfc import jwt
from joserfc.jwk import RSAKey

CLIENT_ID = "penaria"
CLIENT_SECRET = "provider-secret-for-tests"  # noqa: S105 - the fake provider's, used only by the tests
LIFETIME_SECONDS = 300


@dataclass
class _Grant:
    claims: dict[str, Any]
    challenge: str
    redirect_uri: str
    key: RSAKey | None


@dataclass
class FakeOidc:
    """``keys`` are what it publishes; the first one signs. ``up`` False answers every request with 503."""

    keys: list[RSAKey] = field(default_factory=lambda: [_new_key("first")])
    up: bool = True
    port: int = 0
    _grants: dict[str, _Grant] = field(default_factory=dict)
    _server: uvicorn.Server | None = None
    _task: asyncio.Task[None] | None = None

    @property
    def issuer(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        self._server = uvicorn.Server(uvicorn.Config(self._app(), log_level="warning", lifespan="off"))
        self._task = asyncio.create_task(self._server.serve(sockets=[sock]))
        while not self._server.started:
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        if self._server is not None and self._task is not None:
            self._server.should_exit = True
            await self._task

    def rotate(self) -> None:
        """A new signing key, published alone: tokens signed with the old one no longer check out."""
        self.keys = [_new_key(f"key-{secrets.token_hex(4)}")]

    def authorize(self, url: str, *, subject: str, sign_with: RSAKey | None = None, **claims: Any) -> dict[str, str]:
        """The person signs in at the provider as ``subject``: the query the provider sends the browser back with.

        ``claims`` go into the ID token, over the ones it would have (``aud``, ``exp``, ``nonce`` and the like).
        """
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        assert query["response_type"] == "code"
        assert query["client_id"] == CLIENT_ID
        assert query["code_challenge_method"] == "S256"
        assert "openid" in query["scope"].split()
        code = secrets.token_urlsafe(16)
        now = int(time.time())
        self._grants[code] = _Grant(
            claims={
                "iss": self.issuer,
                "aud": CLIENT_ID,
                "sub": subject,
                "iat": now,
                "exp": now + LIFETIME_SECONDS,
                "nonce": query["nonce"],
                **claims,
            },
            challenge=query["code_challenge"],
            redirect_uri=query["redirect_uri"],
            key=sign_with,
        )
        return {"state": query["state"], "code": code}

    def _app(self) -> FastAPI:
        app = FastAPI()

        def check_up() -> None:
            if not self.up:
                raise HTTPException(status_code=503)

        @app.get("/.well-known/openid-configuration")
        async def discovery() -> dict[str, Any]:
            check_up()
            return {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/keys",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
            }

        @app.get("/keys")
        async def keys() -> dict[str, Any]:
            check_up()
            return {"keys": [key.as_dict(private=False) for key in self.keys]}

        @app.post("/token")
        async def token(request: Request, authorization: Annotated[str, Header()]) -> dict[str, Any]:
            form = {key: values[0] for key, values in parse_qs((await request.body()).decode()).items()}
            grant_type, code = form.get("grant_type"), form.get("code", "")
            redirect_uri, code_verifier = form.get("redirect_uri"), form.get("code_verifier", "")
            check_up()
            expected = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            grant = self._grants.pop(code, None)
            if authorization != expected or grant_type != "authorization_code" or grant is None:
                raise HTTPException(status_code=400, detail="invalid_grant")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
            if challenge != grant.challenge or redirect_uri != grant.redirect_uri:
                raise HTTPException(status_code=400, detail="invalid_grant")
            key = grant.key or self.keys[0]
            id_token = jwt.encode({"alg": "RS256", "kid": key.kid}, grant.claims, key)
            return {"access_token": secrets.token_urlsafe(16), "token_type": "Bearer", "id_token": id_token}

        return app


def _new_key(kid: str) -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": kid})
