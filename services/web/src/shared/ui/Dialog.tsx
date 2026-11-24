import {X} from 'lucide-react'
import {type ReactNode, useEffect, useId, useRef} from 'react'

import {IconButton} from './Button'
import styles from './Dialog.module.css'

type Props = {
  title: string
  closeLabel: string
  onClose: () => void
  children: ReactNode
}

/** A modal: a centred card on wide screens, a bottom sheet on phones. Escape and the backdrop close it. */
export function Dialog({title, closeLabel, onClose, children}: Props) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    panel.current?.querySelector<HTMLElement>('input, select, textarea, button:not([data-close])')?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus()
    }
  }, [onClose])

  return (
    <div className={styles.backdrop} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={panel} className={styles.panel} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          <IconButton icon={X} label={closeLabel} onClick={onClose} data-close />
        </header>
        {children}
      </div>
    </div>
  )
}
