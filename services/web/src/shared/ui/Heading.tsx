import type {ReactNode} from 'react'

import styles from './Heading.module.css'

/** The heading of a page. */
export function PageTitle(props: {children: ReactNode; className?: string}) {
  return <h1 className={[styles.page, props.className].filter(Boolean).join(' ')}>{props.children}</h1>
}

/** The heading of a card. */
export function CardTitle(props: {children: ReactNode}) {
  return <h2 className={styles.card}>{props.children}</h2>
}
