import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi, problem} from '@/test/api'
import {renderAt} from '@/test/render'

import {ChangePasswordForm} from './ChangePasswordForm'

function change(current: string, password: string, repeated = password) {
  fireEvent.change(screen.getByLabelText('Current password'), {target: {value: current}})
  fireEvent.change(screen.getByLabelText('New password'), {target: {value: password}})
  fireEvent.change(screen.getByLabelText('Repeat the new password'), {target: {value: repeated}})
  fireEvent.click(screen.getByRole('button', {name: 'Change password'}))
}

describe('ChangePasswordForm', () => {
  it('changes the password and empties the form', async () => {
    const calls = mockApi({'POST /api/v1/me/password': new Response(null, {status: 204})})
    renderAt('/', <Route path="/" element={<ChangePasswordForm />} />)

    change('correct horse battery', 'a brand new secret')

    expect(await screen.findByRole('status')).toHaveTextContent('Your other devices were signed out.')
    expect(calls[0]?.body).toEqual({current_password: 'correct horse battery', new_password: 'a brand new secret'})
    expect(screen.getByLabelText('New password')).toHaveValue('')
  })

  it('checks the new password before calling the server', () => {
    const calls = mockApi({})
    renderAt('/', <Route path="/" element={<ChangePasswordForm />} />)

    change('correct horse battery', 'a brand new secret', 'a brand new secreT')

    expect(screen.getByRole('alert')).toHaveTextContent('The passwords do not match.')
    expect(calls).toEqual([])
  })

  it('says when the current password is wrong', async () => {
    mockApi({'POST /api/v1/me/password': problem(400, 'wrong_password')})
    renderAt('/', <Route path="/" element={<ChangePasswordForm />} />)

    change('not the password', 'a brand new secret')

    expect(await screen.findByRole('alert')).toHaveTextContent('The current password is wrong.')
  })
})
