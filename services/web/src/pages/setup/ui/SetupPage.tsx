import {House} from 'lucide-react'
import {useTranslation} from 'react-i18next'
import {Navigate, useNavigate} from 'react-router'

import {SetupForm} from '@/features/setup'
import {useSetupStatus} from '@/entities/account'
import {Card, IconTile, PageTitle, QueryState} from '@/shared/ui'

import styles from './SetupPage.module.css'

// A command, the same in every language; the service is named as in the Compose quickstart.
const READ_TOKEN = 'docker compose logs penaria-server | grep "setup token"'

/** The first visit to a fresh install: the setup token from the server's log makes the first account. */
export function SetupPage() {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const status = useSetupStatus()

  return (
    <main className={styles.page}>
      <QueryState query={status}>
        {({needed}) =>
          needed ? (
            <>
              <div className={styles.intro}>
                <IconTile icon={House} size="lg" accent />
                <PageTitle>{t('setup.title')}</PageTitle>
                <p className={styles.text}>{t('setup.text')}</p>
              </div>
              <section className={styles.where} aria-labelledby="setup-token-where">
                <h2 id="setup-token-where">{t('setup.tokenTitle')}</h2>
                <p>{t('setup.tokenText')}</p>
                <pre className={styles.command}>
                  <code>{READ_TOKEN}</code>
                </pre>
                <p>{t('setup.tokenRestart')}</p>
              </section>
              <Card className={styles.card}>
                <SetupForm onDone={() => navigate('/', {replace: true})} />
              </Card>
            </>
          ) : (
            <Navigate to="/sign-in" replace />
          )
        }
      </QueryState>
    </main>
  )
}
