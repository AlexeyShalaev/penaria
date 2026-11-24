import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {session} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {SessionList} from './SessionList'

const LAPTOP = session({id: 'laptop', current: true})
const PHONE = session({
  id: 'phone',
  user_agent:
    'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36',
  ip: '198.51.100.7',
})

function renderList() {
  renderAt('/', <Route path="/" element={<SessionList />} />)
}

describe('SessionList', () => {
  it('names each device and marks this one', async () => {
    mockApi({'GET /api/v1/me/sessions': [LAPTOP, PHONE]})
    renderList()

    const rows = await screen.findAllByRole('listitem')

    expect(rows.map((row) => within(row).getByText(/ on /).textContent)).toEqual([
      'Safari on macOSThis device',
      'Chrome on Android',
    ])
    expect(within(rows[0] as HTMLElement).queryByRole('button')).toBeNull()
  })

  it('signs out another device', async () => {
    let sessions = [LAPTOP, PHONE]
    const calls = mockApi({
      'GET /api/v1/me/sessions': () => sessions,
      'DELETE /api/v1/me/sessions/phone': () => {
        sessions = [LAPTOP]
        return new Response(null, {status: 204})
      },
    })
    renderList()

    fireEvent.click(await screen.findByRole('button', {name: 'Sign out Chrome on Android'}))

    await screen.findByText(/Safari on macOS/)
    await expect.poll(() => screen.queryByText('Chrome on Android')).toBeNull()
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
  })

  it('signs out everywhere else', async () => {
    let sessions = [LAPTOP, PHONE, session({id: 'tablet'})]
    mockApi({
      'GET /api/v1/me/sessions': () => sessions,
      'POST /api/v1/me/sessions:revoke-others': () => {
        sessions = [LAPTOP]
        return {revoked: 2}
      },
    })
    renderList()

    fireEvent.click(await screen.findByRole('button', {name: 'Sign out everywhere else'}))

    expect(await screen.findByRole('status')).toHaveTextContent('Signed out of 2 other devices.')
    await expect.poll(() => screen.queryByRole('button', {name: 'Sign out everywhere else'})).toBeNull()
  })
})
