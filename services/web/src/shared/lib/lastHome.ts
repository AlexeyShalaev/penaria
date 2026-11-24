const KEY = 'penaria.lastHome'

// Storage can be missing or blocked (private windows); the app then starts from the first home.
export function readLastHome(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function rememberLastHome(homeId: string): void {
  try {
    localStorage.setItem(KEY, homeId)
  } catch {
    // Nothing to remember it in.
  }
}
