import type {LucideIcon} from 'lucide-react'

import styles from './IconTile.module.css'

export function IconTile(props: {icon: LucideIcon; size?: 'sm' | 'md' | 'lg'; accent?: boolean}) {
  const {icon: Icon, size = 'md', accent} = props
  return (
    <span className={[styles.tile, styles[size], accent && styles.accent].filter(Boolean).join(' ')} aria-hidden>
      <Icon />
    </span>
  )
}
