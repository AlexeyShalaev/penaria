import type {TFunction} from 'i18next'

import {describeError} from '@/shared/api'
import {WebAuthnError} from '@/shared/lib/webauthn'

import {describeDevice} from './device'

/** A translated message for a failed passkey ceremony: the browser's refusal, or the server's answer. */
export function describePasskeyError(error: unknown, t: TFunction): string {
  if (error instanceof WebAuthnError) return t(`passkeys.failure.${error.failure}`)
  return describeError(error, t)
}

/** What a new passkey is called until its person renames it: the browser and system that made it. */
export function defaultPasskeyName(t: TFunction, userAgent: string = navigator.userAgent): string {
  const {browser, system} = describeDevice(userAgent)
  if (browser && system) return t('account.deviceOn', {browser, system})
  return browser ?? system ?? t('passkeys.defaultName')
}
