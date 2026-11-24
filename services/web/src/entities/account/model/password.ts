/** The server's rule (docs/design/sign-in.md, 4.2); checked here too, so the form answers at once. */
export const PASSWORD_MIN_LENGTH = 12

export type PasswordProblem = 'tooShort' | 'mismatch'

/** What is wrong with a new password and its repetition, if anything. */
export function checkNewPassword(password: string, repeated: string): PasswordProblem | null {
  if ([...password].length < PASSWORD_MIN_LENGTH) return 'tooShort'
  if (password !== repeated) return 'mismatch'
  return null
}
