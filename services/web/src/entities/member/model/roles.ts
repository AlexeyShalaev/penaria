import type {TFunction} from 'i18next'

import type {Role} from '../api/people'

export type Preset = NonNullable<Role['preset']>

/** A role's name: a preset's in the interface's language, unless someone renamed it. */
export function roleName(role: Pick<Role, 'preset' | 'name'>, t: TFunction): string {
  if (role.name) return role.name
  return role.preset ? t(`roles.${role.preset}.name`) : ''
}

/** What a role lets its holder do, in plain words; a custom role lists nothing yet. */
export function roleDescription(role: Pick<Role, 'preset'>, t: TFunction): string | null {
  return role.preset ? t(`roles.${role.preset}.description`) : null
}

export const ROLE_TONE = {
  owner: 'ok',
  admin: 'info',
  family: 'neutral',
  guest: 'warn',
  contractor: 'neutral',
} as const satisfies Record<Preset, 'ok' | 'info' | 'neutral' | 'warn'>

/** A place's path as people read it: "House / Kitchen", the top of the home left out when there is more. */
export function placeLabel(names: string[]): string {
  return (names.length > 1 ? names.slice(1) : names).join(' / ')
}

/** Where access applies: the place's path, or the whole home for none. */
export function scopeLabel(scope: {names: string[]} | null, t: TFunction): string {
  return scope ? placeLabel(scope.names) : t('people.wholeHome')
}
