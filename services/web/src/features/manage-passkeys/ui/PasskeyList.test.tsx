import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {type Passkey} from '@/entities/account'
import {mockApi, problem, SECOND_FACTOR_FINE} from '@/test/api'
import {renderAt} from '@/test/render'
import {ASSERTION_JSON, mockPasskeys} from '@/test/webauthn'

import {PasskeyList} from './PasskeyList'

const PHONE: Passkey = {
  id: 'phone',
  name: 'Safari on iPhone',
  created_at: '2026-01-01T10:00:00Z',
  last_used_at: '2026-01-02T10:00:00Z',
}
const KEY: Passkey = {id: 'key', name: 'Security key', created_at: '2026-01-03T10:00:00Z', last_used_at: null}

function renderList() {
  renderAt('/', <Route path="/" element={<PasskeyList />} />)
}

describe('PasskeyList', () => {
  it('shows when each passkey was added and last used', async () => {
    vi.useFakeTimers({now: new Date('2026-01-05T10:00:00Z'), toFake: ['Date']})
    mockApi({...SECOND_FACTOR_FINE, 'GET /api/v1/me/passkeys': [PHONE, KEY]})
    renderList()

    const rows = await screen.findAllByRole('listitem')

    expect(rows.map((row) => row.textContent)).toEqual([
      'Safari on iPhoneAdded January 1, 2026 at 11:00 AM · last used 3 days agoRenameRemove',
      'Security keyAdded January 3, 2026 at 11:00 AM · never usedRenameRemove',
    ])
  })

  it('says when there are none', async () => {
    mockApi({...SECOND_FACTOR_FINE, 'GET /api/v1/me/passkeys': []})
    renderList()

    expect(await screen.findByText('No passkeys yet.')).toBeVisible()
  })

  it('renames a passkey', async () => {
    let passkeys = [PHONE]
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      'GET /api/v1/me/passkeys': () => passkeys,
      'PATCH /api/v1/me/passkeys/phone': () => {
        passkeys = [{...PHONE, name: 'My phone'}]
        return passkeys[0]
      },
    })
    renderList()

    fireEvent.click(await screen.findByRole('button', {name: 'Rename Safari on iPhone'}))
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: '  My phone '}})
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(await screen.findByText('My phone')).toBeVisible()
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({name: 'My phone'})
  })

  it('removes a passkey once confirmed, confirming it is you with a passkey when asked', async () => {
    let recent = false
    let passkeys = [PHONE, KEY]
    const browser = mockPasskeys()
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      'GET /api/v1/me/passkeys': () => passkeys,
      'DELETE /api/v1/me/passkeys/key': () => {
        if (!recent) return problem(403, 'recent_sign_in_required')
        passkeys = [PHONE]
        return new Response(null, {status: 204})
      },
      'POST /api/v1/me/reauthenticate/passkey/options': {
        challenge_id: '00000000-0000-4000-8000-0000000000c1',
        options: {
          rpId: 'localhost',
          challenge: 'Y2hhbGxlbmdl',
          allowCredentials: [{id: 'cGhvbmU', type: 'public-key'}],
        },
      },
      'POST /api/v1/me/reauthenticate/passkey': () => {
        recent = true
        return new Response(null, {status: 204})
      },
    })
    renderList()

    fireEvent.click(await screen.findByRole('button', {name: 'Remove Security key'}))
    fireEvent.click(
      within(screen.getByRole('dialog', {name: 'Remove Security key?'})).getByRole('button', {name: 'Remove'}),
    )
    const confirm = await screen.findByRole('dialog', {name: "Confirm it's you"})
    fireEvent.click(await within(confirm).findByRole('button', {name: 'Use a passkey'}))

    await expect.poll(() => screen.queryByText('Security key')).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(browser.get).toHaveBeenCalledOnce()
    expect(calls.find((call) => call.path === '/api/v1/me/reauthenticate/passkey')?.body).toEqual({
      challenge_id: '00000000-0000-4000-8000-0000000000c1',
      credential: ASSERTION_JSON,
    })
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(2)
  })

  it('keeps a passkey that is the only way to sign in', async () => {
    mockApi({
      ...SECOND_FACTOR_FINE,
      'GET /api/v1/me/passkeys': [PHONE],
      'DELETE /api/v1/me/passkeys/phone': problem(409, 'last_sign_in_method'),
    })
    renderList()

    fireEvent.click(await screen.findByRole('button', {name: 'Remove Safari on iPhone'}))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', {name: 'Remove'}))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This passkey is your only way to sign in, so it cannot be removed.',
    )
  })
})
