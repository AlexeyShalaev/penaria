import {MutationCache, QueryCache, QueryClient} from '@tanstack/react-query'

import {ApiError, isApiError} from './errors'

const MAX_RETRIES = 2

/** The app's query client; `onUnauthenticated` runs whenever a call finds the session gone. */
export function createQueryClient(options: {onUnauthenticated: (client: QueryClient) => void}) {
  const signOut = (error: Error) => {
    if (isApiError(error, 'unauthenticated')) options.onUnauthenticated(client)
  }
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({onError: signOut}),
    mutationCache: new MutationCache({onError: signOut}),
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
