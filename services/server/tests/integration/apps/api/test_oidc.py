"""Signing in with an OpenID Connect provider through the HTTP API, against a provider in the test (sign-in.md, 18)."""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from joserfc.jwk import OctKey
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import func, select, update

from penaria.features.support.identity.infra.orm import OidcFlowDB, SignInFailureDB, UserDB
from tests.integration.apps.api.test_people import age_sign_ins, invite, last_events, make_home, member, ok
from tests.integration.apps.api.test_totp import enrol, forget_used_codes, now_code
from tests.integration.conftest import PUBLIC_URL
from tests.integration.helpers import NewClient, add_second_factor, from_address, uow_of
from tests.oidc import CLIENT_ID, CLIENT_SECRET, FakeOidc

pytestmark = pytest.mark.integration

CALLBACK = "/auth/oidc/callback"


@pytest.fixture
async def provider() -> AsyncIterator[FakeOidc]:
    fake = FakeOidc()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def allow_sign_up() -> bool:
    """``PENARIA_AUTH__OIDC__ALLOW_SIGN_UP`` of the test: off, as by default."""
    return False


@pytest.fixture
def operator_oidc(provider: FakeOidc, allow_sign_up: bool) -> dict[str, Any]:
    return {
        "issuer": provider.issuer,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "allow_sign_up": allow_sign_up,
        "name": "Authentik",
    }


async def start(client: httpx.AsyncClient, path: str, **body: Any) -> str:
    """Start a flow; the provider's address the browser is sent to."""
    started = await ok(await client.post(path, json=body))
    assert set(started) == {"url"}
    return str(started["url"])


async def start_sign_in(client: httpx.AsyncClient, **body: Any) -> str:
    return await start(client, "/auth/oidc:sign-in", locale="en", **body)


async def back(client: httpx.AsyncClient, query: dict[str, str]) -> httpx.Response:
    """The provider sends the browser back to the callback."""
    response = await client.get(CALLBACK, params=query)
    assert response.status_code == 303, response.text
    return response


async def sign_in(client: httpx.AsyncClient, provider: FakeOidc, subject: str, **claims: Any) -> httpx.Response:
    return await back(client, provider.authorize(await start_sign_in(client), subject=subject, **claims))


def location(response: httpx.Response) -> str:
    return response.headers["location"]


async def link(api: httpx.AsyncClient, provider: FakeOidc, subject: str, **claims: Any) -> httpx.Response:
    url = await start(api, "/me/external-identities:link")
    return await back(api, provider.authorize(url, subject=subject, **claims))


async def open_flows(container: DishkaContainer) -> int:
    async with (await uow_of(container)).query() as tx:
        return int(await tx.session.scalar(select(func.count()).select_from(OidcFlowDB)) or 0)


async def accounts(container: DishkaContainer) -> int:
    async with (await uow_of(container)).query() as tx:
        return int(await tx.session.scalar(select(func.count()).select_from(UserDB)) or 0)


# What the web app is told


async def test_the_sign_in_page_learns_the_providers_name(anonymous: httpx.AsyncClient) -> None:
    assert await ok(await anonymous.get("/auth/config")) == {"oidc": {"name": "Authentik"}}


async def test_the_authorization_request_carries_pkce_state_nonce_and_the_callback(
    anonymous: httpx.AsyncClient, provider: FakeOidc
) -> None:
    url = await start_sign_in(anonymous)

    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(f"{provider.issuer}/authorize?")
    assert query.keys() >= {"state", "nonce", "code_challenge"}
    assert (query["redirect_uri"], query["scope"], query["code_challenge_method"]) == (
        f"{PUBLIC_URL}/api/v1/auth/oidc/callback",
        "openid profile email",
        "S256",
    )


# Signing in


