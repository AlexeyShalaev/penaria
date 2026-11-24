"""Signing in with the operator's OpenID Connect provider (sign-in.md, 4.4 and 18).

A flow starts in Penaria, which keeps its state, nonce and PKCE verifier, and ends at the callback the
provider redirects the browser to. An identity is the provider's issuer and its ``sub``; it is linked to an
account, never matched to one by email.
"""

import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from servicewright import ErrorKind, ServiceError

from penaria.features.shared.errors import ConflictError, NotFoundError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.accounts import USERNAME_PATTERN, normalize_username
from penaria.features.support.identity.domain.models import NAME_MAX_LENGTH
from penaria.features.support.identity.domain.sessions import hash_token, new_secret
from penaria.features.support.identity.domain.throttle import TooManyAttemptsError

# Long enough to pick an account at the provider and pass its own second factor; used once.
FLOW_LIFETIME = timedelta(minutes=10)
# Starting needs no account, so an address may hold only this many flows that are neither used nor expired.
OPEN_FLOWS_PER_ADDRESS = 10
USERNAME_MAX_LENGTH = 32
USERNAME_MIN_LENGTH = 3
# Tried after the username the claims suggest is taken: "anna", "anna-2", ... "anna-99".
USERNAME_SUFFIXES = 99
FALLBACK_USERNAME = "user"


class OidcOffError(NotFoundError):
    """The operator configured no OpenID Connect provider."""

    code = "oidc_off"


class IdentityLinkedError(ConflictError):
    """The account already has an identity at the provider."""

    code = "identity_already_linked"


class ExternalIdentityNotFoundError(NotFoundError):
    code = "external_identity_not_found"


class ProviderUnavailableError(ServiceError):
    """The provider cannot be reached or set up the sign-in; the details are in the server's log."""

    kind = ErrorKind.UNAVAILABLE
    code = "oidc_unavailable"


class ProviderError(Exception):
    """The provider could not be reached, refused, or answered with something that does not check out."""


class FlowPurpose(StrEnum):
    SIGN_IN = "sign_in"
    LINK = "link"
    REAUTHENTICATE = "reauthenticate"
    INVITATION = "invitation"


class Problem(StrEnum):
    """Why the callback did not do what the flow was for, as the web page that explains it names it."""

    # The flow is unknown, used, expired, or started in another browser.
    EXPIRED = "expired"
    # The provider refused or failed, or its answer did not check out.
    FAILED = "failed"
    # Nobody has linked this identity, and the operator does not let it make an account.
    INVITATION_REQUIRED = "invitation_required"
    # Another account has linked this identity.
    IDENTITY_TAKEN = "identity_taken"
    # Confirming it is you with another identity than the account's.
    WRONG_ACCOUNT = "wrong_account"
    ACCOUNT_DISABLED = "account_disabled"
    # The account has another identity at the provider already.
    ALREADY_LINKED = "already_linked"
    # The invitation can no longer be accepted, or gives access the account already has.
    INVITATION_UNUSABLE = "invitation_unusable"


@dataclass(frozen=True, slots=True)
class Claims:
    """What the provider says of the person, from a checked ID token."""

    subject: str
    email: str | None = None
    email_verified: bool = False
    name: str | None = None
    preferred_username: str | None = None


class OidcProvider(Protocol):
    @property
    def issuer(self) -> str:
        """The provider's issuer, as identities are keyed by it."""
        ...

    @property
    def name(self) -> str:
        """What the sign-in button calls it, such as "Authentik"."""
        ...

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str, reauthenticate: bool) -> str:
        """Where the browser signs in; ``reauthenticate`` asks the provider to check the person again."""
        ...

    async def claims(self, *, code: str, code_verifier: str, nonce: str) -> Claims:
        """Exchange the code and check the ID token: signature, issuer, audience, expiry and nonce.

        Raises ``ProviderError`` for anything that does not check out.
        """
        ...


@dataclass(frozen=True, slots=True)
class ExternalSignIn:
    """The operator's provider, and whether an identity nobody linked may make an account (off by default)."""

    provider: OidcProvider
    allow_sign_up: bool


