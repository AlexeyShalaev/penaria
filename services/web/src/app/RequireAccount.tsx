import {useEffect} from 'react'
import {useTranslation} from 'react-i18next'
import {Navigate, Outlet, useLocation} from 'react-router'

import {SecondFactorPrompt} from '@/widgets/second-factor-prompt'
import {useAccount} from '@/entities/account'
import {QueryState} from '@/shared/ui'

/**
 * The pages behind it need a session: without one, the sign-in page, which returns here afterwards. An owner or an
 * admin without a second factor is asked to add one over them.
 */
export function RequireAccount() {
  const {i18n} = useTranslation()
  const location = useLocation()
  const account = useAccount()
  const locale = account.data?.locale

  // The interface speaks the account's language once it is known.
  useEffect(() => {
    if (locale && locale !== i18n.language) void i18n.changeLanguage(locale)
  }, [locale, i18n])

  return (
    <QueryState query={account}>
      {(data) => {
        if (data)
          return (
            <>
              <Outlet />
              <SecondFactorPrompt />
            </>
          )
        const next = `${location.pathname}${location.search}`
        return <Navigate to={next === '/' ? '/sign-in' : `/sign-in?next=${encodeURIComponent(next)}`} replace />
      }}
    </QueryState>
  )
}
