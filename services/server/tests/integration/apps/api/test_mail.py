"""Outgoing email through the HTTP API: the install's mailbox, the test email, the queue and its log."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import select, update

from penaria.apps.api.mail import deliver_mail
from penaria.features.support.identity.domain.mailbox import MAILBOX_SEAL
from penaria.features.support.identity.infra.fernet import FernetSecretBox
from penaria.features.support.identity.infra.orm import AccountLinkDB, InstallSettingDB, MailAttemptDB, MailDB
from penaria.features.support.identity.use_cases import postman as postman_module
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.platform.infra.orm import JournalEventDB
from tests.integration.apps.api.test_people import age_sign_ins, make_home, member, ok
from tests.integration.helpers import NewClient, uow_of
from tests.smtp import FakeSmtp, html_of, text_of

pytestmark = pytest.mark.integration

SECRET = "smtp-password-of-the-test"  # noqa: S105 - a value of the tests


async def connect(api: httpx.AsyncClient, smtp: FakeSmtp, **changes: Any) -> dict[str, Any]:
    body = {**smtp.mailbox(), **changes}
    result: dict[str, Any] = await ok(await api.put("/install/mail", json=body))
    return result


async def postman(container: DishkaContainer) -> Postman:
    return await container.container.get(Postman)


async def mail_rows(container: DishkaContainer) -> list[MailDB]:
    async with (await uow_of(container)).query() as tx:
        return list(await tx.session.scalars(select(MailDB).order_by(MailDB.created_at)))


async def make_due(container: DishkaContainer) -> None:
    """Every queued mail's next attempt is now: the time it waits for has passed."""
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(
            update(MailDB).where(MailDB.state == "queued").values(next_attempt_at=datetime.now(UTC))
        )


# The mailbox


async def test_mail_is_off_until_an_admin_connects_a_mailbox(api: httpx.AsyncClient) -> None:
    settings = await ok(await api.get("/install/mail"))
    status = await ok(await api.get("/install/mail/status"))
    public = await ok(await api.get("/mail"))

    assert settings == {
        "source": None,
        "host": None,
        "port": None,
        "security": None,
        "username": None,
        "from_address": None,
        "from_name": None,
        "password_set": False,
    }
    assert status == {"health": "off", "error": None}
    assert public == {"enabled": False}


