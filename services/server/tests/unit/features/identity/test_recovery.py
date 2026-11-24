from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from penaria.features.support.identity.domain.recovery import (
    AccountLink,
    AccountLinkExpiredError,
    AccountLinkUsedError,
    LinkPurpose,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
USER = UUID(int=7)


def reset_link() -> AccountLink:
    link, _ = AccountLink.create(
        user_id=USER, purpose=LinkPurpose.PASSWORD_RESET, lifetime=timedelta(minutes=30), now=NOW
    )
    return link


def test_a_link_works_until_the_moment_it_expires() -> None:
    link = reset_link()

    link.check_open(NOW + timedelta(minutes=30) - timedelta(seconds=1))
    with pytest.raises(AccountLinkExpiredError):
        link.check_open(NOW + timedelta(minutes=30))


def test_a_used_link_works_no_more() -> None:
    link = reset_link()
    link.used_at = NOW

    with pytest.raises(AccountLinkUsedError):
        link.check_open(NOW)


def test_only_a_confirmation_names_an_address() -> None:
    with pytest.raises(ValueError, match="names the address"):
        AccountLink.create(
            user_id=USER, purpose=LinkPurpose.PASSWORD_RESET, lifetime=timedelta(minutes=1), now=NOW, email="a@b.org"
        )
    with pytest.raises(ValueError, match="names the address"):
        AccountLink.create(user_id=USER, purpose=LinkPurpose.EMAIL_VERIFICATION, lifetime=timedelta(hours=1), now=NOW)


def test_a_link_keeps_only_the_hash_of_its_token() -> None:
    link, token = AccountLink.create(
        user_id=USER, purpose=LinkPurpose.PASSWORD_RESET, lifetime=timedelta(minutes=30), now=NOW
    )

    assert token.encode() not in link.token_hash
    assert len(link.token_hash) == 32
