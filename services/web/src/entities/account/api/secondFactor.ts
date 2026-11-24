import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'

export type SecondFactor = Schemas['SecondFactorOut']
export type TotpEnrolment = Schemas['TotpEnrolmentOut']

export const SECOND_FACTOR_KEY = ['second-factor'] as const

/** Whether the account has an authenticator app, and whether it must add a second factor before owner-level work. */
export function useSecondFactor(options: {enabled?: boolean} = {}) {
  return useQuery({
    queryKey: SECOND_FACTOR_KEY,
    queryFn: () => unwrap(api.GET('/api/v1/me/second-factor')),
    enabled: options.enabled,
  })
}

/** A new secret for the authenticator app; the app is on once a code confirms it. Needs a recent sign-in. */
export function useStartTotp() {
  return useMutation({mutationFn: () => unwrap(api.POST('/api/v1/me/totp'))})
}

/** Turns the authenticator app on with its first code; the answer holds the recovery codes, shown only now. */
export function useConfirmTotp() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (code: string) => unwrap(api.POST('/api/v1/me/totp:confirm', {body: {code}})),
    onSuccess: () => queryClient.invalidateQueries({queryKey: SECOND_FACTOR_KEY}),
  })
}

/** Ten new recovery codes; the earlier ones stop working. Needs a recent sign-in. */
export function useRegenerateRecoveryCodes() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/me/totp/recovery-codes')),
    onSuccess: () => queryClient.invalidateQueries({queryKey: SECOND_FACTOR_KEY}),
  })
}

/** Turns the authenticator app off. Needs a recent sign-in; an owner or an admin needs a passkey first. */
export function useTurnOffTotp() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/me/totp')),
    onSettled: () => queryClient.invalidateQueries({queryKey: SECOND_FACTOR_KEY}),
  })
}
