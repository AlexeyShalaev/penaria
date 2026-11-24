import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'

import {TwoStepSignIn} from './TwoStepSignIn'

const OFF = {totp_enabled: false, totp_enabled_at: null, recovery_codes_left: null, required: true, missing: true}
const ON = {
  totp_enabled: true,
  totp_enabled_at: '2026-01-01T10:00:00Z',
  recovery_codes_left: 10,
  required: true,
  missing: false,
}
const ENROLMENT = {
  secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
  uri: 'otpauth://totp/Penaria:owner@home.example.org?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Penaria',
  expires_at: '2026-01-01T10:10:00Z',
}
const CODES = Array.from({length: 10}, (_, i) => `code-000${i}-aaaa-bbbb`)

function renderCard() {
  renderAt('/', <Route path="/" element={<TwoStepSignIn />} />)
}

describe('TwoStepSignIn', () => {
  it('sets the app up with its QR code and key, then shows the recovery codes until they are saved', async () => {
    let status: object = OFF
    const calls = mockApi({
      'GET /api/v1/me/second-factor': () => status,
      'POST /api/v1/me/totp': ENROLMENT,
      'POST /api/v1/me/totp:confirm': () => {
        status = ON
        return {codes: CODES}
      },
    })
    renderCard()

    fireEvent.click(await screen.findByRole('button', {name: 'Set up an authenticator app'}))
    expect(await screen.findByRole('img', {name: 'QR code for the authenticator app'})).toBeVisible()
    expect(screen.getByLabelText('Key')).toHaveTextContent('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP')
    fireEvent.change(screen.getByLabelText('Code from the app'), {target: {value: '123 456'}})
    fireEvent.click(screen.getByRole('button', {name: 'Turn on'}))

    const list = await screen.findByRole('list', {name: 'Recovery codes'})
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual(CODES)
    expect(calls.find((call) => call.path === '/api/v1/me/totp:confirm')?.body).toEqual({code: '123456'})
    fireEvent.click(screen.getByRole('button', {name: 'I have saved them'}))
    expect(await screen.findByText('Two-step sign-in is on')).toBeVisible()
    expect(screen.getByText(/10 recovery codes left/)).toBeVisible()
  })

  it('says a wrong first code is wrong', async () => {
    mockApi({
      'GET /api/v1/me/second-factor': OFF,
      'POST /api/v1/me/totp': ENROLMENT,
      'POST /api/v1/me/totp:confirm': problem(400, 'wrong_code'),
    })
    renderCard()

    fireEvent.click(await screen.findByRole('button', {name: 'Set up an authenticator app'}))
    fireEvent.change(await screen.findByLabelText('Code from the app'), {target: {value: '000000'}})
    fireEvent.click(screen.getByRole('button', {name: 'Turn on'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('The code is wrong or was already used.')
  })

  it('asks for the password and a code before new recovery codes when the sign-in is not recent', async () => {
    let recent = false
    const calls = mockApi({
      'GET /api/v1/me/second-factor': ON,
      'GET /api/v1/me/passkeys': [],
      'POST /api/v1/me/totp/recovery-codes': () => (recent ? {codes: CODES} : problem(403, 'recent_sign_in_required')),
      'POST /api/v1/me/reauthenticate': () => {
        recent = true
        return new Response(null, {status: 204})
      },
    })
    renderCard()

    fireEvent.click(await screen.findByRole('button', {name: 'New recovery codes'}))
    const dialog = await screen.findByRole('dialog', {name: "Confirm it's you"})
    fireEvent.change(within(dialog).getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.change(within(dialog).getByLabelText('Code from the app'), {target: {value: '654321'}})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Confirm'}))

    expect(await screen.findByRole('list', {name: 'Recovery codes'})).toBeVisible()
    expect(calls.find((call) => call.path === '/api/v1/me/reauthenticate')?.body).toEqual({
      password: 'correct horse battery',
      code: '654321',
    })
  })

  it('says an owner without a passkey keeps the app', async () => {
    mockApi({
      'GET /api/v1/me/second-factor': ON,
      'DELETE /api/v1/me/totp': problem(409, 'last_second_factor'),
    })
    renderCard()

    fireEvent.click(await screen.findByRole('button', {name: 'Turn off'}))
    const dialog = await screen.findByRole('dialog', {name: 'Turn off two-step sign-in?'})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Turn off'}))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Add a passkey before you turn the authenticator app off.',
    )
  })

  it('turns the app off', async () => {
    let status: object = ON
    mockApi({
      'GET /api/v1/me/second-factor': () => status,
      'DELETE /api/v1/me/totp': () => {
        status = OFF
        return new Response(null, {status: 204})
      },
    })
    renderCard()

    fireEvent.click(await screen.findByRole('button', {name: 'Turn off'}))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', {name: 'Turn off'}))

    expect(await screen.findByRole('button', {name: 'Set up an authenticator app'})).toBeVisible()
  })
})
