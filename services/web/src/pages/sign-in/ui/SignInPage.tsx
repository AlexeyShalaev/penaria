import {KeyRound} from 'lucide-react'
import {useTranslation} from 'react-i18next'
import {Navigate, useNavigate, useSearchParams} from 'react-router'

import {SignInForm} from '@/features/sign-in'
import {PasskeySignInButton} from '@/features/sign-in-with-passkey'
import {useAccount, useSetupStatus} from '@/entities/account'
import {passkeysSupported} from '@/shared/lib/webauthn'
import {Card, IconTile, PageTitle, QueryState} from '@/shared/ui'

import {safeNext} from '../model/next'
import styles from './SignInPage.module.css'

/** Where the guard sends a request without a session; `next` is the page to return to. */
export function SignInPage() {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const account = useAccount()
  const setup = useSetupStatus()
  const withPasskey = passkeysSupported()
  const signedIn = () => navigate(next, {replace: true})

  return (
    <main className={styles.page}>
      <QueryState query={setup}>
        {(status) => {
          if (status.needed) return <Navigate to="/setup" replace />
          if (account.data) return <Navigate to={next} replace />
          return (
            <>
              <div className={styles.intro}>
                <IconTile icon={KeyRound} size="lg" accent />
                <PageTitle>{t('signIn.title')}</PageTitle>
                <p className={styles.text}>{t('signIn.text')}</p>
              </div>
              <Card className={styles.card}>
                {withPasskey && (
                  <>
                    <PasskeySignInButton onSignedIn={signedIn} />
                    <p className={styles.or}>{t('passkeys.orPassword')}</p>
                  </>
                )}
                <SignInForm onSignedIn={signedIn} submitVariant={withPasskey ? 'secondary' : 'primary'} />
              </Card>
            </>
          )
        }}
      </QueryState>
    </main>
  )
}
