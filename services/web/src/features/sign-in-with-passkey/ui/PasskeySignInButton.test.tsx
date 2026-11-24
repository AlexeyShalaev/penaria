import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'
import {ASSERTION_JSON, mockPasskeys, refuse} from '@/test/webauthn'

import {PasskeySignInButton} from './PasskeySignInButton'

const CHALLENGE_ID = '00000000-0000-4000-8000-0000000000c1'
const OPTIONS = {
  challenge_id: CHALLENGE_ID,
  options: {rpId: 'localhost', challenge: 'Y2hhbGxlbmdl', allowCredentials: [], userVerification: 'required'},
}

function renderButton() {
  const onSignedIn = vi.fn()
  renderAt('/', <Route path="/" element={<PasskeySignInButton onSignedIn={onSignedIn} />} />)
  return onSignedIn
}

describe('PasskeySignInButton', () => {
  it('signs in with the passkey the person picks', async () => {
    const browser = mockPasskeys()
    const calls = mockApi({
      'POST /api/v1/sign-in/passkey/options': OPTIONS,
      'POST /api/v1/sign-in/passkey': account(),
    })
    const onSignedIn = renderButton()

    fireEvent.click(screen.getByRole('button', {name: 'Sign in with a passkey'}))

    await vi.waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    expect(onSignedIn.mock.calls[0]?.[0]).toEqual(account())
    expect(browser.get).toHaveBeenCalledOnce()
    expect(calls.at(-1)?.body).toEqual({challenge_id: CHALLENGE_ID, credential: ASSERTION_JSON})
  })

  it('says no passkey was used when the person closes the prompt', async () => {
    mockPasskeys({get: refuse('NotAllowedError')})
    const calls = mockApi({'POST /api/v1/sign-in/passkey/options': OPTIONS})
    renderButton()

    fireEvent.click(screen.getByRole('button', {name: 'Sign in with a passkey'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('No passkey was used. Try again.')
    expect(calls).toHaveLength(1)
  })

  it('says the passkey does not work here when the server does not know it', async () => {
    mockPasskeys()
    mockApi({
      'POST /api/v1/sign-in/passkey/options': OPTIONS,
      'POST /api/v1/sign-in/passkey': problem(401, 'invalid_passkey'),
    })
    renderButton()

    fireEvent.click(screen.getByRole('button', {name: 'Sign in with a passkey'}))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This passkey does not work here. It may have been removed from your account: sign in with your password instead.',
    )
  })
})
