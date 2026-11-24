import {Share2} from 'lucide-react'
import {useTranslation} from 'react-i18next'

import {Button, CopyButton, QrCode} from '@/shared/ui'

import styles from './ShareLink.module.css'

/** A link just made, to pass on: its QR code, the address, and buttons to copy or send it. */
export function ShareLink(props: {url: string; title: string}) {
  const {t} = useTranslation()
  const canShare = typeof navigator.share === 'function'

  return (
    <div className={styles.share}>
      <QrCode value={props.url} label={t('share.qr')} />
      <div className={styles.side}>
        <input
          className={styles.url}
          value={props.url}
          readOnly
          aria-label={t('share.link')}
          onFocus={(event) => event.currentTarget.select()}
        />
        <div className={styles.buttons}>
          <CopyButton
            text={props.url}
            label={t('share.copy')}
            copiedLabel={t('share.copied')}
            variant={canShare ? 'secondary' : 'primary'}
          />
          {canShare && (
            <Button icon={Share2} onClick={() => void navigator.share({title: props.title, url: props.url})}>
              {t('share.send')}
            </Button>
          )}
        </div>
        <p className={styles.note}>{t('share.onlyNow')}</p>
      </div>
    </div>
  )
}
