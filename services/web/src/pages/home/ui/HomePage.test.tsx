import {render, screen} from '@testing-library/react'
import {afterEach, describe, expect, it} from 'vitest'

import {i18n, initI18n} from '@/shared/i18n'

import {HomePage} from './HomePage'

describe('HomePage', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it.each([
    ['en', 'Your home: things, rooms, documents and devices in one place.'],
    ['ru', 'Ваш дом: вещи, комнаты, документы и устройства в одном месте.'],
  ] as const)('shows the subtitle in %s', async (language, subtitle) => {
    await initI18n(language)

    render(<HomePage />)

    expect(screen.getByText(subtitle)).toBeInTheDocument()
  })
})
