import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'
import {mockPasskeys} from '@/test/webauthn'

import {PasskeySuggestion} from './PasskeySuggestion'

const ACCOUNT_ID = account().id
const PASSKEY = {id: 'phone', name: 'Phone', created_at: '2026-01-01T10:00:00Z', last_used_at: null}

function renderSuggestion() {
  return renderAt('/', <Route path="/" element={<PasskeySuggestion accountId={ACCOUNT_ID} />} />)
}

describe('PasskeySuggestion', () => {
  it('suggests a passkey to an account that signs in with its password', async () => {
    mockPasskeys()
    mockApi({'GET /api/v1/me/passkeys': []})
    renderSuggestion()

    expect(await screen.findByRole('region', {name: 'Sign in faster with a passkey'})).toBeVisible()
    expect(screen.getByRole('button', {name: 'Add a passkey'})).toBeVisible()
  })

  it('remembers that the person said not now', async () => {
    mockPasskeys()
    mockApi({'GET /api/v1/me/passkeys': []})
    const {unmount} = renderSuggestion()

    fireEvent.click(await screen.findByRole('button', {name: 'Not now'}))
    expect(screen.queryByRole('region')).toBeNull()
    unmount()
    const calls = mockApi({})
    renderSuggestion()

    expect(screen.queryByRole('region')).toBeNull()
    expect(calls).toEqual([])
  })

  it('stays away from an account that has a passkey', async () => {
    mockPasskeys()
    const calls = mockApi({'GET /api/v1/me/passkeys': [PASSKEY]})
    renderSuggestion()

    await expect.poll(() => calls.length).toBe(1)
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('stays away where passkeys do not work', () => {
    const calls = mockApi({})
    renderSuggestion()

    expect(screen.queryByRole('region')).toBeNull()
    expect(calls).toEqual([])
  })
})
