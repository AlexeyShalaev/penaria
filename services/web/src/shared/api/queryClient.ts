import {QueryClient} from '@tanstack/react-query'

import {ApiError} from './errors'

const MAX_RETRIES = 2

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 4xx answer does not change on retry; a network failure or a 5xx may.
        retry: (failures, error) => failures < MAX_RETRIES && !(error instanceof ApiError && error.status < 500),
        staleTime: 10_000,
      },
    },
  })
}
