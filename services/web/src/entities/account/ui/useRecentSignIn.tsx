import {type ReactNode, useState} from 'react'

import {isApiError} from '@/shared/api'

import {ReauthenticateDialog} from './ReauthenticateDialog'

/**
 * For a sensitive change that the server takes only after a recent sign-in. `retryAfterConfirming`
 * tells whether a failure was that refusal; if so, it asks the person to confirm it is them and then
 * runs `retry`. `dialog` is where the question shows.
 */
export function useRecentSignIn(): {
  retryAfterConfirming: (error: unknown, retry: () => void) => boolean
  dialog: ReactNode
} {
  const [retry, setRetry] = useState<(() => void) | null>(null)

  const retryAfterConfirming = (error: unknown, action: () => void) => {
    if (!isApiError(error, 'recent_sign_in_required')) return false
    setRetry(() => action)
    return true
  }

  const dialog = retry && (
    <ReauthenticateDialog
      onConfirmed={() => {
        setRetry(null)
        retry()
      }}
      onClose={() => setRetry(null)}
    />
  )
  return {retryAfterConfirming, dialog}
}

/** Whether a failure only asked for a recent sign-in, which `useRecentSignIn` handles; not an error to show. */
export function needsRecentSignIn(error: unknown): boolean {
  return isApiError(error, 'recent_sign_in_required')
}
