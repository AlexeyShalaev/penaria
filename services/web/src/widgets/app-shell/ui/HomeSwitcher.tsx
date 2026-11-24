import {Check, ChevronsUpDown, MapPinHouse, Plus} from 'lucide-react'
import {useEffect, useRef, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link} from 'react-router'

import {useHome, useHomes} from '@/entities/home'
import {IconTile} from '@/shared/ui'

import styles from './HomeSwitcher.module.css'

export function HomeSwitcher(props: {homeId: string | undefined}) {
  const {t} = useTranslation()
  const home = useHome(props.homeId)
  const homes = useHomes()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !root.current?.contains(event.target as Node))
        setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  const access = home.data?.access
  return (
    <div className={styles.root} ref={root}>
      <button
        type="button"
        className={styles.current}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={t('shell.switchHome')}
        onClick={() => setOpen((value) => !value)}
      >
        <IconTile icon={MapPinHouse} size="sm" accent />
        <span className={styles.text}>
          <span className={styles.name}>{home.data?.name ?? '…'}</span>
          {access && <span className={styles.role}>{t(access.owner ? 'shell.owner' : 'shell.member')}</span>}
        </span>
        <ChevronsUpDown aria-hidden className={styles.icon} />
      </button>
      {open && (
        <div className={styles.menu}>
          <p className={styles.menuLabel}>{t('shell.homes')}</p>
          <ul className={styles.list}>
            {homes.data?.map((item) => (
              <li key={item.id}>
                <Link
                  className={styles.item}
                  to={`/homes/${item.id}/places`}
                  aria-current={item.id === props.homeId ? 'page' : undefined}
                  onClick={() => setOpen(false)}
                >
                  <span className={styles.grow}>{item.name}</span>
                  {item.id === props.homeId && <Check aria-hidden className={styles.icon} />}
                </Link>
              </li>
            ))}
            <li>
              <Link className={styles.item} to="/homes/new" onClick={() => setOpen(false)}>
                <Plus aria-hidden className={styles.icon} />
                <span className={styles.grow}>{t('shell.addHome')}</span>
              </Link>
            </li>
          </ul>
        </div>
      )}
    </div>
  )
}
