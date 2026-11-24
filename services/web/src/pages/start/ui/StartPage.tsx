import {Navigate} from 'react-router'

import {useHomes} from '@/entities/home'
import {readLastHome} from '@/shared/lib/lastHome'
import {QueryState} from '@/shared/ui'

import styles from './StartPage.module.css'

/** Opens the home used last, or the first one; with no home yet, the welcome page. */
export function StartPage() {
  const homes = useHomes()
  return (
    <div className={styles.page}>
      <QueryState query={homes}>
        {(list) => {
          const last = readLastHome()
          const home = list.find((item) => item.id === last) ?? list[0]
          return <Navigate to={home ? `/homes/${home.id}/places` : '/homes/new'} replace />
        }}
      </QueryState>
    </div>
  )
}
