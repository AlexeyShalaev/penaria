import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type Account, useUpdateAccount} from '@/entities/account'
import {describeError} from '@/shared/api'
import {SUPPORTED_LANGUAGES} from '@/shared/i18n'
import {Button, Field, FormActions, FormError, FormLayout, Select, TextInput} from '@/shared/ui'

import styles from './AccountForm.module.css'

/** The account's name and the language of the interface. */
export function AccountForm(props: {account: Account}) {
  const {t} = useTranslation()
  const update = useUpdateAccount()
  const [displayName, setDisplayName] = useState(props.account.display_name)
  const [locale, setLocale] = useState(props.account.locale)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    update.mutate({display_name: displayName.trim(), locale})
  }

  return (
    <form onSubmit={submit}>
      <FormLayout>
        <Field label={t('account.username')}>
          <TextInput value={props.account.username} readOnly className={styles.readOnly} />
        </Field>
        <Field label={t('account.displayName')}>
          <TextInput
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            autoComplete="name"
            required
            maxLength={200}
          />
        </Field>
        <Field label={t('account.language')}>
          <Select value={locale} onChange={(event) => setLocale(event.target.value)}>
            {SUPPORTED_LANGUAGES.map((language) => (
              <option key={language} value={language}>
                {t(`languages.${language}`)}
              </option>
            ))}
          </Select>
        </Field>
        {update.isError && <FormError>{describeError(update.error, t)}</FormError>}
        <FormActions>
          {update.isSuccess && (
            <span role="status" className={styles.saved}>
              {t('account.saved')}
            </span>
          )}
          <Button type="submit" disabled={update.isPending}>
            {t('common.save')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
