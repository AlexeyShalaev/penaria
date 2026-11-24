import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {afterEach, describe, expect, it, vi} from 'vitest'

import {MAIL_OFF, mockApi, problem} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'
import {mockPasskeys} from '@/test/webauthn'

import {SignInPage} from './SignInPage'

function renderPage() {
  renderAt(
    '/sign-in?next=/account',
    <>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/account" element={<h1>Account</h1>} />
    </>,
  )
}

const SIGNED_OUT = {'GET /api/v1/setup': {needed: false}, 'GET /api/v1/me': problem(401, 'unauthenticated')}

describe('SignInPage', () => {
  afterEach(() => window.history.replaceState(null, '', '/'))

  it('offers a passkey first, and the password below it', async () => {
    mockPasskeys()
    mockApi({...MAIL_OFF, ...SIGNED_OUT})
    renderPage()

    const passkey = await screen.findByRole('button', {name: 'Sign in with a passkey'})

    expect(screen.getByText('or with your username and password')).toBeVisible()
    expect(screen.getByRole('button', {name: 'Sign in'})).toBeVisible()
    expect(passkey.compareDocumentPosition(screen.getByLabelText('Username'))).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  it('offers a reset by email when the install sends email', async () => {
    mockApi({...SIGNED_OUT, 'GET /api/v1/mail': {enabled: true}})
    renderPage()

    expect(await screen.findByRole('link', {name: 'Forgot your password?'})).toHaveAttribute('href', '/forgot-password')
  })

  it('offers no reset by email when the install sends none', async () => {
    mockApi({...MAIL_OFF, ...SIGNED_OUT})
    renderPage()

    await screen.findByRole('button', {name: 'Sign in'})
    expect(screen.queryByRole('link', {name: 'Forgot your password?'})).toBeNull()
  })

  it('offers only the password where passkeys do not work', async () => {
    mockApi({...MAIL_OFF, ...SIGNED_OUT})
    renderPage()

    expect(await screen.findByRole('button', {name: 'Sign in'})).toBeVisible()
    expect(screen.queryByRole('button', {name: 'Sign in with a passkey'})).toBeNull()
  })

  it('returns to the page asked for after signing in with a passkey', async () => {
    mockPasskeys()
    mockApi({
      ...MAIL_OFF,
      ...SIGNED_OUT,
      'POST /api/v1/sign-in/passkey/options': {
        challenge_id: '00000000-0000-4000-8000-0000000000c1',
        options: {rpId: 'localhost', challenge: 'Y2hhbGxlbmdl', allowCredentials: []},
      },
      'POST /api/v1/sign-in/passkey': account(),
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', {name: 'Sign in with a passkey'}))

    expect(await screen.findByRole('heading', {name: 'Account'})).toBeVisible()
  })

  it('asks for the code of an account with an authenticator app, then returns to the page asked for', async () => {
    const calls = mockApi({
      ...MAIL_OFF,
      ...SIGNED_OUT,
      'POST /api/v1/sign-in': new Response(JSON.stringify({token: 'pending', expires_at: '2026-01-01T10:05:00Z'}), {
        status: 202,
        headers: {'Content-Type': 'application/json'},
      }),
      'POST /api/v1/sign-in/second-factor': account(),
    })
    renderPage()

    fireEvent.change(await screen.findByLabelText('Username'), {target: {value: 'owner'}})
    fireEvent.change(screen.getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))
    expect(await screen.findByRole('heading', {name: 'Two-step sign-in'})).toBeVisible()
    fireEvent.change(screen.getByLabelText('Code from the app'), {target: {value: '123456'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))

    expect(await screen.findByRole('heading', {name: 'Account'})).toBeVisible()
    expect(calls.at(-1)?.body).toEqual({token: 'pending', code: '123456'})
  })

  it('goes back to the password from the code', async () => {
    mockApi({
      ...MAIL_OFF,
      ...SIGNED_OUT,
      'POST /api/v1/sign-in': new Response(JSON.stringify({token: 'pending', expires_at: '2026-01-01T10:05:00Z'}), {
        status: 202,
        headers: {'Content-Type': 'application/json'},
      }),
    })
    renderPage()

    fireEvent.change(await screen.findByLabelText('Username'), {target: {value: 'owner'}})
    fireEvent.change(screen.getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))
    fireEvent.click(await screen.findByRole('button', {name: 'Back'}))

    expect(await screen.findByLabelText('Username')).toBeVisible()
  })

  it("offers the operator's provider, and leaves for it to come back to the page asked for", async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', {...window.location, assign})
    const calls = mockApi({
      ...MAIL_OFF,
      ...SIGNED_OUT,
      'GET /api/v1/auth/config': {oidc: {name: 'Authentik'}},
      'POST /api/v1/auth/oidc:sign-in': {url: 'https://auth.example.org/authorize?state=s'},
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', {name: 'Sign in with Authentik'}))

    await expect.poll(() => assign.mock.calls).toEqual([['https://auth.example.org/authorize?state=s']])
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({locale: 'en', return_to: '/account'})
    expect(screen.getByText('or with your username and password')).toBeVisible()
  })

  it('asks for the code when the provider signed in an account with an authenticator app', async () => {
    window.history.replaceState(null, '', '/sign-in#second-factor=pending&until=2099-01-01T00%3A00%3A00Z')
    mockApi({...MAIL_OFF, ...SIGNED_OUT})
    renderPage()

    expect(await screen.findByRole('heading', {name: 'Two-step sign-in'})).toBeVisible()
    expect(window.location.hash).toBe('')
  })
})
