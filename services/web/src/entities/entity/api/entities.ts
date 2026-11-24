import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, isApiError, type Schemas, unwrap} from '@/shared/api'

import type {ArchiveReason} from '../model/kinds'

export type EntitySummary = Schemas['EntityOut']
export type EntityDetail = Schemas['EntityDetailOut']
export type EntityEvent = Schemas['EventOut']
export type NewEntity = Schemas['EntityIn']
export type EntityChanges = Schemas['EntityPatch']

const HISTORY_LIMIT = 100

export const treeKeys = {
  all: ['tree'] as const,
  children: (homeId: string, parentId: string | null, includeArchived: boolean) =>
    ['tree', 'children', homeId, parentId, includeArchived] as const,
  entity: (entityId: string) => ['tree', 'entity', entityId] as const,
  history: (entityId: string) => ['tree', 'history', entityId] as const,
}

/** The entities directly inside a parent; the tops of the home (its properties) for null. */
export function useChildren(homeId: string, parentId: string | null, includeArchived = false) {
  return useQuery({
    queryKey: treeKeys.children(homeId, parentId, includeArchived),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/homes/{home_id}/entities', {
          params: {
            path: {home_id: homeId},
            query: {parent_id: parentId ?? undefined, include_archived: includeArchived || undefined},
          },
        }),
      ),
  })
}

export function useEntity(entityId: string | undefined) {
  return useQuery({
    queryKey: treeKeys.entity(entityId ?? ''),
    queryFn: () => unwrap(api.GET('/api/v1/entities/{entity_id}', {params: {path: {entity_id: entityId ?? ''}}})),
    enabled: entityId !== undefined,
  })
}

export function useHistory(entityId: string) {
  return useQuery({
    queryKey: treeKeys.history(entityId),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/entities/{entity_id}/history', {
          params: {path: {entity_id: entityId}, query: {limit: HISTORY_LIMIT}},
        }),
      ),
  })
}

/** A change to the tree: the answer replaces the entity, everything else in the tree is read again. */
function useTreeMutation<T>(change: (input: T) => Promise<EntityDetail>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: change,
    onSuccess: async (entity) => {
      queryClient.setQueryData(treeKeys.entity(entity.id), entity)
      await queryClient.invalidateQueries({queryKey: treeKeys.all})
    },
    onError: async (error) => {
      // Someone else changed it first: show what is there now.
      if (isApiError(error) && error.status === 409) await queryClient.invalidateQueries({queryKey: treeKeys.all})
    },
  })
}

export function useCreateEntity(homeId: string) {
  return useTreeMutation((body: NewEntity) =>
    unwrap(api.POST('/api/v1/homes/{home_id}/entities', {params: {path: {home_id: homeId}}, body})),
  )
}

export function useUpdateEntity(entityId: string) {
  return useTreeMutation((body: EntityChanges) =>
    unwrap(api.PATCH('/api/v1/entities/{entity_id}', {params: {path: {entity_id: entityId}}, body})),
  )
}

export function useMoveEntity(entityId: string) {
  return useTreeMutation((body: {parent_id: string; version: number}) =>
    unwrap(api.POST('/api/v1/entities/{entity_id}:move', {params: {path: {entity_id: entityId}}, body})),
  )
}

export function useArchiveEntity(entityId: string) {
  return useTreeMutation((body: {reason: ArchiveReason; version: number}) =>
    unwrap(api.POST('/api/v1/entities/{entity_id}:archive', {params: {path: {entity_id: entityId}}, body})),
  )
}

export function useRestoreEntity(entityId: string) {
  return useTreeMutation((body: {version: number}) =>
    unwrap(api.POST('/api/v1/entities/{entity_id}:restore', {params: {path: {entity_id: entityId}}, body})),
  )
}

export function useVerifyEntity(entityId: string) {
  return useTreeMutation(() =>
    unwrap(api.POST('/api/v1/entities/{entity_id}:verify', {params: {path: {entity_id: entityId}}})),
  )
}
