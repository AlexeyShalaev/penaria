import {useState} from 'react'

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

  const update = (change: (ids: Set<string>) => void) => {
    const next = new Set(expanded)
    change(next)
    write(homeId, next)
    setSaved({homeId, ids: next})
  }
  const toggle = (id: string) =>
    update((ids) => {
      if (!ids.delete(id)) ids.add(id)
    })
  const open = (ids: readonly string[]) =>
    update((current) => {
      for (const id of ids) current.add(id)
    })
  return {expanded, toggle, open}
}
