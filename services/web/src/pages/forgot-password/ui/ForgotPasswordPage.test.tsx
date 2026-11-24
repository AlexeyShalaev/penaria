import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {renderAt} from '@/test/render'

import {ForgotPasswordPage} from './ForgotPasswordPage'

function renderPage() {
  renderAt('/forgot-password', <Route path="/forgot-password" element={<ForgotPasswordPage />} />)
}

describe('ForgotPasswordPage', () => {
  it('asks for a reset link and answers the same whoever it was for', async () => {
    const calls = mockApi({
      'GET /api/v1/mail': {enabled: true},
      'POST /api/v1/password-reset:request': new Response(null, {status: 204}),
    })
    renderPage()

    fireEvent.change(await screen.findByLabelText('Username or email'), {target: {value: ' anna@example.org '}})
    fireEvent.click(screen.getByRole('button', {name: 'Send the link'}))

    expect(await screen.findByRole('status')).toHaveTextContent('If an account with a confirmed email matches')
    expect(calls.at(-1)?.body).toEqual({login: 'anna@example.org'})
  })

  it('without email, says who can make a reset link', async () => {
    mockApi({'GET /api/v1/mail': {enabled: false}})
    renderPage()

    expect(await screen.findByText(/Ask an admin of your home for a reset link/)).toBeVisible()
    expect(screen.queryByRole('button', {name: 'Send the link'})).toBeNull()
  })
})
