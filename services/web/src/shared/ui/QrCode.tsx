import {useMemo} from 'react'
import {encode} from 'uqr'

import styles from './QrCode.module.css'

/** `value` as a QR code, drawn here in the browser: the link never leaves it to be rendered. */
export function QrCode(props: {value: string; label: string; size?: number}) {
  const {size = 168} = props
  const code = useMemo(() => encode(props.value, {ecc: 'M', border: 2}), [props.value])
  const modules = useMemo(
    () =>
      code.data
        .flatMap((row, y) => row.map((dark, x) => (dark ? `M${x} ${y}h1v1h-1z` : '')))
        .filter(Boolean)
        .join(''),
    [code],
  )
  return (
    <svg
      className={styles.qr}
      role="img"
      aria-label={props.label}
      viewBox={`0 0 ${code.size} ${code.size}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
    >
      <rect width={code.size} height={code.size} className={styles.light} />
      <path d={modules} className={styles.dark} />
    </svg>
  )
}
