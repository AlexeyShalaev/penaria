import {KeyRound} from 'lucide-react'
import {useTranslation} from 'react-i18next'
import {Navigate, useNavigate, useSearchParams} from 'react-router'

import {SignInForm} from '@/features/sign-in'
import {useAccount, useSetupStatus} from '@/entities/account'
import {Card, IconTile, PageTitle, QueryState} from '@/shared/ui'

import styles from './AuthPage.module.css'

/** Where the guard sends a request without a session; `next` is the page to return to. */
export function SignInPage() {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const account = useAccount()
  const setup = useSetupStatus()

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
                <SignInForm onSignedIn={() => navigate(next, {replace: true})} />
              </Card>
            </>
          )
        }}
      </QueryState>
    </main>
  )
}

// Only a path of this app: a link to sign in must not send anyone to another site afterwards.
function safeNext(next: string | null): string {
  return next?.startsWith('/') && !next.startsWith('//') ? next : '/'
}
