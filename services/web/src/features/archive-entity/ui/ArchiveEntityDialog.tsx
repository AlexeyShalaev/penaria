import {useId, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {ARCHIVE_REASONS, type ArchiveReason, type EntityDetail, useArchiveEntity} from '@/entities/entity'
import {describeError} from '@/shared/api'
import {Button, Chip, Dialog, FormActions, FormError, FormLayout} from '@/shared/ui'

import styles from './ArchiveEntityDialog.module.css'

type Props = {entity: EntityDetail; onClose: () => void}

export function ArchiveEntityDialog({entity, onClose}: Props) {
  const {t} = useTranslation()
  const archive = useArchiveEntity(entity.id)
  const [reason, setReason] = useState<ArchiveReason | null>(null)
  const labelId = useId()

  return (
    <Dialog title={t('archive.title', {name: entity.name})} closeLabel={t('common.close')} onClose={onClose}>
      <FormLayout>
        <p className={styles.text}>{t('archive.text')}</p>
        <div className={styles.group}>
          <span id={labelId} className={styles.label}>
            {t('archive.reason')}
          </span>
          <div className={styles.reasons} role="radiogroup" aria-labelledby={labelId}>
            {ARCHIVE_REASONS.map((option) => (
              <Chip key={option} role="radio" aria-checked={option === reason} onClick={() => setReason(option)}>
                {t(`archiveReason.${option}`)}
              </Chip>
            ))}
          </div>
        </div>
        {archive.isError && <FormError>{describeError(archive.error, t)}</FormError>}
        <FormActions>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="danger"
            disabled={reason === null || archive.isPending}
            onClick={() => reason && archive.mutate({reason, version: entity.version}, {onSuccess: onClose})}
          >
            {t('archive.submit')}
          </Button>
        </FormActions>
      </FormLayout>
    </Dialog>
  )
}
