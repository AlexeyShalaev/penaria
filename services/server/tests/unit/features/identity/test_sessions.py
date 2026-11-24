from datetime import UTC, datetime, timedelta

import pytest

from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.sessions import Client, Session, hash_token

pytestmark = pytest.mark.unit

STARTED = datetime(2026, 1, 1, tzinfo=UTC)


def started() -> Session:
    session, _ = Session.start(new_id(), Client(user_agent="Firefox", ip="192.0.2.1"), STARTED)
    return session


def test_only_the_hash_of_the_token_is_kept() -> None:
    session, token = Session.start(new_id(), Client(user_agent=None, ip=None), STARTED)

    assert session.token_hash == hash_token(token)
    assert token.encode() not in session.token_hash


def test_a_session_ends_after_thirty_days_unused() -> None:
    session = started()

    assert session.is_active(STARTED + timedelta(days=29, hours=23))
    assert not session.is_active(STARTED + timedelta(days=30))


def test_a_session_in_use_ends_after_one_hundred_and_eighty_days() -> None:
    session = started()
    session.last_seen_at = STARTED + timedelta(days=179)

    assert session.is_active(STARTED + timedelta(days=179, hours=23))
    assert not session.is_active(STARTED + timedelta(days=180))


def test_a_revoked_session_has_ended() -> None:
    session = started()
    session.revoked_at = STARTED + timedelta(minutes=1)

    assert not session.is_active(STARTED + timedelta(minutes=2))


def test_last_use_is_written_at_most_every_five_minutes() -> None:
    session = started()

    assert not session.needs_touch(STARTED + timedelta(minutes=4, seconds=59))
    assert session.needs_touch(STARTED + timedelta(minutes=5))
