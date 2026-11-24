import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type Account, useRecentSignIn, useRemoveEmail, useRequestEmailChange} from '@/entities/account'
import {useMailEnabled} from '@/entities/install'
import {describeError} from '@/shared/api'
import {Badge, Button, Field, FormActions, FormError, FormLayout, QueryState, TextInput} from '@/shared/ui'

import styles from './EmailForm.module.css'

/**
 * The account's email: reset links and notices go there. An address is the account's only once the
 * link mailed to it is opened, so without outgoing mail none can be added.
 */
export function EmailForm(props: {account: Account}) {
  const {t} = useTranslation()
  const mail = useMailEnabled()
  return (
    <QueryState query={mail}>
      {(enabled) => (
        <>
          {props.account.email && <Current email={props.account.email} />}
          {enabled ? (
            <ChangeEmail hasEmail={!!props.account.email} />
          ) : (
            <p className={styles.text}>{t('email.noMail')}</p>
          )}
        </>
      )}
    </QueryState>
  )
}

function Current(props: {email: string}) {
  const {t} = useTranslation()
  const remove = useRemoveEmail()
  const recent = useRecentSignIn()
  const removeEmail = () => {
    const send = () => remove.mutate(undefined, {onError: recent.retryOnError(send)})
    send()
  }
  const error = recent.errorToShow(remove.error)
  return (
    <div className={styles.current}>
      <span className={styles.address}>{props.email}</span>
      <Badge tone="ok" dot>
        {t('email.confirmed')}
      </Badge>
      <Button variant="ghost" size="sm" disabled={remove.isPending} onClick={removeEmail}>
        {t('email.remove')}
      </Button>
      {error && <FormError>{describeError(error, t)}</FormError>}
      {recent.dialog}
    </div>
  )
}

function ChangeEmail(props: {hasEmail: boolean}) {
  const {t} = useTranslation()
  const request = useRequestEmailChange()
  const recent = useRecentSignIn()
  const [email, setEmail] = useState('')

  // Reset links go to this address, so changing it asks to confirm it is you, as adding a passkey does.
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const address = email.trim()
    const send = () => request.mutate(address, {onSuccess: () => setEmail(''), onError: recent.retryOnError(send)})
    send()
  }
  const error = recent.errorToShow(request.error)

  return (
    <form onSubmit={submit}>
      <FormLayout>
        <Field label={props.hasEmail ? t('email.newAddress') : t('email.address')} hint={t('email.hint')}>
          <TextInput
            type="email"
            inputMode="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
          />
        </Field>
        {error && <FormError>{describeError(error, t)}</FormError>}
        {request.isSuccess && (
          <p role="status" className={styles.sent}>
            {t('email.sent', {email: request.data.email})}
          </p>
        )}
        <FormActions>
          <Button type="submit" variant="secondary" disabled={request.isPending}>
            {t('email.send')}
          </Button>
        </FormActions>
      </FormLayout>
      {recent.dialog}
    </form>
  )
}
