import {screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {renderAt} from '@/test/render'

import {ExternalSignInPage} from './ExternalSignInPage'

function renderAtProblem(problem: string) {
  renderAt(`/sign-in/external?problem=${problem}`, <Route path="/sign-in/external" element={<ExternalSignInPage />} />)
}

describe('ExternalSignInPage', () => {
  it('says an invitation is needed, naming the provider', async () => {
    mockApi({'GET /api/v1/auth/config': {oidc: {name: 'Authentik'}}})
    renderAtProblem('invitation_required')

    expect(await screen.findByRole('heading', {name: 'You need an invitation'})).toBeVisible()
    expect(await screen.findByText(/Your Authentik account is not on this Penaria yet/)).toBeVisible()
    expect(screen.getByRole('link', {name: 'Back to sign-in'})).toHaveAttribute('href', '/sign-in')
  })

  it('treats a problem it does not know as a failed sign-in', async () => {
    mockApi({})
    renderAtProblem('something-new')

    expect(await screen.findByRole('heading', {name: 'the sign-in provider did not sign you in'})).toBeVisible()
  })
})
