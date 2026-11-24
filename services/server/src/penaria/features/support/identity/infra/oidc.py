"""The operator's OpenID Connect provider, through authlib's OAuth 2 client and joserfc's JWT checks.

authlib builds the authorization request with PKCE, exchanges the code with the client's credentials,
reads the provider's errors and checks the discovery document; joserfc, authlib's JOSE library, checks the
ID token's signature against the provider's keys and its claims.
"""

import time
from typing import Any

import httpx2
from authlib.integrations.base_client import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.discovery import OpenIDProviderMetadata
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from penaria.features.support.identity.domain.oidc import Claims, ProviderError

# Every call to the provider has a deadline: the person waits on the callback page.
TIMEOUT_SECONDS = 10
# The discovery document changes rarely; read it again after this long.
DISCOVERY_TTL_SECONDS = 3600
# Clocks of the provider and the install may differ a little.
LEEWAY_SECONDS = 60
# Asymmetric signatures only: the client secret never signs a token Penaria accepts.
ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"})
DEFAULT_ALGORITHM = "RS256"


class AuthlibOidcProvider:
    def __init__(self, *, issuer: str, client_id: str, client_secret: str, scopes: str, redirect_uri: str) -> None:
        self._issuer = issuer
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes
        self._redirect_uri = redirect_uri
        self._metadata: dict[str, Any] | None = None
        self._metadata_read_at = 0.0
        self._keys: KeySet | None = None

    @property
    def issuer(self) -> str:
        return self._issuer

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str, reauthenticate: bool) -> str:
        metadata = await self._discover()
        extra = {"prompt": "login", "max_age": "0"} if reauthenticate else {}
        async with self._client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"], state=state, code_verifier=code_verifier, nonce=nonce, **extra
            )
        return str(url)

    async def claims(self, *, code: str, code_verifier: str, nonce: str) -> Claims:
        metadata = await self._discover()
        try:
            async with self._client() as client:
                token = await client.fetch_token(
                    metadata["token_endpoint"], code=code, code_verifier=code_verifier, redirect_uri=self._redirect_uri
                )
        except (OAuthError, httpx2.HTTPError, ValueError) as exc:
            raise ProviderError(f"the provider did not exchange the code: {exc}") from exc
        id_token = token.get("id_token")
        if not isinstance(id_token, str):
            raise ProviderError("the provider answered without an ID token: is the openid scope asked for?")
        return self._checked(await self._decoded(id_token, metadata), nonce)

    async def _decoded(self, id_token: str, metadata: dict[str, Any]) -> dict[str, Any]:
        algorithms = sorted(
            ALGORITHMS.intersection(metadata.get("id_token_signing_alg_values_supported", [DEFAULT_ALGORITHM]))
        )
        # joserfc reads an empty list as "any algorithm", the client secret's HS256 among them.
        if not algorithms:
            raise ProviderError(
                "the provider signs ID tokens with no algorithm Penaria accepts (RS256, ES256 and the like)"
            )
        try:
            return jwt.decode(id_token, await self._signing_keys(metadata, refresh=False), algorithms=algorithms).claims
        except JoseError:
            # The provider may have rotated its keys since they were read. Only the provider's token endpoint,
            # which Penaria calls with its secret, hands out ID tokens, so nobody else can make it read them again.
            pass
        try:
            return jwt.decode(id_token, await self._signing_keys(metadata, refresh=True), algorithms=algorithms).claims
        except JoseError as exc:
            raise ProviderError(f"the ID token does not check out: {exc}") from exc

    def _checked(self, claims: dict[str, Any], nonce: str) -> Claims:
        registry = jwt.JWTClaimsRegistry(
            leeway=LEEWAY_SECONDS,
            iss={"essential": True, "value": self._issuer},
            aud={"essential": True, "value": self._client_id},
            exp={"essential": True},
            sub={"essential": True},
            nonce={"essential": True, "value": nonce},
        )
        try:
            registry.validate(claims)
        except JoseError as exc:
            raise ProviderError(f"the ID token's claims do not check out: {exc}") from exc
        audience = claims["aud"]
        # A token meant for several clients names the one it was issued to.
        if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != self._client_id:
            raise ProviderError("the ID token was issued to another client")
        return Claims(
            subject=str(claims["sub"]),
            email=_text(claims.get("email")),
            email_verified=claims.get("email_verified") is True,
            name=_text(claims.get("name")),
            preferred_username=_text(claims.get("preferred_username")),
            auth_time=claims["auth_time"] if isinstance(claims.get("auth_time"), int) else None,
        )

    # Requests that find the cache empty or stale each read the document, rather than waiting in turn behind
    # one that may hang on an unreachable provider until its deadline; the copies they keep are the same.
    async def _discover(self) -> dict[str, Any]:
        if self._metadata is not None and time.monotonic() - self._metadata_read_at < DISCOVERY_TTL_SECONDS:
            return self._metadata
        url = self._issuer.rstrip("/") + "/.well-known/openid-configuration"
        document = await self._get_json(url)
        metadata = OpenIDProviderMetadata(document)
        try:
            metadata.validate_issuer()
            metadata.validate_authorization_endpoint()
            metadata.validate_token_endpoint()
            metadata.validate_jwks_uri()
        except ValueError as exc:
            raise ProviderError(f"the provider's discovery document is not usable: {exc}") from exc
        # The issuer it names must be the one configured, exactly (OpenID Connect Discovery, 4.3).
        if document["issuer"] != self._issuer:
            raise ProviderError(
                f"the provider names its issuer {document['issuer']!r}, not {self._issuer!r}: "
                "set PENARIA_AUTH__OIDC__ISSUER to exactly that"
            )
        self._metadata, self._metadata_read_at = document, time.monotonic()
        return document

    async def _signing_keys(self, metadata: dict[str, Any], *, refresh: bool) -> KeySet:
        if self._keys is not None and not refresh:
            return self._keys
        document = await self._get_json(metadata["jwks_uri"])
        try:
            # joserfc types the set as its own TypedDict; the provider's JSON is checked by the import itself.
            keys = KeySet.import_key_set(document)  # type: ignore[arg-type]
        except (JoseError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"the provider's keys cannot be read: {exc}") from exc
        self._keys = keys
        return keys

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.request("GET", url, withhold_token=True)
                response.raise_for_status()
                document = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise ProviderError(f"the provider's {url} cannot be read: {exc}") from exc
        if not isinstance(document, dict):
            raise ProviderError(f"the provider's {url} is not a JSON object")
        return document

    def _client(self) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            scope=self._scopes,
            redirect_uri=self._redirect_uri,
            code_challenge_method="S256",
            timeout=TIMEOUT_SECONDS,
        )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
