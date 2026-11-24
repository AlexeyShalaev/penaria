import {MailQuestion} from 'lucide-react'
import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link} from 'react-router'

import {useRequestPasswordReset} from '@/entities/account'
import {useMailEnabled} from '@/entities/install'
import {describeError} from '@/shared/api'
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

import styles from './ForgotPasswordPage.module.css'

/** "Forgot password": a reset link by email, when the install sends email; otherwise who to ask. */
export function ForgotPasswordPage() {
  const {t} = useTranslation()
  const mail = useMailEnabled()
  return (
    <main className={styles.page}>
      <div className={styles.intro}>
        <IconTile icon={MailQuestion} size="lg" accent />
        <PageTitle>{t('forgot.title')}</PageTitle>
      </div>
      <Card className={styles.card}>
        <QueryState query={mail}>{(enabled) => (enabled ? <RequestForm /> : <NoMail />)}</QueryState>
      </Card>
      <p className={styles.back}>
        <Link to="/sign-in">{t('forgot.backToSignIn')}</Link>
      </p>
    </main>
  )
}

function RequestForm() {
  const {t} = useTranslation()
  const request = useRequestPasswordReset()
  const [login, setLogin] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    request.mutate(login.trim())
  }

  if (request.isSuccess) {
    return (
      <p role="status" className={styles.text}>
        {t('forgot.sent')}
      </p>
    )
  }
  return (
    <form onSubmit={submit}>
      <FormLayout>
        <p className={styles.text}>{t('forgot.text')}</p>
        <Field label={t('forgot.login')}>
          <TextInput
            value={login}
            onChange={(event) => setLogin(event.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
          />
        </Field>
        {request.isError && <FormError>{describeError(request.error, t)}</FormError>}
        <FormActions>
          <Button type="submit" disabled={request.isPending}>
            {t('forgot.submit')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}

function NoMail() {
  const {t} = useTranslation()
  return <p className={styles.text}>{t('forgot.noMail')}</p>
}
