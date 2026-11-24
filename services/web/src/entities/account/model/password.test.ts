import {describe, expect, it} from 'vitest'

import {checkNewPassword} from './password'

describe('checkNewPassword', () => {
  it.each([
    ['eleven char', 'eleven char', 'tooShort'],
    ['twelve chars', 'twelve charz', 'mismatch'],
    ['twelve chars', 'twelve chars', null],
  ])('finds %s / %s: %s', (password, repeated, expected) => {
    expect(checkNewPassword(password, repeated)).toBe(expected)
  })
})
