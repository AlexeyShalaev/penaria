const DAY_MS = 24 * 3600 * 1000

/** A date input's value for the day `date` falls on, in the browser's time zone. */
export function toDateInput(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 10)
}

/** The end of the day a date input names, in the browser's time zone, as the API takes times. */
export function endOfDay(value: string): string {
  return new Date(`${value}T23:59:59`).toISOString()
}

export function daysFrom(now: Date, days: number): Date {
  return new Date(now.getTime() + days * DAY_MS)
}

/** The days a role's grants last unless the giver says otherwise, rounded up. */
export function defaultDays(seconds: number | null | undefined): number | null {
  return seconds ? Math.ceil(seconds / (24 * 3600)) : null
}
