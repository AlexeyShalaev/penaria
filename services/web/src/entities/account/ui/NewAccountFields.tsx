import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {Field, TextInput} from '@/shared/ui'

import {checkNewPassword, PASSWORD_MIN_LENGTH} from '../model/password'

export type NewAccount = {username: string; display_name: string; password: string}

/**
 * The fields of a new account, as the setup and an invitation ask for them. `read()` gives the
 * account to send, or the problem with the password to show instead.
 */
export function useNewAccountFields() {
  const {t} = useTranslation()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [repeated, setRepeated] = useState('')

  const read = (): {account: NewAccount; problem: null} | {account: null; problem: string} => {
    const problem = checkNewPassword(password, repeated)
    if (problem) return {account: null, problem: t(`password.${problem}`, {min: PASSWORD_MIN_LENGTH})}
    return {account: {username: username.trim(), display_name: displayName.trim(), password}, problem: null}
  }

  const fields = (
    <>
      <Field label={t('setup.username')} hint={t('setup.usernameHint')}>
        <TextInput
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
        />
      </Field>
      <Field label={t('setup.displayName')} hint={t('setup.displayNameHint')}>
        <TextInput
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          autoComplete="name"
          required
          maxLength={200}
        />
      </Field>
      <Field label={t('setup.password')} hint={t('password.hint', {min: PASSWORD_MIN_LENGTH})}>
        <TextInput
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          required
        />
      </Field>
      <Field label={t('setup.repeatPassword')}>
        <TextInput
          type="password"
          value={repeated}
          onChange={(event) => setRepeated(event.target.value)}
          autoComplete="new-password"
          required
        />
      </Field>
    </>
  )
  return {fields, read}
}
