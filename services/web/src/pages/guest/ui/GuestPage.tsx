import {Clock, DoorClosed, MapPinHouse} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {EntityTree} from '@/entities/entity'
import {type GuestVisit, placeLabel, useGuestVisit} from '@/entities/member'
import {toggled} from '@/shared/lib/set'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Badge, Card, CardTitle, Empty, IconTile, PageTitle, QueryState} from '@/shared/ui'

import styles from './GuestPage.module.css'

/** A guest's visit: the home, when the visit ends, and where the things meant for guests are. */
export function GuestPage() {
  const {t} = useTranslation()
  const visit = useGuestVisit()
  return (
    <QueryState query={visit}>
      {(data) =>
        data ? (
          <Visit visit={data} />
        ) : (
          <main className={styles.narrow}>
            <Card className={styles.ended}>
              <IconTile icon={DoorClosed} size="lg" />
              <PageTitle>{t('guest.endedTitle')}</PageTitle>
              <p className={styles.muted}>{t('guest.endedText')}</p>
            </Card>
          </main>
        )
      }
    </QueryState>
  )
}

function Visit(props: {visit: GuestVisit}) {
  const {t, i18n} = useTranslation()
  const {visit} = props
  // Places start open: a guest has a few things to find, not a house to browse.
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set())
  const expanded = {has: (id: string) => !closed.has(id)}
  const ends = new Date(visit.expires_at)
  return (
    <div className={styles.visit}>
      <header className={styles.hero}>
        <div className={styles.heroInner}>
          <Badge icon={Clock} title={formatDateTime(ends, i18n.language)}>
            {t('guest.until', {when: formatDateTime(ends, i18n.language)})}
          </Badge>
          <p className={styles.welcome}>{t('guest.welcome')}</p>
          <h1 className={styles.home}>{visit.home.name}</h1>
          <p className={styles.heroText}>{t('guest.endsIn', {when: formatRelative(ends, i18n.language)})}</p>
        </div>
      </header>
      <main className={styles.content}>
        <Card as="section" padded={false} aria-labelledby="guest-things">
          <div className={styles.cardHead}>
            <CardTitle id="guest-things">{t('guest.things')}</CardTitle>
            {visit.scope && <p className={styles.muted}>{t('guest.within', {place: placeLabel(visit.scope.names)})}</p>}
          </div>
          <EntityTree
            homeId={visit.home.id}
            parentId={visit.scope?.id ?? null}
            expanded={expanded}
            onToggle={(id) => setClosed((current) => toggled(current, id))}
            readOnly
            empty={<Empty icon={MapPinHouse} title={t('guest.nothingTitle')} text={t('guest.nothingText')} />}
          />
        </Card>
        <p className={styles.footnote}>{t('guest.footnote')}</p>
      </main>
    </div>
  )
}
