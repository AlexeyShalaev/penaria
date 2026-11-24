"""The install's WebAuthn relying party (py_webauthn)."""

from collections.abc import Sequence
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    options_to_json_dict,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.passkeys import (
    CEREMONY_TIMEOUT,
    Assertion,
    Challenge,
    CredentialJson,
    CredentialRejected,
    NewCredential,
    Passkey,
    user_handle,
)

RP_NAME = "Penaria"
TIMEOUT_MS = int(CEREMONY_TIMEOUT.total_seconds() * 1000)
# A passkey is the only factor of its sign-in (sign-in.md, 4.3), so the authenticator must check the
# person (a fingerprint, a face, a PIN), not just that someone touched it: asked for, and checked.
USER_VERIFICATION = UserVerificationRequirement.REQUIRED
REQUIRE_USER_VERIFICATION = USER_VERIFICATION is UserVerificationRequirement.REQUIRED
# People sign in without typing a username, so only a credential the authenticator keeps and offers
# by itself (a discoverable one) could ever sign in.
RESIDENT_KEY = ResidentKeyRequirement.REQUIRED


class WebAuthnRelyingParty:
    """The relying party is the install's host name; answers must come from its own pages' origin."""

    def __init__(self, rp_id: str, origin: str) -> None:
        self._rp_id = rp_id
        self._origin = origin

    def registration_options(self, user: User, challenge: Challenge, existing: Sequence[Passkey]) -> dict[str, Any]:
        if user.username is None:
            raise RuntimeError(f"the user ({user.id}) has no account to add a passkey to")
        options = generate_registration_options(
            rp_id=self._rp_id,
            rp_name=RP_NAME,
            user_id=user_handle(user),
            user_name=user.username,
            user_display_name=user.display_name,
            challenge=challenge.value,
            timeout=TIMEOUT_MS,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=RESIDENT_KEY, user_verification=USER_VERIFICATION
            ),
            exclude_credentials=_descriptors(existing),
        )
        return options_to_json_dict(options)

    def verify_registration(self, credential: CredentialJson, challenge: Challenge) -> NewCredential:
        try:
            parsed = parse_registration_credential_json(dict(credential))
            verified = verify_registration_response(
                credential=parsed,
                expected_challenge=challenge.value,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
                require_user_verification=REQUIRE_USER_VERIFICATION,
            )
        except WebAuthnException as exc:
            raise CredentialRejected(str(exc)) from exc
        return NewCredential(
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=[transport.value for transport in parsed.response.transports or []],
        )

    def authentication_options(self, challenge: Challenge, allowed: Sequence[Passkey]) -> dict[str, Any]:
        options = generate_authentication_options(
            rp_id=self._rp_id,
            challenge=challenge.value,
            timeout=TIMEOUT_MS,
            allow_credentials=_descriptors(allowed),
            user_verification=USER_VERIFICATION,
        )
        return options_to_json_dict(options)

    def read_assertion(self, credential: CredentialJson) -> Assertion:
        try:
            parsed = parse_authentication_credential_json(dict(credential))
        # The library decodes userHandle outside its own error handling: bad base64url is a ValueError.
        except (WebAuthnException, ValueError) as exc:
            raise CredentialRejected(str(exc)) from exc
        return Assertion(credential_id=parsed.raw_id, user_handle=parsed.response.user_handle)

    def verify_authentication(self, credential: CredentialJson, challenge: Challenge, passkey: Passkey) -> int:
        try:
            # It also refuses a signature count that did not grow, the sign of a cloned authenticator;
            # synced passkeys always count zero, which passes.
            verified = verify_authentication_response(
                credential=dict(credential),
                expected_challenge=challenge.value,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
                credential_public_key=passkey.public_key,
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=REQUIRE_USER_VERIFICATION,
            )
        except (WebAuthnException, ValueError) as exc:
            raise CredentialRejected(str(exc)) from exc
        return verified.new_sign_count


def _descriptors(passkeys: Sequence[Passkey]) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(id=passkey.credential_id, transports=_transports(passkey)) for passkey in passkeys
    ]


def _transports(passkey: Passkey) -> list[AuthenticatorTransport]:
    # Only hints: one a later version of the library no longer knows is left out, as it does when reading.
    known = {transport.value for transport in AuthenticatorTransport}
    return [AuthenticatorTransport(transport) for transport in passkey.transports if transport in known]
