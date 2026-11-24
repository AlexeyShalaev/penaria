import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi, problem, SECOND_FACTOR_FINE} from '@/test/api'
import {entity, HOME_ID, role, ROLES} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {DeviceDialog} from './DeviceDialog'

const TOKEN = 'pnr_' + 'a'.repeat(43)

function created(name: string) {
  return {
    device: {
      id: 'device',
      grant_id: 'grant',
      name,
      role: role('contractor'),
      scope: null,
      created_at: '2026-11-24T10:00:00Z',
      last_used_at: null,
      last_used_ip: null,
      granted_by: null,
    },
    token: TOKEN,
  }
}

function renderDialog() {
  renderAt('/', <Route path="/" element={<DeviceDialog homeId={HOME_ID} onClose={() => {}} />} />)
}

describe('DeviceDialog', () => {
  it('offers only the roles a device can hold', async () => {
    mockApi({[`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES})
    renderDialog()

    const roles = await screen.findByRole('group', {name: 'Role'})

    expect(
      within(roles)
        .getAllByRole('radio')
        .map((radio) => radio.getAttribute('value')),
    ).toEqual(['role-admin', 'role-family', 'role-contractor'])
    expect(within(roles).getByRole('radio', {name: /^Family member/})).toBeChecked()
  })

  it('makes a token, shows it once with a command to try it, and copies it', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', {...navigator, clipboard: {writeText}})
    const calls = mockApi({
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`POST /api/v1/homes/${HOME_ID}/devices`]: created('Backup script'),
    })
    renderDialog()

    fireEvent.change(await screen.findByLabelText('Name'), {target: {value: ' Backup script '}})
    fireEvent.click(screen.getByRole('radio', {name: /^Contractor/}))
    fireEvent.click(screen.getByRole('button', {name: 'Make the token'}))

    expect(await screen.findByRole('textbox', {name: 'Token'})).toHaveValue(TOKEN)
    expect(screen.getByLabelText('An example request')).toHaveTextContent(
      `curl -H "Authorization: Bearer ${TOKEN}" http://localhost:3000/api/v1/homes/${HOME_ID}`,
    )
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      name: 'Backup script',
      role_id: 'role-contractor',
      scope_entity_id: null,
    })
    fireEvent.click(screen.getByRole('button', {name: 'Copy the token'}))
    expect(writeText).toHaveBeenCalledWith(TOKEN)
    expect(await screen.findByRole('button', {name: 'Copied'})).toBeVisible()
  })

  it('asks the person to confirm it is them, then makes the token', async () => {
    let confirmed = false
    mockApi({
      ...SECOND_FACTOR_FINE,
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      'GET /api/v1/me/passkeys': [],
      'POST /api/v1/me/reauthenticate': () => {
        confirmed = true
        return new Response(null, {status: 204})
      },
      [`POST /api/v1/homes/${HOME_ID}/devices`]: () =>
        confirmed ? created('Mirror') : problem(403, 'recent_sign_in_required'),
    })
    renderDialog()

    fireEvent.change(await screen.findByLabelText('Name'), {target: {value: 'Mirror'}})
    fireEvent.click(screen.getByRole('button', {name: 'Make the token'}))
    const dialog = await screen.findByRole('dialog', {name: "Confirm it's you"})
    fireEvent.change(within(dialog).getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Confirm'}))

    expect(await screen.findByRole('textbox', {name: 'Token'})).toHaveValue(TOKEN)
  })

  it('says why a role is refused', async () => {
    mockApi({
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`POST /api/v1/homes/${HOME_ID}/devices`]: problem(403, 'escalation'),
    })
    renderDialog()

    fireEvent.change(await screen.findByLabelText('Name'), {target: {value: 'Mirror'}})
    fireEvent.click(screen.getByRole('button', {name: 'Make the token'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('You cannot give more access than you have yourself.')
  })

  it('gives the device one place when one is picked, and asks for it otherwise', async () => {
    const calls = mockApi({
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`GET /api/v1/homes/${HOME_ID}/entities`]: [entity({id: 'hall', name: 'Hall', kind: 'space'})],
      [`POST /api/v1/homes/${HOME_ID}/devices`]: created('Mirror'),
    })
    renderDialog()

    fireEvent.change(await screen.findByLabelText('Name'), {target: {value: 'Mirror'}})
    fireEvent.click(screen.getByRole('radio', {name: 'One place'}))
    fireEvent.click(screen.getByRole('button', {name: 'Make the token'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('Pick a place, or choose the whole home.')
    fireEvent.click(await screen.findByRole('button', {name: /^Hall/}))
    fireEvent.click(screen.getByRole('button', {name: 'Make the token'}))

    expect(await screen.findByRole('textbox', {name: 'Token'})).toHaveValue(TOKEN)
    expect(calls.find((call) => call.method === 'POST')?.body).toMatchObject({scope_entity_id: 'hall'})
  })

  it('offers no copy button where the browser has no clipboard, leaving the token to select', async () => {
    vi.stubGlobal('navigator', {...navigator, clipboard: undefined})
    mockApi({
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`POST /api/v1/homes/${HOME_ID}/devices`]: created('Mirror'),
    })
    renderDialog()

    fireEvent.change(await screen.findByLabelText('Name'), {target: {value: 'Mirror'}})
    fireEvent.click(screen.getByRole('button', {name: 'Make the token'}))

    expect(await screen.findByRole('textbox', {name: 'Token'})).toHaveValue(TOKEN)
    expect(screen.queryByRole('button', {name: 'Copy the token'})).toBeNull()
  })
})