async def test_a_linked_identity_signs_in_and_comes_back_where_it_started(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await link(api, provider, "alex-at-provider")
    browser = new_client()

    url = await start_sign_in(browser, return_to="/account")
    response = await back(browser, provider.authorize(url, subject="alex-at-provider"))

    assert location(response) == "/account"
    assert (await ok(await browser.get("/me")))["username"] == "owner"
    assert (await last_events(container, 1))[0] == (
        "account.signed_in",
        "user",
        {"user_id": "uuid", "session_id": "uuid", "ip": "127.0.0.1", "external_identity_id": "uuid"},
    )


async def test_an_unlinked_identity_needs_an_invitation_when_sign_up_is_off(
    anonymous: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer, setup_token: str
) -> None:
    before = await accounts(container)

    response = await sign_in(anonymous, provider, "stranger", email="s@example.org", email_verified=True)

    assert location(response) == "/sign-in/external?problem=invitation_required"
    assert "penaria_session" not in response.cookies
    assert await accounts(container) == before
    assert (await anonymous.get("/me")).status_code == 401


@pytest.mark.parametrize("allow_sign_up", [True])
async def test_with_sign_up_an_unlinked_identity_makes_an_account_from_its_claims(
    anonymous: httpx.AsyncClient, provider: FakeOidc, setup_token: str, container: DishkaContainer
) -> None:
    response = await sign_in(
        anonymous,
        provider,
        "maria-1",
        preferred_username="Maria Petrova",
        name="Maria Petrova",
        email="Maria@Example.org",
        email_verified=True,
    )

    assert location(response) == "/"
    me = await ok(await anonymous.get("/me"))
    assert {key: me[key] for key in ("username", "display_name", "email", "locale", "install_admin")} == {
        "username": "maria.petrova",
        "display_name": "Maria Petrova",
        "email": "maria@example.org",
        "locale": "en",
        "install_admin": False,
    }
    methods = await ok(await anonymous.get("/me/sign-in-methods"))
    assert (methods["password"], [i["email"] for i in methods["external_identities"]]) == (
        False,
        ["Maria@Example.org"],
    )
    assert (await last_events(container, 2))[0] == (
        "account.created",
        "user",
        {"user_id": "uuid", "external_identity_id": "uuid", "issuer": provider.issuer},
    )


@pytest.mark.parametrize("allow_sign_up", [True])
async def test_an_unverified_email_is_not_taken_and_a_taken_username_gets_a_number(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    browser = new_client()

    await sign_in(browser, provider, "other-owner", preferred_username="owner", email="o@example.org")

    me = await ok(await browser.get("/me"))
    assert (me["username"], me["email"]) == ("owner-2", None)


@pytest.mark.parametrize("allow_sign_up", [True])
async def test_the_same_identity_signs_in_to_the_same_account_and_never_by_email(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    first, second = new_client(), new_client()
    await sign_in(first, provider, "sub-1", preferred_username="kim")
    accounts_after_first = await accounts(container)

    await sign_in(second, provider, "sub-1", preferred_username="someone-else")

    assert (await ok(await second.get("/me")))["username"] == "kim"
    assert await accounts(container) == accounts_after_first


# Checks of the flow and the token


async def test_a_state_works_once(api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer) -> None:
    await link(api, provider, "alex")
    url = await start_sign_in(api)
    binding = api.cookies["penaria_oidc"]
    query = provider.authorize(url, subject="alex")
    first = await back(api, query)
    # The same browser, cookie and all, brings the same state back.
    api.cookies.set("penaria_oidc", binding, path="/api/v1/auth/oidc")

    replayed = await back(api, provider.authorize(url, subject="alex") | {"state": query["state"]})

    assert location(first) == "/"
    assert location(replayed) == "/sign-in/external?problem=expired"
    assert await open_flows(container) == 0


async def test_a_callback_without_a_state_finds_no_flow(anonymous: httpx.AsyncClient) -> None:
    assert location(await back(anonymous, {"code": "x"})) == "/sign-in/external?problem=expired"


async def test_a_callback_in_another_browser_finds_no_flow(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    attacker = new_client()
    # The attacker starts a sign-in and slips their callback to the owner's browser (login CSRF).
    query = provider.authorize(await start_sign_in(attacker), subject="attacker")

    response = await back(new_client(), query)

    assert location(response) == "/sign-in/external?problem=expired"


async def test_an_expired_flow_is_refused(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await link(api, provider, "alex")
    url = await start_sign_in(api)
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(OidcFlowDB).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    response = await back(api, provider.authorize(url, subject="alex"))

    assert location(response) == "/sign-in/external?problem=expired"


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "another-client"},
        {"exp": int(datetime.now(UTC).timestamp()) - 3600},
        {"nonce": "not-the-nonce"},
        {"iss": "https://elsewhere.example"},
        {"aud": [CLIENT_ID, "another-client"]},
    ],
    ids=["wrong audience", "expired", "wrong nonce", "wrong issuer", "several audiences, issued to another"],
)
async def test_an_id_token_that_does_not_check_out_signs_nobody_in(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, claims: dict[str, Any]
) -> None:
    await link(api, provider, "alex")
    browser = new_client()

    response = await sign_in(browser, provider, "alex", **claims)

    assert location(response) == "/sign-in/external?problem=failed"
    assert (await browser.get("/me")).status_code == 401


async def test_a_token_signed_with_a_key_the_provider_does_not_publish_is_refused(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await link(api, provider, "alex")
    stranger_key = FakeOidc().keys[0]

    response = await sign_in(new_client(), provider, "alex", sign_with=stranger_key)

    assert location(response) == "/sign-in/external?problem=failed"


async def test_a_token_for_several_clients_issued_to_this_one_signs_in(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await link(api, provider, "alex")

    response = await sign_in(new_client(), provider, "alex", aud=[CLIENT_ID, "another-client"], azp=CLIENT_ID)

    assert location(response) == "/"


async def test_a_token_signed_with_the_client_secret_is_refused(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await link(api, provider, "alex")

    response = await sign_in(new_client(), provider, "alex", sign_with=OctKey.import_key(CLIENT_SECRET))

    assert location(response) == "/sign-in/external?problem=failed"


async def test_a_provider_naming_another_issuer_is_not_used(anonymous: httpx.AsyncClient, provider: FakeOidc) -> None:
    provider.advertised_issuer = "https://elsewhere.example"

    response = await anonymous.post("/auth/oidc:sign-in", json={"locale": "en"})

    assert (response.status_code, response.json()["code"]) == (503, "oidc_unavailable")


async def test_a_disabled_account_is_not_signed_in_and_the_attempt_is_journalled(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await link(api, provider, "alex")
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(UserDB).values(disabled_at=datetime.now(UTC)))

    response = await sign_in(new_client(), provider, "alex")

    assert location(response) == "/sign-in/external?problem=account_disabled"
    assert "penaria_session" not in response.cookies
    assert (await last_events(container, 1))[0] == (
        "account.sign_in_failed",
        "system",
        {"user_id": "uuid", "ip": "127.0.0.1", "reason": "account_disabled"},
    )


async def test_a_rotated_key_is_fetched_again(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await link(api, provider, "alex")
    provider.rotate()
    browser = new_client()

    response = await sign_in(browser, provider, "alex")

    assert location(response) == "/"
    assert (await browser.get("/me")).status_code == 200


async def test_the_provider_refusing_the_person_ends_the_flow(anonymous: httpx.AsyncClient) -> None:
    url = await start_sign_in(anonymous)
    state = parse_qs(urlsplit(url).query)["state"][0]

    response = await back(anonymous, {"state": state, "error": "access_denied"})

    assert location(response) == "/sign-in/external?problem=failed"


async def test_a_provider_that_cannot_be_reached_is_said_so(anonymous: httpx.AsyncClient, provider: FakeOidc) -> None:
    provider.up = False

    response = await anonymous.post("/auth/oidc:sign-in", json={"locale": "en"})

    assert (response.status_code, response.json()["code"]) == (503, "oidc_unavailable")


async def test_a_return_to_another_site_goes_home_instead(api: httpx.AsyncClient, provider: FakeOidc) -> None:
    await link(api, provider, "alex")

    url = await start_sign_in(api, return_to="//evil.example/path")
    response = await back(api, provider.authorize(url, subject="alex"))

    assert location(response) == "/"


async def test_an_address_holds_a_bounded_number_of_open_sign_ins(new_client: NewClient, app: FastAPI) -> None:
    browser = from_address(new_client, app, "203.0.113.9")
    statuses = [(await browser.post("/auth/oidc:sign-in", json={"locale": "en"})).status_code for _ in range(10)]
    refused = await browser.post("/auth/oidc:sign-in", json={"locale": "en"})

    assert statuses == [200] * 10
    assert (refused.status_code, refused.json()["code"], refused.json()["params"]) == (
        429,
        "too_many_attempts",
        {"retry_after_seconds": 600},
    )


# The second factor


async def test_an_account_with_an_authenticator_app_is_asked_for_its_code_after_the_provider(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    secret, _ = await enrol(api)
    await forget_used_codes(container)
    await link(api, provider, "alex")
    browser = new_client()

    response = await sign_in(browser, provider, "alex")

    page = urlsplit(location(response))
    fragment = {key: values[0] for key, values in parse_qs(page.fragment).items()}
    assert (page.path, page.query) == ("/sign-in", "next=%2F")
    assert fragment.keys() == {"second-factor", "until"}
    assert "penaria_session" not in response.cookies
    signed_in = await browser.post(
        "/sign-in/second-factor", json={"token": fragment["second-factor"], "code": now_code(secret)}
    )
    assert signed_in.status_code == 200
    assert (await ok(await browser.get("/me")))["username"] == "owner"


@pytest.mark.parametrize("allow_sign_up", [True])
async def test_an_owner_who_signs_in_with_the_provider_must_add_a_second_factor(
    anonymous: httpx.AsyncClient, provider: FakeOidc, setup_token: str
) -> None:
    await sign_in(anonymous, provider, "new-owner", preferred_username="nina")
    await make_home(anonymous)

    state = await ok(await anonymous.get("/me/second-factor"))

    assert (state["required"], state["missing"]) == (True, True)


# Linking and unlinking


async def test_linking_needs_a_recent_sign_in(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    await age_sign_ins(container)

    response = await api.post("/me/external-identities:link", json={})

    assert (response.status_code, response.json()["code"]) == (403, "recent_sign_in_required")


async def test_linking_shows_the_identity_and_is_journalled(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    response = await link(api, provider, "alex", email="alex@example.org")

    assert location(response) == "/account"
    methods = await ok(await api.get("/me/sign-in-methods"))
    assert methods["password"] is True
    assert [identity["email"] for identity in methods["external_identities"]] == ["alex@example.org"]
    [event] = await last_events(container, 1)
    assert event == (
        "account.external_identity_linked",
        "user",
        {"user_id": "uuid", "external_identity_id": "uuid", "issuer": provider.issuer},
    )


async def two_links(api: httpx.AsyncClient, provider: FakeOidc, first: str, second: str) -> httpx.Response:
    """Two links started at once, as from two tabs: the second completes first; the first one's callback."""
    first_url = await start(api, "/me/external-identities:link")
    first_binding = api.cookies["penaria_oidc"]
    await link(api, provider, second)
    api.cookies.set("penaria_oidc", first_binding, path="/api/v1/auth/oidc")
    return await back(api, provider.authorize(first_url, subject=first))


async def test_a_link_finishing_after_the_same_identity_was_linked_changes_nothing(
    api: httpx.AsyncClient, provider: FakeOidc
) -> None:
    response = await two_links(api, provider, "alex", "alex")

    assert location(response) == "/account"
    assert len((await ok(await api.get("/me/sign-in-methods")))["external_identities"]) == 1


async def test_a_link_finishing_after_another_identity_was_linked_is_refused(
    api: httpx.AsyncClient, provider: FakeOidc
) -> None:
    response = await two_links(api, provider, "alex", "bob")

    assert location(response) == "/sign-in/external?problem=already_linked"


async def test_an_identity_linked_to_another_account_is_not_linked_again(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await link(api, provider, "alex")
    maria = await member_account(api, new_client)

    response = await link(maria, provider, "alex")

    assert location(response) == "/sign-in/external?problem=identity_taken"


async def test_an_account_links_one_identity_at_the_provider(api: httpx.AsyncClient, provider: FakeOidc) -> None:
    await link(api, provider, "alex")

    response = await api.post("/me/external-identities:link", json={})

    assert (response.status_code, response.json()["code"]) == (409, "identity_already_linked")


async def test_unlinking_ends_signing_in_with_the_identity(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await link(api, provider, "alex")
    [identity] = (await ok(await api.get("/me/sign-in-methods")))["external_identities"]

    await ok(await api.delete(f"/me/external-identities/{identity['id']}"), 204)

    response = await sign_in(new_client(), provider, "alex")
    assert location(response) == "/sign-in/external?problem=invitation_required"


@pytest.mark.parametrize("allow_sign_up", [True])
async def test_the_last_way_to_sign_in_is_not_unlinked(anonymous: httpx.AsyncClient, provider: FakeOidc) -> None:
    await sign_in(anonymous, provider, "only-provider", preferred_username="lena")
    [identity] = (await ok(await anonymous.get("/me/sign-in-methods")))["external_identities"]

    response = await anonymous.delete(f"/me/external-identities/{identity['id']}")

    assert (response.status_code, response.json()["code"]) == (409, "last_sign_in_method")


async def test_unlinking_needs_a_recent_sign_in(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await link(api, provider, "alex")
    [identity] = (await ok(await api.get("/me/sign-in-methods")))["external_identities"]
    await age_sign_ins(container)

    response = await api.delete(f"/me/external-identities/{identity['id']}")

    assert (response.status_code, response.json()["code"]) == (403, "recent_sign_in_required")


async def test_another_accounts_identity_is_not_unlinked(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await link(api, provider, "alex")
    [identity] = (await ok(await api.get("/me/sign-in-methods")))["external_identities"]
    maria = await member_account(api, new_client)

    response = await maria.delete(f"/me/external-identities/{identity['id']}")

    assert (response.status_code, response.json()["code"]) == (404, "external_identity_not_found")


async def test_unlinking_is_journalled(api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer) -> None:
    await link(api, provider, "alex")
    [identity] = (await ok(await api.get("/me/sign-in-methods")))["external_identities"]

    await ok(await api.delete(f"/me/external-identities/{identity['id']}"), 204)

    assert (await last_events(container, 1))[0] == (
        "account.external_identity_unlinked",
        "user",
        {"user_id": "uuid", "external_identity_id": "uuid"},
    )


async def test_a_link_started_in_a_session_that_ended_since_links_nothing(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    url = await start(api, "/me/external-identities:link")
    # The owner signs out (as "sign out everywhere else" would end a stolen session) before the provider answers.
    await ok(await api.post("/sign-out"), 204)

    response = await back(api, provider.authorize(url, subject="intruder"))

    assert location(response) == "/sign-in/external?problem=expired"
    assert location(await sign_in(new_client(), provider, "intruder")) == (
        "/sign-in/external?problem=invitation_required"
    )


@pytest.mark.parametrize("allow_sign_up", [True])
async def test_an_account_made_through_the_provider_may_remove_its_only_passkey(
    anonymous: httpx.AsyncClient, provider: FakeOidc, setup_token: str
) -> None:
    await sign_in(anonymous, provider, "kim-1", preferred_username="kim")
    await add_second_factor(anonymous, PUBLIC_URL)
    [passkey] = await ok(await anonymous.get("/me/passkeys"))

    await ok(await anonymous.delete(f"/me/passkeys/{passkey['id']}"), 204)


@pytest.mark.parametrize("allow_sign_up", [True])
async def test_a_verified_email_another_account_has_is_not_taken(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(UserDB).where(UserDB.username == "owner").values(email="alex@example.org"))
    browser = new_client()

    await sign_in(browser, provider, "kim-1", preferred_username="kim", email="alex@example.org", email_verified=True)

    assert (await ok(await browser.get("/me")))["email"] is None


# Confirming it is you


async def test_signing_in_at_the_provider_again_makes_the_sign_in_recent(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await link(api, provider, "alex")
    await age_sign_ins(container)

    url = await start(api, "/me/reauthenticate/oidc", return_to="/homes/x/people")
    response = await back(api, provider.authorize(url, subject="alex"))

    query = parse_qs(urlsplit(url).query)
    assert (query["prompt"], query["max_age"]) == (["login"], ["0"])
    assert location(response) == "/homes/x/people"
    assert (await api.post("/me/totp")).status_code == 200
    assert (await last_events(container, 1))[0] == (
        "account.reauthenticated",
        "user",
        {"user_id": "uuid", "session_id": "uuid", "external_identity_id": "uuid"},
    )


async def test_a_provider_that_does_not_sign_the_person_in_again_confirms_nothing(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await link(api, provider, "alex")
    await age_sign_ins(container)

    url = await start(api, "/me/reauthenticate/oidc")
    response = await back(api, provider.authorize(url, subject="alex", auth_time=int(time.time()) - 3600))

    assert location(response) == "/sign-in/external?problem=failed"
    assert (await api.post("/me/totp")).json()["code"] == "recent_sign_in_required"


async def test_an_account_without_an_identity_cannot_confirm_with_the_provider(api: httpx.AsyncClient) -> None:
    response = await api.post("/me/reauthenticate/oidc", json={})

    assert (response.status_code, response.json()["code"]) == (404, "external_identity_not_found")


async def test_a_wrong_code_confirms_nothing_and_counts(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await enrol(api)
    await forget_used_codes(container)
    await link(api, provider, "alex")

    wrong = await api.post("/me/reauthenticate/oidc", json={"code": "000000"})

    assert (wrong.status_code, wrong.json()["code"]) == (400, "wrong_code")
    async with (await uow_of(container)).query() as tx:
        counted = await tx.session.scalar(
            select(SignInFailureDB.count).where(SignInFailureDB.key.like("second-factor:%"))
        )
    assert counted == 1


async def test_confirming_with_another_identity_is_refused_and_journalled(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await link(api, provider, "alex")
    await age_sign_ins(container)

    url = await start(api, "/me/reauthenticate/oidc")
    response = await back(api, provider.authorize(url, subject="someone-else"))

    assert location(response) == "/sign-in/external?problem=wrong_account"
    assert (await api.post("/me/totp")).json()["code"] == "recent_sign_in_required"
    assert (await last_events(container, 1))[0] == (
        "account.sign_in_failed",
        "system",
        {"user_id": "uuid", "ip": "127.0.0.1", "reason": "wrong_account"},
    )


async def test_confirming_with_the_provider_asks_for_the_apps_code_too(
    api: httpx.AsyncClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    secret, _ = await enrol(api)
    await forget_used_codes(container)
    await link(api, provider, "alex")

    without = await api.post("/me/reauthenticate/oidc", json={})
    with_code = await api.post("/me/reauthenticate/oidc", json={"code": now_code(secret)})

    assert (without.status_code, without.json()["code"]) == (400, "second_factor_code_required")
    assert with_code.status_code == 200


# Invitations


async def test_an_invitation_makes_an_account_from_an_unlinked_identity_even_without_sign_up(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    browser = new_client()

    url = await start(browser, "/auth/oidc:accept-invitation", token=token, locale="ru")
    response = await back(browser, provider.authorize(url, subject="maria", name="Мария", preferred_username="мария"))

    assert location(response) == "/"
    me = await ok(await browser.get("/me"))
    assert (me["username"], me["display_name"], me["locale"]) == ("мария", "Мария", "ru")
    created = [event for event in await last_events(container, 6) if event[0] == "account.created"]
    assert created == [
        (
            "account.created",
            "user",
            {"user_id": "uuid", "external_identity_id": "uuid", "issuer": provider.issuer, "invitation_id": "uuid"},
        )
    ]
    assert [home["name"] for home in await ok(await browser.get("/homes"))] == ["Country house"]
    assert (await new_client().post("/invitations:preview", json={"token": token})).json()["code"] == (
        "invitation_used"
    )


async def test_a_linked_identity_accepts_an_invitation_with_its_account(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    maria = await member_account(api, new_client)
    await link(maria, provider, "maria")
    second = await make_home(api, "Dacha")
    token = await invite(api, second["home"], "guest")
    browser = new_client()

    url = await start(browser, "/auth/oidc:accept-invitation", token=token, locale="en")
    await back(browser, provider.authorize(url, subject="maria"))

    assert (await ok(await browser.get("/me")))["username"] == "maria"
    assert sorted(home["name"] for home in await ok(await browser.get("/homes"))) == ["Dacha", "Flat"]


async def test_an_invitation_that_cannot_be_accepted_makes_no_account(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    browser = new_client()
    url = await start(browser, "/auth/oidc:accept-invitation", token=token, locale="en")
    [pending] = await ok(await api.get(f"/homes/{ids['home']}/invitations"))
    await ok(await api.delete(f"/homes/{ids['home']}/invitations/{pending['id']}"), 204)
    before = await accounts(container)

    response = await back(browser, provider.authorize(url, subject="late"))

    assert location(response) == "/sign-in/external?problem=invitation_unusable"
    assert await accounts(container) == before


async def test_an_account_with_an_authenticator_app_signs_in_before_it_accepts(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc, container: DishkaContainer
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    maria = await member_account(api, new_client)
    await enrol(maria)
    await forget_used_codes(container)
    await link(maria, provider, "maria")
    dacha = await make_home(api, "Dacha")
    token = await invite(api, dacha["home"], "guest")
    browser = new_client()

    url = await start(browser, "/auth/oidc:accept-invitation", token=token, locale="en")
    response = await back(browser, provider.authorize(url, subject="maria"))

    assert location(response) == "/sign-in/external?problem=sign_in_first"
    assert [home["name"] for home in await ok(await maria.get("/homes"))] == ["Flat"]
    assert (await ok(await new_client().post("/invitations:preview", json={"token": token})))["home"]["name"] == "Dacha"


async def test_the_inviter_cannot_accept_their_own_invitation_through_the_provider(
    api: httpx.AsyncClient, new_client: NewClient, provider: FakeOidc
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    await link(api, provider, "alex")
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    browser = new_client()

    url = await start(browser, "/auth/oidc:accept-invitation", token=token, locale="en")
    response = await back(browser, provider.authorize(url, subject="alex"))

    assert location(response) == "/sign-in/external?problem=invitation_unusable"
    assert (await ok(await new_client().post("/invitations:preview", json={"token": token})))["role"]["preset"] == (
        "family"
    )


async def test_an_unknown_invitation_starts_no_flow(anonymous: httpx.AsyncClient, container: DishkaContainer) -> None:
    response = await anonymous.post("/auth/oidc:accept-invitation", json={"token": "not-a-token", "locale": "en"})

    assert (response.status_code, response.json()["code"]) == (404, "invitation_not_found")
    assert await open_flows(container) == 0


async def member_account(api: httpx.AsyncClient, new_client: NewClient) -> httpx.AsyncClient:
    """Maria, a family member of a new home of the owner's, signed in with her password."""
    home = await make_home(api, "Flat")
    return await member(api, new_client, home["home"], "family", "maria")
