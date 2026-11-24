import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {SecondFactorForm} from './SecondFactorForm'

const CHALLENGE = {token: 'pending-token', expires_at: '2026-01-01T10:05:00Z'}

function renderForm() {
  const onSignedIn = vi.fn()
  const onBack = vi.fn()
  renderAt(
    '/',
    <Route path="/" element={<SecondFactorForm challenge={CHALLENGE} onSignedIn={onSignedIn} onBack={onBack} />} />,
  )
  return {onSignedIn, onBack}
}

describe('SecondFactorForm', () => {
  it('signs in with a code from the app', async () => {
    const calls = mockApi({'POST /api/v1/sign-in/second-factor': account()})
    const {onSignedIn} = renderForm()

    fireEvent.change(screen.getByLabelText('Code from the app'), {target: {value: '123 456'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))

    await vi.waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    expect(calls[0]?.body).toEqual({token: 'pending-token', code: '123 456'})
  })

  it('signs in with a recovery code instead', async () => {
    const calls = mockApi({'POST /api/v1/sign-in/second-factor': account()})
    const {onSignedIn} = renderForm()

    fireEvent.click(screen.getByRole('button', {name: 'Use a recovery code'}))
    expect(screen.getByText('Enter one of your recovery codes. Each code works once.')).toBeVisible()
    fireEvent.change(screen.getByLabelText('Recovery code'), {target: {value: ' 7kq2-m9xd-3hfa-wp0e '}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))

    await vi.waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    expect(calls[0]?.body).toEqual({token: 'pending-token', recovery_code: ' 7kq2-m9xd-3hfa-wp0e '})
  })

  it('says a wrong code is wrong', async () => {
    mockApi({'POST /api/v1/sign-in/second-factor': problem(400, 'wrong_code')})
    renderForm()

    fireEvent.change(screen.getByLabelText('Code from the app'), {target: {value: '000000'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('The code is wrong or was already used.')
  })

  it('sends the person back to the password when the step took too long', async () => {
    mockApi({'POST /api/v1/sign-in/second-factor': problem(401, 'second_factor_expired')})
    const {onBack} = renderForm()

    fireEvent.change(screen.getByLabelText('Code from the app'), {target: {value: '123456'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('Signing in took too long.')
    expect(screen.queryByRole('button', {name: 'Sign in'})).toBeNull()
    fireEvent.click(screen.getByRole('button', {name: 'Back'}))
    expect(onBack).toHaveBeenCalled()
  })
})
