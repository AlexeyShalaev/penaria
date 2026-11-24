import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {MAIL_OFF, mockApi, problem} from '@/test/api'
import {account, detail, home, HOME_ID, session} from '@/test/fixtures'
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
      ...MAIL_OFF,
      'GET /api/v1/me': account(),
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
      ...MAIL_OFF,
      'GET /api/v1/me': account(),
      'GET /api/v1/homes': [home(), home({id: OTHER_ID, name: 'Country house'})],
      [`GET /api/v1/homes/${OTHER_ID}`]: home({id: OTHER_ID, name: 'Country house'}),
      [`GET /api/v1/homes/${OTHER_ID}/entities`]: [],
    })

    renderApp()

    expect(await screen.findByRole('region', {name: 'Country house'})).toBeVisible()
  })

  it('remembers the home of an entity page', async () => {
    mockApi({
      ...MAIL_OFF,
      'GET /api/v1/me': account(),
      'GET /api/v1/entities/drill': {...detail({id: 'drill', name: 'Drill', kind: 'item'}), home_id: OTHER_ID},
      [`GET /api/v1/homes/${OTHER_ID}`]: home({id: OTHER_ID, name: 'Country house'}),
      [`GET /api/v1/homes/${OTHER_ID}/entities?parent_id=drill`]: [],
      'GET /api/v1/homes': [home(), home({id: OTHER_ID, name: 'Country house'})],
    })

    renderApp('/entities/drill')

    expect(await screen.findByRole('heading', {name: 'Drill'})).toBeVisible()
    expect(localStorage.getItem('penaria.lastHome')).toBe(OTHER_ID)
  })

  it('sends a visitor without a session to sign in, and back to the page afterwards', async () => {
    let signedIn = false
    const calls = mockApi({
      ...MAIL_OFF,
      'GET /api/v1/me': () => (signedIn ? account() : problem(401, 'unauthenticated')),
      'GET /api/v1/setup': {needed: false},
      'POST /api/v1/sign-in': () => {
        signedIn = true
        return account()
      },
      'GET /api/v1/entities/drill': detail({id: 'drill', name: 'Drill', kind: 'item'}),
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [`GET /api/v1/homes/${HOME_ID}/entities?parent_id=drill`]: [],
      'GET /api/v1/homes': [home()],
    })
    renderApp('/entities/drill')

    expect(await screen.findByRole('heading', {name: 'Sign in'})).toBeVisible()
    fireEvent.change(screen.getByLabelText('Username'), {target: {value: ' owner '}})
    fireEvent.change(screen.getByLabelText('Password'), {target: {value: 'correct horse battery'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))

    expect(await screen.findByRole('heading', {name: 'Drill'})).toBeVisible()
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      username: 'owner',
      password: 'correct horse battery',
    })
  })

  it('sends the first visitor of a fresh install to the setup', async () => {
    mockApi({...MAIL_OFF, 'GET /api/v1/me': problem(401, 'unauthenticated'), 'GET /api/v1/setup': {needed: true}})

    renderApp()

    expect(await screen.findByRole('heading', {name: 'Set up Penaria'})).toBeVisible()
    expect(screen.getByText('docker compose logs penaria-server | grep "setup token"')).toBeVisible()
  })

  it('goes back to sign in when the session ends while the app is open', async () => {
    mockApi({
      ...MAIL_OFF,
      'GET /api/v1/me': account(),
      'GET /api/v1/homes': problem(401, 'unauthenticated'),
      'GET /api/v1/setup': {needed: false},
    })

    renderApp()

    expect(await screen.findByRole('heading', {name: 'Sign in'})).toBeVisible()
  })

  it('speaks the language of the account', async () => {
    mockApi({...MAIL_OFF, 'GET /api/v1/me': account({locale: 'ru'}), 'GET /api/v1/homes': []})

    renderApp()

    expect(await screen.findByRole('heading', {name: 'Добро пожаловать в Penaria'})).toBeVisible()
  })

  it('shows nothing of the previous person after signing out and in as someone else', async () => {
    let signedIn: string | null = 'Alex'
    mockApi({
      ...MAIL_OFF,
      'GET /api/v1/me': () =>
        signedIn
          ? account({display_name: signedIn, username: signedIn.toLowerCase()})
          : problem(401, 'unauthenticated'),
      'GET /api/v1/setup': {needed: false},
      'GET /api/v1/me/sessions': () => [
        session({id: `${signedIn}-laptop`, current: true, ip: signedIn === 'Alex' ? '192.0.2.1' : '198.51.100.9'}),
      ],
      'GET /api/v1/me/passkeys': [],
      'POST /api/v1/sign-out': () => {
        signedIn = null
        return new Response(null, {status: 204})
      },
      'POST /api/v1/sign-in': () => {
        signedIn = 'Sam'
        return account({display_name: 'Sam', username: 'sam'})
      },
      'GET /api/v1/homes': () => [],
    })
    renderApp('/account')

    expect(await screen.findByText(/192\.0\.2\.1/)).toBeVisible()
    expect(screen.getByRole('link', {name: /Alex/})).toHaveAttribute('aria-current', 'page')
    fireEvent.click(screen.getByRole('button', {name: 'Sign out'}))
    expect(await screen.findByRole('heading', {name: 'Sign in'})).toBeVisible()
    fireEvent.change(screen.getByLabelText('Username'), {target: {value: 'sam'}})
    fireEvent.change(screen.getByLabelText('Password'), {target: {value: 'another long password'}})
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}))

    expect(await screen.findByText(/198\.51\.100\.9/)).toBeVisible()
    expect(screen.queryByText(/192\.0\.2\.1/)).toBeNull()
  })
})
