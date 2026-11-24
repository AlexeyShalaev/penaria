# Sign-in

- **Status:** accepted on 2026-11-24, with outgoing email configurable from the interface (section 9). Steps 1 to 3, then outgoing email with recovery, are built; what they settled is in sections 12 to 15.
- **Date:** 2026-11-24.
- **Scope:** how people, guests and devices prove who they are to a Penaria install:
  - the first start of an install;
  - accounts and sign-in methods;
  - sessions and tokens;
  - invitations and guest links;
  - recovery.

What a principal may do once known is [core-model.md](core-model.md), section 11. This document only decides who the principal is.

The decisions follow v0.3:
- the web uses a session cookie;
- integrations and devices use bearer tokens;
- sign-in is by passkey, or by password with a second factor for owners and admins;
- guest links expire and can be revoked in one click;
- an operator's OIDC provider is optional.

Decisions beyond v0.3 are marked **Decision** and listed in [Decisions](#11-decisions).

Not covered:
- **Hubs.** They pair with a one-time code and then use mTLS; this belongs to the hub design.
- **Signing in through the Telegram bot or mini app.** It reuses the account linking of section 4.4 and arrives with the bot.

## 1. Threats

A registry is an inventory of valuables with an address, and the smart-home part opens gates. The design defends against:

| Threat | Defence |
|---|---|
| Someone reaches a fresh install before its owner | The setup token (section 2) |
| Password guessing | Rate limits and backoff (section 7); passkeys first; a second factor for owners and admins |
| A stolen session cookie | `HttpOnly`, `Secure` and `SameSite=Lax` cookies; sessions bound to an idle timeout; every session visible and revocable |
| Cross-site requests | `SameSite=Lax`, plus an `Origin` check on every request that changes something |
| A leaked guest link or token | Only a hash of the secret is stored; expiry; one-click revoke; a guest sees only guest-visible things |
| Account enumeration | Sign-in and recovery answer the same for an unknown and a known account |

## 2. The first start

A fresh install has no users. **Decision: the server prints a one-time setup token to its log on first start. The setup screen asks for it before creating the owner account.**

A self-hosted install is often reachable from a network before its owner opens it. Letting the first visitor become the owner, as some home products do, hands the house to whoever comes first. A token in the log proves access to the machine. It costs one copy and paste, and the Compose quickstart prints the command to read it.

The setup screen creates:
- the first user;
- their first sign-in method, a passkey or a password;
- their first home, as the welcome screen does now.

The token is single-use. Restarting the server before setup prints a new one and invalidates the old.

**Upgrading from the single-user mode before sign-in.** The one local user that every request acted as becomes the account that setup completes. Its homes and history stay theirs.

## 3. Accounts

| Field | Meaning |
|---|---|
| `username` | Unique, case-insensitive, used to sign in. Chosen at setup or when accepting an invitation |
| `display_name` | What others in the home see |
| `email` | Optional. Used only when the install has SMTP (sign-in links, notifications). Unique when present |
| `locale` | The interface language |
| `disabled_at` | An admin of the install can disable an account. Every session ends at once |

**One account, many homes.** A person has one account however many homes they belong to: their flat, the country house, their parents' house where they are a guest of the family, a friend's flat for the weekend. Each home membership is a grant (core-model 11.2); sign-in never asks which home. The interface remembers the last home and switches between them in one tap. A home's list of people shows accounts, so the same person in two homes is recognisably the same.

**Decision: a username, with email optional.** Many self-hosted installs have no SMTP, and nothing should depend on one. Email adds recovery and notifications when SMTP is configured.

**Decision: the install has its own admin role, separate from home roles.** An install may host several households. Who may disable accounts, see every home's size or configure OIDC is a property of the install, not of a home. The setup account becomes the install admin and can make others admins.

## 4. Sign-in methods

### 4.1 Passkeys

Passkeys are WebAuthn credentials, built into phones and browsers. **Decision: passkeys are the first method the interface offers.** They cannot be phished, guessed or reused across sites, and family members already have them on their phones.

- A user may register several passkeys and name them, for example "Alexey's phone".
- The relying party id is the install's host name, taken from `PENARIA_PUBLIC_URL`.
- Library: `webauthn` (py_webauthn).

### 4.2 Passwords

For browsers and people without passkeys:
- At least 12 characters. No composition rules, as NIST SP 800-63B advises.
- Checked against a built-in list of the most common passwords.
- Stored as Argon2id hashes (`argon2-cffi`), re-hashed when the parameters change.

### 4.3 Second factor

TOTP, an authenticator app, with ten single-use recovery codes. Passkeys need no second factor.

**Decision: required for owners and install admins who sign in with a password, and optional for everyone else.**
- An owner who has only a password is asked to add TOTP or a passkey right after sign-in.
- An owner cannot act on owner-level commands until they do.

### 4.4 External identity (OIDC)

When the operator configures it (`PENARIA_AUTH__OIDC__*`: issuer, client id, secret), the sign-in screen offers "Sign in with <provider>". Examples are Authentik, Keycloak or a Google Workspace.

- An identity links to an account by the provider's `sub`, never by email alone.
- **Decision: a first sign-in through OIDC creates an account only if the operator allows it** (`..._ALLOW_SIGN_UP`, off by default). Otherwise the person needs an invitation first, and linking happens on acceptance.
- Library: `authlib`.

The same table of linked identities later holds Telegram accounts, linked from the bot.

## 5. Sessions

A browser signs in once and holds a session.

- **Storage.** The session is a random 256-bit token in a cookie named `penaria_session`, set `HttpOnly`, `Secure` when `PENARIA_PUBLIC_URL` is `https` (section 12), `SameSite=Lax` and `Path=/`. The server stores only a SHA-256 hash of the token, with the user (or, for a guest, the guest link's grant, section 6.2), the time created, the time last seen, the user agent and the IP address.
- **Lifetime.** **Decision:** a session ends after 30 days without use, and in any case after 180 days.
- **Sensitive commands need a recent sign-in, within 10 minutes:** adding a sign-in method, transferring ownership, changing roles. A session older than that asks for the passkey or password again.
- **Revocation.** The account page lists every session: device, place and last use. Each one can be ended. Signing out ends the current one, and disabling the account ends them all.
- **CSRF.** The server refuses any request that changes something if its `Origin` does not match `PENARIA_PUBLIC_URL`. The `SameSite=Lax` cookie does the rest. No CSRF tokens are needed, because the API takes only JSON.
- **Placement.** Sessions live in PostgreSQL, so any API replica can check them. A cache for that check can come with Redis later.

Every request resolves its actor once, in the API process, from the session cookie or a bearer token. That `Actor` reaches the use cases exactly as it does today; only the provider changes from "the local user" to "the request's principal".

## 6. Invitations, guest links and device tokens

### 6.1 Invitations

An admin of a home, or anyone with `members.manage`, creates an invitation. It carries:
- a role and a scope, as the grant will have;
- an expiry for the invitation itself (default 7 days);
- an expiry for the grant, when the role requires one.

It is shared as a link or a QR code holding a secret token. Only a hash of the token is stored.

- **Accepting.** Opening the link asks the person to sign in, or to create an account with a username and their first method. The grant is then created.
- **Single use.** **Decision:** an invitation can be used once. A second family member needs a second link.
- **Ownership.** The owner invitation of core-model section 3 is this same invitation with the role `owner` and the "leave when accepted" mark.
- **Revocation.** An invitation can be revoked until accepted. Accepting one is journalled (`grant.created`, with the invitation id).

### 6.2 Guest links

**A guest needs no account.** The link creates a grant to a `link` principal (core-model 11.2). Its expiry is required; the default for the guest preset is 3 days.

- Opening the link exchanges its token for a guest session, a cookie as in section 5. The guest session ends when the grant expires or is revoked.
- Revoking the grant ends every guest session made from it, in one click.
- **Decision: the link can be reused until it expires.** A QR code on the fridge should work for every guest of the weekend.
- Anything else a guest opens shows a screen that says so.

### 6.3 Device and integration tokens

A smart mirror or a script is a `device` principal, with grants like anyone else. For example: view and tasks on the house, and control of the hall light.

- It authenticates with `Authorization: Bearer pnr_<random>`. The prefix lets secret scanners recognise leaked tokens.
- The server stores only a hash of the token. The token is shown once, when created, and can be revoked.
- Device tokens never expire on their own. Each shows when it was last used.

## 7. Abuse

- **Rate limits.** Sign-in, setup, invitation acceptance and TOTP checks are limited per account and per IP address: 5 failures, then a doubling delay up to 15 minutes. The limit lives in PostgreSQL, or in Redis when the install runs several API replicas.
- **The same answer for every failure.** Sign-in and recovery never reveal whether an account exists. Password checks against an unknown user still spend the Argon2 time.
- **The journal.** Every sign-in, failed sign-in, new method, revoked session and accepted invitation is journalled under the account. The account page shows it.

## 8. Recovery

- **With SMTP:** "forgot password" sends a one-time link that is valid for 30 minutes.
- **Without SMTP:** a home admin can create a reset link for a member, valid for 24 hours. It is shown on screen to pass on by hand.
- **When the last owner is locked out:** the operator runs `python -m penaria.apps.cli users reset <username>`, which prints a one-time reset link. Access to the server is access to the house.
- **Recovery codes** from section 4.3 replace a lost second factor.

## 9. Configuration

| Variable | Meaning |
|---|---|
| `PENARIA_PUBLIC_URL` | The address people open, such as `https://home.example.org`. Required. Sets the passkey relying party, the `Origin` check and the links in invitations |
| `PENARIA_AUTH__OIDC__ISSUER`, `..._CLIENT_ID`, `..._CLIENT_SECRET`, `..._ALLOW_SIGN_UP` | Optional OIDC |
| `PENARIA_MAIL__*` | Optional outgoing email; when set, it locks the interface's mail settings (section 9.1) |
| `PENARIA_SECRET_KEY` | Encrypts stored secrets: the SMTP password, TOTP secrets, queued mail. Required; the quickstart generates it |
| `PENARIA_RETIRED_SECRET_KEYS` | Earlier values of `PENARIA_SECRET_KEY` while it is rotated (section 15) |

### 9.1 Outgoing email

**Decision: the install admin connects a mailbox from the interface**, as HSE Doc Studio does. Environment variables remain for operators who manage configuration as code.

- **One mailbox per install.** It is used for every message the install sends: sign-in and reset links, invitations, and later notifications. It sends only, over SMTP.
- **Settings.**
  - The fields are: server and port; security, which is STARTTLS on 587, TLS on 465, or none; the login; the password; the sender's address and name.
  - Changing the security moves the default port.
  - Settings live in an `identity_install_settings` table. The password is encrypted with `PENARIA_SECRET_KEY` and is write-only: the interface shows only "password set", and an empty field leaves it unchanged.
  - Changes take effect without a restart.
  - Every change is journalled, and the password itself never is.
- **The environment wins as a whole.** When `PENARIA_MAIL__HOST` is set, every mail setting comes from the environment and the interface shows the fields locked. Half of the settings from each place would make a connection nobody configured.
- **Test email.** "Send a test email" uses the saved settings and goes to the admin's own address unless another one is typed. It shows the server's error verbatim, with the credentials scrubbed. A connection probe feeds the install's status page.
- **Delivery.**
  - Sending uses `aiosmtplib`; messages are text plus HTML, in the recipient's language.
  - Temporary failures are retried 5 times: after 1, 5, 15 and 30 minutes. The queue is a PostgreSQL table whose messages are encrypted at rest.
  - A mail log lets the admin see each attempt and resend.
- **Without a mailbox,** links that would be emailed (reset, invitation) are shown on screen to pass on by hand, as section 8 describes. An email cannot be confirmed without one (section 15).

## 10. Storage

New tables, all `identity_*`, alongside the ones of core-model section 12:

```sql
-- identity_users gains: username (unique, lower), email (unique when present),
--   install_admin bool, disabled_at.
CREATE TABLE identity_passwords (user_id uuid PRIMARY KEY REFERENCES identity_users, hash text NOT NULL, changed_at timestamptz NOT NULL);
CREATE TABLE identity_passkeys (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES identity_users ON DELETE CASCADE,
  credential_id bytea UNIQUE NOT NULL, public_key bytea NOT NULL, sign_count bigint NOT NULL, name text NOT NULL,
  transports text[] NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL, last_used_at timestamptz);
CREATE TABLE identity_passkey_challenges (id uuid PRIMARY KEY, ceremony text NOT NULL, challenge bytea NOT NULL,
  session_id uuid REFERENCES identity_sessions ON DELETE CASCADE,  -- none for a sign-in
  address text,                                                    -- a sign-in's address, as its counter key
  expires_at timestamptz NOT NULL);                                -- section 13
CREATE TABLE identity_totp (user_id uuid PRIMARY KEY REFERENCES identity_users, secret bytea NOT NULL, recovery_codes text[] NOT NULL);
CREATE TABLE identity_external_identities (provider text, subject text, user_id uuid NOT NULL REFERENCES identity_users,
  PRIMARY KEY (provider, subject));
CREATE TABLE identity_sessions (id uuid PRIMARY KEY, token_hash bytea UNIQUE NOT NULL, user_id uuid REFERENCES identity_users,
  grant_id uuid REFERENCES identity_grants,         -- guest sessions: the link's grant
  created_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL, authenticated_at timestamptz NOT NULL,
  user_agent text, ip inet, revoked_at timestamptz,
  CHECK ((user_id IS NULL) <> (grant_id IS NULL)));
CREATE TABLE identity_invitations (id uuid PRIMARY KEY, home_id uuid NOT NULL, token_hash bytea UNIQUE NOT NULL, role_id uuid NOT NULL,
  scope_entity_id uuid, grant_expires_at timestamptz, leave_when_accepted bool NOT NULL DEFAULT false,
  created_by uuid NOT NULL, expires_at timestamptz NOT NULL, accepted_at timestamptz, accepted_by uuid, revoked_at timestamptz);
CREATE TABLE identity_tokens (id uuid PRIMARY KEY, token_hash bytea UNIQUE NOT NULL, principal_type text NOT NULL,
  principal_id uuid NOT NULL, name text NOT NULL, created_at timestamptz NOT NULL, last_used_at timestamptz, revoked_at timestamptz);
```

Step 3 built `identity_invitations`, `identity_tokens` and the guest side of `identity_sessions` as sketched, with `created_at` on invitations and foreign keys to the home (cascading), the role, the place and the accounts; a guest session cascades with its grant. `identity_grants` gained `granted_by` (section 14).

A guest link's secret is stored as a token for its `link` principal.

Outgoing email and recovery added `identity_install_settings`, `identity_mail`, `identity_mail_attempts` and `identity_account_links` (section 15).

The TOTP secret is encrypted with a key derived from `PENARIA_SECRET_KEY`, a new required variable. The quickstart generates it.

## 11. Decisions

The author accepted every decision below on 2026-11-24 and added outgoing email from the interface (9.1).

| # | Decision | Answer |
|---|---|---|
| 1 | A setup token from the log, rather than "first visitor becomes owner" (section 2) | Yes |
| 2 | A username, with email optional (section 3) | Yes: many installs have no SMTP |
| 3 | An install admin role apart from home roles (section 3) | Yes: one install may host several households |
| 4 | Passkeys first, and passwords as the fallback (4.1, 4.2) | Yes |
| 5 | A second factor required for owners and install admins who use a password (4.3) | Yes |
| 6 | OIDC creates accounts only if the operator allows it (4.4) | Yes; off by default |
| 7 | Sessions: 30 days idle, 180 days at most; a recent sign-in for sensitive commands (5) | Yes |
| 8 | Invitations are single-use; guest links are reusable until they expire (6.1, 6.2) | Yes |
| 9 | Device tokens without expiry, with last use shown and revocation (6.3) | Yes |
| 10 | Recovery without SMTP through an admin's link and a CLI command (8) | Yes |
| 11 | The order of work | 1) accounts, passwords, sessions, setup token, sign-out, account page; 2) passkeys; 3) invitations and guest links; 4) TOTP; 5) device tokens; 6) OIDC. Each is a pull request, and the demo keeps working after each |

