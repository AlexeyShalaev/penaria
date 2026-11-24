import {onTestFinished, vi} from 'vitest'

type Ceremony = (options: {
  publicKey: PublicKeyCredentialCreationOptions & PublicKeyCredentialRequestOptions
}) => unknown

const bytes = (text: string) => new TextEncoder().encode(text).buffer

/** What a browser's `navigator.credentials.create` gives: the bytes spell out each field's name. */
export function newCredential() {
  return {
    type: 'public-key',
    id: 'Y3JlZGVudGlhbA',
    rawId: bytes('credential'),
    response: {
      clientDataJSON: bytes('client data'),
      attestationObject: bytes('attestation'),
      getTransports: () => ['internal', 'hybrid'],
    },
  }
}

/** What a browser's `navigator.credentials.get` gives. */
export function assertion() {
  return {
    type: 'public-key',
    id: 'Y3JlZGVudGlhbA',
    rawId: bytes('credential'),
    response: {
      clientDataJSON: bytes('client data'),
      authenticatorData: bytes('authenticator'),
      signature: bytes('signature'),
      userHandle: bytes('user'),
    },
  }
}

/** The JSON the app sends for `newCredential()` and `assertion()`. */
export const NEW_CREDENTIAL_JSON = {
  id: 'Y3JlZGVudGlhbA',
  rawId: 'Y3JlZGVudGlhbA',
  type: 'public-key',
  response: {
    clientDataJSON: 'Y2xpZW50IGRhdGE',
    attestationObject: 'YXR0ZXN0YXRpb24',
    transports: ['internal', 'hybrid'],
  },
}

export const ASSERTION_JSON = {
  id: 'Y3JlZGVudGlhbA',
  rawId: 'Y3JlZGVudGlhbA',
  type: 'public-key',
  response: {
    clientDataJSON: 'Y2xpZW50IGRhdGE',
    authenticatorData: 'YXV0aGVudGljYXRvcg',
    signature: 'c2lnbmF0dXJl',
    userHandle: 'dXNlcg',
  },
}

/** A refusal as browsers report it, such as `NotAllowedError` when the person closes the prompt. */
export function refuse(name: string): Ceremony {
  return () => Promise.reject(new DOMException('refused', name))
}

/**
 * Makes this page one where passkeys work, with the browser's ceremonies answered by `create` and
 * `get`; returns the mocks to inspect what they were asked.
 */
export function mockPasskeys(device: {create?: Ceremony; get?: Ceremony} = {}) {
  const create = vi.fn(device.create ?? (() => Promise.resolve(newCredential())))
  const get = vi.fn(device.get ?? (() => Promise.resolve(assertion())))
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('PublicKeyCredential', function PublicKeyCredential() {})
  Object.defineProperty(navigator, 'credentials', {value: {create, get}, configurable: true})
  onTestFinished(() => {
    Reflect.deleteProperty(navigator, 'credentials')
  })
  return {create, get}
}
