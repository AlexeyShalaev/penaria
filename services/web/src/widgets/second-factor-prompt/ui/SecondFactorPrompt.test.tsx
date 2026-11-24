import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi} from '@/test/api'
import {mockPasskeys} from '@/test/webauthn'
import {renderAt} from '@/test/render'

import {SecondFactorPrompt} from './SecondFactorPrompt'

const MISSING = {totp_enabled: false, totp_enabled_at: null, recovery_codes_left: null, required: true, missing: true}
const ENROLMENT = {
  secret: 'JBSWY3DPEHPK3PXP',
  uri: 'otpauth://totp/Penaria:owner@home.example.org?secret=JBSWY3DPEHPK3PXP&issuer=Penaria',
  expires_at: '2026-01-01T10:10:00Z',
}

function renderPrompt() {
  renderAt('/', <Route path="/" element={<SecondFactorPrompt />} />)
}

describe('SecondFactorPrompt', () => {
  it('asks an owner without a second factor to add one, and stays until the recovery codes are saved', async () => {
    let status: object = MISSING
    mockApi({
      'GET /api/v1/me/second-factor': () => status,
      'POST /api/v1/me/totp': ENROLMENT,
      'POST /api/v1/me/totp:confirm': () => {
        status = {...MISSING, totp_enabled: true, recovery_codes_left: 10, missing: false}
        return {codes: ['aaaa-bbbb-cccc-dddd']}
      },
    })
    renderPrompt()

    const prompt = await screen.findByRole('dialog', {name: 'Add a second step to sign in'})
    expect(within(prompt).getByRole('button', {name: 'Sign out'})).toBeVisible()
    fireEvent.click(within(prompt).getByRole('button', {name: 'Set up an authenticator app'}))
    fireEvent.change(await screen.findByLabelText('Code from the app'), {target: {value: '123456'}})
    fireEvent.click(screen.getByRole('button', {name: 'Turn on'}))

    expect(await screen.findByRole('list', {name: 'Recovery codes'})).toBeVisible()
    fireEvent.click(screen.getByRole('button', {name: 'I have saved them'}))
    await expect.poll(() => screen.queryByRole('dialog')).toBeNull()
  })

  it('shows nothing to an account that needs nothing', async () => {
    const calls = mockApi({'GET /api/v1/me/second-factor': {...MISSING, required: false, missing: false}})
    renderPrompt()

    await vi.waitFor(() => expect(calls).toHaveLength(1))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('goes once a passkey is added', async () => {
    let status: object = MISSING
    mockPasskeys()
    mockApi({
      'GET /api/v1/me/second-factor': () => status,
      'GET /api/v1/me/passkeys': [],
      'POST /api/v1/me/passkeys/options': {
        challenge_id: '00000000-0000-4000-8000-0000000000c1',
        options: {
          rp: {id: 'localhost', name: 'Penaria'},
          user: {id: 'dXNlcg', name: 'owner', displayName: 'Alex'},
          challenge: 'Y2hhbGxlbmdl',
          pubKeyCredParams: [{type: 'public-key', alg: -7}],
          excludeCredentials: [],
        },
      },
      'POST /api/v1/me/passkeys': () => {
        status = {...MISSING, missing: false}
        return {
          id: '00000000-0000-4000-8000-0000000000b1',
          name: 'Passkey',
          created_at: '2026-01-01T10:00:00Z',
          last_used_at: null,
        }
      },
    })
    renderPrompt()

    const prompt = await screen.findByRole('dialog', {name: 'Add a second step to sign in'})
    fireEvent.click(within(prompt).getByRole('button', {name: 'Add a passkey'}))

    await expect.poll(() => screen.queryByRole('dialog')).toBeNull()
  })
})
