import {History as HistoryIcon} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {useHistory} from '@/entities/entity'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Card, Empty, QueryState} from '@/shared/ui'

import {describeEvent} from '../model/history'
import styles from './History.module.css'

export function History({entityId}: {entityId: string}) {
  const {t, i18n} = useTranslation()
  const history = useHistory(entityId)
  return (
    <QueryState query={history}>
      {(events) =>
        events.length === 0 ? (
          <Empty icon={HistoryIcon} title={t('history.empty')} />
        ) : (
          <Card>
            <ol className={styles.timeline}>
              {events.map((event) => {
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
    </QueryState>
  )
}
