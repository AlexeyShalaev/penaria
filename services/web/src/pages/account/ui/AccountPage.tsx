import {LogOut} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {ChangePasswordForm} from '@/features/change-password'
import {AccountForm} from '@/features/edit-account'
import {SessionList} from '@/features/manage-sessions'
import {useAccount, useSignOut} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Button, Card, CardTitle, FormError, PageTitle, QueryState} from '@/shared/ui'

import styles from './AccountPage.module.css'

/** The signed-in person's own account: their name, language, password and devices. */
export function AccountPage() {
  const {t} = useTranslation()
  const account = useAccount()
  const signOut = useSignOut()

  return (
    <QueryState query={account}>
      {(data) =>
        data && (
          <div className={styles.page}>
            <header className={styles.header}>
              <PageTitle>{t('account.title')}</PageTitle>
              <Button variant="secondary" icon={LogOut} disabled={signOut.isPending} onClick={() => signOut.mutate()}>
                {t('account.signOut')}
              </Button>
            </header>
            {signOut.isError && <FormError>{describeError(signOut.error, t)}</FormError>}
            <div className={styles.columns}>
              <Card as="section" aria-labelledby="account-profile">
                <CardTitle id="account-profile">{t('account.profile')}</CardTitle>
                <AccountForm account={data} />
              </Card>
              <Card as="section" aria-labelledby="account-password">
                <CardTitle id="account-password">{t('account.passwordTitle')}</CardTitle>
                <ChangePasswordForm />
              </Card>
              <Card as="section" className={styles.wide} aria-labelledby="account-sessions">
                <CardTitle id="account-sessions">{t('account.sessions')}</CardTitle>
                <p className={styles.text}>{t('account.sessionsText')}</p>
                <SessionList />
              </Card>
            </div>
          </div>
        )
      }
    </QueryState>
  )
}
