import {ChevronRight} from 'lucide-react'
import {Link} from 'react-router'

import styles from './Breadcrumbs.module.css'

export function Breadcrumbs(props: {label: string; items: {label: string; to: string}[]}) {
  return (
    <nav aria-label={props.label}>
      <ol className={styles.crumbs}>
        {props.items.map((item, index) => (
          <li key={item.to}>
            {index > 0 && <ChevronRight aria-hidden className={styles.separator} />}
            <Link to={item.to}>{item.label}</Link>
          </li>
        ))}
      </ol>
    </nav>
  )
}
