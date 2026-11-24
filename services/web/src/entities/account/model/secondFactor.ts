import type {SecondFactorCode} from '../api/account'

/** What was typed, as a code of the app or a recovery code; the server ignores spaces and dashes in either. */
export function secondFactorCode(value: string, recovery: boolean): SecondFactorCode {
  return recovery ? {recovery_code: value} : {code: value}
}
