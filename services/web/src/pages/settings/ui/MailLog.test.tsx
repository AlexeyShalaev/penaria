import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import type {LoggedMail} from '@/entities/install'
import {mockApi} from '@/test/api'
import {renderAt} from '@/test/render'

import {MailLog} from './MailLog'

function mail(overrides: Partial<LoggedMail>): LoggedMail {
  return {
    id: 'm1',
    kind: 'password_reset',
    to: 'anna@example.org',
    subject: 'Reset your Penaria password',
    locale: 'en',
    state: 'sent',
    created_at: '2026-01-01T10:00:00Z',
    next_attempt_at: null,
    resendable: true,
    attempts: [
      {
        at: '2026-01-01T10:00:01Z',
        ok: true,
        reason: null,
        smtp_code: null,
        error: null,
        duration_ms: 80,
        manual: false,
      },
    ],
    ...overrides,
  }
}

const FAILED = mail({
  id: 'm2',
  kind: 'invitation',
  to: 'ivan@example.org',
  subject: 'Oleg invites you to Dacha in Penaria',
  state: 'failed',
  resendable: true,
  attempts: [
    {
      at: '2026-01-01T11:00:00Z',
      ok: false,
      reason: 'recipient_refused',
      smtp_code: 550,
      error: '5.1.1 No such user',
      duration_ms: 50,
      manual: false,
    },
  ],
})

describe('MailLog', () => {
  it('lists the mails with their state and the server’s words for a failure', async () => {
    mockApi({'GET /api/v1/install/mail/messages?limit=20': [FAILED, mail({})]})
    renderAt('/', <Route path="/" element={<MailLog />} />)

    expect(await screen.findByText('Oleg invites you to Dacha in Penaria')).toBeVisible()
    expect(screen.getByText('Not sent')).toBeVisible()
    expect(screen.getByText('5.1.1 No such user')).toBeVisible()
    expect(screen.getByText('Sent')).toBeVisible()
  })

  it('sends a mail again and says so', async () => {
    const calls = mockApi({
      'GET /api/v1/install/mail/messages?limit=20': [FAILED],
      'POST /api/v1/install/mail/messages/m2:resend': {ok: true, error: null, reason: null, mail_id: 'm2'},
    })
    renderAt('/', <Route path="/" element={<MailLog />} />)

    fireEvent.click(await screen.findByRole('button', {name: 'Send again'}))

    expect(await screen.findByRole('status')).toHaveTextContent('Sent again.')
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1)
  })

  it('shows every attempt of a mail', async () => {
    mockApi({'GET /api/v1/install/mail/messages?limit=20': [FAILED]})
    renderAt('/', <Route path="/" element={<MailLog />} />)

    fireEvent.click(await screen.findByRole('button', {name: '1 attempt'}))

    expect(screen.getByText('The address was refused')).toBeVisible()
    expect(screen.getByText('550 5.1.1 No such user')).toBeVisible()
  })

  it('says when no mail was sent yet', async () => {
    mockApi({'GET /api/v1/install/mail/messages?limit=20': []})
    renderAt('/', <Route path="/" element={<MailLog />} />)

    expect(await screen.findByText('No email yet')).toBeVisible()
  })

  it('shows older mail a page at a time', async () => {
    const page = Array.from({length: 20}, (_, n) => mail({id: `m${n}`, subject: `Mail ${n}`}))
    const calls = mockApi({
      'GET /api/v1/install/mail/messages?limit=20': page,
      'GET /api/v1/install/mail/messages?limit=20&before=m19': [mail({id: 'older', subject: 'An older mail'})],
    })
    renderAt('/', <Route path="/" element={<MailLog />} />)

    fireEvent.click(await screen.findByRole('button', {name: 'Show older'}))

    expect(await screen.findByText('An older mail')).toBeVisible()
    expect(screen.getByText('Mail 0')).toBeVisible()
    expect(calls).toHaveLength(2)
    expect(screen.queryByRole('button', {name: 'Show older'})).toBeNull()
  })

  it('shows when a waiting mail is tried again', async () => {
    mockApi({
      'GET /api/v1/install/mail/messages?limit=20': [
        mail({state: 'queued', resendable: false, next_attempt_at: '2099-01-01T10:00:00Z'}),
      ],
    })
    renderAt('/', <Route path="/" element={<MailLog />} />)

    expect(await screen.findByText(/^Next try/)).toBeVisible()
    expect(screen.queryByRole('button', {name: 'Send again'})).toBeNull()
  })
})
