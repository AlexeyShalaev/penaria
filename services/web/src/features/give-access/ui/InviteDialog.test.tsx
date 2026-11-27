import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {MAIL_OFF, mockApi, problem, SECOND_FACTOR_FINE} from '@/test/api'
import {HOME_ID, role, ROLES} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {InviteDialog} from './InviteDialog'

const URL = 'http://localhost:5173/invite/secret-token'

function created(preset: 'family' | 'owner', overrides: Record<string, unknown> = {}) {
  return {
    invitation: {
      id: 'invitation',
      role: role(preset),
      scope: null,
      expires_at: '2026-12-01T10:00:00Z',
      grant_expires_at: null,
      leave_when_accepted: false,
      created_at: '2026-11-24T10:00:00Z',
      created_by: {id: 'me', username: 'owner', display_name: 'Alex'},
      ...overrides,
    },
    url: URL,
  }
}

function renderDialog(owner: boolean) {
  renderAt('/', <Route path="/" element={<InviteDialog homeId={HOME_ID} owner={owner} onClose={() => {}} />} />)
}

const roleNames = () => screen.getAllByRole('radio').filter((r) => r.getAttribute('name') === 'role')

describe('InviteDialog', () => {
  it('offers the roles in plain words, owners only to an owner', async () => {
    mockApi({...SECOND_FACTOR_FINE, ...MAIL_OFF, [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES})
    renderDialog(false)

    await screen.findByRole('radio', {name: /Family member/})

    expect(roleNames().map((radio) => radio.closest('label')?.textContent)).toEqual([
      'AdminEverything except owners: things, devices, tasks, people and settings.',
      'Family memberAdds and changes things, sees receipts and warranties, uses devices and marks tasks done. Does not see private places.',
      'GuestSees only what is marked for guests and where it is, and uses devices. Access ends on its own.',
      'ContractorSees things and tasks and marks tasks done. Best limited to one place.',
    ])
    expect(screen.getByRole('radio', {name: /Family member/})).toBeChecked()
  })

  it('makes a family invitation and shows its link with a QR code', async () => {
    vi.stubGlobal('navigator', {...navigator, clipboard: {writeText: vi.fn()}})
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      ...MAIL_OFF,
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`POST /api/v1/homes/${HOME_ID}/invitations`]: created('family'),
    })
    renderDialog(true)

    fireEvent.click(await screen.findByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('img', {name: 'QR code of the link'})).toBeVisible()
    expect(screen.getByRole('textbox', {name: 'Link'})).toHaveValue(URL)
    expect(screen.getByRole('button', {name: 'Copy link'})).toBeVisible()
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      role_id: 'role-family',
      scope_entity_id: null,
      valid_days: 7,
      grant_expires_at: null,
      leave_when_accepted: false,
    })
  })

  it('asks a guest invitation for the end of access, three days ahead, and a link for thirty days', async () => {
    vi.setSystemTime(new Date('2026-11-24T10:00:00Z'))
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      ...MAIL_OFF,
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`POST /api/v1/homes/${HOME_ID}/invitations`]: created('family'),
    })
    renderDialog(false)

    fireEvent.click(await screen.findByRole('radio', {name: /Guest/}))
    const ends = screen.getByLabelText('Last day of access')
    fireEvent.click(screen.getByRole('radio', {name: '30 days'}))
    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))

    expect(ends).toBeRequired()
    expect(ends).toHaveValue('2026-11-27')
    await screen.findByRole('textbox', {name: 'Link'})
    // The end of that day in the browser's time zone (Europe/Berlin in the tests).
    expect(calls.find((call) => call.method === 'POST')?.body).toMatchObject({
      role_id: 'role-guest',
      valid_days: 30,
      grant_expires_at: '2026-11-27T22:59:59.000Z',
    })
  })

  it('asks for a place when the invitation covers one place', async () => {
    mockApi({
      ...SECOND_FACTOR_FINE,
      ...MAIL_OFF,
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`GET /api/v1/homes/${HOME_ID}/entities`]: [],
    })
    renderDialog(false)

    fireEvent.click(await screen.findByRole('radio', {name: 'One place'}))
    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('Pick a place, or choose the whole home.')
  })

  it('transfers ownership after the owner confirms it is them', async () => {
    let confirmed = false
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      ...MAIL_OFF,
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      'GET /api/v1/me/passkeys': [],
      'POST /api/v1/me/reauthenticate': () => {
        confirmed = true
        return new Response(null, {status: 204})
      },
      [`POST /api/v1/homes/${HOME_ID}/invitations`]: () =>
        confirmed ? created('owner', {leave_when_accepted: true}) : problem(403, 'recent_sign_in_required'),
    })
    renderDialog(true)

    fireEvent.click(await screen.findByRole('radio', {name: /^Owner/}))
    fireEvent.click(screen.getByRole('checkbox', {name: /Hand the home over/}))
    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))
    const dialog = await screen.findByRole('dialog', {name: "Confirm it's you"})
    fireEvent.change(within(dialog).getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Confirm'}))

    expect(await screen.findByRole('img', {name: 'QR code of the link'})).toBeVisible()
    const posts = calls.filter((call) => call.path.endsWith('/invitations'))
    expect(posts).toHaveLength(2)
    expect(posts[1]?.body).toMatchObject({role_id: 'role-owner', leave_when_accepted: true, scope_entity_id: null})
  })

  it('also mails the invitation when the install sends email', async () => {
    const calls = mockApi({
      ...SECOND_FACTOR_FINE,
      'GET /api/v1/mail': {enabled: true},
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`POST /api/v1/homes/${HOME_ID}/invitations`]: {...created('family'), emailed_to: 'ivan@example.org'},
    })
    renderDialog(false)

    fireEvent.change(await screen.findByLabelText('Also send to email'), {target: {value: ' ivan@example.org '}})
    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('status')).toHaveTextContent('The invitation went to ivan@example.org.')
    expect(calls.find((call) => call.method === 'POST')?.body).toMatchObject({email: 'ivan@example.org'})
  })

  it('has no email field when the install sends none', async () => {
    mockApi({...SECOND_FACTOR_FINE, ...MAIL_OFF, [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES})
    renderDialog(false)

    await screen.findByRole('radio', {name: /Family member/})

    expect(screen.queryByLabelText('Also send to email')).toBeNull()
  })
})
