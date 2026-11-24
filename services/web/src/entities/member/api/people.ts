import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'

export type Role = Schemas['RoleOut']
export type Member = Schemas['MemberOut']
export type MemberGrant = Schemas['GrantOut']
export type Invitation = Schemas['InvitationOut']
export type GuestLink = Schemas['GuestLinkOut']
export type Device = Schemas['DeviceOut']
export type PlaceRef = Schemas['PlaceRefOut']
export type NewInvitation = Schemas['InvitationIn']
export type NewGuestLink = Schemas['GuestLinkIn']
export type NewDevice = Schemas['DeviceIn']
export type GrantChanges = Schemas['GrantPatch']

const peopleKeys = {
  home: (homeId: string) => ['people', homeId] as const,
  roles: (homeId: string) => ['people', homeId, 'roles'] as const,
  members: (homeId: string) => ['people', homeId, 'members'] as const,
  invitations: (homeId: string) => ['people', homeId, 'invitations'] as const,
  guestLinks: (homeId: string) => ['people', homeId, 'guest-links'] as const,
  devices: (homeId: string) => ['people', homeId, 'devices'] as const,
}

const path = (homeId: string) => ({params: {path: {home_id: homeId}}})

export function useRoles(homeId: string) {
  return useQuery({
    queryKey: peopleKeys.roles(homeId),
    queryFn: () => unwrap(api.GET('/api/v1/homes/{home_id}/roles', path(homeId))),
    staleTime: Infinity,
  })
}

export function useMembers(homeId: string) {
  return useQuery({
    queryKey: peopleKeys.members(homeId),
    queryFn: () => unwrap(api.GET('/api/v1/homes/{home_id}/members', path(homeId))),
  })
}

export function useInvitations(homeId: string) {
  return useQuery({
    queryKey: peopleKeys.invitations(homeId),
    queryFn: () => unwrap(api.GET('/api/v1/homes/{home_id}/invitations', path(homeId))),
  })
}

export function useGuestLinks(homeId: string) {
  return useQuery({
    queryKey: peopleKeys.guestLinks(homeId),
    queryFn: () => unwrap(api.GET('/api/v1/homes/{home_id}/guest-links', path(homeId))),
  })
}

export function useDevices(homeId: string) {
  return useQuery({
    queryKey: peopleKeys.devices(homeId),
    queryFn: () => unwrap(api.GET('/api/v1/homes/{home_id}/devices', path(homeId))),
  })
}

/** A change to a home's people: everything shown about them is read again afterwards. */
function usePeopleMutation<T, R>(homeId: string, change: (input: T) => Promise<R>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: change,
    onSettled: () => queryClient.invalidateQueries({queryKey: peopleKeys.home(homeId)}),
  })
}

export function useCreateInvitation(homeId: string) {
  return usePeopleMutation(homeId, (body: NewInvitation) =>
    unwrap(api.POST('/api/v1/homes/{home_id}/invitations', {...path(homeId), body})),
  )
}

export function useRevokeInvitation(homeId: string) {
  return usePeopleMutation(homeId, (invitationId: string) =>
    unwrap(
      api.DELETE('/api/v1/homes/{home_id}/invitations/{invitation_id}', {
        params: {path: {home_id: homeId, invitation_id: invitationId}},
      }),
    ),
  )
}

export function useCreateGuestLink(homeId: string) {
  return usePeopleMutation(homeId, (body: NewGuestLink) =>
    unwrap(api.POST('/api/v1/homes/{home_id}/guest-links', {...path(homeId), body})),
  )
}

/** A device or an integration, and its token, which the answer carries only this once. */
export function useCreateDevice(homeId: string) {
  return usePeopleMutation(homeId, (body: NewDevice) =>
    unwrap(api.POST('/api/v1/homes/{home_id}/devices', {...path(homeId), body})),
  )
}

export function useChangeGrant(homeId: string) {
  return usePeopleMutation(homeId, (input: {grantId: string; changes: GrantChanges}) =>
    unwrap(
      api.PATCH('/api/v1/homes/{home_id}/grants/{grant_id}', {
        params: {path: {home_id: homeId, grant_id: input.grantId}},
        body: input.changes,
      }),
    ),
  )
}

/** Takes back a member's access, or ends a guest link and every visit made with it, or a device's token. */
export function useRevokeGrant(homeId: string) {
  return usePeopleMutation(homeId, (grantId: string) =>
    unwrap(
      api.DELETE('/api/v1/homes/{home_id}/grants/{grant_id}', {params: {path: {home_id: homeId, grant_id: grantId}}}),
    ),
  )
}

/** A password reset link for a member, to pass on by hand. */
export function useCreateResetLink(homeId: string) {
  return useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.POST('/api/v1/homes/{home_id}/members/{user_id}:reset-link', {
          params: {path: {home_id: homeId, user_id: userId}},
        }),
      ),
  })
}

/** The signed-in person gives up their access to the home. */
export function useLeaveHome(homeId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/homes/{home_id}:leave', path(homeId))),
    onSuccess: () => queryClient.removeQueries({queryKey: peopleKeys.home(homeId)}),
  })
}
