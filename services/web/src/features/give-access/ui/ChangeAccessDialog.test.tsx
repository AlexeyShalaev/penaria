import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import type {MemberGrant} from '@/entities/member'
import {mockApi} from '@/test/api'
import {HOME_ID, role, ROLES} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {ChangeAccessDialog} from './ChangeAccessDialog'

function grant(overrides: Partial<MemberGrant>): MemberGrant {
  return {
    id: 'g-maria',
    role: role('contractor'),
    scope: {id: 'kitchen', names: ['Flat', 'Kitchen']},
    expires_at: null,
    created_at: '2026-11-20T10:00:00Z',
    granted_by: null,
    ...overrides,
  }
}

function renderDialog(of: MemberGrant) {
  const calls = mockApi({
    [`GET /api/v1/homes/${HOME_ID}/roles`]: ROLES,
    [`GET /api/v1/homes/${HOME_ID}/entities`]: [],
    [`PATCH /api/v1/homes/${HOME_ID}/grants/g-maria`]: new Response(null, {status: 204}),
  })
  renderAt(
    '/',
    <Route path="/" element={<ChangeAccessDialog homeId={HOME_ID} person="Maria" grant={of} onClose={() => {}} />} />,
  )
  return calls
}

const patched = (calls: ReturnType<typeof mockApi>) => calls.find((call) => call.method === 'PATCH')?.body

describe('ChangeAccessDialog', () => {
  it('sends only the role when only the role changes, with the end a guest needs', async () => {
    vi.setSystemTime(new Date('2026-11-24T10:00:00Z'))
    const calls = renderDialog(grant({}))

    fireEvent.click(await screen.findByRole('radio', {name: /Guest/}))
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    await expect.poll(() => patched(calls)).toEqual({role_id: 'role-guest', expires_at: '2026-11-27T22:59:59.000Z'})
  })

  it('keeps an end it was not asked to change, to the minute', async () => {
    const calls = renderDialog(grant({role: role('family'), expires_at: '2026-12-01T13:05:00Z'}))

    fireEvent.click(await screen.findByRole('radio', {name: 'The whole home'}))
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    await expect.poll(() => patched(calls)).toEqual({scope_entity_id: null})
  })

  it('clears the end of a role that need not end', async () => {
    const calls = renderDialog(grant({role: role('family'), expires_at: '2026-12-01T13:05:00Z'}))

    fireEvent.change(await screen.findByLabelText('Last day of access'), {target: {value: ''}})
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    await expect.poll(() => patched(calls)).toEqual({expires_at: null})
  })
})
