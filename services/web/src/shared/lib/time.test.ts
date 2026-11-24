import {describe, expect, it} from 'vitest'

import {formatRelative} from './time'

const NOW = new Date('2026-11-24T12:00:00Z')

describe('formatRelative', () => {
  it.each([
    ['en', '2026-11-24T11:59:50Z', 'now'],
    ['en', '2026-11-24T09:00:00Z', '3 hours ago'],
    ['en', '2026-11-23T12:00:00Z', 'yesterday'],
    ['ru', '2026-11-21T12:00:00Z', '3 дня назад'],
    ['ru', '2026-08-24T12:00:00Z', '3 месяца назад'],
  ])('in %s, %s reads as %s', (language, date, expected) => {
    expect(formatRelative(new Date(date), language, NOW)).toBe(expected)
  })
})
