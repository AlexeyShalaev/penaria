import {CircleAlert, LoaderCircle, type LucideIcon} from 'lucide-react'
import type {ReactNode} from 'react'

import {Button} from './Button'
import {IconTile} from './IconTile'
import styles from './State.module.css'

export function Loading(props: {label: string}) {
  return (
    <div className={styles.loading} role="status">
      <LoaderCircle aria-hidden className={styles.spinner} />
      {props.label}
    </div>
  )
}

export function Empty(props: {icon: LucideIcon; title: string; text?: string; action?: ReactNode}) {
  return (
    <div className={styles.empty}>
      <IconTile icon={props.icon} accent />
      <p className={styles.title}>{props.title}</p>
      {props.text && <p className={styles.text}>{props.text}</p>}
      {props.action}
    </div>
  )
}

export function ErrorState(props: {message: string; retryLabel?: string; onRetry?: () => void}) {
  return (
    <div className={styles.error} role="alert">
      <CircleAlert aria-hidden />
      <span className={styles.grow}>{props.message}</span>
      {props.onRetry && props.retryLabel && (
        <Button size="sm" variant="secondary" onClick={props.onRetry}>
          {props.retryLabel}
        </Button>
      )}
    </div>
  )
}
