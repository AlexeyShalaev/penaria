import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {SignInForm} from './SignInForm'

function renderForm() {
  const onSignedIn = vi.fn()
  renderAt('/', <Route path="/" element={<SignInForm onSignedIn={onSignedIn} />} />)
  return onSignedIn
}

function signIn(password = 'correct horse battery') {
  fireEvent.change(screen.getByLabelText('Username'), {target: {value: 'owner'}})
  fireEvent.change(screen.getByLabelText('Password'), {target: {value: password}})
  fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))
}

describe('SignInForm', () => {
  it('signs in', async () => {
    mockApi({'POST /api/v1/sign-in': account()})
    const onSignedIn = renderForm()

    signIn()

    await vi.waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    expect(onSignedIn.mock.calls[0]?.[0]).toEqual(account())
  })

  it('says the username or the password is wrong, without telling which', async () => {
    mockApi({'POST /api/v1/sign-in': problem(401, 'invalid_credentials')})
    renderForm()

    signIn('not the password')

    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password.')
  })

  it('says how long to wait after too many failures', async () => {
    mockApi({
      'POST /api/v1/sign-in': new Response(
        JSON.stringify({status: 429, code: 'too_many_attempts', params: {retry_after_seconds: 241}}),
        {status: 429, headers: {'Content-Type': 'application/problem+json'}},
      ),
    })
    renderForm()

    signIn()

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many failed attempts. Try again in 5 minutes.')
  })
})
