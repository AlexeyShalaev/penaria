import {useState} from 'react'

import {toggled} from '@/shared/lib/set'

const key = (homeId: string) => `penaria.expanded.${homeId}`

function read(homeId: string): Set<string> | null {
  try {
    const saved = sessionStorage.getItem(key(homeId))
    return saved === null ? null : new Set(JSON.parse(saved) as string[])
  } catch {
    return null
  }
}

function write(homeId: string, ids: Set<string>): void {
  try {
    sessionStorage.setItem(key(homeId), JSON.stringify([...ids]))
  } catch {
    // The tree then opens as it does the first time.
  }
}

/**
 * The places open in a home's tree. They outlive a visit to an entity's page in the same tab; until
 * the person opens or closes something, `initial` (the tops of the home) is open.
 */
export function useExpanded(homeId: string, initial: readonly string[]) {
  const [saved, setSaved] = useState(() => ({homeId, ids: read(homeId)}))
  const own = saved.homeId === homeId ? saved.ids : read(homeId)
  const expanded = own ?? new Set(initial)

  const save = (ids: Set<string>) => {
    write(homeId, ids)
    setSaved({homeId, ids})
  }
  const toggle = (id: string) => save(toggled(expanded, id))
  const open = (ids: readonly string[]) => save(new Set([...expanded, ...ids]))
  return {expanded, toggle, open}
}
