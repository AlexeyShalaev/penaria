import {KeyRound, LogIn} from 'lucide-react'
import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {passkeysSupported} from '@/shared/lib/webauthn'
import {Button, Dialog, Field, FormActions, FormError, FormLayout, TextInput} from '@/shared/ui'

import {useAuthConfig, useReauthenticateWithProvider, useSignInMethods} from '../api/oidc'
import {usePasskeys, useReauthenticate, useReauthenticateWithPasskey} from '../api/passkeys'
import {useSecondFactor} from '../api/secondFactor'
import {describePasskeyError} from '../model/passkeys'
import {secondFactorCode} from '../model/secondFactor'
import styles from './ReauthenticateDialog.module.css'
import {SecondFactorField} from './SecondFactorField'

type Props = {onConfirmed: () => void; onClose: () => void}

/**
 * Asks the person to prove it is them again, with a passkey, the password or the operator's provider, before a
 * sensitive change; with the password or the provider, a code from the authenticator app too while the account
 * has one. The provider takes the browser away and back, so the change is made again afterwards.
 */
export function ReauthenticateDialog({onConfirmed, onClose}: Props) {
  const {t} = useTranslation()
  const passkeys = usePasskeys({enabled: passkeysSupported()})
  const withPassword = useReauthenticate()
  const withPasskey = useReauthenticateWithPasskey()
  const withProvider = useReauthenticateWithProvider()
  const secondFactor = useSecondFactor()
  const methods = useSignInMethods()
  const provider = useAuthConfig().data?.oidc
  const offerProvider = !!provider && (methods.data?.external_identities.length ?? 0) > 0
  const offerPassword = methods.data?.password ?? true
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState(false)
  const asksCode = !!secondFactor.data?.totp_enabled
  const offerPasskey = passkeysSupported() && (passkeys.data?.length ?? 0) > 0
  const busy = withPassword.isPending || withPasskey.isPending || withProvider.isPending
  const failed = withPasskey.error ?? withPassword.error ?? withProvider.error

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // Without a password, the form's one field is the code, which goes along to the provider, if any.
    if (!offerPassword) {
      if (offerProvider) confirmWithProvider()
      return
    }
    withPasskey.reset()
    withPassword.mutate({password, ...(asksCode ? secondFactorCode(code, recovery) : {})}, {onSuccess: onConfirmed})
  }

  const confirmWithPasskey = () => {
    withPassword.reset()
    withProvider.reset()
    withPasskey.mutate(undefined, {onSuccess: onConfirmed})
  }

  const confirmWithProvider = () => {
    withPassword.reset()
    withPasskey.reset()
    const returnTo = window.location.pathname + window.location.search
    withProvider.mutate({return_to: returnTo, ...(asksCode && code ? secondFactorCode(code, recovery) : {})})
  }

  return (
    <Dialog title={t('reauthenticate.title')} closeLabel={t('common.close')} onClose={onClose}>
      <form onSubmit={submit}>
        <FormLayout>
          <p className={styles.text}>{t('reauthenticate.text')}</p>
          {offerPasskey && (
            <Button icon={KeyRound} disabled={busy} onClick={confirmWithPasskey}>
              {t('reauthenticate.usePasskey')}
            </Button>
          )}
          {offerProvider && (
            <Button
              icon={LogIn}
              variant={offerPasskey ? 'secondary' : 'primary'}
              disabled={busy}
              onClick={confirmWithProvider}
            >
              {t('reauthenticate.useProvider', {name: provider?.name})}
            </Button>
          )}
          {offerProvider && asksCode && <p className={styles.text}>{t('reauthenticate.providerCode')}</p>}
          {(offerPasskey || offerProvider) && offerPassword && (
            <p className={styles.or}>{t('reauthenticate.orPassword')}</p>
          )}
          {offerPassword && (
            <Field label={t('reauthenticate.password')}>
              <TextInput
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </Field>
          )}
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
            {offerPassword && (
              <Button type="submit" variant={offerPasskey || offerProvider ? 'secondary' : 'primary'} disabled={busy}>
                {t('reauthenticate.submit')}
              </Button>
            )}
          </FormActions>
        </FormLayout>
      </form>
    </Dialog>
  )
}
