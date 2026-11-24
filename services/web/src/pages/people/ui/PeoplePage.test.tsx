import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {home, HOME_ID, role} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {PeoplePage} from './PeoplePage'

const ME = {id: 'me', username: 'alex', display_name: 'Alex'}
const MEMBERS = [
  {
    person: ME,
    you: true,
    grants: [
      {
        id: 'g-owner',
        role: role('owner'),
        scope: null,
        expires_at: null,
        created_at: '2026-11-01T10:00:00Z',
        granted_by: null,
      },
    ],
  },
  {
    person: {id: 'maria', username: 'maria', display_name: 'Maria'},
    you: false,
    grants: [
      {
        id: 'g-maria',
        role: role('contractor'),
        scope: {id: 'kitchen', names: ['Flat', 'Kitchen']},
        expires_at: null,
        created_at: '2026-11-20T10:00:00Z',
        granted_by: ME,
      },
    ],
  },
]
const LINK = {
  id: 'link',
  grant_id: 'g-link',
  name: 'Weekend guests',
  role: role('guest'),
  scope: null,
  expires_at: '2099-11-27T10:00:00Z',
  created_at: '2026-11-24T10:00:00Z',
  last_used_at: null,
  granted_by: ME,
}

function renderPage() {
  renderAt(
    `/homes/${HOME_ID}/people`,
    <>
      <Route path="/homes/:homeId/people" element={<PeoplePage />} />
      <Route path="/" element={<h1>Start</h1>} />
    </>,
  )
}

const DEVICE = {
  id: 'device',
  grant_id: 'g-device',
  name: 'Hallway mirror',
  role: role('family'),
  scope: {id: 'hall', names: ['Flat', 'Hall']},
  created_at: '2026-11-24T10:00:00Z',
  last_used_at: '2026-11-24T10:00:00Z',
  last_used_ip: '192.0.2.44',
  granted_by: ME,
}

const INVITATION = {
  id: 'inv',
  role: role('family'),
  scope: null,
  expires_at: '2099-12-01T10:00:00Z',
  grant_expires_at: null,
  leave_when_accepted: false,
  created_at: '2026-11-24T10:00:00Z',
  created_by: ME,
}

function manager(overrides: Record<string, unknown> = {}) {
  return {
    [`GET /api/v1/homes/${HOME_ID}`]: home(),
    [`GET /api/v1/homes/${HOME_ID}/members`]: MEMBERS,
    [`GET /api/v1/homes/${HOME_ID}/invitations`]: [],
    [`GET /api/v1/homes/${HOME_ID}/guest-links`]: [],
    [`GET /api/v1/homes/${HOME_ID}/devices`]: [],
    ...overrides,
  }
}

