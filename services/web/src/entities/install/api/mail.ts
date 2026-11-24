import {useInfiniteQuery, useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'

export type Mailbox = Schemas['MailboxOut']
export type MailboxInput = Schemas['MailboxIn']
export type MailSecurity = Schemas['MailSecurity']
export type SendResult = Schemas['SendResultOut']
export type MailboxStatus = Schemas['MailboxStatusOut']
export type LoggedMail = Schemas['MailOut']

const LOG_PAGE = 20

const mailKeys = {
  all: ['mail'] as const,
  enabled: ['mail', 'enabled'] as const,
  mailbox: ['mail', 'mailbox'] as const,
  status: ['mail', 'status'] as const,
  log: ['mail', 'log'] as const,
}

/** Whether the install sends email: without it, links are passed on by hand. Anyone may ask. */
export function useMailEnabled() {
  return useQuery({
    queryKey: mailKeys.enabled,
    queryFn: async () => (await unwrap(api.GET('/api/v1/mail'))).enabled,
  })
}

export function useMailbox() {
  return useQuery({queryKey: mailKeys.mailbox, queryFn: () => unwrap(api.GET('/api/v1/install/mail'))})
}

/** Connects to the mailbox and signs in, so it answers slowly when the server does not. */
export function useMailboxStatus(enabled: boolean) {
  return useQuery({
    queryKey: mailKeys.status,
    queryFn: () => unwrap(api.GET('/api/v1/install/mail/status')),
    enabled,
    staleTime: 60_000,
  })
}

/** After the mailbox changes, everything about mail is read again. */
function useMailMutation<T, R>(change: (input: T) => Promise<R>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: change,
    onSettled: () => queryClient.invalidateQueries({queryKey: mailKeys.all}),
  })
}

export function useSaveMailbox() {
  return useMailMutation((body: MailboxInput) => unwrap(api.PUT('/api/v1/install/mail', {body})))
}

export function useRemoveMailbox() {
  return useMailMutation(() => unwrap(api.DELETE('/api/v1/install/mail')))
}

export function useSendTestMail() {
  return useMailMutation((to: string | null) => unwrap(api.POST('/api/v1/install/mail:test', {body: {to}})))
}

export function useResendMail() {
  return useMailMutation((mailId: string) =>
    unwrap(api.POST('/api/v1/install/mail/messages/{mail_id}:resend', {params: {path: {mail_id: mailId}}})),
  )
}

/** The mail log, the newest first, a page at a time. */
export function useMailLog() {
  return useInfiniteQuery({
    queryKey: mailKeys.log,
    initialPageParam: null as string | null,
    queryFn: ({pageParam}) =>
      unwrap(
        api.GET('/api/v1/install/mail/messages', {
          params: {query: {limit: LOG_PAGE, ...(pageParam ? {before: pageParam} : {})}},
        }),
      ),
    getNextPageParam: (page) => (page.length === LOG_PAGE ? (page.at(-1)?.id ?? null) : null),
  })
}
