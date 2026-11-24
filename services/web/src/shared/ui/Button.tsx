import type {LucideIcon} from 'lucide-react'
import type {ButtonHTMLAttributes} from 'react'

import styles from './Button.module.css'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'md' | 'sm'
  icon?: LucideIcon
}

export function Button({variant = 'primary', size = 'md', icon: Icon, className, children, ...rest}: Props) {
  const classes = [styles.button, styles[variant], size === 'sm' && styles.small, className].filter(Boolean).join(' ')
  return (
    <button type="button" className={classes} {...rest}>
      {Icon && <Icon aria-hidden />}
      {children}
    </button>
  )
}

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {icon: LucideIcon; label: string}

export function IconButton({icon: Icon, label, className, ...rest}: IconButtonProps) {
  return (
    <button
      type="button"
      className={[styles.iconButton, className].filter(Boolean).join(' ')}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon aria-hidden />
    </button>
  )
}