async def test_an_admin_connects_a_mailbox_whose_password_is_write_only(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    saved = await connect(api, smtp, username="home@example.org", password=SECRET, from_name="  Our   home ")

    assert saved == {
        "source": "interface",
        "host": "127.0.0.1",
        "port": smtp.port,
        "security": "none",
        "username": "home@example.org",
        "from_address": "home@example.org",
        "from_name": "Our home",
        "password_set": True,
    }
    assert await ok(await api.get("/install/mail")) == saved
    assert await ok(await api.get("/mail")) == {"enabled": True}
    async with (await uow_of(container)).query() as tx:
        row = await tx.session.scalar(select(InstallSettingDB))
        events = list(await tx.session.scalars(select(JournalEventDB).where(JournalEventDB.type.like("install.%"))))
    assert row is not None
    assert row.secret is not None
    assert row.secret.startswith("pnr1:")
    assert SECRET not in row.secret
    assert SECRET not in str(row.value)
    assert [(e.type, e.payload) for e in events] == [
        (
            "install.mailbox_saved",
            {
                "changed": ["host", "port", "security", "username", "from_address", "from_name"],
                "password_changed": True,
            },
        )
    ]


async def test_saving_without_a_password_keeps_the_saved_one(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp, username="home@example.org", password=SECRET)
    async with (await uow_of(container)).query() as tx:
        before = await tx.session.scalar(select(InstallSettingDB.secret))

    saved = await connect(api, smtp, username="home@example.org", password="", from_name="Home")

    async with (await uow_of(container)).query() as tx:
        after = await tx.session.scalar(select(InstallSettingDB.secret))
    assert saved["password_set"] is True
    assert after == before


async def test_a_mailbox_without_a_login_keeps_no_password(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp, username="home@example.org", password=SECRET)

    saved = await connect(api, smtp, username="")

    assert (saved["username"], saved["password_set"]) == (None, False)


async def test_a_mailbox_with_a_wrong_sender_is_refused(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    response = await api.put("/install/mail", json={**smtp.mailbox(), "from_address": "not an address"})

    assert response.status_code == 400
    assert (response.json()["code"], response.json()["params"]) == ("invalid_email", {"field": "from_address"})


async def test_changing_the_mailbox_needs_a_recent_sign_in(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    saved = await api.put("/install/mail", json=smtp.mailbox())
    removed = await api.delete("/install/mail")

    assert (saved.status_code, saved.json()["code"]) == (403, "recent_sign_in_required")
    assert (removed.status_code, removed.json()["code"]) == (403, "recent_sign_in_required")


async def test_turning_mail_off_forgets_the_mailbox(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp)

    await ok(await api.delete("/install/mail"), 204)

    assert (await ok(await api.get("/install/mail")))["source"] is None
    assert await ok(await api.get("/mail")) == {"enabled": False}


async def test_only_an_install_admin_sees_the_install_settings(
    api: httpx.AsyncClient, new_client: NewClient, smtp: FakeSmtp
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "admin", "maria")

    responses = [
        await maria.get("/install/mail"),
        await maria.put("/install/mail", json=smtp.mailbox()),
        await maria.post("/install/mail:test", json={"to": "maria@example.org"}),
        await maria.get("/install/mail/messages"),
    ]

    assert [(r.status_code, r.json()["code"]) for r in responses] == [(403, "install_admin_required")] * 4


@pytest.mark.parametrize(
    "operator_mail",
    [
        {
            "host": "smtp.example.org",
            "security": "tls",
            "username": "home",
            "password": SECRET,
            "from_address": "h@x.org",
        }
    ],
)
async def test_a_mailbox_from_the_environment_locks_the_settings(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    settings = await ok(await api.get("/install/mail"))
    saved = await api.put("/install/mail", json=smtp.mailbox())
    removed = await api.delete("/install/mail")

    assert settings == {
        "source": "environment",
        "host": "smtp.example.org",
        "port": 465,
        "security": "tls",
        "username": "home",
        "from_address": "h@x.org",
        "from_name": "Penaria",
        "password_set": True,
    }
    assert (saved.status_code, saved.json()["code"]) == (409, "mailbox_locked")
    assert (removed.status_code, removed.json()["code"]) == (409, "mailbox_locked")
    assert await ok(await api.get("/mail")) == {"enabled": True}


# The test email


async def test_a_test_email_goes_through_the_saved_mailbox(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp, from_name="Our home")

    result = await ok(await api.post("/install/mail:test", json={"to": "Someone@Example.org"}))

    assert result == {"ok": True, "error": None, "reason": None, "mail_id": result["mail_id"]}
    [message] = smtp.messages
    assert message["To"] == "someone@example.org"
    assert message["From"] == "Our home <home@example.org>"
    assert message["Subject"] == "Penaria: test email"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_content_type() == "multipart/alternative"
    assert "If you are reading it, the install can send email" in text_of(message)
    assert "<h1" in html_of(message)


async def test_a_test_email_without_an_address_needs_one_when_the_account_has_none(
    api: httpx.AsyncClient, smtp: FakeSmtp
) -> None:
    await connect(api, smtp)

    response = await api.post("/install/mail:test", json={})

    assert (response.status_code, response.json()["code"], response.json()["params"]) == (
        400,
        "invalid_email",
        {"field": "to"},
    )


async def test_a_failed_test_email_answers_with_the_servers_words(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp)
    smtp.refuse = "550 5.1.1 No such mailbox here"

    result = await ok(await api.post("/install/mail:test", json={"to": "nobody@example.org"}))
    log = await ok(await api.get("/install/mail/messages"))

    assert {key: result[key] for key in ("ok", "error", "reason")} == {
        "ok": False,
        "error": "550 5.1.1 No such mailbox here",
        "reason": "recipient_refused",
    }
    assert [(m["kind"], m["state"], len(m["attempts"])) for m in log] == [("test", "failed", 1)]


async def test_a_test_email_to_a_server_that_is_not_there_fails_to_connect(
    api: httpx.AsyncClient, smtp: FakeSmtp
) -> None:
    await connect(api, smtp)
    await smtp.stop()

    result = await ok(await api.post("/install/mail:test", json={"to": "someone@example.org"}))
    status = await ok(await api.get("/install/mail/status"))

    assert (result["ok"], result["reason"]) == (False, "connect")
    assert status["health"] == "failed"


async def test_the_status_line_connects_to_the_mailbox(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp)

    assert await ok(await api.get("/install/mail/status")) == {"health": "ok", "error": None}


async def test_a_test_email_without_a_mailbox_is_refused(api: httpx.AsyncClient) -> None:
    response = await api.post("/install/mail:test", json={"to": "someone@example.org"})

    assert (response.status_code, response.json()["code"]) == (409, "mail_off")


# The queue and its retries


async def test_a_temporary_failure_is_retried_four_times_and_then_given_up(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, new_client: NewClient
) -> None:
    await connect(api, smtp)
    ids = await make_home(api)
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}
    await ok(
        await api.post(
            f"/homes/{ids['home']}/invitations", json={"role_id": roles["family"], "email": "guest@example.org"}
        ),
        201,
    )
    smtp.refuse = "451 4.3.0 Try again later"
    sender = await postman(container)

    started = datetime.now(UTC)
    await sender.deliver_due()
    [first] = await mail_rows(container)
    waits = [first.next_attempt_at]
    for _ in range(4):
        await make_due(container)
        await sender.deliver_due()
        waits.append((await mail_rows(container))[0].next_attempt_at)
    [last] = await mail_rows(container)

    assert first.state == "queued"
    assert first.next_attempt_at is not None
    assert timedelta(seconds=55) < first.next_attempt_at - started < timedelta(minutes=1, seconds=5)
    assert (last.state, last.attempts, last.next_attempt_at) == ("failed", 5, None)
    assert waits[-1] is None
    async with (await uow_of(container)).query() as tx:
        attempts = list(await tx.session.scalars(select(MailAttemptDB).order_by(MailAttemptDB.at)))
    assert [(a.reason, a.smtp_code) for a in attempts] == [("recipient_refused", 451)] * 5
    assert smtp.messages == []


async def test_a_queued_mail_is_sent_once_the_server_answers_again(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    smtp.refuse = "421 4.7.0 Busy"
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    sender = await postman(container)
    await sender.deliver_due()

    smtp.refuse = None
    await make_due(container)
    await sender.deliver_due()

    [mail] = await mail_rows(container)
    assert (mail.state, mail.attempts) == ("sent", 2)
    assert [m["To"] for m in smtp.messages] == ["owner@example.org"]


async def test_a_mail_left_by_a_sender_that_stopped_is_taken_again_after_its_lease(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    now = datetime.now(UTC)
    async with (await uow_of(container)).transaction() as tx:
        # Another replica took it and stopped before it was sent.
        claimed = await tx.mail.claim_due(now, now + timedelta(minutes=5), 10)
    sender = await postman(container)

    await sender.deliver_due()
    sent_while_held = len(smtp.messages)
    await make_due(container)
    await sender.deliver_due()

    assert (len(claimed), sent_while_held, len(smtp.messages)) == (1, 0, 1)


async def test_two_senders_at_once_send_each_mail_once(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, new_client: NewClient
) -> None:
    await connect(api, smtp)
    ids = await make_home(api)
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}
    for n in range(5):
        body = {"role_id": roles["family"], "email": f"person{n}@example.org"}
        await ok(await api.post(f"/homes/{ids['home']}/invitations", json=body), 201)
    sender = await postman(container)

    await asyncio.gather(sender.deliver_due(), sender.deliver_due(), sender.deliver_due())

    assert sorted(m["To"] for m in smtp.messages) == [f"person{n}@example.org" for n in range(5)]


async def test_a_mail_whose_link_expired_is_not_sent(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(MailDB).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    await (await postman(container)).deliver_due()
    await (await postman(container)).sweep()

    [mail] = await mail_rows(container)
    assert (mail.state, mail.content) == ("failed", None)
    assert smtp.messages == []


async def test_a_mail_queued_before_mail_was_turned_off_is_not_sent(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    await ok(await api.delete("/install/mail"), 204)

    await (await postman(container)).deliver_due()

    log = await ok(await api.get("/install/mail/messages"))
    assert [(m["state"], m["attempts"][0]["reason"]) for m in log] == [("failed", "mail_off")]


# The log and resending


async def test_the_log_lists_mails_with_their_attempts_and_resends_one(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    await (await postman(container)).deliver_due()
    [logged] = await ok(await api.get("/install/mail/messages"))

    resent = await ok(await api.post(f"/install/mail/messages/{logged['id']}:resend"))
    [after] = await ok(await api.get("/install/mail/messages"))

    assert {key: logged[key] for key in ("kind", "to", "subject", "locale", "state", "resendable")} == {
        "kind": "email_verification",
        "to": "owner@example.org",
        "subject": "Confirm your email for Penaria",
        "locale": "en",
        "state": "sent",
        "resendable": True,
    }
    assert [(a["ok"], a["manual"]) for a in logged["attempts"]] == [(True, False)]
    assert (resent["ok"], resent["mail_id"]) == (True, logged["id"])
    assert [(a["ok"], a["manual"]) for a in after["attempts"]] == [(True, True), (True, False)]
    assert len(smtp.messages) == 2
    assert text_of(smtp.messages[0]) == text_of(smtp.messages[1])


async def test_a_mail_that_can_no_longer_be_sent_is_not_resent(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    await (await postman(container)).deliver_due()
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(MailDB).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    [logged] = await ok(await api.get("/install/mail/messages"))

    response = await api.post(f"/install/mail/messages/{logged['id']}:resend")

    assert logged["resendable"] is False
    assert (response.status_code, response.json()["code"]) == (409, "mail_expired")


async def test_a_mail_waiting_for_its_retry_is_not_resent(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    smtp.refuse = "451 4.3.0 Try again later"
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    await (await postman(container)).deliver_due()
    [logged] = await ok(await api.get("/install/mail/messages"))

    response = await api.post(f"/install/mail/messages/{logged['id']}:resend")

    assert (logged["state"], logged["resendable"]) == ("queued", False)
    assert (response.status_code, response.json()["code"]) == (409, "mail_queued")


async def test_the_log_pages_by_the_last_mail_seen(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    for n in range(3):
        await ok(await api.post("/install/mail:test", json={"to": f"t{n}@example.org"}))

    first = await ok(await api.get("/install/mail/messages", params={"limit": 2}))
    second = await ok(await api.get("/install/mail/messages", params={"limit": 2, "before": first[-1]["id"]}))

    assert [m["to"] for m in first + second] == ["t2@example.org", "t1@example.org", "t0@example.org"]


# The loop of the api process


async def test_the_mail_loop_sends_what_is_queued_until_it_is_stopped(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    stop = asyncio.Event()

    async with container.unit_scope() as scope:
        loop = asyncio.create_task(deliver_mail(scope, stop))
        for _ in range(100):
            if smtp.messages:
                break
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(loop, timeout=5)

    assert [m["To"] for m in smtp.messages] == ["owner@example.org"]


# The saved password stays with its server


async def test_a_changed_server_needs_the_password_again(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp, username="home@example.org", password=SECRET)

    moved = await api.put(
        "/install/mail", json={**smtp.mailbox(), "host": "smtp.elsewhere.org", "username": "home@example.org"}
    )
    unsafe = await api.put("/install/mail", json={**smtp.mailbox(), "port": 25, "username": "home@example.org"})
    again = await connect(api, smtp, host="localhost", username="home@example.org", password=SECRET)

    assert (moved.status_code, moved.json()["code"], moved.json()["params"]) == (
        400,
        "invalid_mailbox",
        {"field": "password"},
    )
    assert unsafe.status_code == 400
    assert (again["host"], again["password_set"]) == ("localhost", True)


async def test_a_password_that_no_longer_opens_says_so(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp, username="home@example.org", password=SECRET)
    other = FernetSecretBox.of("another-install-key-of-32-characters")
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(InstallSettingDB).values(secret=other.seal(SECRET, bound_to=MAILBOX_SEAL)))
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)

    status = await ok(await api.get("/install/mail/status"))
    await (await postman(container)).deliver_due()
    [logged] = await ok(await api.get("/install/mail/messages"))

    assert status["health"] == "failed"
    assert "enter the password again" in status["error"]
    assert (logged["state"], logged["attempts"][0]["reason"]) == ("failed", "unreadable")
    assert smtp.messages == []


async def test_a_mail_that_no_longer_opens_is_not_sent(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    other = FernetSecretBox.of("another-install-key-of-32-characters")
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(MailDB).values(content=other.seal("text", bound_to="x")))

    await (await postman(container)).deliver_due()

    [logged] = await ok(await api.get("/install/mail/messages"))
    assert (logged["state"], logged["attempts"][0]["reason"]) == ("failed", "unreadable")


# The journal


async def install_events(container: DishkaContainer) -> list[tuple[str, dict[str, Any]]]:
    async with (await uow_of(container)).query() as tx:
        rows = await tx.session.scalars(
            select(JournalEventDB)
            .where(
                JournalEventDB.type.in_(
                    ["install.mailbox_saved", "install.mailbox_removed", "install.mail_tested", "mail.resent"]
                )
            )
            .order_by(JournalEventDB.seq)
        )
        return [(row.type, row.payload) for row in rows]


async def test_every_change_of_the_mailbox_is_journalled_and_no_save_without_one(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await connect(api, smtp, from_name="Dacha")
    await connect(api, smtp, from_name="Dacha")
    test = await ok(await api.post("/install/mail:test", json={"to": "t@example.org"}))
    resent = await ok(await api.post(f"/install/mail/messages/{test['mail_id']}:resend"))
    await ok(await api.delete("/install/mail"), 204)

    events = await install_events(container)

    assert events[1:] == [
        ("install.mailbox_saved", {"changed": ["from_name"], "password_changed": False}),
        ("install.mail_tested", {"mail_id": test["mail_id"], "sent": True}),
        ("mail.resent", {"mail_id": resent["mail_id"], "sent": True}),
        ("install.mailbox_removed", {}),
    ]


async def test_a_test_without_an_address_goes_to_the_admins_own(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "admin@example.org"}), 202)
    await (await postman(container)).deliver_due()
    token = text_of(smtp.messages[-1]).split("/verify-email/")[1].split()[0]
    await ok(await api.post("/email-verifications:confirm", json={"token": token}))

    result = await ok(await api.post("/install/mail:test", json={}))

    assert result["ok"] is True
    assert smtp.messages[-1]["To"] == "admin@example.org"


async def test_a_sender_address_with_a_national_domain_sends(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp, from_address="home@почта.рф")

    result = await ok(await api.post("/install/mail:test", json={"to": "someone@example.org"}))

    assert (result["ok"], result["error"]) == (True, None)
    assert smtp.messages[-1]["From"] == "Penaria <home@xn--80a1acny.xn--p1ai>"


# Limits and refusals


async def test_mailing_invitations_again_and_again_is_slowed_down(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp)
    ids = await make_home(api)
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}

    statuses = [
        (
            await api.post(
                f"/homes/{ids['home']}/invitations", json={"role_id": roles["family"], "email": f"p{n}@example.org"}
            )
        ).status_code
        for n in range(6)
    ]

    assert statuses == [201] * 5 + [429]


async def test_an_unknown_mail_is_not_resent(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await connect(api, smtp)

    response = await api.post("/install/mail/messages/01900000-0000-7000-8000-000000000000:resend")

    assert (response.status_code, response.json()["code"]) == (404, "mail_not_found")


async def test_nothing_is_resent_once_mail_is_off(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    test = await ok(await api.post("/install/mail:test", json={"to": "t@example.org"}))
    await ok(await api.delete("/install/mail"), 204)

    response = await api.post(f"/install/mail/messages/{test['mail_id']}:resend")

    assert (response.status_code, response.json()["code"]) == (409, "mail_off")


# What is forgotten


async def test_the_sweep_forgets_old_mail_and_expired_links_but_keeps_what_waits(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/install/mail:test", json={"to": "old@example.org"}))
    smtp.refuse = "451 4.3.0 Try again later"
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    await (await postman(container)).deliver_due()
    now = datetime.now(UTC)
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(
            update(MailDB).where(MailDB.kind == "test").values(created_at=now - timedelta(days=31))
        )
        # Waiting for a retry, though its link ended: it is not sent again, but nothing is lost meanwhile.
        await tx.session.execute(
            update(MailDB).where(MailDB.kind == "email_verification").values(expires_at=now - timedelta(seconds=1))
        )
        await tx.session.execute(update(AccountLinkDB).values(expires_at=now - timedelta(seconds=1)))

    await (await postman(container)).sweep()

    rows = await mail_rows(container)
    async with (await uow_of(container)).query() as tx:
        links = list(await tx.session.scalars(select(AccountLinkDB)))
        attempts = list(await tx.session.scalars(select(MailAttemptDB.mail_id)))
    assert [(row.kind, row.state, row.content is not None) for row in rows] == [("email_verification", "queued", True)]
    assert set(attempts) == {rows[0].id}
    assert links == []


async def test_a_pass_stops_at_a_mailbox_that_cannot_be_reached(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "one@example.org"}), 202)
    await ok(await api.post("/me/email", json={"email": "two@example.org"}), 202)
    await smtp.stop()

    more = await (await postman(container)).deliver_due()

    async with (await uow_of(container)).query() as tx:
        attempts = list(await tx.session.scalars(select(MailAttemptDB.reason)))
    assert (more, attempts) == (False, ["connect"])


async def test_a_full_pass_says_more_may_be_due(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(postman_module, "BATCH", 2)
    await connect(api, smtp)
    for n in range(3):
        await ok(await api.post("/install/mail:test", json={"to": f"t{n}@example.org"}))
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(MailDB).values(state="queued", next_attempt_at=datetime.now(UTC), attempts=0))
    sender = await postman(container)

    first = await sender.deliver_due()
    second = await sender.deliver_due()

    assert (first, second, len(smtp.messages)) == (True, False, 6)
