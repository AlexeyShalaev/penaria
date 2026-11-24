import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {AccountForm} from './AccountForm'

describe('AccountForm', () => {
  it('saves the name and the language', async () => {
    const calls = mockApi({'PATCH /api/v1/me': account({display_name: 'Alex Doe', locale: 'ru'})})
    renderAt('/', <Route path="/" element={<AccountForm account={account()} />} />)

    expect(screen.getByLabelText('Username')).toHaveAttribute('readonly')
    fireEvent.change(screen.getByLabelText('Your name'), {target: {value: ' Alex Doe '}})
    fireEvent.change(screen.getByLabelText('Language'), {target: {value: 'ru'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(await screen.findByRole('status')).toHaveTextContent('Saved.')
    expect(calls[0]?.body).toEqual({display_name: 'Alex Doe', locale: 'ru'})
  })
})
