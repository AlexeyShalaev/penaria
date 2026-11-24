import type {LucideIcon} from 'lucide-react'
import type {ReactNode} from 'react'

import styles from './Badge.module.css'

export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'ai'

export function Badge(props: {children: ReactNode; tone?: Tone; icon?: LucideIcon; dot?: boolean; title?: string}) {
  const {children, tone = 'neutral', icon: Icon, dot, title} = props
  const classes = [styles.badge, styles[tone], dot && styles.dot].filter(Boolean).join(' ')
  return (
    <span className={classes} title={title}>
      {Icon && <Icon aria-hidden />}
      {children}
    </span>
  )
}
