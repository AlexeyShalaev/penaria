import {useTranslation} from 'react-i18next'
import {Navigate} from 'react-router'

import {MailboxCard} from '@/features/mail-settings'
import {useAccount} from '@/entities/account'
import {useMailbox} from '@/entities/install'
import {Card, CardTitle, PageTitle, QueryState} from '@/shared/ui'

import {MailLog} from './MailLog'
import styles from './SettingsPage.module.css'

/** The install's own settings, for its admins: they apply to every home on it. */
export function SettingsPage() {
  const {t} = useTranslation()
  const account = useAccount()
  if (account.data && !account.data.install_admin) return <Navigate to="/" replace />
  return (
    <div className={styles.page}>
      <header>
        <PageTitle>{t('settings.title')}</PageTitle>
        <p className={styles.text}>{t('settings.text')}</p>
      </header>
      <Mail ownEmail={account.data?.email ?? null} />
    </div>
  )
}

function Mail(props: {ownEmail: string | null}) {
  const {t} = useTranslation()
  const mailbox = useMailbox()
  return (
    <QueryState query={mailbox}>
      {(data) => (
        <div className={styles.columns}>
          <MailboxCard mailbox={data} ownEmail={props.ownEmail} />
          <Card as="section" aria-labelledby="settings-mail-log">
            <CardTitle id="settings-mail-log">{t('mailLog.title')}</CardTitle>
            <p className={styles.text}>{t('mailLog.text')}</p>
            <MailLog />
          </Card>
        </div>
      )}
    </QueryState>
  )
}
