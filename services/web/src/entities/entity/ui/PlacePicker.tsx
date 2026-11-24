import {Check, Home} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {IconTile} from '@/shared/ui'

import type {EntitySummary} from '../api/entities'
import {EntityTree} from './EntityTree'
import styles from './PlacePicker.module.css'

type Props = {
  homeId: string
  /** The picked place's id; null is the top of the home. */
  value: string | null
  onChange: (place: EntitySummary | null) => void
  canPick: (place: EntitySummary) => boolean
  /** Offer the top of the home as a place too. */
  allowTop?: boolean
  hiddenId?: string
  /** Places expanded at the start, such as the way to where the entity is now. */
  initiallyExpanded?: string[]
}

/** The home tree as a list to pick a place from. */
export function PlacePicker(props: Props) {
  const {t} = useTranslation()
  const [expanded, setExpanded] = useState(() => new Set(props.initiallyExpanded))
  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (!next.delete(id)) next.add(id)
      return next
    })
  return (
    <div className={styles.picker}>
      {props.allowTop && (
        <button
          type="button"
          className={styles.top}
          aria-pressed={props.value === null}
          onClick={() => props.onChange(null)}
        >
          <IconTile icon={Home} size="sm" />
          <span className={styles.grow}>{t('picker.top')}</span>
          {props.value === null && <Check className={styles.check} aria-hidden />}
        </button>
      )}
      <EntityTree
        homeId={props.homeId}
        expanded={expanded}
        onToggle={toggle}
        hiddenId={props.hiddenId}
        select={{selectedId: props.value, canSelect: props.canPick, onSelect: props.onChange}}
        empty={<p className={styles.empty}>{t('picker.empty')}</p>}
      />
    </div>
  )
}
