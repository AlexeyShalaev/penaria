import {ArrowLeft, MapPinHouse} from 'lucide-react'
import {useTranslation} from 'react-i18next'
import {Link, useNavigate} from 'react-router'

import {CreateHomeForm} from '@/features/create-home'
import {useHomes} from '@/entities/home'
import {Card, IconTile, PageTitle, QueryState} from '@/shared/ui'

import styles from './NewHomePage.module.css'

/** The first home of a new install (a welcome), or one more home. */
export function NewHomePage() {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const homes = useHomes()

  return (
    <main className={styles.page}>
      <QueryState query={homes}>
        {(list) => {
          const first = list.length === 0
          return (
            <>
              {!first && (
                <Link to="/" className={styles.back}>
                  <ArrowLeft aria-hidden />
                  {t('common.back')}
                </Link>
              )}
              <div className={styles.intro}>
                <IconTile icon={MapPinHouse} size="lg" accent />
                <PageTitle>{t(first ? 'homes.welcomeTitle' : 'homes.newTitle')}</PageTitle>
                <p className={styles.text}>{t(first ? 'homes.welcomeText' : 'homes.newText')}</p>
              </div>
              <Card className={styles.card}>
                <CreateHomeForm onCreated={(home) => navigate(`/homes/${home.id}/places`)} />
              </Card>
            </>
          )
        }}
      </QueryState>
    </main>
  )
}
