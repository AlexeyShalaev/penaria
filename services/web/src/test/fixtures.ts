import type {EntityDetail, EntitySummary} from '@/entities/entity'
import type {Home} from '@/entities/home'

export const HOME_ID = '00000000-0000-4000-8000-000000000001'

export function home(overrides: Partial<Home> = {}): Home {
  return {
    id: HOME_ID,
    name: 'Flat',
    timezone: 'Europe/Berlin',
    locale: 'en',
    version: 1,
    access: {owner: true, all_permissions: true, permissions: []},
    ...overrides,
  }
}

export function entity(overrides: Partial<EntitySummary> & Pick<EntitySummary, 'id' | 'name' | 'kind'>): EntitySummary {
  return {
    home_id: HOME_ID,
    parent_id: null,
    aliases: [],
    quantity: null,
    unit: null,
    status: 'present',
    privacy: 'normal',
    verified_at: null,
    archived_at: null,
    archive_reason: null,
    version: 1,
    freshness: 'fresh',
    children: 0,
    ...overrides,
  }
}

export function detail(overrides: Partial<EntityDetail> & Pick<EntityDetail, 'id' | 'name' | 'kind'>): EntityDetail {
  return {...entity(overrides), path: [], can_edit: true, ...overrides}
}