## 12. Notes from step 1

Step 1 (accounts, passwords, sessions, the setup token, sign-out and the account page) settled what the sections above left open:

- **The `Secure` flag follows the scheme of `PENARIA_PUBLIC_URL`,** not "except on `localhost`" (section 5). Browsers drop a `Secure` cookie set over plain HTTP, so an install opened at `http://192.168.1.10` could not sign in at all. The server warns at start when `PENARIA_PUBLIC_URL` is plain HTTP on another host than the machine itself.
- **Usernames are stored in lower case,** so a plain unique index keeps them unique case-insensitively. A username is 3 to 32 letters or digits of any script, dots, underscores or hyphens.
- **The setup token** is 32 hexadecimal characters. Only its SHA-256 hash is kept, in `identity_setup_tokens`. Issuing and completing the setup take one lock, so the table holds at most one row: with several api replicas, the replica that started last holds the valid token. The install needs setup while no user has an account (a username), whatever sign-in methods later steps add. Setup turns the earliest user into the account, or creates one when there is none.
- **Rate limits** (section 7) count failures in `identity_sign_in_failures`, under the account (a hash of the username typed, so unknown names are limited too and no typed name is stored) and under the address: an IPv4 address, or the /64 block of an IPv6 one, which a single household or attacker holds. Five failures are free; then the wait is 30 seconds, doubling up to 15 minutes. A count is forgotten an hour after its last failure.
  - An attempt is counted as failed before its password is checked, in a short transaction under a lock on its counters, and a success takes the count back: the account's count is cleared, the address's loses this one attempt. Parallel guesses therefore cannot all pass the check, and no transaction stays open while the password is hashed. The success itself then takes the account's lock and checks that the password is still the one it checked, so a sign-in or a change that crosses a password change refuses instead of opening a session or writing the old password back.
  - Wrong setup tokens are counted per address, wrong current passwords (changing the password) per account. The server answers 429 with `too_many_attempts` and `retry_after_seconds`.
  - At most as many Argon2 hashes run at once as the cores allow (each takes 64 MiB), so a burst of attempts cannot exhaust a small home server.
  - **Accepted trade-off:** someone who knows a username can keep that account from signing in with a few wrong attempts an hour; the per-account limit cannot tell the owner's attempt from theirs. Passkeys (step 2, section 13) are not limited this way, nor is the operator's reset command (section 8). The same holds for the address of a reverse proxy that does not pass on people's addresses, which is why the server README asks to trust its `X-Forwarded-For`.
