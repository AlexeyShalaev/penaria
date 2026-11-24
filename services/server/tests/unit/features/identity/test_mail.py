from datetime import UTC, datetime, timedelta

import pytest

from penaria.features.support.identity.domain.mail import (
    Failure,
    FailureReason,
    Mail,
    MailKind,
    MailState,
    after_attempt,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
BUSY = Failure(FailureReason.OTHER, smtp_code=451, text="4.3.0 Try again later")


def mail(attempts: int, *, kind: MailKind = MailKind.PASSWORD_RESET) -> Mail:
    return Mail(
        kind=kind,
        to_address="someone@example.org",
        locale="en",
        subject="Reset your Penaria password",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        attempts=attempts,
    )


@pytest.mark.parametrize(
    ("attempts", "wait"),
    [(1, timedelta(minutes=1)), (2, timedelta(minutes=5)), (3, timedelta(minutes=15)), (4, timedelta(minutes=30))],
)
def test_a_temporary_failure_waits_longer_after_each_attempt(attempts: int, wait: timedelta) -> None:
    assert after_attempt(mail(attempts), BUSY, NOW) == (MailState.QUEUED, NOW + wait)


def test_the_fifth_failed_attempt_is_the_last() -> None:
    assert after_attempt(mail(5), BUSY, NOW) == (MailState.FAILED, None)


def test_a_sent_mail_is_done() -> None:
    assert after_attempt(mail(3), None, NOW) == (MailState.SENT, None)


def test_a_permanent_failure_is_not_retried() -> None:
    refused = Failure(FailureReason.RECIPIENT_REFUSED, smtp_code=550, text="5.1.1 No such user")

    assert after_attempt(mail(1), refused, NOW) == (MailState.FAILED, None)


def test_a_test_mail_is_never_retried() -> None:
    assert after_attempt(mail(1, kind=MailKind.TEST), BUSY, NOW) == (MailState.FAILED, None)


@pytest.mark.parametrize(
    ("failure", "temporary"),
    [
        (Failure(FailureReason.RECIPIENT_REFUSED, smtp_code=450), True),
        (Failure(FailureReason.AUTH, smtp_code=535), False),
        (Failure(FailureReason.CONNECT), True),
        (Failure(FailureReason.TIMEOUT), True),
        (Failure(FailureReason.DISCONNECTED), True),
        (Failure(FailureReason.TLS), False),
        (Failure(FailureReason.MAIL_OFF), False),
        (Failure(FailureReason.EXPIRED), False),
        (Failure(FailureReason.UNREADABLE), False),
    ],
)
def test_temporary_failures_are_4xx_replies_and_broken_connections(failure: Failure, temporary: bool) -> None:
    assert failure.temporary is temporary


@pytest.mark.parametrize(
    ("failure", "described"),
    [
        (Failure(FailureReason.AUTH, smtp_code=535, text="5.7.8 Bad credentials"), "535 5.7.8 Bad credentials"),
        (Failure(FailureReason.CONNECT, text="ConnectionRefusedError: refused"), "ConnectionRefusedError: refused"),
        (Failure(FailureReason.MAIL_OFF), "mail_off"),
    ],
)
def test_a_failure_is_described_with_the_servers_words(failure: Failure, described: str) -> None:
    assert failure.describe() == described


def test_a_mail_can_be_sent_until_it_expires_while_it_has_content() -> None:
    queued = mail(0)
    queued.sealed_content = "pnr1:k:t"

    assert queued.sendable(NOW + timedelta(minutes=29)) is True
    assert queued.sendable(NOW + timedelta(minutes=30)) is False
    queued.sealed_content = None
    assert queued.sendable(NOW) is False
