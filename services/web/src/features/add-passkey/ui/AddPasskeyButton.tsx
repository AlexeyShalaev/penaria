import {Plus} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {describePasskeyError, deviceName, useAddPasskey, useRecentSignIn} from '@/entities/account'
import {Button, FormError} from '@/shared/ui'

import styles from './AddPasskeyButton.module.css'

/**
 * Makes a passkey on this device and adds it to the account, named after the browser and system;
 * asks the person to confirm it is them first when their sign-in is not recent.
 */
export function AddPasskeyButton({variant = 'secondary'}: {variant?: 'primary' | 'secondary'}) {
  const {t} = useTranslation()
  const add = useAddPasskey()
  const recent = useRecentSignIn()

  const failed = recent.errorToShow(add.error)

  const start = () =>
    add.mutate(deviceName(navigator.userAgent, t, t('passkeys.defaultName')), {onError: recent.retryOnError(start)})

  return (
    <div className={styles.root}>
      <Button variant={variant} icon={Plus} disabled={add.isPending} onClick={start}>
        {t('passkeys.add')}
      </Button>
      {failed && <FormError>{describePasskeyError(failed, t)}</FormError>}
      {add.isSuccess && (
        <p role="status" className={styles.status}>
          {t('passkeys.added')}
        </p>
      )}
      {recent.dialog}
    </div>
  )
}
