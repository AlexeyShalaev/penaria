import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type Account, useSignIn} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Button, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

/** `submitVariant` is `secondary` when a passkey is offered above it as the main way in. */
export function SignInForm(props: {onSignedIn: (account: Account) => void; submitVariant?: 'primary' | 'secondary'}) {
  const {t} = useTranslation()
  const signIn = useSignIn()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    signIn.mutate({username: username.trim(), password}, {onSuccess: props.onSignedIn})
  }

  return (
    <form onSubmit={submit}>
      <FormLayout>
        <Field label={t('signIn.username')}>
          <TextInput
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
          />
        </Field>
        <Field label={t('signIn.password')}>
          <TextInput
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        {signIn.isError && <FormError>{describeError(signIn.error, t)}</FormError>}
        <FormActions>
          <Button type="submit" variant={props.submitVariant} disabled={signIn.isPending}>
            {t('signIn.submit')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
