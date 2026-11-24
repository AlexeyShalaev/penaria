import {Check, Copy} from 'lucide-react'
import {useState} from 'react'

import {Button} from './Button'

/**
 * Copies a text to the clipboard and says so. Browsers offer the clipboard only on a secure page, so on an
 * install opened at a plain http address it shows nothing: the text stays on screen to select by hand.
 */
export function CopyButton(props: {
  text: string
  label: string
  copiedLabel: string
  variant?: 'primary' | 'secondary'
}) {
  const [copied, setCopied] = useState(false)
  if (typeof navigator.clipboard?.writeText !== 'function') return null

  const copy = async () => {
    await navigator.clipboard.writeText(props.text)
    setCopied(true)
  }
  return (
    <Button variant={props.variant} icon={copied ? Check : Copy} onClick={() => void copy()}>
      {copied ? props.copiedLabel : props.label}
    </Button>
  )
}
