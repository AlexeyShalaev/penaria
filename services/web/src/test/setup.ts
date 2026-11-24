import '@testing-library/jest-dom/vitest'
import {cleanup} from '@testing-library/react'
import {afterEach, vi} from 'vitest'

import {i18n, initI18n} from '@/shared/i18n'

import {expectEveryCallAnswered} from './api'

await initI18n('en')

// Vitest runs without globals, so Testing Library cannot register its own cleanup.
afterEach(async () => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  sessionStorage.clear()
  localStorage.clear()
  await i18n.changeLanguage('en')
  expectEveryCallAnswered()
})
