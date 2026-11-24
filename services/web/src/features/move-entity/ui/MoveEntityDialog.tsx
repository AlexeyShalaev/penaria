import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {canSitIn, type EntityDetail, PlacePicker, useMoveEntity} from '@/entities/entity'
import {describeError} from '@/shared/api'
import {Button, Dialog, FormActions, FormError, FormLayout} from '@/shared/ui'

import styles from './MoveEntityDialog.module.css'

type Props = {entity: EntityDetail; onClose: () => void}

export function MoveEntityDialog({entity, onClose}: Props) {
  const {t} = useTranslation()
  const move = useMoveEntity(entity.id)
  const [target, setTarget] = useState<string | null>(null)

  return (
    <Dialog title={t('move.title', {name: entity.name})} closeLabel={t('common.close')} onClose={onClose}>
      <FormLayout>
        <p className={styles.hint}>{t('move.hint')}</p>
        <PlacePicker
          homeId={entity.home_id}
          value={target}
          hiddenId={entity.id}
          initiallyExpanded={entity.path.map((place) => place.id)}
          canPick={(place) =>
            place.archived_at === null && place.id !== entity.parent_id && canSitIn(entity.kind, place.kind)
          }
          onChange={(place) => setTarget(place?.id ?? null)}
        />
        {move.isError && <FormError>{describeError(move.error, t)}</FormError>}
        <FormActions>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={target === null || move.isPending}
            onClick={() => target && move.mutate({parent_id: target, version: entity.version}, {onSuccess: onClose})}
          >
            {t('move.submit')}
          </Button>
        </FormActions>
      </FormLayout>
    </Dialog>
  )
}
