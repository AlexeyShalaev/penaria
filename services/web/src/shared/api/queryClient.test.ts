import {describe, expect, it} from 'vitest'

import {ApiError} from './errors'
import {createQueryClient} from './queryClient'

const retry = createQueryClient().getDefaultOptions().queries?.retry as (failures: number, error: Error) => boolean

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
})
