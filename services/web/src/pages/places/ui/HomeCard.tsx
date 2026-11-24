import {useTranslation} from 'react-i18next'

import type {Home} from '@/entities/home'
import {Card} from '@/shared/ui'

import styles from './PlacesPage.module.css'

export function HomeCard({home}: {home: Home}) {
  const {t, i18n} = useTranslation()
  const language = new Intl.DisplayNames([i18n.language], {type: 'language'}).of(home.locale) ?? home.locale
  return (
    <Card as="section" aria-label={home.name}>
      <h2 className={styles.cardTitle}>{home.name}</h2>
      <dl className={styles.facts}>
        <dt>{t('homes.timezone')}</dt>
        <dd>{home.timezone.replaceAll('_', ' ')}</dd>
        <dt>{t('homes.language')}</dt>
        <dd>{language}</dd>
        {home.access && (
          <>
            <dt>{t('homes.access')}</dt>
            <dd>{t(home.access.owner ? 'shell.owner' : 'shell.member')}</dd>
          </>
        )}
      </dl>
    </Card>
  )
}
