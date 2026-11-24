import {Link2, Unlink} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {
  type ExternalIdentity,
  useRecentSignIn,
  useSignInMethods,
  useStartProviderLink,
  useUnlinkIdentity,
} from '@/entities/account'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {Button, FormError, QueryState} from '@/shared/ui'

import styles from './LinkedAccounts.module.css'

/**
 * The account's identity at the operator's provider: link one to sign in with it, or unlink it. Shown only when
 * the install has a provider.
 */
export function LinkedAccounts(props: {provider: string}) {
  const {t} = useTranslation()
  const methods = useSignInMethods()
  const link = useStartProviderLink()
  const unlink = useUnlinkIdentity()
  const recent = useRecentSignIn()
  const failed = recent.errorToShow(link.error) ?? recent.errorToShow(unlink.error)

  const startLink = () => link.mutate({return_to: '/account'}, {onError: recent.retryOnError(startLink)})
  const remove = (identity: ExternalIdentity) =>
    unlink.mutate(identity.id, {onError: recent.retryOnError(() => remove(identity))})

  return (
    <QueryState query={methods}>
      {(data) => (
        <div className={styles.root}>
          {data.external_identities.length === 0 ? (
            <>
              <p className={styles.text}>{t('linked.none', {name: props.provider})}</p>
              <div>
                <Button icon={Link2} variant="secondary" disabled={link.isPending} onClick={startLink}>
                  {t('linked.link', {name: props.provider})}
                </Button>
              </div>
            </>
          ) : (
            <ul className={styles.list}>
              {data.external_identities.map((identity) => (
                <IdentityRow
                  key={identity.id}
                  identity={identity}
                  provider={props.provider}
                  busy={unlink.isPending}
                  onUnlink={() => remove(identity)}
                />
              ))}
            </ul>
          )}
          {failed && <FormError>{describeError(failed, t)}</FormError>}
          {recent.dialog}
        </div>
      )}
    </QueryState>
  )
}

function IdentityRow(props: {identity: ExternalIdentity; provider: string; busy: boolean; onUnlink: () => void}) {
  const {t, i18n} = useTranslation()
  return (
    <li className={styles.row}>
      <div className={styles.body}>
        <span className={styles.title}>{props.provider}</span>
        <span className={styles.details}>
          {t(props.identity.email ? 'linked.detailsEmail' : 'linked.details', {
            email: props.identity.email,
            when: formatDateTime(new Date(props.identity.created_at), i18n.language),
          })}
        </span>
      </div>
      <Button
        variant="ghost"
        size="sm"
        icon={Unlink}
        disabled={props.busy}
        onClick={props.onUnlink}
        aria-label={t('linked.unlinkLabel', {name: props.provider})}
      >
        {t('linked.unlink')}
      </Button>
    </li>
  )
}
