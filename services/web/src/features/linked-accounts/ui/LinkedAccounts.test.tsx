import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi, problem, SECOND_FACTOR_FINE} from '@/test/api'
import {renderAt} from '@/test/render'

import {LinkedAccounts} from './LinkedAccounts'

const LINKED = {
  password: true,
  external_identities: [{id: 'identity', email: 'alex@example.org', created_at: '2026-11-24T10:00:00Z'}],
}

function renderCard() {
  renderAt('/account', <Route path="/account" element={<LinkedAccounts provider="Authentik" />} />)
}

describe('LinkedAccounts', () => {
  it('links an account after the person confirms it is them, then leaves for the provider', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', {...window.location, assign})
    let confirmed = false
    mockApi({
      ...SECOND_FACTOR_FINE,
      'GET /api/v1/me/passkeys': [],
      'POST /api/v1/me/reauthenticate': () => {
        confirmed = true
        return new Response(null, {status: 204})
      },
      'POST /api/v1/me/external-identities:link': () =>
        confirmed ? {url: 'https://auth.example.org/authorize'} : problem(403, 'recent_sign_in_required'),
    })
    renderCard()

    expect(await screen.findByText('No Authentik account is linked.')).toBeVisible()
    fireEvent.click(screen.getByRole('button', {name: 'Link your Authentik account'}))
    const dialog = await screen.findByRole('dialog', {name: "Confirm it's you"})
    fireEvent.change(within(dialog).getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Confirm'}))

    await expect.poll(() => assign.mock.calls).toEqual([['https://auth.example.org/authorize']])
  })

  it('shows the linked account and unlinks it', async () => {
    let methods = LINKED
    const calls = mockApi({
      'GET /api/v1/me/sign-in-methods': () => methods,
      'DELETE /api/v1/me/external-identities/identity': () => {
        methods = {...LINKED, external_identities: []}
        return new Response(null, {status: 204})
      },
    })
    renderCard()

    expect(await screen.findByText(/^alex@example.org · linked/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', {name: 'Unlink the Authentik account'}))

    expect(await screen.findByText('No Authentik account is linked.')).toBeVisible()
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
  })

  it('keeps the only way to sign in, saying why', async () => {
    mockApi({
      'GET /api/v1/me/sign-in-methods': {...LINKED, password: false},
      'DELETE /api/v1/me/external-identities/identity': problem(409, 'last_sign_in_method'),
    })
    renderCard()

    fireEvent.click(await screen.findByRole('button', {name: 'Unlink the Authentik account'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('This is your only way to sign in')
  })

  it('confirms with the provider an account without a password', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', {...window.location, assign})
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      'GET /api/v1/auth/config': {oidc: {name: 'Authentik'}},
      'GET /api/v1/me/sign-in-methods': {...LINKED, password: false},
      'GET /api/v1/me/passkeys': [],
      'DELETE /api/v1/me/external-identities/identity': problem(403, 'recent_sign_in_required'),
      'POST /api/v1/me/reauthenticate/oidc': {url: 'https://auth.example.org/authorize?prompt=login'},
    })
    renderCard()

    fireEvent.click(await screen.findByRole('button', {name: 'Unlink the Authentik account'}))
    const dialog = await screen.findByRole('dialog', {name: "Confirm it's you"})
    expect(within(dialog).queryByLabelText('Password')).toBeNull()
    fireEvent.click(await within(dialog).findByRole('button', {name: 'Continue with Authentik'}))

    await expect.poll(() => assign.mock.calls).toEqual([['https://auth.example.org/authorize?prompt=login']])
    expect(calls.find((call) => call.path === '/api/v1/me/reauthenticate/oidc')?.body).toEqual({return_to: '/'})
  })
})
