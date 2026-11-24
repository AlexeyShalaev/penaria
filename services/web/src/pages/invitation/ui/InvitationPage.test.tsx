import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {account, HOME_ID, role} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {InvitationPage} from './InvitationPage'

const PREVIEW = {
  home: {id: HOME_ID, name: 'Country house'},
  inviter: 'Alex',
  role: role('family'),
  scope: {id: 'kitchen', names: ['Country house', 'House', 'Kitchen']},
  expires_at: '2026-12-01T10:00:00Z',
  grant_expires_at: null,
  leave_when_accepted: false,
}

function renderPage() {
  renderAt(
    '/invite/secret',
    <>
      <Route path="/invite/:token" element={<InvitationPage />} />
      <Route path="/homes/:homeId/places" element={<h1>The home</h1>} />
    </>,
  )
}

describe('InvitationPage', () => {
  it('says who invites, into which home and with which role', async () => {
    mockApi({'POST /api/v1/invitations:preview': PREVIEW, 'GET /api/v1/me': problem(401, 'unauthenticated')})
    renderPage()

    expect(await screen.findByRole('heading', {name: 'Alex invites you to Country house'})).toBeVisible()
    expect(screen.getByText('Family member')).toBeVisible()
    expect(screen.getByText('Only House / Kitchen')).toBeVisible()
    expect(screen.getByText(/Adds and changes things/)).toBeVisible()
  })

  it('makes an account through the invitation and lands in the home', async () => {
    const calls = mockApi({
      'POST /api/v1/invitations:preview': PREVIEW,
      'GET /api/v1/me': problem(401, 'unauthenticated'),
      'POST /api/v1/invitations:accept-new-account': {
        account: account({username: 'maria', display_name: 'Maria', install_admin: false}),
        home: PREVIEW.home,
      },
    })
    renderPage()

    fireEvent.change(await screen.findByLabelText('Username'), {target: {value: ' maria '}})
    fireEvent.change(screen.getByLabelText('Your name'), {target: {value: 'Maria'}})
    fireEvent.change(screen.getByLabelText('Password'), {target: {value: 'a long family password'}})
    fireEvent.change(screen.getByLabelText('Repeat the password'), {target: {value: 'a long family password'}})
    fireEvent.click(screen.getByRole('button', {name: 'Create the account and join'}))

    expect(await screen.findByRole('heading', {name: 'The home'})).toBeVisible()
    expect(calls.find((call) => call.path.endsWith('accept-new-account'))?.body).toEqual({
      token: 'secret',
      username: 'maria',
      display_name: 'Maria',
      password: 'a long family password',
      locale: 'en',
    })
  })

  it('lets a signed-in account accept and lands in the home', async () => {
    const calls = mockApi({
      'POST /api/v1/invitations:preview': PREVIEW,
      'GET /api/v1/me': account({display_name: 'Maria'}),
      'POST /api/v1/invitations:accept': PREVIEW.home,
    })
    renderPage()

    expect(await screen.findByText('You are signed in as Maria.')).toBeVisible()
    fireEvent.click(screen.getByRole('button', {name: 'Accept the invitation'}))

    expect(await screen.findByRole('heading', {name: 'The home'})).toBeVisible()
    expect(calls.find((call) => call.path.endsWith('invitations:accept'))?.body).toEqual({token: 'secret'})
  })

  it('warns about a transfer of ownership', async () => {
    mockApi({
      'POST /api/v1/invitations:preview': {...PREVIEW, role: role('owner'), scope: null, leave_when_accepted: true},
      'GET /api/v1/me': account({display_name: 'Maria'}),
    })
    renderPage()

    expect(await screen.findByText('You will become an owner of the home, and Alex will stop being one.')).toBeVisible()
  })

  it('says plainly that a used invitation no longer works', async () => {
    mockApi({
      'POST /api/v1/invitations:preview': problem(409, 'invitation_used'),
      'GET /api/v1/me': problem(401, 'unauthenticated'),
    })
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This invitation has already been used. Each invitation works once: ask for a new one.',
    )
  })
})
