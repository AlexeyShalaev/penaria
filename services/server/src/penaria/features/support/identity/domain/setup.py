"""The setup token: proof of access to the machine before the first account exists (sign-in.md, 2)."""

import hashlib
import hmac
import secrets

from penaria.features.shared.errors import ConflictError, ForbiddenError

TOKEN_BYTES = 16


class InvalidSetupTokenError(ForbiddenError):
    code = "invalid_setup_token"


class AlreadySetUpError(ConflictError):
    code = "already_set_up"


def new_setup_token() -> tuple[str, bytes]:
    """A token to print and the hash to keep."""
    token = secrets.token_hex(TOKEN_BYTES)
    return token, hash_setup_token(token)


def hash_setup_token(token: str) -> bytes:
    return hashlib.sha256(token.strip().lower().encode()).digest()


def setup_token_matches(token: str, stored_hash: bytes | None) -> bool:
    return stored_hash is not None and hmac.compare_digest(hash_setup_token(token), stored_hash)
