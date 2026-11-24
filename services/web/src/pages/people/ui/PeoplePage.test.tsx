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
  created_by: ME,
}

function renderPage() {
  renderAt(`/homes/${HOME_ID}/people`, <Route path="/homes/:homeId/people" element={<PeoplePage />} />)
}

describe('PeoplePage', () => {
  it('lists the members with their roles and places, and the guest links', async () => {
    mockApi({
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [`GET /api/v1/homes/${HOME_ID}/members`]: MEMBERS,
      [`GET /api/v1/homes/${HOME_ID}/invitations`]: [],
      [`GET /api/v1/homes/${HOME_ID}/guest-links`]: [LINK],
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
})
