import type {LucideIcon} from 'lucide-react'
import type {ButtonHTMLAttributes} from 'react'

import styles from './Chip.module.css'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {icon?: LucideIcon; pressed?: boolean}

/** A pill that toggles (`pressed`) or picks one of several (`role="radio"` with `aria-checked`). */
export function Chip({icon: Icon, pressed, className, children, ...rest}: Props) {
  return (
    <button
      type="button"
      className={[styles.chip, className].filter(Boolean).join(' ')}
      aria-pressed={rest.role === 'radio' ? undefined : (pressed ?? false)}
      {...rest}
    >
      {Icon && <Icon aria-hidden />}
      {children}
    </button>
  )
}
