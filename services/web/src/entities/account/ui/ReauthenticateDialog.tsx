import {KeyRound} from 'lucide-react'
import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {passkeysSupported} from '@/shared/lib/webauthn'
import {Button, Dialog, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

import {usePasskeys, useReauthenticate, useReauthenticateWithPasskey} from '../api/passkeys'
import {describePasskeyError} from '../model/passkeys'
import styles from './ReauthenticateDialog.module.css'

type Props = {onConfirmed: () => void; onClose: () => void}

/** Asks the person to prove it is them again, with a passkey or the password, before a sensitive change. */
export function ReauthenticateDialog({onConfirmed, onClose}: Props) {
  const {t} = useTranslation()
  const passkeys = usePasskeys({enabled: passkeysSupported()})
  const withPassword = useReauthenticate()
  const withPasskey = useReauthenticateWithPasskey()
  const [password, setPassword] = useState('')
  const offerPasskey = passkeysSupported() && (passkeys.data?.length ?? 0) > 0
  const busy = withPassword.isPending || withPasskey.isPending
  const failed = withPasskey.error ?? withPassword.error

  const submit = (event: FormEvent) => {
    event.preventDefault()
    withPasskey.reset()
    withPassword.mutate(password, {onSuccess: onConfirmed})
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
