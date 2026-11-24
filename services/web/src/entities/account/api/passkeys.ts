import {type QueryClient, useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'
import {createCredential, getCredential} from '@/shared/lib/webauthn'

import {type SecondFactorCode, useStartSession} from './account'
import {SECOND_FACTOR_KEY} from './secondFactor'

export type Passkey = Schemas['PasskeyOut']

const passkeysKey = ['passkeys'] as const

export function usePasskeys(options: {enabled?: boolean} = {}) {
  return useQuery({
    queryKey: passkeysKey,
    queryFn: () => unwrap(api.GET('/api/v1/me/passkeys')),
    enabled: options.enabled,
  })
}

/** Signs in with any passkey of this site the person picks; no username needed. */
export function useSignInWithPasskey() {
  const start = useStartSession()
  return useMutation({
    mutationFn: async () => {
      const ceremony = await unwrap(api.POST('/api/v1/sign-in/passkey/options'))
      const credential = await getCredential(ceremony.options)
      return unwrap(api.POST('/api/v1/sign-in/passkey', {body: {challenge_id: ceremony.challenge_id, credential}}))
    },
    onSuccess: start,
  })
}

/** Makes a passkey on this device and adds it to the account under `name`; needs a recent sign-in. */
export function useAddPasskey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      const ceremony = await unwrap(api.POST('/api/v1/me/passkeys/options'))
      const credential = await createCredential(ceremony.options)
      return unwrap(api.POST('/api/v1/me/passkeys', {body: {challenge_id: ceremony.challenge_id, credential, name}}))
    },
    // A passkey is a second factor too.
    onSuccess: () => invalidatePasskeys(queryClient),
  })
}

export function useRenamePasskey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: {id: string; name: string}) =>
      unwrap(
        api.PATCH('/api/v1/me/passkeys/{passkey_id}', {
          params: {path: {passkey_id: variables.id}},
          body: {name: variables.name},
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({queryKey: passkeysKey}),
  })
}

/** Removes a passkey from the account; needs a recent sign-in. */
export function useRemovePasskey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (passkeyId: string) =>
      unwrap(api.DELETE('/api/v1/me/passkeys/{passkey_id}', {params: {path: {passkey_id: passkeyId}}})),
    onSettled: () => invalidatePasskeys(queryClient),
  })
}

/**
 * Confirms it is still the person, so the session counts as signed in recently: the password, and a code
 * while the account has an authenticator app.
 */
export function useReauthenticate() {
  return useMutation({
    mutationFn: (body: {password: string} & Partial<SecondFactorCode>) =>
      unwrap(api.POST('/api/v1/me/reauthenticate', {body})),
  })
}

export function useReauthenticateWithPasskey() {
  return useMutation({
    mutationFn: async () => {
      const ceremony = await unwrap(api.POST('/api/v1/me/reauthenticate/passkey/options'))
      const credential = await getCredential(ceremony.options)
      return unwrap(
        api.POST('/api/v1/me/reauthenticate/passkey', {body: {challenge_id: ceremony.challenge_id, credential}}),
      )
    },
  })
}

function invalidatePasskeys(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({queryKey: passkeysKey}),
    queryClient.invalidateQueries({queryKey: SECOND_FACTOR_KEY}),
  ])
}
