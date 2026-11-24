const KEY = 'penaria.passkeySuggestionDismissed'

// Storage can be missing or blocked (private windows); the suggestion then shows until a passkey is added.
export function passkeySuggestionDismissed(accountId: string): boolean {
  try {
    return localStorage.getItem(KEY)?.split(',').includes(accountId) ?? false
  } catch {
    return false
  }
}

export function dismissPasskeySuggestion(accountId: string): void {
  try {
    const dismissed = localStorage.getItem(KEY)?.split(',') ?? []
    localStorage.setItem(KEY, [...dismissed, accountId].join(','))
  } catch {
    // Nothing to remember it in.
  }
}
