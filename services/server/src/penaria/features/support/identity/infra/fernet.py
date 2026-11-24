"""Stored secrets encrypted with Fernet under keys derived from ``PENARIA_SECRET_KEY`` (sign-in.md, 15).

A sealed secret is an envelope, ``pnr1:<key id>:<Fernet token>``. The key id names the key that
sealed it, so a secret sealed before the key was rotated opens with the retired key that sealed it,
and a secret whose key is gone is told apart from a damaged one. Fernet has no associated data, so
the binding goes inside the token: the plaintext is the binding, a NUL byte and the secret, and
opening checks the binding, so a ciphertext copied into another row, column or table does not open.
"""

import base64
import hashlib
import hmac
from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from penaria.features.support.identity.domain.secrets import SecretUnreadableError

ENVELOPE = "pnr1"
SEPARATOR = b"\x00"
# Another purpose of the same setting (signing, say) derives a key of its own from it.
PURPOSE = b"penaria/stored-secrets/v1"
KEY_BYTES = 32
KEY_ID_LENGTH = 8


class FernetSecretBox:
    """Seals with the first key; opens with any, so the old key keeps reading while it is retired."""

    def __init__(self, keys: dict[str, Fernet], primary: str) -> None:
        self._keys = keys
        self._primary = primary

    @classmethod
    def of(cls, secret_key: str, retired: Sequence[str] = ()) -> FernetSecretBox:
        """The box of ``PENARIA_SECRET_KEY``, reading what the retired keys sealed too."""
        primary = derive_key(secret_key)
        keys = {key_id(key): Fernet(key) for key in [primary, *(derive_key(old) for old in retired)]}
        return cls(keys, key_id(primary))

    def seal(self, plaintext: str, *, bound_to: str) -> str:
        binding = bound_to.encode()
        if SEPARATOR in binding:
            raise ValueError("a binding cannot hold a NUL byte")
        token = self._keys[self._primary].encrypt(binding + SEPARATOR + plaintext.encode())
        return f"{ENVELOPE}:{self._primary}:{token.decode()}"

    def open(self, sealed: str, *, bound_to: str) -> str:
        envelope, _, rest = sealed.partition(":")
        found_id, _, token = rest.partition(":")
        if envelope != ENVELOPE or not token:
            raise SecretUnreadableError("the stored secret is not an envelope of this version")
        fernet = self._keys.get(found_id)
        if fernet is None:
            raise SecretUnreadableError(
                f"the stored secret was sealed with a key ({found_id}) that is neither PENARIA_SECRET_KEY "
                "nor among PENARIA_RETIRED_SECRET_KEYS"
            )
        try:
            payload = fernet.decrypt(token.encode())
        except InvalidToken as exc:
            raise SecretUnreadableError(f"the stored secret sealed with the key ({found_id}) is damaged") from exc
        prefix = bound_to.encode() + SEPARATOR
        if not hmac.compare_digest(payload[: len(prefix)], prefix):
            raise SecretUnreadableError("the stored secret belongs to another record")
        return payload[len(prefix) :].decode()


def derive_key(secret_key: str) -> bytes:
    """The Fernet key of a ``PENARIA_SECRET_KEY``: the setting is a passphrase of any form, not a Fernet key."""
    raw = HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=PURPOSE).derive(secret_key.encode())
    return base64.urlsafe_b64encode(raw)


def key_id(key: bytes) -> str:
    """A short name of a key that tells nothing about it."""
    return hashlib.sha256(key).hexdigest()[:KEY_ID_LENGTH]
