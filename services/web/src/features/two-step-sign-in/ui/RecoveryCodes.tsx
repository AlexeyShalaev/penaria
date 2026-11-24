import {Check, Copy, Download} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {Button, FormActions} from '@/shared/ui'

import styles from './TwoStep.module.css'

const FILE_NAME = 'penaria-recovery-codes.txt'
const REVOKE_AFTER_MS = 60_000

/** Recovery codes just made, shown only now: to copy, download or write down before `onDone`. */
export function RecoveryCodes(props: {codes: string[]; onDone: () => void}) {
  const {t} = useTranslation()
  const [copied, setCopied] = useState(false)
  const text = props.codes.join('\n') + '\n'
  // Browsers offer the clipboard only on a secure page: an install opened at a plain http address has none.
  const canCopy = typeof navigator.clipboard?.writeText === 'function'

  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
  }

  const download = () => {
    const url = URL.createObjectURL(new Blob([text], {type: 'text/plain'}))
    const link = document.createElement('a')
    link.href = url
    link.download = FILE_NAME
    link.click()
    // Revoked at once, some browsers drop the download, and the codes are shown only now.
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS)
  }

  return (
    <div className={styles.codes}>
      <h3 className={styles.subtitle}>{t('twoStep.codesTitle')}</h3>
      <p className={styles.text}>{t('twoStep.codesText')}</p>
      <ol className={styles.codeList} aria-label={t('twoStep.codesTitle')}>
        {props.codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ol>
      <div className={styles.buttons}>
        {canCopy && (
          <Button variant="secondary" icon={copied ? Check : Copy} onClick={() => void copy()}>
            {t(copied ? 'twoStep.copied' : 'twoStep.copy')}
          </Button>
        )}
        <Button variant="secondary" icon={Download} onClick={download}>
          {t('twoStep.download')}
        </Button>
      </div>
      <FormActions>
        <Button onClick={props.onDone}>{t('twoStep.saved')}</Button>
      </FormActions>
    </div>
  )
}
