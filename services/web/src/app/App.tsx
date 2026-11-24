import {QueryClientProvider} from '@tanstack/react-query'
import {useState} from 'react'
import {BrowserRouter, Route, Routes} from 'react-router'

import {EntityPage} from '@/pages/entity'
import {NewHomePage} from '@/pages/new-home'
import {NotFoundPage} from '@/pages/not-found'
import {PlacesPage} from '@/pages/places'
import {StartPage} from '@/pages/start'
import {AppShell} from '@/widgets/app-shell'
import {createQueryClient} from '@/shared/api'

export function AppRoutes() {
  return (
    <Routes>
      <Route index element={<StartPage />} />
      <Route path="homes/new" element={<NewHomePage />} />
      <Route element={<AppShell />}>
        <Route path="homes/:homeId/places" element={<PlacesPage />} />
        <Route path="entities/:entityId" element={<EntityPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}

export function App() {
  const [queryClient] = useState(createQueryClient)
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
