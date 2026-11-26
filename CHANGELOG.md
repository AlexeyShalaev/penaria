# Changelog

All notable changes to Penaria, newest first. This file is generated from `release-notes.json` by
`scripts/release/notes.py`: do not edit it by hand. A change gets here through a fragment in
`changes/` (see `changes/README.md`).

## 0.1.0 (2026-11-26)

### Added

- Devices and integrations, such as a smart mirror or a backup script, get a token of their own on the People page, with a role and a place: they see and do only what that role allows, the page shows when and from where each was last used, and revoking a token ends its access at once.
- An install admin connects a mailbox in Settings, and Penaria emails password reset links, invitations and account notices; without email, a home's admin or the server's owner makes a reset link to pass on by hand.
- Install Penaria at home with Docker Compose: one folder with the database, the server and the web app, HTTPS by itself when you have a domain, and steps for backups and upgrades (deploy/compose).
- Invite your family and others into a home with a link or a QR code, each with a role, a place and an end date; they make their account through the link, and one account can belong to many homes. Guests need no account: a guest link shows only what you marked for guests, ends on its own and can be revoked in one click. The People page shows who has access, lets you change or take it back, and hands the home over to a new owner.
- Homes and their tree: create a home, then its properties, buildings, floors, rooms, containers and things; move, rename, archive, restore and confirm them, and see the history of each.
- Passkeys: sign in with your fingerprint, face or screen lock instead of a password, without typing a username. Add, rename and remove passkeys on the account page; Penaria asks you to confirm it's you before you add or remove one. Passkeys need Penaria opened over https at a domain name.
- If you run an identity provider such as Authentik or Keycloak, people can sign in to Penaria with it: set the PENARIA_AUTH__OIDC__* variables, and the sign-in page offers "Sign in with" your provider. People link it on their account page or join through an invitation with it; new accounts are made only if you allow it.
- Sign-in with accounts: the first start asks for a setup token from the server's log and creates the owner's account; everyone signs in with a username and a password, and the account page changes the name, language and password and shows every signed-in device, each of which can be signed out.
- Two-step sign-in: signing in with a password can also ask for a code from an authenticator app, with ten recovery codes for a lost phone. Home owners and admins who sign in with a password must add an authenticator app or a passkey.
- The web app shows your homes: create the first one, then build its tree of rooms, storage and things in the browser. Every place and thing has a page where you mark that it is in place, move, edit or archive it, and read its history.
