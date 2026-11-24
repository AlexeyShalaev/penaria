import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
import {fireEvent, render, screen} from '@testing-library/react'
import {MemoryRouter} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {home, HOME_ID} from '@/test/fixtures'

import {AppRoutes} from './App'

function renderApp() {
  const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}})
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
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
    expect(screen.getByLabelText(/Time zone/)).toHaveValue(Intl.DateTimeFormat().resolvedOptions().timeZone)
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: 'Flat'}})
    fireEvent.click(screen.getByRole('button', {name: 'Create home'}))

    expect(await screen.findByRole('heading', {name: 'Places and things'})).toBeVisible()
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      name: 'Flat',
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      locale: 'en',
    })
  })

  it('opens the first home when there is one', async () => {
    mockApi({
      'GET /api/v1/homes': [home()],
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [`GET /api/v1/homes/${HOME_ID}/entities`]: [],
    })

    renderApp()

    expect(await screen.findByRole('heading', {name: 'Places and things'})).toBeVisible()
    expect(await screen.findByRole('region', {name: 'Flat'})).toBeVisible()
  })
})
