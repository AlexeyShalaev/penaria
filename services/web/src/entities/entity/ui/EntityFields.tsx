import {useTranslation} from 'react-i18next'

import {Field, Select, TextInput} from '@/shared/ui'

import {PRIVACIES, type Privacy} from '../model/kinds'
import styles from './EntityFields.module.css'

type Text = {value: string; onChange: (value: string) => void}

/** The name and the other names (comma-separated) of an entity, as the forms edit them. */
export function NameFields(props: {name: Text; aliases: Text}) {
  const {t} = useTranslation()
  return (
    <>
      <Field label={t('fields.name')}>
        <TextInput
          value={props.name.value}
          onChange={(event) => props.name.onChange(event.target.value)}
          required
          maxLength={200}
        />
      </Field>
      <Field label={t('fields.aliases')} hint={t('fields.aliasesHint')}>
        <TextInput value={props.aliases.value} onChange={(event) => props.aliases.onChange(event.target.value)} />
      </Field>
    </>
  )
}

export function QuantityFields(props: {quantity: Text; unit: Text}) {
  const {t} = useTranslation()
  return (
    <div className={styles.pair}>
      <Field label={t('fields.quantity')}>
        <TextInput
          type="number"
          inputMode="decimal"
          min="0"
          step="any"
          value={props.quantity.value}
          onChange={(event) => props.quantity.onChange(event.target.value)}
        />
      </Field>
      <Field label={t('fields.unit')}>
        <TextInput
          value={props.unit.value}
          placeholder={t('fields.unitPlaceholder')}
          onChange={(event) => props.unit.onChange(event.target.value)}
        />
      </Field>
    </div>
  )
}

export function PrivacyField(props: {value: Privacy; onChange: (value: Privacy) => void}) {
  const {t} = useTranslation()
  return (
    <Field label={t('fields.privacy')}>
      <Select value={props.value} onChange={(event) => props.onChange(event.target.value as Privacy)}>
        {PRIVACIES.map((option) => (
          <option key={option} value={option}>
            {t(`privacy.${option}`)}
          </option>
        ))}
      </Select>
    </Field>
  )
}
