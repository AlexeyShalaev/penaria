import {type QueryClient, useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, isApiError, type Schemas, unwrap} from '@/shared/api'

export type Account = Schemas['AccountOut']
export type AccountSession = Schemas['SessionOut']

export const ACCOUNT_KEY = ['account'] as const
const setupKey = ['setup'] as const
const sessionsKey = ['sessions'] as const

/** Shows the app signed out, as when the server answers that the session is gone. */
export function forgetAccount(queryClient: QueryClient) {
  startSession(queryClient, null)
}

// After signing in or out, nothing cached under the previous session may show.
function startSession(queryClient: QueryClient, account: Account | null) {
  queryClient.removeQueries({
    predicate: (query) => !(query.queryKey.length === 1 && query.queryKey[0] === ACCOUNT_KEY[0]),
  })
  queryClient.setQueryData(ACCOUNT_KEY, account)
}

/** The signed-in account, or `null` without a session. */
export function useAccount() {
  return useQuery({
    queryKey: ACCOUNT_KEY,
    queryFn: async (): Promise<Account | null> => {
      try {
        return await unwrap(api.GET('/api/v1/me'))
      } catch (error) {
        if (isApiError(error, 'unauthenticated')) return null
        throw error
      }
    },
    staleTime: Infinity,
  })
}

/** Whether the install has no account yet, so the setup screen comes first. */
export function useSetupStatus() {
  return useQuery({queryKey: setupKey, queryFn: () => unwrap(api.GET('/api/v1/setup'))})
}

export function useStartSession() {
  const queryClient = useQueryClient()
  return (account: Account | null) => startSession(queryClient, account)
}

export function useCompleteSetup() {
  const start = useStartSession()
  return useMutation({
    mutationFn: (body: Schemas['SetupIn']) => unwrap(api.POST('/api/v1/setup', {body})),
    onSuccess: start,
  })
}

export function useSignIn() {
  const start = useStartSession()
  return useMutation({
    mutationFn: (body: Schemas['SignInIn']) => unwrap(api.POST('/api/v1/sign-in', {body})),
    onSuccess: start,
  })
}

export function useSignOut() {
  const start = useStartSession()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/sign-out')),
    onSuccess: () => start(null),
  })
}

export function useUpdateAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['AccountPatch']) => unwrap(api.PATCH('/api/v1/me', {body})),
    onSuccess: (account) => queryClient.setQueryData(ACCOUNT_KEY, account),
  })
}

export function useChangePassword() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['PasswordChangeIn']) => unwrap(api.POST('/api/v1/me/password', {body})),
    // A new password ends the other sessions.
    onSuccess: () => queryClient.invalidateQueries({queryKey: sessionsKey}),
  })
}

export function useSessions() {
  return useQuery({queryKey: sessionsKey, queryFn: () => unwrap(api.GET('/api/v1/me/sessions'))})
}

export function useRevokeSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) =>
      unwrap(api.DELETE('/api/v1/me/sessions/{session_id}', {params: {path: {session_id: sessionId}}})),
    onSettled: () => queryClient.invalidateQueries({queryKey: sessionsKey}),
  })
}

export function useRevokeOtherSessions() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/me/sessions:revoke-others')),
    onSettled: () => queryClient.invalidateQueries({queryKey: sessionsKey}),
  })
}