describe('PeoplePage', () => {
  it('lists the members with their roles and places, and the guest links', async () => {
    mockApi({
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [`GET /api/v1/homes/${HOME_ID}/members`]: MEMBERS,
      [`GET /api/v1/homes/${HOME_ID}/invitations`]: [],
      [`GET /api/v1/homes/${HOME_ID}/guest-links`]: [LINK],
      [`GET /api/v1/homes/${HOME_ID}/devices`]: [],
    })
    renderPage()

    const members = await screen.findByRole('region', {name: 'Members'})
    expect(await within(members).findByText('Maria')).toBeVisible()
    expect(within(members).getByText('Contractor')).toBeVisible()
    expect(within(members).getByText('Kitchen · invited by Alex')).toBeVisible()
    // Your own access is not changed from here: you leave the home instead.
    expect(within(members).getAllByRole('button', {name: 'Change'})).toHaveLength(1)
    expect(screen.getByText('No invitations are waiting.')).toBeVisible()
    expect(screen.getByText('Weekend guests')).toBeVisible()
  })

  it('revokes a guest link in one click', async () => {
    let links = [LINK]
    const calls = mockApi({
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [`GET /api/v1/homes/${HOME_ID}/members`]: MEMBERS,
      [`GET /api/v1/homes/${HOME_ID}/invitations`]: [],
      [`GET /api/v1/homes/${HOME_ID}/guest-links`]: () => links,
      [`GET /api/v1/homes/${HOME_ID}/devices`]: [],
      [`DELETE /api/v1/homes/${HOME_ID}/grants/g-link`]: () => {
        links = []
        return new Response(null, {status: 204})
      },
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', {name: 'Revoke the guest link “Weekend guests”'}))

    expect(await screen.findByText('No guest links yet.')).toBeVisible()
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
  })

  it('lists the devices with their roles, places and last use, and revokes one in one click', async () => {
    let devices = [DEVICE]
    const calls = mockApi(
      manager({
        [`GET /api/v1/homes/${HOME_ID}/devices`]: () => devices,
        [`DELETE /api/v1/homes/${HOME_ID}/grants/g-device`]: () => {
          devices = []
          return new Response(null, {status: 204})
        },
      }),
    )
    renderPage()

    const section = await screen.findByRole('region', {name: 'Devices and integrations'})
    expect(await within(section).findByText('Hallway mirror')).toBeVisible()
    expect(within(section).getByText('Family member')).toBeVisible()
    expect(within(section).getByText('Hall')).toBeVisible()
    expect(within(section).getByText(/^Last used .* from 192\.0\.2\.44$/)).toBeVisible()
    fireEvent.click(within(section).getByRole('button', {name: 'Revoke the token of “Hallway mirror”'}))

    expect(await within(section).findByText('No devices or integrations yet.')).toBeVisible()
    expect(calls.filter((call) => call.method === 'DELETE').map((call) => call.path)).toEqual([
      `/api/v1/homes/${HOME_ID}/grants/g-device`,
    ])
  })

  it('opens the dialog that adds a device', async () => {
    mockApi(manager({[`GET /api/v1/homes/${HOME_ID}/roles`]: [role('family')]}))
    renderPage()

    fireEvent.click(await screen.findByRole('button', {name: 'Add a device'}))

    expect(await screen.findByRole('dialog', {name: 'Add a device or an integration'})).toBeVisible()
  })

  it('shows someone who does not manage people only how to leave', async () => {
    mockApi({
      [`GET /api/v1/homes/${HOME_ID}`]: home({
        access: {owner: false, all_permissions: false, permissions: ['entities.edit', 'entities.view']},
      }),
    })
    renderPage()

    expect(await screen.findByRole('region', {name: 'Your access'})).toBeVisible()
    expect(screen.queryByRole('button', {name: 'Invite'})).toBeNull()
    expect(screen.getByRole('button', {name: 'Leave the home'})).toBeVisible()
  })

  it('refuses the last owner leaving, saying why', async () => {
    mockApi({
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [`GET /api/v1/homes/${HOME_ID}/members`]: MEMBERS,
      [`GET /api/v1/homes/${HOME_ID}/invitations`]: [],
      [`GET /api/v1/homes/${HOME_ID}/guest-links`]: [],
      [`GET /api/v1/homes/${HOME_ID}/devices`]: [],
      [`POST /api/v1/homes/${HOME_ID}:leave`]: problem(409, 'last_owner'),
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', {name: 'Leave the home'}))
    const dialog = await screen.findByRole('dialog', {name: 'Leave Flat?'})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Leave the home'}))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'A home needs at least one owner. Make someone else an owner first.',
    )
  })

  it("takes back a member's access after asking", async () => {
    let members = MEMBERS
    const calls = mockApi(
      manager({
        [`GET /api/v1/homes/${HOME_ID}/members`]: () => members,
        [`DELETE /api/v1/homes/${HOME_ID}/grants/g-maria`]: () => {
          members = MEMBERS.slice(0, 1)
          return new Response(null, {status: 204})
        },
      }),
    )
    renderPage()

    const members_ = await screen.findByRole('region', {name: 'Members'})
    fireEvent.click(await within(members_).findByRole('button', {name: 'Remove'}))
    const dialog = await screen.findByRole('dialog', {name: "Remove Maria's access?"})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Remove'}))

    await expect.poll(() => screen.queryByText('Maria')).toBeNull()
    expect(calls.filter((call) => call.method === 'DELETE').map((call) => call.path)).toEqual([
      `/api/v1/homes/${HOME_ID}/grants/g-maria`,
    ])
  })

  it('offers an admin no way to remove an owner', async () => {
    const owner = {...MEMBERS[0], you: false}
    const admin = {person: {id: 'anna', username: 'anna', display_name: 'Anna'}, you: true, grants: []}
    mockApi(
      manager({
        [`GET /api/v1/homes/${HOME_ID}`]: home({access: {owner: false, all_permissions: true, permissions: []}}),
        [`GET /api/v1/homes/${HOME_ID}/members`]: [owner, admin],
      }),
    )
    renderPage()

    const members = await screen.findByRole('region', {name: 'Members'})
    await within(members).findByText('Alex')

    expect(within(members).queryByRole('button', {name: 'Remove'})).toBeNull()
    expect(within(members).queryByRole('button', {name: 'Change'})).toBeNull()
  })

  it('revokes a waiting invitation', async () => {
    let invitations = [INVITATION]
    mockApi(
      manager({
        [`GET /api/v1/homes/${HOME_ID}/invitations`]: () => invitations,
        [`DELETE /api/v1/homes/${HOME_ID}/invitations/inv`]: () => {
          invitations = []
          return new Response(null, {status: 204})
        },
      }),
    )
    renderPage()

    const waiting = await screen.findByRole('region', {name: 'Invitations waiting'})
    fireEvent.click(await within(waiting).findByRole('button', {name: 'Revoke'}))

    expect(await within(waiting).findByText('No invitations are waiting.')).toBeVisible()
  })

  it('leaves the home and goes to the start page with the list of homes read again', async () => {
    const calls = mockApi(
      manager({
        [`POST /api/v1/homes/${HOME_ID}:leave`]: new Response(null, {status: 204}),
      }),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', {name: 'Leave the home'}))
    const dialog = await screen.findByRole('dialog', {name: 'Leave Flat?'})
    fireEvent.click(within(dialog).getByRole('button', {name: 'Leave the home'}))

    expect(await screen.findByRole('heading', {name: 'Start'})).toBeVisible()
    expect(calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([
      `/api/v1/homes/${HOME_ID}:leave`,
    ])
  })

  it('offers a reset link for another member, not for yourself', async () => {
    mockApi({
      ...manager(),
      [`POST /api/v1/homes/${HOME_ID}/members/maria:reset-link`]: {
        url: 'http://localhost/reset-password/abc',
        expires_at: '2099-01-02T10:00:00Z',
      },
    })
    renderPage()

    const members = await screen.findByRole('region', {name: 'Members'})
    await within(members).findByText('Maria')
    // One button: yours is not offered, since you change your own password on the account page.
    fireEvent.click(within(members).getByRole('button', {name: 'Reset password'}))
    fireEvent.click(await screen.findByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('textbox', {name: 'Link'})).toHaveValue('http://localhost/reset-password/abc')
  })
})
