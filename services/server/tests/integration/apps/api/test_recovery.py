"""Getting back into an account through the HTTP API: email, reset links by email, by an admin and by the operator."""

import re
from typing import Any

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import select

from penaria.apps.api.settings import Settings
from penaria.apps.cli.__main__ import reset_password as operator_reset
from penaria.apps.cli.settings import Settings as CliSettings
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.platform.infra.orm import JournalEventDB
from tests.authenticator import Authenticator
from tests.integration.apps.api.test_people import CHOSEN, age_sign_ins, make_home, member, ok
from tests.integration.conftest import OWNER, PUBLIC_URL
from tests.integration.helpers import NewClient, add_passkey, uow_of
from tests.smtp import FakeSmtp, html_of, text_of

pytestmark = pytest.mark.integration

FRESH = "a fresh new passphrase"
RESET_LINK = re.compile(re.escape(f"{PUBLIC_URL}/reset-password/") + r"([\w-]+)")
VERIFY_LINK = re.compile(re.escape(f"{PUBLIC_URL}/verify-email/") + r"([\w-]+)")


async def connect(api: httpx.AsyncClient, smtp: FakeSmtp) -> None:
    await ok(await api.put("/install/mail", json=smtp.mailbox()))


async def deliver(container: DishkaContainer) -> None:
    await (await container.container.get(Postman)).deliver_due()


async def confirm_email(api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, email: str) -> None:
    """Give the signed-in account a confirmed email, the way its person does."""
    await ok(await api.post("/me/email", json={"email": email}), 202)
    await deliver(container)
    token = link_in(smtp, VERIFY_LINK)
    await ok(await api.post("/email-verifications:confirm", json={"token": token}))


def link_in(smtp: FakeSmtp, pattern: re.Pattern[str]) -> str:
    """The token of the link in the latest email."""
    found = pattern.search(text_of(smtp.messages[-1]))
    assert found is not None, text_of(smtp.messages[-1])
    return found.group(1)


def token_of(url: str) -> str:
    found = RESET_LINK.fullmatch(url)
    assert found is not None, url
    return found.group(1)


async def journal(container: DishkaContainer, prefix: str) -> list[tuple[str, dict[str, Any]]]:
    async with (await uow_of(container)).query() as tx:
        rows = await tx.session.scalars(
            select(JournalEventDB).where(JournalEventDB.type.like(f"{prefix}%")).order_by(JournalEventDB.seq)
        )
        return [(row.type, row.payload) for row in rows]


# Email


