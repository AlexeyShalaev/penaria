import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'
import {mockPasskeys, NEW_CREDENTIAL_JSON, refuse} from '@/test/webauthn'

import {AddPasskeyButton} from './AddPasskeyButton'

const IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
const CHALLENGE_ID = '00000000-0000-4000-8000-0000000000c1'
const OPTIONS = {
  challenge_id: CHALLENGE_ID,
  options: {
    rp: {id: 'localhost', name: 'Penaria'},
    user: {id: 'dXNlcg', name: 'owner', displayName: 'Alex'},
    challenge: 'Y2hhbGxlbmdl',
    pubKeyCredParams: [{type: 'public-key', alg: -7}],
    excludeCredentials: [],
  },
}
const ADDED = {
  id: '00000000-0000-4000-8000-0000000000b1',
  name: 'Safari on iPhone',
  created_at: '2026-01-01T10:00:00Z',
  last_used_at: null,
}

function renderButton() {
  renderAt('/', <Route path="/" element={<AddPasskeyButton />} />)
}

describe('AddPasskeyButton', () => {
  it('adds a passkey named after the browser and the phone', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(IPHONE)
    mockPasskeys()
    const calls = mockApi({
      'POST /api/v1/me/passkeys/options': OPTIONS,
      'POST /api/v1/me/passkeys': ADDED,
    })
    renderButton()

    fireEvent.click(screen.getByRole('button', {name: 'Add a passkey'}))

    expect(await screen.findByRole('status')).toHaveTextContent('The passkey is added. Next time, sign in with it.')
    expect(calls.at(-1)?.body).toEqual({
      challenge_id: CHALLENGE_ID,
      credential: NEW_CREDENTIAL_JSON,
      name: 'Safari on iPhone',
    })
  })

  it('asks to confirm it is you when the sign-in is not recent, then adds the passkey', async () => {
    let recent = false
    mockPasskeys()
    const calls = mockApi({
      'POST /api/v1/me/passkeys/options': () => (recent ? OPTIONS : problem(403, 'recent_sign_in_required')),
      'POST /api/v1/me/reauthenticate': () => {
        recent = true
        return new Response(null, {status: 204})
      },
      'GET /api/v1/me/passkeys': [],
      'POST /api/v1/me/passkeys': ADDED,
    })
    renderButton()

    fireEvent.click(screen.getByRole('button', {name: 'Add a passkey'}))
    const dialog = await screen.findByRole('dialog', {name: "Confirm it's you"})
    expect(screen.queryByRole('alert')).toBeNull()
    fireEvent.change(within(dialog).getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Confirm'}))

    expect(await screen.findByRole('status')).toHaveTextContent('The passkey is added.')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls.find((call) => call.path === '/api/v1/me/reauthenticate')?.body).toEqual({
      password: 'correct horse battery',
    })
  })

  it('says when this device already keeps a passkey for the account', async () => {
    mockPasskeys({create: refuse('InvalidStateError')})
    mockApi({'POST /api/v1/me/passkeys/options': OPTIONS})
    renderButton()

    fireEvent.click(screen.getByRole('button', {name: 'Add a passkey'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('This device already keeps a passkey for your account.')
  })
})
