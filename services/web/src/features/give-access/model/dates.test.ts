import {describe, expect, it} from 'vitest'

import {daysFrom, defaultDays, endOfDay, toDateInput} from './dates'

describe('dates', () => {
  it('reads and writes the day of a date input in the local time zone', () => {
    const value = toDateInput(new Date(2026, 10, 27, 15, 30))

    expect(value).toBe('2026-11-27')
    expect(new Date(endOfDay(value)).getDate()).toBe(27)
    expect(new Date(endOfDay(value)).getHours()).toBe(23)
  })

  it('counts whole days', () => {
    expect(daysFrom(new Date('2026-11-24T10:00:00Z'), 3).toISOString()).toBe('2026-11-27T10:00:00.000Z')
    expect(defaultDays(3 * 24 * 3600)).toBe(3)
    expect(defaultDays(null)).toBeNull()
  })
})
