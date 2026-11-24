import type {SecondFactorCode} from '../api/account'

/** What the server takes for what was typed: a code of the app without spaces, or a recovery code. */
export function secondFactorCode(value: string, recovery: boolean): SecondFactorCode {
  return recovery ? {recovery_code: value.trim()} : {code: value.replace(/\s/g, '')}
}