- **Changing the password ends every other session** of the account.
- **The `Origin` check** (section 5) falls back to `Referer` when a request has no `Origin`. A request with neither comes from a client that is not a browser, which a forged page cannot make carry the cookie, and passes.
- **Account events are journalled with no home:** `journal_events.home_id` is nullable (core-model 9.3). The types are `account.setup_completed`, `account.signed_in`, `account.sign_in_failed`, `account.signed_out`, `account.updated`, `account.password_changed` and `session.revoked`, each with the `user_id` in the payload. A failed sign-in is recorded only for an existing account, with the `system` actor: nobody is signed in.
- **A session's last use** is written at most every 5 minutes, so reading pages does not write on every request.
- **`identity_sessions` had no `grant_id` in step 1,** and `user_id` was required. Step 3 added `grant_id` for guest sessions, made `user_id` nullable and requires exactly one of the two (section 14).

## 13. Notes from step 2

Step 2 (passkeys) settled these:

- **Signing in is usernameless.** The sign-in screen offers "Sign in with a passkey" first and the username and password below it. The options carry an empty `allowCredentials`, so the browser offers every passkey it keeps for the install; the answer names its credential, and it must carry the authenticator's user handle (the account's id, 16 bytes that say nothing about the person), which must match the account that owns the credential.
- **Discoverable credentials and user verification are required,** not preferred. With no username to look credentials up by, a credential the authenticator does not keep by itself could never sign in; asking for one up front fails at once on the rare authenticator that cannot, instead of adding a passkey that never works. A passkey is the only factor of its sign-in (4.3), so the authenticator must check the person (a fingerprint, a face, a PIN), not just a touch. Attestation is `none`: Penaria does not restrict which authenticators people use.
- **The relying party** is the host of `PENARIA_PUBLIC_URL`, named "Penaria", and answers must come from its origin. Browsers allow passkeys only on `https` with a domain name, or on `localhost`. An install opened at an IP address keeps passwords: the server warns at start, and the interface offers no passkey where the browser has no WebAuthn or the address is an IP.
- **Challenges** are 32 random bytes in `identity_passkey_challenges`, given out with an id that the browser's answer brings back. Each is used at most once (taking it deletes it) and expires after 5 minutes, the time to pick a phone through a QR code; expired ones are deleted whenever a new one is given out. A registration or a confirmation belongs to the session that asked for it; a sign-in to none. An id in the response, rather than a cookie, is enough: the signature already binds the answer to the install's origin and to this challenge.
- **Open sign-ins per address.** Starting a sign-in needs no account, so an address (an IPv4 address or an IPv6 /64, as in section 12) may hold at most 10 sign-in challenges that are neither used nor expired; the 11th answers 429 `too_many_attempts` until the oldest expires. A household signing in at once stays far below it, and a script cannot fill the table.
- **Signature counts** follow py_webauthn: a count that did not grow refuses the sign-in, as a sign of a cloned authenticator; synced passkeys always count zero, which passes. The new count is written only if nobody changed it since it was read, so of two sign-ins racing with one counting authenticator only one opens a session, and a passkey removed meanwhile opens none.
- **A recent sign-in** is `authenticated_at` of the session, set when it starts and again when the person confirms it is them: `POST /me/reauthenticate` with the password, or `/me/reauthenticate/passkey` with a passkey, without ending the session. Adding and removing a passkey need one within 10 minutes; the server answers `403 recent_sign_in_required` and the interface asks for the password or a passkey, then repeats the action. Adding checks it when the ceremony starts, not again when the browser answers: the challenge belongs to the session and lives 5 minutes, and refusing at the end would leave a credential on the device that the account never got. Renaming needs no recent sign-in. Changing the password needs none either: it asks for the current password itself.
- **The last way to sign in** cannot be removed: a passkey goes only if the account has a password or another passkey. Every account has a password: accounts made through an invitation (step 3) take one too, and a passkey can be added afterwards.
- **Setup stays password-only.** The setup screen is the one place a person types the setup token, and a passkey added a moment later from the suggestion (below) costs one tap; a second ceremony inside setup would double its failure modes for little gain.
- **Limits.** Failed passkey sign-ins count per address only, as section 7 counts them, and a success takes its attempt back. They do not count per account: a passkey cannot be guessed, and the owner's passkey keeps working while someone tries their password (the trade-off of section 12). Confirming with the password counts per account, like changing it; confirming with a passkey is not limited.
- **The journal** gains `account.passkey_added`, `account.passkey_renamed`, `account.passkey_removed` (each with the `passkey_id`) and `account.reauthenticated` (with the `passkey_id` when a passkey confirmed it). A sign-in with a passkey is `account.signed_in` with its `passkey_id`; an answer that does not check out for a known passkey is `account.sign_in_failed` with its `passkey_id`, under the `system` actor. Answers naming an unknown credential are not journalled: they belong to no account.
- **Names.** A new passkey is named after the browser and system that made it ("Chrome on macOS", "Safari on iPhone"); its person renames it on the account page, which lists each passkey with when it was added and last used.
- **The suggestion.** An account without passkeys, in a browser that can make one, sees "Sign in faster with a passkey" above its pages, with a button that adds one at once. "Not now" hides it for good in that browser.
- **The web app** calls `navigator.credentials` directly, converting the JSON options and answers itself (`src/shared/lib/webauthn.ts`), rather than adding `@simplewebauthn/browser`: the conversion is a few lines, and the app maps the browser's refusals (`NotAllowedError`, `InvalidStateError`, `SecurityError`) to its own messages anyway.

