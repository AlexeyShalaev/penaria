/** The server's reasons (`Problem` in its `domain/oidc.py`); one it adds later shows as a failed sign-in. */
export const PROBLEMS = [
  'expired',
  'failed',
  'invitation_required',
  'identity_taken',
  'wrong_account',
  'account_disabled',
  'already_linked',
  'invitation_unusable',
  'sign_in_first',
] as const

export type Problem = (typeof PROBLEMS)[number]

export function problemOf(value: string | null): Problem {
  return PROBLEMS.find((problem) => problem === value) ?? 'failed'
}
