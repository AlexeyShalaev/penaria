import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'

export type InvitationPreview = Schemas['InvitationPreviewOut']
export type NewAccount = Omit<Schemas['NewAccountIn'], 'token'>

/** What an invitation's link offers. It changes nothing, so it is asked again freely. */
export function useInvitationPreview(token: string) {
  return useQuery({
    queryKey: ['invitation', token],
    queryFn: () => unwrap(api.POST('/api/v1/invitations:preview', {body: {token}})),
    staleTime: Infinity,
  })
}

// The new home joins the switcher's list.
function useJoined() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({queryKey: ['homes'], exact: true})
}

/** Accepts the invitation with the signed-in account; the answer is the home now joined. */
export function useAcceptInvitation(token: string) {
  const joined = useJoined()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/invitations:accept', {body: {token}})),
    onSuccess: joined,
  })
}

/** Makes an account through the invitation and accepts it; the new account is signed in. */
export function useAcceptWithNewAccount(token: string, onSignedIn: (account: Schemas['AccountOut']) => void) {
  return useMutation({
    mutationFn: (body: NewAccount) =>
      unwrap(api.POST('/api/v1/invitations:accept-new-account', {body: {...body, token}})),
    onSuccess: (answer) => onSignedIn(answer.account),
  })
}
