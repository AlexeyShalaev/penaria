import {describe, expect, it} from 'vitest'

import {safeNext} from './next'

describe('safeNext', () => {
  it.each([
    ['/account', '/account'],
    ['/entities/drill?tab=history#top', '/entities/drill?tab=history#top'],
    [null, '/'],
    ['https://evil.example/', '/'],
    ['//evil.example', '/'],
    ['/\\evil.example', '/'],
    ['/\t/evil.example', '/'],
    ['account', '/'],
    ['//[', '/'],
    ['/\\[', '/'],
    ['//a:99999', '/'],
  ])('sends %s back to %s', (next, expected) => {
    expect(safeNext(next)).toBe(expected)
  })
})
