import {Home, MapPin} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {PlacePicker} from '@/entities/entity'
import {Chip} from '@/shared/ui'

import styles from './ScopeField.module.css'

/** Where access applies: the whole home, or one place with everything inside it. */
export function ScopeField(props: {
  homeId: string
  value: string | null
  onChange: (placeId: string | null) => void
  whole: boolean
  onWholeChange: (whole: boolean) => void
}) {
  const {t} = useTranslation()
  return (
    <fieldset className={styles.field}>
      <legend className={styles.legend}>{t('people.scope')}</legend>
      <div className={styles.choices} role="radiogroup" aria-label={t('people.scope')}>
        <Chip role="radio" aria-checked={props.whole} icon={Home} onClick={() => props.onWholeChange(true)}>
          {t('people.wholeHome')}
        </Chip>
        <Chip role="radio" aria-checked={!props.whole} icon={MapPin} onClick={() => props.onWholeChange(false)}>
          {t('people.onePlace')}
        </Chip>
      </div>
      {!props.whole && (
        <>
          <p className={styles.hint}>{t('people.onePlaceHint')}</p>
          <PlacePicker
            homeId={props.homeId}
            value={props.value}
            onChange={(place) => props.onChange(place?.id ?? null)}
            canPick={() => true}
          />
        </>
      )}
    </fieldset>
  )
}
