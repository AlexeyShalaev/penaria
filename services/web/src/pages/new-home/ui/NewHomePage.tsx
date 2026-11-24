import {ArrowLeft, MapPinHouse} from 'lucide-react'
import {useTranslation} from 'react-i18next'
import {Link, useNavigate} from 'react-router'

import {CreateHomeForm} from '@/features/create-home'
import {useHomes} from '@/entities/home'
import {Card, IconTile, Loading} from '@/shared/ui'

import styles from './NewHomePage.module.css'

/** The first home of a new install (a welcome), or one more home. */
export function NewHomePage() {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const homes = useHomes()
  if (homes.isPending) return <Loading label={t('common.loading')} />
  const first = !homes.data?.length

  return (
    <main className={styles.page}>
      {!first && (
        <Link to="/" className={styles.back}>
          <ArrowLeft aria-hidden />
          {t('common.back')}
        </Link>
      )}
      <div className={styles.intro}>
        <IconTile icon={MapPinHouse} size="lg" accent />
        <h1 className={styles.title}>{t(first ? 'homes.welcomeTitle' : 'homes.newTitle')}</h1>
        <p className={styles.text}>{t(first ? 'homes.welcomeText' : 'homes.newText')}</p>
      </div>
      <Card className={styles.card}>
        <CreateHomeForm onCreated={(home) => navigate(`/homes/${home.id}/places`)} />
      </Card>
    </main>
  )
}
