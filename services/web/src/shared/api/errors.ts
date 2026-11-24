import type {TFunction} from 'i18next'

/** A failed API call: the problem+json body's `code` names what went wrong. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly params: Record<string, unknown>

  constructor(status: number, code: string, detail: string, params: Record<string, unknown> = {}) {
    super(detail || code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.params = params
  }
}

type Problem = {code?: unknown; detail?: unknown; params?: unknown}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** The data of a successful call; a failed one throws an ApiError. */
export async function unwrap<T>(call: Promise<{data?: T; error?: unknown; response: Response}>): Promise<T> {
  const {data, error, response} = await call
  if (response.ok) return data as T
  const problem: Problem = isObject(error) ? error : {}
  throw new ApiError(
    response.status,
    typeof problem.code === 'string' ? problem.code : 'http_error',
    typeof problem.detail === 'string' ? problem.detail : response.statusText,
    isObject(problem.params) ? problem.params : {},
  )
}

export function isApiError(error: unknown, code?: string): error is ApiError {
  return error instanceof ApiError && (code === undefined || error.code === code)
}

/** A translated message for any error a call can end with. */
export function describeError(error: unknown, t: TFunction): string {
  if (error instanceof ApiError) {
    const key = `errors.${error.code}`
    return t(key, {defaultValue: t('errors.generic')})
  }
  if (error instanceof TypeError) return t('errors.network')
  return t('errors.generic')
}
