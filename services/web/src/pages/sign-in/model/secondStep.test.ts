import {describe, expect, it} from 'vitest'

import {secondStepIn} from './secondStep'

describe('secondStepIn', () => {
  it('reads the pending sign-in the provider left in the fragment', () => {
    expect(secondStepIn('#second-factor=abc&until=2026-11-24T10%3A05%3A00%2B00%3A00')).toEqual({
      token: 'abc',
      expires_at: '2026-11-24T10:05:00+00:00',
    })
  })

  it('finds none in an empty or unrelated fragment', () => {
    expect(secondStepIn('')).toBeNull()
    expect(secondStepIn('#second-factor=abc')).toBeNull()
    expect(secondStepIn('#passkeys')).toBeNull()
  })
})
