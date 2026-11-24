import {QueryClientProvider} from '@tanstack/react-query'
import {render} from '@testing-library/react'
import type {ReactNode} from 'react'
import {MemoryRouter, Routes} from 'react-router'

import {forgetAccount} from '@/entities/account'
import {createQueryClient} from '@/shared/api'

/** Renders routes at `url` with a fresh query cache, set up as the app's but without retries. */
export function renderAt(url: string, routes: ReactNode) {
  const queryClient = createQueryClient({onUnauthenticated: forgetAccount})
  queryClient.setDefaultOptions({
    queries: {...queryClient.getDefaultOptions().queries, retry: false},
    mutations: {retry: false},
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>{routes}</Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
