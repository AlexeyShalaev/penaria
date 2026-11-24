import {KeyRound} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {type Account, describePasskeyError, useSignInWithPasskey} from '@/entities/account'
import {Button, FormError} from '@/shared/ui'

import styles from './PasskeySignInButton.module.css'

/** Signs in with a passkey the person picks in the browser's prompt; shown only where passkeys work. */
export function PasskeySignInButton(props: {onSignedIn: (account: Account) => void}) {
  const {t} = useTranslation()
  const signIn = useSignInWithPasskey()

  return (
    <div className={styles.root}>
      <Button
        icon={KeyRound}
        className={styles.button}
        disabled={signIn.isPending}
        onClick={() => signIn.mutate(undefined, {onSuccess: props.onSignedIn})}
      >
        {t('passkeys.signIn')}
      </Button>
      {signIn.isError && <FormError>{describePasskeyError(signIn.error, t)}</FormError>}
    </div>
  )
}
