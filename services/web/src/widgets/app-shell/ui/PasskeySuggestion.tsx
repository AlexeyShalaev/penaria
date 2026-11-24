import {KeyRound, X} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {AddPasskeyButton} from '@/features/add-passkey'
import {usePasskeys} from '@/entities/account'
import {passkeysSupported} from '@/shared/lib/webauthn'
import {IconButton, IconTile} from '@/shared/ui'

import {dismissPasskeySuggestion, passkeySuggestionDismissed} from '../model/passkeySuggestion'
import styles from './PasskeySuggestion.module.css'

/**
 * A gentle suggestion to add a passkey, for an account that signs in only with its password, in a
 * browser that can have one. Dismissing it is remembered in this browser.
 */
export function PasskeySuggestion(props: {accountId: string}) {
  const {t} = useTranslation()
  const [dismissed, setDismissed] = useState(() => passkeySuggestionDismissed(props.accountId))
  const offered = passkeysSupported() && !dismissed
  const passkeys = usePasskeys({enabled: offered})

  if (!offered || passkeys.data?.length !== 0) return null

  const dismiss = () => {
    dismissPasskeySuggestion(props.accountId)
    setDismissed(true)
  }

  return (
    <section className={styles.banner} aria-labelledby="passkey-suggestion">
      <IconTile icon={KeyRound} accent />
      <div className={styles.text}>
        <h2 id="passkey-suggestion" className={styles.title}>
          {t('passkeys.suggestionTitle')}
        </h2>
        <p className={styles.body}>{t('passkeys.suggestionText')}</p>
        <AddPasskeyButton variant="primary" />
      </div>
      <IconButton icon={X} label={t('passkeys.notNow')} onClick={dismiss} />
    </section>
  )
}
