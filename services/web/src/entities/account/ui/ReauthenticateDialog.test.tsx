import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi, SECOND_FACTOR_FINE} from '@/test/api'
import {renderAt} from '@/test/render'

import {ReauthenticateDialog} from './ReauthenticateDialog'

const PROVIDER = {'GET /api/v1/auth/config': {oidc: {name: 'Authentik'}}, 'GET /api/v1/me/passkeys': []}
const LINKED_WITHOUT_PASSWORD = {
  'GET /api/v1/me/sign-in-methods': {
    password: false,
    external_identities: [{id: 'identity', email: null, created_at: '2026-11-24T10:00:00Z'}],
  },
}
const APP_ON = {
  'GET /api/v1/me/second-factor': {...SECOND_FACTOR_FINE['GET /api/v1/me/second-factor'], totp_enabled: true},
}

function leaveFrom(pathname: string) {
  const assign = vi.fn()
  vi.stubGlobal('location', {...window.location, pathname, search: '?tab=people', assign})
  return assign
}

function renderDialog() {
  renderAt('/', <Route path="/" element={<ReauthenticateDialog onConfirmed={() => {}} onClose={() => {}} />} />)
}

describe('ReauthenticateDialog', () => {
  it('confirms with the provider and comes back to the page it was asked on', async () => {
    const assign = leaveFrom('/homes/1/people')
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      ...PROVIDER,
      ...LINKED_WITHOUT_PASSWORD,
      'POST /api/v1/me/reauthenticate/oidc': {url: 'https://auth.example.org/authorize'},
    })
    renderDialog()

    fireEvent.click(await screen.findByRole('button', {name: 'Continue with Authentik'}))

    await expect.poll(() => assign.mock.calls).toEqual([['https://auth.example.org/authorize']])
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({return_to: '/homes/1/people?tab=people'})
  })

  it('sends the code of the authenticator app along, also when the person presses Enter in it', async () => {
    leaveFrom('/account')
    const calls = mockApi({
      ...APP_ON,
      ...PROVIDER,
      ...LINKED_WITHOUT_PASSWORD,
      'POST /api/v1/me/reauthenticate/oidc': {url: 'https://auth.example.org/authorize'},
    })
    renderDialog()

    const code = await screen.findByLabelText('Code from the app')
    fireEvent.change(code, {target: {value: '123456'}})
    fireEvent.submit(code)

    await expect
      .poll(() => calls.filter((call) => call.method === 'POST').map((call) => call.body))
      .toEqual([{return_to: '/account?tab=people', code: '123456'}])
    expect(screen.queryByLabelText('Password')).toBeNull()
  })
})
