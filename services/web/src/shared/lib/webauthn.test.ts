import {describe, expect, it} from 'vitest'

import {ASSERTION_JSON, mockPasskeys, NEW_CREDENTIAL_JSON, refuse} from '@/test/webauthn'

import {createCredential, fromBase64url, getCredential, passkeysSupported, toBase64url, WebAuthnError} from './webauthn'

const CREATION: PublicKeyCredentialCreationOptionsJSON = {
  rp: {id: 'localhost', name: 'Penaria'},
  user: {id: 'dXNlcg', name: 'owner', displayName: 'Alex'},
  challenge: 'Y2hhbGxlbmdl',
  pubKeyCredParams: [{type: 'public-key', alg: -7}],
  timeout: 300000,
  excludeCredentials: [{id: 'b2xk', type: 'public-key', transports: ['usb']}],
  authenticatorSelection: {residentKey: 'required', userVerification: 'required'},
  attestation: 'none',
}

const REQUEST: PublicKeyCredentialRequestOptionsJSON = {
  rpId: 'localhost',
  challenge: 'Y2hhbGxlbmdl',
  timeout: 300000,
  allowCredentials: [],
  userVerification: 'required',
}

const text = (buffer: BufferSource) => new TextDecoder().decode(buffer)

/** The value with every buffer replaced by the text it holds: equality does not look into buffers. */
function readable(value: unknown): unknown {
  if (value instanceof ArrayBuffer) return `bytes:${text(value)}`
  if (Array.isArray(value)) return value.map(readable)
  if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, readable(item)]))
  }
  return value
}

describe('webauthn', () => {
  it('converts base64url both ways, padding and the characters base64 differs in included', () => {
    const bytes = new Uint8Array([0, 251, 255, 191, 62, 63]).buffer

    expect(toBase64url(bytes)).toBe('APv_vz4_')
    expect(new Uint8Array(fromBase64url('APv_vz4_'))).toEqual(new Uint8Array(bytes))
    expect(text(fromBase64url('dXNlcg'))).toBe('user')
  })

  it('tells that passkeys do not work on a page without WebAuthn', () => {
    expect(passkeysSupported()).toBe(false)
  })

  it('tells that passkeys work on a secure page with WebAuthn', () => {
    mockPasskeys()

    expect(passkeysSupported()).toBe(true)
  })

  it('makes a passkey from the options in JSON and gives the credential back in JSON', async () => {
    const browser = mockPasskeys()

    const credential = await createCredential(CREATION)

    expect(credential).toEqual(NEW_CREDENTIAL_JSON)
    expect(readable(browser.create.mock.lastCall)).toEqual([
      {
        publicKey: {
          ...CREATION,
          challenge: 'bytes:challenge',
          user: {...CREATION.user, id: 'bytes:user'},
          excludeCredentials: [{id: 'bytes:old', type: 'public-key', transports: ['usb']}],
        },
      },
    ])
  })

  it('signs a challenge and gives the answer back in JSON', async () => {
    const browser = mockPasskeys()

    const credential = await getCredential(REQUEST)

    expect(credential).toEqual(ASSERTION_JSON)
    expect(readable(browser.get.mock.lastCall)).toEqual([{publicKey: {...REQUEST, challenge: 'bytes:challenge'}}])
  })

  it.each([
    ['NotAllowedError', 'cancelled'],
    ['AbortError', 'cancelled'],
    ['InvalidStateError', 'exists'],
    ['SecurityError', 'unavailable'],
    ['NotSupportedError', 'unavailable'],
  ])('explains the browser refusing with %s as %s', async (name, failure) => {
    mockPasskeys({create: refuse(name)})

    const refused = createCredential(CREATION)

    await expect(refused).rejects.toBeInstanceOf(WebAuthnError)
    await expect(refused).rejects.toHaveProperty('failure', failure)
  })

  it('passes on what it cannot explain', async () => {
    mockPasskeys({get: refuse('UnknownError')})

    await expect(getCredential(REQUEST)).rejects.toHaveProperty('name', 'UnknownError')
  })

  it('takes no credential at all as cancelled', async () => {
    mockPasskeys({get: () => Promise.resolve(null)})

    await expect(getCredential(REQUEST)).rejects.toHaveProperty('failure', 'cancelled')
  })
})
