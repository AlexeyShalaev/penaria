import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'

import type {SecondFactorCode} from './account'

export type ExternalIdentity = Schemas['ExternalIdentityOut']

const configKey = ['auth-config'] as const
const methodsKey = ['sign-in-methods'] as const

/** The operator's sign-in provider, if the install has one: `{name}` for its button. */
export function useAuthConfig() {
  return useQuery({
    queryKey: configKey,
    queryFn: () => unwrap(api.GET('/api/v1/auth/config')),
    staleTime: Infinity,
  })
}

/** Whether the account has a password, and its identities at the provider. */
export function useSignInMethods() {
  return useQuery({queryKey: methodsKey, queryFn: () => unwrap(api.GET('/api/v1/me/sign-in-methods'))})
}

/** Leaves for the provider's sign-in page; the provider sends the browser back to the install. */
function leaveFor(started: {url: string}) {
  window.location.assign(started.url)
}

export function useStartProviderSignIn() {
  return useMutation({
    mutationFn: (body: {locale: string; return_to: string}) => unwrap(api.POST('/api/v1/auth/oidc:sign-in', {body})),
    onSuccess: leaveFor,
  })
}

/** Accepts an invitation with an identity at the provider, making an account from it when there is none. */
export function useStartProviderInvitation() {
  return useMutation({
    mutationFn: (body: {token: string; locale: string}) =>
      unwrap(api.POST('/api/v1/auth/oidc:accept-invitation', {body})),
    onSuccess: leaveFor,
  })
}

export function useStartProviderLink() {
  return useMutation({
    mutationFn: (body: {return_to: string}) => unwrap(api.POST('/api/v1/me/external-identities:link', {body})),
    onSuccess: leaveFor,
  })
}

/** Confirms it is you by signing in at the provider again; with a code too while the authenticator app is on. */
export function useReauthenticateWithProvider() {
  return useMutation({
    mutationFn: (body: {return_to: string} & Partial<SecondFactorCode>) =>
      unwrap(api.POST('/api/v1/me/reauthenticate/oidc', {body})),
    onSuccess: leaveFor,
  })
}

export function useUnlinkIdentity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (identityId: string) =>
      unwrap(api.DELETE('/api/v1/me/external-identities/{identity_id}', {params: {path: {identity_id: identityId}}})),
    onSettled: () => queryClient.invalidateQueries({queryKey: methodsKey}),
  })
}
