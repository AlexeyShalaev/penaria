import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {
  type EntityChanges,
  type EntityDetail,
  NameFields,
  type Privacy,
  PrivacyField,
  QuantityFields,
  STATUSES,
  type Status,
  useUpdateEntity,
} from '@/entities/entity'
import {describeError} from '@/shared/api'
import {splitList} from '@/shared/lib/text'
import {Button, Dialog, Field, FormActions, FormError, FormLayout, Select} from '@/shared/ui'

type Props = {entity: EntityDetail; onClose: () => void}

export function EditEntityDialog({entity, onClose}: Props) {
  const {t} = useTranslation()
  const update = useUpdateEntity(entity.id)
  return (
    <Dialog title={t('edit.title', {name: entity.name})} closeLabel={t('common.close')} onClose={onClose}>
      {/* A newer version of the entity starts the form again from what is saved now. */}
      <EditForm
        key={entity.version}
        entity={entity}
        error={update.isError ? describeError(update.error, t) : null}
        pending={update.isPending}
        onCancel={onClose}
        onSave={(changes) => {
          if (Object.keys(changes).length === 0) return onClose()
          update.mutate({version: entity.version, ...changes}, {onSuccess: onClose})
        }}
      />
    </Dialog>
  )
}

type Changes = Omit<EntityChanges, 'version'>

function EditForm(props: {
  entity: EntityDetail
  error: string | null
  pending: boolean
  onCancel: () => void
  onSave: (changes: Changes) => void
}) {
  const {t} = useTranslation()
  const {entity} = props
  const [name, setName] = useState(entity.name)
  const [aliases, setAliases] = useState(entity.aliases.join(', '))
  const [quantity, setQuantity] = useState(entity.quantity ?? '')
  const [unit, setUnit] = useState(entity.unit ?? '')
  const [status, setStatus] = useState<Status>(entity.status)
  const [privacy, setPrivacy] = useState<Privacy>(entity.privacy)

  // Only what changed is sent: a field left alone never overwrites someone else's change to it.
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const changes: Changes = {}
    if (name.trim() !== entity.name) changes.name = name.trim()
    const newAliases = splitList(aliases)
    if (newAliases.join('\n') !== entity.aliases.join('\n')) changes.aliases = newAliases
    if (quantity.trim() !== (entity.quantity ?? '')) changes.quantity = quantity.trim() || null
    if (unit.trim() !== (entity.unit ?? '')) changes.unit = unit.trim()
    if (status !== entity.status) changes.status = status
    if (privacy !== entity.privacy) changes.privacy = privacy
    props.onSave(changes)
  }

  return (
    <form onSubmit={submit}>
      <FormLayout>
        <NameFields name={{value: name, onChange: setName}} aliases={{value: aliases, onChange: setAliases}} />
        <QuantityFields quantity={{value: quantity, onChange: setQuantity}} unit={{value: unit, onChange: setUnit}} />
        <Field label={t('fields.status')}>
          <Select value={status} onChange={(event) => setStatus(event.target.value as Status)}>
            {STATUSES.map((option) => (
              <option key={option} value={option}>
                {t(`status.${option}`)}
              </option>
            ))}
          </Select>
        </Field>
        <PrivacyField value={privacy} onChange={setPrivacy} />
        {props.error && <FormError>{props.error}</FormError>}
        <FormActions>
          <Button variant="secondary" onClick={props.onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={props.pending}>
            {t('common.save')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
