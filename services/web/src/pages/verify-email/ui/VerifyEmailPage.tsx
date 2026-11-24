import {MailCheck} from 'lucide-react'
import {useEffect, useRef} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, useParams} from 'react-router'

import {useConfirmEmail} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Card, FormError, IconTile, Loading, PageTitle} from '@/shared/ui'

import styles from './VerifyEmailPage.module.css'

/** Where a confirmation link leads: opening it confirms the address, with or without a session. */
export function VerifyEmailPage() {
  const {t} = useTranslation()
  const {token = ''} = useParams<{token: string}>()
  const confirm = useConfirmEmail(token)
  const {mutate} = confirm
  const sent = useRef(false)

  // A link works once: the page confirms on opening, and the effect running twice must not send it again.
  useEffect(() => {
    if (sent.current) return
    sent.current = true
    mutate()
  }, [mutate])

  return (
    <main className={styles.page}>
      <div className={styles.intro}>
        <IconTile icon={MailCheck} size="lg" accent />
        <PageTitle>{t('verifyEmail.title')}</PageTitle>
      </div>
      <Card className={styles.card}>
        {confirm.isSuccess && (
          <p role="status" className={styles.text}>
            {t('verifyEmail.done', {email: confirm.data.email})}
          </p>
        )}
        {confirm.isError && <FormError>{describeError(confirm.error, t)}</FormError>}
        {confirm.isPending && <Loading label={t('verifyEmail.checking')} />}
      </Card>
      <p className={styles.back}>
        <Link to="/account">{t('verifyEmail.toAccount')}</Link>
      </p>
    </main>
  )
}