@dataclass(slots=True)
class OidcFlow:
    """A flow from its start to the provider's callback; only hashes of its state and browser binding are kept."""

    purpose: FlowPurpose
    state_hash: bytes
    # The hash of a random value in a cookie of the browser that started it: a callback opened in another
    # browser (someone else's code and state, slipped to a victim) finds no flow.
    browser_hash: bytes
    nonce: str
    code_verifier: str
    return_to: str
    locale: str
    created_at: datetime
    expires_at: datetime
    # The counter key of the address that started it (domain/throttle.py).
    address: str | None
    # The account and session of a link or a confirmation.
    user_id: UUID | None = None
    session_id: UUID | None = None
    # The hash of the invitation's token, for a flow that accepts one.
    invitation_hash: bytes | None = None
    id: UUID = field(default_factory=new_id)

    @classmethod
    def start(
        cls,
        purpose: FlowPurpose,
        *,
        return_to: str,
        locale: str,
        address: str | None,
        now: datetime,
        user_id: UUID | None = None,
        session_id: UUID | None = None,
        invitation_hash: bytes | None = None,
    ) -> tuple[OidcFlow, str, str]:
        """A new flow, its state for the provider and the browser binding for the cookie."""
        state, state_hash = new_secret()
        binding, browser_hash = new_secret()
        flow = cls(
            purpose=purpose,
            state_hash=state_hash,
            browser_hash=browser_hash,
            nonce=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(48),
            return_to=return_to,
            locale=locale,
            created_at=now,
            expires_at=now + FLOW_LIFETIME,
            address=address,
            user_id=user_id,
            session_id=session_id,
            invitation_hash=invitation_hash,
        )
        return flow, state, binding

    def started_in(self, binding: str | None) -> bool:
        return binding is not None and secrets.compare_digest(hash_token(binding), self.browser_hash)


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """An account's identity at the provider: the issuer and the ``sub`` it never reuses."""

    provider: str
    subject: str
    user_id: UUID
    created_at: datetime
    # What the provider said when it was linked, to tell identities apart on the account page.
    email: str | None = None
    id: UUID = field(default_factory=new_id)


def check_open_flows(open_count: int) -> None:
    if open_count >= OPEN_FLOWS_PER_ADDRESS:
        raise TooManyAttemptsError(
            "too many sign-ins started from here; wait a few minutes",
            params={"retry_after_seconds": int(FLOW_LIFETIME.total_seconds())},
        )


def safe_return_to(path: str | None, default: str) -> str:
    """A page of the install to come back to: a path of its own, never another site."""
    if path is None or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return default
    return path


def username_candidates(claims: Claims) -> list[str]:
    """Usernames to try for an account the provider's identity makes, the first one that is free wins."""
    base = _username_base(claims)
    return [base, *(f"{base[: USERNAME_MAX_LENGTH - len(str(n)) - 1]}-{n}" for n in range(2, USERNAME_SUFFIXES + 1))]


def display_name_of(claims: Claims, username: str) -> str:
    for candidate in (claims.name, claims.preferred_username):
        if candidate and candidate.strip():
            return candidate.strip()[:NAME_MAX_LENGTH]
    return username


def _username_base(claims: Claims) -> str:
    local_part = claims.email.split("@", 1)[0] if claims.email else None
    for candidate in (claims.preferred_username, local_part, claims.name):
        if candidate:
            cleaned = _usernameish(candidate)
            if USERNAME_PATTERN.fullmatch(cleaned):
                return cleaned
    return FALLBACK_USERNAME


def _usernameish(text: str) -> str:
    """The text as a username: spaces as dots, other characters a username cannot have dropped."""
    normalized = normalize_username(unicodedata.normalize("NFKC", text))
    joined = re.sub(r"\s+", ".", normalized)
    kept = re.sub(r"[^\w.-]", "", joined).strip(".-_")
    return kept[:USERNAME_MAX_LENGTH] if len(kept) >= USERNAME_MIN_LENGTH else ""
