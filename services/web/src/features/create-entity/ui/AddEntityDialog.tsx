import {type FormEvent, useId, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {
  childKinds,
  type EntityDetail,
  KIND_ICON,
  type Kind,
  PlacePicker,
  PRIVACIES,
  type Privacy,
  useCreateEntity,
} from '@/entities/entity'
import {describeError} from '@/shared/api'
import {splitList} from '@/shared/lib/text'
import {Button, Chip, Dialog, Field, FormActions, FormError, FormLayout, Select, TextInput} from '@/shared/ui'

import styles from './AddEntityDialog.module.css'

export type Place = {id: string; kind: Kind; name: string}

type Props = {
  homeId: string
  /** Where the new entity goes; null is the top of the home. */
  parent: Place | null
  /** Let the person pick another place than `parent`. */
  canChangePlace?: boolean
  onClose: () => void
  onCreated: (entity: EntityDetail) => void
}

export function AddEntityDialog({homeId, canChangePlace, onClose, onCreated, ...props}: Props) {
  const {t} = useTranslation()
  const create = useCreateEntity(homeId)
  const kindLabelId = useId()
  const [parent, setParent] = useState(props.parent)
  const [picking, setPicking] = useState(false)
  const kinds = childKinds(parent?.kind ?? null)
  const [chosenKind, setKind] = useState<Kind | undefined>(kinds[0])
  const kind = chosenKind && kinds.includes(chosenKind) ? chosenKind : kinds[0]
  const [name, setName] = useState('')
  const [aliases, setAliases] = useState('')
  const [quantity, setQuantity] = useState('')
  const [unit, setUnit] = useState('')
  const [privacy, setPrivacy] = useState<Privacy>('normal')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!kind) return
    create.mutate(
      {
        kind,
        parent_id: parent?.id ?? null,
        name: name.trim(),
        aliases: splitList(aliases),
        quantity: quantity.trim() || null,
        unit: unit.trim() || null,
        privacy,
      },
      {onSuccess: onCreated},
    )
  }

  return (
    <Dialog
      title={parent ? t('create.titleInside', {name: parent.name}) : t('create.title')}
      closeLabel={t('common.close')}
      onClose={onClose}
    >
      <form onSubmit={submit}>
        <FormLayout>
          {canChangePlace && (
            <div className={styles.place}>
              <span className={styles.label}>{t('create.place')}</span>
              <div className={styles.placeRow}>
                <span className={styles.placeName}>{parent ? parent.name : t('picker.top')}</span>
                <Button size="sm" variant="ghost" onClick={() => setPicking((value) => !value)} aria-expanded={picking}>
                  {picking ? t('create.placeDone') : t('create.placeChange')}
                </Button>
              </div>
              {picking && (
                <PlacePicker
                  homeId={homeId}
                  value={parent?.id ?? null}
                  allowTop
                  canPick={(place) => place.archived_at === null && childKinds(place.kind).length > 0}
                  onChange={(place) => setParent(place && {id: place.id, kind: place.kind, name: place.name})}
                />
              )}
            </div>
          )}

          <div className={styles.place}>
            <span className={styles.label} id={kindLabelId}>
              {t('create.kind')}
            </span>
            {kinds.length === 0 ? (
              <p className={styles.note}>{t('create.nothingInside')}</p>
            ) : (
              <div className={styles.kinds} role="radiogroup" aria-labelledby={kindLabelId}>
                {kinds.map((option) => (
                  <Chip
                    key={option}
                    role="radio"
                    aria-checked={option === kind}
                    icon={KIND_ICON[option]}
                    onClick={() => setKind(option)}
                  >
                    {t(`kinds.${option}`)}
                  </Chip>
                ))}
              </div>
            )}
          </div>

          <Field label={t('fields.name')}>
            <TextInput value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} />
          </Field>
          <Field label={t('fields.aliases')} hint={t('fields.aliasesHint')}>
            <TextInput value={aliases} onChange={(event) => setAliases(event.target.value)} />
          </Field>
          {kind === 'item' && (
            <div className={styles.pair}>
              <Field label={t('fields.quantity')}>
                <TextInput
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="any"
                  value={quantity}
                  onChange={(event) => setQuantity(event.target.value)}
                />
              </Field>
              <Field label={t('fields.unit')}>
                <TextInput
                  value={unit}
                  placeholder={t('fields.unitPlaceholder')}
                  onChange={(event) => setUnit(event.target.value)}
                />
              </Field>
            </div>
          )}
          <Field label={t('fields.privacy')}>
            <Select value={privacy} onChange={(event) => setPrivacy(event.target.value as Privacy)}>
              {PRIVACIES.map((option) => (
                <option key={option} value={option}>
                  {t(`privacy.${option}`)}
                </option>
              ))}
            </Select>
          </Field>

          {create.isError && <FormError>{describeError(create.error, t)}</FormError>}
          <FormActions>
            <Button variant="secondary" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!kind || create.isPending}>
              {t('create.submit')}
            </Button>
          </FormActions>
        </FormLayout>
      </form>
    </Dialog>
  )
}
