import {useTranslation} from 'react-i18next'

import {Button, Field, TextInput} from '@/shared/ui'

import styles from './SecondFactorField.module.css'

// A code with whatever spaces and dashes people type; the server's bound.
const CODE_MAX_LENGTH = 64

/** A code from the authenticator app, or one of the recovery codes when `recovery` is on; `onToggle` switches. */
export function SecondFactorField(props: {
  value: string
  onChange: (value: string) => void
  recovery: boolean
  onToggle: () => void
}) {
  const {t} = useTranslation()
  return (
    <div className={styles.root}>
      <Field label={t(props.recovery ? 'twoStep.recoveryCode' : 'twoStep.code')}>
        <TextInput
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
          inputMode={props.recovery ? 'text' : 'numeric'}
          autoComplete={props.recovery ? 'off' : 'one-time-code'}
          autoCapitalize="none"
          spellCheck={false}
          maxLength={CODE_MAX_LENGTH}
          required
        />
      </Field>
      <Button variant="ghost" size="sm" className={styles.toggle} onClick={props.onToggle}>
        {t(props.recovery ? 'twoStep.useApp' : 'twoStep.useRecovery')}
      </Button>
    </div>
  )
}
