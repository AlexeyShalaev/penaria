/** "drill, screwdriver , " -> ["drill", "screwdriver"]. */
export function splitList(value: string): string[] {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}
