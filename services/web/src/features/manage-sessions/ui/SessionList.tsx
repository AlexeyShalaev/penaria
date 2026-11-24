import {Monitor, Smartphone} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {
  type AccountSession,
  describeDevice,
  useRevokeOtherSessions,
  useRevokeSession,
  useSessions,
} from '@/entities/account'
import {describeError} from '@/shared/api'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Badge, Button, FormError, IconTile, QueryState} from '@/shared/ui'

import styles from './SessionList.module.css'

/** The account's open sessions, each of which but this one can be ended. */
export function SessionList() {
  const {t} = useTranslation()
  const sessions = useSessions()
  const revoke = useRevokeSession()
  const revokeOthers = useRevokeOtherSessions()
  const failed = revoke.error ?? revokeOthers.error

  return (
    <QueryState query={sessions}>
      {(list) => (
        <div className={styles.root}>
          <ul className={styles.list}>
            {[...list]
              .sort((a, b) => Number(b.current) - Number(a.current))
              .map((session) => (
                <SessionRow
                  key={session.id}
                  session={session}
                  onRevoke={() => revoke.mutate(session.id)}
                  busy={revoke.isPending && revoke.variables === session.id}
                />
              ))}
          </ul>
          {failed && <FormError>{describeError(failed, t)}</FormError>}
          {revokeOthers.isSuccess && (
            <p role="status" className={styles.status}>
              {t('account.othersRevoked', {count: revokeOthers.data.revoked})}
            </p>
          )}
          {list.some((session) => !session.current) && (
            <div className={styles.actions}>
              <Button variant="secondary" disabled={revokeOthers.isPending} onClick={() => revokeOthers.mutate()}>
                {t('account.revokeOthers')}
              </Button>
            </div>
          )}
        </div>
      )}
    </QueryState>
  )
}

function SessionRow(props: {session: AccountSession; onRevoke: () => void; busy: boolean}) {
  const {t, i18n} = useTranslation()
  const {session} = props
  const {browser, system} = describeDevice(session.user_agent)
  const device =
    browser && system ? t('account.deviceOn', {browser, system}) : (browser ?? system ?? t('account.unknownDevice'))
  const lastUsed = new Date(session.last_seen_at)
  const details = [
    session.ip,
    t('account.lastUsed', {when: formatRelative(lastUsed, i18n.language)}),
    t('account.signedInAt', {when: formatDateTime(new Date(session.created_at), i18n.language)}),
  ].filter(Boolean)
  return (
    <li className={styles.row}>
      <IconTile icon={system === 'iOS' || system === 'Android' ? Smartphone : Monitor} size="sm" />
      <div className={styles.text}>
        <span className={styles.device}>
          {device}
          {session.current && <Badge tone="ok">{t('account.thisDevice')}</Badge>}
        </span>
        <span className={styles.details} title={session.user_agent ?? undefined}>
          {details.join(' · ')}
        </span>
      </div>
      {!session.current && (
        <Button
          variant="ghost"
          size="sm"
          disabled={props.busy}
          onClick={props.onRevoke}
          aria-label={t('account.revokeLabel', {device})}
        >
          {t('account.revoke')}
        </Button>
      )}
    </li>
  )
}
