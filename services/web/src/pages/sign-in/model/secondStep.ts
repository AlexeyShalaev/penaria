import type {SecondFactorChallenge} from '@/entities/account'

/**
 * The second step a sign-in through the provider left in the address's fragment, for an account with an
 * authenticator app: the server puts it there, since browsers never send a fragment to a server or its logs.
 */
export function secondStepIn(fragment: string): SecondFactorChallenge | null {
  const params = new URLSearchParams(fragment.replace(/^#/, ''))
  const token = params.get('second-factor')
  const until = params.get('until')
  return token && until ? {token, expires_at: until} : null
}
