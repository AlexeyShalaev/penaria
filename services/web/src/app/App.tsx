import {QueryClientProvider} from '@tanstack/react-query'
import {useState} from 'react'
import {BrowserRouter, Route, Routes} from 'react-router'

import {AccountPage} from '@/pages/account'
import {EntityPage} from '@/pages/entity'
import {NewHomePage} from '@/pages/new-home'
import {NotFoundPage} from '@/pages/not-found'
import {PlacesPage} from '@/pages/places'
import {SetupPage} from '@/pages/setup'
import {SignInPage} from '@/pages/sign-in'
import {StartPage} from '@/pages/start'
import {AppShell} from '@/widgets/app-shell'
import {forgetAccount} from '@/entities/account'
import {createQueryClient} from '@/shared/api'

import {RequireAccount} from './RequireAccount'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="setup" element={<SetupPage />} />
      <Route path="sign-in" element={<SignInPage />} />
      <Route element={<RequireAccount />}>
        <Route index element={<StartPage />} />
        <Route path="homes/new" element={<NewHomePage />} />
        <Route element={<AppShell section="places" />}>
          <Route path="homes/:homeId/places" element={<PlacesPage />} />
          <Route path="entities/:entityId" element={<EntityPage />} />
        </Route>
        <Route element={<AppShell section="account" />}>
          <Route path="account" element={<AccountPage />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}

export function App() {
  const [queryClient] = useState(() => createQueryClient({onUnauthenticated: forgetAccount}))
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
