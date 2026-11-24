import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type Account, useCompleteSetup, useNewAccountFields} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Button, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

import styles from './SetupForm.module.css'

export function SetupForm(props: {onDone: (account: Account) => void}) {
  const {t, i18n} = useTranslation()
  const setup = useCompleteSetup()
  const account = useNewAccountFields()
  const [token, setToken] = useState('')
  const [problem, setProblem] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const read = account.read()
    setProblem(read.problem)
    if (!read.account) return
    setup.mutate({...read.account, token: token.trim(), locale: i18n.language}, {onSuccess: props.onDone})
  }

  const error = problem ?? (setup.isError ? describeError(setup.error, t) : null)
  return (
    <form onSubmit={submit}>
      <FormLayout>
        <Field label={t('setup.token')}>
          <TextInput
            className={styles.token}
            value={token}
            onChange={(event) => setToken(event.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            required
          />
        </Field>
        {account.fields}
        {error && <FormError>{error}</FormError>}
        <FormActions>
          <Button type="submit" disabled={setup.isPending}>
            {t('setup.submit')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
