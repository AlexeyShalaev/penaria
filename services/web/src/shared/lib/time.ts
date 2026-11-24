const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

/** "3 days ago", "yesterday", "now" in the given language. */
export function formatRelative(date: Date, language: string, now: Date = new Date()): string {
  const format = new Intl.RelativeTimeFormat(language, {numeric: 'auto'})
  const seconds = (date.getTime() - now.getTime()) / 1000
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit)
  }
  return format.format(0, 'second')
}

export function formatDateTime(date: Date, language: string): string {
  return new Intl.DateTimeFormat(language, {dateStyle: 'long', timeStyle: 'short'}).format(date)
}

export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

export function timeZones(): string[] {
  return Intl.supportedValuesOf('timeZone')
}
