import {useTranslation} from 'react-i18next'

import styles from './HomePage.module.css'

export function HomePage() {
  const {t} = useTranslation()
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{t('home.title')}</h1>
      <p className={styles.subtitle}>{t('home.subtitle')}</p>
    </main>
  )
}
