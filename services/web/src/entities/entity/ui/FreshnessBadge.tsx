import {useTranslation} from 'react-i18next'

import type {Schemas} from '@/shared/api'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Badge, type Tone} from '@/shared/ui'

const TONE: Record<Schemas['Freshness'], Tone> = {fresh: 'ok', stale: 'warn', doubtful: 'danger'}

/** When the place was last confirmed, coloured by how much it can be trusted. */
export function FreshnessBadge(props: {freshness: Schemas['Freshness']; verifiedAt: string | null}) {
  const {t, i18n} = useTranslation()
  if (props.verifiedAt === null) {
    return (
      <Badge tone={props.freshness === 'doubtful' ? 'danger' : 'neutral'} dot>
        {t('entity.neverChecked')}
      </Badge>
    )
  }
  const verifiedAt = new Date(props.verifiedAt)
  return (
    <Badge tone={TONE[props.freshness]} dot title={formatDateTime(verifiedAt, i18n.language)}>
      {t('entity.checked', {when: formatRelative(verifiedAt, i18n.language)})}
    </Badge>
  )
}
