import {screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {account, entity, HOME_ID} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {GuestOpenPage} from './GuestOpenPage'
import {GuestPage} from './GuestPage'

const VISIT = {
  home: {id: HOME_ID, name: 'Country house'},
  name: 'Weekend',
  expires_at: '2099-11-27T19:00:00Z',
  scope: null,
}

function renderGuest(url: string) {
  renderAt(
    url,
    <>
      <Route path="/guest/:token" element={<GuestOpenPage />} />
      <Route path="/guest" element={<GuestPage />} />
    </>,
  )
}

describe('GuestOpenPage', () => {
  it('exchanges the link for a guest session and leaves the token out of the address', async () => {
    const calls = mockApi({
      'GET /api/v1/me': problem(401, 'unauthenticated'),
      'POST /api/v1/guest-sessions': VISIT,
      'GET /api/v1/guest': VISIT,
      [`GET /api/v1/homes/${HOME_ID}/entities`]: [],
    })
    renderGuest('/guest/secret')

    expect(await screen.findByRole('heading', {name: 'Country house'})).toBeVisible()
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({token: 'secret'})
  })

  it('asks a signed-in person before opening the link', async () => {
    const calls = mockApi({'GET /api/v1/me': account({display_name: 'Alex'})})
    renderGuest('/guest/secret')

    expect(await screen.findByRole('heading', {name: 'Open as a guest?'})).toBeVisible()
    expect(screen.getByRole('button', {name: 'Sign out and continue as a guest'})).toBeVisible()
    expect(calls.filter((call) => call.method === 'POST')).toEqual([])
  })

  it('says why a link does not open', async () => {
    mockApi({
      'GET /api/v1/me': problem(401, 'unauthenticated'),
      'POST /api/v1/guest-sessions': problem(409, 'guest_link_ended'),
    })
    renderGuest('/guest/secret')

    expect(
      await screen.findByText('This guest link has expired or was revoked. Ask your hosts for a new one.'),
    ).toBeVisible()
  })
})

describe('GuestPage', () => {
  it('shows the home, the end of the visit and the guest-visible things, opened', async () => {
    mockApi({
      'GET /api/v1/guest': VISIT,
      [`GET /api/v1/homes/${HOME_ID}/entities`]: [
        entity({id: 'plot', name: 'Country house', kind: 'property', children: 1}),
      ],
      [`GET /api/v1/homes/${HOME_ID}/entities?parent_id=plot`]: [
        entity({id: 'towels', name: 'Towels', kind: 'item', privacy: 'guest_visible'}),
      ],
    })
    renderGuest('/guest')

    expect(await screen.findByText('Towels')).toBeVisible()
    expect(screen.getByText(/^until /)).toBeVisible()
    // Read-only: no links to entity pages, which a guest cannot open.
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByText('Nothing inside yet.')).toBeNull()
  })

  it('says the visit has ended once the link is revoked', async () => {
    mockApi({'GET /api/v1/guest': problem(401, 'unauthenticated')})
    renderGuest('/guest')

    expect(await screen.findByRole('heading', {name: 'The visit has ended'})).toBeVisible()
  })
})
