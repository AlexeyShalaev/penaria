import {CircleUserRound, Map as MapIcon, Settings, Users} from 'lucide-react'
import {useEffect} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, Outlet, useParams} from 'react-router'

import {useAccount} from '@/entities/account'
import {useEntity} from '@/entities/entity'
import {readLastHome, rememberLastHome} from '@/shared/lib/lastHome'

import styles from './AppShell.module.css'
import {HomeSwitcher} from './HomeSwitcher'
import {PasskeySuggestion} from './PasskeySuggestion'

/**
 * The frame of the app's pages: a sidebar on wide screens, a top bar and tab bar on phones. A page
 * of one home shows that home in the switcher; the account and the install's settings, which belong to no home,
 * the home used last.
 */
type AppShellProps = {section: 'places' | 'people' | 'account' | 'settings'}

export function AppShell(props: AppShellProps) {
  const {t} = useTranslation()
  const params = useParams<{homeId?: string; entityId?: string}>()
  const entity = useEntity(params.entityId)
  const account = useAccount()
  const onAccountPage = props.section === 'account'
  const homeless = onAccountPage || props.section === 'settings'
  const pageHomeId = params.homeId ?? entity.data?.home_id
  const homeId = pageHomeId ?? (homeless ? (readLastHome() ?? undefined) : undefined)
  const installAdmin = !!account.data?.install_admin

  useEffect(() => {
    if (pageHomeId) rememberLastHome(pageHomeId)
  }, [pageHomeId])

  const placesLink = homeId ? `/homes/${homeId}/places` : undefined
  const peopleLink = homeId ? `/homes/${homeId}/people` : undefined
  const current = (section: AppShellProps['section']) => (props.section === section ? 'page' : undefined)

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <HomeSwitcher homeId={homeId} />
        <nav className={styles.nav} aria-label={t('shell.navigation')}>
          {placesLink && (
            <Link to={placesLink} className={styles.navItem} aria-current={current('places')}>
              <MapIcon aria-hidden />
              {t('shell.places')}
            </Link>
          )}
          {peopleLink && (
            <Link to={peopleLink} className={styles.navItem} aria-current={current('people')}>
              <Users aria-hidden />
              {t('shell.people')}
            </Link>
          )}
          {installAdmin && (
            <Link to="/settings" className={styles.navItem} aria-current={current('settings')}>
              <Settings aria-hidden />
              {t('shell.settings')}
            </Link>
          )}
        </nav>
        <Link to="/account" className={styles.account} aria-current={current('account')}>
          <CircleUserRound aria-hidden />
          <span className={styles.accountText}>
            <span className={styles.accountName}>{account.data?.display_name}</span>
            <span className={styles.accountHint}>{t('shell.account')}</span>
          </span>
        </Link>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <HomeSwitcher homeId={homeId} />
        </header>
        <main className={styles.page}>
          {/* The account page has its own place for passkeys. */}
          {account.data && !onAccountPage && <PasskeySuggestion accountId={account.data.id} />}
          <Outlet />
        </main>
      </div>

      <nav className={styles.tabbar} aria-label={t('shell.navigation')}>
        {placesLink && (
          <Link to={placesLink} className={styles.tab} aria-current={current('places')}>
            <MapIcon aria-hidden />
            {t('shell.placesShort')}
          </Link>
        )}
        {peopleLink && (
          <Link to={peopleLink} className={styles.tab} aria-current={current('people')}>
            <Users aria-hidden />
            {t('shell.peopleShort')}
          </Link>
        )}
        {installAdmin && (
          <Link to="/settings" className={styles.tab} aria-current={current('settings')}>
            <Settings aria-hidden />
            {t('shell.settingsShort')}
          </Link>
        )}
        <Link to="/account" className={styles.tab} aria-current={current('account')}>
          <CircleUserRound aria-hidden />
          {t('shell.accountShort')}
        </Link>
      </nav>
    </div>
  )
}
