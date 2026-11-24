"""A software passkey authenticator that answers as a browser with a phone or a password manager would."""

import copy
import hashlib
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.encode_cbor import encode_cbor

USER_PRESENT = 0x01
USER_VERIFIED = 0x04
ATTESTED_DATA = 0x40
# COSE: an EC2 key on P-256 for ES256.
COSE_KEY_TYPE, COSE_ALG, COSE_CURVE, COSE_X, COSE_Y = 1, 3, -1, -2, -3
EC2, ES256, P256 = 2, -7, 1
COORDINATE_BYTES = 32


class Authenticator:
    """One credential on one device, made by ``create`` and used by ``get``.

    ``counting`` makes it count its signatures as security keys do; synced passkeys always say zero.
    """

    def __init__(self, origin: str, *, counting: bool = False, verifies_user: bool = True) -> None:
        self.origin = origin
        self.counting = counting
        self.verifies_user = verifies_user
        self.credential_id = secrets.token_bytes(16)
        self.sign_count = 0
        self.user_handle: bytes | None = None
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._rp_id: str | None = None

    def create(self, options: dict[str, Any]) -> dict[str, Any]:
        """The JSON of the credential ``navigator.credentials.create`` would give for the options."""
        self._rp_id = options["rp"]["id"]
        self.user_handle = base64url_to_bytes(options["user"]["id"])
        client_data = self._client_data("webauthn.create", options["challenge"])
        auth_data = self._auth_data(ATTESTED_DATA) + bytes(16) + len(self.credential_id).to_bytes(2, "big")
        auth_data += self.credential_id + self._public_key()
        attestation = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["hybrid", "internal"],
            },
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
        }

    def get(self, options: dict[str, Any]) -> dict[str, Any]:
        """The JSON of the answer ``navigator.credentials.get`` would give for the options."""
        allowed = [base64url_to_bytes(c["id"]) for c in options.get("allowCredentials", [])]
        if allowed and self.credential_id not in allowed:
            raise AssertionError("the options do not allow this credential")
        if self._rp_id != options["rpId"]:
            raise AssertionError("the credential belongs to another relying party")
        if self.counting:
            self.sign_count += 1
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = self._auth_data(0)
        signature = self._key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": None if self.user_handle is None else bytes_to_base64url(self.user_handle),
            },
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
        }

    @classmethod
    def stranger(cls, origin: str, rp_id: str) -> Authenticator:
        """A credential for the relying party that was never added to it."""
        device = cls(origin)
        device._rp_id = rp_id
        device.user_handle = secrets.token_bytes(16)
        return device

    def impostor(self) -> Authenticator:
        """Another key that claims this device's credential and account."""
        device = type(self)(self.origin)
        device.credential_id, device.user_handle, device._rp_id = self.credential_id, self.user_handle, self._rp_id
        return device

    def clone(self) -> Authenticator:
        """A copy of the device, its key and its count included, as an attacker who copied it would hold."""
        return copy.deepcopy(self)

    def _client_data(self, ceremony: str, challenge: str) -> bytes:
        return json.dumps(
            {"type": ceremony, "challenge": challenge, "origin": self.origin, "crossOrigin": False}
        ).encode()

    def _auth_data(self, flags: int) -> bytes:
        if self._rp_id is None:
            raise AssertionError("the credential has not been created")
        flags |= USER_PRESENT | (USER_VERIFIED if self.verifies_user else 0)
        rp_id_hash = hashlib.sha256(self._rp_id.encode()).digest()
        return rp_id_hash + bytes([flags]) + self.sign_count.to_bytes(4, "big")

    def _public_key(self) -> bytes:
        numbers = self._key.public_key().public_numbers()
        return encode_cbor(
            {
                COSE_KEY_TYPE: EC2,
                COSE_ALG: ES256,
                COSE_CURVE: P256,
                COSE_X: numbers.x.to_bytes(COORDINATE_BYTES, "big"),
                COSE_Y: numbers.y.to_bytes(COORDINATE_BYTES, "big"),
            }
        )
