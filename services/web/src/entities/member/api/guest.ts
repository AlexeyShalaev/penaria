import {useMutation, useQuery} from '@tanstack/react-query'

import {api, isApiError, type Schemas, unwrap} from '@/shared/api'

export type GuestVisit = Schemas['GuestOut']

const guestKey = ['guest'] as const

/** Exchanges a guest link's token for a guest session in this browser. */
export function useOpenGuestLink() {
  return useMutation({mutationFn: (token: string) => unwrap(api.POST('/api/v1/guest-sessions', {body: {token}}))})
}

/** The visit of this browser's guest session, or `null` once it has ended (or there is none). */
export function useGuestVisit() {
  return useQuery({
    queryKey: guestKey,
    queryFn: async (): Promise<GuestVisit | null> => {
      try {
        return await unwrap(api.GET('/api/v1/guest'))
      } catch (error) {
        if (isApiError(error, 'unauthenticated')) return null
        throw error
      }
    },
  })
}
