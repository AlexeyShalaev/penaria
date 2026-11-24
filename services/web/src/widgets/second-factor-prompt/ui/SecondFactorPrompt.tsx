import {KeyRound, LogOut, ShieldAlert, Smartphone} from 'lucide-react'
import {useId, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {AddPasskeyButton} from '@/features/add-passkey'
import {TotpSetup} from '@/features/two-step-sign-in'
import {useSecondFactor, useSignOut} from '@/entities/account'
import {passkeysSupported} from '@/shared/lib/webauthn'
import {Button, IconTile} from '@/shared/ui'

import styles from './SecondFactorPrompt.module.css'

/**
 * Covers the app for an owner or an install admin who signs in with a password and has no second factor: the
 * server refuses their owner-level commands until they add a passkey or an authenticator app, so they are
 * asked at once. It stays while the app's set-up shows its recovery codes.
 *
 * Not a `Dialog`: nothing dismisses it but adding a factor or signing out, and it sits under the dialogs it
 * opens itself (confirming it is you before the set-up), which is why its layer is below theirs.
 */
export function SecondFactorPrompt() {
  const {t} = useTranslation()
  const titleId = useId()
  const status = useSecondFactor()
  const signOut = useSignOut()
  const [settingUp, setSettingUp] = useState(false)

  if (!status.data?.missing && !settingUp) return null

  return (
    <div className={styles.backdrop}>
      <section className={styles.panel} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className={styles.header}>
          <IconTile icon={ShieldAlert} size="lg" accent />
          <h2 id={titleId} className={styles.title}>
            {t('secondFactorPrompt.title')}
          </h2>
          <p className={styles.text}>{t('secondFactorPrompt.text')}</p>
        </header>
        {passkeysSupported() && !settingUp && (
          <div className={styles.choice}>
            <div className={styles.choiceHead}>
              <IconTile icon={KeyRound} size="sm" />
              <h3 className={styles.choiceTitle}>{t('secondFactorPrompt.passkey')}</h3>
            </div>
            <p className={styles.text}>{t('secondFactorPrompt.passkeyText')}</p>
            <AddPasskeyButton variant="primary" />
          </div>
        )}
        <div className={styles.choice}>
          <div className={styles.choiceHead}>
            <IconTile icon={Smartphone} size="sm" />
            <h3 className={styles.choiceTitle}>{t('secondFactorPrompt.app')}</h3>
          </div>
          <p className={styles.text}>{t('secondFactorPrompt.appText')}</p>
          <TotpSetup
            onStarted={() => setSettingUp(true)}
            onDone={() => setSettingUp(false)}
            onCancel={() => setSettingUp(false)}
          />
        </div>
        <footer className={styles.footer}>
          <Button variant="ghost" size="sm" icon={LogOut} disabled={signOut.isPending} onClick={() => signOut.mutate()}>
            {t('account.signOut')}
          </Button>
        </footer>
      </section>
    </div>
  )
}
