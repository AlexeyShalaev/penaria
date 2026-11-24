import {useTranslation} from 'react-i18next'

import {Field, TextInput} from '@/shared/ui'

import {toDateInput} from '../model/dates'

/** The last day of access; `required` for roles whose access must end, otherwise it may stay empty. */
export function ExpiryField(props: {
  label: string
  value: string
  onChange: (value: string) => void
  required: boolean
}) {
  const {t} = useTranslation()
  return (
    <Field label={props.label} hint={t(props.required ? 'people.endsRequired' : 'people.endsOptional')}>
      <TextInput
        type="date"
        value={props.value}
        min={toDateInput(new Date())}
        onChange={(event) => props.onChange(event.target.value)}
        required={props.required}
      />
    </Field>
  )
}
