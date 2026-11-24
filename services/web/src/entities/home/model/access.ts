import type {Home} from '../api/homes'

/** Whether the actor may change the tree at the top of the home; deeper places answer for themselves. */
export function canEditHome(home: Home | undefined): boolean {
  const access = home?.access
  return !!access && (access.all_permissions || access.permissions.includes('entities.edit'))
}

/** Whether the actor manages the home's people: sees who has access and gives it. */
export function canManagePeople(home: Home | undefined): boolean {
  const access = home?.access
  return !!access && (access.all_permissions || access.permissions.includes('members.manage'))
}
