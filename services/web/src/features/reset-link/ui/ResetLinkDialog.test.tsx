import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {HOME_ID} from '@/test/fixtures'
import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'

import {ResetLinkDialog} from './ResetLinkDialog'

const URL = 'http://localhost/reset-password/abc'
const PATH = `POST /api/v1/homes/${HOME_ID}/members/user-1:reset-link`

function renderDialog() {
  renderAt(
    '/',
    <Route path="/" element={<ResetLinkDialog homeId={HOME_ID} userId="user-1" name="Anna" onClose={vi.fn()} />} />,
  )
}

describe('ResetLinkDialog', () => {
  it('makes a reset link for a member and shows it once, with its end', async () => {
    mockApi({[PATH]: {url: URL, expires_at: '2026-01-02T10:00:00Z'}})
    renderDialog()

    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('textbox', {name: 'Link'})).toHaveValue(URL)
    expect(screen.getByText(/Pass this link on to Anna. It works once, until/)).toBeVisible()
  })

  it('says when the admin may not reset this person', async () => {
    mockApi({[PATH]: problem(403, 'reset_not_allowed')})
    renderDialog()

    fireEvent.click(screen.getByRole('button', {name: 'Make the link'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('they have access you could not give')
  })
})
