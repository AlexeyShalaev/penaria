import {Fingerprint, KeyRound} from 'lucide-react'
import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, useParams} from 'react-router'

import {
  checkNewPassword,
  PASSWORD_MIN_LENGTH,
  type ResetPreview,
  usePasswordResetPreview,
  useResetPassword,
} from '@/entities/account'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {
  Button,
  Card,
  Field,
  FormActions,
  FormError,
  FormLayout,
  IconTile,
  PageTitle,
  QueryState,
  TextInput,
} from '@/shared/ui'

import styles from './ResetPasswordPage.module.css'

/** Where a reset link leads: a new password for the account; every device is signed out, passkeys stay. */
export function ResetPasswordPage() {
  const {t} = useTranslation()
  const {token = ''} = useParams<{token: string}>()
  const preview = usePasswordResetPreview(token)
  return (
    <main className={styles.page}>
      <div className={styles.intro}>
        <IconTile icon={KeyRound} size="lg" accent />
        <PageTitle>{t('reset.title')}</PageTitle>
      </div>
      <QueryState query={preview}>{(found) => <ResetForm token={token} preview={found} />}</QueryState>
      {preview.isError && (
        <p className={styles.back}>
          <Link to="/forgot-password">{t('reset.askAgain')}</Link>
        </p>
      )}
    </main>
  )
}

function ResetForm(props: {token: string; preview: ResetPreview}) {
  const {t, i18n} = useTranslation()
  const reset = useResetPassword(props.token)
  const [password, setPassword] = useState('')
  const [repeated, setRepeated] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const {preview} = props

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const passwordProblem = checkNewPassword(password, repeated)
    setProblem(passwordProblem && t(`password.${passwordProblem}`, {min: PASSWORD_MIN_LENGTH}))
    if (!passwordProblem) reset.mutate(password)
  }

  if (reset.isSuccess) {
    return (
      <Card className={styles.card}>
        <FormLayout>
          <p role="status" className={styles.text}>
            {t('reset.done')}
          </p>
          <FormActions>
            <Link to="/sign-in" className={styles.linkButton}>
              {t('reset.signIn')}
            </Link>
          </FormActions>
        </FormLayout>
      </Card>
    )
  }

  const error = problem ?? (reset.isError ? describeError(reset.error, t) : null)
  return (
    <Card className={styles.card}>
      <form onSubmit={submit}>
        <FormLayout>
          <p className={styles.text}>{t('reset.for', {name: preview.display_name, username: preview.username})}</p>
          {/* The browser's password manager files the new password under this username. */}
          <input type="text" name="username" autoComplete="username" value={preview.username} readOnly hidden />
          <Field label={t('account.newPassword')} hint={t('password.hint', {min: PASSWORD_MIN_LENGTH})}>
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
          <p className={styles.note}>{t('reset.signsOut')}</p>
          {error && <FormError>{error}</FormError>}
          <FormActions>
            <Button type="submit" disabled={reset.isPending}>
              {t('reset.submit')}
            </Button>
          </FormActions>
        </FormLayout>
      </form>
      <section className={styles.passkeys} aria-labelledby="reset-passkeys">
        <h2 id="reset-passkeys" className={styles.passkeysTitle}>
          {t('reset.passkeysTitle')}
        </h2>
        {preview.passkeys.length === 0 ? (
          <p className={styles.note}>{t('reset.noPasskeys')}</p>
        ) : (
          <>
            <p className={styles.note}>{t('reset.passkeysText')}</p>
            <ul className={styles.passkeyList}>
              {preview.passkeys.map((passkey) => (
                <li key={`${passkey.name}-${passkey.created_at}`} className={styles.passkey}>
                  <Fingerprint aria-hidden />
                  <span>
                    <span className={styles.passkeyName}>{passkey.name}</span>
                    <span className={styles.note}>
                      {t('passkeys.created', {when: formatDateTime(new Date(passkey.created_at), i18n.language)})}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </Card>
  )
}
