import {useTranslation} from 'react-i18next'
import {Navigate} from 'react-router'

import {useHomes} from '@/entities/home'
import {describeError} from '@/shared/api'
import {readLastHome} from '@/shared/lib/lastHome'
import {ErrorState, Loading} from '@/shared/ui'

import styles from './StartPage.module.css'

/** Opens the home used last, or the first one; with no home yet, the welcome page. */
export function StartPage() {
  const {t} = useTranslation()
  const homes = useHomes()
  if (homes.isPending) return <Loading label={t('common.loading')} />
  if (homes.isError) {
    return (
      <div className={styles.page}>
        <ErrorState
          message={describeError(homes.error, t)}
          retryLabel={t('common.retry')}
          onRetry={() => void homes.refetch()}
        />
      </div>
    )
  }
  const last = readLastHome()
  const home = homes.data.find((item) => item.id === last) ?? homes.data[0]
  return <Navigate to={home ? `/homes/${home.id}/places` : '/homes/new'} replace />
}
