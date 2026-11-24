import {LogIn} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {useAuthConfig, useStartProviderInvitation, useStartProviderSignIn} from '@/entities/account'
import {describeError} from '@/shared/api'
import {Button, FormError} from '@/shared/ui'

import styles from './ProviderButtons.module.css'

/** "Sign in with Authentik": shown only when the operator set a provider up; `returnTo` is the page to come back to. */
export function ProviderSignInButton(props: {returnTo: string; variant?: 'primary' | 'secondary'}) {
  const {t, i18n} = useTranslation()
  const config = useAuthConfig()
  const start = useStartProviderSignIn()
  const provider = config.data?.oidc
  if (!provider) return null
  return (
    <div className={styles.root}>
      <Button
        icon={LogIn}
        variant={props.variant}
        className={styles.button}
        disabled={start.isPending || start.isSuccess}
        onClick={() => start.mutate({locale: i18n.language, return_to: props.returnTo})}
      >
        {t('provider.signIn', {name: provider.name})}
      </Button>
      {start.isError && <FormError>{describeError(start.error, t)}</FormError>}
    </div>
  )
}

/** "Join with Authentik": accepts the invitation with an identity at the provider, making an account if needed. */
export function ProviderInvitationButton(props: {token: string}) {
  const {t, i18n} = useTranslation()
  const config = useAuthConfig()
  const start = useStartProviderInvitation()
  const provider = config.data?.oidc
  if (!provider) return null
  return (
    <div className={styles.root}>
      <Button
        icon={LogIn}
        variant="secondary"
        className={styles.button}
        disabled={start.isPending || start.isSuccess}
        onClick={() => start.mutate({token: props.token, locale: i18n.language})}
      >
        {t('provider.join', {name: provider.name})}
      </Button>
      {start.isError && <FormError>{describeError(start.error, t)}</FormError>}
    </div>
  )
}
