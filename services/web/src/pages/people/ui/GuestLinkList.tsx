import {Clock} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {placeLabel, useGuestLinks, useRevokeGrant} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatRelative} from '@/shared/lib/time'
import {Badge, Button, FormError, QueryState} from '@/shared/ui'

import styles from './Lists.module.css'

/** Guest links that still open, with when each ends; revoking one ends every visit made with it. */
export function GuestLinkList(props: {homeId: string}) {
  const {t, i18n} = useTranslation()
  const links = useGuestLinks(props.homeId)
  const revoke = useRevokeGrant(props.homeId)

  return (
    <QueryState query={links}>
      {(list) =>
        list.length === 0 ? (
          <p className={styles.empty}>{t('people.noGuestLinks')}</p>
        ) : (
          <>
            <ul className={styles.list}>
              {list.map((link) => (
                <li key={link.id} className={styles.row}>
                  <div className={styles.body}>
                    <span className={styles.title}>{link.name}</span>
                    <span className={styles.grant}>
                      <Badge tone="warn" icon={Clock}>
                        {t('people.endsIn', {when: formatRelative(new Date(link.expires_at), i18n.language)})}
                      </Badge>
                      <span className={styles.details}>
                        {link.scope ? placeLabel(link.scope.names) : t('people.wholeHome')}
                      </span>
                    </span>
                    <span className={styles.details}>
                      {link.last_used_at
                        ? t('people.lastOpened', {when: formatRelative(new Date(link.last_used_at), i18n.language)})
                        : t('people.notOpened')}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending && revoke.variables === link.grant_id}
                    onClick={() => revoke.mutate(link.grant_id)}
                    aria-label={t('people.revokeLink', {name: link.name})}
                  >
                    {t('people.revoke')}
                  </Button>
                </li>
              ))}
            </ul>
            {revoke.isError && <FormError>{describeError(revoke.error, t)}</FormError>}
          </>
        )
      }
    </QueryState>
  )
}
