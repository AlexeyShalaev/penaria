import {KeyRound, ShieldCheck} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, Navigate, useNavigate, useSearchParams} from 'react-router'

import {SecondFactorForm, SignInForm} from '@/features/sign-in'
import {PasskeySignInButton} from '@/features/sign-in-with-passkey'
import {type SecondFactorChallenge, useAccount, useSetupStatus} from '@/entities/account'
import {useMailEnabled} from '@/entities/install'
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
  const mail = useMailEnabled()
  const withPasskey = passkeysSupported()
  const signedIn = () => navigate(next, {replace: true})
  // Set once the password was right for an account with an authenticator app: its code comes next.
  const [challenge, setChallenge] = useState<SecondFactorChallenge | null>(null)

  return (
    <main className={styles.page}>
      <QueryState query={setup}>
        {(status) => {
          if (status.needed) return <Navigate to="/setup" replace />
          if (account.data) return <Navigate to={next} replace />
          if (challenge)
            return (
              <>
                <div className={styles.intro}>
                  <IconTile icon={ShieldCheck} size="lg" accent />
                  <PageTitle>{t('twoStep.title')}</PageTitle>
                </div>
                <Card className={styles.card}>
                  <SecondFactorForm challenge={challenge} onSignedIn={signedIn} onBack={() => setChallenge(null)} />
                </Card>
              </>
            )
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
                <SignInForm
                  onSignedIn={signedIn}
                  onSecondFactor={setChallenge}
                  submitVariant={withPasskey ? 'secondary' : 'primary'}
                />
                {mail.data && (
                  <p className={styles.forgot}>
                    <Link to="/forgot-password">{t('signIn.forgot')}</Link>
                  </p>
                )}
              </Card>
            </>
          )
        }}
      </QueryState>
    </main>
  )
}
