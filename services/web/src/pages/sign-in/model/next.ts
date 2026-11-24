/** Only a page of this app: a link to sign in must not send anyone to another site afterwards. */
export function safeNext(next: string | null): string {
  if (!next?.startsWith('/')) return '/'
  // Browsers read `/\host` and `/<tab>/host` as `//host`; resolving the path the same way catches them.
  let url: URL
  try {
    url = new URL(next, window.location.origin)
  } catch {
    return '/'
  }
  return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : '/'
}
