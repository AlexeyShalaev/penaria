import {Smartphone} from 'lucide-react'
import {type FormEvent, useId, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useConfirmTotp, useRecentSignIn, useStartTotp} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Button, Field, FormActions, FormError, FormLayout, QrCode, TextInput} from '@/shared/ui'

import {RecoveryCodes} from './RecoveryCodes'
import styles from './TwoStep.module.css'

const GROUP = 4

/**
 * Sets up an authenticator app: a QR code and the key to type by hand, a first code to turn it on, then the
 * recovery codes. `onStarted` runs when the secret is shown, `onDone` once the codes are put away, so a parent
 * that switches on the account's state can keep this open until then.
 */
export function TotpSetup(props: {onStarted?: () => void; onDone?: () => void; onCancel?: () => void}) {
  const {t} = useTranslation()
  const start = useStartTotp()
  const confirm = useConfirmTotp()
  const recent = useRecentSignIn()
  const [code, setCode] = useState('')
  const keyId = useId()

  const begin = () => {
    confirm.reset()
    setCode('')
    start.mutate(undefined, {onSuccess: props.onStarted, onError: recent.retryOnError(begin)})
  }

  const cancel = () => {
    start.reset()
    confirm.reset()
    props.onCancel?.()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    confirm.mutate(code.replace(/\s/g, ''))
  }

  if (confirm.data) return <RecoveryCodes codes={confirm.data.codes} onDone={() => props.onDone?.()} />

  const failed = recent.errorToShow(start.error)
  if (!start.data)
    return (
      <div className={styles.idle}>
        <Button icon={Smartphone} disabled={start.isPending} onClick={begin}>
          {t('twoStep.setUp')}
        </Button>
        {failed && <FormError>{describeError(failed, t)}</FormError>}
        {recent.dialog}
      </div>
    )

  const {secret, uri} = start.data
  return (
    <div className={styles.scan}>
      <QrCode value={uri} label={t('twoStep.qr')} />
      <form className={styles.side} onSubmit={submit}>
        <FormLayout>
          <p className={styles.text}>{t('twoStep.scan')}</p>
          <div className={styles.keyField}>
            <span id={keyId} className={styles.keyLabel}>
              {t('twoStep.key')}
            </span>
            <code className={styles.key} aria-labelledby={keyId}>
              {groups(secret)}
            </code>
          </div>
          <Field label={t('twoStep.code')} hint={t('twoStep.codeHint')}>
            <TextInput
              value={code}
              onChange={(event) => setCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={16}
              required
            />
          </Field>
          {confirm.isError && <FormError>{describeError(confirm.error, t)}</FormError>}
          <FormActions>
            <Button variant="secondary" onClick={cancel}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={confirm.isPending}>
              {t('twoStep.turnOn')}
            </Button>
          </FormActions>
        </FormLayout>
      </form>
    </div>
  )
}

/** The key as apps show it, in groups of four, which is easier to type; apps ignore the spaces. */
function groups(secret: string): string {
  return secret.match(new RegExp(`.{1,${GROUP}}`, 'g'))?.join(' ') ?? secret
}
