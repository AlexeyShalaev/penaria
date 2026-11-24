import {vi} from 'vitest'

export type ApiCall = {method: string; path: string; search: string; body: unknown}
type Reply = unknown | ((call: ApiCall) => unknown)

const unmatched: string[] = []

function json(status: number, body: unknown, type = 'application/json') {
  return new Response(JSON.stringify(body), {status, headers: {'Content-Type': type}})
}

/** A problem+json answer, as the server sends for a failure. */
export function problem(status: number, code: string) {
  return json(status, {type: 'about:blank', title: code, status, code, detail: code}, 'application/problem+json')
}

/**
 * What an install without a sign-in provider and an account with a password answer, for the many pages and
 * dialogs that ask; a test overrides them by naming the same routes.
 */
const DEFAULT_ROUTES: Record<string, Reply> = {
  'GET /api/v1/auth/config': {oidc: null},
  'GET /api/v1/me/sign-in-methods': {password: true, external_identities: []},
}

/**
 * Replaces fetch with canned answers keyed by "METHOD /path" plus the exact query string, if any; a
 * reply is a JSON body, a Response, or a function of the call. Returns the calls, in order. A call
 * nothing answers fails the test in `expectEveryCallAnswered`, run after each test.
 */
export function mockApi(overrides: Record<string, Reply>): ApiCall[] {
  const routes = {...DEFAULT_ROUTES, ...overrides}
  const calls: ApiCall[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const url = new URL(request.url)
      const text = await request.text()
      const call = {
        method: request.method,
        path: url.pathname,
        search: url.search,
        body: text ? JSON.parse(text) : undefined,
      }
      calls.push(call)
      const key = `${call.method} ${call.path}${call.search}`
      if (!(key in routes)) {
        unmatched.push(key)
        throw new Error(`no mocked answer for ${key}`)
      }
      const reply = routes[key]
      const value = typeof reply === 'function' ? await reply(call) : reply
      return value instanceof Response ? value : json(200, value)
    }),
  )
  return calls
}

export function expectEveryCallAnswered() {
  const missed = unmatched.splice(0)
  if (missed.length) throw new Error(`calls with no mocked answer: ${missed.join(', ')}`)
}

/** The answer of an install that sends no email, for the pages that ask. */
export const MAIL_OFF = {'GET /api/v1/mail': {enabled: false}}

/** The answer of an account that needs no second factor, or has one, for the pages and dialogs that ask. */
export const SECOND_FACTOR_FINE = {
  'GET /api/v1/me/second-factor': {
    totp_enabled: false,
    totp_enabled_at: null,
    recovery_codes_left: null,
    required: false,
    missing: false,
  },
}
