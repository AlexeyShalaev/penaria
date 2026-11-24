import {describe, expect, it, vi} from 'vitest'

import {ApiError} from './errors'
import {createQueryClient} from './queryClient'

const retry = createQueryClient({onUnauthenticated: () => {}}).getDefaultOptions().queries?.retry as (
  failures: number,
  error: Error,
) => boolean

const reject = (error: Error) => () => Promise.reject(error)

describe('createQueryClient', () => {
  it.each([
    ['a 404', 0, new ApiError(404, 'entity_not_found', ''), false],
    ['a 500, the first time', 0, new ApiError(500, 'internal_error', ''), true],
    ['a 500, the second time', 1, new ApiError(500, 'internal_error', ''), true],
    ['a 500, the third time', 2, new ApiError(500, 'internal_error', ''), false],
    ['a network failure', 0, new TypeError('Failed to fetch'), true],
  ])('retries %s: %s', (_, failures, error, expected) => {
    expect(retry(failures, error)).toBe(expected)
  })

  it('signs out when a query finds the session gone', async () => {
    const onUnauthenticated = vi.fn()
    const client = createQueryClient({onUnauthenticated})

    await client
      .fetchQuery({queryKey: ['homes'], queryFn: reject(new ApiError(401, 'unauthenticated', '')), retry: false})
      .catch(() => {})

    expect(onUnauthenticated).toHaveBeenCalledWith(client)
  })

  it('signs out when a change finds the session gone', async () => {
    const onUnauthenticated = vi.fn()
    const client = createQueryClient({onUnauthenticated})

    await client
      .getMutationCache()
      .build(client, {mutationFn: reject(new ApiError(401, 'unauthenticated', ''))})
      .execute(undefined)
      .catch(() => {})

    expect(onUnauthenticated).toHaveBeenCalledWith(client)
  })

  it('stays signed in after other failures', async () => {
    const onUnauthenticated = vi.fn()
    const client = createQueryClient({onUnauthenticated})

    await client
      .fetchQuery({queryKey: ['homes'], queryFn: reject(new ApiError(401, 'invalid_credentials', '')), retry: false})
      .catch(() => {})

    expect(onUnauthenticated).not.toHaveBeenCalled()
  })
})
