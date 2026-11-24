import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {account} from '@/test/fixtures'
import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'

import {EmailForm} from './EmailForm'

describe('EmailForm', () => {
  it('sends a confirmation link to the new address', async () => {
    const calls = mockApi({
      'GET /api/v1/mail': {enabled: true},
      'POST /api/v1/me/email': {email: 'alex@example.org', expires_at: '2026-01-02T10:00:00Z'},
    })
    renderAt('/', <Route path="/" element={<EmailForm account={account()} />} />)

    fireEvent.change(await screen.findByLabelText('Email'), {target: {value: 'Alex@Example.org'}})
    fireEvent.click(screen.getByRole('button', {name: 'Send the link'}))

    expect(await screen.findByRole('status')).toHaveTextContent('A link went to alex@example.org.')
    expect(calls.at(-1)?.body).toEqual({email: 'Alex@Example.org'})
  })

  it('shows the confirmed address', async () => {
    mockApi({'GET /api/v1/mail': {enabled: true}})
    renderAt('/', <Route path="/" element={<EmailForm account={account({email: 'alex@example.org'})} />} />)

    expect(await screen.findByText('alex@example.org')).toBeVisible()
    expect(screen.getByText('Confirmed')).toBeVisible()
    expect(screen.getByLabelText('New email')).toBeVisible()
  })

  it('says an address cannot be confirmed without outgoing mail', async () => {
    mockApi({'GET /api/v1/mail': {enabled: false}})
    renderAt('/', <Route path="/" element={<EmailForm account={account()} />} />)

    expect(await screen.findByText(/sends no email yet/)).toBeVisible()
    expect(screen.queryByRole('button', {name: 'Send the link'})).toBeNull()
  })

  it('says when another account has the address', async () => {
    mockApi({'GET /api/v1/mail': {enabled: true}, 'POST /api/v1/me/email': problem(409, 'email_taken')})
    renderAt('/', <Route path="/" element={<EmailForm account={account()} />} />)

    fireEvent.change(await screen.findByLabelText('Email'), {target: {value: 'taken@example.org'}})
    fireEvent.click(screen.getByRole('button', {name: 'Send the link'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('Another account uses this address.')
  })
})