## 14. Notes from step 3

Step 3 (invitations, a home's people and guest links) settled these:

- **Who gives what.** Making, changing and taking back access all follow one rule, the no-escalation rule of core-model 11.1: a role can be given over a place only by someone who holds `members.manage` there and every permission of the role; a role with every permission only by someone with every permission; a role with guest view is the only kind a guest-view holder can give; an owner only by an owner. Changing or taking back a grant needs the same right over the grant as it is, so a member who manages people cannot demote an admin. Everyone can take back their own access (leaving), except the last owner, but nobody changes their own (`403 own_grant`): a time-limited admin must not lift their own end. Every change to a home's people locks the home's row first and checks this rule under the lock, from the grants as that transaction sees them, so of two admins demoting each other at once only the first succeeds.
- **Owners** are made only by invitation and leave only by revocation: an owner grant is never edited (`409 owner_grant`). Removing an owner, and leaving as one, is refused for the last owner (`409 last_owner`). Under the lock of the home's row two owners cannot remove each other at once. A change that finds the grant changed since it was read answers `409 stale_version`.
- **A recent sign-in** (section 5) is needed to invite an owner (a transfer of ownership is one), to change a grant and to take back an owner grant, leaving as an owner included. Taking back other grants, revoking invitations and guest links need none: they only reduce access.
- **Invitations.** The role is named by its id, so roles made later work as they are. The scope is a live place of the same home, or the whole home; an owner invitation covers the whole home and gives access without end. The link works for 7 days by default and for 30 at most, asked for in days (`valid_days`) rather than as a moment, so a browser whose clock runs ahead is not refused the longest choice; it never works longer than the access it gives: a guest invitation whose access ends in 3 days stops working then too. A role that requires an end gets its default duration from when the invitation is made, unless the inviter picks a day.
- **Accepting** re-checks the rule above for the inviter, under the lock: an invitation gives only what its inviter may still give (`409 inviter_lost_access`), so taking an admin's access back also disarms their pending invitations. The invitation row is locked, so it is used once. Accepting your own invitation is refused (`own_invitation`), and so is access you already hold with the same role over the same place (`already_granted`); the invitation then stays unused, to be passed on. Accepting a different role adds a grant: access is the union of grants (core-model 11.2). For a transfer, the inviter's owner grants are revoked in the same transaction, journalled with the inviter as the actor and the reason `transferred`.
- **New accounts.** Accepting an invitation is the only way to make an account besides the setup. It takes a username, a display name and a password; the account is not an install admin, and the passkey suggestion of section 13 follows. A taken username answers `409 username_taken`: only someone holding a valid invitation can learn that a username exists.
- **Secrets in bodies.** The web pages carry the token in their address (`/invite/<token>`, `/guest/<token>`), but the API takes it only in request bodies (`POST /invitations:preview`, `:accept`, `:accept-new-account`, `POST /guest-sessions`), so API access logs never hold one. The guest page moves on to `/guest` once the session is open, so the token leaves the address bar too. Links are shown once, when made: only hashes are kept, and a lost link is replaced by a new one.
- **Limits.** Unknown invitation and guest-link tokens count per address as section 7 counts failures, under a key of their own (`links:<address>`), so guessing tokens and guessing passwords do not share a counter. A token found takes its count back, so a household opening one link from many phones is never slowed down. A browser that opens a link again keeps its guest session, and a link keeps at most 50 guest sessions open: opening it beyond that ends the oldest, so a loop cannot pile up sessions.
- **Guest links.** A link is a `link` principal: one grant and one row in `identity_tokens` share its id. Its role must have guest view; it ends after the role's default duration (3 days for the guest preset, and 3 days for a role with guest view and no default) unless the person making it picks another day, within 90 days: a guest link is for a visit, and longer access belongs to an account. A link ends too when its maker can no longer give it, because their access was taken back, changed or handed over with the home; this sweep runs with the change, under the home's lock, and journals `guest_link.revoked` with the reason `giver_lost_access`. Revoking a link's grant revokes its token and ends its guest sessions in the same transaction, and every request of a guest session checks the grant, so an expired or revoked link ends the visit at the next request. A guest session reaches no account endpoint (`401`), cannot create a home (`403 account_required`) and changes nothing its role does not allow. A link's access is not changed afterwards: a new link is made instead.
- **One cookie.** A guest session uses the session cookie of section 5. A browser signed in to an account that opens a guest link is asked first, and signs out before it becomes a guest's.
- **Who sees the people.** The lists of members, invitations and guest links need `members.manage` over the whole home. Everyone else sees their own place in the home and a way to leave it. Grants keep who gave them (`identity_grants.granted_by`), so the list says who invited whom.
- **What a guest learns of places.** The guest's tree counts only what a guest may see: a place's count of what is inside leaves out the things not meant for guests. A place on the way to guest-visible things shows only its name and kind (its other names, quantity and verification are left out), and a guest sees no entity's history.
- **History and private places.** Invitations bring members without `entities.view_private`, such as the family preset. The history of an entity names other places (where it was created, moved from and to); for such a member, a place that is private, inside something private or gone is left out (`null`), so a history does not tell where the safe is.
- **Places across contexts.** Identity checks a scope and names it through a `PlaceDirectory` port that the registry implements, as the registry asks identity through `AccessPolicy`; neither reads the other's tables.
- **The journal** gains `invitation.created`, `invitation.revoked`, `invitation.accepted`, `account.created` (with the `invitation_id`), `grant.created` (with the `invitation_id`), `grant.changed` (with the grant `before`), `grant.revoked` (with the `reason`: `revoked`, `left` or `transferred`), `guest_link.created`, `guest_link.opened` and `guest_link.revoked` (with the number of `sessions_ended` and the `reason`, `giver_lost_access` among them). Every `grant.created`, the home creator's included, records the grant in one shape: its id, principal, role, scope and end.
- **Left open.** Access given by someone whose own access ends may outlast theirs: a time-limited admin can invite an admin without end. Capping what a giver gives at their own end needs the end of the access that allows the giving, which several grants may share; it waits for a decision.
- **QR codes** are drawn in the browser with `uqr`, a dependency-free encoder, as an SVG of the app's own, rather than with `qrcode`, which brings a command line tool's dependencies along. The link never leaves the browser to be drawn.

## 15. Notes from outgoing email and recovery

The step after invitations (outgoing email from the interface and recovery, sections 8 and 9.1) settled these:

- **Stored secrets.** A secret is sealed with Fernet under a key derived from `PENARIA_SECRET_KEY` with HKDF-SHA256 (the setting is a passphrase of any form, not a Fernet key). The stored value is an envelope, `pnr1:<key id>:<token>`, where the key id is a short hash of the derived key. Fernet has no associated data, so the plaintext carries its binding, the record it belongs to (`mailbox/password`, `mail/<id>/content`), and opening checks it: a ciphertext copied into another record does not open. **Rotation:** `PENARIA_RETIRED_SECRET_KEYS` lists earlier keys, separated by commas; what they sealed still opens, new secrets use the current key. The mailbox's password is sealed again when an admin saves it; queued email lives a few days at most. With several api replicas, rotate in two deploys: first add the new key to the retired ones everywhere, then make it the current key and retire the old one; otherwise a replica still on the old key cannot open what a new one sealed, and fails that mail for good. A secret whose key is gone answers as unreadable, and the mail log says to enter the password again.
- **Install settings.** `identity_install_settings` holds a row per setting: a `value` (JSON) and a sealed `secret`. The mailbox is one row, `mail`, with the fields in `value` and the password in `secret`; saving it is one statement, so half a mailbox is never stored. The password is write-only: the API answers `password_set`, an empty password keeps the saved one, and a mailbox without a login keeps none. **The saved password stays with the connection it was given for:** a change of the server, the port, the security or the login without a new password answers `400 invalid_mailbox` (field `password`), so a saved password is never sent to another server, nor in the clear. Every save is journalled as `install.mailbox_saved` with the names of the fields that changed and whether the password did; turning mail off as `install.mailbox_removed`. Connecting or changing the mailbox, and turning it off, need a recent sign-in (section 5): whoever chooses the mailbox could read every reset link sent through it.
- **The environment as a whole.** With `PENARIA_MAIL__HOST` set, `..._FROM_ADDRESS` is required and the port defaults by the security (587, 465, 25); any other `PENARIA_MAIL__*` variable without the host stops the process at start, as a misspelt one does. The interface shows the fields locked, and saving or removing answers `409 mailbox_locked`.
- **The queue and the log are one table.** `identity_mail` holds every email: its kind, recipient, language, subject and its text and HTML sealed (bound to the row), its state (`queued`, `sent`, `failed`), its attempts and when the next is due. `identity_mail_attempts` holds one row per attempt with the kind of failure, the SMTP code and the server's words, scrubbed of the login and password (plain and in base64, as `AUTH PLAIN` and `AUTH LOGIN` send them) and cut to one line of 500 characters.
- **Sending.** Whatever sends an email queues it in the transaction of the change it is about, so a reset email exists only if its link does, and the request does not wait for the SMTP server: the answer to "forgot password" never waits for the SMTP server, whether or not a mail was queued. A loop in the api process (a servicewright daemon entrypoint, until the worker exists) sends what is due every 3 seconds, taking one email at a time, and stops the pass at a failure of the mailbox itself (it cannot be reached or signed in to): the other emails would fail the same way. Sender addresses at national domains (`home@почта.рф`) go out in IDNA. A test email and a resend are sent at once, since an admin waits for the answer; a test is never retried.
- **Retries.** "Retried 5 times" means five attempts in all: the first, then after 1, 5, 15 and 30 minutes. Temporary is a `4xx` reply, or a connection that did not open, timed out or broke off without one; everything else fails at once. Nothing is sent after the email's link stops working (30 minutes for a reset, 24 hours for a confirmation, the invitation's end) or, without a link, after 3 days; the text is then cleared, and the log keeps the rest for 30 days.
- **Several replicas.** Taking a due email moves its next attempt five minutes ahead in a transaction that skips rows other transactions hold (`FOR UPDATE SKIP LOCKED`), so two replicas never take the same email, and one taken by a replica that stopped is taken again after the lease. Emails are taken one at a time, so one attempt (15 seconds at most per SMTP step) stays well inside its lease. An email may go twice if a replica stops between sending and recording; it never goes twice otherwise.
- **The log and resending.** The log lists each email with its attempts, the newest first, paged by the last one seen, for install admins only. An email can be sent again while it is not waiting for a retry and its link still works; the resend is an attempt of the same email, its retries start over, and `mail.resent` is journalled. A test is journalled as `install.mail_tested`.
- **Verified email.** **Decision:** an account's email is set only by opening a confirmation link mailed to it, valid 24 hours (`POST /me/email`, then `POST /email-verifications:confirm` from `/verify-email/<token>`, which needs no session). The address stays the old one until then, and the link names the address it confirms. Section 9.1 shows a link on screen when there is no mail; for a confirmation that would let a typo become the account's address, and later reset links would go to whoever owns it, so **without outgoing mail an account adds no email**. Another account's confirmed address answers `409 email_taken`; only people with an account on the install can learn that an address is used. Reset links go to the address, so **changing or removing it needs a recent sign-in** (section 5), the old address is told of the new one, and unused reset links of the account stop working; so does a changed password. Each account may have the install mail a few addresses it typed an hour (confirmations and invitations together: five, then the wait of section 12), so the install's mailbox does not become a way to mail strangers. `account.email_changed` and `account.email_removed` are journalled.
- **One-time account links.** Reset and confirmation links share `identity_account_links`: the account, the purpose, a hash of the token, the address for a confirmation, the end, when it was used and who made it for someone else. A new link of a purpose replaces the account's unused ones. Unknown tokens count against the address as other secret links do (section 14). The pages carry the token in their address (`/reset-password/<token>`, `/verify-email/<token>`); the API takes it only in bodies.
- **Forgot password.** The form takes a username or a confirmed email and answers `204` whatever it finds; it is offered only when mail is on, and answers `409 mail_off` otherwise. A link goes only to a confirmed email of an enabled account. Requests count per address and per login typed, apart from sign-in failures: five an hour, then the wait of section 12.
- **Resetting.** The reset page shows whose account it is and its passkeys, then takes a new password: it ends every session of the account, clears the account's sign-in failures and keeps the passkeys, so an unknown passkey is removed after signing in. **Decision:** a reset does not sign in; the person signs in with the new password, so the second factor of section 4.3 will still be asked. `account.password_reset` is journalled with the link and the number of sessions ended; when the account has a confirmed email, a notice of the change goes there.
- **An admin's reset link.** `POST /homes/{id}/members/{user}:reset-link` needs `members.manage` over the whole home and a recent sign-in, and makes a 24-hour link shown once. Since the link hands over the whole account, **the admin must be able to give every access the member holds, in this home and in any other** (the rule of section 14), and only an install admin resets an install admin; nobody makes one for themselves. Otherwise `403 reset_not_allowed`. **The rule is checked again when the link is used**, as an invitation checks its inviter: an admin who lost their access, or a member who gained access the admin cannot give, makes the link refuse with the same answer. `account.reset_link_created` is journalled with `by` (`self`, `admin` or `operator`).
- **The operator's command.** `python -m penaria.apps.cli users reset <username>` prints a 24-hour link and journals it with the `system` actor. `apps/cli` joins the processes; it accepts the api's variables, as migrate does.
- **Invitations by email** go in the home's language: the person invited has no account to say theirs. Without mail, asking for one answers `409 mail_off` and makes no invitation.
- **Notices.** A changed password (by the person or a reset), a new passkey and a changed email (to the old address) are told by email to the account's confirmed address, when mail is on.
- **The interface.** Install admins see Settings: the mailbox form, as HSE Doc Studio's, with the port following the security, the password write-only, lock marks when the environment sets the mailbox, a status line from a connection check (connect, STARTTLS, sign in, no mail sent), a test email that checks the saved settings, and the mail log. The account page has the email; the people page a "Reset password" action per member; the invitation dialog an optional address when mail is on.
