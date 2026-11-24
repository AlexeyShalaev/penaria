import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
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
  it('offers a passkey first, and the password below it', async () => {
    mockPasskeys()
    mockApi(SIGNED_OUT)
    renderPage()

    const passkey = await screen.findByRole('button', {name: 'Sign in with a passkey'})

    expect(screen.getByText('or with your username and password')).toBeVisible()
    expect(screen.getByRole('button', {name: 'Sign in'})).toBeVisible()
    expect(passkey.compareDocumentPosition(screen.getByLabelText('Username'))).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  it('offers only the password where passkeys do not work', async () => {
    mockApi(SIGNED_OUT)
    renderPage()

    expect(await screen.findByRole('button', {name: 'Sign in'})).toBeVisible()
    expect(screen.queryByRole('button', {name: 'Sign in with a passkey'})).toBeNull()
  })

  it('returns to the page asked for after signing in with a passkey', async () => {
    mockPasskeys()
    mockApi({
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
})
