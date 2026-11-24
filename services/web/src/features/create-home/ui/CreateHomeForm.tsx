import {type FormEvent, useMemo, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type Home, useCreateHome} from '@/entities/home'
import {describeError} from '@/shared/api'
import {browserTimeZone, timeZones} from '@/shared/lib/time'
import {Button, Field, FormActions, FormError, FormLayout, Select, TextInput} from '@/shared/ui'

export function CreateHomeForm(props: {onCreated: (home: Home) => void}) {
  const {t, i18n} = useTranslation()
  const create = useCreateHome()
  const [name, setName] = useState('')
  const [timezone, setTimezone] = useState(browserTimeZone)
  const zones = useMemo(() => {
    const all = timeZones()
    return all.includes(timezone) ? all : [timezone, ...all]
  }, [timezone])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate({name: name.trim(), timezone, locale: i18n.language}, {onSuccess: props.onCreated})
  }

  return (
    <form onSubmit={submit}>
      <FormLayout>
        <Field label={t('homes.name')}>
          <TextInput
            value={name}
            placeholder={t('homes.namePlaceholder')}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={200}
          />
        </Field>
        <Field label={t('homes.timezone')} hint={t('homes.timezoneHint')}>
          <Select value={timezone} onChange={(event) => setTimezone(event.target.value)}>
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replaceAll('_', ' ')}
              </option>
            ))}
          </Select>
        </Field>
        {create.isError && <FormError>{describeError(create.error, t)}</FormError>}
        <FormActions>
          <Button type="submit" disabled={create.isPending}>
            {t('homes.create')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
