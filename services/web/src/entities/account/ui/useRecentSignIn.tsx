import {type ReactNode, useState} from 'react'

import {isApiError} from '@/shared/api'

import {ReauthenticateDialog} from './ReauthenticateDialog'

/**
 * For a sensitive change that the server takes only after a recent sign-in. Pass `retryOnError(retry)`
 * as the change's `onError`: when the server asks for a recent sign-in, the person is asked to confirm
 * it is them, and `retry` runs once they do. `errorToShow` drops that request from the change's error,
 * since the dialog answers it; `dialog` is where the question shows.
 */
export function useRecentSignIn(): {
  retryOnError: (retry: () => void) => (error: unknown) => void
  errorToShow: (error: Error | null) => Error | null
  dialog: ReactNode
} {
  const [retry, setRetry] = useState<(() => void) | null>(null)
  const asksToConfirm = (error: unknown) => isApiError(error, 'recent_sign_in_required')

  const dialog = retry && (
    <ReauthenticateDialog
      onConfirmed={() => {
        setRetry(null)
        retry()
      }}
      onClose={() => setRetry(null)}
    />
  )
  return {
    retryOnError: (action) => (error) => {
      if (asksToConfirm(error)) setRetry(() => action)
    },
    errorToShow: (error) => (asksToConfirm(error) ? null : error),
    dialog,
  }
}
