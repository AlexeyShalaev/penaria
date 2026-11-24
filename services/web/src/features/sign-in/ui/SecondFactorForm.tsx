import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {
  type Account,
  type SecondFactorChallenge,
  secondFactorCode,
  SecondFactorField,
  useSignInWithCode,
} from '@/entities/account'
import {describeError, isApiError} from '@/shared/api'
import {Button, FormActions, FormError, FormLayout} from '@/shared/ui'

import styles from './SecondFactorForm.module.css'

/**
 * The second step of signing in with the password: a code from the authenticator app, or a recovery code.
 * `onBack` returns to the password, as a step that took too long must.
 */
export function SecondFactorForm(props: {
  challenge: SecondFactorChallenge
  onSignedIn: (account: Account) => void
  onBack: () => void
}) {
  const {t} = useTranslation()
  const signIn = useSignInWithCode()
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState(false)
  const expired = isApiError(signIn.error, 'second_factor_expired')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    signIn.mutate({token: props.challenge.token, ...secondFactorCode(code, recovery)}, {onSuccess: props.onSignedIn})
  }

  return (
    <form onSubmit={submit}>
      <FormLayout>
        <p className={styles.text}>{t(recovery ? 'twoStep.enterRecoveryCode' : 'twoStep.enterCode')}</p>
        <SecondFactorField
          value={code}
          onChange={setCode}
          recovery={recovery}
          onToggle={() => {
            setRecovery(!recovery)
            setCode('')
            signIn.reset()
          }}
        />
        {signIn.isError && <FormError>{describeError(signIn.error, t)}</FormError>}
        <FormActions>
          <Button variant="secondary" onClick={props.onBack}>
            {t('common.back')}
          </Button>
          {!expired && (
            <Button type="submit" disabled={signIn.isPending}>
              {t('signIn.submit')}
            </Button>
          )}
        </FormActions>
      </FormLayout>
    </form>
  )
}
