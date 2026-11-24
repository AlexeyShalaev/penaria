import {MutationCache, QueryCache, QueryClient} from '@tanstack/react-query'

import {ApiError, isApiError} from './errors'

const MAX_RETRIES = 2

/** The signed-in account's query; `null` once the server says there is no session. */
export const ACCOUNT_KEY = ['account'] as const

export function createQueryClient() {
  // Any call that finds the session gone signs the app out, and the guard sends the person to sign in.
  const signOutOnUnauthenticated = (error: Error) => {
    if (isApiError(error, 'unauthenticated')) client.setQueryData(ACCOUNT_KEY, null)
  }
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({onError: signOutOnUnauthenticated}),
    mutationCache: new MutationCache({onError: signOutOnUnauthenticated}),
    defaultOptions: {
      queries: {
        // A 4xx answer does not change on retry; a network failure or a 5xx may.
        retry: (failures, error) => failures < MAX_RETRIES && !(error instanceof ApiError && error.status < 500),
        staleTime: 10_000,
      },
    },
  })
  return client
}
