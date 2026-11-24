import {useTranslation} from 'react-i18next'

import {placeLabel, RoleBadge, useInvitations, useRevokeInvitation} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatRelative} from '@/shared/lib/time'
import {Badge, Button, FormError, QueryState} from '@/shared/ui'

import styles from './Lists.module.css'

/** Invitations not yet accepted; each can be revoked until it is. */
export function InvitationList(props: {homeId: string}) {
  const {t, i18n} = useTranslation()
  const invitations = useInvitations(props.homeId)
  const revoke = useRevokeInvitation(props.homeId)

  return (
    <QueryState query={invitations}>
      {(list) =>
        list.length === 0 ? (
          <p className={styles.empty}>{t('people.noInvitations')}</p>
        ) : (
          <>
            <ul className={styles.list}>
              {list.map((invitation) => (
                <li key={invitation.id} className={styles.row}>
                  <div className={styles.body}>
                    <span className={styles.grant}>
                      <RoleBadge role={invitation.role} />
                      <span className={styles.details}>
                        {invitation.scope ? placeLabel(invitation.scope.names) : t('people.wholeHome')}
                      </span>
                      {invitation.leave_when_accepted && <Badge tone="warn">{t('people.transfer')}</Badge>}
                    </span>
                    <span className={styles.details}>
                      {t('people.invitationDetails', {
                        name: invitation.created_by.display_name,
                        when: formatRelative(new Date(invitation.expires_at), i18n.language),
                      })}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending && revoke.variables === invitation.id}
                    onClick={() => revoke.mutate(invitation.id)}
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
