"""One-time links that act on an account: resetting its password and confirming its email (sign-in.md, 8 and 15).

Only a hash of a link's token is kept, as for invitations; a link works once, until it expires.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from penaria.features.shared.errors import ConflictError, ForbiddenError, NotFoundError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.sessions import new_secret

# A link in an email goes stale fast: whoever reads the mailbox later should not find a working one.
EMAILED_RESET_LIFETIME = timedelta(minutes=30)
# A link passed on by hand (an admin's, the operator's) may wait for its person a day.
HANDED_RESET_LIFETIME = timedelta(hours=24)
EMAIL_VERIFICATION_LIFETIME = timedelta(hours=24)


class LinkPurpose(StrEnum):
    PASSWORD_RESET = "password_reset"  # noqa: S105 - a kind of link, not a password
    EMAIL_VERIFICATION = "email_verification"


class ResetBy(StrEnum):
    """Who made a reset link, as the journal says it."""

    # The person, through "forgot password": emailed.
    SELF = "self"
    # An admin of a home the person belongs to.
    ADMIN = "admin"
    # Whoever runs the server, with the command line.
    OPERATOR = "operator"


class AccountLinkNotFoundError(NotFoundError):
    code = "account_link_not_found"


class AccountLinkExpiredError(ConflictError):
    code = "account_link_expired"


class AccountLinkUsedError(ConflictError):
    code = "account_link_used"


class EmailTakenError(ConflictError):
    code = "email_taken"


class ResetNotAllowedError(ForbiddenError):
    """The person has access the admin could not give, so resetting their password would hand it over."""

    code = "reset_not_allowed"


@dataclass(slots=True)
class AccountLink:
    user_id: UUID
    purpose: LinkPurpose
    token_hash: bytes
    created_at: datetime
    expires_at: datetime
    # The address it confirms; only for an email verification.
    email: str | None = None
    # Who made it for someone else: the admin; None when the person or the operator did.
    created_by: UUID | None = None
    used_at: datetime | None = None
    id: UUID = field(default_factory=new_id)

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        purpose: LinkPurpose,
        lifetime: timedelta,
        now: datetime,
        email: str | None = None,
        created_by: UUID | None = None,
    ) -> tuple[AccountLink, str]:
        """A new link and its secret token; only the token's hash is kept."""
        if (purpose is LinkPurpose.EMAIL_VERIFICATION) != (email is not None):
            raise ValueError("an email verification, and only it, names the address it confirms")
        token, token_hash = new_secret()
        link = cls(
            user_id=user_id,
            purpose=purpose,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + lifetime,
            email=email,
            created_by=created_by,
        )
        return link, token

    def check_open(self, now: datetime) -> None:
        if self.used_at is not None:
            raise AccountLinkUsedError("this link has already been used: ask for a new one")
        if now >= self.expires_at:
            raise AccountLinkExpiredError("this link has expired: ask for a new one")