async def test_an_address_becomes_the_accounts_once_its_link_is_opened(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    await connect(api, smtp)

    pending = await ok(await api.post("/me/email", json={"email": " Owner@Example.org "}), 202)
    before = await ok(await api.get("/me"))
    await deliver(container)
    confirmed = await ok(
        await anonymous.post("/email-verifications:confirm", json={"token": link_in(smtp, VERIFY_LINK)})
    )

    assert pending["email"] == "owner@example.org"
    assert before["email"] is None
    assert confirmed == {"email": "owner@example.org"}
    assert (await ok(await api.get("/me")))["email"] == "owner@example.org"
    assert smtp.messages[-1]["Subject"] == "Confirm your email for Penaria"
    assert "The link works for 24 hours, once." in text_of(smtp.messages[-1])


async def test_a_confirmation_link_works_once(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    await deliver(container)
    token = link_in(smtp, VERIFY_LINK)
    await ok(await api.post("/email-verifications:confirm", json={"token": token}))

    again = await api.post("/email-verifications:confirm", json={"token": token})

    assert (again.status_code, again.json()["code"]) == (409, "account_link_used")


async def test_another_accounts_address_is_refused(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, new_client: NewClient
) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")

    response = await maria.post("/me/email", json={"email": "OWNER@example.org"})

    assert (response.status_code, response.json()["code"]) == (409, "email_taken")


async def test_an_email_needs_outgoing_mail(api: httpx.AsyncClient) -> None:
    response = await api.post("/me/email", json={"email": "owner@example.org"})

    assert (response.status_code, response.json()["code"]) == (409, "mail_off")


async def test_the_email_can_be_removed(api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")

    account = await ok(await api.delete("/me/email"))

    assert account["email"] is None


async def test_the_confirmation_email_speaks_the_accounts_language(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await ok(await api.patch("/me", json={"locale": "ru"}))

    await ok(await api.post("/me/email", json={"email": "owner@example.org"}), 202)
    await deliver(container)

    [message] = smtp.messages
    assert message["Subject"] == "Подтвердите почту для Penaria"
    assert "Ссылка действует 24 часа и срабатывает один раз." in text_of(message)
    assert 'lang="ru"' in html_of(message)


# Forgot password


async def test_a_reset_by_email_sets_a_new_password_and_ends_every_session(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")
    await ok(await anonymous.post("/password-reset:request", json={"login": "owner@example.org"}), 204)
    await deliver(container)
    token = link_in(smtp, RESET_LINK)

    preview = await ok(await anonymous.post("/password-reset:preview", json={"token": token}))
    await ok(await anonymous.post("/password-reset", json={"token": token, "new_password": FRESH}), 204)
    await deliver(container)

    assert preview == {"username": "owner", "display_name": "Owner", "passkeys": []}
    assert (await api.get("/me")).status_code == 401
    old = await anonymous.post("/sign-in", json={"username": "owner", "password": OWNER["password"]})
    new = await anonymous.post("/sign-in", json={"username": "owner", "password": FRESH})
    assert (old.status_code, new.status_code) == (401, 200)
    assert smtp.messages[-1]["Subject"] == "Your Penaria password was changed"
    assert [t for t, _ in await journal(container, "account.password_reset")] == ["account.password_reset"]


async def test_a_reset_keeps_the_passkeys_and_shows_them(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")
    await ok(await add_passkey(api, Authenticator(PUBLIC_URL), name="Phone"), 201)
    await ok(await anonymous.post("/password-reset:request", json={"login": "owner"}), 204)
    await deliver(container)
    token = link_in(smtp, RESET_LINK)

    preview = await ok(await anonymous.post("/password-reset:preview", json={"token": token}))
    await ok(await anonymous.post("/password-reset", json={"token": token, "new_password": FRESH}), 204)

    assert [passkey["name"] for passkey in preview["passkeys"]] == ["Phone"]
    owner = await ok(await anonymous.post("/sign-in", json={"username": "owner", "password": FRESH}))
    assert owner["username"] == "owner"
    assert [p["name"] for p in await ok(await anonymous.get("/me/passkeys"))] == ["Phone"]


@pytest.mark.parametrize("login", ["nobody", "nobody@example.org", "owner"])
async def test_forgot_password_answers_the_same_for_any_login(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, anonymous: httpx.AsyncClient, login: str
) -> None:
    await connect(api, smtp)

    response = await anonymous.post("/password-reset:request", json={"login": login})
    await deliver(container)

    # The owner has no confirmed email yet, so nobody is mailed either.
    assert (response.status_code, response.content) == (204, b"")
    assert smtp.messages == []


async def test_forgot_password_needs_outgoing_mail(anonymous: httpx.AsyncClient, api: httpx.AsyncClient) -> None:
    response = await anonymous.post("/password-reset:request", json={"login": "owner"})

    assert (response.status_code, response.json()["code"]) == (409, "mail_off")


async def test_asking_for_resets_again_and_again_is_slowed_down(
    api: httpx.AsyncClient, smtp: FakeSmtp, anonymous: httpx.AsyncClient
) -> None:
    await connect(api, smtp)

    statuses = [
        (await anonymous.post("/password-reset:request", json={"login": "owner"})).status_code for _ in range(7)
    ]

    assert statuses == [204] * 5 + [429] * 2


async def test_a_new_reset_link_replaces_the_one_before(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")
    await ok(await anonymous.post("/password-reset:request", json={"login": "owner"}), 204)
    await deliver(container)
    first = link_in(smtp, RESET_LINK)
    await ok(await anonymous.post("/password-reset:request", json={"login": "owner"}), 204)

    response = await anonymous.post("/password-reset:preview", json={"token": first})

    assert (response.status_code, response.json()["code"]) == (404, "account_link_not_found")


async def test_a_reset_link_works_once(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")
    await ok(await anonymous.post("/password-reset:request", json={"login": "owner"}), 204)
    await deliver(container)
    token = link_in(smtp, RESET_LINK)
    await ok(await anonymous.post("/password-reset", json={"token": token, "new_password": FRESH}), 204)

    again = await anonymous.post("/password-reset", json={"token": token, "new_password": "yet another passphrase"})

    assert (again.status_code, again.json()["code"]) == (409, "account_link_used")


async def test_a_reset_refuses_a_weak_password(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")
    await ok(await anonymous.post("/password-reset:request", json={"login": "owner"}), 204)
    await deliver(container)

    response = await anonymous.post(
        "/password-reset", json={"token": link_in(smtp, RESET_LINK), "new_password": "short"}
    )

    assert (response.status_code, response.json()["code"]) == (400, "weak_password")


async def test_an_unknown_reset_token_is_not_found(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.post("/password-reset:preview", json={"token": "x" * 43})

    assert (response.status_code, response.json()["code"]) == (404, "account_link_not_found")


# A home's admin


async def test_an_admin_makes_a_reset_link_for_a_member_without_mail(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    maria_id = (await ok(await maria.get("/me")))["id"]

    made = await ok(await api.post(f"/homes/{ids['home']}/members/{maria_id}:reset-link"), 201)
    await ok(await anonymous.post("/password-reset", json={"token": token_of(made["url"]), "new_password": FRESH}), 204)

    assert (await maria.get("/me")).status_code == 401
    signed_in = await anonymous.post("/sign-in", json={"username": "maria", "password": FRESH})
    assert signed_in.status_code == 200
    [(_, created)] = await journal(container, "account.reset_link_created")
    assert (created["by"], created["user_id"]) == ("admin", maria_id)


async def test_an_admin_cannot_reset_an_owner(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "maria")
    owner_id = (await ok(await api.get("/me")))["id"]

    response = await admin.post(f"/homes/{ids['home']}/members/{owner_id}:reset-link")

    assert (response.status_code, response.json()["code"]) == (403, "reset_not_allowed")


async def test_an_admin_cannot_reset_someone_who_owns_another_home(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    flat = await make_home(api, "Flat")
    admin = await member(api, new_client, flat["home"], "admin", "maria")
    dacha = await make_home(admin, "Dacha")
    ivan = await member(admin, new_client, dacha["home"], "family", "ivan")
    ivan_id = (await ok(await ivan.get("/me")))["id"]
    # Maria owns the dacha, where Ivan is family; Ivan owns a home of his own.
    await make_home(ivan, "Ivan's place")

    response = await admin.post(f"/homes/{dacha['home']}/members/{ivan_id}:reset-link")

    assert (response.status_code, response.json()["code"]) == (403, "reset_not_allowed")


async def test_a_member_who_does_not_manage_people_makes_no_reset_links(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    owner_id = (await ok(await api.get("/me")))["id"]

    response = await maria.post(f"/homes/{ids['home']}/members/{owner_id}:reset-link")

    assert (response.status_code, response.json()["code"]) == (403, "permission_denied")


async def test_a_reset_link_for_yourself_is_refused(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    owner_id = (await ok(await api.get("/me")))["id"]

    response = await api.post(f"/homes/{ids['home']}/members/{owner_id}:reset-link")

    assert (response.status_code, response.json()["code"]) == (403, "reset_not_allowed")


async def test_a_reset_link_needs_a_recent_sign_in(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    maria_id = (await ok(await maria.get("/me")))["id"]
    await age_sign_ins(container)

    response = await api.post(f"/homes/{ids['home']}/members/{maria_id}:reset-link")

    assert (response.status_code, response.json()["code"]) == (403, "recent_sign_in_required")


# The operator


async def test_the_operators_command_prints_a_reset_link_for_a_locked_out_owner(
    api: httpx.AsyncClient, settings: Settings, anonymous: httpx.AsyncClient, container: DishkaContainer
) -> None:
    cli = CliSettings.model_validate({"database": settings.database, "public_url": PUBLIC_URL})

    printed = await operator_reset(cli, "Owner")
    [url] = RESET_LINK.findall(printed)
    await ok(await anonymous.post("/password-reset", json={"token": url, "new_password": FRESH}), 204)

    assert printed.startswith("Open this link to set a new password for owner;")
    signed_in = await anonymous.post("/sign-in", json={"username": "owner", "password": FRESH})
    assert signed_in.status_code == 200
    [(_, created)] = await journal(container, "account.reset_link_created")
    assert created["by"] == "operator"


async def test_the_operators_command_names_an_unknown_account(settings: Settings, api: httpx.AsyncClient) -> None:
    cli = CliSettings.model_validate({"database": settings.database, "public_url": PUBLIC_URL})

    with pytest.raises(Exception, match="no account has the username 'nobody'"):
        await operator_reset(cli, "nobody")


# Invitations and notices by email


async def test_an_invitation_goes_by_email_in_the_homes_language(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    home = await ok(await api.post("/homes", json={"name": "Дача", "timezone": "Europe/Moscow", "locale": "ru"}), 201)
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{home['id']}/roles"))}

    created = await ok(
        await api.post(
            f"/homes/{home['id']}/invitations", json={"role_id": roles["family"], "email": "Ivan@Example.org"}
        ),
        201,
    )
    await deliver(container)

    [message] = smtp.messages
    assert created["emailed_to"] == "ivan@example.org"
    assert message["Subject"] == "Owner приглашает вас в «Дача» в Penaria"
    assert created["url"] in text_of(message)
    assert "роль — член семьи" in text_of(message)


async def test_an_invitation_by_email_needs_outgoing_mail(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}

    response = await api.post(
        f"/homes/{ids['home']}/invitations", json={"role_id": roles["family"], "email": "i@x.org"}
    )

    assert (response.status_code, response.json()["code"]) == (409, "mail_off")
    assert await ok(await api.get(f"/homes/{ids['home']}/invitations")) == []


async def test_a_changed_password_and_a_new_passkey_are_told_by_email(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")

    await ok(await api.post("/me/password", json={"current_password": OWNER["password"], "new_password": FRESH}), 204)
    await ok(await add_passkey(api, Authenticator(PUBLIC_URL), name="Laptop"), 201)
    await deliver(container)

    assert [m["Subject"] for m in smtp.messages[1:]] == [
        "Your Penaria password was changed",
        "A passkey was added to your Penaria account",
    ]
    assert "“Laptop”" in text_of(smtp.messages[-1])


async def test_no_notice_goes_to_an_account_without_email(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await connect(api, smtp)

    await ok(await api.post("/me/password", json={"current_password": OWNER["password"], "new_password": CHOSEN}), 204)
    await deliver(container)

    assert smtp.messages == []
