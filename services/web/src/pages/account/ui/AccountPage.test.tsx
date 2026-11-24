import {screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {MAIL_OFF, mockApi, SECOND_FACTOR_FINE} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {AccountPage} from './AccountPage'

const PAGE = {
  ...MAIL_OFF,
  ...SECOND_FACTOR_FINE,
  'GET /api/v1/me': account(),
  'GET /api/v1/me/passkeys': [],
  'GET /api/v1/me/sessions': [],
}

function renderPage() {
  renderAt('/account', <Route path="/account" element={<AccountPage />} />)
}

describe('AccountPage', () => {
  it('shows the linked accounts where the install has a provider, and no password form without a password', async () => {
    mockApi({
      ...PAGE,
      'GET /api/v1/auth/config': {oidc: {name: 'Authentik'}},
      'GET /api/v1/me/sign-in-methods': {password: false, external_identities: []},
    })
    renderPage()

    expect(await screen.findByRole('region', {name: 'Linked accounts'})).toBeVisible()
    expect(screen.queryByRole('region', {name: 'Password'})).toBeNull()
  })

  it('shows the password form and no linked accounts without a provider', async () => {
    mockApi(PAGE)
    renderPage()

    expect(await screen.findByRole('region', {name: 'Password'})).toBeVisible()
    expect(screen.queryByRole('region', {name: 'Linked accounts'})).toBeNull()
  })
})
