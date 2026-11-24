import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {i18n} from '@/shared/i18n'
import {mockApi, problem} from '@/test/api'
import {account} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {SetupForm} from './SetupForm'

const TOKEN = '384753e9c5a280bc58bd9d6121f0ade8'

function renderForm() {
  const onDone = vi.fn()
  renderAt('/', <Route path="/" element={<SetupForm onDone={onDone} />} />)
  return onDone
}

function fill(password: string, repeated = password) {
  fireEvent.change(screen.getByLabelText(i18n.t('setup.token')), {target: {value: ` ${TOKEN} `}})
  fireEvent.change(screen.getByLabelText(i18n.t('setup.username')), {target: {value: 'owner'}})
  fireEvent.change(screen.getByLabelText(i18n.t('setup.displayName')), {target: {value: 'Alex'}})
  fireEvent.change(screen.getByLabelText(i18n.t('setup.password')), {target: {value: password}})
  fireEvent.change(screen.getByLabelText(i18n.t('setup.repeatPassword')), {target: {value: repeated}})
  fireEvent.click(screen.getByRole('button', {name: i18n.t('setup.submit')}))
}

describe('SetupForm', () => {
  it('creates the account in the language of the interface', async () => {
    await i18n.changeLanguage('ru')
    const calls = mockApi({'POST /api/v1/setup': account()})
    const onDone = renderForm()

    fill('correct horse battery')

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(calls[0]?.body).toEqual({
      token: TOKEN,
      username: 'owner',
      display_name: 'Alex',
      password: 'correct horse battery',
      locale: 'ru',
    })
  })

  it('asks for a longer password before calling the server', () => {
    const calls = mockApi({})
    renderForm()

    fill('short')

    expect(screen.getByRole('alert')).toHaveTextContent('The password needs at least 12 characters.')
    expect(calls).toEqual([])
  })

  it('asks to repeat the same password', () => {
    const calls = mockApi({})
    renderForm()

    fill('correct horse battery', 'correct horse batter')

    expect(screen.getByRole('alert')).toHaveTextContent('The passwords do not match.')
    expect(calls).toEqual([])
  })

  it('explains a wrong setup token', async () => {
    mockApi({'POST /api/v1/setup': problem(403, 'invalid_setup_token')})
    renderForm()

    fill('correct horse battery')

    expect(await screen.findByRole('alert')).toHaveTextContent(/Copy the token from the server's latest log/)
  })

  it('names the reason the server refuses a password', async () => {
    mockApi({
      'POST /api/v1/setup': new Response(
        JSON.stringify({status: 400, code: 'weak_password', params: {reason: 'common', min_length: 12}}),
        {status: 400, headers: {'Content-Type': 'application/problem+json'}},
      ),
    })
    renderForm()

    fill('password1234')

    expect(await screen.findByRole('alert')).toHaveTextContent('This password is one of the most common ones.')
  })
})
