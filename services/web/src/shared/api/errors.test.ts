import {describe, expect, it} from 'vitest'

import {i18n} from '@/shared/i18n'

import {ApiError, describeError, unwrap} from './errors'

const failed = (status: number, error: unknown, statusText = '') =>
  Promise.resolve({error, response: new Response(null, {status, statusText})})

describe('unwrap', () => {
  it('returns the data of a successful call', async () => {
    await expect(unwrap(Promise.resolve({data: [1], response: new Response(null, {status: 200})}))).resolves.toEqual([
      1,
    ])
  })

  it('takes the code from a problem+json body', async () => {
    const error = await unwrap(failed(409, {code: 'stale_version', detail: 'changed'})).catch((e: unknown) => e)

    expect(error).toEqual(new ApiError(409, 'stale_version', 'changed'))
    expect(error).toMatchObject({status: 409, code: 'stale_version'})
  })

  it('names a failure without a problem body by its status', async () => {
    const error = await unwrap(failed(502, '<html>Bad gateway</html>', 'Bad Gateway')).catch((e: unknown) => e)

    expect(error).toMatchObject({status: 502, code: 'http_error', message: 'Bad Gateway'})
  })
})

describe('describeError', () => {
  it.each([
    [new ApiError(409, 'stale_version', ''), i18n.t('errors.stale_version')],
    [new ApiError(400, 'something_new', ''), 'Something went wrong. Try again.'],
    [new TypeError('Failed to fetch'), 'The server cannot be reached. Check the connection and try again.'],
    [new Error('boom'), 'Something went wrong. Try again.'],
  ])('describes %s', (error, expected) => {
    expect(describeError(error, i18n.t)).toBe(expected)
  })
})
