# Sign-in

- **Status:** accepted on 2026-11-24, with outgoing email configurable from the interface (section 9).
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

- **Storage.** The session is a random 256-bit token in a cookie named `penaria_session`, set `HttpOnly`, `Secure` when `PENARIA_PUBLIC_URL` is `https` (section 12), `SameSite=Lax` and `Path=/`. The server stores only a SHA-256 hash of the token, with the user, the time created, the time last seen, the user agent and the IP address.
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
- **Without a mailbox,** links that would be emailed (verification, reset, invitation) are shown on screen to pass on by hand, as section 8 describes.

## 10. Storage

New tables, all `identity_*`, alongside the ones of core-model section 12:

```sql
-- identity_users gains: username (unique, lower), email (unique when present),
--   install_admin bool, disabled_at.
CREATE TABLE identity_passwords (user_id uuid PRIMARY KEY REFERENCES identity_users, hash text NOT NULL, changed_at timestamptz NOT NULL);
CREATE TABLE identity_passkeys (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES identity_users, credential_id bytea UNIQUE NOT NULL,
  public_key bytea NOT NULL, sign_count bigint NOT NULL, name text NOT NULL, last_used_at timestamptz);
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

A guest link's secret is stored as a token for its `link` principal.

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
  - **Accepted trade-off:** someone who knows a username can keep that account from signing in with a few wrong attempts an hour; the per-account limit cannot tell the owner's attempt from theirs. Passkeys (step 2) and the operator's reset command (section 8), both still to come, will not be limited this way. The same holds for the address of a reverse proxy that does not pass on people's addresses, which is why the server README asks to trust its `X-Forwarded-For`.
- **Changing the password ends every other session** of the account.
- **The `Origin` check** (section 5) falls back to `Referer` when a request has no `Origin`. A request with neither comes from a client that is not a browser, which a forged page cannot make carry the cookie, and passes.
- **Account events are journalled with no home:** `journal_events.home_id` is nullable (core-model 9.3). The types are `account.setup_completed`, `account.signed_in`, `account.sign_in_failed`, `account.signed_out`, `account.updated`, `account.password_changed` and `session.revoked`, each with the `user_id` in the payload. A failed sign-in is recorded only for an existing account, with the `system` actor: nobody is signed in.
- **A session's last use** is written at most every 5 minutes, so reading pages does not write on every request.
- **`identity_sessions` has no `grant_id` yet:** it comes with guest links (step 3), and `user_id` is required until then.
