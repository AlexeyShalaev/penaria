import {fireEvent, screen, waitFor, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import type {Mailbox} from '@/entities/install'
import {i18n} from '@/shared/i18n'
import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'

import {MailboxCard} from './MailboxCard'

const OFF: Mailbox = {
  source: null,
  host: null,
  port: null,
  security: null,
  username: null,
  from_address: null,
  from_name: null,
  password_set: false,
}

const SAVED: Mailbox = {
  source: 'interface',
  host: 'smtp.example.org',
  port: 587,
  security: 'starttls',
  username: 'home@example.org',
  from_address: 'home@example.org',
  from_name: 'Our home',
  password_set: true,
}

const ENVIRONMENT: Mailbox = {...SAVED, source: 'environment', port: 465, security: 'tls'}

function renderCard(mailbox: Mailbox, ownEmail: string | null = 'admin@example.org') {
  renderAt('/', <Route path="/" element={<MailboxCard mailbox={mailbox} ownEmail={ownEmail} />} />)
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), {target: {value}})
}

describe('MailboxCard', () => {
  it('says mail is off and links are shown on screen until a mailbox is connected', () => {
    mockApi({})
    renderCard(OFF)

    expect(screen.getByText('Off')).toBeVisible()
    expect(screen.getByText(/reset and invitation links are shown on screen/)).toBeVisible()
    expect(screen.getByRole('button', {name: 'Send'})).toBeDisabled()
    expect(screen.getByText('Connect a mailbox and save it first.')).toBeVisible()
  })

  it('checks the fields before saving', () => {
    const calls = mockApi({})
    renderCard(OFF)

    type('Port', '70000')
    type('Sender address', 'home')
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(screen.getByText('Enter the server.')).toBeVisible()
    expect(screen.getByText('A port is from 1 to 65535.')).toBeVisible()
    expect(screen.getByText('This does not look like an email address.')).toBeVisible()
    expect(calls).toEqual([])
  })

  it('moves the port with the security and saves the mailbox', async () => {
    const calls = mockApi({
      'PUT /api/v1/install/mail': {...SAVED, port: 465, security: 'tls'},
      'GET /api/v1/install/mail/status': {health: 'ok', error: null},
    })
    renderCard(OFF)

    type('Server', ' smtp.example.org ')
    fireEvent.change(screen.getByLabelText('Connection security'), {target: {value: 'tls'}})
    type('Login', 'home@example.org')
    type('Password', 'app-password')
    type('Sender address', 'home@example.org')
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(screen.getByLabelText('Port')).toHaveValue('465')
    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true))
    expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({
      host: 'smtp.example.org',
      port: 465,
      security: 'tls',
      username: 'home@example.org',
      password: 'app-password',
      from_address: 'home@example.org',
      from_name: null,
    })
  })

  it('keeps the saved password write-only and says one is set', () => {
    mockApi({'GET /api/v1/install/mail/status': {health: 'ok', error: null}})
    renderCard(SAVED)

    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByLabelText('Password')).toHaveAttribute('placeholder', 'Saved; type to replace')
    expect(screen.getByText('Password is set')).toBeVisible()
  })

  it('shows the connection status', async () => {
    mockApi({'GET /api/v1/install/mail/status': {health: 'failed', error: '535 5.7.8 Bad credentials'}})
    renderCard(SAVED)

    const status = await screen.findByText('Cannot connect')
    expect(status).toHaveAttribute('title', '535 5.7.8 Bad credentials')
  })

  it('locks every field of a mailbox from the environment', () => {
    mockApi({'GET /api/v1/install/mail/status': {health: 'ok', error: null}})
    renderCard(ENVIRONMENT)

    expect(screen.getByText(/The server's environment sets this mailbox/)).toBeVisible()
    for (const label of ['Server', 'Port', 'Connection security', 'Login', 'Password', 'Sender address']) {
      expect(screen.getByLabelText(label)).toBeDisabled()
    }
    expect(screen.getAllByText('Set on the server')).toHaveLength(6)
    expect(screen.queryByRole('button', {name: 'Save'})).toBeNull()
    expect(screen.queryByRole('button', {name: 'Turn mail off'})).toBeNull()
  })

  it('sends a test email to the admin’s own address and says where it went', async () => {
    const calls = mockApi({
      'GET /api/v1/install/mail/status': {health: 'ok', error: null},
      'POST /api/v1/install/mail:test': {ok: true, error: null, reason: null, mail_id: 'm1'},
      'GET /api/v1/install/mail': SAVED,
    })
    renderCard(SAVED)

    fireEvent.click(screen.getByRole('button', {name: 'Send'}))

    expect(await screen.findByText('Sent to admin@example.org. Check the inbox.')).toBeVisible()
    expect(calls.find((call) => call.path.endsWith(':test'))?.body).toEqual({to: null})
  })

  it('shows the server’s words when the test email fails', async () => {
    mockApi({
      'GET /api/v1/install/mail/status': {health: 'ok', error: null},
      'POST /api/v1/install/mail:test': {
        ok: false,
        error: '550 5.1.1 No such user',
        reason: 'recipient_refused',
        mail_id: 'm1',
      },
      'GET /api/v1/install/mail': SAVED,
    })
    renderCard(SAVED)

    type('To', 'nobody@example.org')
    fireEvent.click(screen.getByRole('button', {name: 'Send'}))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The email was not sent. The server said:')
    expect(within(alert).getByText('550 5.1.1 No such user')).toBeVisible()
  })

  it('asks to save before testing changed settings', () => {
    mockApi({'GET /api/v1/install/mail/status': {health: 'ok', error: null}})
    renderCard(SAVED)

    type('Sender name', 'Dacha')

    expect(screen.getByText('Save your changes first: the test checks the saved settings.')).toBeVisible()
    expect(screen.getByRole('button', {name: 'Send'})).toBeDisabled()
  })

  it('asks for an address when the admin’s account has none', () => {
    mockApi({'GET /api/v1/install/mail/status': {health: 'ok', error: null}})
    renderCard(SAVED, null)

    expect(screen.getByText('Your account has no email: type the address to send the test to.')).toBeVisible()
  })

  it('says when the server’s environment locks the mailbox', async () => {
    mockApi({
      'GET /api/v1/install/mail/status': {health: 'ok', error: null},
      'PUT /api/v1/install/mail': problem(409, 'mailbox_locked'),
      'GET /api/v1/install/mail': SAVED,
    })
    renderCard(SAVED)

    type('Sender name', 'Dacha')
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('cannot be changed here')
  })

  it('speaks Russian', async () => {
    await i18n.changeLanguage('ru')
    mockApi({})
    renderCard(OFF)

    expect(screen.getByRole('heading', {name: 'Почта (SMTP)'})).toBeVisible()
    expect(screen.getByText('Выключена')).toBeVisible()
  })

  it('turns mail off', async () => {
    const calls = mockApi({
      'GET /api/v1/install/mail/status': {health: 'ok', error: null},
      'DELETE /api/v1/install/mail': new Response(null, {status: 204}),
      'GET /api/v1/install/mail': OFF,
    })
    renderCard(SAVED)

    fireEvent.click(screen.getByRole('button', {name: 'Turn mail off'}))

    await waitFor(() => expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1))
  })

  it('says it saved and empties the password field', async () => {
    mockApi({
      'GET /api/v1/install/mail/status': {health: 'ok', error: null},
      'PUT /api/v1/install/mail': SAVED,
      'GET /api/v1/install/mail': SAVED,
    })
    renderCard(SAVED)

    type('Password', 'a new app password')
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(await screen.findByRole('status')).toHaveTextContent('Saved.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
  })

  it('asks for the password again when the server changes', () => {
    const calls = mockApi({'GET /api/v1/install/mail/status': {health: 'ok', error: null}})
    renderCard(SAVED)

    type('Server', 'smtp.elsewhere.org')
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(screen.getByText('The server or the login changed: enter the password again.')).toBeVisible()
    expect(calls.filter((call) => call.method === 'PUT')).toEqual([])
  })
})
