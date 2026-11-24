import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'

export type ResetPreview = Schemas['ResetPreviewOut']

const ACCOUNT_KEY = ['account'] as const

/** Asks for a reset link by email; the answer is the same whether or not the account exists. */
export function useRequestPasswordReset() {
  return useMutation({
    mutationFn: (login: string) => unwrap(api.POST('/api/v1/password-reset:request', {body: {login}})),
  })
}

/** Whose password a reset link sets, and the passkeys it keeps. It changes nothing. */
export function usePasswordResetPreview(token: string) {
  return useQuery({
    queryKey: ['password-reset', token],
    queryFn: () => unwrap(api.POST('/api/v1/password-reset:preview', {body: {token}})),
    staleTime: Infinity,
  })
}

export function useResetPassword(token: string) {
  return useMutation({
    mutationFn: (newPassword: string) =>
      unwrap(api.POST('/api/v1/password-reset', {body: {token, new_password: newPassword}})),
  })
}

/** Makes the address a confirmation link went to the account's email. */
export function useConfirmEmail(token: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/email-verifications:confirm', {body: {token}})),
    onSuccess: () => queryClient.invalidateQueries({queryKey: ACCOUNT_KEY}),
  })
}

/** Mails a confirmation link to the address; it becomes the account's email once opened. */
export function useRequestEmailChange() {
  return useMutation({
    mutationFn: (email: string) => unwrap(api.POST('/api/v1/me/email', {body: {email}})),
  })
}

export function useRemoveEmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/me/email')),
    onSuccess: (account) => queryClient.setQueryData(ACCOUNT_KEY, account),
  })
}
