import type {Mailbox, MailboxInput, MailSecurity} from '@/entities/install'

/** The mailbox form as typed: every field a string, the port too, until it is saved. */
export type MailboxDraft = {
  host: string
  port: string
  security: MailSecurity
  username: string
  password: string
  from_address: string
  from_name: string
}

export type MailboxIssue = 'hostRequired' | 'portInvalid' | 'fromInvalid'
export type MailboxIssues = Partial<Record<'host' | 'port' | 'from_address', MailboxIssue>>

export const SECURITIES: readonly MailSecurity[] = ['starttls', 'tls', 'none']

/** The port each kind of security usually listens on, as the server's defaults. */
export const DEFAULT_PORT: Record<MailSecurity, number> = {starttls: 587, tls: 465, none: 25}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MAX_PORT = 65535

export function isEmail(value: string): boolean {
  return EMAIL.test(value.trim())
}

/** The form filled from the saved mailbox; the password field starts empty, since it is write-only. */
export function draftOf(mailbox: Mailbox): MailboxDraft {
  const security = mailbox.security ?? 'starttls'
  return {
    host: mailbox.host ?? '',
    port: String(mailbox.port ?? DEFAULT_PORT[security]),
    security,
    username: mailbox.username ?? '',
    password: '',
    from_address: mailbox.from_address ?? '',
    from_name: mailbox.from_name ?? '',
  }
}

/** The form with another security; the port follows it unless someone typed their own. */
export function withSecurity(draft: MailboxDraft, security: MailSecurity): MailboxDraft {
  const typedOwnPort = !Object.values(DEFAULT_PORT).includes(Number(draft.port))
  return {...draft, security, port: typedOwnPort ? draft.port : String(DEFAULT_PORT[security])}
}

export function validateMailbox(draft: MailboxDraft): MailboxIssues {
  const issues: MailboxIssues = {}
  if (draft.host.trim() === '') issues.host = 'hostRequired'
  const port = Number(draft.port)
  if (!/^\d+$/.test(draft.port.trim()) || port < 1 || port > MAX_PORT) issues.port = 'portInvalid'
  if (!isEmail(draft.from_address)) issues.from_address = 'fromInvalid'
  return issues
}

/** What is sent to save the form; an empty password keeps the saved one. */
export function inputOf(draft: MailboxDraft): MailboxInput {
  return {
    host: draft.host.trim(),
    port: Number(draft.port),
    security: draft.security,
    username: draft.username.trim() || null,
    password: draft.password || null,
    from_address: draft.from_address.trim(),
    from_name: draft.from_name.trim() || null,
  }
}

/** Whether the form differs from what is saved, so a test would not check what is on screen. */
export function isDirty(draft: MailboxDraft, mailbox: Mailbox): boolean {
  const saved = draftOf(mailbox)
  return (Object.keys(draft) as (keyof MailboxDraft)[]).some((key) => draft[key] !== saved[key])
}
