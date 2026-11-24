import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {detail, home, HOME_ID} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {AppRoutes} from './App'

const OTHER_ID = '00000000-0000-4000-8000-000000000002'

function renderApp(url = '/') {
  renderAt(url, <Route path="*" element={<AppRoutes />} />)
}

describe('App', () => {
  it('welcomes a new install and lands in the tree of the home it creates', async () => {
    let homes: unknown[] = []
    const calls = mockApi({
      'GET /api/v1/homes': () => homes,
      'POST /api/v1/homes': () => {
        homes = [home()]
        return home()
      },
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [`GET /api/v1/homes/${HOME_ID}/entities`]: [],
    })
    renderApp()

    expect(await screen.findByRole('heading', {name: 'Welcome to Penaria'})).toBeVisible()
    expect(screen.getByLabelText('Time zone')).toHaveValue('Europe/Berlin')
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: 'Flat'}})
    fireEvent.click(screen.getByRole('button', {name: 'Create home'}))

    expect(await screen.findByRole('heading', {name: 'Places and things'})).toBeVisible()
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      name: 'Flat',
      timezone: 'Europe/Berlin',
      locale: 'en',
    })
  })

  it('opens the home used last', async () => {
    localStorage.setItem('penaria.lastHome', OTHER_ID)
    mockApi({
      'GET /api/v1/homes': [home(), home({id: OTHER_ID, name: 'Country house'})],
      [`GET /api/v1/homes/${OTHER_ID}`]: home({id: OTHER_ID, name: 'Country house'}),
      [`GET /api/v1/homes/${OTHER_ID}/entities`]: [],
    })

    renderApp()

    expect(await screen.findByRole('region', {name: 'Country house'})).toBeVisible()
  })

  it('remembers the home of an entity page', async () => {
    mockApi({
      'GET /api/v1/entities/drill': {...detail({id: 'drill', name: 'Drill', kind: 'item'}), home_id: OTHER_ID},
      [`GET /api/v1/homes/${OTHER_ID}`]: home({id: OTHER_ID, name: 'Country house'}),
      [`GET /api/v1/homes/${OTHER_ID}/entities?parent_id=drill`]: [],
      'GET /api/v1/homes': [home(), home({id: OTHER_ID, name: 'Country house'})],
    })

    renderApp('/entities/drill')

    expect(await screen.findByRole('heading', {name: 'Drill'})).toBeVisible()
    expect(localStorage.getItem('penaria.lastHome')).toBe(OTHER_ID)
  })
})
