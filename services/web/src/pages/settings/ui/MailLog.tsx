import {ChevronDown, Inbox, RotateCw} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {type LoggedMail, useMailLog, useResendMail} from '@/entities/install'
import {describeError} from '@/shared/api'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Badge, Button, Empty, ErrorState, Loading, type Tone} from '@/shared/ui'

import styles from './MailLog.module.css'

const STATE_TONE: Record<LoggedMail['state'], Tone> = {sent: 'ok', queued: 'warn', failed: 'danger'}

/** Every email the install sent or tried to, the newest first, with each attempt and a way to send it again. */
export function MailLog() {
  const {t} = useTranslation()
  const log = useMailLog()

  if (log.isPending) return <Loading label={t('common.loading')} />
  if (log.isError) {
    return (
      <ErrorState
        message={describeError(log.error, t)}
        retryLabel={t('common.retry')}
        onRetry={() => void log.refetch()}
      />
    )
  }
  const mails = log.data.pages.flat()
  if (mails.length === 0) return <Empty icon={Inbox} title={t('mailLog.empty')} text={t('mailLog.emptyText')} />
  return (
    <>
      <ul className={styles.list}>
        {mails.map((mail) => (
          <MailRow key={mail.id} mail={mail} />
        ))}
      </ul>
      {log.hasNextPage && (
        <div className={styles.more}>
          <Button variant="secondary" disabled={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
            {t('mailLog.more')}
          </Button>
        </div>
      )}
    </>
  )
}

function MailRow(props: {mail: LoggedMail}) {
  const {t, i18n} = useTranslation()
  const {mail} = props
  const [open, setOpen] = useState(false)
  const resend = useResendMail()
  const latest = mail.attempts[0]
  const detailsId = `mail-${mail.id}`

  return (
    <li className={styles.row}>
      <div className={styles.summary}>
        <div className={styles.what}>
          <span className={styles.subject}>{mail.subject}</span>
          <span className={styles.meta}>
            {t(`mailLog.kind.${mail.kind}`)} · {mail.to} ·{' '}
            <time dateTime={mail.created_at} title={formatDateTime(new Date(mail.created_at), i18n.language)}>
              {formatRelative(new Date(mail.created_at), i18n.language)}
            </time>
          </span>
        </div>
        <div className={styles.side}>
          <Badge tone={STATE_TONE[mail.state]} dot>
            {mail.state === 'queued' && mail.next_attempt_at
              ? t('mailLog.retryAt', {when: formatRelative(new Date(mail.next_attempt_at), i18n.language)})
              : t(`mailLog.state.${mail.state}`)}
          </Badge>
          {mail.resendable && (
            <Button
              variant="ghost"
              size="sm"
              icon={RotateCw}
              disabled={resend.isPending}
              onClick={() => resend.mutate(mail.id)}
            >
              {t('mailLog.resend')}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            icon={ChevronDown}
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={() => setOpen(!open)}
          >
            {t('mailLog.attempts', {count: mail.attempts.length})}
          </Button>
        </div>
      </div>
      {latest && !latest.ok && !open && (
        <p className={styles.reason}>{latest.error ?? t(`mailLog.reason.${latest.reason ?? 'other'}`)}</p>
      )}
      {resend.isError && <p className={styles.reason}>{describeError(resend.error, t)}</p>}
      {resend.data && (
        <p role="status" className={resend.data.ok ? styles.resent : styles.reason}>
          {resend.data.ok ? t('mailLog.resent') : (resend.data.error ?? t('mailLog.notResent'))}
        </p>
      )}
      {open && (
        <ol id={detailsId} className={styles.attempts}>
          {mail.attempts.map((attempt) => (
            <li key={attempt.at} className={styles.attempt}>
              <Badge tone={attempt.ok ? 'ok' : 'danger'}>
                {attempt.ok ? t('mailLog.sent') : t(`mailLog.reason.${attempt.reason ?? 'other'}`)}
              </Badge>
              <span className={styles.meta}>
                {formatDateTime(new Date(attempt.at), i18n.language)}
                {attempt.manual && ` · ${t('mailLog.byAdmin')}`}
              </span>
              {attempt.error && (
                <code className={styles.words}>
                  {attempt.smtp_code ? `${attempt.smtp_code} ` : ''}
                  {attempt.error}
                </code>
              )}
            </li>
          ))}
        </ol>
      )}
    </li>
  )
}
