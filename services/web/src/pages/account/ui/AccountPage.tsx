import {LogOut} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {AddPasskeyButton} from '@/features/add-passkey'
import {EmailForm} from '@/features/account-email'
import {ChangePasswordForm} from '@/features/change-password'
import {AccountForm} from '@/features/edit-account'
import {PasskeyList} from '@/features/manage-passkeys'
import {SessionList} from '@/features/manage-sessions'
import {TwoStepSignIn} from '@/features/two-step-sign-in'
import {useAccount, useSignOut} from '@/entities/account'
import {describeError} from '@/shared/api'
import {passkeysSupported} from '@/shared/lib/webauthn'
import {Button, Card, CardTitle, FormError, PageTitle, QueryState} from '@/shared/ui'

import styles from './AccountPage.module.css'

/** The signed-in person's own account: their name, language, password, passkeys, two-step sign-in and devices. */
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
              <Card as="section" className={styles.wide} aria-labelledby="account-email">
                <CardTitle id="account-email">{t('email.title')}</CardTitle>
                <p className={styles.text}>{t('email.text')}</p>
                <EmailForm account={data} />
              </Card>
              <Card as="section" id="passkeys" className={styles.wide} aria-labelledby="account-passkeys">
                <CardTitle id="account-passkeys">{t('passkeys.title')}</CardTitle>
                <p className={styles.text}>{t('passkeys.text')}</p>
                <PasskeyList />
                <div className={styles.passkeyActions}>
                  {passkeysSupported() ? (
                    <AddPasskeyButton />
                  ) : (
                    <p className={styles.text}>{t('passkeys.unsupported')}</p>
                  )}
                </div>
              </Card>
              <Card as="section" id="two-step" className={styles.wide} aria-labelledby="account-two-step">
                <CardTitle id="account-two-step">{t('twoStep.title')}</CardTitle>
                <p className={styles.text}>{t('twoStep.text')}</p>
                <TwoStepSignIn />
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
