import {Map as MapIcon} from 'lucide-react'
import {useEffect} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, Outlet, useParams} from 'react-router'

import {useEntity} from '@/entities/entity'
import {rememberLastHome} from '@/shared/lib/lastHome'

import styles from './AppShell.module.css'
import {HomeSwitcher} from './HomeSwitcher'

/** The frame of every page inside a home: a sidebar on wide screens, a top bar and tab bar on phones. */
export function AppShell() {
  const {t} = useTranslation()
  const params = useParams<{homeId?: string; entityId?: string}>()
  const entity = useEntity(params.entityId)
  const homeId = params.homeId ?? entity.data?.home_id

  useEffect(() => {
    if (homeId) rememberLastHome(homeId)
  }, [homeId])

  // So far every page inside a home belongs to "Places and things", so its link is always current.
  const placesLink = homeId ? `/homes/${homeId}/places` : undefined

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <HomeSwitcher homeId={homeId} />
        <nav className={styles.nav} aria-label={t('shell.navigation')}>
          {placesLink && (
            <Link to={placesLink} className={styles.navItem} aria-current="page">
              <MapIcon aria-hidden />
              {t('shell.places')}
            </Link>
          )}
        </nav>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <HomeSwitcher homeId={homeId} />
        </header>
        <main className={styles.page}>
          <Outlet />
        </main>
      </div>

      <nav className={styles.tabbar} aria-label={t('shell.navigation')}>
        {placesLink && (
          <Link to={placesLink} className={styles.tab} aria-current="page">
            <MapIcon aria-hidden />
            {t('shell.placesShort')}
          </Link>
        )}
      </nav>
    </div>
  )
}
