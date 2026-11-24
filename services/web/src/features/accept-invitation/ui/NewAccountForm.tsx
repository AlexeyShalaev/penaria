import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type Account, checkNewPassword, PASSWORD_MIN_LENGTH, useStartSession} from '@/entities/account'
import {useAcceptWithNewAccount} from '@/entities/member'
import {describeError} from '@/shared/api'
import {Button, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

/** Makes an account through an invitation, the one way in besides the setup, and accepts the invitation. */
export function NewAccountForm(props: {token: string; onJoined: (account: Account, homeId: string) => void}) {
  const {t, i18n} = useTranslation()
  const start = useStartSession()
  const accept = useAcceptWithNewAccount(props.token, start)
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
    accept.mutate(
      {username: username.trim(), display_name: displayName.trim(), password, locale: i18n.language},
      {onSuccess: (answer) => props.onJoined(answer.account, answer.home.id)},
    )
  }

  const error = problem ?? (accept.isError ? describeError(accept.error, t) : null)
  return (
    <form onSubmit={submit}>
      <FormLayout>
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
          <Button type="submit" disabled={accept.isPending}>
            {t('invitation.createAndJoin')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
