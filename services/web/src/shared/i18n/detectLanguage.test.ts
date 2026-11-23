import {describe, expect, it} from 'vitest'

import {detectLanguage} from '.'

describe('detectLanguage', () => {
  it('takes the first supported language', () => {
    expect(detectLanguage(['de-DE', 'ru-RU', 'en'])).toBe('ru')
  })

  it('falls back to English', () => {
    expect(detectLanguage(['de-DE', 'fr'])).toBe('en')
  })
})
