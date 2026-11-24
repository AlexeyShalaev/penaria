import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
import {render} from '@testing-library/react'
import type {ReactNode} from 'react'
import {MemoryRouter, Routes} from 'react-router'

/** Renders routes at `url` with a fresh query cache that does not retry. */
export function renderAt(url: string, routes: ReactNode) {
  const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>{routes}</Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
