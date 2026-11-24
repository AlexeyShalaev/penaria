import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'

import {api, type Schemas, unwrap} from '@/shared/api'

export type Home = Schemas['HomeOut']

const homeKeys = {
  all: ['homes'] as const,
  one: (homeId: string) => ['homes', homeId] as const,
}

export function useHomes() {
  return useQuery({queryKey: homeKeys.all, queryFn: () => unwrap(api.GET('/api/v1/homes'))})
}

export function useHome(homeId: string | undefined) {
  return useQuery({
    queryKey: homeKeys.one(homeId ?? ''),
    queryFn: () => unwrap(api.GET('/api/v1/homes/{home_id}', {params: {path: {home_id: homeId ?? ''}}})),
    enabled: homeId !== undefined,
  })
}

export function useCreateHome() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['HomeIn']) => unwrap(api.POST('/api/v1/homes', {body})),
    onSuccess: async (home) => {
      queryClient.setQueryData(homeKeys.one(home.id), home)
      await queryClient.invalidateQueries({queryKey: homeKeys.all, exact: true})
    },
  })
}
