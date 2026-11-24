import {vi} from 'vitest'

export type ApiCall = {method: string; path: string; search: string; body: unknown}
type Reply = unknown | ((call: ApiCall) => unknown)

function json(status: number, body: unknown, type = 'application/json') {
  return new Response(JSON.stringify(body), {status, headers: {'Content-Type': type}})
}

/** A problem+json answer, as the server sends for a failure. */
export function problem(status: number, code: string) {
  return json(
    status,
    {type: 'about:blank', title: code, status, code, detail: code, params: {}},
    'application/problem+json',
  )
}

/**
 * Replaces fetch with canned answers keyed by "METHOD /path?query" (or "METHOD /path" for any query);
 * a reply is a JSON body, a Response, or a function of the call. Returns the calls, in order.
 */
export function mockApi(routes: Record<string, Reply>): ApiCall[] {
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
      const key = [`${call.method} ${call.path}${call.search}`, `${call.method} ${call.path}`].find((k) => k in routes)
      if (key === undefined) throw new Error(`no mocked answer for ${call.method} ${call.path}${call.search}`)
      const reply = routes[key]
      const value = typeof reply === 'function' ? await reply(call) : reply
      return value instanceof Response ? value : json(200, value)
    }),
  )
  return calls
}
