import type {TFunction} from 'i18next'

import {describeError} from '@/shared/api'
import {WebAuthnError} from '@/shared/lib/webauthn'

/** A translated message for a failed passkey ceremony: the browser's refusal, or the server's answer. */
export function describePasskeyError(error: unknown, t: TFunction): string {
  if (error instanceof WebAuthnError) return t(`passkeys.failure.${error.failure}`)
  return describeError(error, t)
}
