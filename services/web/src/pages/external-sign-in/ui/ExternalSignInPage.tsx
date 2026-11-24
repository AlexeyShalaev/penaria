import {CircleAlert} from 'lucide-react'
import {useTranslation} from 'react-i18next'
import {Link, useSearchParams} from 'react-router'

import {useAuthConfig} from '@/entities/account'
import {Card, IconTile, PageTitle} from '@/shared/ui'

import styles from './ExternalSignInPage.module.css'

const PROBLEMS = [
  'expired',
  'failed',
  'invitation_required',
  'identity_taken',
  'wrong_account',
  'account_disabled',
  'already_linked',
  'invitation_unusable',
] as const

type Problem = (typeof PROBLEMS)[number]

function problemOf(value: string | null): Problem {
  return PROBLEMS.find((problem) => problem === value) ?? 'failed'
}

/** Where the server sends the browser when a sign-in with the operator's provider did not go through, and why. */
export function ExternalSignInPage() {
  const {t} = useTranslation()
  const [params] = useSearchParams()
  const problem = problemOf(params.get('problem'))
  const name = useAuthConfig().data?.oidc?.name ?? t('provider.fallbackName')

  return (
    <main className={styles.page}>
      <div className={styles.intro}>
        <IconTile icon={CircleAlert} size="lg" accent />
        <PageTitle>{t(`provider.problems.${problem}.title`, {name})}</PageTitle>
      </div>
      <Card className={styles.card}>
        <p className={styles.text}>{t(`provider.problems.${problem}.text`, {name})}</p>
        <div className={styles.actions}>
          <Link to="/sign-in">{t('provider.backToSignIn')}</Link>
          <Link to="/account">{t('provider.toAccount')}</Link>
        </div>
      </Card>
    </main>
  )
}
