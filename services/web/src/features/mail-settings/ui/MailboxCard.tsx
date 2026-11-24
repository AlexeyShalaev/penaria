import {Lock, Send} from 'lucide-react'
import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useRecentSignIn} from '@/entities/account'
import {
  type Mailbox,
  type MailSecurity,
  useMailboxStatus,
  useRemoveMailbox,
  useSaveMailbox,
  useSendTestMail,
} from '@/entities/install'
import {describeError} from '@/shared/api'
import {Badge, Button, Card, CardTitle, Field, FormActions, FormError, Select, TextInput} from '@/shared/ui'

import {
  draftOf,
  inputOf,
  isDirty,
  isEmail,
  type MailboxDraft,
  type MailboxIssues,
  SECURITIES,
  validateMailbox,
  withSecurity,
} from '../model/mailbox'
import styles from './MailboxCard.module.css'

/**
 * The install's mailbox: the SMTP server every email goes through, a test email and the connection's
 * status. A mailbox set by the server's environment shows locked.
 */
export function MailboxCard(props: {mailbox: Mailbox; ownEmail: string | null}) {
  const {t} = useTranslation()
  const {mailbox} = props
  const on = mailbox.source !== null
  const locked = mailbox.source === 'environment'
  // Held here, so their outcome outlives the form, which starts anew from every saved mailbox.
  const save = useSaveMailbox()
  const remove = useRemoveMailbox()

  return (
    <Card as="section" aria-labelledby="settings-mail">
      <header className={styles.header}>
        <CardTitle id="settings-mail">{t('mail.title')}</CardTitle>
        <StatusLine on={on} />
      </header>
      <p className={styles.text}>{t('mail.text')}</p>
      {!on && <p className={styles.notice}>{t('mail.offNotice')}</p>}
      {locked && (
        <p className={styles.notice}>
          <Lock aria-hidden className={styles.noticeIcon} />
          {t('mail.lockedNotice')}
        </p>
      )}
      {/* A new form when the saved mailbox changes, so it starts from what is saved. */}
      <MailboxForm
        key={JSON.stringify(mailbox)}
        mailbox={mailbox}
        locked={locked}
        on={on}
        ownEmail={props.ownEmail}
        save={save}
        remove={remove}
      />
    </Card>
  )
}

function StatusLine(props: {on: boolean}) {
  const {t} = useTranslation()
  const status = useMailboxStatus(props.on)
  if (!props.on) return <Badge dot>{t('mail.off')}</Badge>
  if (status.isPending) return <Badge dot>{t('mail.checking')}</Badge>
  if (status.data?.health === 'ok') {
    return (
      <Badge tone="ok" dot>
        {t('mail.connected')}
      </Badge>
    )
  }
  const error = status.data?.error ?? (status.isError ? describeError(status.error, t) : undefined)
  return (
    <Badge tone="danger" dot title={error}>
      {t('mail.notConnected')}
    </Badge>
  )
}

