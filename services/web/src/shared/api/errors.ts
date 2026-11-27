import type {TFunction} from 'i18next'

import {i18n} from '@/shared/i18n'
import {formatDateTime, formatWait} from '@/shared/lib/time'

type Params = Record<string, unknown>

/** A failed API call: the problem+json body's `code` names what went wrong, its `params` the details. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly params: Params

  constructor(status: number, code: string, detail: string, params: Params = {}) {
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

/**
 * A translated message for any error a call can end with. The error's params fill the message; a
 * `reason` or `field` picks a more precise message (`errors.weak_password_common`) when there is one,
 * `retry_after_seconds` becomes `{{wait}}`, such as "in 30 seconds", and `ends_at` becomes `{{until}}`,
 * a date and time in the reader's language.
 */
export function describeError(error: unknown, t: TFunction): string {
  if (error instanceof ApiError) {
    const {reason, field, retry_after_seconds: retryAfter, ends_at: endsAt} = error.params
    const context = typeof reason === 'string' ? reason : typeof field === 'string' ? field : undefined
    const wait = typeof retryAfter === 'number' ? formatWait(retryAfter, i18n.language) : undefined
    const until = typeof endsAt === 'string' ? formatDateTime(new Date(endsAt), i18n.language) : undefined
    return t(`errors.${error.code}`, {...error.params, context, wait, until, defaultValue: t('errors.generic')})
  }
  if (error instanceof TypeError) return t('errors.network')
  return t('errors.generic')
}
