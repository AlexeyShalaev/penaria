"""Checking a second factor, and the rule of who must have one (sign-in.md, 4.3).

An owner of any home and an install admin who can sign in with a password or the provider must also have an
authenticator app or a passkey. Until they add one, the owner-level commands refuse them
(``require_second_factor``); the rule follows the account as it is now, so adding a factor lifts it
in every session at once, and becoming an owner brings it.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import assert_never
from uuid import UUID

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.mail import MailKind
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.secrets import SecretBox, SecretUnreadableError
from penaria.features.support.identity.domain.totp import (
    SecondFactorRequiredError,
    Totp,
    TotpUnreadableError,
    bound_to,
    second_factor_required,
)
from penaria.features.support.identity.use_cases.postman import Postman

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AppCode:
    """A code the authenticator app shows."""

    code: str


@dataclass(frozen=True, slots=True)
class RecoveryCode:
    """One of the account's single-use recovery codes."""

    code: str


type SecondFactorProof = AppCode | RecoveryCode


class SecondFactorMethod(StrEnum):
    """How a person proved the second factor, as the journal says it."""

    TOTP = "totp"
    RECOVERY_CODE = "recovery_code"


async def prove_second_factor(
    tx: IdentityTransaction,
    box: SecretBox,
    postman: Postman,
    user: User,
    totp: Totp,
    proof: SecondFactorProof,
    now: datetime,
) -> SecondFactorMethod:
    """Accept the proof for the account's authenticator app, in ``tx``, which holds the account locked:
    a code is used once, and a recovery code is crossed off, journalled and told by email."""
    match proof:
        case AppCode(code=code):
            totp.use_code(open_secret(box, totp), code, now)
            await tx.totp.save(totp)
        case RecoveryCode(code=code):
            totp.use_recovery_code(code)
            await tx.totp.save(totp)
            left = len(totp.recovery_codes)
            await tx.journal.append(
                [
                    Event(
                        "account.recovery_code_used",
                        None,
                        Actor.user(user.id),
                        {"user_id": str(user.id), "recovery_codes_left": left},
                    )
                ]
            )
            await postman.notify(tx, user, MailKind.RECOVERY_CODE_USED, {"left": str(left)})
        case _:
            assert_never(proof)
    return method_of(proof)


def method_of(proof: SecondFactorProof) -> SecondFactorMethod:
    match proof:
        case AppCode():
            return SecondFactorMethod.TOTP
        case RecoveryCode():
            return SecondFactorMethod.RECOVERY_CODE
        case _:
            assert_never(proof)


def open_secret(box: SecretBox, totp: Totp) -> str:
    try:
        return box.open(totp.sealed_secret, bound_to=bound_to(totp.user_id))
    except SecretUnreadableError as exc:
        logger.error("The authenticator app's secret of an account does not open: %s", exc)  # noqa: TRY400 - expected
        raise TotpUnreadableError(
            "the authenticator app's key does not open with the install's keys: use a recovery code"
        ) from exc


async def totp_enabled(tx: IdentityTransaction, user_id: UUID) -> Totp | None:
    """The account's authenticator app, if it is turned on."""
    totp = await tx.totp.get(user_id)
    return totp if totp is not None and totp.enabled else None


async def must_have_second_factor(tx: IdentityTransaction, user: User) -> bool:
    """Whether the account must keep a second factor: an install admin or an owner who has a password or an
    identity at the operator's provider. Any identity counts, one of an earlier issuer too: asking for a
    factor it no longer needs errs on the safe side."""
    return second_factor_required(
        signs_in_without_passkey=await tx.passwords.get(user.id) is not None
        or bool(await tx.external_identities.for_user(user.id)),
        install_admin=user.install_admin,
        owns_a_home=await tx.grants.owns_a_home(user.id),
    )


@dataclass(frozen=True, slots=True)
class SecondFactorState:
    # The authenticator app, if it is on.
    totp: Totp | None
    # The account must keep a second factor (``must_have_second_factor``).
    required: bool
    # Required, and it has neither an app nor a passkey: owner-level commands refuse it.
    missing: bool


async def second_factor_state(tx: IdentityTransaction, user: User) -> SecondFactorState:
    totp = await totp_enabled(tx, user.id)
    required = await must_have_second_factor(tx, user)
    missing = required and totp is None and not await tx.passkeys.for_user(user.id)
    return SecondFactorState(totp=totp, required=required, missing=missing)


async def require_second_factor(tx: IdentityTransaction, user_id: UUID) -> None:
    """Refuse an owner-level command to an account that must have a second factor and has none."""
    user = await tx.users.get(user_id)
    if user is None:
        raise RuntimeError(f"the user ({user_id}) of an open session does not exist")
    if (await second_factor_state(tx, user)).missing:
        raise SecondFactorRequiredError(
            "add a passkey or an authenticator app first: owners and install admins who sign in with a "
            "password or the sign-in provider need a second factor"
        )
