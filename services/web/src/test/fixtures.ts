import type {Account, AccountSession} from '@/entities/account'
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

export function account(overrides: Partial<Account> = {}): Account {
  return {
    id: '00000000-0000-4000-8000-0000000000a1',
    username: 'owner',
    display_name: 'Alex',
    email: null,
    locale: 'en',
    install_admin: true,
    ...overrides,
  }
}

export function session(overrides: Partial<AccountSession> & Pick<AccountSession, 'id'>): AccountSession {
  return {
    created_at: '2026-01-01T10:00:00Z',
    last_seen_at: '2026-01-02T10:00:00Z',
    user_agent:
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
    ip: '192.0.2.10',
    current: false,
    ...overrides,
  }
}
