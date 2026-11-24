/** A copy of the set with the value added, or removed if it was there. */
export function toggled<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set)
  if (!next.delete(value)) next.add(value)
  return next
}
