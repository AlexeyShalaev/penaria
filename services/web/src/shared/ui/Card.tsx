import type {HTMLAttributes} from 'react'

import styles from './Card.module.css'

type Props = HTMLAttributes<HTMLElement> & {padded?: boolean; as?: 'div' | 'section'}

export function Card({padded = true, as: Tag = 'div', className, ...rest}: Props) {
  return <Tag className={[styles.card, padded && styles.padded, className].filter(Boolean).join(' ')} {...rest} />
}
