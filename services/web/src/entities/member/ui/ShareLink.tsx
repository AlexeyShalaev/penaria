import {Check, Copy, Share2} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {Button, QrCode} from '@/shared/ui'

import styles from './ShareLink.module.css'

/** A link just made, to pass on: its QR code, the address, and buttons to copy or send it. */
export function ShareLink(props: {url: string; title: string}) {
  const {t} = useTranslation()
  const [copied, setCopied] = useState(false)
  const canShare = typeof navigator.share === 'function'

  const copy = async () => {
    await navigator.clipboard.writeText(props.url)
    setCopied(true)
  }

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
          <Button icon={copied ? Check : Copy} variant={canShare ? 'secondary' : 'primary'} onClick={() => void copy()}>
            {t(copied ? 'share.copied' : 'share.copy')}
          </Button>
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
