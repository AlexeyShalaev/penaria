import {useTranslation} from 'react-i18next'

import type {Home} from '@/entities/home'
import {formatTimeZone} from '@/shared/lib/time'
import {Card, CardTitle, Facts} from '@/shared/ui'

export function HomeCard({home}: {home: Home}) {
  const {t, i18n} = useTranslation()
  const language = new Intl.DisplayNames([i18n.language], {type: 'language'}).of(home.locale) ?? home.locale
  const facts = [
    {label: t('homes.timezone'), value: formatTimeZone(home.timezone)},
    {label: t('homes.language'), value: language},
  ]
  if (home.access) facts.push({label: t('homes.access'), value: t(home.access.owner ? 'shell.owner' : 'shell.member')})
  return (
    <Card as="section" aria-label={home.name}>
      <CardTitle>{home.name}</CardTitle>
      <Facts items={facts} />
    </Card>
  )
}
