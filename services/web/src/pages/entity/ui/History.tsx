import {History as HistoryIcon} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {useHistory} from '@/entities/entity'
import {describeError} from '@/shared/api'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Card, Empty, ErrorState, Loading} from '@/shared/ui'

import {describeEvent} from '../model/history'
import styles from './EntityPage.module.css'

export function History({entityId}: {entityId: string}) {
  const {t, i18n} = useTranslation()
  const history = useHistory(entityId)
  if (history.isPending) return <Loading label={t('common.loading')} />
  if (history.isError) {
    return (
      <ErrorState
        message={describeError(history.error, t)}
        retryLabel={t('common.retry')}
        onRetry={() => void history.refetch()}
      />
    )
  }
  if (history.data.length === 0) return <Empty icon={HistoryIcon} title={t('history.empty')} />
  return (
    <Card>
      <ol className={styles.timeline}>
        {history.data.map((event) => {
          const at = new Date(event.at)
          return (
            <li key={event.id} className={styles.event}>
              <time dateTime={event.at} title={formatDateTime(at, i18n.language)} className={styles.when}>
                {formatRelative(at, i18n.language)}
              </time>
              {describeEvent(event, t).map((line) => (
                <p key={line} className={styles.what}>
                  {line}
                </p>
              ))}
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
