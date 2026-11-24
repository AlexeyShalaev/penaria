import base64
import ssl

import aiosmtplib
import pytest

from penaria.features.support.identity.domain.mail import Failure, FailureReason
from penaria.features.support.identity.infra.smtp import classify, scrub

pytestmark = pytest.mark.unit

LOGIN = "home@example.org"
PASSWORD = "s3cret-Passw0rd"  # noqa: S105 - a value of the tests


def test_an_authentication_failure_hides_the_login_and_the_password_in_every_form() -> None:
    plain = base64.b64encode(f"\0{LOGIN}\0{PASSWORD}".encode()).decode()
    words = f"5.7.8 Rejected {LOGIN} {PASSWORD} {base64.b64encode(PASSWORD.encode()).decode()} {plain}"

    failure = classify(aiosmtplib.SMTPAuthenticationError(535, words), login=LOGIN, password=PASSWORD)

    assert failure == Failure(
        FailureReason.AUTH, smtp_code=535, text="5.7.8 Rejected [hidden] [hidden] [hidden] [hidden]"
    )


def test_a_refused_recipient_takes_the_recipients_reply() -> None:
    refused = aiosmtplib.SMTPRecipientsRefused([aiosmtplib.SMTPRecipientRefused(550, "5.1.1 Unknown user", "x@y.z")])

    assert classify(refused, login=None, password=None) == Failure(
        FailureReason.RECIPIENT_REFUSED, smtp_code=550, text="5.1.1 Unknown user"
    )


def test_a_refused_connection_names_the_error() -> None:
    error = aiosmtplib.SMTPConnectError("Error connecting to 127.0.0.1 on port 1: [Errno 61] Connection refused")

    assert classify(error, login=None, password=None) == Failure(
        FailureReason.CONNECT, text="Error connecting to 127.0.0.1 on port 1: [Errno 61] Connection refused"
    )


def test_a_timeout_is_a_timeout() -> None:
    assert (
        classify(aiosmtplib.SMTPReadTimeoutError("Timed out"), login=None, password=None).reason
        is FailureReason.TIMEOUT
    )


def test_a_tls_failure_inside_a_connection_error_is_a_tls_failure() -> None:
    error = aiosmtplib.SMTPConnectError("Error connecting")
    error.__cause__ = ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")

    failure = classify(error, login=None, password=None)

    assert failure.reason is FailureReason.TLS


def test_starttls_the_server_does_not_offer_is_a_tls_failure() -> None:
    failure = classify(aiosmtplib.SMTPNotSupported("STARTTLS extension not supported"), login=None, password=None)

    assert failure.reason is FailureReason.TLS


def test_a_plain_smtp_error_without_a_reply_is_another_failure() -> None:
    failure = classify(aiosmtplib.SMTPException("Something odd"), login=None, password=None)

    assert failure == Failure(FailureReason.OTHER, text="Something odd")


def test_an_unexpected_error_names_its_kind() -> None:
    assert classify(ValueError("odd"), login=None, password=None) == Failure(
        FailureReason.OTHER, text="ValueError: odd"
    )


def test_scrubbed_text_is_one_line_of_500_characters_at_most() -> None:
    assert scrub("line one\r\nline\ttwo", login=None, password=None) == "line one line two"
    assert len(scrub("x" * 900, login=None, password=None) or "") == 500
    assert scrub("   ", login=None, password=None) is None
