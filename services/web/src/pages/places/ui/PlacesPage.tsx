import {Archive, MapPinHouse, Plus} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'
import {useParams} from 'react-router'

import {AddEntityDialog} from '@/features/create-entity'
import {EntityTree, useChildren} from '@/entities/entity'
import {canEditHome, useHome} from '@/entities/home'
import {Button, Card, Chip, Empty, PageTitle, QueryState} from '@/shared/ui'

import {useExpanded} from '../model/expanded'
import {HomeCard} from './HomeCard'
import styles from './PlacesPage.module.css'

export function PlacesPage() {
  const {t} = useTranslation()
  const {homeId = ''} = useParams<{homeId: string}>()
  const home = useHome(homeId)
  const tops = useChildren(homeId, null)
  const {expanded, toggle, open} = useExpanded(homeId, tops.data?.map((entity) => entity.id) ?? [])
  const [showArchived, setShowArchived] = useState(false)
  const [adding, setAdding] = useState(false)

  return (
    <QueryState query={home}>
      {(data) => {
        const canEdit = canEditHome(data)
        return (
          <>
            <header className={styles.header}>
              <PageTitle>{t('places.title')}</PageTitle>
              <div className={styles.actions}>
                <Chip icon={Archive} pressed={showArchived} onClick={() => setShowArchived((value) => !value)}>
                  {t('places.showArchived')}
                </Chip>
                {canEdit && (
                  <Button icon={Plus} onClick={() => setAdding(true)}>
                    {t('places.add')}
                  </Button>
                )}
              </div>
            </header>

            <div className={styles.columns}>
              <Card padded={false}>
                <EntityTree
                  homeId={homeId}
                  includeArchived={showArchived}
                  expanded={expanded}
                  onToggle={toggle}
                  empty={
                    <Empty
                      icon={MapPinHouse}
                      title={t('places.emptyTitle')}
                      text={t('places.emptyText')}
                      action={
                        canEdit && (
                          <Button icon={Plus} onClick={() => setAdding(true)}>
                            {t('places.addProperty')}
                          </Button>
                        )
                      }
                    />
                  }
                />
              </Card>
              <HomeCard home={data} />
            </div>

            {adding && (
              <AddEntityDialog
                homeId={homeId}
                parent={null}
                canChangePlace
                onClose={() => setAdding(false)}
                onCreated={(entity) => {
                  setAdding(false)
                  open(entity.path.map((place) => place.id))
                }}
              />
            )}
          </>
        )
      }}
    </QueryState>
  )
}
