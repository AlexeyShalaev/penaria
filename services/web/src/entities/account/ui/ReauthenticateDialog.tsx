import {KeyRound} from 'lucide-react'
import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {passkeysSupported} from '@/shared/lib/webauthn'
import {Button, Dialog, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

import {usePasskeys, useReauthenticate, useReauthenticateWithPasskey} from '../api/passkeys'
import {useSecondFactor} from '../api/secondFactor'
import {describePasskeyError} from '../model/passkeys'
import {secondFactorCode} from '../model/secondFactor'
import styles from './ReauthenticateDialog.module.css'
import {SecondFactorField} from './SecondFactorField'

type Props = {onConfirmed: () => void; onClose: () => void}

/**
 * Asks the person to prove it is them again, with a passkey or the password, before a sensitive change; with the
 * password, a code from the authenticator app too while the account has one.
 */
export function ReauthenticateDialog({onConfirmed, onClose}: Props) {
  const {t} = useTranslation()
  const passkeys = usePasskeys({enabled: passkeysSupported()})
  const withPassword = useReauthenticate()
  const withPasskey = useReauthenticateWithPasskey()
  const secondFactor = useSecondFactor()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState(false)
  const asksCode = !!secondFactor.data?.totp_enabled
  const offerPasskey = passkeysSupported() && (passkeys.data?.length ?? 0) > 0
  const busy = withPassword.isPending || withPasskey.isPending
  const failed = withPasskey.error ?? withPassword.error

  const submit = (event: FormEvent) => {
    event.preventDefault()
    withPasskey.reset()
    withPassword.mutate({password, ...(asksCode ? secondFactorCode(code, recovery) : {})}, {onSuccess: onConfirmed})
  }

  const confirmWithPasskey = () => {
    withPassword.reset()
    withPasskey.mutate(undefined, {onSuccess: onConfirmed})
  }

  return (
    <Dialog title={t('reauthenticate.title')} closeLabel={t('common.close')} onClose={onClose}>
      <form onSubmit={submit}>
        <FormLayout>
          <p className={styles.text}>{t('reauthenticate.text')}</p>
          {offerPasskey && (
            <>
              <Button icon={KeyRound} disabled={busy} onClick={confirmWithPasskey}>
                {t('reauthenticate.usePasskey')}
              </Button>
              <p className={styles.or}>{t('reauthenticate.orPassword')}</p>
            </>
          )}
          <Field label={t('reauthenticate.password')}>
            <TextInput
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          {asksCode && (
            <SecondFactorField
              value={code}
              onChange={setCode}
              recovery={recovery}
              onToggle={() => {
                setRecovery(!recovery)
                setCode('')
              }}
            />
          )}
          {failed && <FormError>{describePasskeyError(failed, t)}</FormError>}
          <FormActions>
            <Button variant="secondary" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" variant={offerPasskey ? 'secondary' : 'primary'} disabled={busy}>
              {t('reauthenticate.submit')}
            </Button>
          </FormActions>
        </FormLayout>
      </form>
    </Dialog>
  )
}
