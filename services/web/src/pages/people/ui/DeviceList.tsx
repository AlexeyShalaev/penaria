import {useTranslation} from 'react-i18next'

import {RoleBadge, scopeLabel, useDevices, useRevokeGrant} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatRelative} from '@/shared/lib/time'
import {Button, FormError, QueryState} from '@/shared/ui'

import styles from './Lists.module.css'

/** Devices and integrations whose tokens work, with when and where each was last used; revoking one ends it at once. */
export function DeviceList(props: {homeId: string}) {
  const {t, i18n} = useTranslation()
  const devices = useDevices(props.homeId)
  const revoke = useRevokeGrant(props.homeId)

  return (
    <QueryState query={devices}>
      {(list) =>
        list.length === 0 ? (
          <p className={styles.empty}>{t('people.noDevices')}</p>
        ) : (
          <>
            <ul className={styles.list}>
              {list.map((device) => (
                <li key={device.id} className={styles.row}>
                  <div className={styles.body}>
                    <span className={styles.title}>{device.name}</span>
                    <span className={styles.grant}>
                      <RoleBadge role={device.role} />
                      <span className={styles.details}>{scopeLabel(device.scope, t)}</span>
                    </span>
                    <span className={styles.details}>
                      {device.last_used_at
                        ? t(device.last_used_ip ? 'people.lastUsedFrom' : 'people.lastUsed', {
                            when: formatRelative(new Date(device.last_used_at), i18n.language),
                            address: device.last_used_ip,
                          })
                        : t('people.notUsed')}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending && revoke.variables === device.grant_id}
                    onClick={() => revoke.mutate(device.grant_id)}
                    aria-label={t('people.revokeDevice', {name: device.name})}
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
