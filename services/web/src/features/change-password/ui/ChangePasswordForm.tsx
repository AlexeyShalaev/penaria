import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {checkNewPassword, PASSWORD_MIN_LENGTH, useChangePassword} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Button, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

import styles from './ChangePasswordForm.module.css'

export function ChangePasswordForm() {
  const {t} = useTranslation()
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [password, setPassword] = useState('')
  const [repeated, setRepeated] = useState('')
  const [problem, setProblem] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const passwordProblem = checkNewPassword(password, repeated)
    setProblem(passwordProblem && t(`password.${passwordProblem}`, {min: PASSWORD_MIN_LENGTH}))
    if (passwordProblem) return
    change.mutate(
      {current_password: current, new_password: password},
      {
        onSuccess: () => {
          setCurrent('')
          setPassword('')
          setRepeated('')
        },
      },
    )
  }

  const error = problem ?? (change.isError ? describeError(change.error, t) : null)
  return (
    <form onSubmit={submit}>
      <FormLayout>
        <Field label={t('account.currentPassword')}>
          <TextInput
            type="password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        <Field label={t('account.newPassword')} hint={t('setup.passwordHint', {min: PASSWORD_MIN_LENGTH})}>
          <TextInput
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
            required
          />
        </Field>
        <Field label={t('account.repeatPassword')}>
          <TextInput
            type="password"
            value={repeated}
            onChange={(event) => setRepeated(event.target.value)}
            autoComplete="new-password"
            required
          />
        </Field>
        {error && <FormError>{error}</FormError>}
        {change.isSuccess && (
          <p role="status" className={styles.done}>
            {t('account.passwordChanged')}
          </p>
        )}
        <FormActions>
          <Button type="submit" variant="secondary" disabled={change.isPending}>
            {t('account.changePassword')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
