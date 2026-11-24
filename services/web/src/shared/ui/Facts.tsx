import type {ReactNode} from 'react'

import styles from './Facts.module.css'

/** Label and value pairs, such as the details of a home. */
export function Facts(props: {items: {label: string; value: ReactNode}[]}) {
  return (
    <dl className={styles.facts}>
      {props.items.map((item) => (
        <div key={item.label} className={styles.row}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