function MailboxForm(props: {
  mailbox: Mailbox
  locked: boolean
  on: boolean
  ownEmail: string | null
  save: ReturnType<typeof useSaveMailbox>
  remove: ReturnType<typeof useRemoveMailbox>
}) {
  const {t} = useTranslation()
  const {mailbox, locked, save, remove} = props
  const recent = useRecentSignIn()
  const [draft, setDraft] = useState<MailboxDraft>(() => draftOf(mailbox))
  const [shown, setShown] = useState<MailboxIssues>({})
  const dirty = isDirty(draft, mailbox)

  const set = (changes: Partial<MailboxDraft>) => setDraft((current) => ({...current, ...changes}))
  const issue = (key: keyof MailboxIssues) => (shown[key] ? t(`mail.issue.${shown[key]}`) : undefined)
  const lockMark = locked ? (
    <Badge icon={Lock} title={t('mail.lockedHint')}>
      {t('mail.locked')}
    </Badge>
  ) : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const issues = validateMailbox(draft, mailbox)
    setShown(issues)
    if (Object.keys(issues).length > 0) return
    const send = () =>
      save.mutate(inputOf(draft), {
        // The form starts from what was saved, the password field empty again, even when the answer
        // looks as before (only the password changed).
        onSuccess: (saved) => setDraft(draftOf(saved)),
        onError: recent.retryOnError(send),
      })
    send()
  }
  const turnOff = () => {
    const send = () => remove.mutate(undefined, {onError: recent.retryOnError(send)})
    send()
  }

  const error = recent.errorToShow(save.error) ?? recent.errorToShow(remove.error)
  return (
    <>
      <form onSubmit={submit} className={styles.form} noValidate>
        <div className={styles.serverRow}>
          <Field label={t('mail.host')} hint={t('mail.hostHint')} aside={lockMark} error={issue('host')}>
            <TextInput
              value={draft.host}
              onChange={(event) => set({host: event.target.value})}
              placeholder="smtp.example.org"
              disabled={locked}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={!!shown.host}
            />
          </Field>
          <Field label={t('mail.port')} error={issue('port')}>
            <TextInput
              className={styles.port}
              value={draft.port}
              onChange={(event) => set({port: event.target.value})}
              inputMode="numeric"
              disabled={locked}
              aria-invalid={!!shown.port}
            />
          </Field>
        </div>
        <Field label={t('mail.security')} hint={t('mail.securityHint')} aside={lockMark}>
          <Select
            value={draft.security}
            onChange={(event) => setDraft(withSecurity(draft, event.target.value as MailSecurity))}
            disabled={locked}
          >
            {SECURITIES.map((security) => (
              <option key={security} value={security}>
                {t(`mail.securityOption.${security}`)}
              </option>
            ))}
          </Select>
        </Field>
        <div className={styles.pair}>
          <Field label={t('mail.username')} hint={t('mail.usernameHint')} aside={lockMark}>
            <TextInput
              value={draft.username}
              onChange={(event) => set({username: event.target.value})}
              disabled={locked}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
          <Field
            label={t('mail.password')}
            hint={mailbox.password_set ? t('mail.passwordSetHint') : t('mail.passwordHint')}
            error={issue('password')}
            aside={
              lockMark ??
              (mailbox.password_set && (
                <Badge tone="ok" dot>
                  {t('mail.passwordSet')}
                </Badge>
              ))
            }
          >
            <TextInput
              type="password"
              value={draft.password}
              onChange={(event) => set({password: event.target.value})}
              placeholder={mailbox.password_set ? t('mail.passwordKeep') : ''}
              disabled={locked}
              autoComplete="new-password"
              name="smtp-password"
              aria-invalid={!!shown.password}
            />
          </Field>
        </div>
        <div className={styles.pair}>
          <Field
            label={t('mail.fromAddress')}
            hint={t('mail.fromAddressHint')}
            aside={lockMark}
            error={issue('from_address')}
          >
            <TextInput
              type="email"
              value={draft.from_address}
              onChange={(event) => set({from_address: event.target.value})}
              placeholder="home@example.org"
              disabled={locked}
              inputMode="email"
              aria-invalid={!!shown.from_address}
            />
          </Field>
          <Field label={t('mail.fromName')} hint={t('mail.fromNameHint')} aside={lockMark}>
            <TextInput
              value={draft.from_name}
              onChange={(event) => set({from_name: event.target.value})}
              placeholder="Penaria"
              disabled={locked}
              maxLength={100}
            />
          </Field>
        </div>
        {error && <FormError>{describeError(error, t)}</FormError>}
        {!locked && (
          <FormActions>
            {save.isSuccess && !dirty && (
              <span role="status" className={styles.saved}>
                {t('mail.saved')}
              </span>
            )}
            {mailbox.source === 'interface' && (
              <Button variant="ghost" disabled={remove.isPending} onClick={turnOff}>
                {t('mail.turnOff')}
              </Button>
            )}
            <Button type="submit" disabled={save.isPending || !dirty}>
              {t('common.save')}
            </Button>
          </FormActions>
        )}
      </form>
      <TestMail on={props.on} dirty={dirty} ownEmail={props.ownEmail} />
      {recent.dialog}
    </>
  )
}

function TestMail(props: {on: boolean; dirty: boolean; ownEmail: string | null}) {
  const {t} = useTranslation()
  const test = useSendTestMail()
  const [to, setTo] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const typed = to.trim()
  const invalid = typed !== '' && !isEmail(typed)
  const recipient = typed || props.ownEmail
  const blocker = !props.on
    ? t('mail.test.needMailbox')
    : props.dirty
      ? t('mail.test.saveFirst')
      : !recipient
        ? t('mail.test.needAddress')
        : null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (blocker || invalid) return
    setSentTo(recipient)
    test.mutate(typed || null)
  }

  return (
    <form className={styles.test} onSubmit={submit} noValidate>
      <h3 className={styles.testTitle}>{t('mail.test.title')}</h3>
      <p className={styles.text}>{t('mail.test.text')}</p>
      <div className={styles.testRow}>
        <Field label={t('mail.test.to')} error={invalid ? t('mail.test.toInvalid') : undefined}>
          <TextInput
            type="email"
            inputMode="email"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            placeholder={props.ownEmail ?? 'someone@example.org'}
            aria-invalid={invalid}
          />
        </Field>
        <Button type="submit" variant="secondary" icon={Send} disabled={!!blocker || invalid || test.isPending}>
          {test.isPending ? t('mail.test.sending') : t('mail.test.send')}
        </Button>
      </div>
      {blocker && <p className={styles.hint}>{blocker}</p>}
      {test.isError && <FormError>{describeError(test.error, t)}</FormError>}
      {test.data?.ok === true && (
        <p role="status" className={styles.sent}>
          {t('mail.test.sent', {to: sentTo})}
        </p>
      )}
      {test.data?.ok === false && (
        <div role="alert" className={styles.failed}>
          <span>{t('mail.test.failed')}</span>
          {test.data.error && <code className={styles.serverWords}>{test.data.error}</code>}
        </div>
      )}
    </form>
  )
}
