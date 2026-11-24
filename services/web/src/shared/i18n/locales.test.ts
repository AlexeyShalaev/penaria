import {describe, expect, it} from 'vitest'

import en from './locales/en.json'
import ru from './locales/ru.json'

// i18next picks a plural form by suffix; languages have different sets of forms (ru has few and many).
const PLURAL = /_(zero|one|two|few|many|other)$/

function keys(tree: object, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'object' && value !== null ? keys(value, `${prefix}${key}.`) : [`${prefix}${key}`],
  )
}

const base = (tree: object) => [...new Set(keys(tree).map((key) => key.replace(PLURAL, '')))].sort()

describe('locales', () => {
  it('have the same keys in English and Russian', () => {
    expect(base(ru)).toEqual(base(en))
  })

  it('have every plural form Russian needs', () => {
    const plurals = keys(ru).filter((key) => key.endsWith('_other'))
    const missing = plurals.flatMap((key) =>
      ['one', 'few', 'many'].map((form) => key.replace(/_other$/, `_${form}`)).filter((k) => !keys(ru).includes(k)),
    )
    expect(missing).toEqual([])
  })
})
