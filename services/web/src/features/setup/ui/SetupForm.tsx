import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type Account, checkNewPassword, PASSWORD_MIN_LENGTH, useCompleteSetup} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Button, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

import styles from './SetupForm.module.css'

export function SetupForm(props: {onDone: (account: Account) => void}) {
  const {t, i18n} = useTranslation()
  const setup = useCompleteSetup()
  const [token, setToken] = useState('')
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [repeated, setRepeated] = useState('')
  const [problem, setProblem] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const passwordProblem = checkNewPassword(password, repeated)
    setProblem(passwordProblem && t(`password.${passwordProblem}`, {min: PASSWORD_MIN_LENGTH}))
    if (passwordProblem) return
    setup.mutate(
      {
        token: token.trim(),
        username: username.trim(),
        display_name: displayName.trim(),
        password,
        locale: i18n.language,
      },
      {onSuccess: props.onDone},
    )
  }

  const error = problem ?? (setup.isError ? describeError(setup.error, t) : null)
  return (
    <form onSubmit={submit}>
      <FormLayout>
        <Field label={t('setup.token')}>
          <TextInput
            className={styles.token}
            value={token}
            onChange={(event) => setToken(event.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            required
          />
        </Field>
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
        {error && <FormError>{error}</FormError>}
        <FormActions>
          <Button type="submit" disabled={setup.isPending}>
            {t('setup.submit')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
