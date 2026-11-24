import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'

import {ResetPasswordPage} from './ResetPasswordPage'

const PREVIEW = {
  username: 'anna',
  display_name: 'Anna',
  passkeys: [{name: 'Phone', created_at: '2026-01-01T10:00:00Z', last_used_at: null}],
}

function renderPage() {
  renderAt('/reset-password/tok', <Route path="/reset-password/:token" element={<ResetPasswordPage />} />)
}

function choose(password: string, repeated = password) {
  fireEvent.change(screen.getByLabelText('New password'), {target: {value: password}})
  fireEvent.change(screen.getByLabelText('Repeat the new password'), {target: {value: repeated}})
  fireEvent.click(screen.getByRole('button', {name: 'Set the password'}))
}

describe('ResetPasswordPage', () => {
  it('shows whose password it sets and the passkeys it keeps', async () => {
    mockApi({'POST /api/v1/password-reset:preview': PREVIEW})
    renderPage()

    expect(await screen.findByText('Account: Anna (@anna).')).toBeVisible()
    expect(screen.getByText('Phone')).toBeVisible()
    expect(screen.getByText(/They keep working/)).toBeVisible()
  })

  it('sets the new password and sends the person to sign in', async () => {
    const calls = mockApi({
      'POST /api/v1/password-reset:preview': PREVIEW,
      'POST /api/v1/password-reset': new Response(null, {status: 204}),
    })
    renderPage()
    await screen.findByText('Account: Anna (@anna).')

    choose('a fresh new passphrase')

    expect(await screen.findByRole('status')).toHaveTextContent('every device was signed out')
    expect(screen.getByRole('link', {name: 'Sign in'})).toHaveAttribute('href', '/sign-in')
    expect(calls.at(-1)?.body).toEqual({token: 'tok', new_password: 'a fresh new passphrase'})
  })

  it('checks the passwords match before calling the server', async () => {
    const calls = mockApi({'POST /api/v1/password-reset:preview': PREVIEW})
    renderPage()
    await screen.findByText('Account: Anna (@anna).')

    choose('a fresh new passphrase', 'another one entirely')

    expect(screen.getByRole('alert')).toHaveTextContent('The passwords do not match.')
    expect(calls).toHaveLength(1)
  })

  it('says when the link no longer works and offers a new one', async () => {
    mockApi({'POST /api/v1/password-reset:preview': problem(409, 'account_link_used')})
    renderPage()

    expect(await screen.findByText('This link has already been used. Ask for a new one.')).toBeVisible()
    expect(screen.getByRole('link', {name: 'Ask for a new link'})).toHaveAttribute('href', '/forgot-password')
  })
})
