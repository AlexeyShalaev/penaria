import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {HOME_ID, role, ROLES} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {GuestLinkDialog} from './GuestLinkDialog'

const URL = 'http://localhost:5173/guest/secret-token'

describe('GuestLinkDialog', () => {
  it('makes a guest link for three days and shows it with a QR code', async () => {
    const calls = mockApi({
      [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
      [`POST /api/v1/homes/${HOME_ID}/guest-links`]: {
        link: {
          id: 'link',
          grant_id: 'grant',
          name: 'Weekend',
          role: role('guest'),
          scope: null,
          expires_at: '2026-11-27T10:00:00Z',
          created_at: '2026-11-24T10:00:00Z',
          last_used_at: null,
          granted_by: null,
        },
        url: URL,
      },
    })
    renderAt('/', <Route path="/" element={<GuestLinkDialog homeId={HOME_ID} onClose={() => {}} />} />)

    // Only one role has guest view, so there is nothing to choose.
    const name = await screen.findByLabelText('Name')
    expect(screen.queryByRole('radio', {name: /Family member/})).toBeNull()
    expect(screen.getByRole('radio', {name: '3 days'})).toHaveAttribute('aria-checked', 'true')
    fireEvent.change(name, {target: {value: ' Weekend '}})
    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('textbox', {name: 'Link'})).toHaveValue(URL)
    const body = calls.find((call) => call.method === 'POST')?.body as {expires_at: string}
    expect(body).toMatchObject({name: 'Weekend', role_id: 'role-guest', scope_entity_id: null})
    const days = (new Date(body.expires_at).getTime() - Date.now()) / (24 * 3600 * 1000)
    expect(days).toBeCloseTo(3, 1)
  })

  it('asks for a place when the link covers one place', async () => {
    mockApi({[`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES, [`GET /api/v1/homes/${HOME_ID}/entities`]: []})
    renderAt('/', <Route path="/" element={<GuestLinkDialog homeId={HOME_ID} onClose={() => {}} />} />)

    fireEvent.click(await screen.findByRole('radio', {name: 'One place'}))
    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('Pick a place, or choose the whole home.')
  })
})
