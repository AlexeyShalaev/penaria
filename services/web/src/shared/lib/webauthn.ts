/**
 * Passkeys through the browser's WebAuthn API. The server sends the options as JSON (base64url for
 * the bytes) and takes the credential back as JSON; this module converts both ways, so it works in
 * browsers that lack `PublicKeyCredential.parseCreationOptionsFromJSON` and `toJSON`.
 */

/** Why the browser did not make or use a passkey, in the terms the interface explains. */
export type WebAuthnFailure =
  // The person closed the browser's prompt, it timed out, or no passkey of this site was there.
  | 'cancelled'
  // The authenticator already holds one of the account's passkeys.
  | 'exists'
  // The page's address cannot have passkeys, such as an IP address.
  | 'unavailable'

export class WebAuthnError extends Error {
  readonly failure: WebAuthnFailure

  constructor(failure: WebAuthnFailure, cause: unknown) {
    super(failure, {cause})
    this.name = 'WebAuthnError'
    this.failure = failure
  }
}

export type RegistrationCredentialJSON = {
  id: string
  rawId: string
  type: 'public-key'
  response: {clientDataJSON: string; attestationObject: string; transports: string[]}
}

export type AuthenticationCredentialJSON = {
  id: string
  rawId: string
  type: 'public-key'
  response: {clientDataJSON: string; authenticatorData: string; signature: string; userHandle: string | null}
}

/** Whether passkeys can work here: WebAuthn exists only on secure pages (https, or localhost in development). */
export function passkeysSupported(): boolean {
  return (
    window.isSecureContext === true && typeof window.PublicKeyCredential === 'function' && 'credentials' in navigator
  )
}

/** Asks the browser to make a passkey for the options the server gave. */
export async function createCredential(options: PublicKeyCredentialCreationOptionsJSON) {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...options,
    challenge: fromBase64url(options.challenge),
    user: {...options.user, id: fromBase64url(options.user.id)},
    excludeCredentials: options.excludeCredentials?.map(descriptor),
  } as PublicKeyCredentialCreationOptions
  const credential = await ask(() => navigator.credentials.create({publicKey}))
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: 'public-key',
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      attestationObject: toBase64url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
  } satisfies RegistrationCredentialJSON
}

/** Asks the browser to sign the server's challenge with a passkey of this site. */
export async function getCredential(options: PublicKeyCredentialRequestOptionsJSON) {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: fromBase64url(options.challenge),
    allowCredentials: options.allowCredentials?.map(descriptor),
  } as PublicKeyCredentialRequestOptions
  const credential = await ask(() => navigator.credentials.get({publicKey}))
  const response = credential.response as AuthenticatorAssertionResponse
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: 'public-key',
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      authenticatorData: toBase64url(response.authenticatorData),
      signature: toBase64url(response.signature),
      userHandle: response.userHandle ? toBase64url(response.userHandle) : null,
    },
  } satisfies AuthenticationCredentialJSON
}

async function ask(call: () => Promise<Credential | null>): Promise<PublicKeyCredential> {
  let credential: Credential | null
  try {
    credential = await call()
  } catch (error) {
    throw failure(error)
  }
  if (credential?.type !== 'public-key') throw new WebAuthnError('cancelled', credential)
  return credential as PublicKeyCredential
}

// The names browsers give WebAuthn's failures (https://w3c.github.io/webauthn/#sctn-createCredential).
function failure(error: unknown): unknown {
  if (!(error instanceof DOMException)) return error
  switch (error.name) {
    case 'NotAllowedError':
    case 'AbortError':
      return new WebAuthnError('cancelled', error)
    case 'InvalidStateError':
      return new WebAuthnError('exists', error)
    case 'SecurityError':
    case 'NotSupportedError':
      return new WebAuthnError('unavailable', error)
    default:
      return error
  }
}

function descriptor(credential: PublicKeyCredentialDescriptorJSON): PublicKeyCredentialDescriptor {
  return {...credential, id: fromBase64url(credential.id)} as PublicKeyCredentialDescriptor
}

export function fromBase64url(value: string): ArrayBuffer {
  const base64 = value.replaceAll('-', '+').replaceAll('_', '/')
  const binary = atob(base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '='))
  return Uint8Array.from(binary, (char) => char.charCodeAt(0)).buffer
}

export function toBase64url(bytes: ArrayBuffer): string {
  const binary = String.fromCharCode(...new Uint8Array(bytes))
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}
