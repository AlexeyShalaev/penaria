from datetime import UTC, datetime, timedelta

import pytest

from penaria.features.support.identity.domain.throttle import (
    Failures,
    TooManyAttemptsError,
    address_key,
    check_not_blocked,
    delay_after,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("failures", "delay"),
    [
        (4, None),
        (5, timedelta(seconds=30)),
        (6, timedelta(seconds=60)),
        (9, timedelta(minutes=8)),
        (10, timedelta(minutes=15)),
        (1000, timedelta(minutes=15)),
    ],
)
def test_the_wait_doubles_after_five_failures_up_to_fifteen_minutes(failures: int, delay: timedelta | None) -> None:
    assert delay_after(failures) == delay


def test_an_attempt_within_the_wait_is_refused_with_the_time_left() -> None:
    failures = [Failures(count=6, last_at=NOW - timedelta(seconds=20))]

    with pytest.raises(TooManyAttemptsError) as raised:
        check_not_blocked(failures, NOW)

    assert raised.value.params == {"retry_after_seconds": 41}


def test_the_longest_wait_of_the_counters_applies() -> None:
    failures = [
        Failures(count=5, last_at=NOW),
        Failures(count=10, last_at=NOW),
    ]

    with pytest.raises(TooManyAttemptsError) as raised:
        check_not_blocked(failures, NOW)

    assert raised.value.params == {"retry_after_seconds": 901}


def test_an_attempt_after_the_wait_passes() -> None:
    check_not_blocked([Failures(count=5, last_at=NOW - timedelta(seconds=30))], NOW)


def test_a_few_failures_do_not_block() -> None:
    check_not_blocked([Failures(count=4, last_at=NOW)], NOW)


@pytest.mark.parametrize(
    ("ip", "key"),
    [
        ("192.0.2.7", "ip:192.0.2.7"),
        ("2001:db8:1:2:aaaa::1", "ip:2001:db8:1:2::/64"),
        ("2001:db8:1:2:bbbb::2", "ip:2001:db8:1:2::/64"),
        (None, None),
    ],
)
def test_an_ipv6_address_counts_by_its_64_block(ip: str | None, key: str | None) -> None:
    assert address_key(ip) == key
