import {describe, expect, it} from 'vitest'

import {canSitIn, childKinds} from './kinds'

describe('childKinds', () => {
  it.each([
    [null, ['property']],
    ['property', ['building', 'space', 'system']],
    ['building', ['floor', 'space', 'system']],
    ['floor', ['space']],
    ['space', ['space', 'container', 'item', 'device']],
    ['container', ['container', 'item', 'device']],
    ['item', ['container', 'item', 'device']],
    ['device', []],
    ['system', ['system']],
  ] as const)('inside %s offers %j', (parent, expected) => {
    expect(childKinds(parent)).toEqual(expected)
  })
})

describe('canSitIn', () => {
  it('keeps a property at the top of the home', () => {
    expect(canSitIn('property', null)).toBe(true)
    expect(canSitIn('property', 'building')).toBe(false)
  })
})
