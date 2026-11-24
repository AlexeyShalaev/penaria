import {ShieldCheck} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useRecentSignIn, useRegenerateRecoveryCodes, useSecondFactor, useTurnOffTotp} from '@/entities/account'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {Button, Dialog, FormActions, FormError, FormLayout, IconTile, QueryState} from '@/shared/ui'

import {RecoveryCodes} from './RecoveryCodes'
import {TotpSetup} from './TotpSetup'
import styles from './TwoStep.module.css'

/** The account page's two-step sign-in: setting up the authenticator app, its recovery codes, turning it off. */
export function TwoStepSignIn() {
  const status = useSecondFactor()
  // While the set-up shows the secret or the codes, it stays though the app is already on.
  const [settingUp, setSettingUp] = useState(false)

  return (
    <QueryState query={status}>
      {(data) =>
        settingUp || !data.totp_enabled ? (
          <TotpSetup
            onStarted={() => setSettingUp(true)}
            onDone={() => setSettingUp(false)}
            onCancel={() => setSettingUp(false)}
          />
        ) : (
          <TotpOn enabledAt={data.totp_enabled_at} codesLeft={data.recovery_codes_left ?? 0} />
        )
      }
    </QueryState>
  )
}

function TotpOn(props: {enabledAt: string | null | undefined; codesLeft: number}) {
  const {t, i18n} = useTranslation()
  const regenerate = useRegenerateRecoveryCodes()
  const turnOff = useTurnOffTotp()
  const recent = useRecentSignIn()
  const [codes, setCodes] = useState<string[] | null>(null)
  const [confirming, setConfirming] = useState(false)
  const failed = recent.errorToShow(regenerate.error ?? turnOff.error)

  const newCodes = () => {
    turnOff.reset()
    regenerate.mutate(undefined, {onSuccess: (data) => setCodes(data.codes), onError: recent.retryOnError(newCodes)})
  }
  const off = () => {
    regenerate.reset()
    turnOff.mutate(undefined, {onError: recent.retryOnError(off)})
  }

  if (codes) return <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />

  return (
    <div className={styles.on}>
      <div className={styles.state}>
        <IconTile icon={ShieldCheck} size="sm" accent />
        <div className={styles.stateText}>
          <span className={styles.stateTitle}>{t('twoStep.on')}</span>
          <span className={styles.details}>
            {[
              props.enabledAt && t('twoStep.since', {when: formatDateTime(new Date(props.enabledAt), i18n.language)}),
              t('twoStep.codesLeft', {count: props.codesLeft}),
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </div>
      </div>
      <div className={styles.buttons}>
        <Button variant="secondary" disabled={regenerate.isPending} onClick={newCodes}>
          {t('twoStep.newCodes')}
        </Button>
        <Button variant="ghost" disabled={turnOff.isPending} onClick={() => setConfirming(true)}>
          {t('twoStep.turnOff')}
        </Button>
      </div>
      {failed && <FormError>{describeError(failed, t)}</FormError>}
      {confirming && (
        <Dialog title={t('twoStep.turnOffTitle')} closeLabel={t('common.close')} onClose={() => setConfirming(false)}>
          <FormLayout>
            <p className={styles.text}>{t('twoStep.turnOffText')}</p>
            <FormActions>
              <Button variant="secondary" onClick={() => setConfirming(false)}>
                {t('common.cancel')}
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  setConfirming(false)
                  off()
                }}
              >
                {t('twoStep.turnOff')}
              </Button>
            </FormActions>
          </FormLayout>
        </Dialog>
      )}
      {recent.dialog}
    </div>
  )
}
