import {screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'

import {VerifyEmailPage} from './VerifyEmailPage'

describe('VerifyEmailPage', () => {
  it('confirms the address once, on opening', async () => {
    const calls = mockApi({'POST /api/v1/email-verifications:confirm': {email: 'anna@example.org'}})
    renderAt('/verify-email/tok', <Route path="/verify-email/:token" element={<VerifyEmailPage />} />)

    expect(await screen.findByRole('status')).toHaveTextContent('anna@example.org is now the email of your account.')
    expect(calls).toEqual([
      {method: 'POST', path: '/api/v1/email-verifications:confirm', search: '', body: {token: 'tok'}},
    ])
  })

  it('says when the link has expired', async () => {
    mockApi({'POST /api/v1/email-verifications:confirm': problem(409, 'account_link_expired')})
    renderAt('/verify-email/tok', <Route path="/verify-email/:token" element={<VerifyEmailPage />} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('This link has expired.')
  })
})
